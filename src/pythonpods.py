import os
import sys
import json
import uuid
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Union
from concurrent.futures import Future, ThreadPoolExecutor
import bencodepy as bencode
from bencode_reader import read_message as read_bencode_stream
from transit.writer import Writer
from transit.reader import Reader
import edn
from resolver import resolve
import time
import types

# Global state
pods = {}
loaded_namespaces = {} #tracks namespaces loaded from pods
transit_read_handlers = {}
transit_read_handler_maps = {}
transit_write_handlers = {}
transit_write_handler_maps = {}
transit_default_write_handlers = {}

# Thread-local storage for pod-id
import threading
_thread_local = threading.local()

def get_pod_id():
    return getattr(_thread_local, 'pod_id', None)

def set_pod_id(pod_id):
    _thread_local.pod_id = pod_id

def warn(*args):
    print(*args, file=sys.stderr)

def debug(*args):
    print(*args, file=sys.stderr)

def next_id():
    return str(uuid.uuid4())

def bytes_to_string(data):
    if isinstance(data, bytes):
        return data.decode('utf-8')
    return data

def bytes_to_boolean(data):
    if isinstance(data, bytes):
        return data.decode('utf-8') == 'true'
    return data

def get_string(m, k):
    return bytes_to_string(m.get(k))

def get_maybe_string(m, k):
    value = m.get(k)
    return bytes_to_string(value) if value is not None else None

def get_maybe_boolean(m, k):
    value = m.get(k)
    return bytes_to_boolean(value) if value is not None else None

class PodError(Exception):
    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data or {}

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

def load_and_expose_namespace(pod_id, namespace_name):
    """Load a deferred namespace and expose it as a module"""
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

def list_deferred_namespaces(pod_id=None):
    """List deferred namespaces for a pod or all pods"""
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

def unregister_pod_modules(pod_id):
    """Unregister all modules from a specific pod"""
    to_remove = []
    for module_name, module in sys.modules.items():
        if hasattr(module, '__pod_id__') and module.__pod_id__ == pod_id:
            to_remove.append(module_name)
    
    for module_name in to_remove:
        del sys.modules[module_name]
        print(f"🗑️  Unregistered module: {module_name}")
    
    # Clean up loaded namespaces tracking
    loaded_namespaces.pop(pod_id, None)

# Update the load_ns function to work with deferred loading
def load_ns_enhanced(pod, namespace_name):
    """Enhanced load_ns that works with the module system"""
    # Call the original load_ns function
    result = load_ns(pod, namespace_name)
    
    # If this was a deferred namespace, expose it as a module
    pod_id = pod["pod_id"]
    
    # Check if this namespace was deferred and not yet loaded
    for namespace in pod["namespaces"]:
        if (namespace["name"] == namespace_name and 
            namespace.get("defer", False) and
            (pod_id not in loaded_namespaces or 
             namespace_name not in loaded_namespaces[pod_id])):
            
            # Update the namespace with the loaded result if it's a dict
            if isinstance(result, dict) and "vars" in result:
                namespace.update(result)
            
            # Expose as module
            expose_namespace_as_module(pod, namespace)
            break
    
    return result
# End Code required to expose pod namespaces as python modules

# def update_transit_read_handler_map(pod_id):
#     if pod_id in transit_read_handlers:
#         handlers = transit_read_handlers[pod_id]
#         transit_read_handler_maps[pod_id] = transit.create_read_handler_map(handlers)

# def add_transit_read_handler(tag, fn, pod_id=None):
#     pod_id = pod_id or get_pod_id()
#     if pod_id not in transit_read_handlers:
#         transit_read_handlers[pod_id] = {}
#     transit_read_handlers[pod_id][tag] = fn
#     update_transit_read_handler_map(pod_id)

# def update_transit_write_handler_map(pod_id):
#     if pod_id in transit_write_handlers:
#         handlers = transit_write_handlers[pod_id]
#         transit_write_handler_maps[pod_id] = transit.create_write_handler_map(handlers)

# def add_transit_write_handler(classes, tag, fn, pod_id=None):
#     pod_id = pod_id or get_pod_id()
#     if pod_id not in transit_write_handlers:
#         transit_write_handlers[pod_id] = {}
#     for cls in classes:
#         transit_write_handlers[pod_id][cls] = (tag, fn)
#     update_transit_write_handler_map(pod_id)

