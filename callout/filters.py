"""Small, pure helpers that decide what Whisper output is worth showing.

Whisper is famous for inventing text on noise ("Thank you for watching",
Russian subtitle credits, ...). These checks keep that off the overlay.
"""

from __future__ import annotations

import re
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
    *,
    min_confidence: float = 0.45,
    min_coverage: float = 0.25,
) -> tuple[str | None, float]:
    """Pick the spoken language from Whisper's language probabilities.

    Only languages Callout knows about (plus English) are considered, with
    close relatives folded together (Belarusian counts as Russian, etc.), and
    the result is renormalised over that set. Returns (code, confidence);
    code is None when nothing is convincing. Callers decide what to do with
    English or with a listed-but-switched-off language.
    """
    agg: dict[str, float] = defaultdict(float)
    for code, p in probs:
        code = CONFUSABLE.get(code, code)
        if code == "en" or code in BY_CODE:
            agg[code] += float(p)
    total = sum(agg.values())
    if total < min_coverage:
        return None, 0.0
    best = max(agg, key=agg.__getitem__)
    conf = agg[best] / total
    if conf < min_confidence:
        return None, conf
    return best, conf


def looks_untranslated(text: str) -> bool:
    """True when 'English' output is mostly in a non-Latin script, which
    happens when Whisper ignores the translate task."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 3:
        return False
    latin = sum(1 for ch in letters if ord(ch) < 0x250)
    return latin / len(letters) < 0.5
