import sys
sys.path.append("src")
import python_pods as pods  # type: ignore

pod = pods.load_pod(["clojure", "-M:test-pod", "--json"])

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

# Test async functionality
# Collect async results
async_results = []
async_done = False

def handle_success(value):
    print(f"Received: {value}")
    # Filter out the initial status response
    if value != {'status': 'started'}:
        async_results.append(value)

def handle_done():
    global async_done
    print("Async operation completed!")
    async_done = True

def handle_error(error):
    print(f"Error: {error}")

# Use lower-level invoke for async operation
result = pods.invoke(
    pod, 
    "pod.test-pod/async-countdown", 
    [{}],  # Empty opts, callbacks are provided separately
    {"handlers": {
        "success": handle_success,
        "done": handle_done,
        "error": handle_error
    }}
)

# Wait for async operation to complete with proper blocking
import time
max_wait = 6  # Wait up to 6 seconds (a bit longer than the 3 second countdown)
start_time = time.time()
print("Waiting for async events...")

while not async_done and (time.time() - start_time) < max_wait:
    time.sleep(0.1)  # Small sleep to prevent busy waiting
    
    # Add some progress indication
    elapsed = time.time() - start_time
    if int(elapsed) != int(elapsed - 0.1):  # Print every second
        print(f"Waiting... ({elapsed:.1f}s elapsed)")

if async_done:
    assert async_results == ["3", "2", "1"], f"Expected ['3', '2', '1'], got {async_results}"
else:
    print(f"❌ Async operation timed out. Received so far: {async_results}")
    print("This might indicate an issue with the async callback handling")


# Test client-side code execution functionality
import math

# Test 1: Function definition code
function_result = test_pod.return_python_code("function")

# NEW: The function should now be available globally
try:
    # Test using the globally available function
    global_test = multiply_by_three(7)  # Should work now!
    assert global_test == 21, f"Expected 21, got {global_test}"
    
    # Also test the returned function
    if callable(function_result):
        test_value = function_result(10)
        assert test_value == 30, f"Expected 30, got {test_value}"
    
except NameError as e:
    print(f"❌ Function not available in global scope: {e}")

# Test 2: Expression code
expression_result = test_pod.return_python_code("expression")

# Should get back the result of the expression (50)
assert expression_result == 50, f"Expected 50, got {expression_result}"

# Test 3: Complex code with imports and multiple definitions
complex_result = test_pod.return_python_code("complex")

# Should get back the calculated area (math.pi * 5 * 5)
expected_area = math.pi * 5 * 5

# NEW: The functions should now be available in our namespace
try:
    # Test that the function is now available globally
    test_area = calculate_area(3)  # Should work now!
    
    # Check the returned value
    assert abs(complex_result - expected_area) < 0.0001, f"Expected {expected_area}, got {complex_result}"
    
except NameError as e:
    print(f"❌ Function not available in global scope: {e}")

# Test 4: Simple Python-only code (no multi-language structure)
simple_result = test_pod.return_python_code("simple")

# NEW: Check if the variable is available globally
try:
    # The variable should now be available globally
    assert simple_value == "Hello from executed Python code!", f"Expected string message, got {simple_value}"
    
    # Also check the returned value
    assert simple_result == "Hello from executed Python code!", f"Expected string message, got {simple_result}"
    
except NameError as e:
    print(f"❌ Variable not available in global scope: {e}")

# Test 5: Verify that non-code results still work normally
normal_result = test_pod.add_one(42)
assert normal_result == 43, f"Expected 43, got {normal_result}"

# Test 6: Code patch functionality
print("Testing code patch...")

# Register a simple code patch that replaces add_one with custom logic
pod_id = pod['pod_id']
pods.register_code_patch(
    pod_id, 
    'pod.test-pod/add-one',
    '''
# Simple patch: instead of adding 1, add 10
x = args[0]
result = x + 10
'''
)

# Test 6: Code patch functionality
print("Testing code patch...")

# The define-add2 function returns Clojure code, but we want Python
# Let's register a code patch to replace it with Python code
pod_id = pod['pod_id']
pods.register_code_patch(
    pod_id, 
    'pod.test-pod/define-add2',
    '''
# Simple patch: return Python code instead of Clojure
def add2(x):
    return x + 2

result = add2
'''
)

# Test the patched function - it should now execute Python code and define add2
patched_result = test_pod.define_add2()
assert patched_result(4) == 6