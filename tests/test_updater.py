import hashlib
import zipfile

import pytest

from callout import updater


@pytest.mark.parametrize("remote,local,expected", [
    ("0.1.1", "0.1.0", True),
    ("v0.2.0", "0.1.9", True),
    ("0.1.10", "0.1.9", True),
    ("0.1.0", "0.1.0", False),
    ("0.1", "0.1.0", False),
    ("0.0.9", "0.1.0", False),
    ("nonsense", "0.1.0", False),
])
def test_is_newer(remote, local, expected):
    assert updater.is_newer(remote, local) is expected


def release_json(**over):
    data = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/fgmrkt/callout/releases/tag/v0.2.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://x/notes.txt", "size": 1},
            {"name": "Callout-v0.2.0-win64.zip", "browser_download_url": "https://x/old.zip", "size": 9},
            {"name": "FragSubs-Setup.exe", "browser_download_url": "https://x/setup.exe", "size": 9},
            {"name": "FragSubs-v0.2.0-win64.zip", "browser_download_url": "https://x/c.zip",
             "size": 1234, "digest": "sha256:abc123"},
        ],
    }
    data.update(over)
    return data


def test_release_from_json_picks_the_fragsubs_zip():
    rel = updater.release_from_json(release_json())
    assert rel.version == "0.2.0"
    assert rel.url == "https://x/c.zip"
    assert rel.size == 1234 and rel.sha256 == "abc123"


def test_prereleases_and_missing_assets_are_ignored():
    assert updater.release_from_json(release_json(prerelease=True)) is None
    assert updater.release_from_json(release_json(assets=[])) is None


def test_check_only_reports_newer(monkeypatch):
    monkeypatch.setattr(updater, "_get_json", lambda url: release_json(tag_name="v99.0.0"))
    assert updater.check().version == "99.0.0"
    monkeypatch.setattr(updater, "_get_json", lambda url: release_json(tag_name="v0.0.1"))
    assert updater.check() is None


def test_source_checkout_does_not_self_update():
    ok, why = updater.can_self_update()
    assert not ok and why


def make_zip(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("FragSubs/FragSubs.exe", b"MZ fake exe")
        zf.writestr("FragSubs/_internal/marker.txt", "new")
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def test_download_and_unpack(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLOUT_HOME", str(tmp_path / "home"))
    zpath = tmp_path / "FragSubs-v0.2.0-win64.zip"
    size, sha = make_zip(zpath)
    rel = updater.Release("0.2.0", zpath.as_uri(), size, sha, "")
    seen = []
    new_exe = updater.download(rel, lambda done, total: seen.append(done))
    assert new_exe.name == "FragSubs.exe" and new_exe.exists()
    assert (new_exe.parent / "_internal" / "marker.txt").read_text() == "new"
    assert seen and seen[-1] == size


def test_download_rejects_bad_checksum(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLOUT_HOME", str(tmp_path / "home"))
    zpath = tmp_path / "FragSubs-v0.2.0-win64.zip"
    size, _ = make_zip(zpath)
    rel = updater.Release("0.2.0", zpath.as_uri(), size, "0" * 64, "")
    with pytest.raises(RuntimeError, match="checksum"):
        updater.download(rel)


def test_update_script_mentions_rollback_and_keeps_the_exe_name():
    script = updater.UPDATE_SCRIPT
    assert "_internal.old" in script and "restoring the previous version" in script
    # Old installs run as Callout.exe: the script writes to whatever name is running.
    assert "$ExeName" in script and "$NewExeName" in script
