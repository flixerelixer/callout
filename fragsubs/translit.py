"""Write non-Latin text in Latin letters: Привет -> Privet, 你好 -> nǐ hǎo.

Used for the "original words" line under each translation, so you can read
(and learn) what was said even if you can't read the alphabet.

- Cyrillic: per-language tables (Russian, Ukrainian, Bulgarian, Serbian,
  Kazakh) because the rules differ (Ukrainian и is y, Russian и is i).
- Chinese: pinyin with tone marks (pypinyin).
- Japanese: kana in romaji. Kanji are left as they are, because reading them
  needs a dictionary and a wrong reading is worse than none.
- Everything else (Korean, Arabic, Greek, Hebrew, Thai, Hindi...): anyascii.
"""

from __future__ import annotations

import logging
import re
import unicodedata

log = logging.getLogger(__name__)

_RU = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}
_CYRILLIC: dict[str, dict[str, str]] = {
    "ru": _RU,
    "uk": {**_RU, "г": "h", "ґ": "g", "е": "e", "є": "ye", "и": "y", "і": "i", "ї": "yi",
           "й": "y", "щ": "shch", "ь": "", "'": ""},
    "bg": {**_RU, "х": "h", "щ": "sht", "ъ": "a", "ь": "y", "ц": "ts"},
    "sr": {**_RU, "ђ": "đ", "ж": "ž", "ј": "j", "љ": "lj", "њ": "nj", "х": "h", "ц": "c",
           "ћ": "ć", "ч": "č", "џ": "dž", "ш": "š"},
    "kk": {**_RU, "ә": "ä", "ғ": "ğ", "қ": "q", "ң": "ñ", "ө": "ö", "ұ": "ū", "ү": "ü",
           "һ": "h", "і": "ı"},
}


def _is_latin_text(text: str) -> bool:
    return all(ord(ch) < 0x250 or not ch.isalpha() for ch in text)


def _cyrillic(text: str, language: str) -> str:
    table = _CYRILLIC.get(language, _RU)
    out: list[str] = []
    for i, ch in enumerate(text):
        low = ch.lower()
        if low not in table or (low == "'" and language != "uk"):
            out.append(ch)
            continue
        rep = table[low]
        if ch != low and rep:
            # Whole word in capitals stays in capitals: ЖОПА -> ZHOPA, Жопа -> Zhopa.
            neighbours = text[max(0, i - 1):i] + text[i + 1:i + 2]
            if any(n.isalpha() and n.isupper() for n in neighbours):
                rep = rep.upper()
            else:
                rep = rep[0].upper() + rep[1:]
        out.append(rep)
    return "".join(out)


def _script(ch: str) -> str:
    try:
        return unicodedata.name(ch).split(" ", 1)[0]
    except ValueError:
        return ""


def _runs(text: str, key) -> list[tuple[bool, str]]:
    """Split text into runs where key(ch) is True/False."""
    runs: list[tuple[bool, str]] = []
    for ch in text:
        k = bool(key(ch))
        if runs and runs[-1][0] == k:
            runs[-1] = (k, runs[-1][1] + ch)
        else:
            runs.append((k, ch))
    return runs


def _join(parts: list[str]) -> str:
    """Join pieces, putting a space between words but not before punctuation."""
    out = ""
    for part in parts:
        if not part:
            continue
        if out and out[-1].isalnum() and part[0].isalnum():
            out += " "
        out += part
    out = re.sub(r"\s+([,.!?;:])", r"\1", out)
    out = re.sub(r"([,.!?;:])(?=[^\s\d,.!?;:])", r"\1 ", out)
    return " ".join(out.split())


def _anyascii(text: str) -> str:
    from anyascii import anyascii

    return anyascii(text)


def _chinese(text: str) -> str:
    from pypinyin import Style, lazy_pinyin

    parts: list[str] = []
    for han, run in _runs(text, lambda ch: _script(ch) == "CJK"):
        if han:
            parts.append(" ".join(lazy_pinyin(run, style=Style.TONE)))
        else:
            parts.append(_anyascii(run))  # also turns ，！ into , !
    return _join(parts)


def _japanese(text: str) -> str:
    parts: list[str] = []
    for kanji, run in _runs(text, lambda ch: _script(ch) == "CJK"):
        if kanji:
            parts.append(run)
        elif any(_script(c) in ("HIRAGANA", "KATAKANA") for c in run):
            parts.append(_anyascii(run).lower())
        else:
            parts.append(_anyascii(run))
    return _join(parts)


def _generic(text: str, language: str) -> str:
    parts: list[str] = []
    # Everything outside Latin, including vowel signs and viramas (नमस्ते),
    # which are not "letters" on their own.
    for foreign, run in _runs(text, lambda ch: ord(ch) >= 0x250 and not ch.isspace()):
        if not foreign:
            parts.append(run)
            continue
        if _script(run[0]) == "CYRILLIC":
            parts.append(_cyrillic(run, language))
            continue
        latin = _anyascii(run)
        # anyascii writes Korean syllables as "AnNyeong"; lowercase reads better.
        if _script(run[0]) == "HANGUL":
            latin = latin.lower()
        parts.append(latin)
    # Cyrillic and Latin pieces sit inside the same words, so join them as-is.
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def to_latin(text: str, language: str) -> str:
    """Latin-letter version of text, or "" when it is already Latin."""
    if not text or _is_latin_text(text):
        return ""
    try:
        if language == "zh" or (language not in ("ja",) and any(_script(c) == "CJK" for c in text)
                                and not any(_script(c) in ("HIRAGANA", "KATAKANA") for c in text)):
            return _chinese(text)
        if language == "ja" or any(_script(c) in ("HIRAGANA", "KATAKANA") for c in text):
            return _japanese(text)
        return _generic(text, language)
    except Exception as exc:  # noqa: BLE001
        log.warning("Transliteration failed: %s", exc)
        return ""
