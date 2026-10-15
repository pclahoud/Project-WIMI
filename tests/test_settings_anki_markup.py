"""Settings -> Anki Integration (#784 Wave 3): the markup, script and reset
contract that the scenarios do not reach.

- The panel carries no ``data-field``. Each control saves itself through
  ``settings_anki.js``; a ``data-field`` would also put it under the page's
  Save and Reset, two owners for one value.
- So ``SettingsPage.DEFAULTS`` must not hold the Anki keys: Reset posts
  DEFAULTS wholesale and would switch Anki off behind a panel that says
  nothing on it waits for Save.
- Every id the script looks up exists in the panel, both stylesheets and the
  script are linked, and the script builds from nodes, never from HTML.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HTML = (REPO / "src/web/html/settings.html").read_text(encoding="utf-8")
JS = (REPO / "src/web/js/settings_anki.js").read_text(encoding="utf-8")
SETTINGS_JS = (REPO / "src/web/js/settings.js").read_text(encoding="utf-8")


def _panel() -> str:
    start = HTML.index('data-panel="anki_integration" data-testid="settings-panel-anki"')
    end = HTML.index('data-panel="data_backup">', start)
    return HTML[start:end]


def test_the_reader_finds_the_panel():
    panel = _panel()
    assert 'id="anki-enabled"' in panel and 'id="anki-field-list"' in panel


def test_no_control_in_the_panel_is_a_save_button_field():
    assert "data-field" not in _panel()


def test_reset_does_not_cover_the_anki_switch_or_port():
    body = re.search(r"this\.DEFAULTS = \{(.*?)\n        \};", SETTINGS_JS, re.S)
    assert body, "could not find SettingsPage.DEFAULTS"
    keys = set(re.findall(r"^\s*([a-z_0-9]+):", body.group(1), re.M))
    assert len(keys) >= 40, "reader found too few DEFAULTS keys"
    assert not keys & {"anki_integration_enabled", "ankiconnect_port",
                       "anki_auto_refresh", "anki_cache_refresh_interval_minutes",
                       "anki_display_mode"}


def test_every_id_the_script_reads_is_in_the_panel():
    wanted = set(re.findall(r"\$\('([a-z0-9-]+)'\)", JS))
    wanted |= set(re.findall(r"say\('([a-z0-9-]+)'", JS))
    assert len(wanted) >= 12, sorted(wanted)
    ids = set(re.findall(r'id="([a-z0-9-]+)"', _panel()))
    assert wanted <= ids, sorted(wanted - ids)


def test_the_stylesheet_and_script_are_linked_once():
    assert HTML.count('href="../css/settings_anki.css"') == 1
    assert HTML.count('src="../js/settings_anki.js"') == 1
    assert HTML.index('src="../js/settings.js"') < HTML.index('src="../js/settings_anki.js"')


def test_the_script_never_parses_a_string_as_html():
    """Template text and field names come from the database and from Anki."""
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML", JS)
    assert "textContent" in JS
