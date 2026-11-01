import json

import numpy as np

from fragsubs.audio import Downmixer
from fragsubs.config import Settings


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(model="small", languages=["ru", "pl"], font_size=26, background_opacity=0.3)
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.model == "small"
    assert loaded.languages == ["ru", "pl"]
    assert loaded.font_size == 26
    assert loaded.background_opacity == 0.3


def test_bad_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"font_size": "huge", "show_original": 1, "languages": [1, 2],
                                "max_lines": 6, "unknown": True}))
    s = Settings.load(path)
    assert s.font_size == Settings().font_size
    assert s.show_original is True  # default kept, 1 is not a bool
    assert s.languages == Settings().languages
    assert s.max_lines == 6


def test_old_minimum_speech_length_is_migrated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"min_speech_ms": 400, "font_size": 24}))
    s = Settings.load(path)
    assert s.min_speech_ms == 200 and s.font_size == 24
    # A value the user picked on purpose stays.
    path.write_text(json.dumps({"min_speech_ms": 600}))
    assert Settings.load(path).min_speech_ms == 600
    # Once migrated, 400 is respected as a deliberate choice.
    path.write_text(json.dumps({"min_speech_ms": 400, "settings_version": 2}))
    assert Settings.load(path).min_speech_ms == 400


def test_old_sentence_timing_is_migrated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"end_silence_ms": 550, "max_segment_s": 12.0, "settings_version": 2}))
    s = Settings.load(path)
    assert s.end_silence_ms == 450 and s.max_segment_s == 6.0
    path.write_text(json.dumps({"end_silence_ms": 800, "settings_version": 2}))
    assert Settings.load(path).end_silence_ms == 800  # chosen on purpose


def test_corrupt_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert Settings.load(path) == Settings()


def test_downmix_float_stereo_48k():
    mix = Downmixer(48000, 2, 32)
    left = np.full(4800, 0.5, dtype=np.float32)
    right = np.full(4800, -0.5, dtype=np.float32)
    data = np.stack([left, right], axis=1).reshape(-1).tobytes()
    out = np.concatenate([mix(data[:5000]), mix(data[5000:])])  # odd split mid-frame
    assert out.dtype == np.float32
    # 100 ms at 16 kHz, minus the resampler's start-up delay (< 30 ms)
    assert 1600 - 480 <= len(out) <= 1600
    assert np.abs(out).max() < 1e-3  # L and R cancel


def test_downmix_int16_44k():
    mix = Downmixer(44100, 2, 16)
    t = np.arange(44100) / 44100
    tone = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    data = np.stack([tone, tone], axis=1).reshape(-1).tobytes()
    out = mix(data)
    assert 16000 - 480 <= len(out) <= 16000
    assert 0.3 < np.abs(out).max() < 0.6
