import sys
import os
import json
import uuid
import socket
import subprocess
import threading
import time
import inspect
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Union
from concurrent.futures import Future, ThreadPoolExecutor
import bencodepy as bencode
from bencode_reader import read_message as read_bencode_stream
import transit2
from transit2 import WithMeta
import edn
from resolver import resolve
import time
import types
from patch_registry import PatchRegistry
from pod_modules import (
    expose_non_deferred_namespaces,
    unregister_pod_modules,
    namespace_to_module_name,
    loaded_namespaces,
    list_pod_modules
)

# Global state
pods = {}

_patch_registry = PatchRegistry()

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
    elif isinstance(data, str):
        return data == 'true'
    return data

def get_string(m, k):
    return bytes_to_string(m.get(k))

def get_maybe_string(m, k):
    value = m.get(k)
    return bytes_to_string(value) if value is not None else None

def get_maybe_boolean(m, k):
    value = m.get(k)
    return bytes_to_boolean(value) if value is not None else None

def python_specific(maybe_dict):
    if isinstance(maybe_dict, dict):
        return maybe_dict.get("py")
    else:
        return None

class PodError(Exception):
    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data or {}

# Transit
def get_transit_read_fn(pod):
    """Get transit read function using pod's transit instance"""
    transit_instance = pod.get("transit_instance")
    if transit_instance:
        return transit_instance.read
    else:
        # Fallback for pods without transit instance
        import transit2
        return lambda s: transit2.transit_json_read_with_metadata(s)

def get_transit_write_fn(pod):
    """Get transit write function using pod's transit instance"""
    transit_instance = pod.get("transit_instance")
    if transit_instance:
        return transit_instance.write
    else:
        # Fallback for pods without transit instance
        import transit2
        return lambda data: transit2.transit_json_write_with_metadata(data)


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
    """Convert bencode vars to Python functions with __doc__, __module__, and __meta__ support"""
    result = {}
    
    # Get the Python module name for this namespace
    module_name = namespace_to_module_name(ns_name_str)

    edn_instance = pod.get("edn_instance")
    
    for var in vars_list:
        name = get_string(var, "name")
        async_flag = get_maybe_string(var, "async")
        is_async = async_flag == "true" if async_flag else False
        code = get_maybe_string(var, "code")
        meta_str = get_maybe_string(var, "meta")
        arg_meta = get_maybe_boolean(var, "arg-meta")
        
        # Parse metadata to extract doc string and full metadata
        doc_string = None
        var_meta = {}
        if meta_str:
            try:
                if edn_instance:
                    var_meta = edn_instance.read(meta_str)
                    doc_string = var_meta.get("doc")
                else:
                    # Fallback for non-EDN formats - try basic parsing
                    import ast
                    try:
                        var_meta = ast.literal_eval(meta_str)
                        doc_string = var_meta.get("doc")
                    except:
                        var_meta = {}
            except Exception as e:
                print(f"Warning: Could not parse metadata for {name}: {e}", file=sys.stderr)
                var_meta = {}
        
        if code:
            # If code is provided, use it directly
            result[name] = code
        else:
            # Create a function that invokes the pod
            def create_invoker(var_name, is_async, arg_meta, doc, mod_name, metadata):
                def invoker(*args, _is_async=is_async, _arg_meta=arg_meta):
                    opts_dict = {"async": _is_async, "arg_meta": _arg_meta}
                    return invoke(pod, f"{ns_name_str}/{var_name}", list(args), opts_dict)
                
                # Set standard Python attributes
                invoker.__name__ = var_name
                invoker.__module__ = mod_name
                if doc:
                    invoker.__doc__ = doc
                
                # Set custom metadata catch-all
                invoker.__meta__ = metadata
                
                return invoker
            
            result[name] = create_invoker(name, is_async, arg_meta, doc_string, module_name, var_meta)
    
    return result

