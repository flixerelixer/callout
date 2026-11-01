"""Which map you're on, from Counter-Strike 2 itself.

CS2 has an official way to tell other programs about the match: Game State
Integration (GSI). A small .cfg file in the game's cfg folder names a local
web address, and the game sends the current state there whenever it
changes. Stream overlays and RGB keyboards use the same feature. FragSubs
asks only for the map; it never reads the game's memory.

The game reads the file when it starts, so the first time FragSubs adds it
while CS2 is already open, CS2 needs one restart.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

PORT = 31975
CFG_NAME = "gamestate_integration_fragsubs.cfg"
CS2_APP_ID = "730"
# The game sends its state at least this often while it runs.
HEARTBEAT_S = 30
# No word from the game for this long: it was closed.
STALE_S = HEARTBEAT_S * 2 + 15


def new_token() -> str:
    return secrets.token_hex(12)


def cfg_text(token: str, port: int = PORT) -> str:
    return (
        '"FragSubs"\n'
        "{\n"
        f'  "uri"       "http://127.0.0.1:{port}/"\n'
        '  "timeout"   "2.0"\n'
        '  "buffer"    "0.5"\n'
        '  "throttle"  "1.0"\n'
        f'  "heartbeat" "{HEARTBEAT_S}.0"\n'
        '  "auth"\n'
        "  {\n"
        f'    "token" "{token}"\n'
        "  }\n"
        '  "data"\n'
        "  {\n"
        '    "map" "1"\n'
        "  }\n"
        "}\n"
    )


# ------------------------------------------------------------------ finding CS2
def _steam_dirs() -> list[Path]:
    found: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            for root, key, value in [
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            ]:
                try:
                    with winreg.OpenKey(root, key) as k:
                        found.append(Path(winreg.QueryValueEx(k, value)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                found.append(Path(os.environ[env]) / "Steam")
    else:
        home = Path.home()
        found += [home / ".steam" / "steam", home / ".local" / "share" / "Steam"]
    unique: list[Path] = []
    for p in found:
        if p not in unique:
            unique.append(p)
    return unique


_VDF_PATH = re.compile(r'"path"\s+"((?:[^"\\]|\\.)*)"', re.IGNORECASE)
_VDF_INSTALLDIR = re.compile(r'"installdir"\s+"((?:[^"\\]|\\.)*)"', re.IGNORECASE)


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


def library_dirs(steam: Path) -> list[Path]:
    """Steam library folders listed in libraryfolders.vdf (the Steam folder
    itself included)."""
    libs = [steam]
    for vdf in (steam / "steamapps" / "libraryfolders.vdf", steam / "config" / "libraryfolders.vdf"):
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _VDF_PATH.finditer(text):
            p = Path(_unescape(m.group(1)))
            if p not in libs:
                libs.append(p)
    return libs


def cfg_dir_in_library(library: Path) -> Path | None:
    apps = library / "steamapps"
    manifest = apps / f"appmanifest_{CS2_APP_ID}.acf"
    installdir = "Counter-Strike Global Offensive"
    if manifest.is_file():
        try:
            m = _VDF_INSTALLDIR.search(manifest.read_text(encoding="utf-8", errors="replace"))
            if m:
                installdir = _unescape(m.group(1))
        except OSError:
            pass
    elif not (apps / "common" / installdir).is_dir():
        return None
    cfg = apps / "common" / installdir / "game" / "csgo" / "cfg"
    return cfg if cfg.is_dir() else None


def _running_cs2_cfg_dir() -> Path | None:
    """From a running cs2.exe: <install>/game/bin/win64/cs2.exe."""
    try:
        import psutil
    except ImportError:
        return None
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            if (proc.info["name"] or "").lower() == "cs2.exe" and proc.info["exe"]:
                cfg = Path(proc.info["exe"]).parents[2] / "csgo" / "cfg"
                if cfg.is_dir():
                    return cfg
        except Exception:  # noqa: BLE001
            continue
    return None


def find_cfg_dirs() -> list[Path]:
    """Every CS2 cfg folder on this PC (usually one)."""
    dirs: list[Path] = []
    running = _running_cs2_cfg_dir()
    if running:
        dirs.append(running)
    for steam in _steam_dirs():
        for lib in library_dirs(steam):
            cfg = cfg_dir_in_library(lib)
            if cfg and all(not _same(cfg, d) for d in dirs):
                dirs.append(cfg)
    return dirs


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return str(a).lower() == str(b).lower()


# ------------------------------------------------------------------ the cfg file
def install(token: str, port: int = PORT, cfg_dirs: list[Path] | None = None) -> tuple[list[Path], bool]:
    """Put the GSI file in every CS2 cfg folder. Returns (files, changed):
    changed means at least one file was new or different, so a CS2 that is
    already running won't use it until it restarts."""
    text = cfg_text(token, port)
    files: list[Path] = []
    changed = False
    for d in find_cfg_dirs() if cfg_dirs is None else cfg_dirs:
        path = d / CFG_NAME
        try:
            if not path.is_file() or path.read_text(encoding="utf-8", errors="replace") != text:
                path.write_text(text, encoding="utf-8")
                changed = True
                log.info("Added the map detection file to %s", d)
            files.append(path)
        except OSError as exc:
            log.warning("Could not write %s: %s", path, exc)
    return files, changed


