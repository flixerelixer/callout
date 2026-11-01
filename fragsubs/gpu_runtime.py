"""NVIDIA GPU runtime (cuBLAS + cuDNN) for Whisper.

The libraries are about 1.2 GB, so they are not bundled with the app.
Instead FragSubs downloads NVIDIA's official wheels from PyPI on first use,
verifies their SHA-256, and extracts just the DLLs into the app data folder.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import paths

log = logging.getLogger(__name__)

# cuBLAS 12.8+ and cuDNN 9.7+ are needed for RTX 50-series (Blackwell).
# cuDNN must match the cudnn64_9.dll loader that ships inside ctranslate2.
PACKAGES = [
    ("nvidia-cublas-cu12", "12.9.1.4", "nvidia/cublas/bin/"),
    ("nvidia-cudnn-cu12", "9.10.2.21", "nvidia/cudnn/bin/"),
]
REQUIRED_DLLS = [
    "cublas64_12.dll",
    "cublasLt64_12.dll",
    "cudnn_graph64_9.dll",
    "cudnn_ops64_9.dll",
    "cudnn_cnn64_9.dll",
]
# Loaded up front so ctranslate2 finds them regardless of DLL search rules.
_PRELOAD_ORDER = [
    "cublasLt64_12.dll",
    "cublas64_12.dll",
    "cudnn_graph64_9.dll",
    "cudnn_engines_precompiled64_9.dll",
    "cudnn_heuristic64_9.dll",
    "cudnn_ops64_9.dll",
    "cudnn_cnn64_9.dll",
]
MARKER = "runtime.json"

_activated = False
_dll_handles: list = []


class Cancelled(Exception):
    pass


def runtime_dir() -> Path:
    return paths.gpu_runtime_dir()


def _wanted_versions() -> dict[str, str]:
    return {name: version for name, version, _ in PACKAGES}


def is_installed() -> bool:
    d = runtime_dir()
    marker = d / MARKER
    if not marker.exists():
        return False
    try:
        if json.loads(marker.read_text()) != _wanted_versions():
            return False
    except (OSError, ValueError):
        return False
    return all((d / dll).exists() for dll in REQUIRED_DLLS)


def activate() -> bool:
    """Make the downloaded DLLs loadable. Safe to call more than once."""
    global _activated
    if _activated:
        return True
    if sys.platform != "win32" or not is_installed():
        return False
    d = str(runtime_dir())
    try:
        _dll_handles.append(os.add_dll_directory(d))
    except OSError as exc:
        log.warning("add_dll_directory failed: %s", exc)
    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    import ctypes

    for name in _PRELOAD_ORDER:
        path = os.path.join(d, name)
        if os.path.exists(path):
            try:
                _dll_handles.append(ctypes.WinDLL(path))
            except OSError as exc:
                log.warning("Could not preload %s: %s", name, exc)
    _activated = True
    log.info("GPU runtime activated from %s", d)
    return True


def cuda_device_count() -> int:
    """Number of NVIDIA GPUs the driver exposes (0 if none or no driver)."""
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception as exc:  # noqa: BLE001
        log.info("No CUDA device: %s", exc)
        return 0


def gpu_name() -> str:
    """Best-effort GPU name for display."""
    if sys.platform != "win32":
        return ""
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
    except Exception:  # noqa: BLE001
        return ""


def _wheel_info(package: str, version: str) -> dict:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "FragSubs"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    for f in data.get("urls", []):
        if f.get("filename", "").endswith("win_amd64.whl"):
            return {"url": f["url"], "size": int(f["size"]), "sha256": f["digests"]["sha256"],
                    "filename": f["filename"]}
    raise RuntimeError(f"No Windows wheel found for {package} {version}")


def download(progress: Callable[[int, int, str], None] | None = None,
             cancel: threading.Event | None = None) -> None:
    """Download and install the runtime. progress(done_bytes, total_bytes, label)."""
    progress = progress or (lambda *_: None)
    cancel = cancel or threading.Event()
    infos = [(name, version, prefix, _wheel_info(name, version)) for name, version, prefix in PACKAGES]
    total = sum(info["size"] for *_, info in infos)
    done = 0
    target = runtime_dir()
    staging = Path(tempfile.mkdtemp(prefix="gpu-runtime-", dir=paths.app_data_dir()))
    try:
        for name, _version, prefix, info in infos:
            label = name.replace("nvidia-", "").replace("-cu12", "")
            wheel_path = staging / info["filename"]
            sha = hashlib.sha256()
            req = urllib.request.Request(info["url"], headers={"User-Agent": "FragSubs"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(wheel_path, "wb") as out:
                while True:
                    if cancel.is_set():
                        raise Cancelled()
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    sha.update(block)
                    done += len(block)
                    progress(done, total, f"Downloading {label}")
            if sha.hexdigest() != info["sha256"]:
                raise RuntimeError(f"Checksum mismatch for {info['filename']}")
            progress(done, total, f"Unpacking {label}")
            with zipfile.ZipFile(wheel_path) as zf:
                for member in zf.namelist():
                    if member.startswith(prefix) and member.lower().endswith(".dll"):
                        dest = staging / "dlls" / Path(member).name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
            wheel_path.unlink(missing_ok=True)
        (staging / "dlls" / MARKER).write_text(json.dumps(_wanted_versions()))
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(staging / "dlls"), str(target))
        progress(total, total, "GPU runtime installed")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