# def set_default_transit_write_handler(tag_fn, val_fn, pod_id=None):
#     pod_id = pod_id or get_pod_id()
#     transit_default_write_handlers[pod_id] = (tag_fn, val_fn)

# def transit_json_read(pod_id, s):
#     handler_map = transit_read_handler_maps.get(pod_id, {})
#     return transit.read(transit.reader('json', handler_map=handler_map), s)

# def transit_json_write(pod_id, obj, metadata=False):
#     handler_map = transit_write_handler_maps.get(pod_id, {})
#     default_handler = transit_default_write_handlers.get(pod_id)
#     writer = transit.writer('json', handler_map=handler_map, default_handler=default_handler)
#     return transit.write(writer, obj)

def write_message(stream, message):
    """Write a bencode message to stream"""
    encoded = bencode.encode(message)
    stream.write(encoded)
    stream.flush()

def read_message(stream):
    """Read a bencode message from stream"""
    try:
        return read_bencode_stream(stream)
    except EOFError:
        return None

def bencode_to_vars(pod, ns_name_str, vars_list):
    """Convert bencode vars to Python functions"""
    result = {}
    
    for var in vars_list:
        name = get_string(var, "name")
        async_flag = get_maybe_string(var, "async")
        is_async = async_flag == "true" if async_flag else False
        code = get_maybe_string(var, "code")
        meta_str = get_maybe_string(var, "meta")
        arg_meta = get_maybe_boolean(var, "arg-meta")
        
        var_meta = None
        if meta_str:
            try:
                var_meta = edn.from_edn(meta_str)
            except:
                pass
        
        if code:
            # If code is provided, use it directly
            result[name] = code
        else:
            # Create a function that invokes the pod
            def create_invoker(var_name, is_async, arg_meta):
                def invoker(*args):
                    return invoke(pod, f"{ns_name_str}/{var_name}", list(args), 
                                {"async": is_async, "arg_meta": arg_meta})
                return invoker
            
            result[name] = create_invoker(name, is_async, arg_meta)
    
    return result

def invoke(pod, pod_var, args, opts=None):
    """Invoke a function in the pod"""
    opts = opts or {}
    handlers = opts.get("handlers")
    stream = pod["stdin"]
    format_type = pod["format"]
    chans = pod["chans"]
    
    # Determine write function based on format
    if format_type == "edn":
        write_fn = edn.to_edn
    elif format_type == "json":
        write_fn = json.dumps
    # elif format_type == "transit+json":
    #     write_fn = lambda x: transit_json_write(pod["pod_id"], x, opts.get("arg_meta", False))
    else:
        write_fn = str
    
    msg_id = next_id()
    
    if handlers:
        chan = handlers
    else:
        chan = Future()
    
    chans[msg_id] = chan
    
    message = {
        "id": msg_id,
        "op": "invoke",
        "var": str(pod_var),
        "args": write_fn(args)
    }
    
    write_message(stream, message)
    
    if not handlers:
        result = chan.result()  # This will block until result is available
        if isinstance(result, Exception):
            raise result
        return result

