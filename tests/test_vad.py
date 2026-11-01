import numpy as np
import pytest

from callout.vad import FRAME, SAMPLE_RATE, Segmenter, SegmenterConfig


def stub_from_mask(mask):
    """Probability function that replays a per-frame speech mask."""
    it = iter(mask)

    def fn(frames):
        return np.array([next(it, 0.0) for _ in range(len(frames))], dtype=np.float32)

    return fn


def frames_for(seconds):
    return round(seconds * SAMPLE_RATE / FRAME)


def run(mask, cfg=None, chunk=480):
    seg = Segmenter(stub_from_mask(mask), cfg or SegmenterConfig())
    audio = np.random.default_rng(0).normal(0, 0.01, len(mask) * FRAME).astype(np.float32)
    out = []
    for i in range(0, len(audio), chunk):
        out += seg.feed(audio[i:i + chunk])
    return out, seg


def test_one_sentence_is_one_segment():
    mask = [0.0] * frames_for(1) + [0.9] * frames_for(2) + [0.0] * frames_for(1)
    out, _ = run(mask)
    assert len(out) == 1
    dur = len(out[0]) / SAMPLE_RATE
    # 2 s of speech + pre-roll + tail pad, minus nothing
    assert 2.0 <= dur <= 2.7


def test_short_blip_is_ignored_but_reported():
    mask = [0.0] * 20 + [0.9] * 5 + [0.0] * 40  # 160 ms of "speech": too short, worth listing
    out, seg = run(mask)
    assert out == []
    assert len(seg.short_drops) == 1 and 0.15 < seg.short_drops[0] < 0.17


def test_clicks_are_not_even_listed():
    mask = [0.0] * 20 + [0.9] * 3 + [0.0] * 40  # 0.1 s: a click
    out, seg = run(mask)
    assert out == [] and seg.short_drops == []


def test_short_greeting_is_kept():
    # "привет": about 0.3 s of clearly voiced frames
    mask = [0.0] * 20 + [0.2, 0.6] + [0.9] * 8 + [0.5, 0.2] + [0.0] * 40
    out, seg = run(mask)
    assert len(out) == 1 and seg.short_drops == []


def test_brief_dip_does_not_split_sentence():
    mask = [0.0] * 10 + [0.9] * 30 + [0.2] * 8 + [0.9] * 30 + [0.0] * 40
    out, _ = run(mask)
    assert len(out) == 1


def test_long_monologue_is_cut():
    cfg = SegmenterConfig(max_segment_s=3.0)
    mask = [0.9] * frames_for(7) + [0.0] * 40
    out, _ = run(mask, cfg)
    assert len(out) >= 2
    assert all(len(s) / SAMPLE_RATE <= 3.1 for s in out)


def test_flush_returns_unfinished_speech():
    mask = [0.9] * frames_for(1)
    out, seg = run(mask)
    assert out == []
    rest = seg.flush()
    assert rest is not None and len(rest) >= SAMPLE_RATE * 0.9


def test_streaming_silero_matches_batch():
    pytest.importorskip("onnxruntime")
    from faster_whisper.vad import get_vad_model

    from callout.vad import SileroVAD

    rng = np.random.default_rng(1)
    t = np.arange(SAMPLE_RATE * 3) / SAMPLE_RATE
    # Something speech-ish: modulated harmonics plus noise.
    audio = (0.2 * np.sin(2 * np.pi * 180 * t) * (1 + np.sin(2 * np.pi * 4 * t))
             + 0.02 * rng.normal(size=t.size)).astype(np.float32)
    n = len(audio) // FRAME
    ref = get_vad_model()(audio[: n * FRAME]).reshape(-1)[:n]
    vad = SileroVAD()
    got, pos = [], 0
    while pos < n:
        k = min(int(rng.integers(1, 6)), n - pos)
        got.append(vad(audio[pos * FRAME:(pos + k) * FRAME].reshape(k, FRAME)))
        pos += k
    assert np.allclose(np.concatenate(got), ref, atol=1e-5)


def test_back_to_back_sentences_become_separate_captions():
    # Four 1.2 s sentences with 0.3 s pauses where game noise keeps the
    # detector at 0.4: this used to come out as one 6+ s block.
    sentence, pause = [0.9] * frames_for(1.2), [0.4] * frames_for(0.3)
    mask = [0.0] * 10 + (sentence + pause) * 4 + [0.0] * 40
    out, _ = run(mask)
    assert len(out) >= 2
    assert all(len(s) / SAMPLE_RATE <= 4.5 for s in out)


