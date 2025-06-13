import sys
sys.path.append("src")
import python_pods as pods  # type: ignore

# Load pod with socket transport
pod = pods.load_pod(["clojure", "-M:test-pod"], {"transport": "socket"})

# Import the pod namespace
import pod_test_pod as test_pod # type: ignore

# Test basic function call
result = test_pod.add_one(5)
assert result == 6

# Test echo with data
test_data = {"message": "Hello from socket transport!", "numbers": [1, 2, 3, 4, 5]}
echo_result = test_pod.echo(test_data)
assert echo_result == test_data

# Test deep merge
dict1 = {"a": {"x": 1, "y": 2}, "b": [1, 2]}
dict2 = {"a": {"y": 3, "z": 4}, "b": [3, 4]}
merge_result = test_pod.deep_merge(dict1, dict2)
expected = {"a": {"x": 1, "y": 3, "z": 4}, "b": [3, 4]}
assert merge_result == expected

# Check if socket exists in pod
assert pod["socket"] != None

# Clean up
pods.destroy(pod["pod_id"])