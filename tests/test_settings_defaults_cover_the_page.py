"""#509: Reset what Save covers resets every setting the page's Save covers.

That is the set of ``data-field`` controls (#652 put the scope in the button's
label). Controls that save themselves on change -- per-exam analytics, each
question bank's address and Desktop site switch, add-ons -- are not
``data-field`` controls and are deliberately outside it.

``resetToDefaults()`` posts ``SettingsPage.DEFAULTS`` wholesale, so a
``data-field`` missing from that object is silently un-resettable: it keeps
its value and ``populateForm`` then redraws the old choice, positively
confirming a reset that never happened. The three Question Banks choices were
exactly that, under a comment warning about it.

Self-checking, both ways: every ``data-field`` on the page is in DEFAULTS or
in ``EXEMPT`` with its reason, every exemption is still a field and still
absent (so the list cannot go stale), and every DEFAULTS value is the stored
default of the Python dataclass that owns it -- which the comment above
DEFAULTS asserts and nothing checked.
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from database.models import DeviceSettings, UserPreferences

REPO = Path(__file__).resolve().parents[1]
HTML = REPO / "src/web/html/settings.html"
JS = REPO / "src/web/js/settings.js"

# A data-field that is deliberately not in DEFAULTS, and why.
EXEMPT = {
    # A virtual control: the page shows pixels and stores font_size_scale,
    # which IS in DEFAULTS and is what a reset writes.
    "font_size_base_px": "stored as font_size_scale",
}


def _page_fields() -> set[str]:
    html, js = HTML.read_text(encoding="utf-8"), JS.read_text(encoding="utf-8")
    return (set(re.findall(r'data-field="([^"]+)"', html))
            | set(re.findall(r'data-field="([^"]+)"', js))
            | set(re.findall(r"dataset\.field\s*=\s*'([^']+)'", js)))


def _defaults() -> dict:
    body = re.search(r"this\.DEFAULTS = \{(.*?)\n        \};",
                     JS.read_text(encoding="utf-8"), re.S)
    assert body, "could not find SettingsPage.DEFAULTS in settings.js"
    out = {}
    for key, raw in re.findall(r"^\s*([a-z_0-9]+):\s*([^\n]+?),?\s*$", body.group(1), re.M):
        out[key] = json.loads(raw.replace("'", '"'))
    return out


def _python_defaults() -> dict:
    out = {}
    for cls in (UserPreferences, DeviceSettings):
        for f in dataclasses.fields(cls):
            if f.default is not dataclasses.MISSING:
                out.setdefault(f.name, f.default)
    return out


def test_the_readers_find_what_they_should():
    """Controls: a reader that finds nothing makes every test below pass."""
    fields, defaults = _page_fields(), _defaults()
    assert len(fields) >= 40 and len(defaults) >= 40, (len(fields), len(defaults))
    assert {"theme_name", "pane_open_mode", "stt_model_size"} <= fields


def test_every_field_on_the_page_is_reset():
    missing = sorted(_page_fields() - set(_defaults()) - set(EXEMPT))
    assert not missing, (
        f"Reset what Save covers would silently skip {missing}: add each to "
        "SettingsPage.DEFAULTS at its stored default, or to EXEMPT with a reason")


@pytest.mark.parametrize("field", sorted(EXEMPT))
def test_every_exemption_is_still_needed(field):
    assert field in _page_fields(), f"{field} is no longer on the page; drop its exemption"
    assert field not in _defaults(), f"{field} is in DEFAULTS now; drop its exemption"


def test_every_default_is_the_stored_default():
    stored = _python_defaults()
    wrong = {key: (value, stored.get(key, "<no such field>"))
             for key, value in _defaults().items()
             if key not in stored or stored[key] != value}
    assert not wrong, f"DEFAULTS disagrees with the dataclasses (js, python): {wrong}"
