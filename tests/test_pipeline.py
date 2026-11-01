"""Live preview bookkeeping in the pipeline (no audio, no threads)."""

import numpy as np

from fragsubs.config import Settings
from fragsubs.pipeline import Callbacks, Pipeline


class FakeTranslator:
    def __init__(self, text="Two in Palace"):
        self.text = text
        self.calls = []

    def preview(self, audio, settings, game_map=None, language=None):
        self.calls.append(language)
        return "ru", self.text


def make(device="cuda", **settings):
    events = []
    cb = Callbacks(status=lambda *_: None, source=lambda *_: None,
                   caption=lambda c: events.append(("caption", c)),
                   skipped=lambda s: events.append(("skipped", s)),
                   level=lambda *_: None, progress=lambda *_: None, error=lambda *_: None,
                   ready=lambda: None, retract=lambda sid: events.append(("retract", sid)))
    return Pipeline(Settings(**settings), device, cb, game_map=lambda: "de_mirage"), events


AUDIO = np.zeros(16000, dtype=np.float32)


def test_preview_is_shown_as_a_partial_caption():
    p, events = make()
    p._preview = (3, AUDIO)
    job = p._take_preview()
    t = FakeTranslator()
    p._run_preview(t, *job)
    (kind, cap), = events
    assert kind == "caption" and cap.partial and cap.segment_id == 3 and cap.text == "Two in Palace"
    # The language is remembered for the next preview of the same sentence.
    p._preview = (3, AUDIO)
    p._run_preview(t, *p._take_preview())
    assert t.calls == [None, "ru"]


def test_no_preview_after_the_sentence_ended():
    p, events = make()
    p._preview = (3, AUDIO)
    assert p._close(3) is False
    assert p._take_preview() is None
    p._run_preview(FakeTranslator(), 3, AUDIO)  # one that was already running
    assert events == []


def test_ending_reports_a_preview_on_screen():
    p, _ = make()
    p._run_preview(FakeTranslator(), 5, AUDIO)
    assert p._close(5) is True and p._close(5) is False


def test_previews_need_a_gpu_and_the_setting():
    assert make("cuda")[0].previews_on
    assert not make("cpu")[0].previews_on
    assert not make("cuda", live_preview=False)[0].previews_on


def test_dropping_a_queued_sentence_takes_its_preview_away():
    p, events = make()
    for sid in range(1, 5):
        p._enqueue(sid, AUDIO)
    assert ("retract", 1) in events and p._segments.qsize() == 3