def invoke(pod, pod_var, args, opts=None):
    """Invoke a function in the pod"""
    opts = opts or {}
    handlers = opts.get("handlers")
    stream = pod["stdin"]
    format_type = pod["format"]
    chans = pod["chans"]
    arg_meta = opts.get("arg_meta", False)

    # unwrap any metadata when arg_meta is not True
    processed_args = []
    if not arg_meta:
        for arg in args:
            if isinstance(arg, WithMeta):
                processed_args.append(arg.value)
            else:
                processed_args.append(arg)
    else:
        processed_args = args
    
    # Determine write function based on format
    if format_type == "edn":
        edn_instance = pod.get("edn_instance")
        write_fn = edn_instance.write
    elif format_type == "json":
        write_fn = json.dumps
    elif format_type == "transit+json":
        write_fn = get_transit_write_fn(pod)
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
        "args": write_fn(processed_args)
    }
    
    write_message(stream, message)
    
    if not handlers:
        result = chan.result()  # This will block until result is available
        
        # STEP 1: Apply result transform patch if it exists (BEFORE function patches)
        pod_id = pod["pod_id"]
        transform_function = _patch_registry.get_result_transform_patch(pod_id, str(pod_var))
        if transform_function:
            try:
                result = transform_function(result)
            except Exception as e:
                warn(f"Result transform failed for {pod_var}: {e}")
                # Keep original result on error
        
        # STEP 2: Handle client-side code execution (code patches)
        python_code = None  # Initialize python_code
        
        if isinstance(result, dict) and "code" in result:
            code_value = result["code"]
            
            # Check for Python-specific code
            python_code = python_specific(code_value) if isinstance(code_value, dict) else code_value
            
            # Apply code patches if they exist
            patched_code = _patch_registry.get_code_patch(pod_id, str(pod_var))
            
            if patched_code:
                # Code patches completely replace the pod function
                try:
                    # Execute the patch code with access to original args
                    # Create execution environment with args available
                    exec_globals = {
                        '__builtins__': __builtins__,
                        'args': args,  # Make args available to the code
                    }
                    exec_locals = {}
                    
                    # Execute the patched code
                    exec(patched_code, exec_globals, exec_locals)
                    
                    # Look for a return value in locals
                    if 'result' in exec_locals:
                        result = exec_locals['result']
                    elif len(exec_locals) == 1:
                        # If only one variable was created, use it as result
                        result = list(exec_locals.values())[0]
                    else:
                        # Return all non-private variables
                        result = {k: v for k, v in exec_locals.items() if not k.startswith('_')}
                    
                    if isinstance(result, Exception):
                        raise result
                    return result
                except Exception as e:
                    warn(f"Code patch failed for {pod_var}: {e}")
                    # Fall back to original python_code if patch fails
        
        # STEP 3: Execute original python code if no function patch was applied
        if python_code:
            print(f"🔍 Executing Python code: {repr(python_code)}") 
            try:
                # Find the first frame outside python_pods module
                current_frame = inspect.currentframe()
                target_frame = current_frame.f_back

                # Walk up the call stack until we find a frame not in python_pods
                while target_frame:
                    frame_file = target_frame.f_globals.get('__file__', '')
                    frame_name = target_frame.f_globals.get('__name__', '')
                    
                    # Check if this frame is from the test file (more specific check)
                    if ('test_json.py' in frame_file or 
                        frame_name == '__main__' or 
                        ('python_pods' not in frame_file and frame_file)):
                        break
                    target_frame = target_frame.f_back

                if target_frame:
                    caller_globals = target_frame.f_globals
                else:
                    # Fallback to immediate caller if we can't find a suitable frame
                    warn("Could not find target frame for code execution, using immediate caller")
                    caller_globals = current_frame.f_back.f_globals

                # Execute in caller's environment so variables/functions persist
                exec(python_code, caller_globals)
                
                # For the return value, prefer calculated values over functions/modules
                exec_locals = {}
                exec(python_code, caller_globals, exec_locals)
                
                non_private = {k: v for k, v in exec_locals.items() if not k.startswith('_')}
                if len(non_private) == 1:
                    result = list(non_private.values())[0]
                elif non_private:
                    # Prefer non-function, non-module values (like calculated results)
                    values_only = {k: v for k, v in non_private.items() 
                                if not callable(v) and not hasattr(v, '__file__')}
                    if len(values_only) == 1:
                        result = list(values_only.values())[0]
                    else:
                        result = non_private  # Return everything if no clear preference
                # If no results, keep original result
                    
            except Exception as e:
                warn(f"Failed to execute client code: {e}")
                # Keep original result on error
        
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
        edn_instance = pod.get("edn_instance")
        def read_fn(s):
            try:
                return edn_instance.read(s)
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
    elif format_type == "transit+json":
        read_fn_with_transforms = get_transit_read_fn(pod)
        def read_fn(s):
            try:
                return read_fn_with_transforms(s)
            except Exception as e:
                print(f"Cannot read Transit JSON: {repr(s)}", file=sys.stderr)
                raise e
    else:
        read_fn = str
    
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

        chans = pod["chans"]
        for msg_id, chan in chans.items():
            if isinstance(chan, Future) and not chan.done():
                chan.set_exception(PodError(f"Pod process failed: {e}"))
        
        # Clear the channels
        chans.clear()

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

