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
    mask = [0.0] * 20 + [0.9] * 4 + [0.0] * 40  # 128 ms "speech", e.g. a gunshot
    out, seg = run(mask)
    assert out == []
    assert len(seg.short_drops) == 1 and 0.1 < seg.short_drops[0] < 0.15


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
