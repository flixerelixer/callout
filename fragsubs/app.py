"""Application entry point."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from . import APP_NAME, __version__, gpu_runtime, paths


def fix_std_streams() -> None:
    """A windowed .exe has no console, so sys.stdout/sys.stderr are None.
    Libraries that print (tqdm progress bars during the model download) then
    crash with "'NoneType' object has no attribute 'write'". Point them at
    the null device instead."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def _setup_logging() -> None:
    level = logging.DEBUG if (os.environ.get("FRAGSUBS_DEBUG") or os.environ.get("CALLOUT_DEBUG")) else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        paths.logs_dir() / "fragsubs.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    # Quiet chatty libraries.
    for name in ("huggingface_hub", "httpx", "urllib3", "faster_whisper"):
        logging.getLogger(name).setLevel(logging.WARNING)


def self_test() -> int:
    """Used by CI on the packaged .exe: load every heavy dependency and run
    the voice detector once. Exit code 0 means the build is complete."""
    log = logging.getLogger("fragsubs.selftest")
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
        # Transliteration data (pypinyin, anyascii) made it into the build.
        from .translit import to_latin

        assert to_latin("Привет", "ru") == "Privet", to_latin("Привет", "ru")
        assert to_latin("你好", "zh") == "nǐ hǎo", to_latin("你好", "zh")
        assert to_latin("안녕", "ko") == "annyeong", to_latin("안녕", "ko")
        # Map callouts and map detection.
        from . import callouts, gamestate

        for game_map in callouts.MAPS.values():
            assert game_map.name in callouts.build_prompt(game_map), game_map.key
        state = gamestate.GameState("t")
        state.receive({"auth": {"token": "t"}, "map": {"name": "de_mirage"}})
        assert callouts.map_for(state.map_name).name == "Mirage", state.map_name
        # Progress bars must not crash without a console (model download).
        from tqdm.auto import tqdm

        for _ in tqdm(range(3)):
            pass
        print("stdout works")
        log.info("Self-test passed (ctranslate2 %s, CUDA devices: %s)", ctranslate2.__version__,
                 gpu_runtime.cuda_device_count())
        return 0
    except Exception:  # noqa: BLE001
        log.exception("Self-test failed")
        return 1


def main() -> int:
    fix_std_streams()
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    _setup_logging()
    log = logging.getLogger("fragsubs")
    log.info("%s %s starting (Python %s)", APP_NAME, __version__, sys.version.split()[0])

    # Make NVIDIA DLLs findable before ctranslate2 is imported anywhere.
    gpu_runtime.activate()

    if "--self-test" in sys.argv:
        return self_test()
    if "--remove-game-config" in sys.argv:
        # Run by the uninstaller: take the map detection file out of CS2.
        from . import gamestate

        log.info("Removed %d map detection file(s)", gamestate.uninstall())
        return 0

    if sys.platform == "win32":
        try:
            import ctypes

            # Own taskbar icon instead of Python's.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fgmrkt.fragsubs")
        except Exception:  # noqa: BLE001
            pass

    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from .config import Settings
    from .ui import theme
    from .ui.main_window import MainWindow
    from .ui.overlay import Overlay

    from .single_instance import SingleInstance

    app = QApplication(sys.argv)
    instance = SingleInstance()
    if instance.already_running():
        log.info("FragSubs is already running (%s); bringing it to the front instead", instance.reason)
        if not instance.show_running_instance():
            # An older copy that can't be asked to show itself.
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                None, APP_NAME,
                "FragSubs (or Callout, its old name) is already running. Look for its icon in the "
                "system tray, next to the clock.\n\nIf you can't find it, end it in Task Manager "
                "and start FragSubs again.")
        return 0
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

    def show_window() -> None:
        window.showNormal()
        window.raise_()
        window.activateWindow()

    # Launching FragSubs again (desktop shortcut, Start menu) shows this window.
    instance.listen(show_window)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(icon, app)
        tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_action = QAction(f"Open {APP_NAME}", menu)
        toggle_action = QAction("Start listening", menu)
        captions_action = QAction("Show captions", menu, checkable=True)
        captions_action.setChecked(settings.overlay_enabled)
        quit_action = QAction("Quit", menu)
        for a in (show_action, toggle_action, captions_action):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)

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
