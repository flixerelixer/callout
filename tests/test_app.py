import sys

from callout.app import fix_std_streams


def test_progress_bars_survive_without_console(monkeypatch):
    # A windowed .exe starts with no stdout/stderr at all.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    fix_std_streams()
    from tqdm.auto import tqdm

    for _ in tqdm(range(3)):
        pass
    print("still fine")
