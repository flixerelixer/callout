"""Where Callout keeps its settings, models, GPU runtime and logs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def app_data_dir() -> Path:
    """Per-user data folder (%LOCALAPPDATA%\\Callout on Windows)."""
    override = os.environ.get("CALLOUT_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME.lower()
    base.mkdir(parents=True, exist_ok=True)
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
