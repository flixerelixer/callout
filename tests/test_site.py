import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("make_site_maps", ROOT / "scripts" / "make_site_maps.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_site_callouts_match_the_app():
    current = (ROOT / "site" / "maps.js").read_text(encoding="utf-8")
    assert current == _script().render(), "Run: python scripts/make_site_maps.py"


def test_site_loads_its_scripts_in_order():
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert html.index('src="maps.js"') < html.index('src="app.js"')
