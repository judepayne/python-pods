import edn_format


def transform_dict(d):
    if isinstance(d, edn_format.immutable_dict.ImmutableDict):
        result = {}
        for k, v in d.items():
            # Handle different key types
            if hasattr(k, 'name'):  # Keyword or Symbol
                key = k.name
            else:  # Regular string or other type
                key = k
            result[key] = transform_dict(v)
        return result
    elif isinstance(d, (list, edn_format.immutable_list.ImmutableList)):
        return [transform_dict(item) for item in d]
    elif isinstance(d, edn_format.edn_lex.Symbol):
        return d.name
    elif isinstance(d, edn_format.edn_lex.Keyword):
        return d.name
    else:
        return d

def from_edn(s):
    res = transform_dict(edn_format.loads(s))
    return res

def to_edn(d):
    return edn_format.dumps(d)


class Edn:
    """EDN serialization/deserialization class with read and write methods."""
    
    def __init__(self, readers=None):
        """Initialize Edn with optional edn readers.
        
        Args:
            readers (dict, optional): Dictionary of edn readers, where each
            reader is a dict item of tag -> string representation of function/class
        """
        self.readers = readers or {}
        self.compiled_readers = {}

        # Process and compile reader functions/classes
        for tag, reader_code in self.readers.items():
            reader_fn = self._compile_reader(tag, reader_code)
            if reader_fn:
                self.compiled_readers[tag] = reader_fn
                edn_format.add_tag(tag, reader_fn)
    
    def _compile_reader(self, tag, reader_code):
        """Compile a reader function from string code"""
        try:
            # Create a clean namespace
            namespace = {'__builtins__': __builtins__}
            
            # Execute the code
            exec(reader_code, namespace)
            
            # Strategy 1: Look for a function/class with the same name as tag
            if tag in namespace and callable(namespace[tag]):
                return namespace[tag]
            
            # Strategy 2: Look for functions with common reader names
            common_names = [f"{tag}_reader", f"read_{tag}", "reader", "read"]
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
           
    def read(self, s):
        return from_edn(s)

    def add_read_handler(self, tag, handler_fn):
        """Add a custom EDN read handler for a specific tag"""
        if not callable(handler_fn):
            raise ValueError(f"Read handler must be callable: {handler_fn}")
        
        # Add to our readers dict
        self.readers[tag] = handler_fn
        
        # Recompile readers to update the EDN parser
        self._compile_readers()

    def add_write_handler(self, type_class, writer_fn):
        """Add a custom EDN write handler for a Python type"""
        if not callable(writer_fn):
            raise ValueError(f"Write handler must be callable: {writer_fn}")
        
        # Initialize write handlers if not exists
        if not hasattr(self, 'write_handlers'):
            self.write_handlers = {}
        
        self.write_handlers[type_class] = writer_fn

    def write(self, obj):
        """Write Python object to EDN string with custom write handlers"""
        return self._to_edn_with_handlers(obj)
    
    def _escape_edn_string(self, s):
        """Properly escape a string for EDN format"""
        # Basic escaping - may need more comprehensive escaping
        escaped = s.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'    

    def _to_edn_with_handlers(self, obj):
        """Convert Python object to EDN string using registered write handlers"""
        # Check if we have a custom write handler for this object's type
        if hasattr(self, 'write_handlers'):
            for type_class, writer_fn in self.write_handlers.items():
                if isinstance(obj, type_class):
                    # Apply the write handler
                    transformed = writer_fn(obj)
                    # Recursively process the transformed data
                    return self._to_edn_with_handlers(transformed)
        
        # Handle basic types
        if obj is None:
            return "nil"
        elif isinstance(obj, bool):
            return "true" if obj else "false"
        elif isinstance(obj, int):
            return str(obj)
        elif isinstance(obj, float):
            return str(obj)
        elif isinstance(obj, str):
            return self._escape_edn_string(obj)
        elif isinstance(obj, list):
            items = [self._to_edn_with_handlers(item) for item in obj]
            return f"[{' '.join(items)}]"
        elif isinstance(obj, tuple):
            items = [self._to_edn_with_handlers(item) for item in obj]
            return f"[{' '.join(items)}]"
        elif isinstance(obj, dict):
            pairs = []
            for k, v in obj.items():
                key_edn = self._to_edn_with_handlers(k)
                val_edn = self._to_edn_with_handlers(v)
                pairs.append(f"{key_edn} {val_edn}")
            return f"{{{' '.join(pairs)}}}"
        elif isinstance(obj, set):
            items = [self._to_edn_with_handlers(item) for item in obj]
            return f"#{{{' '.join(items)}}}"
        else:
            # Fallback - convert to string representation
            return f'"{str(obj)}"'