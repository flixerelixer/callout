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


class Pipeline:
    def __init__(self, settings: Settings, device: str, callbacks: Callbacks):
        self.settings = settings
        self.device = device
        self.cb = callbacks
        self._stop = threading.Event()
        self._segments: queue.Queue[np.ndarray] = queue.Queue()
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._run_capture, name="callout-capture", daemon=True),
            threading.Thread(target=self._run_inference, name="callout-whisper", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads = []

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
        recent: list[np.ndarray] = []
        try:
            while not self._stop.is_set():
                chunk = cap.read()
                now = time.monotonic()
                if chunk is not None and chunk.size:
                    last_data = now
                    recent.append(chunk)
                    finished = seg.feed(chunk)
                elif now - last_data > 0.2:
                    # Loopback delivers nothing while everything is silent; feed
                    # silence so a sentence still ends when the speaker stops.
                    gap = min(now - last_data, 1.0)
                    finished = seg.feed(np.zeros(int(SAMPLE_RATE * gap), dtype=np.float32))
                    last_data = now
                else:
                    finished = []
                for segment in finished:
                    self._enqueue(segment)
                for seconds in seg.short_drops:
                    log.info("Skipped %.1fs of speech: too short", seconds)
                    self.cb.skipped(Skipped(f"too short ({seconds:.1f} s of speech)", seconds))
                seg.short_drops.clear()
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

    def _enqueue(self, segment: np.ndarray) -> None:
        # Stay close to real time: if Whisper falls behind, drop the oldest.
        while self._segments.qsize() >= MAX_QUEUED_SEGMENTS:
            try:
                self._segments.get_nowait()
                log.info("Dropped a queued sentence to keep up")
            except queue.Empty:
                break
        self._segments.put(segment)

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
                segment = self._segments.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                caption = translator.process(segment, s)
            except Exception as exc:  # noqa: BLE001
                log.exception("Translation failed")
                self.cb.error(f"Translation failed: {exc}")
                continue
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
