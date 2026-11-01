"""Counter-Strike 2 callouts per map, and the vocabulary prompt built from them.

Whisper accepts a short "prompt" of text it treats as what was said just
before. Words in it come out spelled the way they are written there, so
"Palace", "Banana" and "Heaven" stop turning into "Pales", "Bonanza" and
"heavy". Only the callouts of the map being played go in, because the prompt
is limited to 223 tokens and unrelated names make Whisper guess them where
they weren't said.

Map callouts are from https://totalcsgo.com/callouts, for the maps that site
lists as being in CS2 (Cobblestone and Train are marked CS:GO only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GameMap:
    key: str  # the name the game reports, e.g. "de_mirage"
    name: str  # as shown to people
    callouts: tuple[str, ...]


def _m(key: str, name: str, callouts: str) -> GameMap:
    seen: set[str] = set()
    items = []
    for item in callouts.split(","):
        item = " ".join(item.split())
        if item and item.lower() not in seen:
            seen.add(item.lower())
            items.append(item)
    return GameMap(key, name, tuple(items))


MAPS: dict[str, GameMap] = {m.key: m for m in [
    _m("de_ancient", "Ancient",
       "T Spawn, Tunnel, Water, Ruins, Doors, Split, Stairs, Elbow, A Halls, A Main, Long, Boost, "
       "Big Box, Single, Plat, A Site, Triple Box, CT Lane, Temple, CT Spawn, Sniper's Nest, Top Mid, "
       "Pit, Mid, Tunnels, Short, Xbox, Heaven, Lamp Room, Dark, T Lower, Ramp, House, B Site, Pillar, "
       "Square, Back Halls, Alley"),
    _m("de_anubis", "Anubis",
       "T Spawn, Alley, Ruins, Top Mid, B Long, Gate, Ivy, Heaven, Pillar, Default, E Box, Water, "
       "Arches, Wood, B Site, Back Site, Ninja, Bridge, Double Doors, Palace, Street, Sniper, Stairs, "
       "Middle, Cave, A Connector, Plateau, Drop, CT Spawn, Main, Headshot, Boat, Tunnel, Fountain, "
       "Upper, A Site, Beach, Corner"),
    _m("de_cache", "Cache",
       "Mid, A Site, T Spawn, A Long, Squeaky, Shroud, NBK, Quad, A Default, Forklift, Balcony, "
       "Highway, Default Box, Truck, CT Halls, CT Connector, White Box, Sandbags, Mid Roof, Vents, "
       "Cubby, Boost, Boost Boxes, Checkers, Back Checkers, Garage, T Red, Dumpster, B Halls, B Main, "
       "B Main Boxes, Sun Room, Toxic, B Offen, Pit, B Ramp, Headshot, B Site, B Default, Back Site, "
       "Back Boxes, New Boxes, Spray, Close Left, Heaven, Blue, Rafters, Tree, CT Spawn, T Truck, "
       "T Boxes, Flash Window, A Main, Lockers, Elektro"),
    _m("de_dust2", "Dust 2",
       "A Short, T Spawn, T Ramp, T Plat, Outside Tunnels, Upper B Tunnels, Lower B Tunnels, Close, "
       "B Closet, B Car, Fence, B Plat, Back Plat, Big Box, Double Stack, B Default Plant, B Window, "
       "B Back Site, B Doors, B Boxes, Scaffolding, CT Mid, Mid Doors, Close Mid Doors, Hiko, Xbox, "
       "Mid, Palm, Right Side Mid, Top Mid, Suicide, Outside Long, Long Doors, Blue, Side Pit, Pit, "
       "Pit Plat, A Long, Long Corner, A Car, A Cross, A Ramp, A Default Plant, Barrels, Goose, "
       "Elevator, Short Boost, A Platform, A Ninja, Stairs, Catwalk, CT Spawn"),
    _m("de_inferno", "Inferno",
       "Banana, B Site, T Spawn, Mid, Second Mid, T Ramp, Ledge, Living Room, Balcony, Bridge, "
       "A Short, A Long, T Apartments, Second Mid Door, Back Alley, Underpass, Bench, "
       "Second Mid Stairs, CT Apartments, Top Mid, Pit, Boiler, Window, Stairs, Close Apartments, "
       "Dosia, Cemetery, Graveyard, Truck, Patio, Long Corner, Library, Kitchen, A Site, Close Left, "
       "Back Site, Arch, CT Spawn, Speedway, Terrace, Well, CT, Tree, CT Boost, Construction, "
       "Sandbags, Garden, Coffins, Grill, Dark, Fountain, Quad, Boost, Car, Logs, Bottom Mid"),
    _m("de_mirage", "Mirage",
       "Mid, B Site, A Site, T Spawn, T Roof, A Ramp, Palace, Pillars, Balcony, Shadows, Tetris, "
       "Sandwich, Stairs, Firebox, Ninja, CT, Ticket Booth, Trash, CT Spawn, Jungle, Connector, Vent, "
       "Sniper's Nest, Ladder Room, Underpass, Boost, Chair, Top Mid, Mid Boxes, Default, Triple Box, "
       "Catwalk, B Short, Short Corner, Market, Window, Door, Bench, Van, Car, B Apartments, Kitchen, "
       "B Plat, Side Alley, TV, Cart, Apps Ramp, Arches, Sneaky, Empty, E Box, Boost Boxes, House, "
       "Back Alley"),
    _m("de_nuke", "Nuke",
       "T Spawn, CT Spawn, Outside, A Site, B Site, Garage, Ramp, CT Box, T Roof, Lobby, Radio, "
       "Trophy, Control, Squeaky, Vent, Hell, Heaven, Lockers, Headshot, Sandbags, Hut, Tetris, "
       "Mustang, Rafters, Bridge, Turn Pike, Stack, Boost, Big Box, T Red, CT Red, Main, Window, Dark, "
       "Decon, Back Vents, Tunnels, Doors, Bottom Ramp, Silo, Secret"),
    _m("de_overpass", "Overpass",
       "A Site, B Site, T Spawn, A Long, Upper Tunnels, Lower Tunnels, Connector, Party, Mid, "
       "Fountain, Playground, Rock, Tree, Long Toilets, Long Boost, Close Left, Van, Bank, Default, "
       "Optimus, Bins, Toilets, A Short, Flowers, CT, Monster, Tracks, Short Tunnel, Water, Squeaky, "
       "B Short, Sandbags, Sewers, Pillar, Toxic Barrels, Pit, Heaven, Graffiti, Cafe, Bench, Storage, "
       "Bridge, Boost, Ladder, Signpost, Hitmarker"),
    _m("de_vertigo", "Vertigo",
       "Under Stairs, B Stairs, Underpass, Save Spot, Big Box, Bridge, Sheets, Ladder, Toilets, "
       "T Spawn, Dark, Scaffold, A Ramp, Fence, Sandbags, Stairs, Back B, Catwalk, B Site, "
       "Electric Box, Connector, CT Spawn, Headshot, Boost, Mid, Iron, T Mid, Generator, T Stairs, "
       "Lane, Double, A Site, Elevator, Door, Heaven, Top Mid"),
]}

# Words heard on every map. The core is kept whenever possible; the rest
# only goes in when there is room left after the map's callouts.
GENERAL_CORE = (
    "AWP, smoke, flash, molly, HE, eco, force buy, rush, plant, defuse, rotate, push, lurk, "
    "one HP, lit, CT, T spawn, A site, B site, mid"
)
GENERAL_MORE = (
    "AK, M4, Deagle, Scout, nade, utility, full buy, save, drop, planted, kit, bomb, retake, hold, "
    "peek, tagged, low, dink, entry, trade, clutch, long, short, ramp, heaven"
)

# Whisper keeps at most this many prompt tokens (half its 448-token window,
# minus one). Stay a little under it.
MAX_PROMPT_TOKENS = 215


def map_for(name: str | None) -> GameMap | None:
    """The map for a name the game reports: "de_mirage", a workshop copy like
    "workshop/123456/de_mirage", or a variant like "de_ancient_night"."""
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    for key, game_map in MAPS.items():
        if base == key or base.startswith(key + "_"):
            return game_map
    return None


def estimate_tokens(text: str) -> int:
    """Rough Whisper token count, on the high side (about 3 characters per
    token for comma-separated callouts). Used when the real tokenizer isn't
    at hand."""
    return len(text) // 3 + 1


def _words(item: str) -> set[str]:
    return set(item.lower().replace("'s", "").split())


def _trim_one(callouts: list[str], core: list[str]) -> bool:
    """Remove the callout that adds the least: the last one whose words all
    appear elsewhere in the prompt ("Close Mid Doors" next to "Close" and
    "Mid Doors"), otherwise simply the last one."""
    if not callouts:
        return False
    for i in range(len(callouts) - 1, -1, -1):
        others = set()
        for j, item in enumerate(callouts):
            if j != i:
                others |= _words(item)
        for word in core:
            others |= _words(word)
        if _words(callouts[i]) <= others:
            del callouts[i]
            return True
    callouts.pop()
    return True


def build_prompt(game_map: GameMap | None, extra: str = "", *,
                 count: Callable[[str], int] = estimate_tokens, budget: int = MAX_PROMPT_TOKENS) -> str:
    """The text given to Whisper as context: callouts of the map being played,
    common Counter-Strike words, and the person's own extra words (always
    kept, so names of teammates come through).

    When it doesn't fit, the extra common words go first, then the callouts
    that only repeat words already in the prompt, then the last callouts."""
    extra = " ".join(extra.split())
    if extra and not extra.endswith((".", "!", "?")):
        extra += "."
    callouts = list(game_map.callouts) if game_map else []
    known = {c.lower() for c in callouts}
    core = [w.strip() for w in GENERAL_CORE.split(",") if w.strip().lower() not in known]
    more = [w.strip() for w in GENERAL_MORE.split(",") if w.strip().lower() not in known]
    head = f"Counter-Strike 2 team voice chat on {game_map.name}." if game_map else "Counter-Strike 2 team voice chat."

    def render() -> str:
        parts = [head]
        if callouts:
            parts.append("Callouts: " + ", ".join(callouts) + ".")
        if core or more:
            parts.append(("Also: " if callouts else "Callouts and words: ") + ", ".join(core + more) + ".")
        if extra:
            parts.append(extra)
        return " ".join(parts)

    text = render()
    while count(text) > budget:
        if more:
            more.pop()
        elif not _trim_one(callouts, core):
            if not core:
                break
            core.pop()
        text = render()
    return text
