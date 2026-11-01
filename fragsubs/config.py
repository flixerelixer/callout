"""User settings, stored as JSON in the app data folder."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import languages, paths

log = logging.getLogger(__name__)

# What the vocabulary box held by default up to 0.2.x. The Counter-Strike
# words are built in now (see callouts.py), and the box is for extra words.
LEGACY_HINT = (
    "Counter-Strike team voice chat. Callouts: A site, B site, mid, long, short, "
    "ramp, CT, T spawn, AWP, smoke, flash, molotov, HE grenade, rush, eco, "
    "force buy, plant, defuse, bomb, retake, rotate, push, hold, one HP, lit."
)


@dataclass
class Settings:
    # --- audio ---------------------------------------------------------
    # "auto": the game process when it is running, otherwise all system audio.
    # "process": only the game process. "system": everything you hear.
    audio_source: str = "auto"
    process_name: str = "cs2.exe"
    # Output device name for system capture; "" means the Windows default.
    output_device: str = ""
    # Silero VAD speech probability threshold (lower = more sensitive).
    vad_threshold: float = 0.4  # "sensitive" on the slider
    min_speech_ms: int = 200
    end_silence_ms: int = 500
    max_segment_s: float = 6.0
    filter_bangs: bool = True  # gunshots/explosions count as quiet

    # --- recognition / translation --------------------------------------
    model: str = "large-v3"
    device: str = "auto"  # "auto", "cuda" or "cpu"
    languages: list[str] = field(default_factory=languages.default_codes)
    show_english: bool = False
    show_original: bool = True
    # How to write the original words: "native" (Привет), "latin" (Privet) or "both".
    original_script: str = "native"
    min_language_confidence: float = 0.45
    # Extra words for the speech model (teammates' names, your own callouts),
    # added to the built-in Counter-Strike words.
    vocabulary_hint: str = ""
    # Which map's callouts to use: "auto" (ask the game), "none", or a map
    # key such as "de_mirage".
    game_map: str = "auto"
    # Shared secret in the game's GSI file, so only CS2 can set the map.
    gsi_token: str = ""

    # --- overlay ---------------------------------------------------------
    overlay_enabled: bool = True
    # Show a sentence while it is still being spoken, growing as it goes
    # (needs an NVIDIA GPU); the full translation replaces it at the end.
    live_preview: bool = True
    overlay_x: int = -1  # -1 = not placed yet; start at the default spot
    overlay_y: int = -1
    overlay_width: int = 720
    font_size: int = 20
    max_lines: int = 4
    display_seconds: float = 7.0
    background_opacity: float = 0.55
    show_language_tag: bool = True

    # --- app ----------------------------------------------------------------
    start_listening_on_launch: bool = False
    minimize_to_tray: bool = True
    auto_update: bool = True
    last_version: str = ""  # used to say "Callout was updated" once
    show_skipped: bool = False  # list heard-but-skipped speech in the Live log
    settings_version: int = 5

    def enabled_languages(self) -> set[str]:
        return {code for code in self.languages if code in languages.BY_CODE}

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or paths.settings_file()
        settings = cls()
        if not path.exists():
            return settings
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Could not read settings (%s); using defaults", exc)
            return settings
        if not isinstance(data, dict):
            return settings
        # v1 (Callout 0.1.0/0.1.1) needed 0.4 s of speech, which dropped short
        # greetings like "привет". Move people still on that default.
        version = data.get("settings_version", 1)
        if version < 2:
            if data.get("min_speech_ms") == 400:
                data["min_speech_ms"] = settings.min_speech_ms
        # v2 waited 0.55 s of quiet and up to 12 s, bundling sentences.
        if version < 3:
            if data.get("end_silence_ms") == 550:
                data["end_silence_ms"] = settings.end_silence_ms
            if data.get("max_segment_s") == 12.0:
                data["max_segment_s"] = settings.max_segment_s
        # v3 kept the Counter-Strike words in the vocabulary box. They are
        # built in now; an unchanged box becomes empty (extra words only).
        if version < 4:
            if " ".join(str(data.get("vocabulary_hint", "")).split()) == " ".join(LEGACY_HINT.split()):
                data["vocabulary_hint"] = ""
        # v4 started at "balanced" speech detection and a 450 ms pause. Now
        # sensitive (quiet teammates and short callouts get through) with
        # 500 ms (fewer sentences cut in half); move people still on the old
        # values.
        if version < 5:
            if data.get("vad_threshold") == 0.5:
                data["vad_threshold"] = settings.vad_threshold
            if data.get("end_silence_ms") == 450:
                data["end_silence_ms"] = settings.end_silence_ms
        data["settings_version"] = settings.settings_version
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            current = getattr(settings, f.name)
            # Only accept values of the same basic type as the default.
            if isinstance(current, bool):
                ok = isinstance(value, bool)
            elif isinstance(current, (int, float)):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                if ok:
                    value = type(current)(value)
            elif isinstance(current, list):
                ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
            else:
                ok = isinstance(value, type(current))
            if ok:
                setattr(settings, f.name, value)
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or paths.settings_file()
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            log.warning("Could not save settings: %s", exc)
