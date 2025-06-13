import sys
sys.path.append("src")
import python_pods as pods  # type: ignore

pod = pods.load_pod(["clojure", "-M:test-pod"], {"resolve": True})

pod_id = pod['pod_id']

# Import the pod namespace
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

res3 = test_pod.echo({"test": "data"})
assert res3 == {'test': 'data'}

# Test custom EDN readers with tagged data (these should just echo back as strings)
person_tagged = "#person {:name \"Alice\", :age 30}"
date_tagged = "#date \"2025-06-07\""
res4 = test_pod.echo(person_tagged)
res5 = test_pod.echo(date_tagged)

assert res4 == person_tagged
assert res5 == date_tagged


def test_custom_edn_handlers():
    """Test custom EDN read/write handler registration"""
    
    # Define Python classes that match the pod's EDN readers
    class Person:
        def __init__(self, name, age):
            self.name = name
            self.age = age
        
        def __repr__(self):
            return f"Person('{self.name}', {self.age})"
    
    class Date:
        def __init__(self, date_string):
            self.date_string = date_string
        
        def __repr__(self):
            return f"Date('{self.date_string}')"
    
    # Define write handlers that create data in the format expected by the pod
    def write_person(person):
        # Return the data structure that will be serialized as EDN
        # The edn.py library will handle the TaggedLiteral creation internally
        return {'name': person.name, 'age': person.age}
    
    def write_date(date):
        # Return the data that will be serialized as EDN
        return date.date_string
    
    # Test that our EDN instance exists and has readers
    edn_instance = pod.get("edn_instance")
    assert edn_instance is not None, "EDN instance should exist"
    assert hasattr(edn_instance, 'readers'), "EDN instance should have readers"
    
    # Check that the expected readers are available
    expected_readers = ['person', 'date']
    available_readers = list(edn_instance.readers.keys())
    
    for reader in expected_readers:
        assert reader in available_readers, f"Reader '{reader}' should be available in {available_readers}"

# Call the test function
test_custom_edn_handlers()