"""#507: the Addons panel's folder route says a restart is required.

WIMI reads ``app_data/plugins/`` once, at startup (``PluginManager.load_all``);
a profile switch reloads only the manifests already found (#505) and the panel
reads that cache. So a folder dropped in while WIMI is open never appears, and
the two places that offer the folder route beside "Install from .zip" have to
say so, or the student concludes their plugin is broken (the #174 family).

Self-counting: every first-party line that names the folder must also say
"restart WIMI", and the sweep must find at least the two known sites.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SURFACES = [REPO / "src/web/html/settings.html", REPO / "src/web/js/settings.js"]


def _lines_naming_the_folder():
    for path in SURFACES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "app_data/plugins/" in line:
                yield f"{path.name}:{number}", line


def test_the_sweep_finds_both_known_sites():
    names = {where.split(":")[0] for where, _ in _lines_naming_the_folder()}
    assert names == {"settings.html", "settings.js"}, names


def test_every_line_offering_the_folder_route_says_restart():
    missing = [where for where, line in _lines_naming_the_folder()
               if "restart WIMI" not in line]
    assert not missing, f"folder route offered without the restart: {missing}"