def create_socket(hostname, port):
    """Create a socket connection"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.connect((hostname, port))
    return sock

def close_socket(sock):
    """Close a socket"""
    try:
        sock.close()
    except:
        pass

def port_file(pid):
    """Get the port file for a process"""
    return Path(f".babashka-pod-{pid}.port")

def read_port(port_file_path):
    """Read port from port file"""
    while True:
        if port_file_path.exists():
            content = port_file_path.read_text().strip()
            if content.endswith('\n') or content:
                try:
                    return int(content.strip())
                except ValueError:
                    pass
        time.sleep(0.01)  # Small delay before retry

def processor(pod):
    """Process messages from pod stdout"""
    stdout = pod["stdout"]
    format_type = pod["format"]
    chans = pod["chans"]
    out_stream = pod["out"]
    err_stream = pod["err"]
    readers = pod.get("readers", {})
    pod_id = pod["pod_id"]
    
    # Determine read function based on format
    if format_type == "edn":
        def read_fn(s):
            try:
                return edn.from_edn(s)
            except Exception as e:
                print(f"Cannot read EDN: {repr(s)}", file=sys.stderr)
                raise e
    elif format_type == "json":
        def read_fn(s):
            try:
                return json.loads(s)
            except Exception as e:
                print(f"Cannot read JSON: {repr(s)}", file=sys.stderr)
                raise e
    # elif format_type == "transit+json":
    #     def read_fn(s):
    #         try:
    #             return transit_json_read(pod_id, s)
    #         except Exception as e:
    #             print(f"Cannot read Transit JSON: {repr(s)}", file=sys.stderr)
    #             raise e
    else:
        read_fn = str
    
    set_pod_id(pod_id)
    
    try:
        while True:
            reply = read_message(stdout)
            if reply is None:  # EOF
                break
            
            msg_id = get_string(reply, "id")
            value_entry = reply.get("value")
            
            exception = None
            value = None
            
            if value_entry is not None:
                try:
                    value_str = bytes_to_string(value_entry)
                    value = read_fn(value_str)
                except Exception as e:
                    exception = e
            
            status_list = reply.get("status", [])
            status = set(bytes_to_string(s) for s in status_list)
            
            error = exception or "error" in status
            done = error or exception or "done" in status
            
            ex_message = ""
            ex_data = {}
            if error:
                ex_message = get_maybe_string(reply, "ex-message") or ""
                ex_data_str = get_maybe_string(reply, "ex-data")
                if ex_data_str:
                    try:
                        ex_data = read_fn(ex_data_str)
                    except:
                        ex_data = {}
            
            namespace = None
            if "vars" in reply:
                name_str = get_string(reply, "name")
                vars_list = reply["vars"]
                namespace = {
                    "name": name_str,
                    "vars": bencode_to_vars(pod, name_str, vars_list)
                }
            
            chan = chans.get(msg_id)
            if chan is None:
                continue
            
            is_future = isinstance(chan, Future)
            
            if not is_future and isinstance(chan, dict):
                error_handler = chan.get("error")
                done_handler = chan.get("done")
                success_handler = chan.get("success")
            else:
                error_handler = done_handler = success_handler = None
            
            # Handle output streams
            out_msg = get_maybe_string(reply, "out")
            err_msg = get_maybe_string(reply, "err")
            
            if out_msg:
                out_stream.write(out_msg)
                out_stream.flush()
            
            if err_msg:
                err_stream.write(err_msg)
                err_stream.flush()
            
            # Handle the main response
            if value_entry is not None or error or namespace:
                if is_future:
                    if error:
                        chan.set_exception(PodError(ex_message, ex_data))
                    elif value is not None:
                        chan.set_result(value)
                    elif namespace:
                        chan.set_result(namespace)
                else:
                    if not error and success_handler:
                        success_handler(value)
                    elif error and error_handler:
                        error_handler({"ex-message": ex_message, "ex-data": ex_data})
            
            if done and not error:
                if is_future:
                    if not chan.done():
                        chan.set_result(None)
                elif done_handler:
                    done_handler()
    
    except Exception as e:
        print(f"Processor error: {e}", file=sys.stderr)

def get_pod_id_from_spec(x):
    """Extract pod ID from pod spec"""
    if isinstance(x, dict):
        return x.get("pod/id")
    return x

def lookup_pod(pod_id):
    """Look up a pod by ID"""
    return pods.get(pod_id)

def destroy_pod(pod):
    """Destroy a pod process"""
    ops = pod.get("ops", set())
    stdin = pod["stdin"]
    process = pod["process"]
    
    if "shutdown" in ops:
        try:
            message = {"op": "shutdown", "id": next_id()}
            write_message(stdin, message)
            process.wait(timeout=5)  # Wait up to 5 seconds
        except:
            process.terminate()
    else:
        process.terminate()

def destroy(pod_id_or_pod):
    """Destroy a pod and clean up"""
    pod_id = get_pod_id_from_spec(pod_id_or_pod)
    pod = lookup_pod(pod_id)
    
    if pod:
        # NEW: Unregister modules first
        unregister_pod_modules(pod_id)
        
        destroy_pod(pod)
        # Clean up namespaces if needed
        remove_ns_fn = pod.get("remove_ns")
        if remove_ns_fn:
            for namespace in pod.get("namespaces", []):
                ns_name = namespace["name"]  # Access dict key instead of tuple unpacking
                remove_ns_fn(ns_name)
    
    pods.pop(pod_id, None)
    return None

def read_readers(reply, resolve_fn):
    """Read reader functions from reply"""
    readers_dict = reply.get("readers")
    if not readers_dict:
        return {}
    
    result = {}
    for k, v in readers_dict.items():
        key = k if isinstance(k, str) else bytes_to_string(k)
        val = bytes_to_string(v) if isinstance(v, bytes) else v
        result[key] = resolve_fn(val)
    
    return result

def bencode_to_namespace(pod, namespace):
    """Convert bencode namespace to Python namespace"""
    name_str = get_string(namespace, "name")
    vars_list = namespace.get("vars", [])
    defer_str = get_maybe_string(namespace, "defer")
    defer = defer_str == "true" if defer_str else False
    
    vars_dict = bencode_to_vars(pod, name_str, vars_list)
    
    # Return a dictionary instead of tuple
    return {
        "name": name_str,
        "vars": vars_dict,
        "defer": defer
    }

def resolve_pod(pod_spec, opts=None):
    """Resolve pod specification"""
    opts = opts or {}
    version = opts.get("version")
    path = opts.get("path")
    force = opts.get("force", False)
    
    # Check if pod_spec is a qualified symbol (string with namespace/name format)
    is_qualified_symbol = isinstance(pod_spec, str) and '/' in pod_spec
    
    if is_qualified_symbol:
        if not version and not path:
            raise ValueError("Version or path must be provided")
        if version and path:
            raise ValueError("You must provide either version or path, not both")
    
    resolved = None
    if is_qualified_symbol and version:
        # Use the resolver to get the executable and options
        resolved = resolve(pod_spec, version, force)
    
    # Merge any extra options from the resolved pod
    if resolved:
        extra_opts = resolved.get("options")
        if extra_opts:
            opts = {**opts, **extra_opts}
    
    # Determine the final pod_spec (command to run)
    if resolved:
        # Use the executable from resolver
        final_pod_spec = [resolved["executable"]]
    elif path:
        # Use the provided path
        final_pod_spec = [path]
    elif isinstance(pod_spec, str):
        # Use the string as-is (single command)
        final_pod_spec = [pod_spec]
    else:
        # Assume it's already a list/sequence of commands
        final_pod_spec = list(pod_spec)
    
    return {
        "pod_spec": final_pod_spec,
        "opts": opts
    }

def run_pod(pod_spec, opts=None):
    """Run a pod process and return communication handles"""
    opts = opts or {}
    transport = opts.get("transport")
    
    # Create the process
    is_socket = transport == "socket"
    
    # Set up process builder equivalent
    env = os.environ.copy()
    env["BABASHKA_POD"] = "true"
    
    if is_socket:
        env["BABASHKA_POD_TRANSPORT"] = "socket"
    
    # Configure stdio redirection
    if is_socket:
        # For socket transport, inherit IO
        stdout = None
        stderr = None
    else:
        # For stdio transport, redirect stderr to inherit, capture stdout
        stdout = subprocess.PIPE
        stderr = None  # Will inherit
    
    # Start the process
    process = subprocess.Popen(
        pod_spec,
        env=env,
        stdin=subprocess.PIPE,
        stdout=stdout,
        stderr=stderr
    )
    
    if is_socket:
        # Handle socket transport
        port_file_path = port_file(process.pid)
        socket_port = read_port(port_file_path)
        
        # Connect to the socket
        sock = None
        while sock is None:
            try:
                sock = create_socket("localhost", socket_port)
            except ConnectionRefusedError:
                time.sleep(0.01)  # Small delay before retry
        
        # Use socket streams
        stdin_stream = sock.makefile('wb')
        stdout_stream = sock.makefile('rb')
        
        return {
            "process": process,
            "socket": sock,
            "stdin": stdin_stream,
            "stdout": stdout_stream
        }
    else:
        # Handle stdio transport
        return {
            "process": process,
            "socket": None,
            "stdin": process.stdin,
            "stdout": process.stdout
        }

def describe_pod(running_pod):
    """Send describe operation to pod and get response"""
    stdin = running_pod["stdin"]
    stdout = running_pod["stdout"]

    message = {
        "op": "describe",
        "id": next_id()
    }
    
    write_message(stdin, message)
    return read_message(stdout)

def describe_to_ops(describe_reply):
    """Extract operations from describe reply"""
    ops_dict = describe_reply.get("ops")
    if not ops_dict:
        return set()
    
    # Convert keys to a set of operation names
    return set(ops_dict.keys())

def describe_to_metadata(describe_reply, resolve_fn=None):
    """Extract metadata from describe reply"""
    format_bytes = describe_reply.get("format")
    format_str = bytes_to_string(format_bytes) if format_bytes else "edn"
    format_type = format_str
    
    ops = describe_to_ops(describe_reply)
    
    readers = {}
    if format_type == "edn" and resolve_fn:
        readers = read_readers(describe_reply, resolve_fn)
    
    return {
        "format": format_type,
        "ops": ops,
        "readers": readers
    }

def run_pod_for_metadata(pod_spec, opts=None):
    """Run a pod just to get its metadata, then shut it down"""
    opts = opts or {}
    
    # Start the pod
    running_pod = run_pod(pod_spec, opts)
    
    try:
        # Get the describe response
        describe_reply = describe_pod(running_pod)
        ops = describe_to_ops(describe_reply)
        
        # Shut down the pod
        destroy_pod({**running_pod, "ops": ops})
        
        return describe_reply
    
    except Exception as e:
        # Make sure to clean up the process if something goes wrong
        try:
            running_pod["process"].terminate()
        except:
            pass
        raise e

def load_pod_metadata(unresolved_pod_spec, opts=None):
    """Load pod metadata, resolving the pod spec first"""
    opts = opts or {}
    download_only = opts.get("download_only", False)
    
    # Resolve the pod specification
    resolved = resolve_pod(unresolved_pod_spec, opts)
    pod_spec = resolved["pod_spec"]
    final_opts = resolved["opts"]
    
    if download_only:
        warn("Not running pod", unresolved_pod_spec, 
             "to pre-cache metadata because OS and/or arch are different than system")
        return None
    else:
        return run_pod_for_metadata(pod_spec, final_opts)


def load_pod(pod_spec, opts=None):
    """Load a pod and return the pod object"""
    opts = opts or {}
    
    # Resolve the pod specification
    resolved = resolve_pod(pod_spec, opts)
    final_pod_spec = resolved["pod_spec"]
    final_opts = resolved["opts"]
    
    remove_ns = final_opts.get("remove_ns")
    resolve_fn = final_opts.get("resolve")
    
    # Start the pod process
    running_pod = run_pod(final_pod_spec, final_opts)
    
    process = running_pod["process"]
    stdin = running_pod["stdin"]
    stdout = running_pod["stdout"]
    sock = running_pod.get("socket")

    # Get pod description or use provided metadata
    reply = final_opts.get("metadata")

    if not reply:
        reply = describe_pod(running_pod)

    # Extract metadata
    metadata = describe_to_metadata(reply, resolve_fn)
    format_type = metadata["format"]
    ops = metadata["ops"]
    readers = metadata["readers"]
    
    # Get pod namespaces
    pod_namespaces_raw = reply.get("namespaces", [])
    
    # Determine pod ID
    pod_id = None
    if pod_namespaces_raw:
        first_ns = pod_namespaces_raw[0]
        pod_id = get_string(first_ns, "name")
    
    if not pod_id:
        pod_id = next_id()
    
    # Create the pod object
    pod = {
        "process": process,
        "pod_spec": final_pod_spec,
        "stdin": stdin,
        "stdout": stdout,
        "chans": {},
        "format": format_type,
        "ops": ops,
        "out": sys.stdout,
        "err": sys.stderr,
        "remove_ns": remove_ns,
        "readers": readers,
        "pod_id": pod_id
    }
    
    # Process namespaces
    pod_namespaces = []
    for ns_raw in pod_namespaces_raw:
        ns_dict = bencode_to_namespace(pod, ns_raw)  # Now returns a dict
        pod_namespaces.append(ns_dict)
    
    pod["namespaces"] = pod_namespaces
    
    # Set up shutdown hook (Python equivalent using atexit)
    import atexit
    def cleanup():
        destroy(pod_id)
        if sock:
            close_socket(sock)
    
    atexit.register(cleanup)
    
    # Start the processor thread
    processor_thread = threading.Thread(target=processor, args=(pod,))
    processor_thread.daemon = True
    processor_thread.start()
 #   with ThreadPoolExecutor() as executor:
 #       future = executor.submit(processor, pod)


    print('completed!')
    pod["processor_thread"] = processor_thread
    
    # Store the pod
    pods[pod_id] = pod

    expose_non_deferred_namespaces(pod)
    
    return pod

def load_ns_impl(pod, namespace):
    """Load a namespace in the pod"""
    chan = Future()
    chans = pod["chans"]
    msg_id = next_id()
    
    chans[msg_id] = chan
    
    message = {
        "op": "load-ns",
        "ns": str(namespace),
        "id": msg_id
    }
    
    write_message(pod["stdin"], message)
    
    # Wait for the result
    return chan.result()

def load_ns(pod, namespace_name):
    """Load a namespace and expose as module if deferred"""
    # Call the original load_ns function  
    result = load_ns_impl(pod, namespace_name)
    
    # If this was a deferred namespace, expose it as a module
    pod_id = pod["pod_id"]
    
    # Check if this namespace was deferred and not yet loaded
    for namespace in pod["namespaces"]:
        if (namespace["name"] == namespace_name and 
            namespace.get("defer", False) and
            (pod_id not in loaded_namespaces or 
             namespace_name not in loaded_namespaces[pod_id])):
            
            # Update the namespace with the loaded result if it's a dict
            if isinstance(result, dict) and "vars" in result:
                namespace.update(result)
            
            # Expose as module
            expose_namespace_as_module(pod, namespace)
            break
    
    return result

# Suggest by Claude. TODO. Do I need this?
def list_available_namespaces(pod_id=None):
    """List all available namespaces (loaded and deferred)"""
    if pod_id:
        pod = lookup_pod(pod_id)
        if not pod:
            print(f"Pod {pod_id} not found")
            return
        pods_to_check = {pod_id: pod}
    else:
        pods_to_check = pods
    
    for pid, pod in pods_to_check.items():
        print(f"\nPod {pid} namespaces:")
        for namespace in pod["namespaces"]:
            defer = namespace.get("defer", False)
            is_loaded = (pid in loaded_namespaces and 
                        namespace["name"] in loaded_namespaces[pid])
            
            if defer:
                status = "deferred (loaded)" if is_loaded else "deferred (not loaded)"
            else:
                status = "loaded"
            
            print(f"  {namespace['name']} - {status}")

def invoke_public(pod_id_or_pod, fn_sym, args, opts=None):
    """Invoke a public function in a pod"""
    opts = opts or {}
    
    pod_id = get_pod_id_from_spec(pod_id_or_pod)
    pod = lookup_pod(pod_id)
    
    if not pod:
        raise ValueError(f"Pod {pod_id} not found")
    
    return invoke(pod, fn_sym, args, opts)

def unload_pod(pod_id_or_pod):
    """Unload/destroy a pod"""
    return destroy(pod_id_or_pod)

# not used yet
def expose_pod_functions_locally(pod):
    """Expose pod functions in the caller's local namespace"""
    import inspect
    caller_locals = inspect.currentframe().f_back.f_locals
    
    for namespace in pod["namespaces"]:
        ns_name = namespace["name"]
        ns_vars = namespace["vars"]
        defer = namespace["defer"]
        
        print(f"📦 Exposing functions from namespace: {ns_name}")
        
        for func_name, func in ns_vars.items():
            if callable(func):  # Only add actual functions
                caller_locals[func_name] = func
                
                # Also add Python-style name
                python_name = func_name.replace('-', '_')
                if python_name != func_name:
                    caller_locals[python_name] = func
                
                print(f"  ✅ {func_name}" + (f" (also as {python_name})" if python_name != func_name else ""))


pod = load_pod(["clojure", "-M:test-pod"])

# res = invoke_public(pod["pod_id"], "pod.test-pod/add-one", [5])

import pod_test_pod as test_pod # type: ignore

res1 = test_pod.add_one(5)

print(res1)

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

print(res2)