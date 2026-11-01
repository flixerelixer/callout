"""Whisper models (CTranslate2 format) and their one-time download."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    repo: str
    size_bytes: int
    label: str


# "turbo" and "distil" models are left out on purpose: they were not trained
# to translate, which is the whole point here.
MODELS: dict[str, ModelInfo] = {
    m.name: m
    for m in [
        ModelInfo("large-v3", "Systran/faster-whisper-large-v3", 3_087_000_000,
                  "Large v3: best quality, needs a GPU (~4 GB VRAM)"),
        ModelInfo("large-v2", "Systran/faster-whisper-large-v2", 3_087_000_000,
                  "Large v2: alternative, sometimes hallucinates less"),
        ModelInfo("medium", "Systran/faster-whisper-medium", 1_528_000_000,
                  "Medium: good quality, lighter (~2 GB VRAM)"),
        ModelInfo("small", "Systran/faster-whisper-small", 484_000_000,
                  "Small: for CPU or older GPUs"),
        ModelInfo("base", "Systran/faster-whisper-base", 145_000_000,
                  "Base: fastest, lowest quality"),
    ]
}
_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def model_path(name: str) -> Path:
    return paths.models_dir() / name


def is_downloaded(name: str) -> bool:
    d = model_path(name)
    return (d / "model.bin").exists() and (d / "config.json").exists() and (d / "tokenizer.json").exists()


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def download(name: str, progress: Callable[[int, int], None] | None = None) -> Path:
    """Download a model into the app data folder. progress(done, total)."""
    info = MODELS[name]
    target = model_path(name)
    target.mkdir(parents=True, exist_ok=True)
    if is_downloaded(name):
        return target

    from huggingface_hub import snapshot_download

    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(0.5):
            if progress:
                progress(min(_dir_size(target), info.size_bytes), info.size_bytes)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        snapshot_download(info.repo, local_dir=str(target), allow_patterns=_FILES)
    finally:
        stop.set()
        watcher.join(timeout=2)
    if not is_downloaded(name):
        raise RuntimeError(f"Model {name} did not download completely")
    if progress:
        progress(info.size_bytes, info.size_bytes)
    return target
