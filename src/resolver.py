import os
import re
import tempfile
import hashlib
import requests
import tarfile
import zipfile
import gzip
import platform
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse
from subprocess import run, CalledProcessError
import edn as edn

# globals to hold the manifest & os info. using like Clojure atoms
manifest = None
os_info = None

# Normalize architecture name
def normalize_arch(arch):
    return {
        "amd64": "x86_64",
        "arm64": "aarch64"
    }.get(arch, arch)
 
# Normalize operating system name
def normalize_os(os_name):
    return "Mac OS X" if os_name == "Darwin" else os_name

# New function to get os & arch info
def get_system_info():
    return {
        "sysname": platform.system(),         # OS name: 'Linux', 'Darwin', 'Windows'
        "machine": platform.machine()         # Architecture: 'x86_64', 'arm64', etc.
    }

# Get OS details
def get_os():
    sys_info = get_system_info()

    global os_info
    os_info = {
        "os/name": normalize_os(os.getenv("BABASHKA_PODS_OS_NAME", sys_info['sysname'])),
        "os/arch": normalize_arch(os.getenv("BABASHKA_PODS_OS_ARCH", sys_info['machine']))
    }
    return os_info

# Print warnings to stderr
def warn(*strs):
    print(*strs, file=sys.stderr)

# Match artifacts
def match_artifacts(package, arch=None):
    os_info = get_os()
    arch = arch or os_info["os/arch"]
    artifacts = package.get("pod/artifacts", [])
    res = [
        artifact for artifact in artifacts
        if re.match(artifact["os/name"], os_info["os/name"])
        and re.match(normalize_arch(artifact["os/arch"]), arch)
    ]
    if not res:
        if os_info["os/name"] == "Mac OS X" and os_info["os/arch"] == "aarch64":
            return match_artifacts(package, "x86_64")
        raise ValueError(f"No executable found for pod {package['pod/name']} ({package['pod/version']}) and OS {os_info['os/name']}/{os_info['os/arch']}")
    return res

# Unzip a file
def unzip(zip_file, destination_dir, verbose=False):
    if verbose:
        warn(f"Unzipping {zip_file} to {destination_dir}")
    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
        zip_ref.extractall(destination_dir)

# Un-tar-gz a file
# tarfile can't un-tar-gz a binary in a tar.gz file. need to do in two steps
def untar_file(tar_path, destination_dir, verbose=False):
    if verbose:
        warn(f"Untar-ing {tar_path} to {destination_dir}")    
    try:
        with tarfile.open(tar_path, 'r:*') as tar:
            tar.extractall(destination_dir,filter='fully_trusted')
    except Exception as e:
        raise ValueError(f"Error extracting tar file: {e}")

def gunzip_file(tgz_path, destination_file, verbose=False):
    if verbose:
        warn(f"Ungzipping {tgz_path} to tar file {destination_file}")    
    
    try:
        with gzip.open(tgz_path, 'rb') as f_in, open(destination_file, 'wb') as f_out:
            f_out.write(f_in.read())
        return True
    except Exception as e:
        raise ValueError(f"Error extracting tgz file: {e}")

def un_tgz(zip_file, destination_dir, verbose=False):
    tmp_file = destination_dir / 'tmp.tar'
    if gunzip_file(zip_file, tmp_file, verbose):
        untar_file(tmp_file, destination_dir, verbose)
        if verbose:
            warn(f"Deleting intermediate tar file {tmp_file}")
        tmp_file.unlink()
    else:
        return False

# Make files executable
def make_executable(dest_dir, executables, verbose=False):
    for executable in executables:
        executable_path = os.path.join(dest_dir, executable)
        if verbose:
            warn(f"Making {executable_path} executable.")
        os.chmod(executable_path, 0o755)

# Download a file
def download(source, dest, verbose=False):
    if verbose:
        warn(f"Downloading {source} to {dest}")
    # create directories in path as needed
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    # download and write
    response = requests.get(source, stream=True)
    response.raise_for_status()
    with open(dest, 'wb') as f:
         for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

# Get repository directory
def repo_dir():
    pods_dir = os.getenv("BABASHKA_PODS_DIR")
    if pods_dir:
        return Path(pods_dir)
    else:
        data_home = os.getenv("XDG_DATA_HOME", Path.home())
        return Path(data_home) / ".babashka" / "pods" / "repository"

# Generate GitHub URL
def github_url(qsym, version):
    return f"https://raw.githubusercontent.com/babashka/pod-registry/master/manifests/{qsym}/{version}/manifest.edn"

# Get pod manifest
def pod_manifest(qsym, version, force=False):
    manifest_path = repo_dir() / qsym / version / "manifest.edn"
    if not force and manifest_path.exists():
        with open(manifest_path, "r") as f:
            return f.read()
    else:
        download(github_url(qsym, version), manifest_path, verbose=False)
        with open(manifest_path, "r") as f:
            return f.read()

def to_snake_case(s):
    return s.lower().replace(' ', '_')

def cache_dir():
    pods_dir = os.getenv('BABASHKA_PODS_DIR')
    if pods_dir:
        base_file = pods_dir
    else:
        xdg_cache = os.getenv('XDG_CACHE_HOME')
        home = Path.home()
        base_file = Path(xdg_cache) if xdg_cache else home / ".babashka" / "pods"

    path_os = to_snake_case(os_info['os/name'])
    os_arch = os_info['os/arch']

    return base_file / "repository" / manifest['pod/name'] / manifest ['pod/version'] / path_os / os_arch   
        
def data_dir():
    path_os = to_snake_case(os_info['os/name'])
    os_arch = os_info['os/arch']    
    return repo_dir() / manifest['pod/name'] / manifest ['pod/version'] / path_os / os_arch
    

# Compute SHA-256 of a file
def sha256(file_path):
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha.update(byte_block)
    return sha.hexdigest()

# Resolve pod
def resolve(qsym, version, force=False):
    if not isinstance(version, str):
        raise ValueError("Version must be provided for resolving from pod registry!")
    
    global manifest
    manifest = edn.from_edn(pod_manifest(qsym, version, force))
    artifacts = match_artifacts(manifest)
    cdir = cache_dir()
    ddir = data_dir()
    execs = []
    
    for artifact in artifacts:
        url = artifact["artifact/url"]
        file_name = url.split("/")[-1]
        cache_file = cdir / file_name
        executable = ddir / artifact["artifact/executable"]
        
        if force or not executable.exists():
            warn(f"Downloading pod {qsym} ({version})")
            download(url, cache_file, verbose=False)
            if "artifact/hash" in artifact:
                expected_sha = artifact["artifact/hash"]
                if sha256(cache_file) != expected_sha:
                    raise ValueError(f"Wrong SHA-256 for file {cache_file}")
            if file_name.endswith(".zip"):
                unzip(cache_file, ddir, verbose=False)
            elif file_name.endswith(".tgz") or file_name.endswith(".tar.gz"):
                un_tgz(cache_file, ddir, verbose=False)
            cache_file.unlink()
            make_executable(ddir, [artifact["artifact/executable"]], verbose=False)
            warn(f"Successfully installed pod {qsym} ({version})")
        execs.append(str(executable))
        
    return {
        "executable": execs[0],
        "options": manifest.get("pod/options", None)
    }
