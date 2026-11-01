from callout.filters import (
    choose_language,
    clean_text,
    is_hallucination,
    looks_untranslated,
    mixed_language,
    top_candidates,
    wrong_script,
)


def probs(**kw):
    return list(kw.items())


def test_clear_russian():
    lang, conf, _ = choose_language(probs(ru=0.92, uk=0.04, en=0.02))
    assert lang == "ru" and conf > 0.9


def test_belarusian_counts_as_russian():
    lang, _, _ = choose_language(probs(be=0.45, ru=0.35, en=0.05))
    assert lang == "ru"


def test_unlisted_language_is_ignored():
    # Mostly Persian, which Callout does not list: too little coverage.
    lang, _, _ = choose_language(probs(fa=0.9, ar=0.05, en=0.02))
    assert lang is None


def test_unsure_returns_none():
    lang, conf, guess = choose_language(probs(de=0.3, nl=0.3, en=0.3))
    assert lang is None and conf < 0.45 and guess in ("de", "nl", "en")


def test_short_greeting_with_split_slavic_vote_is_accepted():
    # "привет": Whisper splits the vote between related languages.
    vote = probs(ru=0.40, uk=0.30, bg=0.12, en=0.08, pl=0.05)
    assert choose_language(vote)[0] is None  # no enabled list: too unsure
    lang, conf, _ = choose_language(vote, {"ru", "uk", "pl"})
    assert lang == "ru" and conf < 0.45


def test_split_vote_with_english_is_not_forced():
    # Russian barely ahead of English: not enough agreement to force it.
    vote = probs(ru=0.36, en=0.34, uk=0.10, pl=0.05)
    assert choose_language(vote, {"ru", "uk", "pl"})[0] is None


def test_english_is_reported_as_english():
    lang, _, _ = choose_language(probs(en=0.8, de=0.1))
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


def test_mixed_language_spots_cyrillic_words():
    vote = probs(en=0.8, ru=0.1, uk=0.08)
    assert mixed_language("say меня зовут blank", vote, {"ru", "uk"}) == "ru"
    assert mixed_language("say меня зовут blank", probs(en=0.8, uk=0.15, ru=0.02), {"ru", "uk"}) == "uk"
    assert mixed_language("say меня зовут blank", vote, {"de"}) is None  # not switched on
    assert mixed_language("plain English only", vote, {"ru"}) is None
    assert mixed_language("A я", vote, {"ru"}) is None  # a single letter is not enough


def test_mixed_language_other_scripts():
    assert mixed_language("he said 你好 to me", probs(en=0.9, zh=0.05), {"zh", "ja"}) == "zh"
    assert mixed_language("then こんにちは", probs(en=0.9), {"ja"}) == "ja"
    assert mixed_language("say 안녕하세요", probs(en=0.9), {"ko"}) == "ko"


def test_top_candidates():
    assert top_candidates(probs(no=0.38, en=0.32, ru=0.22, fa=0.05)) == ["no", "en", "ru"]
    assert top_candidates(probs(be=0.3, ru=0.3, en=0.2)) == ["ru", "en"]  # Belarusian folded in


def test_wrong_script():
    assert wrong_script("Двое на Б", "en")
    assert wrong_script("Dvoe na B", "ru")
    assert not wrong_script("Двое на Б", "ru")
    assert not wrong_script("Two on B", "en")
    assert not wrong_script("OK", "ru")  # too short to judge
