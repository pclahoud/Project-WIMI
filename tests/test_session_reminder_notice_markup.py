"""Static shape of #778 Wave 3's dashboard reminder notice (owner decision 7).
The behaviour is in the scenario; this holds the markup properties a
scenario would pass through unnoticed: it ships hidden, its hidden state is
not overridden by the stylesheet, its three actions exist, the module is
linked after landing.js, and the module writes text, never markup.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INDEX = (REPO / "src/web/html/index.html").read_text(encoding="utf-8")
CSS = (REPO / "src/web/css/landing.css").read_text(encoding="utf-8")
MODULE = (REPO / "src/web/js/session_reminder_notice.js").read_text(encoding="utf-8")


def _tag(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.S)
    assert m, pattern
    return m.group(0)


@pytest.mark.unit
def test_the_notice_ships_hidden_and_the_stylesheet_lets_hidden_win():
    section = _tag(INDEX, r'<section class="session-reminder-notice"[^>]*>')
    assert " hidden" in section
    rule = re.search(r"\.session-reminder-notice\[hidden\]\s*\{([^}]*)\}", CSS)
    assert rule and re.search(r"display\s*:\s*none", rule.group(1)), "display: flex would show an empty banner"


@pytest.mark.unit
def test_the_notice_has_its_three_actions():
    block = _tag(INDEX, r'<section class="session-reminder-notice".*?</section>')
    assert 'id="session-reminder-start"' in block
    assert 'id="session-reminder-calendar"' in block and 'href="calendar.html"' in block
    assert 'id="session-reminder-dismiss"' in block


@pytest.mark.unit
def test_the_module_is_linked_after_landing_js_and_writes_text_only():
    scripts = re.findall(r'<script src="([^"]+)">', INDEX)
    assert scripts.index("../js/session_reminder_notice.js") > scripts.index("../js/landing.js")
    assert "innerHTML" not in MODULE and "insertAdjacentHTML" not in MODULE
    assert "api.getSessionReminders()" in MODULE and "api.dismissSessionReminders()" in MODULE
    assert "window.loadSessionReminderNotice" in MODULE


@pytest.mark.unit
def test_the_module_builds_no_date_so_it_needs_no_localdate_link():
    """Days arrive as YYYY-MM-DD strings and are shown as such. If a Date is
    ever built here, link local_date.js and use LocalDate.parse (#286)."""
    assert "new Date(" not in MODULE and "toISOString" not in MODULE
