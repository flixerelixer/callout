from fragsubs import callouts
from fragsubs.callouts import MAPS, build_prompt, map_for


def test_the_cs2_maps_from_totalcsgo():
    assert {m.name for m in MAPS.values()} == {
        "Ancient", "Anubis", "Cache", "Dust 2", "Inferno", "Mirage", "Nuke", "Overpass", "Vertigo"}
    # Only in CS:GO according to the source, so left out.
    assert map_for("de_train") is None and map_for("de_cbble") is None
    for m in MAPS.values():
        assert len(m.callouts) >= 30, m.name
        assert len({c.lower() for c in m.callouts}) == len(m.callouts), m.name


def test_well_known_callouts():
    assert {"Palace", "Tetris", "Jungle", "Firebox", "Apps Ramp"} <= set(MAPS["de_mirage"].callouts)
    assert {"Banana", "Coffins", "Library", "Pit"} <= set(MAPS["de_inferno"].callouts)
    assert {"Goose", "Xbox", "Suicide", "Catwalk"} <= set(MAPS["de_dust2"].callouts)
    assert {"Heaven", "Hell", "Squeaky", "Ramp"} <= set(MAPS["de_nuke"].callouts)


def test_map_names_from_the_game():
    assert map_for("de_mirage").name == "Mirage"
    assert map_for("DE_DUST2").name == "Dust 2"
    assert map_for("workshop/3070284539/de_inferno").name == "Inferno"
    assert map_for("de_ancient_night").name == "Ancient"
    assert map_for("de_dust") is None  # not Dust 2
    assert map_for("") is None and map_for(None) is None


def test_prompt_has_the_map_and_common_words():
    p = build_prompt(MAPS["de_mirage"])
    assert p.startswith("Counter-Strike 2 team voice chat on Mirage.")
    assert "Palace" in p and "Tetris" in p and "AWP" in p and "smoke" in p
    assert "Banana" not in p  # other maps stay out
    general = build_prompt(None)
    assert "AWP" in general and "Palace" not in general


def test_every_prompt_fits_whispers_limit():
    for m in [None, *MAPS.values()]:
        p = build_prompt(m)
        assert callouts.estimate_tokens(p) <= callouts.MAX_PROMPT_TOKENS


def test_core_words_and_extra_words_survive_trimming():
    extra = "Artyom, Kuba, Dmytro"
    for m in MAPS.values():
        p = build_prompt(m, extra)
        assert p.endswith("Artyom, Kuba, Dmytro.")
        for word in ("AWP", "smoke", "flash", "rotate", "one HP"):
            assert word in p, (m.name, word)


def test_redundant_callouts_go_first():
    # A tight budget: "Close Mid Doors" only repeats words that are already
    # there, so it goes before callouts with words of their own.
    m = MAPS["de_dust2"]
    p = build_prompt(m, budget=180)
    assert "Goose" in p and "Suicide" in p and "Hiko" in p
    assert "Close Mid Doors" not in p and "A Long" not in p
    assert callouts.estimate_tokens(p) <= 180


def test_extra_words_keep_their_punctuation():
    assert build_prompt(None, "Hi there!").endswith("Hi there!")
    assert build_prompt(None, "  ").endswith(".")