def describe_to_metadata(describe_reply, resolve_readers=False):
    """Extract metadata from describe reply"""
    format_bytes = describe_reply.get("format")
    format_str = bytes_to_string(format_bytes) if format_bytes else "edn"
    format_type = format_str
    
    ops = describe_to_ops(describe_reply)
    
    readers = {}
    if format_type == "edn" and resolve_readers:
        readers = describe_reply.get("readers")
    
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
    resolve_readers = final_opts.get("resolve", False)
    
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
    metadata = describe_to_metadata(reply, resolve_readers)
    format_type = metadata["format"]
    ops = metadata["ops"]
    readers = metadata["readers"]

    # Get pod namespaces FIRST
    pod_namespaces_raw = reply.get("namespaces", [])

    # Determine pod_id for patch lookup
    potential_pod_id = None
    if isinstance(pod_spec, str) and '/' in pod_spec:
        # For registry pods, use the pod spec as ID
        potential_pod_id = pod_spec
    elif pod_namespaces_raw:
        # For local pods, use first namespace (following babashka logic)
        first_ns = pod_namespaces_raw[0]
        potential_pod_id = get_string(first_ns, "name")

    edn_instance = None
    if format_type == "edn":
        # Priority: patches > pod-provided python readers > empty dict
        if potential_pod_id:
            patched_readers = _patch_registry.get_edn_reader_patches(potential_pod_id)
            if patched_readers:
                edn_instance = edn.Edn(patched_readers)
            else:
                pod_readers = python_specific(readers) or {}
                edn_instance = edn.Edn(pod_readers)
        else:
            pod_readers = python_specific(readers) or {}
            edn_instance = edn.Edn(pod_readers)

    transit_instance = None
    if format_type == "transit+json":
        import transit2
        transit_instance = transit2.Transit(
            pod_readers=python_specific(readers),
            pod_writers=None
        )
    
    # Use the potential_pod_id we already determined, or fall back to UUID
    pod_id = potential_pod_id or next_id()
    
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
        "pod_id": pod_id,
        "edn_instance": edn_instance,
        "transit_instance": transit_instance,
        "socket": sock
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

def add_transit_read_handler(pod_id, tag, handler_class):
    """Add a transit read handler class for a specific tag
    
    Args:
        tag (str): The transit tag to handle
        handler_class: A class with a static 'from_rep' method
    
    Example:
        class MyTypeReadHandler:
            @staticmethod
            def from_rep(rep):
                return MyType(rep)
        
        add_transit_read_handler("my-type", MyTypeReadHandler)
    """
    pod = lookup_pod(pod_id)
    if not pod:
        raise RuntimeError(f"Pod {pod_id} not found")
    
    transit_instance = pod.get("transit_instance")
    if not transit_instance:
        raise RuntimeError("Pod does not have a transit instance (not using transit+json format?)")
    
    transit_instance.add_read_handler(tag, handler_class)
    return None

def add_transit_write_handler(pod_id, classes, handler_class):
    """Add a transit write handler class for specific classes
    
    Args:
        classes: A class or list of classes to handle
        handler_class: A class with static 'tag' and 'rep' methods
    
    Example:
        class MyTypeWriteHandler:
            @staticmethod
            def tag(obj):
                return "my-type"
            
            @staticmethod
            def rep(obj):
                return obj.serialize()
        
        add_transit_write_handler([MyType], MyTypeWriteHandler)
    """    
    pod = lookup_pod(pod_id)
    if not pod:
        raise RuntimeError(f"Pod {pod_id} not found")
    
    transit_instance = pod.get("transit_instance")
    if not transit_instance:
        raise RuntimeError("Pod does not have a transit instance (not using transit+json format?)")
    
    transit_instance.add_write_handler(classes, handler_class)
    return None

def set_default_transit_write_handler(pod_id, handler_class):
    """Set a default transit write handler class for unregistered types
    
    Args:
        handler_class: A class with static 'tag' and 'rep' methods
    
    Example:
        class DefaultWriteHandler:
            @staticmethod
            def tag(obj):
                return type(obj).__name__
            
            @staticmethod
            def rep(obj):
                return str(obj)
        
        set_default_transit_write_handler(DefaultWriteHandler)
    """
    pod = lookup_pod(pod_id)
    if not pod:
        raise RuntimeError(f"Pod {pod_id} not found")
    
    transit_instance = pod.get("transit_instance")
    if not transit_instance:
        raise RuntimeError("Pod does not have a transit instance (not using transit+json format?)")
    
    transit_instance.set_default_write_handler(handler_class)
    return None

def register_code_patch(pod_id, function_name, python_code):
    """Register a code patch with arbitrary Python code for a specific pod and function"""
    _patch_registry.register_code_patch(pod_id, function_name, python_code)

def register_edn_reader_patch(pod_id, tag, reader_function):
    """Register an EDN reader patch for a specific pod and tag"""
    _patch_registry.register_edn_reader_patch(pod_id, tag, reader_function)

def register_result_transform_patch(pod_id, function_name, transform_function):
    """Register a result transform patch to convert pod results to Python-friendly forms"""
    _patch_registry.register_result_transform_patch(pod_id, function_name, transform_function)

def clear_patches(pod_id=None):
    """Clear registered patches"""
    _patch_registry.clear_patches(pod_id)

def list_patches(pod_id=None):
    """List all registered patches"""
    _patch_registry.list_patches(pod_id)
