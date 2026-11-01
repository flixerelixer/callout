from fragsubs.slang import fix_translation, latin_language, translate_short


def test_swearing_and_shouts():
    assert translate_short("Нет, сука, блять!", "ru") == "No, fucking hell!"
    assert translate_short("Сука блять", "ru") == "Fucking hell!"
    assert translate_short("Иди нахуй.", "ru") == "Fuck off."
    assert translate_short("Давай, давай, быстрее", "ru") == "Come on, come on, faster!"
    assert translate_short("Пиздец...", "ru") == "Holy shit."
    assert translate_short("Ты дебил, блять", "ru") == "You fucking moron!"
    assert translate_short("Ёбаный в рот!", "ru") == "Fuck me!"
    assert translate_short("Ні, блять", "uk") == "No, fuck!"


def test_anything_else_is_left_to_whisper():
    assert translate_short("Двое на Б, один лоу", "ru") is None
    assert translate_short("Сука, он на балконе", "ru") is None
    assert translate_short("б***ь", "ru") is None
    assert translate_short("Нет", "pl") is None
    assert translate_short("", "ru") is None


def test_latin_swearing_in_english_output():
    assert fix_translation("Rush B, suka blyat!", "ru") == "Rush B, fucking hell!"
    assert fix_translation("cyka blyat", "ru") == "Fucking hell"
    assert fix_translation("Idi nahui, I'm not dropping", "ru") == "Fuck off, I'm not dropping"
    assert fix_translation("Davai, rotate", "ru") == "Come on, rotate"
    assert fix_translation("Two on B, one is low.", "ru") == "Two on B, one is low."
    assert fix_translation("suka", "pl") == "suka"


def test_russian_swearing_in_an_english_transcript():
    assert latin_language("Mexico blyat", {"ru", "pl"}) == "ru"
    assert latin_language("Nyet, nyet, rotate", {"uk"}) == "uk"
    assert latin_language("Mexico blyat", {"pl"}) is None
    assert latin_language("Mexico is nice", {"ru"}) is None
