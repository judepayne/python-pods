from transit.writer import Writer
from transit.reader import Reader
from io import StringIO
import transit.transit_types
from datetime import datetime
import uuid
import sys

def transform(d):
    """Converts immutable frozendict to python dict"""
    if isinstance(d, transit.transit_types.frozendict):
        return {k: transform(v) for k, v in d.items()}
    elif isinstance(d, tuple):
        return [transform(item) for item in d]  # Transform each element
    elif isinstance(d, list):
        return [transform(item) for item in d]  # Transform each element
    elif isinstance(d, transit.transit_types.Boolean):
        return bool(d)
    elif isinstance(d, dict):
        return {k: transform(v) for k, v in d.items()}
    else:
        return d

# Metadata handling
class WithMeta:
    def __init__(self, value, meta=None):
        self.value = value
        self.meta = meta or {}
    
    def __repr__(self):
        return f"WithMeta({self.value}, meta={self.meta})"

class MetadataWriteHandler:
    @staticmethod
    def tag(obj):
        return "with-meta"  # Official transit metadata tag
    
    @staticmethod  
    def rep(obj):
        # Return [value, metadata_map] structure (same as Clojure)
        return [obj.value, obj.meta]
    
    @staticmethod
    def string_rep(obj):
        return str([obj.value, obj.meta])
    
class MetadataReadHandler:
    @staticmethod
    def from_rep(data):
        # Check for tuple OR list with exactly 2 elements
        if (isinstance(data, (list, tuple)) and len(data) == 2):
            value, meta = data
            # Convert frozendict to regular dict if needed
            if hasattr(meta, 'items'):  # frozendict or dict
                meta = dict(meta)
            result = WithMeta(transform(value), meta)
            return result
        return data

# Common built-in handler classes
class UuidReadHandler:
    @staticmethod
    def from_rep(rep):
        """Read UUID from string representation"""
        return uuid.UUID(rep)

class DateTimeReadHandler:
    @staticmethod
    def from_rep(rep):
        """Read datetime from ISO string"""
        if isinstance(rep, str):
            return datetime.fromisoformat(rep)
        return rep

class UuidWriteHandler:
    @staticmethod
    def tag(obj):
        return "u"
    
    @staticmethod
    def rep(obj):
        return str(obj)
    
    @staticmethod
    def string_rep(obj):
        return str(obj)

class DateTimeWriteHandler:
    @staticmethod
    def tag(obj):
        return "local-date-time"  # Match pod's handler tag
    
    @staticmethod
    def rep(obj):
        # Convert to ISO string format that Java LocalDateTime can parse
        return obj.replace(tzinfo=None).isoformat()
    
    @staticmethod
    def string_rep(obj):
        return obj.replace(tzinfo=None).isoformat()

def _compile_reader(tag, reader_code):
    """Compile a reader function from string code"""
    try:
        namespace = {'__builtins__': __builtins__}
        exec(reader_code, namespace)
        
        # Strategy 1: Look for a function/class with the same name as tag
        if tag in namespace and callable(namespace[tag]):
            return namespace[tag]
        
        # Strategy 2: Look for functions with common reader names
        common_names = [f"{tag}_reader", f"read_{tag}", "reader", "read", "from_rep"]
        for name in common_names:
            if name in namespace and callable(namespace[name]):
                return namespace[name]
        
        # Strategy 3: Find the first non-builtin callable
        for name, obj in namespace.items():
            if (not name.startswith('_') and 
                callable(obj) and 
                obj not in namespace['__builtins__'].values()):
                return obj
        
        print(f"⚠️  No suitable callable found for tag '{tag}'")
        return None
        
    except Exception as e:
        print(f"❌ Error compiling reader for tag '{tag}': {e}")
        return None

def _compile_writer_handler(tag, writer_code):
    """Compile a writer handler class from string code"""
    try:
        namespace = {'__builtins__': __builtins__}
        exec(writer_code, namespace)
        
        # Look for a class that has tag() and rep() methods
        for name, obj in namespace.items():
            if (not name.startswith('_') and 
                hasattr(obj, 'tag') and hasattr(obj, 'rep')):
                return obj
        
        # If no handler class found, create one from functions
        tag_fn = None
        rep_fn = None
        
        # Look for tag and rep functions
        for name, obj in namespace.items():
            if not name.startswith('_') and callable(obj):
                if 'tag' in name.lower():
                    tag_fn = obj
                elif 'rep' in name.lower():
                    rep_fn = obj
        
        if tag_fn and rep_fn:
            # Create a dynamic handler class
            class DynamicWriteHandler:
                @staticmethod
                def tag(obj):
                    return tag_fn(obj)
                
                @staticmethod
                def rep(obj):
                    return rep_fn(obj)
                
                @staticmethod
                def string_rep(obj):
                    return str(rep_fn(obj))
            
            return DynamicWriteHandler
        
        print(f"⚠️  No suitable write handler found for tag '{tag}'")
        return None
        
    except Exception as e:
        print(f"❌ Error compiling write handler for tag '{tag}': {e}")
        return None

