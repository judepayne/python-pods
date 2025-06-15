"""
Patch Registry for Python Pods

Provides three types of patches:
1. Function Patches - Replace pod functions that return code
2. EDN Reader Patches - Handle custom EDN tags during parsing (EDN format only)
3. Result Transform Patches - Convert pod results to Python-friendly forms
"""

from typing import Dict, Any, Optional, Callable


def warn(*args):
    """Print warning to stderr"""
    import sys
    print(*args, file=sys.stderr)


class PatchRegistry:
    """Registry for managing all types of patches for pods"""
    
    def __init__(self):
        self.code_patches = {}          # {pod_id: {function_name: function}}
        self.edn_reader_patches = {}        # {pod_id: {tag: function}}
        self.result_transform_patches = {}  # {pod_id: {function_name: function}}
    
    def register_code_patch(self, pod_id: str, function_name: str, python_code: str):
        """Register a code patch with arbitrary Python code for a specific pod and function
        
        Code patches completely replace pod functions with custom Python code.
        
        Args:
            pod_id: Pod identifier (e.g., 'org.babashka/instaparse')
            function_name: Full function name (e.g., 'pod.babashka.instaparse/parse')
            python_code: Python code string to execute instead of pod function
        """
        if not isinstance(python_code, str):
            raise ValueError("python_code must be a string")
        
        if pod_id not in self.code_patches:
            self.code_patches[pod_id] = {}
        
        self.code_patches[pod_id][function_name] = python_code
        print(f"Registered code patch: {pod_id} -> {function_name}")
    
    def register_edn_reader_patch(self, pod_id: str, tag: str, reader_function: Callable):
        """Register an EDN reader patch for a specific pod and tag
        
        EDN reader patches handle custom EDN tags during parsing.
        Only applies to pods using EDN format.
        
        Args:
            pod_id: Pod identifier (e.g., 'org.babashka/instaparse')
            tag: EDN tag (e.g., 'person', 'myapp/data')
            reader_function: Python function to parse the tagged value
        """
        if not callable(reader_function):
            raise ValueError("reader_function must be callable")
        
        if pod_id not in self.edn_reader_patches:
            self.edn_reader_patches[pod_id] = {}
        
        self.edn_reader_patches[pod_id][tag] = reader_function
        print(f"Registered EDN reader patch: {pod_id} -> {tag}")
    
    def register_result_transform_patch(self, pod_id: str, function_name: str, transform_function: Callable):
        """Register a result transform patch for a specific pod function
        
        Result transform patches convert complex pod results (like WithMeta objects,
        transit keywords) into Python-friendly data structures.
        
        Args:
            pod_id: Pod identifier (e.g., 'org.babashka/instaparse')
            function_name: Full function name (e.g., 'pod.babashka.instaparse/parse')
            transform_function: Function that takes raw result and returns cleaned result
        """
        if not callable(transform_function):
            raise ValueError("transform_function must be callable")
        
        if pod_id not in self.result_transform_patches:
            self.result_transform_patches[pod_id] = {}
        
        self.result_transform_patches[pod_id][function_name] = transform_function
        print(f"Registered result transform patch: {pod_id} -> {function_name}")
    
    def get_code_patch(self, pod_id: str, function_name: str) -> Optional[str]:
        """Get a code patch if it exists"""
        return self.code_patches.get(pod_id, {}).get(function_name)
    
    def get_edn_reader_patches(self, pod_id: str) -> Dict[str, Callable]:
        """Get all EDN reader patches for a pod"""
        return self.edn_reader_patches.get(pod_id, {})
    
    def get_result_transform_patch(self, pod_id: str, function_name: str) -> Optional[Callable]:
        """Get a result transform patch if it exists"""
        return self.result_transform_patches.get(pod_id, {}).get(function_name)
    
    def clear_patches(self, pod_id: Optional[str] = None):
        """Clear patches for a pod or all pods"""
        if pod_id:
            removed_code = len(self.code_patches.get(pod_id, {}))
            removed_edn_readers = len(self.edn_reader_patches.get(pod_id, {}))
            removed_transforms = len(self.result_transform_patches.get(pod_id, {}))
            
            self.code_patches.pop(pod_id, None)  # Changed from function_patches
            self.edn_reader_patches.pop(pod_id, None)
            self.result_transform_patches.pop(pod_id, None)
            
            total_removed = removed_code + removed_edn_readers + removed_transforms
            if total_removed > 0:
                print(f"🧹 Cleared {removed_code} code, {removed_edn_readers} EDN reader, "
                      f"and {removed_transforms} result transform patches for {pod_id}")
        else:
            total_code = sum(len(patches) for patches in self.code_patches.values())
            total_edn_readers = sum(len(patches) for patches in self.edn_reader_patches.values())
            total_transforms = sum(len(patches) for patches in self.result_transform_patches.values())
            
            self.code_patches.clear()  # Changed from function_patches
            self.edn_reader_patches.clear()
            self.result_transform_patches.clear()
            
            total_cleared = total_code + total_edn_readers + total_transforms
            if total_cleared > 0:
                print(f"🧹 Cleared all patches: {total_code} code, {total_edn_readers} EDN reader, "
                      f"and {total_transforms} result transform patches")
    
    def list_patches(self, pod_id: Optional[str] = None):
        """List all registered patches"""
        if pod_id:
            pods_to_check = {pod_id} if (pod_id in self.code_patches or 
                                       pod_id in self.edn_reader_patches or 
                                       pod_id in self.result_transform_patches) else set()
        else:
            pods_to_check = (set(self.code_patches.keys()) | 
                           set(self.edn_reader_patches.keys()) | 
                           set(self.result_transform_patches.keys()))
        
        if not pods_to_check:
            print("No patches registered")
            return
        
        for pid in sorted(pods_to_check):
            code_patches = self.code_patches.get(pid, {})
            edn_reader_patches = self.edn_reader_patches.get(pid, {})
            result_transform_patches = self.result_transform_patches.get(pid, {})
            
            if code_patches or edn_reader_patches or result_transform_patches:
                print(f"\nPod: {pid}")
                
                if code_patches:
                    print("  Code patches (replace pod functions with Python code):")
                    for func_name in sorted(code_patches.keys()):
                        print(f"    - {func_name}")
                
                if edn_reader_patches:
                    print("  EDN reader patches (handle custom tags):")
                    for tag in sorted(edn_reader_patches.keys()):
                        print(f"    - {tag}")
                
                if result_transform_patches:
                    print("  Result transform patches (clean pod results):")
                    for func_name in sorted(result_transform_patches.keys()):
                        print(f"    - {func_name}")
    
    def _normalize_pod_name(self, pod_spec):
        """Normalize pod specification to consistent pod_id format"""
        if isinstance(pod_spec, str):
            return pod_spec
        elif isinstance(pod_spec, dict):
            return pod_spec.get("pod_id", str(pod_spec))
        else:
            return str(pod_spec)
