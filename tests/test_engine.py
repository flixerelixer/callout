"""Routing logic of the Translator, with a fake Whisper model."""

from types import SimpleNamespace

import numpy as np

from callout.config import Settings
from callout.engine import Translator


class FakeModel:
    def __init__(self, lang_probs, outputs):
        self.lang_probs = lang_probs
        self.outputs = outputs  # task -> (text, avg_logprob, no_speech_prob)
        self.calls = []

    def detect_language(self, audio):
        top = max(self.lang_probs, key=lambda x: x[1])
        return top[0], top[1], self.lang_probs

    def transcribe(self, audio, language, task, **kw):
        self.calls.append((language, task, kw.get("initial_prompt")))
        text, logprob, nsp = self.outputs[task]
        seg = SimpleNamespace(text=text, avg_logprob=logprob, no_speech_prob=nsp, compression_ratio=1.2)
        return iter([seg]), None


def make(lang_probs, outputs):
    t = Translator.__new__(Translator)
    t.device = "cpu"
    t.beam_size = 1
    t.model = FakeModel(lang_probs, outputs)
    return t


AUDIO = np.zeros(16000 * 2, dtype=np.float32)


def test_russian_is_translated_with_original():
    t = make([("ru", 0.95), ("en", 0.02)], {
        "translate": (" Two on B.", -0.2, 0.01),
        "transcribe": (" Двое на Б.", -0.2, 0.01),
    })
    cap = t.process(AUDIO, Settings())
    assert cap is not None
    assert cap.language == "ru" and cap.text == "Two on B." and cap.original == "Двое на Б."
    tasks = [c[1] for c in t.model.calls]
    assert tasks == ["translate", "transcribe"]
    # The English vocabulary hint is only used for the English output.
    assert t.model.calls[0][2] and t.model.calls[1][2] is None


def test_english_is_skipped_by_default():
    t = make([("en", 0.9)], {"transcribe": ("Rotate A.", -0.1, 0.0)})
    assert t.process(AUDIO, Settings()) is None
    s = Settings(show_english=True)
    cap = t.process(AUDIO, s)
    assert cap is not None and cap.text == "Rotate A." and cap.original == ""


def test_switched_off_language_is_skipped():
    t = make([("nl", 0.9)], {"translate": ("Hello", -0.1, 0.0), "transcribe": ("Hallo", -0.1, 0.0)})
    assert t.process(AUDIO, Settings()) is None  # Dutch is off by default
    assert t.process(AUDIO, Settings(languages=["nl"])) is not None


def test_hallucination_is_dropped():
    t = make([("ru", 0.9)], {"translate": ("Thanks for watching!", -0.3, 0.1),
                             "transcribe": ("Продолжение следует...", -0.3, 0.1)})
    assert t.process(AUDIO, Settings()) is None


def test_low_confidence_output_is_dropped():
    t = make([("de", 0.9)], {"translate": ("Something garbled", -1.5, 0.1)})
    assert t.process(AUDIO, Settings()) is None