class Transit:
    """Transit serialization/deserialization class with read and write methods."""
    
    def __init__(self, pod_readers=None, pod_writers=None):
        """Initialize Transit with optional pod readers and writers.
        
        Args:
            pod_readers (dict, optional): Dictionary of pod readers, where each
                reader is a dict item of tag -> string representation of function/class
            pod_writers (dict, optional): Dictionary of pod writers  
        """
        self.pod_readers = pod_readers or {}
        self.pod_writers = pod_writers or {}
        
        # Dynamic handler storage
        self.read_handlers = {}
        self.write_handlers = {}
        self.default_write_handler = None
        
        # Built-in handlers - always available
        self.builtin_read_handlers = {
            "u": UuidReadHandler,
            "local-date-time": DateTimeReadHandler,
            "with-meta": MetadataReadHandler,
        }
        
        self.builtin_write_handlers = {
            uuid.UUID: UuidWriteHandler,
            datetime: DateTimeWriteHandler,
            WithMeta: MetadataWriteHandler,
        }
        
        # Process pod readers and writers from pod description
        self._process_pod_readers()
        self._process_pod_writers()
    
    def _process_pod_readers(self):
        """Process and compile reader functions/classes from pod readers"""
        for tag, reader_code in self.pod_readers.items():
            if isinstance(reader_code, str):
                reader_fn = _compile_reader(tag, reader_code)
                if reader_fn:
                    # Wrap function in a handler class
                    class CompiledReadHandler:
                        @staticmethod
                        def from_rep(rep):
                            return reader_fn(rep)
                    self.read_handlers[tag] = CompiledReadHandler
            elif hasattr(reader_code, 'from_rep'):
                # Already a handler class
                self.read_handlers[tag] = reader_code
            elif callable(reader_code):
                # Function - wrap in handler class
                class FunctionReadHandler:
                    @staticmethod
                    def from_rep(rep):
                        return reader_code(rep)
                self.read_handlers[tag] = FunctionReadHandler
    
    def _process_pod_writers(self):
        """Process pod writers from pod description"""
        for type_class, writer_spec in self.pod_writers.items():
            if isinstance(writer_spec, str):
                # Compile handler class from string code
                handler_class = _compile_writer_handler(type_class.__name__, writer_spec)
                if handler_class:
                    self.write_handlers[type_class] = handler_class
            elif hasattr(writer_spec, 'tag') and hasattr(writer_spec, 'rep'):
                # Already a handler class
                self.write_handlers[type_class] = writer_spec
            elif isinstance(writer_spec, tuple) and len(writer_spec) == 2:
                # (tag, function) tuple - create handler class
                tag, writer_fn = writer_spec
                
                class SimpleWriteHandler:
                    @staticmethod
                    def tag(obj):
                        return tag
                    
                    @staticmethod
                    def rep(obj):
                        return writer_fn(obj)
                    
                    @staticmethod
                    def string_rep(obj):
                        return str(writer_fn(obj))
                
                self.write_handlers[type_class] = SimpleWriteHandler
    
    def add_read_handler(self, tag, handler_class):
        """Add a transit read handler class for a specific tag"""
        if not hasattr(handler_class, 'from_rep'):
            raise ValueError(f"Read handler must have a 'from_rep' method: {handler_class}")
        
        self.read_handlers[tag] = handler_class

    def add_write_handler(self, classes, handler_class):
        """Add a transit write handler class for specific classes"""
        if not (hasattr(handler_class, 'tag') and hasattr(handler_class, 'rep')):
            raise ValueError(f"Write handler must have 'tag' and 'rep' methods: {handler_class}")
        
        # Handle both single class and list of classes
        if not isinstance(classes, (list, tuple)):
            classes = [classes]
        
        for cls in classes:
            self.write_handlers[cls] = handler_class

    def set_default_write_handler(self, handler_class):
        """Set a default transit write handler class for unregistered types"""
        if not (hasattr(handler_class, 'tag') and hasattr(handler_class, 'rep')):
            raise ValueError(f"Default write handler must have 'tag' and 'rep' methods: {handler_class}")
        
        self.default_write_handler = handler_class
    
    def _get_combined_read_handlers(self):
        """Get combined read handlers (builtin + pod + dynamic)"""
        combined = {}
        combined.update(self.builtin_read_handlers)
        combined.update(self.read_handlers)
        print(f"🔍 DEBUG: builtin_read_handlers: {self.builtin_read_handlers}")
        print(f"🔍 DEBUG: read_handlers: {self.read_handlers}")
        print(f"🔍 DEBUG: combined: {combined}")
        return combined
    
    def _get_combined_write_handlers(self):
        """Get combined write handlers (builtin + pod + dynamic)"""
        combined = {}
        combined.update(self.builtin_write_handlers)
        combined.update(self.write_handlers)
        return combined
    
    def read(self, s):
        """Read transit+json string and return Python data"""
        try:
            reader = Reader("json")
            
            # Register builtin handler classes
            reader.register("u", UuidReadHandler)
            reader.register("local-date-time", DateTimeReadHandler) 
            reader.register("with-meta", MetadataReadHandler)
            
            # Register dynamic read handlers (all should be classes now)
            for tag, handler_class in self.read_handlers.items():
                reader.register(tag, handler_class)
            
            result = reader.read(StringIO(s))
            return transform(result)
        except Exception as e:
            print(f"Transit read error: {e}", file=sys.stderr)
            raise
    
    def write(self, data):
        """Write Python data as transit+json string"""
        try:
            io_object = StringIO()
            writer = Writer(io_object, "json")
            
            # Register all write handlers
            write_handlers = self._get_combined_write_handlers()
            for type_class, handler_class in write_handlers.items():
                writer.register(type_class, handler_class)
            
            # Set default handler if available
            if self.default_write_handler:
                writer.set_default_handler(self.default_write_handler)
            
            writer.write(data)
            return io_object.getvalue()
        except Exception as e:
            print(f"Transit write error: {e}", file=sys.stderr)
            raise