def test_short_sentence_ends_quickly():
    # 1 s of speech, then silence: the segment is done within ~0.5 s.
    mask = [0.0] * 10 + [0.9] * frames_for(1.0) + [0.0] * 60
    seg = Segmenter(stub_from_mask(mask), SegmenterConfig())
    audio = np.zeros(len(mask) * FRAME, dtype=np.float32)
    done_at = None
    for i in range(0, len(audio), FRAME):
        if seg.feed(audio[i:i + FRAME]) and done_at is None:
            done_at = i / SAMPLE_RATE
    speech_end = (10 + frames_for(1.0)) * FRAME / SAMPLE_RATE
    assert done_at is not None and done_at - speech_end <= 0.5


def test_nonstop_talk_is_cut_at_the_quietest_moment():
    cfg = SegmenterConfig(max_segment_s=3.0, soft_segment_s=10.0)
    # Speech with a slight dip (0.45, still "speech" for the soft rule) every second.
    second = [0.9] * 28 + [0.45] * 3
    mask = second * 5 + [0.0] * 40
    out, _ = run(mask, cfg)
    assert len(out) >= 2
    first = len(out[0]) // FRAME
    # The cut lands just after one of the dips, not in the middle of a word.
    assert first % 31 in (29, 30, 31, 0, 1)


def _gunfire(seconds, rate=8, seed=0):
    rng = np.random.default_rng(seed)
    x = np.zeros(int(seconds * SAMPLE_RATE), np.float32)
    t = np.arange(4000)
    for k in range(int(seconds * rate)):
        s = int(k * SAMPLE_RATE / rate)
        burst = rng.normal(0, 1, 4000) * np.exp(-t / 500)
        x[s:s + 4000] += burst[: len(x[s:s + 4000])].astype(np.float32)
    return 0.9 * x / np.abs(x).max()


def _voice(seconds):
    """A pitched, voice-like sound (harmonics of 150 Hz with a 4 Hz wobble)."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    x = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 6)) * (1 + 0.3 * np.sin(2 * np.pi * 4 * t))
    return (0.2 * x / np.abs(x).max()).astype(np.float32)


def test_bang_filter_flags_gunfire_but_not_voice():
    from callout.vad import BangFilter

    gun = _gunfire(2)
    flags = BangFilter()(gun[: len(gun) // FRAME * FRAME].reshape(-1, FRAME))
    assert flags.mean() > 0.3
    quiet_then_voice = np.concatenate([np.zeros(SAMPLE_RATE // 2, np.float32), _voice(1.5)])
    flags = BangFilter()(quiet_then_voice[: len(quiet_then_voice) // FRAME * FRAME].reshape(-1, FRAME))
    assert flags.sum() == 0


def test_gunfire_after_speech_does_not_keep_the_sentence_open():
    # Worst case: the voice detector rates the gunfire 0.42, which used to
    # count as "still talking" and stretched the caption out.
    voice, gun = _voice(1.0), _gunfire(3)
    audio = np.concatenate([np.zeros(8000, np.float32), voice, gun, np.zeros(16000, np.float32)])
    n = len(audio) // FRAME
    speech = range(8000 // FRAME, (8000 + len(voice)) // FRAME)
    gunfire = range((8000 + len(voice)) // FRAME, (8000 + len(voice) + len(gun)) // FRAME)
    mask = [0.9 if i in speech else 0.42 if i in gunfire else 0.0 for i in range(n)]

    def first_caption(filter_bangs):
        seg = Segmenter(stub_from_mask(mask), SegmenterConfig(filter_bangs=filter_bangs))
        for i in range(0, n * FRAME, 480):
            out = seg.feed(audio[i:i + 480])
            if out:
                return i / SAMPLE_RATE, len(out[0]) / SAMPLE_RATE
        return None, None

    speech_end = (8000 + len(voice)) / SAMPLE_RATE
    sent_off, length_off = first_caption(False)
    sent_on, length_on = first_caption(True)
    # Without the filter the caption waits ~1.5 s into the gunfire (until the
    # long-sentence rule kicks in); with it, it ends like normal speech.
    assert sent_off - speech_end > 1.0
    assert sent_on - speech_end < 0.6 and length_on < 1.6
