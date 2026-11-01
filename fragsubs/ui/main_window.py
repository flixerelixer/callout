"""The settings / control window."""

from __future__ import annotations

import html
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import (APP_NAME, REPO_URL, WEBSITE, __version__, audio, callouts, gamestate, gpu_runtime, languages, models,
               paths, translit, updater)
from ..config import Settings
from ..engine import Caption, Skipped
from ..pipeline import Callbacks, Pipeline
from . import theme
from .overlay import Overlay
from .widgets import CaptionLog, SignalMeter, StatusPill

log = logging.getLogger(__name__)


class Bridge(QObject):
    """Thread-safe hop from worker threads to the UI thread."""

    status = Signal(str)
    source = Signal(str)
    caption = Signal(object)
    skipped = Signal(object)
    level = Signal(float, float, bool)
    progress = Signal(str, int, int)
    error = Signal(str)
    ready = Signal()
    task_done = Signal(str, object)
    map_changed = Signal(str)
    retract = Signal(int)


def _gb(n: int) -> str:
    if n < 1e9:
        return f"{n / 1e6:.0f} MB"
    return f"{n / 1e9:.1f} GB"


class MainWindow(QMainWindow):
    listening_changed = Signal(bool)

    def __init__(self, settings: Settings, overlay: Overlay, icon: QIcon | None = None):
        super().__init__()
        self.settings = settings
        self.overlay = overlay
        self.quitting = False
        self._pipeline: Pipeline | None = None
        self._running = False
        self._task: threading.Thread | None = None
        self._cancel = threading.Event()
        self._gpu_count: int | None = None
        self._gpu_name = ""
        self._tray_hint_shown = False
        self._update_thread: threading.Thread | None = None
        self._update_release: updater.Release | None = None

        self.bridge = Bridge()
        self.bridge.status.connect(self._on_status)
        self.bridge.source.connect(self._on_source)
        self.bridge.caption.connect(self._on_caption)
        self.bridge.skipped.connect(self._on_skipped)
        self.bridge.level.connect(self._on_level)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.error.connect(self._on_error)
        self.bridge.ready.connect(self._on_ready)
        self.bridge.task_done.connect(self._on_task_done)
        self.bridge.map_changed.connect(lambda _name: self._refresh_map_status())
        self.bridge.retract.connect(self.overlay.remove_segment)

        # Map detection (CS2 Game State Integration). File work runs one job
        # at a time, off the UI thread.
        self.game = gamestate.GameState(self.settings.gsi_token,
                                        on_change=lambda name: self.bridge.map_changed.emit(name or ""))
        self._gsi_jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fragsubs-gsi")
        self._gsi_files: list | None = None  # CS2 cfg files written; None = not looked yet
        self._gsi_added_now = False

        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self.settings.save)
        self._restart_timer = QTimer(self, singleShot=True, interval=900, timeout=self._restart_if_running)

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        if icon:
            self.setWindowIcon(icon)
        self.resize(940, 660)
        self.setMinimumSize(760, 520)
        self._build()
        self.overlay.moved.connect(self._on_overlay_moved)
        QTimer.singleShot(0, self._probe_gpu)
        QTimer.singleShot(0, self._announce_update)
        QTimer.singleShot(1500, lambda: self.check_updates(manual=False))
        QTimer.singleShot(0, self._apply_map_detection)
        self._map_timer = QTimer(self, interval=5000, timeout=self._refresh_map_status)
        self._map_timer.start()

    # ================================================================== layout
    def _build(self) -> None:
        root = QWidget(objectName="root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(objectName="header")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setStyleSheet(f"QWidget#header {{ background: {theme.BASE}; }}")
        h = QHBoxLayout(header)
        h.setContentsMargins(20, 14, 20, 14)
        h.setSpacing(14)
        brand = QLabel(APP_NAME, objectName="brand")
        h.addWidget(brand)
        self.pill = StatusPill()
        h.addWidget(self.pill)
        h.addStretch(1)
        self.start_btn = QPushButton("Start listening", objectName="primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.toggle_listening)
        h.addWidget(self.start_btn)
        outer.addWidget(header)

        self.meter = SignalMeter()
        outer.addWidget(self.meter)

        # Download progress / error strip (hidden unless needed)
        self.notice = QWidget(objectName="notice")
        self.notice.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.notice.setStyleSheet(
            f"QWidget#notice {{ background: {theme.PANEL}; border-bottom: 1px solid {theme.LINE}; }}")
        n = QHBoxLayout(self.notice)
        n.setContentsMargins(20, 8, 20, 8)
        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        n.addWidget(self.notice_label, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(260)
        self.progress.setTextVisible(False)
        n.addWidget(self.progress)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel.set)
        n.addWidget(self.cancel_btn)
        self.notice_action = QPushButton()
        self.notice_action.setObjectName("primary")
        self.notice_action.hide()
        self.notice_action.clicked.connect(self._on_notice_action)
        n.addWidget(self.notice_action)
        self._notice_callback = None
        self.notice.hide()
        outer.addWidget(self.notice)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.nav = QListWidget(objectName="nav")
        self.nav.setFixedWidth(190)
        self.nav.setFont(theme.ui_font(15))
        self.pages = QStackedWidget()
        for title, builder in [
            ("Live", self._page_live),
            ("Languages", self._page_languages),
            ("Maps & callouts", self._page_maps),
            ("Overlay", self._page_overlay),
            ("Audio & model", self._page_audio),
            ("About", self._page_about),
        ]:
            self.nav.addItem(title)
            self.pages.addWidget(builder())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(root)

    def _page(self, title: str, intro: str = "") -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(objectName="page")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(10)
        lay.addWidget(QLabel(title, objectName="pageTitle"))
        if intro:
            lab = QLabel(intro, objectName="muted")
            lab.setWordWrap(True)
            lay.addWidget(lab)
        return scroll, lay

    @staticmethod
    def _section(lay: QVBoxLayout, title: str) -> None:
        lay.addSpacing(10)
        lay.addWidget(QLabel(title, objectName="sectionTitle"))

    @staticmethod
    def _note(text: str) -> QLabel:
        lab = QLabel(text, objectName="muted")
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setOpenExternalLinks(True)
        return lab

    # ---------------------------------------------------------------- pages
    def _page_live(self) -> QWidget:
        page = QWidget(objectName="page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 22, 28, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("Live translations", objectName="pageTitle"))
        top.addStretch(1)
        test = QPushButton("Show a test caption")
        test.clicked.connect(self._test_caption)
        top.addWidget(test)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.log.clear())
        top.addWidget(clear)
        lay.addLayout(top)
        self.log = CaptionLog()
        lay.addWidget(self.log, 1)
        skipped = QCheckBox("Also list speech that was heard but skipped, with the reason")
        skipped.setChecked(self.settings.show_skipped)
        skipped.toggled.connect(lambda on: self._set("show_skipped", on))
        lay.addWidget(skipped)
        return page

    def _page_languages(self) -> QWidget:
        scroll, lay = self._page(
            "Languages",
            "Speech in the languages you tick is translated into English. Speech in any other "
            "language is ignored, so untick the ones you already understand.",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(2)
        self.lang_boxes: dict[str, QCheckBox] = {}
        enabled = self.settings.enabled_languages()
        cols = 3
        for i, lang in enumerate(languages.LANGUAGES):
            box = QCheckBox(lang.name)
            box.setChecked(lang.code in enabled)
            box.toggled.connect(self._languages_changed)
            self.lang_boxes[lang.code] = box
            grid.addWidget(box, i // cols, i % cols)
        lay.addLayout(grid)

        row = QHBoxLayout()
        for label, fn in [("Common languages", self._langs_default), ("Select all", self._langs_all),
                          ("Clear all", self._langs_none)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(row)

        self._section(lay, "What to show")
        self._check(lay, "Show the original words under the translation", "show_original")
        row = QHBoxLayout()
        row.addWidget(QLabel("Write the original words in"))
        script = QComboBox()
        for key, label in [("native", "Their own alphabet (Привет, 你好)"),
                           ("latin", "Latin letters (Privet, nǐ hǎo)"),
                           ("both", "Both")]:
            script.addItem(label, key)
        script.setCurrentIndex(max(0, script.findData(self.settings.original_script)))

        def script_changed() -> None:
            self._set("original_script", script.currentData())
            self.overlay.apply_settings()

        script.currentIndexChanged.connect(script_changed)
        row.addWidget(script, 1)
        lay.addLayout(row)
        lay.addWidget(self._note("Latin letters cover Cyrillic, Chinese (pinyin), Korean, Arabic, Greek, "
                                 "Hebrew, Thai and Hindi. Japanese kana become romaji; kanji stay as they are."))
        self._check(lay, "Also caption English speech", "show_english")
        lay.addStretch(1)
        return scroll

    def _page_overlay(self) -> QWidget:
        scroll, lay = self._page(
            "Overlay",
            "Captions appear in a small see-through box on top of the game. Mouse clicks go "
            "straight through it.",
        )
        self._check(lay, "Show captions over the game", "overlay_enabled",
                    after=lambda: None if self.settings.overlay_enabled else self.overlay.clear())
        self._check(lay, "Show sentences while they're still being spoken, growing as the teammate talks",
                    "live_preview")
        lay.addWidget(self._note(
            "The line ends in “…” while they talk. When they stop, the full, more careful translation "
            "replaces it. Needs an NVIDIA GPU; on the CPU captions appear when the sentence is finished."))
        lay.addWidget(self._note(
            "Set Counter-Strike 2 to <b>Fullscreen Windowed</b> (Settings, Video, Display Mode). "
            "In plain Fullscreen the game hides every other window, including this overlay."
        ))

        self._section(lay, "Position")
        row = QHBoxLayout()
        self.move_btn = QPushButton("Move overlay")
        self.move_btn.clicked.connect(self._toggle_overlay_edit)
        row.addWidget(self.move_btn)
        reset = QPushButton("Reset position")
        reset.clicked.connect(self._reset_overlay)
        row.addWidget(reset)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self._note("Captions line up left, centre or right depending on where you put the box."))

        self._section(lay, "Look")
        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self._slider(form, 0, "Text size", "font_size", 14, 40, 1, lambda v: f"{v}px", overlay=True)
        self._slider(form, 1, "Lines on screen", "max_lines", 1, 8, 1, str, overlay=True)
        self._slider(form, 2, "Time on screen", "display_seconds", 3, 20, 1, lambda v: f"{v}s", overlay=True)
        self._slider(form, 3, "Background", "background_opacity", 0, 100, 100,
                     lambda v: f"{v}%", overlay=True)
        lay.addLayout(form)
        self._check(lay, "Show the language code (RU, PL…) in front of each line", "show_language_tag",
                    after=self.overlay.update)
        lay.addStretch(1)
        return scroll

    def _page_audio(self) -> QWidget:
        scroll, lay = self._page("Audio & model")

        self._section(lay, "What to listen to")
        self.source_combo = QComboBox()
        sources = [
            ("auto", "The game when it's running, otherwise everything I hear"),
            ("process", "Only the game"),
            ("system", "Everything I hear (Discord, browser, game…)"),
        ]
        for key, label in sources:
            self.source_combo.addItem(label, key)
        self.source_combo.setCurrentIndex(max(0, self.source_combo.findData(self.settings.audio_source)))
        self.source_combo.currentIndexChanged.connect(
            lambda: self._set("audio_source", self.source_combo.currentData(), restart=True))
        lay.addWidget(self.source_combo)

        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.addWidget(QLabel("Game program"), 0, 0)
        proc = QLineEdit(self.settings.process_name)
        proc.setPlaceholderText("cs2.exe")
        proc.editingFinished.connect(lambda: self._set("process_name", proc.text().strip() or "cs2.exe", restart=True))
        form.addWidget(proc, 0, 1)
        form.addWidget(QLabel("Output device"), 1, 0)
        self.device_combo = QComboBox()
        self.device_combo.addItem("Windows default", "")
        for name in audio.list_output_devices():
            self.device_combo.addItem(name, name)
        idx = self.device_combo.findData(self.settings.output_device)
        self.device_combo.setCurrentIndex(max(0, idx))
        self.device_combo.currentIndexChanged.connect(
            lambda: self._set("output_device", self.device_combo.currentData(), restart=True))
        form.addWidget(self.device_combo, 1, 1)
        form.setColumnStretch(1, 1)
        lay.addLayout(form)
        lay.addWidget(self._note(
            "FragSubs only reads the sound the game plays and never touches the game's memory, so it is "
            "safe with VAC."))

        self._section(lay, "Picking up speech")
        speech = QGridLayout()
        speech.setHorizontalSpacing(16)
        speech.setVerticalSpacing(10)
        self._slider(speech, 0, "Speech detection", "vad_threshold", 20, 80, 100,
                     lambda v: "very sensitive" if v < 35 else "sensitive" if v < 48
                     else "balanced" if v < 60 else "strict", restart=True)
        self._slider(speech, 1, "Pause that ends a sentence", "end_silence_ms", 250, 1500, 1,
                     lambda v: f"{v} ms", restart=True)
        speech.setColumnStretch(1, 1)
        lay.addLayout(speech)
        lay.addWidget(self._note(
            "Quiet teammates or short callouts missed? Move <b>Speech detection</b> towards sensitive. Game "
            "sounds taken for talking? Towards strict.<br>Sentences cut in half? Raise the <b>pause</b> "
            "(for example to 700 ms). Subtitles too slow, or several sentences in one? Lower it (300 to "
            "400 ms)."))
        self._check(lay, "Ignore gunshots and explosions (they can't stretch a sentence, and Whisper "
                         "hears them turned down)", "filter_bangs", restart=True)

        self._section(lay, "Speech model")
        self.model_combo = QComboBox()
        for info in models.MODELS.values():
            self.model_combo.addItem(info.label, info.name)
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(self.settings.model)))
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        lay.addWidget(self.model_combo)
        self.model_note = self._note("")
        lay.addWidget(self.model_note)
        self._refresh_model_note()

        row = QHBoxLayout()
        row.addWidget(QLabel("Run on"))
        self.dev_combo = QComboBox()
        for key, label in [("auto", "Automatic (GPU if available)"), ("cuda", "NVIDIA GPU"), ("cpu", "CPU")]:
            self.dev_combo.addItem(label, key)
        self.dev_combo.setCurrentIndex(max(0, self.dev_combo.findData(self.settings.device)))
        self.dev_combo.currentIndexChanged.connect(
            lambda: self._set("device", self.dev_combo.currentData(), restart=True))
        row.addWidget(self.dev_combo, 1)
        lay.addLayout(row)
        self.gpu_note = self._note("Checking for an NVIDIA GPU…")
        lay.addWidget(self.gpu_note)
        self.gpu_btn = QPushButton("Download GPU support (1.2 GB)")
        self.gpu_btn.clicked.connect(lambda: self._download_gpu_runtime(then_start=False))
        self.gpu_btn.hide()
        self.gpu_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.gpu_btn)

        lay.addStretch(1)
        return scroll

    def _page_maps(self) -> QWidget:
        scroll, lay = self._page(
            "Maps & callouts",
            "FragSubs tells the speech model the callouts of the map you're playing, so names like Palace, "
            "Banana and Heaven come out right instead of as words that sound alike.")
        self._section(lay, "Map")
        self.map_combo = QComboBox()
        self.map_combo.addItem("Detect it from the game (recommended)", "auto")
        for game_map in sorted(callouts.MAPS.values(), key=lambda m: m.name):
            self.map_combo.addItem(game_map.name, game_map.key)
        self.map_combo.addItem("No map (only general Counter-Strike words)", "none")
        self.map_combo.setCurrentIndex(max(0, self.map_combo.findData(self.settings.game_map)))
        self.map_combo.currentIndexChanged.connect(self._map_choice_changed)
        lay.addWidget(self.map_combo)
        self.map_status = self._note("")
        lay.addWidget(self.map_status)

        self._section(lay, "Words the speech model listens for")
        self.map_words = self._note("")
        self.map_words.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.map_words)

        self._section(lay, "Extra words")
        lay.addWidget(self._note(
            "Teammates' names or your team's own callouts, separated by commas. They are always included."))
        hint = QPlainTextEdit(self.settings.vocabulary_hint)
        hint.setPlaceholderText("For example: Artyom, Kuba, our stack")
        hint.setFixedHeight(64)

        hint.textChanged.connect(lambda: self._set("vocabulary_hint", hint.toPlainText()))
        lay.addWidget(hint)

        self._section(lay, "How map detection works")
        lay.addWidget(self._note(
            "Counter-Strike 2 can tell other programs which map you're on through Valve's Game State "
            "Integration, the official feature stream overlays and RGB keyboards use. FragSubs adds the file "
            f"<b>{gamestate.CFG_NAME}</b> to the game's cfg folder and asks only for the map name. It never "
            "reads the game's memory. Picking a map by hand, or uninstalling FragSubs, removes the file."))
        lay.addStretch(1)
        self._refresh_map_status()
        return scroll

    def _page_about(self) -> QWidget:
        scroll, lay = self._page(f"{APP_NAME} {__version__}")
        lay.addWidget(self._note(
            "Listens to your game's voice chat, works out which language each sentence is in, and "
            "shows an English translation on top of the game. Speech recognition and translation "
            "run on this PC with OpenAI's Whisper model."))
        self._section(lay, "Privacy")
        lay.addWidget(self._note(
            "Audio never leaves your computer and nothing you hear is saved. The only downloads are "
            "the speech model (from Hugging Face), NVIDIA's libraries for NVIDIA GPUs (from PyPI) and "
            "FragSubs updates (from GitHub)."))
        self._section(lay, "Good to know")
        lay.addWidget(self._note(
            "FragSubs cannot tell teammates apart in in-game voice chat, because the game mixes them "
            "into one sound. Translations arrive about a second after someone stops talking. Loud "
            "gunfights and heavy slang lower the accuracy."))
        self._section(lay, "Updates")
        self._check(lay, "Update automatically when FragSubs starts", "auto_update")
        upd = QPushButton("Check for updates")
        upd.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        upd.clicked.connect(lambda: self.check_updates(manual=True))
        lay.addWidget(upd)
        self._section(lay, "Settings")
        self._check(lay, "Keep running in the system tray when this window is closed", "minimize_to_tray")
        self._check(lay, "Start listening when FragSubs opens", "start_listening_on_launch")
        row = QHBoxLayout()
        for label, target in [("Open the data folder", paths.app_data_dir), ("Open the log folder", paths.logs_dir)]:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, t=target: QDesktopServices.openUrl(QUrl.fromLocalFile(str(t()))))
            row.addWidget(b)
        site = QPushButton("fragsubs.com")
        site.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE)))
        row.addWidget(site)
        gh = QPushButton("Source on GitHub")
        gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        row.addWidget(gh)
        row.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(row)
        lay.addStretch(1)
        return scroll

    # ---------------------------------------------------------------- bindings
    def _set(self, attr: str, value, restart: bool = False) -> None:
        if getattr(self.settings, attr) == value:
            return
        setattr(self.settings, attr, value)
        self._save_timer.start()
        if restart and self._running:
            self._restart_timer.start()

    def _check(self, lay: QVBoxLayout, label: str, attr: str, after=None, restart: bool = False) -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(bool(getattr(self.settings, attr)))

        def changed(on: bool) -> None:
            self._set(attr, on, restart)
            if after:
                after()
            if attr == "show_original":
                self.overlay.apply_settings()

        box.toggled.connect(changed)
        lay.addWidget(box)
        return box

    def _slider(self, grid: QGridLayout, row: int, label: str, attr: str, lo: int, hi: int, scale: int,
                fmt, overlay: bool = False, restart: bool = False) -> QSlider:
        grid.addWidget(QLabel(label), row, 0)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        current = getattr(self.settings, attr)
        slider.setValue(int(round(current * scale)) if scale != 1 else int(current))
        value_label = QLabel(fmt(slider.value()), objectName="muted")
        value_label.setMinimumWidth(130)

        def changed(v: int) -> None:
            value_label.setText(fmt(v))
            typ = type(getattr(self.settings, attr))
            new = typ(v / scale) if scale != 1 else typ(v)
            self._set(attr, new, restart)
            if overlay:
                self.overlay.apply_settings()

        slider.valueChanged.connect(changed)
        grid.addWidget(slider, row, 1)
        grid.addWidget(value_label, row, 2)
        return slider

    def _languages_changed(self) -> None:
        codes = [code for code, box in self.lang_boxes.items() if box.isChecked()]
        self._set("languages", codes)

    def _set_langs(self, codes: set[str]) -> None:
        for code, box in self.lang_boxes.items():
            box.blockSignals(True)
            box.setChecked(code in codes)
            box.blockSignals(False)
        self._languages_changed()

    def _langs_default(self) -> None:
        self._set_langs(set(languages.default_codes()))

    def _langs_all(self) -> None:
        self._set_langs(set(self.lang_boxes))

    def _langs_none(self) -> None:
        self._set_langs(set())

    # ---------------------------------------------------------------- maps
    def current_map(self) -> str | None:
        """The map whose callouts to use, as the game names it. Called from
        the speech thread before every sentence."""
        choice = self.settings.game_map
        if choice == "auto":
            return self.game.map_name
        if choice == "none":
            return None
        return choice

    def _map_choice_changed(self) -> None:
        self._set("game_map", self.map_combo.currentData())
        self._apply_map_detection()
        self._refresh_map_status()

    def _apply_map_detection(self) -> None:
        """Map detection on: listen, and put the GSI file in CS2's cfg folder.
        Off: stop listening and take the file out again."""
        want = self.settings.game_map == "auto"
        if want:
            if not self.settings.gsi_token:
                self.settings.gsi_token = gamestate.new_token()
                self._save_timer.start()
            self.game.token = self.settings.gsi_token
            self.game.start()
            token = self.settings.gsi_token

            def job():
                return gamestate.install(token)
        else:
            self.game.stop()
            job = gamestate.uninstall
        self._gsi_files = None if want else []

        def work() -> None:
            try:
                result = job()
            except Exception as exc:  # noqa: BLE001
                log.warning("Map detection setup failed: %s", exc)
                result = exc
            self.bridge.task_done.emit("gsi", (want, result))

        self._gsi_jobs.submit(work)

    def _refresh_map_status(self) -> None:
        if not hasattr(self, "map_status"):
            return
        choice = self.settings.game_map
        name = self.current_map()
        game_map = callouts.map_for(name)
        if choice == "auto":
            if not self.game.listening:
                text = (f"Map detection can't start ({self.game.error or 'unknown problem'}). "
                        "Pick your map by hand above.")
            elif self.game.connected:
                if game_map:
                    text = f"<b>Playing {game_map.name}</b>, detected from the game."
                elif name:
                    text = (f"Playing {html.escape(name)}. FragSubs has no callout list for this map, so it "
                            "uses the general words.")
                else:
                    text = "Counter-Strike 2 is connected. The map shows up here when you join a match."
            elif self._gsi_files is None:
                text = "Looking for Counter-Strike 2…"
            elif not self._gsi_files:
                text = "Couldn't find Counter-Strike 2 on this PC. Pick your map by hand above."
            elif self._gsi_added_now:
                text = ("Set up. If Counter-Strike 2 is open right now, restart it once so it starts telling "
                        "FragSubs the map.")
            else:
                text = "Waiting for Counter-Strike 2. Start the game and the map shows up here."
        elif choice == "none":
            text = "Only the general Counter-Strike words are used."
        else:
            text = f"Using the callouts for {game_map.name if game_map else html.escape(choice)}."
        self.map_status.setText(text)
        if game_map:
            words = (f"<b>{game_map.name}:</b> {html.escape(', '.join(game_map.callouts))}. "
                     "Plus common words like AWP, smoke, flash, molly, eco and one HP.")
        else:
            words = ("No map yet, so common words only: AWP, smoke, flash, molly, eco, rush, rotate, one HP, "
                     "A site, B site, mid and more.")
        self.map_words.setText(words)

    def _model_changed(self) -> None:
        self._set("model", self.model_combo.currentData(), restart=True)
        self._refresh_model_note()

    def _refresh_model_note(self) -> None:
        info = models.MODELS.get(self.settings.model)
        if info is None:
            return
        if models.is_downloaded(info.name):
            self.model_note.setText("Downloaded and ready.")
        else:
            self.model_note.setText(f"Downloads automatically the first time you start ({_gb(info.size_bytes)}).")

    # ---------------------------------------------------------------- overlay
    def _toggle_overlay_edit(self) -> None:
        on = not self.overlay.edit_mode
        self.overlay.set_edit_mode(on)
        self.move_btn.setText("Done" if on else "Move overlay")

    def _reset_overlay(self) -> None:
        self.settings.overlay_x = -1
        self.settings.overlay_y = -1
        self.settings.overlay_width = Settings().overlay_width
        self._save_timer.start()
        self.overlay.apply_settings()

    def _on_overlay_moved(self, x: int, y: int, w: int) -> None:
        self.settings.overlay_x, self.settings.overlay_y, self.settings.overlay_width = x, y, w
        self._save_timer.start()

    def _test_caption(self) -> None:
        cap = Caption("ru", "Two on B, one is low. I'm rotating.", "Двое на Б, один лоу. Я ротейчусь.", 0.97, 2.1, 180)
        cap.original_latin = translit.to_latin(cap.original, cap.language)
        self._on_caption(cap)

    # ================================================================== GPU
    def _probe_gpu(self) -> None:
        def work() -> None:
            count = gpu_runtime.cuda_device_count()
            name = gpu_runtime.gpu_name() if count else ""
            self.bridge.task_done.emit("gpu_probe", (count, name))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_gpu_note(self) -> None:
        if self._gpu_count is None:
            return
        if self._gpu_count == 0:
            self.gpu_note.setText("No NVIDIA GPU found, so FragSubs runs on the CPU. Pick the Small model for "
                                  "real-time speed.")
            self.gpu_btn.hide()
            return
        name = self._gpu_name or "An NVIDIA GPU"
        if gpu_runtime.is_installed():
            self.gpu_note.setText(f"{name} found. GPU support is installed.")
            self.gpu_btn.hide()
        else:
            self.gpu_note.setText(f"{name} found. GPU support still needs a one-time download "
                                  "(NVIDIA cuBLAS and cuDNN, about 1.2 GB).")
            self.gpu_btn.setVisible(self._task is None)

    def _download_gpu_runtime(self, then_start: bool) -> None:
        if self._task is not None:
            return
        self._cancel.clear()

        def work() -> None:
            try:
                gpu_runtime.download(
                    lambda done, total, label: self.bridge.progress.emit(label, done, total), self._cancel)
                gpu_runtime.activate()
                self.bridge.task_done.emit("gpu_download", None if not then_start else "start")
            except gpu_runtime.Cancelled:
                self.bridge.task_done.emit("gpu_download", "cancelled")
            except Exception as exc:  # noqa: BLE001
                log.exception("GPU runtime download failed")
                self.bridge.task_done.emit("gpu_download", exc)

        self._task = threading.Thread(target=work, daemon=True)
        self._task.start()
        self.gpu_btn.hide()
        self.cancel_btn.show()
        self._show_notice("Downloading GPU support…", busy=True)

    def _resolve_device(self) -> str | None:
        pref = self.settings.device
        if pref == "cpu":
            return "cpu"
        if self._gpu_count is None:
            self._gpu_count = gpu_runtime.cuda_device_count()
        if self._gpu_count == 0:
            if pref == "cuda":
                QMessageBox.warning(self, APP_NAME, "No NVIDIA GPU was found. Switch “Run on” to CPU or "
                                                    "Automatic in Audio & model.")
                return None
            return "cpu"
        if gpu_runtime.is_installed():
            gpu_runtime.activate()
            return "cuda"
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText("Download GPU support?")
        box.setInformativeText(
            "FragSubs found an NVIDIA GPU. To run the speech model on it, it needs NVIDIA's cuBLAS and "
            "cuDNN libraries: a one-time download of about 1.2 GB (1.8 GB on disk).\n\n"
            "Without them FragSubs runs on the CPU, which is too slow for the large model.")
        dl = box.addButton("Download and start", QMessageBox.ButtonRole.AcceptRole)
        cpu = box.addButton("Use the CPU this time", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is dl:
            self._download_gpu_runtime(then_start=True)
            return None
        if box.clickedButton() is cpu:
            return "cpu"
        return None

    # ================================================================== start / stop
    def toggle_listening(self) -> None:
        if self._running:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self) -> None:
        if self._running or self._task is not None:
            return
        device = self._resolve_device()
        if device is None:
            return
        if device == "cpu" and self.settings.model in ("large-v3", "large-v2", "medium"):
            log.info("Running %s on CPU; this will be slow", self.settings.model)
        cb = Callbacks(
            status=self.bridge.status.emit,
            source=self.bridge.source.emit,
            caption=self.bridge.caption.emit,
            skipped=self.bridge.skipped.emit,
            level=self.bridge.level.emit,
            progress=self.bridge.progress.emit,
            error=self.bridge.error.emit,
            ready=self.bridge.ready.emit,
            retract=self.bridge.retract.emit,
        )
        self._pipeline = Pipeline(self.settings, device, cb, game_map=self.current_map)
        self._pipeline.start()
        self._running = True
        self.meter.set_active(True)
        self.pill.set("busy", "Starting…")
        self._update_button()
        self.listening_changed.emit(True)

    def stop_listening(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop(timeout=0.5)
        self._pipeline = None
        self._running = False
        self.meter.set_active(False)
        self.pill.set("idle", "Not listening")
        self.notice.hide()
        self._update_button()
        self.listening_changed.emit(False)

    def _restart_if_running(self) -> None:
        if self._running:
            self.stop_listening()
            self.start_listening()

    def _update_button(self) -> None:
        self.start_btn.setText("Stop listening" if self._running else "Start listening")
        self.start_btn.setProperty("running", "true" if self._running else "false")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)

    @property
    def running(self) -> bool:
        return self._running

    # ================================================================== callbacks
    def _show_notice(self, text: str, busy: bool = False, error: bool = False) -> None:
        color = theme.DANGER if error else theme.TEXT
        self.notice_label.setStyleSheet(f"color: {color};")
        self.notice_label.setText(text)
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy and (self._task is not None or self._update_thread is not None))
        if busy:
            self.progress.setRange(0, 0)
        self.notice_action.hide()
        self._notice_callback = None
        self.notice.show()

    def _show_notice_action(self, text: str, button: str, callback) -> None:
        self._show_notice(text)
        self.notice_action.setText(button)
        self.notice_action.show()
        self._notice_callback = callback

    def _on_notice_action(self) -> None:
        callback = self._notice_callback
        if callback:
            callback()

    def _on_status(self, text: str) -> None:
        if self._running:
            self.pill.set("busy", text)

    def _on_source(self, text: str) -> None:
        self.meter.set_source(text)

    def _on_ready(self) -> None:
        if not self._running:
            return
        self.pill.set("live", "Listening")
        self.notice.hide()
        self._refresh_model_note()

    def _on_level(self, level_db: float, _prob: float, speech: bool) -> None:
        if not self._running:
            return
        self.meter.push(level_db, speech)
        if self.pill.state in ("live", "speech"):
            self.pill.set("speech" if speech else "live", "Someone is talking" if speech else "Listening")

    def _on_caption(self, caption: Caption) -> None:
        if not caption.partial:  # the Live list only gets finished sentences
            self.log.add(caption, self.settings.original_script)
        self.overlay.add_caption(caption)

    def _on_skipped(self, item: Skipped) -> None:
        self.overlay.remove_segment(item.segment_id)
        if self.settings.show_skipped:
            self.log.add(item)

    def _on_progress(self, label: str, done: int, total: int) -> None:
        if not self.notice.isVisible() or not self.progress.isVisible():
            self._show_notice(label, busy=True)
        self.progress.setRange(0, 1000)
        self.progress.setValue(int(1000 * done / max(1, total)))
        self.notice_label.setText(f"{label}: {_gb(done)} of {_gb(total)}")

    def _on_error(self, text: str) -> None:
        log.error(text)
        self._show_notice(text, error=True)
        if self._running and self._pipeline is not None:
            QTimer.singleShot(400, self._check_pipeline)

    def _check_pipeline(self) -> None:
        if self._running and self._pipeline is not None and not self._pipeline.running:
            msg = self.notice_label.text()
            self.stop_listening()
            self._show_notice(msg, error=True)
            self.pill.set("error", "Stopped")

    def _on_task_done(self, name: str, result) -> None:
        if name == "gsi":
            want, outcome = result
            if want == (self.settings.game_map == "auto"):
                if want and isinstance(outcome, tuple):
                    self._gsi_files, self._gsi_added_now = outcome
                elif want:
                    self._gsi_files = []
            self._refresh_map_status()
            return
        if name == "gpu_probe":
            self._gpu_count, self._gpu_name = result
            self._refresh_gpu_note()
            return
        if name.startswith("update_"):
            self._on_update_result(name, result)
            return
        if name == "gpu_download":
            self._task = None
            self.cancel_btn.hide()
            if isinstance(result, Exception):
                self._show_notice(f"GPU support download failed: {result}", error=True)
            elif result == "cancelled":
                self.notice.hide()
            else:
                self.notice.hide()
                if result == "start":
                    self.start_listening()
            self._refresh_gpu_note()

    # ================================================================== updates
    def _announce_update(self) -> None:
        last = self.settings.last_version
        if last and updater.is_newer(__version__, last):
            self._show_notice(f"FragSubs was updated to {__version__}.")
            QTimer.singleShot(8000, lambda: self.notice.hide() if "updated to" in self.notice_label.text() else None)
        if last != __version__:
            self.settings.last_version = __version__
            self._save_timer.start()

    def check_updates(self, manual: bool) -> None:
        if self._update_thread is not None:
            return
        if not manual and not self.settings.auto_update:
            return

        def work() -> None:
            try:
                self.bridge.task_done.emit("update_check", (manual, updater.check()))
            except Exception as exc:  # noqa: BLE001
                log.warning("Update check failed: %s", exc)
                self.bridge.task_done.emit("update_check", (manual, exc))

        self._update_thread = threading.Thread(target=work, daemon=True)
        self._update_thread.start()
        if manual:
            self._show_notice("Checking for updates…", busy=True)

    def _install_update(self) -> None:
        release = self._update_release
        if release is None or self._update_thread is not None:
            return
        ok, why = updater.can_self_update()
        if not ok:
            self._show_notice_action(f"{why} You can download {release.version} yourself.", "Open download page",
                                     lambda: QDesktopServices.openUrl(QUrl(release.page)))
            return
        self._cancel.clear()

        def work() -> None:
            try:
                new_dir = updater.download(
                    release, lambda done, total: self.bridge.progress.emit(
                        f"Downloading FragSubs {release.version}", done, total), self._cancel)
                self.bridge.task_done.emit("update_ready", new_dir)
            except updater.Cancelled:
                self.bridge.task_done.emit("update_ready", "cancelled")
            except Exception as exc:  # noqa: BLE001
                log.exception("Update download failed")
                self.bridge.task_done.emit("update_ready", exc)

        self._update_thread = threading.Thread(target=work, daemon=True)
        self._update_thread.start()
        self._show_notice(f"Downloading FragSubs {release.version}…", busy=True)

    def _on_update_result(self, name: str, result) -> None:
        self._update_thread = None
        self.cancel_btn.hide()
        if name == "update_check":
            manual, outcome = result
            if isinstance(outcome, Exception):
                if manual:
                    self._show_notice(f"Couldn't check for updates: {outcome}", error=True)
                return
            if outcome is None:
                if manual:
                    self._show_notice(f"You have the latest version ({__version__}).")
                return
            self._update_release = outcome
            ok, _ = updater.can_self_update()
            if not manual and ok and not self._running and self._task is None:
                self._install_update()
            else:
                self._show_notice_action(f"FragSubs {outcome.version} is available (you have {__version__}).",
                                         "Update now", self._install_update)
                if hasattr(self, "notify") and not manual and not self.isVisible():
                    self.notify(f"FragSubs {outcome.version} is available.")
            return
        if name == "update_ready":
            if result == "cancelled":
                self.notice.hide()
                return
            if isinstance(result, Exception):
                self._show_notice_action(f"The update failed: {result}", "Try again", self._install_update)
                return
            self._show_notice("Restarting to finish the update…", busy=True)
            QApplication.processEvents()
            try:
                updater.launch_installer(result)
            except Exception as exc:  # noqa: BLE001
                log.exception("Could not start the updater")
                self._show_notice(f"Couldn't start the updater: {exc}", error=True)
                return
            self.quitting = True
            self.shutdown()
            QApplication.instance().quit()

    # ================================================================== window
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.settings.minimize_to_tray and not self.quitting and getattr(self, "tray_available", False):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown and hasattr(self, "notify"):
                self._tray_hint_shown = True
                self.notify("FragSubs is still running in the system tray.")
            return
        self.shutdown()
        event.accept()
        QApplication.instance().quit()

    def shutdown(self) -> None:
        if getattr(self, "_shut_down", False):
            return
        self._shut_down = True
        self._cancel.set()
        if self.overlay.edit_mode:
            self.overlay.set_edit_mode(False)
        self.settings.save()
        if self._pipeline is not None:
            self._pipeline.stop(timeout=1.0)
            self._pipeline = None
        self.game.stop()
        self._gsi_jobs.shutdown(wait=False)
        self.overlay.close()
