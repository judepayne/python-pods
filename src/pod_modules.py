import sys
import types

loaded_namespaces = {}


# Code required to expose pod namespaces as python modules
def namespace_to_module_name(ns_name):
    """Convert pod namespace to Python module name"""
    # Convert pod.lispyclouds.docker -> pod_lispyclouds_docker
    return ns_name.replace('.', '_').replace('-', '_')

def expose_namespace_as_module(pod, namespace):
    """Register pod namespace as an importable Python module"""
    ns_name = namespace["name"]
    ns_vars = namespace["vars"]
    pod_id = pod["pod_id"]
    
    # Create the module name
    module_name = namespace_to_module_name(ns_name)
    
    # Create a new module
    module = types.ModuleType(module_name)
    
    # Add metadata
    module.__doc__ = f"Pod namespace: {ns_name}"
    module.__pod_namespace__ = ns_name
    module.__pod_id__ = pod_id
    
    # Add functions to the module
    for func_name, func in ns_vars.items():
        # Add with original name (kebab-case)
        setattr(module, func_name, func)
        
        # Also add Python-style name (snake_case) for convenience
        python_name = func_name.replace('-', '_')
        if python_name != func_name:
            setattr(module, python_name, func)
    
    # Register in sys.modules so it can be imported
    sys.modules[module_name] = module
    
    # Track the loaded namespace
    if pod_id not in loaded_namespaces:
        loaded_namespaces[pod_id] = {}
    loaded_namespaces[pod_id][ns_name] = namespace
    
    print(f"📦 Registered module: {module_name} (namespace: {ns_name})")
    print(f"   Functions: {list(ns_vars.keys())}")
    
    return module

def expose_non_deferred_namespaces(pod):
    """Expose only non-deferred pod namespaces as importable modules"""
    modules = []
    for namespace in pod["namespaces"]:
        defer = namespace.get("defer", False)
        if not defer:  # Only expose if defer is False or None
            module = expose_namespace_as_module(pod, namespace)
            modules.append(module)
        else:
            print(f"⏳ Deferred namespace: {namespace['name']} (will load on demand)")
    return modules


def list_pod_modules():
    """List all currently registered pod modules"""
    pod_modules = {name: module for name, module in sys.modules.items() 
                   if hasattr(module, '__pod_namespace__')}
    
    if not pod_modules:
        print("No pod modules currently registered")
        return
    
    print("Registered pod modules:")
    for module_name, module in pod_modules.items():
        ns_name = module.__pod_namespace__
        pod_id = module.__pod_id__
        functions = [name for name in dir(module) 
                    if not name.startswith('_') and callable(getattr(module, name))]
        print(f"  {module_name} (namespace: {ns_name}, pod: {pod_id})")
        print(f"    Functions: {functions}")

def unregister_pod_modules(pod_id):
    """Unregister all modules from a specific pod"""
    to_remove = []
    for module_name, module in sys.modules.items():
        if hasattr(module, '__pod_id__') and module.__pod_id__ == pod_id:
            to_remove.append(module_name)
    
    for module_name in to_remove:
        del sys.modules[module_name]
    
    # Clean up loaded namespaces tracking
    loaded_namespaces.pop(pod_id, None)

def load_and_expose_namespace(pod_id, namespace_name):
    """Load a deferred namespace and expose it as a module"""
    # Import inside function to avoid circular dependency
    from python_pods import lookup_pod, load_ns
    
    pod = lookup_pod(pod_id)
    if not pod:
        raise ValueError(f"Pod {pod_id} not found")
    
    # Check if already loaded
    if (pod_id in loaded_namespaces and 
        namespace_name in loaded_namespaces[pod_id]):
        print(f"✅ Namespace {namespace_name} already loaded")
        return loaded_namespaces[pod_id][namespace_name]
    
    # Find the namespace in the pod's deferred namespaces
    deferred_namespace = None
    for namespace in pod["namespaces"]:
        if namespace["name"] == namespace_name and namespace.get("defer", False):
            deferred_namespace = namespace
            break
    
    if not deferred_namespace:
        raise ValueError(f"Deferred namespace {namespace_name} not found in pod {pod_id}")
    
    # Load the namespace from the pod
    result = load_ns(pod, namespace_name)
    
    # If load_ns returns a namespace dict, use it; otherwise use the existing one
    if isinstance(result, dict) and "name" in result:
        # Update the namespace with loaded vars
        deferred_namespace.update(result)
    
    # Now expose it as a module
    module = expose_namespace_as_module(pod, deferred_namespace)
    
    print(f"🚀 Loaded and registered deferred namespace: {namespace_name}")
    return deferred_namespace

def list_deferred_namespaces(pod_id=None):
    """List deferred namespaces for a pod or all pods"""
    # Import inside function to avoid circular dependency
    from python_pods import lookup_pod, pods
    
    if pod_id:
        pod = lookup_pod(pod_id)
        if not pod:
            print(f"Pod {pod_id} not found")
            return
        pods_to_check = {pod_id: pod}
    else:
        pods_to_check = pods
    
    deferred_found = False
    for pid, pod in pods_to_check.items():
        pod_deferred = []
        for namespace in pod["namespaces"]:
            if namespace.get("defer", False):
                is_loaded = (pid in loaded_namespaces and 
                           namespace["name"] in loaded_namespaces[pid])
                status = "loaded" if is_loaded else "not loaded"
                pod_deferred.append(f"    {namespace['name']} ({status})")
        
        if pod_deferred:
            deferred_found = True
            print(f"Pod {pid} deferred namespaces:")
            for ns_info in pod_deferred:
                print(ns_info)
    
    if not deferred_found:
        print("No deferred namespaces found")