# Python Pods

A faithful port of the babashka pods library to python.

Python Pods provides a way to invoke functionality from other programs (pods) and expose functionality to other programs. Pods are programs that implement the pod protocol, which is a simple bencode-based protocol for inter-process communication.

## Features

- Load and communicate with pods using EDN, JSON, or Transit+JSON formats
- Automatic pod downloading from the babashka pod registry
- Pod functionality patching system via pyproject.toml configuration
- Expose pod namespaces as importable Python modules
- Support for custom EDN readers and Transit transforms
- Metadata preservation with Transit+JSON format
- Dynamic registration of custom Transit read/write handlers
- Automatic type conversion between Python and pod data types
- Thread-safe communication with pods

## Installation

This project uses [uv](https://astral.sh/uv) as the Python package manager for fast and reliable dependency management.

```bash
# Install uv first (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/your-username/python-pods
cd python-pods

# Install dependencies and activate environment
uv sync
source .venv/bin/activate

# Run tests
./run_test.sh
```

For development workflows, uv automatically manages virtual environments and provides 10-100x faster dependency resolution compared to pip.

## Quick Start

```python
import python_pods as pods

# Load a pod from the babashka registry
pod = pods.load_pod('org.babashka/instaparse', {'version': '0.0.6'})

# Import the pod namespace as a Python module
import pod_babashka_instaparse as insta

# Use functions from the pod
parser = insta.parser("S = AB* AB = A B A = 'a'+ B = 'b'+")
result = insta.parse(parser, "aaaaabbbaaaabb")
print(result)
```

For a complete working example with result processing, see `test/test_instaparse.py` which demonstrates how to work with complex pod results including `WithMeta` objects and transit keywords.

## Pod Registry Support

Python Pods integrates with the [babashka pod registry](https://github.com/babashka/pod-registry) to automatically download and cache pods.

### Loading Pods from Registry

```python
# Load a specific version from the registry
pod = pods.load_pod('org.babashka/instaparse', {'version': '0.0.6'})

# Load the latest version (if available)
pod = pods.load_pod('org.babashka/postgresql', {'version': '0.5.0'})
```

### Registry Features

- **Automatic downloading**: Pods are downloaded on first use and cached locally
- **Version management**: Specify exact versions for reproducible builds
- **Multi-platform support**: Automatically selects the correct binary for your OS/architecture
- **Checksum verification**: Downloads are verified against SHA-256 checksums
- **Caching**: Downloaded pods are cached in `~/.babashka/pods/repository/`

### Cache Management

Pod cache location can be controlled via environment variables:

```bash
# Custom cache location
export BABASHKA_PODS_DIR="/custom/path/to/pods"

# Use XDG standard directories
export XDG_CACHE_HOME="/custom/cache"
```

The resolver automatically handles platform detection and will fall back to compatible architectures when needed (e.g., x86_64 binaries on Apple Silicon with Rosetta).

## Patch System

Python Pods includes a powerful patching system that allows you to modify pod behavior through `pyproject.toml` configuration. This enables you to add custom functionality, fix compatibility issues, or enhance pod functions without modifying the original pod code.

### Configuring Patches

Add patches to your `pyproject.toml` file:

```toml
[[tool.python-pods.patches]]
pod = "org.babashka/instaparse"

# EDN reader patches for custom data type handling
[tool.python-pods.patches.readers]
"person" = """
def read_person(data):
    return {
        'type': 'Person',
        'name': data['name'],
        'age': data['age'],
        'description': f"{data['name']} is {data['age']} years old"
    }
"""

# Function patches to modify or enhance pod functions
[tool.python-pods.patches.functions]
"pod.babashka.instaparse/parse" = """
def parse(parser, text, options=None):
    # Get the original result from the pod
    original_result = original_parse_function(parser, text, options)
    
    # Apply custom post-processing
    def convert_parse_tree(node):
        if hasattr(node, 'value') and hasattr(node, 'meta'):
            # Convert WithMeta objects to Python dicts
            value = node.value
            if isinstance(value, list) and len(value) > 0:
                tag = str(value[0]).replace('<Keyword ', '').replace(' >', '')
                children = [convert_parse_tree(child) for child in value[1:]]
                return {
                    'tag': tag,
                    'content': children
                }
        elif isinstance(node, list):
            return [convert_parse_tree(child) for child in node]
        return node
    
    return convert_parse_tree(original_result)
"""
```

### Patch Types

1. **Reader Patches**: Modify how EDN or Transit data is parsed
   - Useful for handling custom data types from pods
   - Applied during the deserialization phase

2. **Function Patches**: Replace or enhance pod function behavior
   - Access to original function results via `original_*_function`
   - Can modify inputs, outputs, or add completely new functionality
   - Applied when pod functions are invoked

### Patch Priority

Patches always take precedence over pod-provided functionality:
1. **Function patches** override any code returned by the pod
2. **Reader patches** override pod-provided EDN readers
3. **Original functionality** is still accessible within patches

This system is particularly useful for:
- Converting complex pod results to Python-friendly formats
- Adding type safety and validation
- Implementing missing functionality
- Working around pod compatibility issues

## Key Design Choices

### Exposing Pod Namespaces as Python Modules

One of the major design decisions in this library is automatically exposing pod namespaces as importable Python modules. When you load a pod:

1. Each pod namespace becomes a Python module (e.g., `pod.test-pod` → `pod_test_pod`)
2. Pod functions become callable Python functions with proper `__doc__` and metadata
3. Both kebab-case and snake_case naming conventions are supported
4. Modules are registered in `sys.modules` for standard Python imports

```python
# After loading a pod, you can import and use it like any Python module
import pod_test_pod as test_pod

# Functions retain their original names and get snake_case aliases
result1 = test_pod.deep_merge(dict1, dict2)  # kebab-case original
result2 = test_pod.deep_merge(dict1, dict2)  # same function, different style
```

### Deferred Namespace Loading

For pods with multiple namespaces, the library supports deferred loading to improve startup performance:

```python
# List available deferred namespaces
pods.list_deferred_namespaces(pod_id)

# Load a deferred namespace on demand
pods.load_and_expose_namespace(pod_id, "pod.example.deferred-ns")
```

## Data Formats

### JSON Support

The library supports standard JSON format for basic data interchange:

```python
# Load a pod with JSON format (default for many pods)
pod = pods.load_pod(["json-pod"])

# JSON automatically handles basic Python types
data = {
    "numbers": [1, 2, 3],
    "text": "hello",
    "boolean": True,
    "nested": {"key": "value"}
}

result = test_pod.process_data(data)
```

JSON format provides the most basic compatibility and works well for simple data structures. However, it has limitations:
- No support for custom types beyond basic JSON types
- No metadata preservation
- Limited type fidelity (e.g., no distinction between integers and floats in some cases)

For more advanced features like custom types and metadata, consider using Transit+JSON format.

### EDN Support

The library supports EDN format with custom readers. To enable custom EDN readers:

```python
# Load pod with custom reader resolution
pod = pods.load_pod(["clojure", "-M:test-pod"], {"resolve": True})

# EDN with custom tags will be automatically converted
# Example: #person {:name "Alice" :age 30} becomes a Python dict with custom structure
```

Custom EDN readers in pods should follow the standard EDN reader format. The `resolve` option must be set to `True` in `load_pod()` for custom readers to be processed.

#### Dynamic EDN Handler Registration

You can register custom EDN handlers at runtime:

```python
from edn import TaggedLiteral

# Define a custom type
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age

# Define read handler
def read_person(data):
    return Person(data['name'], data['age'])

# Define write handler that creates tagged EDN
def write_person(person):
    return TaggedLiteral('myapp/person', {'name': person.name, 'age': person.age})

# Register handlers (must be called within pod context)
pods.add_edn_read_handler('myapp/person', read_person)
pods.add_edn_write_handler(Person, write_person)

# Now Person objects work seamlessly with EDN pods
person = Person("Alice", 30)
result = test_pod.echo(person)  # Preserves Person type

# The write handler creates: #myapp/person {:name "Alice", :age 30}
# The pod parses it, and our read handler converts it back to Person
```

### Transit+JSON Support

For Transit+JSON format, the library uses the `transit-python2` library and supports custom read and write transforms:

```python
# Load a pod with Transit+JSON format
pod = pods.load_pod(["clojure", "-M:test-pod", "--transit+json"])

# Custom transforms automatically handle special types
from datetime import datetime
import uuid

# These types are automatically serialized/deserialized
test_datetime = datetime.now()
test_uuid = uuid.uuid4()

# Round-trip through the pod
result_datetime = test_pod.echo(test_datetime)
result_uuid = test_pod.echo(test_uuid)
```

#### Built-in Transit Support

The library automatically handles these common types with Transit:

- **DateTime objects**: Serialized with tag `"local-date-time"` compatible with Java `LocalDateTime`
- **UUID objects**: Serialized with tag `"u"` using standard Transit UUID format
- **Metadata**: Special support for preserving metadata on data structures (see below)

#### Metadata Support with Transit+JSON

Python Pods supports rich metadata preservation using the official Transit `"with-meta"` tag:

```python
from transit2 import WithMeta

# Create data with metadata
data = [1, 2, 3, 4, 5]
metadata = {"source": "user-input", "timestamp": "2024-01-01", "version": 1}
wrapped_data = WithMeta(data, metadata)

# Send to pod function that preserves metadata
result = test_pod.echo_meta(wrapped_data)

# Check if metadata was preserved
if hasattr(result, 'value') and hasattr(result, 'meta'):
    print(f"Data: {result.value}")
    print(f"Metadata: {result.meta}")
else:
    print("Metadata was not preserved by this pod function")
```

**Note**: Metadata preservation depends on the pod function being designed to handle metadata. Functions with `arg-meta` set to `true` in their pod definition will receive and can return `WithMeta` objects.

#### Working with Complex Transit Results

When working with pods that return complex transit data structures (like parse trees), you may need to post-process the results to make them more Python-friendly. See `test/test_instaparse.py` for a complete example of handling `WithMeta` objects and transit keywords:

```python
def unwrap_withmeta(node):
    """Recursively unwrap WithMeta objects and convert keywords to strings"""
    if hasattr(node, 'value'):
        return unwrap_withmeta(node.value)
    elif isinstance(node, list):
        return [unwrap_withmeta(item) for item in node]
    elif str(type(node)) == "<class 'transit.transit_types.Keyword'>":
        keyword_str = str(node)
        if ' ' in keyword_str:
            name = keyword_str.split(' ')[1].rstrip(' >')
            if '/' in name:
                return name.split('/')[-1]
            return name
        return keyword_str
    else:
        return node

# Convert complex pod results to clean Python data
cleaned_result = unwrap_withmeta(raw_pod_result)
```

#### Dynamic Transit Handler Registration

You can register custom Transit handlers at runtime:

```python
# Define custom read handler
class PersonReadHandler:
    @staticmethod
    def from_rep(rep):
        return Person(name=rep["name"], age=rep["age"])

# Define custom write handler  
class PersonWriteHandler:
    @staticmethod
    def tag(obj):
        return "person"
    
    @staticmethod
    def rep(obj):
        return {"name": obj.name, "age": obj.age}

# Register handlers (must be called within pod context)
pods.add_transit_read_handler("person", PersonReadHandler)
pods.add_transit_write_handler([Person], PersonWriteHandler)

# Now Person objects will be automatically serialized/deserialized
person = Person("Alice", 30)
result = test_pod.echo(person)  # Preserves Person type
```

## API Reference

### Core Functions

#### `load_pod(pod_spec, opts=None)`

Load and start a pod process.

**Parameters:**
- `pod_spec`: Command to run the pod (string or list of strings), or registry pod identifier (e.g., 'org.babashka/instaparse')
- `opts`: Optional configuration dict
  - `"version"`: Version to download from registry (required for registry pods)
  - `"resolve"`: Enable custom EDN readers (default: False)
  - `"transport"`: Use "socket" for socket transport (default: stdio)
  - `"force"`: Force re-download from registry (default: False)

**Returns:** Pod object

**Examples:**
```python
# Load from registry
pod = pods.load_pod('org.babashka/instaparse', {'version': '0.0.6'})

# Load local pod
pod = pods.load_pod(["clojure", "-M:test-pod"])

# Load with socket transport
pod = pods.load_pod(["my-pod"], {"transport": "socket"})
```

#### `invoke_public(pod_id, function_symbol, args, opts=None)`

Directly invoke a pod function without using module imports.

#### `unload_pod(pod_id)`

Shutdown and cleanup a pod.

### Module Management

#### `list_pod_modules()`

List all currently registered pod modules.

#### `list_deferred_namespaces(pod_id=None)`

List deferred namespaces for a pod.

#### `load_and_expose_namespace(pod_id, namespace_name)`

Load a deferred namespace and expose it as a module.

### Declarative Pod Configuration

Python Pods supports declarative pod configuration through `pyproject.toml`, similar to how babashka uses `bb.edn`. This allows you to specify which pods your project uses in a configuration file, making it easy to manage dependencies and ensure consistent pod versions across environments.

#### Configuration Format

Add a `[tool.python-pods]` section to your `pyproject.toml`:

```toml
[tool.python-pods]
pods = [
    # Pod from registry with version
    { name = "org.babashka/hsqldb", version = "0.1.0" },
    
    # Local pod with path
    { name = "my.local/pod", path = "../pod-my-local/my-pod-binary", cache = false },
    
    # Pod with additional options
    { name = "pod.example/advanced", version = "2.0.0", opts = { transport = "socket" } }
]
```

#### Loading Pods from Configuration

Use the `load_pods_from_pyproject()` function to load pods:

```python
import python_pods as pods

# Load all pods declared in pyproject.toml
all_pods = pods.load_pods_from_pyproject()

# Load only specific pods
selected_pods = pods.load_pods_from_pyproject("org.babashka/hsqldb", "my.local/pod")

# Use a different configuration file
custom_pods = pods.load_pods_from_pyproject(config_file="./config/pyproject.toml")

# After loading, the pods are automatically available as modules
import pod_babashka_hsqldb as hsqldb
result = hsqldb.execute("SELECT * FROM users")
```

#### Configuration Options

Each pod specification supports the following fields:

- `name` (required): The pod identifier (e.g., "org.babashka/hsqldb")
- `version` (optional): Version to download from the pod registry
- `path` (optional): Path to a local pod executable
- `cache` (optional): Whether to cache pod metadata (default: true)
- `opts` (optional): Additional options passed to `load_pod()`

**Note**: You must specify either `version` (for registry pods) or `path` (for local pods), but not both.

#### Requirements

- Python 3.11+ includes `tomllib` for reading TOML files
- For Python < 3.11, install `tomli`: `pip install tomli`

#### Example Project Setup

1. Create a `pyproject.toml` with your pod dependencies:

```toml
[project]
name = "my-data-project"
version = "0.1.0"

[tool.python-pods]
pods = [
    { name = "org.babashka/hsqldb", version = "0.1.0" },
    { name = "org.babashka/postgresql", version = "0.5.0" }
]
```

2. In your Python code:

```python
import python_pods as pods

# Load all configured pods at startup
pods.load_pods_from_pyproject()

# Now use them anywhere in your project
import pod_babashka_hsqldb as hsqldb
import pod_babashka_postgresql as pg

# Your database operations...
```

This approach ensures all team members and deployment environments use the same pod versions, similar to how `requirements.txt` or `poetry.lock` work for Python dependencies.

### EDN Handler Registration

These functions must be called within a pod context (after loading an EDN pod):

#### `add_edn_read_handler(tag, handler_fn)`

Register a custom EDN read handler for deserializing tagged values from pods.

**Parameters:**
- `tag` (str): The EDN tag to handle (e.g., 'inst', 'uuid', 'myapp/person')
- `handler_fn`: Function that takes the tagged value and returns Python object

**Example:**
```python
def read_person(data):
    return Person(data['name'], data['age'])

pods.add_edn_read_handler('myapp/person', read_person)
```

#### `add_edn_write_handler(type_class, writer_fn)`

Register a custom EDN write handler for serializing Python objects to pods.

**Parameters:**
- `type_class`: The Python class to handle
- `writer_fn`: Function that takes the object and returns EDN-serializable data

**Example:**
```python
def write_person(person):
    return {'name': person.name, 'age': person.age}

pods.add_edn_write_handler(Person, write_person)
```

### Socket Transport

By default, pods communicate via standard input/output (stdio). You can also use socket transport for better performance and isolation:

```python
# Use socket transport instead of stdio
pod = pods.load_pod(["clojure", "-M:some-pod"], {"transport": "socket"})

# Everything else works the same way
result = pod_namespace.some_function(args)
```

Socket transport is particularly useful for:
- **Long-running pods** - Better resource isolation
- **High-throughput scenarios** - Reduced overhead compared to stdio
- **Concurrent pod usage** - Multiple pods can run independently

The pod automatically creates a temporary port file and establishes the socket connection. No additional configuration is required.

### Transit Handler Registration

These functions must be called within a pod context (after loading a Transit+JSON pod):

#### `add_transit_read_handler(tag, handler_class)`

Register a custom Transit read handler for deserializing tagged values from pods.

**Parameters:**
- `tag` (str): The Transit tag to handle
- `handler_class`: A class with a static `from_rep` method

**Example:**
```python
class MyTypeReadHandler:
    @staticmethod
    def from_rep(rep):
        return MyType(rep)

pods.add_transit_read_handler("my-type", MyTypeReadHandler)
```

#### `add_transit_write_handler(classes, handler_class)`

Register a custom Transit write handler for serializing Python objects to pods.

**Parameters:**
- `classes`: A class or list of classes to handle
- `handler_class`: A class with static `tag` and `rep` methods

**Example:**
```python
class MyTypeWriteHandler:
    @staticmethod
    def tag(obj):
        return "my-type"
    
    @staticmethod
    def rep(obj):
        return obj.serialize()

pods.add_transit_write_handler([MyType], MyTypeWriteHandler)
```

#### `set_default_transit_write_handler(handler_class)`

Set a default Transit write handler for unregistered types.

**Parameters:**
- `handler_class`: A class with static `tag` and `rep` methods

**Example:**
```python
class DefaultWriteHandler:
    @staticmethod
    def tag(obj):
        return type(obj).__name__
    
    @staticmethod
    def rep(obj):
        return str(obj)

pods.set_default_transit_write_handler(DefaultWriteHandler)
```

## Examples

### Basic Usage

```python
import python_pods as pods

# Load a simple pod
pod = pods.load_pod(["echo-pod"])
import pod_echo as echo

result = echo.echo_message("Hello, World!")
print(result)
```

### Working with Registry Pods

```python
import python_pods as pods

# Load the instaparse pod from the registry
pod = pods.load_pod('org.babashka/instaparse', {'version': '0.0.6'})
import pod_babashka_instaparse as insta

# Create a grammar and parse some text
parser = insta.parser("S = AB* AB = A B A = 'a'+ B = 'b'+")
result = insta.parse(parser, "aaaaabbbaaaabb")

# The result contains WithMeta objects and transit keywords
# See test/test_instaparse.py for complete example of processing these results
print("Raw result:", result)

# Post-process to get clean Python data structures
def unwrap_withmeta(node):
    if hasattr(node, 'value'):
        return unwrap_withmeta(node.value)
    elif isinstance(node, list):
        return [unwrap_withmeta(item) for item in node]
    elif str(type(node)) == "<class 'transit.transit_types.Keyword'>":
        keyword_str = str(node)
        if ' ' in keyword_str:
            name = keyword_str.split(' ')[1].rstrip(' >')
            if '/' in name:
                return name.split('/')[-1]
            return name
        return keyword_str
    else:
        return node

clean_result = unwrap_withmeta(result)
print("Cleaned result:", clean_result)
```

### Working with Complex Data

```python
# Load pod with custom EDN readers
pod = pods.load_pod(["data-pod"], {"resolve": True})
import pod_data as data

# Pod functions can handle complex nested data
nested_data = {
    "users": [
        {"name": "Alice", "scores": [95, 87, 92]},
        {"name": "Bob", "scores": [78, 85, 90]}
    ]
}

processed = data.process_user_data(nested_data)
```

### Custom Transit Handlers

```python
# Load a Transit+JSON pod
pod = pods.load_pod(["my-pod", "--transit+json"])

# Define a custom data type
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    
    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

# Define handlers
class PointReadHandler:
    @staticmethod
    def from_rep(rep):
        return Point(rep[0], rep[1])

class PointWriteHandler:
    @staticmethod
    def tag(obj):
        return "point"
    
    @staticmethod
    def rep(obj):
        return [obj.x, obj.y]

# Register handlers
pods.add_transit_read_handler("point", PointReadHandler)
pods.add_transit_write_handler([Point], PointWriteHandler)

# Now Point objects work seamlessly with the pod
import pod_my_pod as my_pod

point = Point(10, 20)
result = my_pod.transform_point(point)  # Returns a Point object
```

### Working with Metadata

```python
from transit2 import WithMeta

# Load a pod that supports metadata
pod = pods.load_pod(["metadata-pod", "--transit+json"])
import pod_metadata_pod as meta_pod

# Create data with metadata
data = {"temperature": 23.5, "humidity": 60}
metadata = {
    "sensor_id": "temp_001", 
    "timestamp": "2024-01-01T10:00:00",
    "unit": "celsius"
}

wrapped_data = WithMeta(data, metadata)

# Send to a metadata-aware pod function
result = meta_pod.process_sensor_data(wrapped_data)

# Check if metadata was preserved and enriched
if hasattr(result, 'meta'):
    print(f"Original metadata: {wrapped_data.meta}")
    print(f"Processed metadata: {result.meta}")
    print(f"Processed data: {result.value}")
```

### Async Operations

```python
# Some pods support async operations through callbacks
def handle_result(result):
    print(f"Received: {result}")

def handle_error(error):
    print(f"Error: {error}")

def handle_done():
    print("Operation completed!")

# Use lower-level invoke for async operations
pods.invoke(
    pod, 
    "pod.async/watch-files", 
    ["/path/to/watch"],
    {"handlers": {"success": handle_result, "error": handle_error, "done": handle_done}}
)
```

## Error Handling

The library raises `PodError` exceptions when pod operations fail:

```python
from python_pods import PodError

try:
    result = test_pod.some_function("invalid_input")
except PodError as e:
    print(f"Pod error: {e}")
    print(f"Error data: {e.data}")
```

## Threading

The library is thread-safe and uses concurrent futures for managing pod communication. Each pod runs in its own process with a dedicated communication thread.

## Development and Testing

The project includes a comprehensive test suite using a local test pod. To run tests:

```bash
# Install dependencies
uv sync

# Run all tests
./run_test.sh

# Or run individual test files
python test/test_instaparse.py
```

The test pod (in `test-pod/`) provides example functions for testing various pod features including metadata handling, async operations, and custom data types.

## Protocol Compatibility

This library implements the babashka pod protocol and is compatible with any program that implements the pod protocol, regardless of the implementation language. The protocol uses:

- Bencode for message framing
- EDN, JSON, or Transit+JSON for payload encoding
- Standard stdin/stdout or socket communication

## License

Copyright © 2024 Jude Payne

Distributed under the MIT License.