"""Where FragSubs keeps its settings, models, GPU runtime and logs."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from . import APP_NAME

log = logging.getLogger(__name__)

# The app was called Callout before 0.2.0; its folder is moved over once.
OLD_NAMES = ("Callout",)
_resolved: Path | None = None


def _root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _folder_name(name: str) -> str:
    return name if sys.platform == "win32" else name.lower()


def app_data_dir() -> Path:
    """Per-user data folder (%LOCALAPPDATA%\\FragSubs on Windows)."""
    global _resolved
    override = os.environ.get("FRAGSUBS_HOME") or os.environ.get("CALLOUT_HOME")
    if override:
        base = Path(override)
        base.mkdir(parents=True, exist_ok=True)
        return base
    if _resolved is not None and _resolved.exists():
        return _resolved
    root = _root()
    base = root / _folder_name(APP_NAME)
    if not base.exists():
        for old_name in OLD_NAMES:
            old = root / _folder_name(old_name)
            if not old.exists():
                continue
            try:
                # Same drive, so this is instant, models and all.
                old.rename(base)
                log.info("Moved %s to %s", old, base)
            except OSError as exc:
                # Something still has a file open (the updater's log, say):
                # keep using the old folder this time and try again next start.
                log.info("Could not move %s yet (%s); using it for now", old, exc)
                base = old
            break
    base.mkdir(parents=True, exist_ok=True)
    _resolved = base
    return base


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def models_dir() -> Path:
    d = app_data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def gpu_runtime_dir() -> Path:
    return app_data_dir() / "gpu-runtime"


def logs_dir() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resource_path(*parts: str) -> Path:
    """Path to a bundled resource, both from source and inside a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)
