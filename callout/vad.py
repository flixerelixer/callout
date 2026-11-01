"""Streaming voice activity detection.

Uses the Silero VAD model that ships inside faster-whisper, run frame by frame
so speech can be cut into sentences as it happens. Gunshots, footsteps and
music mostly score low, so they never reach Whisper.
"""

from __future__ import annotations

import collections
import os
from dataclasses import dataclass
from typing import Callable

import numpy as np

SAMPLE_RATE = 16000
FRAME = 512  # 32 ms at 16 kHz, what Silero expects
CONTEXT = 64


class SileroVAD:
    """Frame-by-frame Silero VAD that keeps its LSTM state between calls."""

    def __init__(self, model_path: str | None = None):
        import onnxruntime

        if model_path is None:
            from faster_whisper.utils import get_assets_path

            model_path = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"], sess_options=opts
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)

    def __call__(self, frames: np.ndarray) -> np.ndarray:
        """frames: (n, 512) float32. Returns n speech probabilities."""
        n = frames.shape[0]
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        contexts = np.empty((n, CONTEXT), dtype=np.float32)
        contexts[0] = self._context
        if n > 1:
            contexts[1:] = frames[:-1, -CONTEXT:]
        batch = np.concatenate([contexts, frames], axis=1).astype(np.float32)
        out, self._h, self._c = self._session.run(None, {"input": batch, "h": self._h, "c": self._c})
        self._context = frames[-1, -CONTEXT:].copy()
        return np.asarray(out, dtype=np.float32).reshape(-1)[:n]


@dataclass
class SegmenterConfig:
    threshold: float = 0.5
    min_speech_ms: int = 200
    # Quiet needed to end a sentence...
    end_silence_ms: int = 450
    # ...but once someone has talked this long, a short breath is enough, so
    # back-to-back sentences become separate captions instead of one block.
    soft_segment_s: float = 2.5
    soft_silence_ms: int = 200
    # Hard limit: cut at the quietest moment of the last second.
    max_segment_s: float = 6.0
    pre_roll_ms: int = 250
    tail_pad_ms: int = 150


class Segmenter:
    """Turns a stream of 16 kHz audio into finished speech segments.

    ``prob_fn`` maps (n, 512) frames to n speech probabilities; it is the
    Silero model in the app and a stub in tests.
    """

    def __init__(self, prob_fn: Callable[[np.ndarray], np.ndarray], config: SegmenterConfig | None = None):
        self.prob_fn = prob_fn
        self.cfg = config or SegmenterConfig()
        ms_per_frame = FRAME * 1000 / SAMPLE_RATE

        def frames(ms: float) -> int:
            return max(1, round(ms / ms_per_frame))

        self._min_speech = frames(self.cfg.min_speech_ms)
        self._end_silence = frames(self.cfg.end_silence_ms)
        self._soft_frames = frames(self.cfg.soft_segment_s * 1000)
        self._soft_silence = min(self._end_silence, frames(self.cfg.soft_silence_ms))
        self._max_frames = max(8, frames(self.cfg.max_segment_s * 1000))
        self._cut_window = min(frames(1000), self._max_frames // 2)
        self._tail_pad = max(0, round(self.cfg.tail_pad_ms / ms_per_frame))
        self._neg_threshold = max(0.05, self.cfg.threshold - 0.15)
        self._pre_roll: collections.deque[tuple[np.ndarray, float]] = collections.deque(
            maxlen=frames(self.cfg.pre_roll_ms)
        )
        self._pending = np.zeros(0, dtype=np.float32)
        self._frames: list[np.ndarray] = []
        self._probs: list[float] = []
        self._silence_run = 0
        self.in_speech = False
        self.last_prob = 0.0
        # Seconds of speech in segments dropped for being too short, so the
        # app can show them as skipped. The caller empties this list.
        self.short_drops: list[float] = []

    def feed(self, audio: np.ndarray) -> list[np.ndarray]:
        """Add audio; return any segments that just finished."""
        if audio.size:
            self._pending = np.concatenate([self._pending, audio.astype(np.float32, copy=False)])
        n = len(self._pending) // FRAME
        if n == 0:
            return []
        frames = self._pending[: n * FRAME].reshape(n, FRAME)
        self._pending = self._pending[n * FRAME:]
        probs = self.prob_fn(frames)
        done: list[np.ndarray] = []
        for frame, prob in zip(frames, probs):
            self.last_prob = float(prob)
            segment = self._step(frame, float(prob))
            if segment is not None:
                done.append(segment)
        return done

    def _step(self, frame: np.ndarray, prob: float) -> np.ndarray | None:
        if not self.in_speech:
            if prob >= self.cfg.threshold:
                self.in_speech = True
                self._frames = [f for f, _ in self._pre_roll] + [frame]
                self._probs = [p for _, p in self._pre_roll] + [prob]
                self._pre_roll.clear()
                self._silence_run = 0
            else:
                self._pre_roll.append((frame, prob))
            return None

        self._frames.append(frame)
        self._probs.append(prob)
        long = len(self._frames) >= self._soft_frames
        # Short sentences end on real quiet; long talk also ends on a dip
        # below the speech threshold (game noise can keep Silero at ~0.4).
        quiet = prob < (self.cfg.threshold if long else self._neg_threshold)
        self._silence_run = self._silence_run + 1 if quiet else 0

        if self._silence_run >= (self._soft_silence if long else self._end_silence):
            keep = len(self._frames) - self._silence_run + self._tail_pad
            return self._finish(keep)
        if len(self._frames) >= self._max_frames:
            # Nonstop talk: cut at the quietest moment of the last second and
            # carry the rest over as the start of the next segment.
            window = self._probs[-self._cut_window:]
            cut = len(self._probs) - len(window) + int(np.argmin(window)) + 1
            rest_frames, rest_probs = self._frames[cut:], self._probs[cut:]
            segment = self._finish(cut)
            if rest_frames:
                self.in_speech = True
                self._frames, self._probs = rest_frames, rest_probs
            return segment
        return None

    def _finish(self, keep_frames: int) -> np.ndarray | None:
        keep = max(1, min(keep_frames, len(self._frames)))
        frames = self._frames[:keep]
        speech_frames = sum(1 for p in self._probs[:keep] if p >= self.cfg.threshold)
        self._frames = []
        self._probs = []
        self._silence_run = 0
        self.in_speech = False
        if speech_frames < self._min_speech:
            if speech_frames >= 3:  # ignore single clicks and shots
                self.short_drops.append(speech_frames * FRAME / SAMPLE_RATE)
            return None
        return np.concatenate(frames)

    def flush(self) -> np.ndarray | None:
        """Finish whatever is in progress (e.g. when stopping)."""
        if not self.in_speech:
            return None
        return self._finish(len(self._frames))
