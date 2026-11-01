"""Make sure only one FragSubs runs at a time.

On Windows a named mutex is the lock (it disappears the moment the process
exits, even after a crash, so an update or restart is never blocked). A local
socket lets a second launch ask the running copy to show its window before
the second launch quits.
"""

from __future__ import annotations

import getpass
import logging
import sys
from typing import Callable

log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183


def _name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    safe = "".join(ch for ch in user if ch.isalnum()) or "user"
    return f"fgmrkt.fragsubs.{safe}"


class SingleInstance:
    def __init__(self, name: str | None = None):
        self.name = name or _name()
        self._mutex = None
        self._server = None

    def already_running(self) -> bool:
        """True if another FragSubs holds the lock. Call once, early."""
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            # Kept open for the life of the process; Windows frees it on exit.
            self._mutex = kernel32.CreateMutexW(None, False, "Local\\" + self.name)
            return ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        # Elsewhere (running from source on Linux/macOS): is anyone listening?
        return self._connect(b"") is True

    def _connect(self, message: bytes) -> bool:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QLocalSocket

        if QCoreApplication.instance() is None:
            self._app = QCoreApplication(sys.argv[:1])
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(1000):
            return False
        if message:
            sock.write(message)
            sock.flush()
            sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return True

    def show_running_instance(self) -> bool:
        """Ask the running FragSubs to bring its window to the front."""
        if sys.platform == "win32":
            try:
                import ctypes

                # We were just launched by the user, so we may hand over the
                # right to take the foreground to the other process.
                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
            except Exception:  # noqa: BLE001
                pass
        ok = self._connect(b"show\n")
        if not ok:
            log.warning("FragSubs is already running but didn't answer")
        return ok

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
