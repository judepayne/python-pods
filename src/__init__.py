"""Python Pods - A faithful port of babashka pods to python"""

from .python_pods import (
    # Core functions
    load_pod,
    unload_pod,
    invoke_public,
    PodError,
    
    # Patch functions
    register_code_patch,
    register_edn_reader_patch,
    register_result_transform_patch,
    clear_patches,
    list_patches,
    
    # Transit handlers
    add_transit_read_handler,
    add_transit_write_handler,
    set_default_transit_write_handler,
)

from .pod_modules import (
    list_pod_modules,
    load_and_expose_namespace,
    list_deferred_namespaces,    
)

from .transit2 import (
    WithMeta
)

__version__ = "0.1.0"
__all__ = [
    "load_pod",
    "unload_pod", 
    "invoke_public",
    "PodError",
    "register_code_patch",
    "register_edn_reader_patch", 
    "register_result_transform_patch",
    "clear_patches",
    "list_patches",
    "add_transit_read_handler",
    "add_transit_write_handler",
    "set_default_transit_write_handler",
    "list_pod_modules",
    "load_and_expose_namespace",
    "list_deferred_namespaces",
    "WithMeta",
]