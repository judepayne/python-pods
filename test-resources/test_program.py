import subprocess
import os
import signal

fmt = os.getenv("BABASHKA_POD_TEST_FORMAT") or "json"
socket = os.getenv("BABASHKA_POD_TEST_SOCKET")

cmd = ["clojure", "-M:test-pod"]
if fmt == "json":
    cmd.append("--json")
if fmt == "transit+json":
    cmd.append("--transit+json")


process = subprocess.Popen(cmd)
pid = process.pid
print(f"Pod process ID: {pid}")


def check_process_exists(pid):
    """Check if a process with given PID exists"""
    try:
        # Send signal 0 - doesn't actually send a signal, just checks if process exists
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def get_basic_process_info(pid):
    if check_process_exists(pid):
        print(f"Process {pid} is running")
        
        # Try to get some basic info from /proc (Linux/Mac)
        try:
            with open(f"/proc/{pid}/stat", 'r') as f:
                stat_data = f.read().split()
                print(f"Process name: {stat_data[1]}")
                print(f"State: {stat_data[2]}")
        except FileNotFoundError:
            print("Process exists but can't read /proc info (maybe not Linux)")
    else:
        print(f"Process {pid} is not running")

