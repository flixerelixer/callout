"""Speech -> English text, using faster-whisper (CTranslate2)."""

from __future__ import annotations

import collections
import logging
import time
from dataclasses import dataclass, field

import numpy as np

from . import filters, languages
from .config import Settings

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


@dataclass
class Caption:
    language: str  # Whisper code of the spoken language
    text: str  # English
    original: str = ""  # Text in the spoken language (if enabled)
    original_latin: str = ""  # The same in Latin letters, if it uses another alphabet
    confidence: float = 0.0
    duration_s: float = 0.0
    latency_ms: float = 0.0
    created: float = field(default_factory=time.time)

    def original_lines(self, mode: str) -> list[str]:
        """Original words to show: mode is "native", "latin" or "both"."""
        if not self.original:
            return []
        latin = self.original_latin
        if mode == "latin":
            return [latin or self.original]
        if mode == "both" and latin and latin != self.original:
            return [self.original, latin]
        return [self.original]


@dataclass
class Skipped:
    """Speech that was heard but not shown, and why (for the Live log)."""

    reason: str
    duration_s: float = 0.0
    language: str = ""
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
        # Languages heard clearly in the last few minutes. Teammates don't
        # switch languages, so this breaks ties on short, unclear clips.
        self._recent: collections.deque[tuple[float, str]] = collections.deque(maxlen=20)
        # Warm up so the first real sentence is not slow.
        try:
            self.model.detect_language(np.zeros(SAMPLE_RATE, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            log.debug("warm-up failed: %s", exc)

    def _decode(self, audio: np.ndarray, language: str, task: str, hint: str,
                temperature: tuple[float, ...] = (0.0, 0.2, 0.4), beam_size: int | None = None) -> Decoded:
        segments, _info = self.model.transcribe(
            audio,
            language=language,
            task=task,
            beam_size=beam_size or self.beam_size,
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

    RECENT_S = 180.0
    RECENT_BONUS = 0.1

    def recent_languages(self, now: float | None = None) -> set[str]:
        now = time.monotonic() if now is None else now
        recent = getattr(self, "_recent", None) or ()
        return {lang for t, lang in recent if now - t <= self.RECENT_S}

    def _remember(self, language: str) -> None:
        if not hasattr(self, "_recent"):
            self._recent = collections.deque(maxlen=20)
        self._recent.append((time.monotonic(), language))

    def _try_languages(self, audio: np.ndarray, all_probs, enabled: set[str]) -> tuple[str, Decoded, list[str]]:
        """Whisper's quick language check is unsure: transcribe the clip as
        each likely language and keep the one that gives the most confident
        words. Much more reliable than the quick check on short clips."""
        recent = self.recent_languages()
        candidates = filters.top_candidates(all_probs, n=3)
        for lang in sorted(recent):
            if lang in enabled and lang not in candidates:
                candidates.append(lang)
        best: tuple[float, str, Decoded] | None = None
        for lang in candidates:
            out = self._decode(audio, lang, "transcribe", "", temperature=(0.0,), beam_size=1)
            score = out.avg_logprob
            if not out.text or filters.is_hallucination(out.text, avg_logprob=out.avg_logprob,
                                                        no_speech_prob=out.no_speech_prob):
                score -= 5.0
            if filters.wrong_script(out.text, lang):
                score -= 1.0
            if lang in recent:
                score += self.RECENT_BONUS
            log.debug("Trial %s: %.2f", lang, score)
            if best is None or score > best[0]:
                best = (score, lang, out)
        if best is None:
            return "", Decoded("", -10.0, 1.0), candidates
        score, lang, out = best
        if score < -1.0:
            return "", out, candidates
        return lang, out, candidates

    def process(self, audio: np.ndarray, settings: Settings) -> Caption | Skipped:
        t0 = time.perf_counter()
        duration = len(audio) / SAMPLE_RATE
        enabled = settings.enabled_languages()
        hint = settings.vocabulary_hint.strip()

        def skip(reason: str, language: str = "", log_reason: str = "") -> Skipped:
            # The log gets the reason without anything that was said.
            log.info("Skipped %.1fs of speech: %s", duration, log_reason or reason)
            return Skipped(reason, duration, language)

        def check(out: Decoded, language: str) -> Skipped | None:
            if not out.text:
                return skip("no words recognised", language)
            if filters.is_hallucination(out.text, avg_logprob=out.avg_logprob,
                                        no_speech_prob=out.no_speech_prob, hint=hint):
                return skip(f"ignored “{out.text}” as likely noise", language, "likely noise")
            if out.avg_logprob < -1.2:
                return skip(f"too unclear to translate (heard “{out.text}”)", language, "too unclear")
            return None

        def caption(language: str, text: str, original: str, confidence: float) -> Caption:
            return Caption(language=language, text=text, original=original, confidence=confidence,
                           duration_s=duration, latency_ms=(time.perf_counter() - t0) * 1000)

        def translate(language: str, confidence: float, original: str | None = None) -> Caption | Skipped:
            english = self._decode(audio, language, "translate", hint)
            if filters.looks_untranslated(english.text):
                # Whisper sometimes answers in the spoken language; one retry with
                # sampling usually gets English out of it.
                log.debug("Untranslated output; retrying")
                english = self._decode(audio, language, "translate", hint, temperature=(0.3, 0.6))
                if filters.looks_untranslated(english.text):
                    return skip("Whisper didn't translate it", language)
            problem = check(english, language)
            if problem:
                return problem
            if original is None:
                original = ""
                if settings.show_original:
                    # No hint here: an English prompt nudges Whisper into English.
                    native = self._decode(audio, language, "transcribe", "")
                    if native.text and not filters.is_hallucination(
                        native.text, avg_logprob=native.avg_logprob, no_speech_prob=native.no_speech_prob
                    ):
                        original = native.text
            return caption(language, english.text, original if settings.show_original else "", confidence)

        _lang, _p, all_probs = self.model.detect_language(audio)
        language, confidence, guess = filters.choose_language(
            all_probs, enabled, min_confidence=settings.min_language_confidence
        )
        heard: Decoded | None = None  # a transcript we already have, if any
        if language is None:
            language, heard, tried = self._try_languages(audio, all_probs, enabled)
            if not language:
                names = ", ".join(languages.display_name(c) for c in tried) or "nothing likely"
                return skip(f"couldn't make out the words (tried {names})", guess)
            log.info("Unclear clip resolved as %s by trial transcription", language)

        if language != "en":
            if language not in enabled:
                return skip(f"{languages.display_name(language)} is switched off under Languages", language)
            original = heard.text if heard is not None and settings.show_original else None
            result = translate(language, confidence, original=original)
            if isinstance(result, Caption):
                self._remember(language)
            return result

        # English, possibly with words from another language mixed in
        # ("меня зовут means my name is"). Only worth a look when one of your
        # languages got some of the vote, or when English is captioned anyway.
        if not settings.show_english and filters.enabled_share(all_probs, enabled) < 0.05:
            return skip("English (captioning English is off)", "en")
        if heard is None:
            heard = self._decode(audio, "en", "transcribe", hint)
        foreign = filters.mixed_language(heard.text, all_probs, enabled)
        if foreign:
            mixed = translate(foreign, confidence, original=heard.text)
            if isinstance(mixed, Caption):
                self._remember(foreign)
                return mixed
        if not settings.show_english:
            return skip("English (captioning English is off)", "en")
        problem = check(heard, "en")
        if problem:
            return problem
        return caption("en", heard.text, "", confidence)
