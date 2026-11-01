from callout.filters import choose_language, clean_text, is_hallucination, looks_untranslated


def probs(**kw):
    return list(kw.items())


def test_clear_russian():
    lang, conf = choose_language(probs(ru=0.92, uk=0.04, en=0.02))
    assert lang == "ru" and conf > 0.9


def test_belarusian_counts_as_russian():
    lang, _ = choose_language(probs(be=0.45, ru=0.35, en=0.05))
    assert lang == "ru"


def test_unlisted_language_is_ignored():
    # Mostly Persian, which Callout does not list: too little coverage.
    lang, _ = choose_language(probs(fa=0.9, ar=0.05, en=0.02))
    assert lang is None


def test_unsure_returns_none():
    lang, conf = choose_language(probs(de=0.3, nl=0.3, en=0.3))
    assert lang is None and conf < 0.45


def test_english_is_reported_as_english():
    lang, _ = choose_language(probs(en=0.8, de=0.1))
    assert lang == "en"


def test_known_hallucinations_are_dropped():
    assert is_hallucination("Thanks for watching!")
    assert is_hallucination("Продолжение следует...")
    assert is_hallucination("Субтитры сделал DimaTorzok")
    assert is_hallucination("Subtitles by the Amara.org community")
    assert is_hallucination("   ")


def test_short_phrases_need_confidence():
    assert is_hallucination("Thank you.", avg_logprob=-0.8, no_speech_prob=0.1)
    assert not is_hallucination("Thank you.", avg_logprob=-0.2, no_speech_prob=0.05)


def test_real_callouts_survive():
    assert not is_hallucination("Two on B, one is low.")
    assert not is_hallucination("Go go go!")
    assert not is_hallucination("Rush B, rush B, everyone together", hint="rush B, A site")


def test_looping_output_is_dropped():
    assert is_hallucination(" ".join(["go"] * 30))


def test_hint_echo_is_dropped():
    hint = "Counter-Strike callouts: A site, B site, mid, AWP, smoke, flash"
    assert is_hallucination("A site, B site, mid, AWP, smoke.", hint=hint)


def test_clean_text_strips_sound_tags():
    assert clean_text(" - [Music] Plant the bomb (gunshots) ") == "Plant the bomb"


def test_untranslated_detection():
    assert looks_untranslated("Двое на Б, один лоу")
    assert looks_untranslated("我在B点")
    assert not looks_untranslated("Two on B, one is low")
    assert not looks_untranslated("Zwei auf B")  # Latin script passes
    assert not looks_untranslated("OK")
