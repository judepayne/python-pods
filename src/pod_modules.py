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