import json
import time
import urllib.request

from fragsubs import gamestate
from fragsubs.gamestate import CFG_NAME, GameState, cfg_dir_in_library, cfg_text, install, library_dirs, uninstall


def make_steam(tmp_path):
    """A Steam folder with CS2 installed in a second library."""
    steam = tmp_path / "Steam"
    lib = tmp_path / "Games" / "SteamLibrary"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n'
        '\t\t"apps"\n\t\t{\n\t\t\t"730"\t\t"40000000000"\n\t\t}\n\t}\n}\n'
        % (str(steam).replace("\\", "\\\\"), str(lib).replace("\\", "\\\\")), encoding="utf-8")
    (lib / "steamapps").mkdir(parents=True)
    (lib / "steamapps" / "appmanifest_730.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"730"\n\t"installdir"\t\t"Counter-Strike Global Offensive"\n}\n',
        encoding="utf-8")
    cfg = lib / "steamapps" / "common" / "Counter-Strike Global Offensive" / "game" / "csgo" / "cfg"
    cfg.mkdir(parents=True)
    return steam, lib, cfg


def test_finds_cs2_in_another_library(tmp_path):
    steam, lib, cfg = make_steam(tmp_path)
    assert library_dirs(steam) == [steam, lib]
    assert cfg_dir_in_library(lib) == cfg
    assert cfg_dir_in_library(steam) is None


def test_finds_cs2_through_steam(tmp_path, monkeypatch):
    steam, _lib, cfg = make_steam(tmp_path)
    monkeypatch.setattr(gamestate, "_steam_dirs", lambda: [steam])
    monkeypatch.setattr(gamestate, "_running_cs2_cfg_dir", lambda: None)
    assert gamestate.find_cfg_dirs() == [cfg]


def test_cfg_file_asks_only_for_the_map():
    text = cfg_text("abc", 31975)
    assert '"uri"       "http://127.0.0.1:31975/"' in text
    assert '"token" "abc"' in text
    assert '"map" "1"' in text
    assert "player" not in text and "provider" not in text


def test_install_and_uninstall(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    files, changed = install("tok", cfg_dirs=[cfg])
    assert files == [cfg / CFG_NAME] and changed
    assert (cfg / CFG_NAME).read_text(encoding="utf-8") == cfg_text("tok")
    # Same file again: nothing changes, so a running game needs no restart.
    assert install("tok", cfg_dirs=[cfg]) == ([cfg / CFG_NAME], False)
    assert install("other", cfg_dirs=[cfg])[1]
    assert uninstall(cfg_dirs=[cfg]) == 1 and not (cfg / CFG_NAME).exists()
    assert uninstall(cfg_dirs=[cfg]) == 0


def test_map_from_payloads():
    seen = []
    state = GameState("tok", on_change=seen.append)
    assert state.map_name is None and not state.connected
    state.receive({"auth": {"token": "wrong"}, "map": {"name": "de_nuke"}})
    assert state.map_name is None  # someone else's message
    state.receive({"auth": {"token": "tok"}, "map": {"name": "de_mirage", "phase": "live"}})
    assert state.connected and state.map_name == "de_mirage"
    state.receive({"auth": {"token": "tok"}, "map": {"name": "de_mirage", "phase": "over"}})
    state.receive({"auth": {"token": "tok"}})  # back in the menu
    assert state.map_name is None and state.connected
    assert seen == ["de_mirage", None]


def test_map_goes_stale_when_the_game_closes(monkeypatch):
    state = GameState("tok")
    state.receive({"auth": {"token": "tok"}, "map": {"name": "de_anubis"}})
    later = time.monotonic() + gamestate.STALE_S + 1
    monkeypatch.setattr(gamestate.time, "monotonic", lambda: later)
    assert state.map_name is None and not state.connected


def test_listens_for_the_game():
    state = GameState("tok", port=0)  # any free port
    assert state.start()
    try:
        port = state._server.server_address[1]
        body = json.dumps({"auth": {"token": "tok"}, "map": {"name": "de_overpass"}}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
        assert state.map_name == "de_overpass"
    finally:
        state.stop()
    assert not state.listening


def test_busy_port_is_reported():
    first = GameState("a", port=0)
    assert first.start()
    try:
        second = GameState("b", port=first._server.server_address[1])
        assert not second.start() and "in use" in second.error
    finally:
        first.stop()
