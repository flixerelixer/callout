"""Application entry point."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from . import APP_NAME, __version__, gpu_runtime, paths


def _setup_logging() -> None:
    level = logging.DEBUG if os.environ.get("CALLOUT_DEBUG") else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        paths.logs_dir() / "callout.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    # Quiet chatty libraries.
    for name in ("huggingface_hub", "httpx", "urllib3", "faster_whisper"):
        logging.getLogger(name).setLevel(logging.WARNING)


def self_test() -> int:
    """Used by CI on the packaged .exe: load every heavy dependency and run
    the voice detector once. Exit code 0 means the build is complete."""
    log = logging.getLogger("callout.selftest")
    try:
        import numpy as np

        import ctranslate2  # noqa: F401
        import faster_whisper  # noqa: F401
        import huggingface_hub  # noqa: F401
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from .audio import Downmixer
        from .vad import FRAME, SileroVAD

        if sys.platform == "win32":
            import pyaudiowpatch  # noqa: F401
            from proctap._native import ProcessLoopback  # noqa: F401

        probs = SileroVAD()(np.zeros((4, FRAME), dtype=np.float32))
        assert probs.shape == (4,), probs.shape
        mono = Downmixer(48000, 2, 32)(np.zeros(9600, dtype=np.float32).tobytes())
        assert mono.size > 0
        log.info("Self-test passed (ctranslate2 %s, CUDA devices: %s)", ctranslate2.__version__,
                 gpu_runtime.cuda_device_count())
        return 0
    except Exception:  # noqa: BLE001
        log.exception("Self-test failed")
        return 1


def main() -> int:
    _setup_logging()
    log = logging.getLogger("callout")
    log.info("%s %s starting (Python %s)", APP_NAME, __version__, sys.version.split()[0])
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    # Make NVIDIA DLLs findable before ctranslate2 is imported anywhere.
    gpu_runtime.activate()

    if "--self-test" in sys.argv:
        return self_test()

    if sys.platform == "win32":
        try:
            import ctypes

            # Own taskbar icon instead of Python's.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fgmrkt.callout")
        except Exception:  # noqa: BLE001
            pass

    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from .config import Settings
    from .ui import theme
    from .ui.main_window import MainWindow
    from .ui.overlay import Overlay

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    theme.load_fonts()
    app.setFont(theme.ui_font(14))
    app.setStyleSheet(theme.stylesheet())
    icon = QIcon(str(paths.resource_path("assets", "icon.png")))
    app.setWindowIcon(icon)

    settings = Settings.load()
    overlay = Overlay(settings)
    window = MainWindow(settings, overlay, icon)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(icon, app)
        tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_action = QAction("Open Callout", menu)
        toggle_action = QAction("Start listening", menu)
        captions_action = QAction("Show captions", menu, checkable=True)
        captions_action.setChecked(settings.overlay_enabled)
        quit_action = QAction("Quit", menu)
        for a in (show_action, toggle_action, captions_action):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)

        def show_window() -> None:
            window.showNormal()
            window.raise_()
            window.activateWindow()

        def set_captions(on: bool) -> None:
            settings.overlay_enabled = on
            settings.save()
            if not on:
                overlay.clear()

        def do_quit() -> None:
            window.quitting = True
            window.shutdown()
            app.quit()

        show_action.triggered.connect(show_window)
        toggle_action.triggered.connect(window.toggle_listening)
        captions_action.toggled.connect(set_captions)
        quit_action.triggered.connect(do_quit)
        window.listening_changed.connect(
            lambda on: toggle_action.setText("Stop listening" if on else "Start listening"))
        tray.activated.connect(
            lambda reason: show_window() if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                                                       QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        tray.show()
        window.tray_available = True
        window.notify = lambda text: tray.showMessage(APP_NAME, text, icon, 4000)

    window.show()
    if settings.start_listening_on_launch:
        window.start_listening()
    code = app.exec()
    if tray is not None:
        tray.hide()
    return code


if __name__ == "__main__":
    sys.exit(main())
