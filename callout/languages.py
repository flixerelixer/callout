"""Languages Callout can translate from (all into English).

Codes are Whisper language codes. ``default`` marks the languages that are
switched on for a fresh install; everything else can be enabled in the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    default: bool


LANGUAGES: list[Language] = [
    Language("ru", "Russian", True),
    Language("uk", "Ukrainian", True),
    Language("pl", "Polish", True),
    Language("tr", "Turkish", True),
    Language("de", "German", True),
    Language("fr", "French", True),
    Language("es", "Spanish", True),
    Language("pt", "Portuguese", True),
    Language("it", "Italian", True),
    Language("zh", "Chinese", True),
    Language("ja", "Japanese", True),
    Language("ko", "Korean", True),
    Language("ar", "Arabic", True),
    Language("nl", "Dutch", False),
    Language("cs", "Czech", False),
    Language("sk", "Slovak", False),
    Language("hu", "Hungarian", False),
    Language("ro", "Romanian", False),
    Language("bg", "Bulgarian", False),
    Language("sr", "Serbian", False),
    Language("hr", "Croatian", False),
    Language("el", "Greek", False),
    Language("sv", "Swedish", False),
    Language("da", "Danish", False),
    Language("no", "Norwegian", False),
    Language("fi", "Finnish", False),
    Language("kk", "Kazakh", False),
    Language("he", "Hebrew", False),
    Language("hi", "Hindi", False),
    Language("vi", "Vietnamese", False),
    Language("th", "Thai", False),
    Language("id", "Indonesian", False),
]

BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}

# Languages Whisper often confuses with listed ones on short, noisy clips.
# They are folded into the listed language instead of being treated as
# "some other language".
CONFUSABLE: dict[str, str] = {
    "be": "ru",  # Belarusian -> Russian
    "mk": "bg",  # Macedonian -> Bulgarian
    "bs": "sr",  # Bosnian -> Serbian
    "nn": "no",  # Nynorsk -> Norwegian
    "af": "nl",  # Afrikaans -> Dutch
    "yue": "zh",  # Cantonese -> Chinese
}


def default_codes() -> list[str]:
    return [lang.code for lang in LANGUAGES if lang.default]


def display_name(code: str) -> str:
    if code == "en":
        return "English"
    lang = BY_CODE.get(code)
    return lang.name if lang else code.upper()
