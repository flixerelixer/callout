"""Routing logic of the Translator, with a fake Whisper model."""

from types import SimpleNamespace

import numpy as np

from fragsubs.config import Settings
from fragsubs.engine import Caption, Skipped, Translator


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
        text, logprob, nsp = self.outputs.get((language, task)) or self.outputs[task]
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
    skipped = t.process(AUDIO, Settings())
    assert isinstance(skipped, Skipped) and "English" in skipped.reason
    s = Settings(show_english=True)
    cap = t.process(AUDIO, s)
    assert isinstance(cap, Caption) and cap.text == "Rotate A." and cap.original == ""


def test_switched_off_language_is_skipped():
    t = make([("nl", 0.9)], {"translate": ("Hello", -0.1, 0.0), "transcribe": ("Hallo", -0.1, 0.0)})
    skipped = t.process(AUDIO, Settings())  # Dutch is off by default
    assert isinstance(skipped, Skipped) and "Dutch is switched off" in skipped.reason
    assert isinstance(t.process(AUDIO, Settings(languages=["nl"])), Caption)


def test_hallucination_is_dropped():
    t = make([("ru", 0.9)], {"translate": ("Thanks for watching!", -0.3, 0.1),
                             "transcribe": ("Продолжение следует...", -0.3, 0.1)})
    skipped = t.process(AUDIO, Settings())
    assert isinstance(skipped, Skipped) and "noise" in skipped.reason


def test_low_confidence_output_is_dropped():
    t = make([("de", 0.9)], {"translate": ("Something garbled", -1.5, 0.1)})
    skipped = t.process(AUDIO, Settings())
    assert isinstance(skipped, Skipped) and "unclear" in skipped.reason


def test_greeting_with_split_vote_is_translated():
    t = make([("ru", 0.40), ("uk", 0.30), ("bg", 0.12), ("en", 0.08)],
             {"translate": ("Hi!", -0.3, 0.05), "transcribe": ("Привет!", -0.3, 0.05)})
    cap = t.process(np.zeros(8000, dtype=np.float32), Settings())
    assert isinstance(cap, Caption) and cap.text == "Hi!" and cap.language == "ru"


UNSURE = [("no", 0.38), ("en", 0.32), ("ru", 0.22)]  # quick check: Norwegian 41%, too unsure


def test_unclear_clip_is_resolved_by_trying_languages():
    t = make(UNSURE, {
        ("no", "transcribe"): ("To på B", -1.3, 0.1),
        ("en", "transcribe"): ("Two on B", -0.9, 0.1),     # Whisper translating, not transcribing
        ("ru", "transcribe"): ("Двое на Б", -0.3, 0.05),
        ("ru", "translate"): ("Two on B", -0.3, 0.05),
    })
    cap = t.process(AUDIO, Settings())
    assert isinstance(cap, Caption) and cap.language == "ru" and cap.text == "Two on B"
    assert cap.original == "Двое на Б"  # the trial transcript is reused, no extra pass
    assert ("ru", "translate") in [c[:2] for c in t.model.calls]


def test_unclear_clip_with_no_good_trial_is_skipped():
    t = make(UNSURE, {"transcribe": ("mmh", -1.8, 0.4)})
    skipped = t.process(AUDIO, Settings())
    assert isinstance(skipped, Skipped) and "couldn't make out the words" in skipped.reason
    assert "Norwegian" in skipped.reason and "Russian" in skipped.reason


def test_wrong_alphabet_counts_against_a_language():
    # Forced to English, Whisper wrote Cyrillic: that's not English speech.
    t = make(UNSURE, {
        ("no", "transcribe"): ("", -2.0, 0.5),
        ("en", "transcribe"): ("Двое на Б", -0.35, 0.05),
        ("ru", "transcribe"): ("Двое на Б", -0.4, 0.05),
        ("ru", "translate"): ("Two on B", -0.3, 0.05),
    })
    cap = t.process(AUDIO, Settings())
    assert isinstance(cap, Caption) and cap.language == "ru"


def test_language_heard_recently_wins_close_calls():
    outputs = {
        ("no", "transcribe"): ("", -2.0, 0.5),
        ("en", "transcribe"): ("Go mid", -0.50, 0.05),
        ("ru", "transcribe"): ("Гоу мид", -0.55, 0.05),
        ("ru", "translate"): ("Go mid", -0.4, 0.05),
    }
    fresh = make(UNSURE, outputs)
    assert isinstance(fresh.process(AUDIO, Settings()), Skipped)  # English wins, English is off
    t = make(UNSURE, outputs)
    t._remember("ru")  # a teammate spoke Russian a minute ago
    cap = t.process(AUDIO, Settings())
    assert isinstance(cap, Caption) and cap.language == "ru"


MIXED = [("en", 0.80), ("ru", 0.15), ("uk", 0.02)]
LESSON = "Say меня зовут and then your name."


def test_russian_words_in_english_are_translated():
    t = make(MIXED, {("en", "transcribe"): (LESSON, -0.2, 0.01),
                     ("ru", "translate"): ("Say my name is and then your name.", -0.3, 0.01)})
    cap = t.process(AUDIO, Settings())  # English captions off: still translated
    assert isinstance(cap, Caption)
    assert cap.language == "ru" and cap.text == "Say my name is and then your name."
    assert cap.original == LESSON
    assert [c[:2] for c in t.model.calls] == [("en", "transcribe"), ("ru", "translate")]


def test_mixed_words_need_the_language_switched_on():
    t = make(MIXED, {("en", "transcribe"): (LESSON, -0.2, 0.01)})
    skipped = t.process(AUDIO, Settings(languages=["de"]))
    assert isinstance(skipped, Skipped) and "English" in skipped.reason


def test_plain_english_costs_nothing_when_english_is_off():
    t = make([("en", 0.97), ("de", 0.01)], {"transcribe": ("Rotate B.", -0.1, 0.0)})
    skipped = t.process(AUDIO, Settings())
    assert isinstance(skipped, Skipped) and t.model.calls == []


def test_plain_english_with_a_foreign_vote_is_still_skipped():
    t = make(MIXED, {("en", "transcribe"): ("Rotate B, rotate.", -0.2, 0.01)})
    skipped = t.process(AUDIO, Settings())
    assert isinstance(skipped, Skipped) and "English" in skipped.reason


def test_original_lines_modes():
    cap = Caption("ru", "Hi!", "Привет!", original_latin="Privet!")
    assert cap.original_lines("native") == ["Привет!"]
    assert cap.original_lines("latin") == ["Privet!"]
    assert cap.original_lines("both") == ["Привет!", "Privet!"]
    plain = Caption("pl", "Save it", "Sejwuj")  # already Latin: nothing extra
    assert plain.original_lines("both") == ["Sejwuj"] and plain.original_lines("latin") == ["Sejwuj"]
    assert Caption("ru", "Hi").original_lines("both") == []
