import pytest

from callout.translit import to_latin


@pytest.mark.parametrize("text,lang,expected", [
    ("Может ворвать смок? Не видел мид.", "ru", "Mozhet vorvat smok? Ne videl mid."),
    ("Привет, меня зовут Феликс", "ru", "Privet, menya zovut Feliks"),
    ("Щука и ёжик", "ru", "Shchuka i yozhik"),
    ("ЖОПА", "ru", "ZHOPA"),
    ("Привіт, як справи? Їжак, ґанок, є", "uk", "Pryvit, yak spravy? Yizhak, ganok, ye"),
    ("Здравей, щастие", "bg", "Zdravey, shtastie"),
    ("Ћао, како си, љубави", "sr", "Ćao, kako si, ljubavi"),
])
def test_cyrillic(text, lang, expected):
    assert to_latin(text, lang) == expected


def test_mixed_english_and_russian():
    assert to_latin("Say меня зовут and then your name.", "ru") == "Say menya zovut and then your name."


def test_chinese_pinyin_with_tones():
    assert to_latin("你好，我在B点，小心！", "zh") == "nǐ hǎo, wǒ zài B diǎn, xiǎo xīn!"


def test_japanese_kana_and_kanji_kept():
    out = to_latin("こんにちは、日本語です", "ja")
    assert out.startswith("konnichiha,") and "日本語" in out and out.endswith("desu")


def test_korean_is_lowercase_romanization():
    assert to_latin("안녕하세요", "ko") == "annyeonghaseyo"


def test_other_scripts_produce_latin():
    for text, lang in [("مرحبا", "ar"), ("Γειά σου", "el"), ("नमस्ते", "hi"), ("สวัสดี", "th")]:
        out = to_latin(text, lang)
        assert out and all(ord(c) < 0x250 for c in out), (text, out)


def test_latin_text_needs_nothing():
    assert to_latin("Sejwuj karabin, kupujemy w następnej", "pl") == ""
    assert to_latin("", "ru") == ""
