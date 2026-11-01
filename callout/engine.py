"""Speech -> English text, using faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np

from . import filters
from .config import Settings

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


@dataclass
class Caption:
    language: str  # Whisper code of the spoken language
    text: str  # English
    original: str = ""  # Text in the spoken language (if enabled)
    confidence: float = 0.0
    duration_s: float = 0.0
    latency_ms: float = 0.0
    created: float = field(default_factory=time.time)


@dataclass
class Decoded:
    text: str
    avg_logprob: float
    no_speech_prob: float


class Translator:
    """Owns one WhisperModel. Use it from a single thread."""

    def __init__(self, model_dir: str, device: str):
        from faster_whisper import WhisperModel

        self.device = device
        if device == "cuda":
            # INT8 is disabled on Blackwell in CTranslate2; FP16 is fast anyway.
            compute_type = "float16"
            self.beam_size = 5
        else:
            compute_type = "int8"
            self.beam_size = 2
        log.info("Loading Whisper from %s on %s (%s)", model_dir, device, compute_type)
        t0 = time.perf_counter()
        self.model = WhisperModel(model_dir, device=device, compute_type=compute_type,
                                  cpu_threads=4 if device == "cpu" else 0, num_workers=1)
        log.info("Model loaded in %.1fs", time.perf_counter() - t0)
        # Warm up so the first real sentence is not slow.
        try:
            self.model.detect_language(np.zeros(SAMPLE_RATE, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            log.debug("warm-up failed: %s", exc)

    def _decode(self, audio: np.ndarray, language: str, task: str, hint: str,
                temperature: tuple[float, ...] = (0.0, 0.2, 0.4)) -> Decoded:
        segments, _info = self.model.transcribe(
            audio,
            language=language,
            task=task,
            beam_size=self.beam_size,
            temperature=temperature,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            initial_prompt=hint or None,
        )
        texts: list[str] = []
        logprobs: list[float] = []
        no_speech = 0.0
        for seg in segments:
            # Same rule Whisper uses to call a window "silence".
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
                continue
            if seg.compression_ratio > 2.4:
                continue
            texts.append(seg.text)
            logprobs.append(seg.avg_logprob)
            no_speech = max(no_speech, seg.no_speech_prob)
        text = filters.clean_text(" ".join(texts))
        avg = float(np.mean(logprobs)) if logprobs else -10.0
        return Decoded(text, avg, no_speech)

    def process(self, audio: np.ndarray, settings: Settings) -> Caption | None:
        t0 = time.perf_counter()
        duration = len(audio) / SAMPLE_RATE
        _lang, _p, all_probs = self.model.detect_language(audio)
        language, confidence = filters.choose_language(
            all_probs, min_confidence=settings.min_language_confidence
        )
        if language is None:
            log.debug("Skipped %.1fs clip: language unclear", duration)
            return None
        if language == "en":
            if not settings.show_english:
                return None
            task = "transcribe"
        elif language in settings.enabled_languages():
            task = "translate"
        else:
            log.debug("Skipped %.1fs clip in %s (switched off)", duration, language)
            return None

        hint = settings.vocabulary_hint.strip()
        english = self._decode(audio, language, task, hint)
        if task == "translate" and filters.looks_untranslated(english.text):
            # Whisper sometimes answers in the spoken language; one retry with
            # sampling usually gets English out of it.
            log.debug("Untranslated output %r; retrying", english.text)
            english = self._decode(audio, language, task, hint, temperature=(0.3, 0.6))
            if filters.looks_untranslated(english.text):
                return None
        if not english.text or filters.is_hallucination(
            english.text, avg_logprob=english.avg_logprob,
            no_speech_prob=english.no_speech_prob, hint=hint,
        ):
            log.debug("Dropped likely hallucination: %r", english.text)
            return None
        if english.avg_logprob < -1.2:
            log.debug("Dropped low-confidence output: %r (%.2f)", english.text, english.avg_logprob)
            return None

        original = ""
        if settings.show_original and language != "en":
            # No hint here: an English prompt nudges Whisper into English.
            native = self._decode(audio, language, "transcribe", "")
            if native.text and not filters.is_hallucination(
                native.text, avg_logprob=native.avg_logprob, no_speech_prob=native.no_speech_prob
            ):
                original = native.text

        return Caption(
            language=language,
            text=english.text,
            original=original,
            confidence=confidence,
            duration_s=duration,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
