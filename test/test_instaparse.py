import sys
sys.path.append("src")
import python_pods as pods  # type: ignore

def unwrap_withmeta(node):
    """Recursively unwrap WithMeta objects and convert keywords to strings"""
    if hasattr(node, 'value'):
        # Unwrap WithMeta and recurse
        return unwrap_withmeta(node.value)
    elif isinstance(node, dict):
        # Process dictionaries (like failure objects)
        result = {}
        for key, value in node.items():
            clean_key = unwrap_withmeta(key)
            clean_value = unwrap_withmeta(value)
            result[clean_key] = clean_value
        return result
    elif isinstance(node, list):
        # Process each item in the list
        return [unwrap_withmeta(item) for item in node]
    elif str(type(node)) == "<class 'transit.transit_types.Keyword'>":
        # Convert keyword to string, removing the wrapper
        keyword_str = str(node)
        # Extract just the keyword name, handling namespaced keywords
        if ' ' in keyword_str:
            name = keyword_str.split(' ')[1].rstrip(' >')
            if '/' in name:
                return name.split('/')[-1]  # Just the name part
            return name
        return keyword_str
    else:
        return node

# Load the pod
pod = pods.load_pod('org.babashka/instaparse', {'version': '0.0.6'})
pod_id = pod['pod_id']

# Register result transform patch for the parse function
# This will automatically clean up the results from instaparse
pods.register_result_transform_patch(
    pod_id, 
    'pod.babashka.instaparse/parse', 
    unwrap_withmeta
)

# Now use the pod normally - results will be automatically transformed
import pod_babashka_instaparse as insta # type: ignore

parser = insta.parser("S = AB* AB = A B A = 'a'+ B = 'b'+")
result = insta.parse(parser, "aaaaabbbaaaabb")

# The result is now automatically cleaned - no manual unwrapping needed!
assert result == ['S', ['AB', ['A', 'a', 'a', 'a', 'a', 'a'], ['B', 'b', 'b', 'b']], ['AB', ['A', 'a', 'a', 'a', 'a'], ['B', 'b', 'b']]]