def uninstall(cfg_dirs: list[Path] | None = None) -> int:
    """Remove FragSubs' GSI file again. Returns how many were removed."""
    removed = 0
    for d in find_cfg_dirs() if cfg_dirs is None else cfg_dirs:
        path = d / CFG_NAME
        try:
            if path.is_file():
                path.unlink()
                removed += 1
                log.info("Removed the map detection file from %s", d)
        except OSError as exc:
            log.warning("Could not remove %s: %s", path, exc)
    return removed


# ------------------------------------------------------------------ listening
class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, SO_REUSEADDR would let a second program bind the same port
    # and steal the game's messages; ask for the port exclusively instead.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class GameState:
    """Receives the game's updates on 127.0.0.1 and remembers the map."""

    def __init__(self, token: str, port: int = PORT, on_change: Callable[[str | None], None] | None = None):
        self.token = token
        self.port = port
        self.on_change = on_change
        self._map: str | None = None
        self._last_seen = 0.0
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self.error = ""

    # -- the server ------------------------------------------------------
    def start(self) -> bool:
        if self._server is not None:
            return True
        state = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 256_000)
                    body = self.rfile.read(length)
                    state.receive(json.loads(body.decode("utf-8", errors="replace") or "{}"))
                except (ValueError, OSError) as exc:
                    log.debug("Bad game state message: %s", exc)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args) -> None:  # quiet
                pass

        try:
            server = _Server(("127.0.0.1", self.port), Handler)
        except OSError as exc:
            self.error = f"port {self.port} is in use by another program"
            log.warning("Map detection can't listen on 127.0.0.1:%s (%s)", self.port, exc)
            return False
        threading.Thread(target=server.serve_forever, name="fragsubs-gamestate", daemon=True).start()
        self._server = server
        self.error = ""
        log.info("Listening for the game's map on 127.0.0.1:%s", self.port)
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._set(None)

    @property
    def listening(self) -> bool:
        return self._server is not None

    # -- state -----------------------------------------------------------
    def receive(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        auth = payload.get("auth")
        if not isinstance(auth, dict) or auth.get("token") != self.token:
            return  # not our game, or an old file with another token
        with self._lock:
            self._last_seen = time.monotonic()
        game_map = payload.get("map")
        name = game_map.get("name") if isinstance(game_map, dict) else None
        self._set(name if isinstance(name, str) and name else None)

    def _set(self, name: str | None) -> None:
        with self._lock:
            changed = name != self._map
            self._map = name
        if changed:
            log.info("Map from the game: %s", name or "none (menu)")
            if self.on_change:
                self.on_change(name)

    @property
    def connected(self) -> bool:
        """The game has talked to us recently."""
        with self._lock:
            return bool(self._last_seen) and time.monotonic() - self._last_seen < STALE_S

    @property
    def map_name(self) -> str | None:
        """The map being played, as the game names it ("de_mirage"), or None
        in the menus or when the game hasn't said anything for a while."""
        if not self.connected:
            return None
        with self._lock:
            return self._map
