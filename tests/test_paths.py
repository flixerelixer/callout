import importlib


def fresh_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("CALLOUT_HOME", raising=False)
    monkeypatch.delenv("FRAGSUBS_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from fragsubs import paths

    return importlib.reload(paths)


def test_old_callout_folder_is_moved_over(monkeypatch, tmp_path):
    paths = fresh_paths(monkeypatch, tmp_path)
    old = tmp_path / paths._folder_name("Callout")
    (old / "models" / "large-v3").mkdir(parents=True)
    (old / "models" / "large-v3" / "model.bin").write_text("weights")
    (old / "settings.json").write_text("{}")
    d = paths.app_data_dir()
    assert d.name == paths._folder_name("FragSubs")
    assert (d / "models" / "large-v3" / "model.bin").read_text() == "weights"
    assert (d / "settings.json").exists() and not old.exists()


def test_fresh_install_gets_a_fragsubs_folder(monkeypatch, tmp_path):
    paths = fresh_paths(monkeypatch, tmp_path)
    d = paths.app_data_dir()
    assert d.exists() and d.name == paths._folder_name("FragSubs")
