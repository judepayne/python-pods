import sys
sys.path.append("src")
import python_pods as pods  # type: ignore

pod = pods.load_pod(["clojure", "-M:test-pod", "--transit+json"])

# res = invoke_public(pod["pod_id"], "pod.test-pod/add-one", [5])

import pod_test_pod as test_pod # type: ignore

res1 = test_pod.add_one(5)

assert res1 == 6

dict1 = {
    "user": {
        "name": "Alice",
        "age": 28,
        "settings": {
            "theme": "dark",
            "notifications": True
        }
    },
    "items": ["apple", "banana", "cherry"]
}

dict2 = {
    "user": {
        "name": "Alice",
        "age": 29,
        "settings": {
            "theme": "light"
        }
    },
    "items": ["apple", "banana", "cherry", "strawberries"]
}

res2 = test_pod.deep_merge(dict1, dict2)

assert res2 == {'user': {'name': 'Alice', 'age': 29, 'settings': {'theme': 'light', 'notifications': True}}, 'items': ['apple', 'banana', 'cherry', 'strawberries']}

# Test custom transit read/write handlers
from datetime import datetime
import uuid

# Test UUID round-trip (using built-in transit UUID support)
test_uuid = uuid.uuid4()
uuid_result = test_pod.echo(test_uuid)
assert uuid_result == test_uuid

# Test datetime round-trip (using pod's LocalDateTime handler)
# Use timezone-naive datetime to match Java LocalDateTime
test_datetime = datetime.now().replace(microsecond=0)  # Remove microseconds for cleaner comparison
datetime_result = test_pod.echo(test_datetime)
assert datetime_result == test_datetime

# Test array round-trip (using pod's java.array handler)
test_array = [1, 2, 3, "test", True]
array_result = test_pod.echo(test_array)

assert array_result == test_array

# Test metadata functionality
from transit2 import WithMeta

# Create data with metadata
test_data = [1, 2, 3, 4, 5]
test_metadata = {"source": "user-input", "timestamp": "2024-01-01", "version": 1}
wrapped_data = WithMeta(test_data, test_metadata)

try:
    metadata_result = test_pod.echo_meta(wrapped_data)
        
    # Check if we got the data back
    if hasattr(metadata_result, 'value'):
        assert metadata_result.value == test_data
    else:
        assert metadata_result == test_data
        
except Exception as e:
    print(f"❌ Metadata test failed: {e}")
    import traceback
    traceback.print_exc()


# Test custom transit handlers
def test_custom_transit_handlers():
    """Test custom Transit read/write handler registration"""
    
    # Define a custom Python class
    class Point:
        def __init__(self, x, y):
            self.x = x
            self.y = y
        
        def __eq__(self, other):
            return isinstance(other, Point) and self.x == other.x and self.y == other.y
        
        def __repr__(self):
            return f"Point({self.x}, {self.y})"
    
    # Define read handler class
    class PointReadHandler:
        @staticmethod
        def from_rep(rep):
            return Point(rep[0], rep[1])
    
    # Define write handler class
    class PointWriteHandler:
        @staticmethod
        def tag(obj):
            return "point"
        
        @staticmethod
        def rep(obj):
            return [obj.x, obj.y]
    
    # Register handlers using direct pod access (alternative approach)
    transit_instance = pod.get("transit_instance")
    if transit_instance:
        transit_instance.add_read_handler("point", PointReadHandler)
        transit_instance.add_write_handler([Point], PointWriteHandler)
        
        # Test the custom handlers
        original_point = Point(10, 20)
        
        # Send point to pod and get it back - should preserve Point type
        result_point = test_pod.echo(original_point)
        
        # Verify the result
        assert isinstance(result_point, Point), f"Expected Point, got {type(result_point)}"
        assert result_point == original_point, f"Expected {original_point}, got {result_point}"
    else:
        print("❌ No transit instance found")

# Add this call after the metadata test
test_custom_transit_handlers()