"""Self-update from GitHub Releases.

On start, Callout asks GitHub for the latest release. If it is newer, the
release zip is downloaded and unpacked next to the user's data, then a small
PowerShell script waits for Callout to exit, swaps in the new program files
(keeping the old ones until the copy succeeds) and starts the new version.

Settings, models and the GPU runtime live in %LOCALAPPDATA%\\Callout and are
never touched by an update.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import REPO_URL, __version__, paths

log = logging.getLogger(__name__)

API_LATEST = REPO_URL.replace("https://github.com/", "https://api.github.com/repos/") + "/releases/latest"
RELEASES_PAGE = REPO_URL + "/releases"
ASSET_PATTERN = re.compile(r"^Callout-v?[\d.]+-win64\.zip$", re.IGNORECASE)
EXE_NAME = "Callout.exe"


class Cancelled(Exception):
    pass


@dataclass
class Release:
    version: str
    url: str
    size: int
    sha256: str | None
    page: str


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.1.10' -> (0, 1, 10). Anything after the numbers is ignored."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(remote: str, local: str = __version__) -> bool:
    new, cur = parse_version(remote), parse_version(local)
    if not new:
        return False
    width = max(len(new), len(cur))
    return new + (0,) * (width - len(new)) > cur + (0,) * (width - len(cur))


def release_from_json(data: dict) -> Release | None:
    """Pick the Windows zip out of a GitHub 'latest release' response."""
    if data.get("draft") or data.get("prerelease"):
        return None
    version = str(data.get("tag_name", "")).lstrip("v")
    for asset in data.get("assets", []):
        if ASSET_PATTERN.match(asset.get("name", "")):
            digest = asset.get("digest") or ""
            sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
            return Release(version, asset["browser_download_url"], int(asset.get("size", 0)), sha,
                           data.get("html_url") or RELEASES_PAGE)
    return None


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_self_update() -> tuple[bool, str]:
    """Whether this copy can replace itself, and why not if it can't."""
    if sys.platform != "win32":
        return False, "Automatic updates only work on Windows."
    if not getattr(sys, "frozen", False):
        return False, "Running from source; update with git pull."
    target = install_dir()
    if not (target / "_internal").is_dir():
        return False, "Unexpected install layout."
    probe = target / ".callout-write-test"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        return False, f"Callout can't write to {target}. Move the Callout folder somewhere you own, like Documents."
    return True, ""


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Callout/{__version__}",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def check() -> Release | None:
    """The latest release if it is newer than this version, else None."""
    try:
        data = _get_json(API_LATEST)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # no releases published yet
            return None
        raise
    release = release_from_json(data)
    if release and is_newer(release.version):
        return release
    return None


def updates_dir() -> Path:
    d = paths.app_data_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(release: Release, progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None) -> Path:
    """Download and unpack the release. Returns the folder holding the new Callout.exe."""
    progress = progress or (lambda *_: None)
    cancel = cancel or threading.Event()
    root = updates_dir()
    # Clear out older attempts.
    for old in root.iterdir():
        if old.name != "update.log":
            shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)

    zip_path = root / f"Callout-{release.version}.zip"
    sha = hashlib.sha256()
    done = 0
    req = urllib.request.Request(release.url, headers={"User-Agent": f"Callout/{__version__}"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
        total = int(resp.headers.get("Content-Length") or release.size or 0)
        while True:
            if cancel.is_set():
                raise Cancelled()
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
            sha.update(block)
            done += len(block)
            progress(done, total)
    if release.size and done != release.size:
        raise RuntimeError(f"Download incomplete ({done} of {release.size} bytes)")
    if release.sha256 and sha.hexdigest() != release.sha256.lower():
        raise RuntimeError("Downloaded update failed its checksum")

    staging = root / f"v{release.version}"
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            dest = (staging / member).resolve()
            if not str(dest).startswith(str(staging.resolve())):
                raise RuntimeError("Unsafe path in update zip")
        zf.extractall(staging)
    zip_path.unlink(missing_ok=True)

    for exe in staging.rglob(EXE_NAME):
        if (exe.parent / "_internal").is_dir():
            return exe.parent
    raise RuntimeError("The update zip doesn't contain Callout.exe")


# Swaps program files once Callout has exited. Keeps a backup until the new
# files are in place and restores it if anything fails.
UPDATE_SCRIPT = r"""
param(
    [int]$AppPid,
    [string]$Install,
    [string]$New,
    [string]$Log,
    [switch]$NoRestart
)
$ErrorActionPreference = "Stop"
Start-Transcript -Path $Log -Force | Out-Null
$internal = Join-Path $Install "_internal"
$backup = Join-Path $Install "_internal.old"
$exe = Join-Path $Install "Callout.exe"
$exeBackup = Join-Path $Install "Callout.exe.old"

function Retry([scriptblock]$Action) {
    for ($i = 1; $i -le 10; $i++) {
        try { & $Action; return } catch { if ($i -eq 10) { throw }; Start-Sleep -Milliseconds 500 }
    }
}

try {
    Write-Output "Waiting for Callout (pid $AppPid) to exit"
    Wait-Process -Id $AppPid -Timeout 60 -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500

    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    if (Test-Path $exeBackup) { Remove-Item $exeBackup -Force }
    Retry { Rename-Item $internal "_internal.old" }
    Retry { Copy-Item $exe $exeBackup -Force }
    try {
        Retry { Copy-Item (Join-Path $New "_internal") $internal -Recurse -Force }
        Retry { Copy-Item (Join-Path $New "Callout.exe") $exe -Force }
    } catch {
        Write-Output "Update failed, restoring the previous version: $_"
        if (Test-Path $internal) { Remove-Item $internal -Recurse -Force }
        Rename-Item $backup "_internal"
        Copy-Item $exeBackup $exe -Force
        throw
    }
    Remove-Item $backup -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $exeBackup -Force -ErrorAction SilentlyContinue
    Remove-Item (Split-Path $New -Parent) -Recurse -Force -ErrorAction SilentlyContinue
    Write-Output "Update installed"
} catch {
    Write-Output "Error: $_"
} finally {
    if (-not $NoRestart) { Start-Process -FilePath $exe }
    Stop-Transcript | Out-Null
}
"""


def write_script() -> Path:
    path = updates_dir() / "apply-update.ps1"
    path.write_text(UPDATE_SCRIPT, encoding="utf-8")
    return path


def launch_installer(new_dir: Path) -> None:
    """Start the swap script; the caller must quit right after."""
    script = write_script()
    args = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden", "-File", str(script),
        "-AppPid", str(os.getpid()),
        "-Install", str(install_dir()),
        "-New", str(new_dir),
        "-Log", str(updates_dir() / "update.log"),
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log.info("Launching updater: %s", " ".join(args))
    subprocess.Popen(args, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
