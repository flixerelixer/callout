"""Glue: capture thread -> VAD -> queue -> Whisper thread -> captions.

The pipeline is UI-agnostic; the app passes callbacks that are safe to call
from worker threads (Qt signals).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import gpu_runtime, models, translit
from .config import Settings
from .engine import Caption, Skipped

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MAX_QUEUED_SEGMENTS = 3
# Live preview: translate the sentence in progress once it has this much
# audio, then again every PREVIEW_EVERY_S (slower if the GPU needs longer).
PREVIEW_MIN_S = 0.8
PREVIEW_EVERY_S = 0.5
PREVIEW_MAX_EVERY_S = 2.0


@dataclass
class Callbacks:
    status: Callable[[str], None]  # short human-readable state
    source: Callable[[str], None]  # what is being captured
    caption: Callable[[Caption], None]
    skipped: Callable[[Skipped], None]  # heard but not shown, with the reason
    level: Callable[[float, float, bool], None]  # level dBFS, speech prob, in speech
    progress: Callable[[str, int, int], None]  # label, done, total (downloads)
    error: Callable[[str], None]
    ready: Callable[[], None]  # model loaded, captions will flow
    # A sentence with a live preview on screen ended without a caption
    # (too short, or dropped to keep up): take the preview away.
    retract: Callable[[int], None] = lambda _segment_id: None


class Pipeline:
    def __init__(self, settings: Settings, device: str, callbacks: Callbacks,
                 game_map: Callable[[], str | None] = lambda: None):
        self.settings = settings
        self.device = device
        self.cb = callbacks
        # Called before each sentence: the map being played, for its callouts.
        self.game_map = game_map
        self._stop = threading.Event()
        self._segments: queue.Queue[tuple[int, np.ndarray]] = queue.Queue()
        self._threads: list[threading.Thread] = []
        # Live preview state, shared by both threads under _lock.
        self._lock = threading.Lock()
        self._preview: tuple[int, np.ndarray] | None = None  # latest sentence-so-far
        self._closed_upto = 0  # sentences up to this id have ended
        self._previewed: set[int] = set()  # ids with a preview on screen
        self._preview_lang: dict[int, str] = {}
        self._preview_every = PREVIEW_EVERY_S

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._run_capture, name="fragsubs-capture", daemon=True),
            threading.Thread(target=self._run_inference, name="fragsubs-whisper", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads = []

    @property
    def previews_on(self) -> bool:
        # Too slow on a CPU: the final captions would fall behind.
        return self.settings.live_preview and self.device == "cuda"

    @property
    def running(self) -> bool:
        """False once either worker has stopped (both are needed)."""
        return bool(self._threads) and all(t.is_alive() for t in self._threads)

    # ------------------------------------------------------------------
    def _run_capture(self) -> None:
        from .audio import CaptureManager
        from .vad import Segmenter, SegmenterConfig, SileroVAD

        s = self.settings
        try:
            vad = SileroVAD()
            seg = Segmenter(vad, SegmenterConfig(
                threshold=s.vad_threshold,
                min_speech_ms=s.min_speech_ms,
                end_silence_ms=s.end_silence_ms,
                max_segment_s=s.max_segment_s,
                filter_bangs=s.filter_bangs,
            ))
            cap = CaptureManager(s.audio_source, s.process_name, s.output_device, on_status=self.cb.source)
        except Exception as exc:  # noqa: BLE001
            log.exception("Capture setup failed")
            self._stop.set()
            self.cb.error(f"Audio setup failed: {exc}")
            return

        last_data = time.monotonic()
        last_level = 0.0
        last_preview = 0.0
        recent: list[np.ndarray] = []
        try:
            while not self._stop.is_set():
                chunk = cap.read()
                now = time.monotonic()
                if chunk is not None and chunk.size:
                    last_data = now
                    recent.append(chunk)
                    finished = seg.feed_ids(chunk)
                elif now - last_data > 0.2:
                    # Loopback delivers nothing while everything is silent; feed
                    # silence so a sentence still ends when the speaker stops.
                    gap = min(now - last_data, 1.0)
                    finished = seg.feed_ids(np.zeros(int(SAMPLE_RATE * gap), dtype=np.float32))
                    last_data = now
                else:
                    finished = []
                for segment_id, segment in finished:
                    self._close(segment_id)
                    self._enqueue(segment_id, segment)
                for segment_id, seconds in seg.dropped:
                    had_preview = self._close(segment_id)
                    if seconds >= 0.16:
                        log.info("Skipped %.1fs of speech: too short", seconds)
                        self.cb.skipped(Skipped(f"too short ({seconds:.1f} s of speech)", seconds,
                                                segment_id=segment_id))
                    elif had_preview:
                        self.cb.retract(segment_id)
                seg.dropped.clear()
                seg.short_drops.clear()
                # Live preview of the sentence still going on, when the speech
                # thread has nothing more important to do.
                if (self.previews_on and seg.current_seconds >= PREVIEW_MIN_S
                        and now - last_preview >= self._preview_every and self._segments.empty()):
                    current = seg.current()
                    if current is not None:
                        with self._lock:
                            self._preview = current
                        last_preview = now
                if now - last_level >= 0.1:
                    last_level = now
                    audio = np.concatenate(recent) if recent else np.zeros(1, dtype=np.float32)
                    recent = []
                    rms = float(np.sqrt(np.mean(np.square(audio)) + 1e-12))
                    self.cb.level(20 * np.log10(rms), seg.last_prob, seg.in_speech)
                time.sleep(0.01)
        except Exception as exc:  # noqa: BLE001
            log.exception("Capture loop crashed")
            self.cb.error(f"Audio capture stopped: {exc}")
        finally:
            cap.close()

    def _close(self, segment_id: int) -> bool:
        """A sentence ended: no more previews of it. True if one is on screen."""
        with self._lock:
            self._closed_upto = max(self._closed_upto, segment_id)
            if self._preview is not None and self._preview[0] <= segment_id:
                self._preview = None
            for old in [k for k in self._preview_lang if k <= segment_id]:
                del self._preview_lang[old]
            had = segment_id in self._previewed
            self._previewed.discard(segment_id)
            return had

    def _enqueue(self, segment_id: int, segment: np.ndarray) -> None:
        # Stay close to real time: if Whisper falls behind, drop the oldest.
        while self._segments.qsize() >= MAX_QUEUED_SEGMENTS:
            try:
                dropped_id, _ = self._segments.get_nowait()
                log.info("Dropped a queued sentence to keep up")
                self.cb.retract(dropped_id)
            except queue.Empty:
                break
        self._segments.put((segment_id, segment))

    def _take_preview(self) -> tuple[int, np.ndarray] | None:
        with self._lock:
            job, self._preview = self._preview, None
            if job is None or job[0] <= self._closed_upto:
                return None
            return job

    def _run_preview(self, translator, segment_id: int, audio: np.ndarray) -> None:
        with self._lock:
            language = self._preview_lang.get(segment_id)
        if language == "":
            return  # this sentence isn't shown live
        t0 = time.perf_counter()
        try:
            language, text = translator.preview(audio, self.settings, game_map=self.game_map(), language=language)
        except Exception as exc:  # noqa: BLE001
            log.debug("Preview failed: %s", exc)
            return
        took = time.perf_counter() - t0
        # Keep previews to well under the GPU's time, so final captions never wait long.
        self._preview_every = min(PREVIEW_MAX_EVERY_S, max(PREVIEW_EVERY_S, took * 2.0))
        with self._lock:
            if segment_id <= self._closed_upto:
                return
            if language is not None:
                self._preview_lang[segment_id] = language
            if not text:
                return
            self._previewed.add(segment_id)
            # Emitted under the lock, so a sentence that ends right now can't
            # miss that its preview needs taking away.
            self.cb.caption(Caption(language or "", text, segment_id=segment_id, partial=True,
                                    duration_s=len(audio) / SAMPLE_RATE, latency_ms=took * 1000))
        log.debug("Preview of sentence %d (%.1fs) in %.0f ms", segment_id, len(audio) / SAMPLE_RATE, took * 1000)

    # ------------------------------------------------------------------
    def _run_inference(self) -> None:
        from .engine import Translator

        s = self.settings
        if not models.is_downloaded(s.model):
            self.cb.status(f"Downloading the {s.model} model (one time)…")
            try:
                models.download(s.model, lambda done, total: self.cb.progress(f"Model {s.model}", done, total))
            except Exception as exc:  # noqa: BLE001
                log.exception("Model download failed")
                self._stop.set()
                self.cb.error(f"Could not download the {s.model} model ({exc}). Check your internet "
                              "connection and start again.")
                return
        if self._stop.is_set():
            return
        try:
            if self.device == "cuda":
                gpu_runtime.activate()
            self.cb.status("Loading the speech model…")
            translator = Translator(str(models.model_path(s.model)), self.device)
        except Exception as exc:  # noqa: BLE001
            log.exception("Model setup failed")
            self._stop.set()
            hint = ""
            if self.device == "cuda":
                hint = " Update your NVIDIA driver, or set Run on to CPU in Audio & model."
            self.cb.error(f"Could not load the speech model ({exc}).{hint}")
            return

        if self._stop.is_set():
            return
        self.cb.ready()
        while not self._stop.is_set():
            try:
                segment_id, segment = self._segments.get(timeout=0.05)
            except queue.Empty:
                job = self._take_preview() if self.previews_on else None
                if job is not None:
                    self._run_preview(translator, *job)
                continue
            try:
                caption = translator.process(segment, s, game_map=self.game_map())
            except Exception as exc:  # noqa: BLE001
                log.exception("Translation failed")
                self.cb.error(f"Translation failed: {exc}")
                self.cb.retract(segment_id)
                continue
            if caption is not None:
                caption.segment_id = segment_id
            if isinstance(caption, Skipped):
                self.cb.skipped(caption)
            elif caption is not None:
                log.info("Caption: %.1fs of speech, translated in %.0f ms", caption.duration_s,
                         caption.latency_ms)
                if caption.original:
                    caption.original_latin = translit.to_latin(caption.original, caption.language)
                # Debug level on purpose: what teammates say is not written to
                # the log file unless debug logging is switched on.
                log.debug("[%s %.0f%% %.0fms] %s | %s", caption.language, caption.confidence * 100,
                          caption.latency_ms, caption.text, caption.original)
                self.cb.caption(caption)
