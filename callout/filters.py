"""Small, pure helpers that decide what Whisper output is worth showing.

Whisper is famous for inventing text on noise ("Thank you for watching",
Russian subtitle credits, ...). These checks keep that off the overlay.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Iterable

from .languages import BY_CODE, CONFUSABLE

# Text that only ever appears as a hallucination.
_ALWAYS_BOGUS = [
    "subtitles by",
    "subtitled by",
    "captions by",
    "transcribed by",
    "translated by",
    "amara.org",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "don't forget to subscribe",
    "see you in the next video",
    "dimatorzok",
    "продолжение следует",
    "субтитры",
    "редактор субтитров",
    "корректор",
    "спасибо за просмотр",
    "подписывайтесь на канал",
    "untertitel",
    "sous-titres",
    "sottotitoli",
    "napisy",
    "字幕",
]

# Short phrases Whisper produces on noise; only kept when it is confident.
_SUSPICIOUS = {
    "thank you",
    "thanks",
    "thank you very much",
    "you",
    "bye",
    "bye bye",
    "okay",
    "ok",
    "oh",
    "hmm",
    "uh",
    "so",
    "the end",
    "music",
    "applause",
    "laughter",
}

_WORD = re.compile(r"[\w']+", re.UNICODE)


def normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def clean_text(text: str) -> str:
    text = " ".join(text.split())
    text = text.strip(" -–—\"'")
    # Drop sound-effect annotations like [Music] or (gunshots).
    text = re.sub(r"[\[\(\*♪][^\]\)\*♪]{0,40}[\]\)\*♪]", "", text).strip()
    return " ".join(text.split())


def is_hallucination(text: str, *, avg_logprob: float = 0.0, no_speech_prob: float = 0.0,
                     hint: str = "") -> bool:
    norm = normalize(text)
    if not norm:
        return True
    if any(bad in text.lower() or bad in norm for bad in _ALWAYS_BOGUS):
        return True
    if norm in _SUSPICIOUS and (avg_logprob < -0.45 or no_speech_prob > 0.25):
        return True
    words = norm.split()
    # Looping output ("go go go go go go go go go ...") beyond normal shouting.
    if len(words) >= 10 and len(set(words)) / len(words) < 0.2:
        return True
    # Echo of the vocabulary hint, which Whisper sometimes reads back on noise.
    if hint and len(words) >= 4:
        hint_words = set(normalize(hint).split())
        if sum(w in hint_words for w in words) / len(words) > 0.85:
            return True
    return False


def choose_language(
    probs: Iterable[tuple[str, float]],
    enabled: set[str] | None = None,
    *,
    min_confidence: float = 0.45,
    min_coverage: float = 0.25,
    enabled_mass: float = 0.7,
) -> tuple[str | None, float, str]:
    """Pick the spoken language from Whisper's language probabilities.

    Only languages Callout knows about (plus English) are considered, with
    close relatives folded together (Belarusian counts as Russian, etc.), and
    the result is renormalised over that set.

    Short clips like "привет" often split the vote between related languages
    (Russian 40%, Ukrainian 30%, Bulgarian 10%). If the top guess is a
    language you translate and the languages you translate hold most of the
    vote together, the top guess is accepted even below ``min_confidence``:
    translating Ukrainian as if it were Russian still gives good English.

    Returns (code or None, confidence, best guess). Callers decide what to do
    with English or with a listed-but-switched-off language.
    """
    agg: dict[str, float] = defaultdict(float)
    for code, p in probs:
        code = CONFUSABLE.get(code, code)
        if code == "en" or code in BY_CODE:
            agg[code] += float(p)
    total = sum(agg.values())
    if total < min_coverage:
        return None, 0.0, ""
    best = max(agg, key=agg.__getitem__)
    conf = agg[best] / total
    if conf >= min_confidence:
        return best, conf, best
    if enabled and best in enabled:
        mass = sum(v for k, v in agg.items() if k in enabled) / total
        if mass >= enabled_mass:
            return best, conf, best
    return None, conf, best


# Writing systems that give away the language of words mixed into English,
# and the languages that use them.
SCRIPT_LANGUAGES: dict[str, list[str]] = {
    "CYRILLIC": ["ru", "uk", "bg", "sr", "kk"],
    "CJK": ["zh", "ja"],
    "HIRAGANA": ["ja"],
    "KATAKANA": ["ja"],
    "HANGUL": ["ko"],
    "ARABIC": ["ar"],
    "GREEK": ["el"],
    "HEBREW": ["he"],
    "THAI": ["th"],
    "DEVANAGARI": ["hi"],
}


def _script(ch: str) -> str:
    try:
        return unicodedata.name(ch).split(" ", 1)[0]
    except ValueError:
        return ""


def enabled_share(probs: Iterable[tuple[str, float]], enabled: set[str]) -> float:
    """How much of Whisper's language vote went to languages you translate."""
    return sum(float(p) for code, p in probs if CONFUSABLE.get(code, code) in enabled)


def mixed_language(text: str, probs: Iterable[tuple[str, float]], enabled: set[str]) -> str | None:
    """For English output that contains words in another writing system
    ("say меня зовут"), the enabled language those words are most likely in."""
    counts: dict[str, int] = defaultdict(int)
    for ch in text:
        if ch.isalpha() and ord(ch) >= 0x250:
            script = _script(ch)
            if script in SCRIPT_LANGUAGES:
                counts[script] += 1
    if not counts or max(counts.values()) < 2:
        return None
    script = max(counts, key=counts.__getitem__)
    candidates = [code for code in SCRIPT_LANGUAGES[script] if code in enabled]
    if not candidates:
        return None
    vote: dict[str, float] = defaultdict(float)
    for code, p in probs:
        vote[CONFUSABLE.get(code, code)] += float(p)
    return max(candidates, key=lambda code: vote.get(code, 0.0))


# Languages Whisper writes in a non-Latin alphabet (Serbian can go either way).
NON_LATIN = {"ru", "uk", "bg", "kk", "zh", "ja", "ko", "ar", "el", "he", "th", "hi"}


def top_candidates(probs: Iterable[tuple[str, float]], n: int = 3, min_share: float = 0.04) -> list[str]:
    """The n most likely languages Callout knows (English included), folded
    and renormalised like choose_language."""
    agg: dict[str, float] = defaultdict(float)
    for code, p in probs:
        code = CONFUSABLE.get(code, code)
        if code == "en" or code in BY_CODE:
            agg[code] += float(p)
    total = sum(agg.values()) or 1.0
    ranked = sorted(agg, key=agg.__getitem__, reverse=True)
    return [code for code in ranked[:n] if agg[code] / total >= min_share]


def wrong_script(text: str, language: str) -> bool:
    """True when text written 'in' a language uses the wrong alphabet, which
    is what Whisper does when forced to read speech as the wrong language
    (Russian forced as English comes out translated, English forced as
    Russian comes out in Latin letters)."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 3:
        return False
    latin = sum(1 for ch in letters if ord(ch) < 0x250) / len(letters)
    if language in NON_LATIN:
        return latin > 0.5
    if language == "sr":
        return False
    return latin < 0.5


def looks_untranslated(text: str) -> bool:
    """True when 'English' output is mostly in a non-Latin script, which
    happens when Whisper ignores the translate task."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 3:
        return False
    latin = sum(1 for ch in letters if ord(ch) < 0x250)
    return latin / len(letters) < 0.5
