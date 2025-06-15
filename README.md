# python-pods

A faithful port of the babashka pods library to python.

![](img/IMG_8734.jpeg)

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/judepayne/python-pods/tree/main.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/judepayne/python-pods/tree/main)

python-pods allow interop with all pods that implement the pod protocol defined by [babashka pods](https://github.com/babashka/pods). You can load and run any pod from the [pod registry](https://github.com/babashka/pod-registry).

python pods has a 'patch system' to override certain behaviour exposed by pods which expect the client to be clojure/ babashka. Details below.


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
pip install python-pods
# or
uv add python-pods
```

## Quick Start

```python
import python_pods as pods

# Load a pod from the pod registry
pod = pods.load_pod('org.babashka/instaparse', {'version': '0.0.6'})

# Import the pod namespace as a Python module
import pod_babashka_instaparse as insta

# Use functions from the pod
parser = insta.parser("S = AB* AB = A B A = 'a'+ B = 'b'+")
result = insta.parse(parser, "aaaaabbbaaaabb")
print(result)
```

For a complete working example with result processing, see `test/test_instaparse.py` which demonstrates how to work with complex pod results including `WithMeta` objects and transit keywords. `WithMeta` is a simple python class that allows you to work with pods that expect or return metadata along with data.

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

Python Pods includes a runtime patching system that allows you to modify pod behavior at runtime without changing pod code. This enables you to transform pod results, override functions, or add custom data type handling.

### Patch Types

**Result Transform Patches** - Transform pod function results after execution:
```python
# Transform complex pod results to Python-friendly formats
def unwrap_withmeta(node):
    # Convert WithMeta objects and transit keywords to clean Python data
    # See test/test_instaparse.py for complete implementation
    pass

pods.register_result_transform_patch(
    pod_id, 
    'pod.babashka.instaparse/parse', 
    unwrap_withmeta
)
```

**Code Patches** - Replace pod functions entirely with Python code:
```python
python_code = """
result = sum(args[0])  # args available in execution context
"""

pods.register_code_patch(pod_id, 'pod.example/sum-list', python_code)
```
(for pods with functions that return clj "code")

**EDN Reader Patches** - Add custom EDN data type handlers:
```python
def read_person(data):
    return Person(data['name'], data['age'])

pods.register_edn_reader_patch(pod_id, 'person', read_person)
```

### Example Usage

See `test/test_instaparse.py` for a complete example where result transform patches automatically clean up complex parse tree results with `WithMeta` objects and transit keywords.

### Patch Management

```python
# List all registered patches
pods.list_patches(pod_id)

# Clear patches for specific pod or all pods
pods.clear_patches(pod_id)  # specific pod
pods.clear_patches()        # all pods
```

Patches are applied in order: result transforms, then code patches (if present), with code patches taking precedence over pod-provided functionality.

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

# Function names are converted to snake case.
result1 = test_pod.deep_merge(dict1, dict2)  # deep-merge was the function in test-pod
```

### Deferred Namespace Loading

For pods with multiple namespaces, the library supports deferred loading to improve startup performance:

```python
# List available deferred namespaces
pods.list_deferred_namespaces(pod_id)

# Load a deferred namespace on demand
pods.load_and_expose_namespace(pod_id, "pod.example.deferred-ns")
```

Note pod_id is obtained from when you load a pod. e.g.

````python
pod = pods.load_pod('org.babashka/instaparse', {'version': '0.0.6'})
pod_id = pod['pod_id'] # 'org.babashka/instaparse'
````

pod_id is used in several of the public api functions which are detailed below.

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
from python_pods import WithMeta

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

**Note**: Metadata preservation depends on the pod function being designed to handle metadata. Functions with `arg-meta` set to `true` in their pod definition can receive (and maybe return) `WithMeta` objects.

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

#### `unload_pod(pod_id_or_pod)`

Shutdown and cleanup a pod.

**Parameters:**
- `pod_id_or_pod`: Pod ID string or pod object

#### `invoke_public(pod_id_or_pod, function_symbol, args, opts=None)`

Directly invoke a pod function without using module imports.

**Parameters:**
- `pod_id_or_pod`: Pod ID string or pod object
- `function_symbol`: Function name (e.g., "pod.namespace/function-name")
- `args`: List of arguments to pass to the function
- `opts`: Optional configuration dict

### Patch System

#### `register_result_transform_patch(pod_id, function_name, transform_function)`

Register a function to transform pod results after execution.

**Parameters:**
- `pod_id`: Pod ID string
- `function_name`: Full function name (e.g., "pod.namespace/function")
- `transform_function`: Function that takes result and returns transformed result

**Example:**
```python
def clean_result(result):
    # Transform complex pod results to Python-friendly format
    return result

pods.register_result_transform_patch(pod_id, 'pod.example/parse', clean_result)
```

#### `register_code_patch(pod_id, function_name, python_code)`

Replace a pod function entirely with Python code.

**Parameters:**
- `pod_id`: Pod ID string
- `function_name`: Full function name (e.g., "pod.namespace/function")
- `python_code`: Python code string (has access to `args` variable)

**Example:**
```python
code = "result = sum(args[0])"
pods.register_code_patch(pod_id, 'pod.example/sum-list', code)
```

#### `register_edn_reader_patch(pod_id, tag, reader_function)`

Register a custom EDN reader for a specific tag.

**Parameters:**
- `pod_id`: Pod ID string
- `tag`: EDN tag string (e.g., "person", "date")
- `reader_function`: Function that takes tagged data and returns Python object

#### `clear_patches(pod_id=None)`

Clear registered patches.

**Parameters:**
- `pod_id`: Pod ID to clear (optional, clears all if None)

#### `list_patches(pod_id=None)`

List all registered patches.

**Parameters:**
- `pod_id`: Pod ID to list (optional, lists all if None)

### Module Management

#### `list_pod_modules()`

List all currently registered pod modules and their functions.

#### `list_deferred_namespaces(pod_id=None)`

List deferred namespaces for a pod or all pods.

**Parameters:**
- `pod_id`: Pod ID string (optional, lists all pods if None)

#### `load_and_expose_namespace(pod_id, namespace_name)`

Load a deferred namespace and expose it as an importable module.

**Parameters:**
- `pod_id`: Pod ID string
- `namespace_name`: Namespace name to load

### Transit Handlers

#### `add_transit_read_handler(pod_id, tag, handler_class)`

Register a custom Transit read handler for a specific tag.

**Parameters:**
- `pod_id`: Pod ID string
- `tag`: Transit tag string
- `handler_class`: Class with static `from_rep` method

**Example:**
```python
class PersonReadHandler:
    @staticmethod
    def from_rep(rep):
        return Person(rep["name"], rep["age"])

pods.add_transit_read_handler(pod_id, "person", PersonReadHandler)
```

#### `add_transit_write_handler(pod_id, classes, handler_class)`

Register a custom Transit write handler for specific classes.

**Parameters:**
- `pod_id`: Pod ID string
- `classes`: Class or list of classes to handle
- `handler_class`: Class with static `tag` and `rep` methods

**Example:**
```python
class PersonWriteHandler:
    @staticmethod
    def tag(obj):
        return "person"
    
    @staticmethod
    def rep(obj):
        return {"name": obj.name, "age": obj.age}

pods.add_transit_write_handler(pod_id, [Person], PersonWriteHandler)
```

#### `set_default_transit_write_handler(pod_id, handler_class)`

Set a default Transit write handler for unregistered types.

**Parameters:**
- `pod_id`: Pod ID string
- `handler_class`: Class with static `tag` and `rep` methods

### Data Types

#### `WithMeta(value, meta=None)`

Container class for data with metadata, used with Transit+JSON format.

**Parameters:**
- `value`: The actual data value
- `meta`: Metadata dictionary (optional)

**Attributes:**
- `value`: The wrapped data
- `meta`: The metadata dictionary

**Example:**
```python
data = [1, 2, 3]
metadata = {"source": "user", "timestamp": "2024-01-01"}
wrapped = pods.WithMeta(data, metadata)

# Send to pod function
result = some_pod_function(wrapped)

# Access result
if hasattr(result, 'meta'):
    print(f"Data: {result.value}")
    print(f"Metadata: {result.meta}")
```

### Exceptions

#### `PodError(message, data=None)`

Exception raised when pod operations fail.

**Attributes:**
- `message`: Error message string
- `data`: Additional error data (dict)

**Example:**
```python
try:
    result = pod_function("invalid_input")
except pods.PodError as e:
    print(f"Pod error: {e}")
    print(f"Error data: {e.data}")
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

Copyright © 2025 Jude Payne

Distributed under the MIT License.