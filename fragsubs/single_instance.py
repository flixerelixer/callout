"""Make sure only one FragSubs runs at a time.

On Windows a named mutex is the lock (it disappears the moment the process
exits, even after a crash, so an update or restart is never blocked). A local
socket lets a second launch ask the running copy to show its window before
the second launch quits.

Older versions are caught too: Callout 0.1.8 used a lock with another name,
and copies before that had no lock at all, so FragSubs also looks for the
old lock and for running FragSubs.exe / Callout.exe processes.
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
from typing import Callable

log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000
PROGRAM_NAMES = {"fragsubs.exe", "callout.exe"}


def _user() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "".join(ch for ch in user if ch.isalnum()) or "user"


# These names are fixed identifiers shared by every version, not links: if
# they changed, an older copy and a newer one could run side by side.
def _name() -> str:
    return f"fgmrkt.fragsubs.{_user()}"


def _legacy_name() -> str:
    return f"fgmrkt.callout.{_user()}"


def other_copy_pid() -> int | None:
    """PID of another running FragSubs or Callout program, if any."""
    try:
        import psutil
    except ImportError:
        return None
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["pid"] != me and (proc.info["name"] or "").lower() in PROGRAM_NAMES:
                return proc.info["pid"]
        except Exception:  # noqa: BLE001
            continue
    return None


class SingleInstance:
    def __init__(self, name: str | None = None, legacy_name: str | None = None):
        self.name = name or _name()
        self.legacy_name = legacy_name if legacy_name is not None else (None if name else _legacy_name())
        self._mutex = None
        self._server = None
        self.reason = ""

    def already_running(self) -> bool:
        """True if another FragSubs (or an older Callout) is running. Call once, early."""
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.OpenMutexW.restype = wintypes.HANDLE
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            # Kept open for the life of the process; Windows frees it on exit.
            self._mutex = kernel32.CreateMutexW(None, False, "Local\\" + self.name)
            if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
                self.reason = "lock"
                return True
            if self.legacy_name:
                old = kernel32.OpenMutexW(SYNCHRONIZE, False, "Local\\" + self.legacy_name)
                if old:
                    kernel32.CloseHandle(old)
                    self.reason = "Callout 0.1.8 lock"
                    return True
            if getattr(sys, "frozen", False):
                pid = other_copy_pid()
                if pid is not None:
                    self.reason = f"process {pid}"
                    return True
            return False
        # Elsewhere (running from source on Linux/macOS): is anyone listening?
        if self._connect(self.name, b""):
            self.reason = "socket"
            return True
        return False

    def _connect(self, name: str, message: bytes) -> bool:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QLocalSocket

        if QCoreApplication.instance() is None:
            self._app = QCoreApplication(sys.argv[:1])
        sock = QLocalSocket()
        sock.connectToServer(name)
        if not sock.waitForConnected(1000):
            return False
        if message:
            sock.write(message)
            sock.flush()
            sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return True

    def show_running_instance(self) -> bool:
        """Ask the running copy to bring its window to the front. False if it
        didn't answer (copies before 0.1.8 can't)."""
        if sys.platform == "win32":
            try:
                import ctypes

                # We were just launched by the user, so we may hand over the
                # right to take the foreground to the other process.
                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
            except Exception:  # noqa: BLE001
                pass
        for name in filter(None, (self.name, self.legacy_name)):
            if self._connect(name, b"show\n"):
                return True
        log.warning("FragSubs is already running (%s) but didn't answer", self.reason)
        return False

    def listen(self, on_show: Callable[[], None]) -> None:
        """In the running copy: call on_show whenever a second launch knocks."""
        from PySide6.QtNetwork import QLocalServer

        if sys.platform != "win32":
            QLocalServer.removeServer(self.name)  # left behind by a crash
        server = QLocalServer()
        if not server.listen(self.name):
            log.warning("Single-instance listener failed: %s", server.errorString())
            return

        def accept() -> None:
            while server.hasPendingConnections():
                conn = server.nextPendingConnection()
                conn.disconnected.connect(conn.deleteLater)
                on_show()

        server.newConnection.connect(accept)
        self._server = server
