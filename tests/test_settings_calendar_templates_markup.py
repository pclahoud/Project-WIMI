"""Static shape of Settings -> Calendar's session templates list (#778 Wave 4,
decision 10). The behaviour is in
tests/wimi_test/scenarios/test_calendar_series_templates_and_export.py; this
holds the properties a scenario passes through unnoticed.

Templates are rows in session_templates, not preferences, so the block must
carry no data-field (the page's flat save would post an unknown key and
tests/test_settings_defaults_cover_the_page.py would demand a DEFAULTS entry
for a value another table owns, the same reason the self-assessment panel
has none). The list is built from nodes, so the module must not reach for
innerHTML: a template's name is the student's own text.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SETTINGS = (REPO / "src/web/html/settings.html").read_text(encoding="utf-8")
MODULE = (REPO / "src/web/js/settings_calendar.js").read_text(encoding="utf-8")


def _block() -> str:
    m = re.search(r'<div class="form-group" id="calendar-templates">.*?</div>\s*</div>', SETTINGS, re.S)
    assert m, "the templates block is missing from settings.html"
    return m.group(0)


@pytest.mark.unit
def test_the_templates_block_carries_no_data_field():
    assert "data-field" not in _block()


@pytest.mark.unit
def test_the_block_has_its_list_its_empty_state_and_its_error_line():
    block = _block()
    for needle in ('id="calendar-templates-list"', 'id="calendar-templates-empty"', 'id="calendar-templates-error"'):
        assert needle in block, needle
    assert re.search(r'id="calendar-templates-empty"[^>]*\bhidden\b', block), "the empty state ships hidden until the read answers"
    assert re.search(r'id="calendar-templates-error"[^>]*\bhidden\b', block)


@pytest.mark.unit
def test_the_module_is_linked_after_settings_js_and_once():
    scripts = re.findall(r'<script src="\.\./js/([^"]+)"', SETTINGS)
    assert scripts.count("settings_calendar.js") == 1
    assert scripts.index("settings_calendar.js") > scripts.index("settings.js")


@pytest.mark.unit
def test_the_module_builds_rows_from_nodes():
    assert "innerHTML" not in MODULE and "insertAdjacentHTML" not in MODULE
    assert "archiveSessionTemplate" in MODULE and "getSessionTemplates" in MODULE
    code = "\n".join(l for l in MODULE.splitlines() if not l.lstrip().startswith(("*", "/*", "//")))
    assert "data-field" not in code, "no control the module builds may ride the flat save"
