"""Russian swearing and short shouts, which Whisper's translation handles badly.

Whisper is trained mostly on clean subtitles. On a one-second "нет, сука,
блять" it guesses ("Mexico blyat"), leaves words untranslated ("suka
blyat") or reads the whole thing as English. Three fixes:

* ``translate_short``: when the Russian transcript (which Whisper gets right
  far more often) consists only of known swear words and short shouts, the
  English comes from this table instead of from Whisper's translation.
* ``fix_translation``: Russian words Whisper left in Latin letters in its
  English output ("Rush B, suka blyat") are translated.
* ``latin_language``: English transcripts with such words in them ("Mexico
  blyat") were really Russian, so FragSubs tries again as Russian.
"""

from __future__ import annotations

import re

# Languages whose speakers swear with these words (Ukrainian gamers use the
# same Russian "мат"; Belarusian is folded into Russian elsewhere).
LANGUAGES = {"ru", "uk"}

# Russian (and Ukrainian) words and phrases -> English, as said in a match.
# Keys are lowercase with ё written as е; the longest match wins.
_PHRASES: dict[str, str] = {
    # swearing
    "сука блять": "fucking hell",
    "сука бля": "fucking hell",
    "блять сука": "fucking hell",
    "бля сука": "fucking hell",
    "блять": "fuck",
    "блядь": "fuck",
    "бля": "fuck",
    "сука": "fuck",
    "блин": "damn",
    "черт": "damn",
    "черт возьми": "damn it",
    "нахуй": "fuck it",
    "нахер": "screw it",
    "иди нахуй": "fuck off",
    "пошел нахуй": "fuck off",
    "иди нахер": "piss off",
    "пошел нахер": "piss off",
    "да пошел ты": "screw you",
    "пиздец": "holy shit",
    "ебать": "holy fuck",
    "охуеть": "holy shit",
    "ахуеть": "holy shit",
    "нихуя": "no fucking way",
    "нихуя себе": "holy shit",
    "заебал": "you're pissing me off",
    "заебали": "you're pissing me off",
    "заебись": "fucking great",
    "хуйня": "bullshit",
    "ебаный": "fucking",
    "ебаный в рот": "fuck me",
    "твою мать": "goddammit",
    "еб твою мать": "goddammit",
    "дерьмо": "shit",
    "говно": "shit",
    # insults
    "мудак": "asshole",
    "дебил": "moron",
    "долбоеб": "fucking idiot",
    "долбаеб": "fucking idiot",
    "идиот": "idiot",
    "урод": "freak",
    "лох": "loser",
    "нуб": "noob",
    "тварь": "scum",
    # short shouts
    "привет": "hi",
    "здарова": "hey",
    "пока": "bye",
    "нет": "no",
    "ні": "no",
    "да": "yes",
    "давай": "come on",
    "давай давай": "come on, come on",
    "быстрее": "faster",
    "быстро": "quick",
    "стой": "wait",
    "жди": "wait",
    "назад": "back",
    "погнали": "let's go",
    "го": "go",
    "помоги": "help me",
    "спасибо": "thanks",
    "прости": "sorry",
    "сорри": "sorry",
    "ладно": "okay",
    "окей": "okay",
    "красава": "nice one",
    "красавчик": "nice one",
    "изи": "easy",
}
# "ты дебил" -> "you moron", for every insult above.
for _ru, _en in [("мудак", "asshole"), ("дебил", "moron"), ("долбоеб", "fucking idiot"),
                 ("долбаеб", "fucking idiot"), ("идиот", "idiot"), ("урод", "freak"), ("лох", "loser"),
                 ("нуб", "noob"), ("тварь", "scum")]:
    _PHRASES[f"ты {_ru}"] = f"you {_en}"
    _PHRASES[f"ты {_ru} блять"] = f"you fucking {_en}" if not _en.startswith("fucking") else f"you {_en}"
_MAX_PHRASE = max(len(k.split()) for k in _PHRASES)

_WORD = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)


def _norm(word: str) -> str:
    return word.lower().replace("ё", "е")


def translate_short(text: str, language: str) -> str | None:
    """English for a transcript made only of known shouts and swear words
    ("Нет, сука, блять!" -> "No, fucking hell!"), else None."""
    if language not in LANGUAGES or not text or "*" in text:
        return None
    words = [_norm(w) for w in _WORD.findall(text)]
    if not words or len(words) > 6:
        return None
    chunks: list[str] = []
    i = 0
    while i < len(words):
        for size in range(min(_MAX_PHRASE, len(words) - i), 0, -1):
            english = _PHRASES.get(" ".join(words[i:i + size]))
            if english:
                chunks.append(english)
                i += size
                break
        else:
            return None  # a word we don't know: leave it to Whisper
    out = ", ".join(chunks)
    end = text.rstrip()[-1:]
    out += end if end in "!?." else "!"
    return out[0].upper() + out[1:]


# Russian swearing as Whisper writes it in Latin letters.
_LATIN: list[tuple[str, str]] = [
    (r"(?:suka|syka|cyka),? bl(?:y|i)a[dt]?", "fucking hell"),
    (r"idi na(?:k?h)u[iyj]", "fuck off"),
    (r"bl(?:y|i)a[dt]", "fuck"),
    (r"blya", "fuck"),
    (r"(?:suka|syka|cyka)", "bitch"),
    (r"na(?:k?h)u[iyj]", "the fuck"),
    (r"pizdec|pizdets", "holy shit"),
    (r"(?:y?e)bat", "holy fuck"),
    (r"davai|davay", "come on"),
    (r"nyet|niet", "no"),
]
_LATIN_RE = [(re.compile(rf"\b{pattern}\b", re.IGNORECASE), english) for pattern, english in _LATIN]


def fix_translation(text: str, language: str) -> str:
    """Translate Russian words left in Latin letters in Whisper's English."""
    if language not in LANGUAGES or not text:
        return text
    out = text
    for pattern, english in _LATIN_RE:
        out = pattern.sub(english, out)
    if out != text and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out


def latin_language(text: str, enabled: set[str]) -> str | None:
    """'Mexico blyat': an English transcript with Russian swearing in it, so
    the speech was most likely Russian. Returns the language to retry with."""
    if not text:
        return None
    for pattern, _english in _LATIN_RE:
        if pattern.search(text):
            for code in ("ru", "uk"):
                if code in enabled:
                    return code
            return None
    return None
