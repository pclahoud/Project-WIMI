"""Static shape of the calendar page (#778 Wave 2). The behaviour is in the
scenarios; this holds the markup properties a scenario would pass through
unnoticed, and the two stylesheet and script rules the plan made load-bearing:
no hex literal paints a chip (an exam's colour arrives as custom properties
written by calendar.js), and the page never links escape.js because it builds
every node and escapes nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HTML = (REPO / "src/web/html/calendar.html").read_text(encoding="utf-8")
JS = (REPO / "src/web/js/calendar.js").read_text(encoding="utf-8")
CSS = (REPO / "src/web/css/calendar.css").read_text(encoding="utf-8")


@pytest.mark.unit
def test_the_grid_is_a_labelled_grid_with_column_headers():
    assert re.search(r'<table class="cal-grid" id="cal-grid" role="grid" aria-labelledby="cal-range"', HTML)
    assert HTML.count('<th scope="col"') == 7
    assert HTML.count("<abbr title=") == 7
    assert 'data-weekday="0"><abbr title="Monday">' in HTML, "weeks start Monday (decision 8)"


@pytest.mark.unit
def test_the_three_tour_anchors_exist():
    for anchor in ("cal-grid", "cal-plan", "cal-legend"):
        assert f'data-tour-anchor="{anchor}"' in HTML, anchor


@pytest.mark.unit
def test_the_range_heading_ships_empty_and_focusable():
    assert '<h2 class="cal-range" id="cal-range" tabindex="-1"></h2>' in HTML


@pytest.mark.unit
def test_links_local_date_and_not_escape_js():
    assert '../js/local_date.js' in HTML
    assert 'escape.js' not in HTML
    assert 'd3' not in HTML.lower().replace("data-", "")


@pytest.mark.unit
def test_both_modals_follow_the_shared_pattern():
    surfaces = re.findall(r'<div class="cal-modal" data-modal-surface role="dialog" aria-modal="true" aria-labelledby="([^"]+)">', HTML)
    assert sorted(surfaces) == ["cal-plan-title", "cal-remove-title"]
    for title_id in surfaces:
        assert re.search(rf'<h2 class="modal-title" id="{title_id}">', HTML), title_id
    assert HTML.count('class="cal-modal-backdrop"') == 2
    assert '../js/modal_dialog.js' in HTML


@pytest.mark.unit
def test_no_hex_literal_paints_a_chip():
    """Chip colours are theme tokens or custom properties set from the exam's
    stored colour at runtime. The only hex literals allowed are the two
    black/white text fallbacks the derivation picks between."""
    css_hex = re.findall(r"#[0-9a-fA-F]{6}\b", CSS)
    assert css_hex == [], css_hex
    js_hex = sorted(set(re.findall(r"'#[0-9a-fA-F]{6}'", JS)))
    assert js_hex == ["'#111111'", "'#ffffff'"], js_hex


@pytest.mark.unit
def test_series_slots_never_use_the_error_triple():
    assert "--color-error" not in CSS.replace("--color-error-text", "")
    for slot in ("primary", "success", "warning", "info"):
        assert f"var(--color-{slot}-bg)" in CSS and f"var(--color-{slot}-text)" in CSS, slot


@pytest.mark.unit
def test_the_page_builds_nodes_and_never_sets_innerhtml():
    assert ".innerHTML" not in JS and "insertAdjacentHTML" not in JS and ".outerHTML" not in JS


@pytest.mark.unit
def test_the_state_is_on_window_and_the_gate_releases_on_every_exit():
    assert "window.CalendarState = {" in JS
    assert JS.count("markCalendarReady(") >= 3, "success, failure and fail-open"
    assert "GATE_FAIL_OPEN_MS = 15000" in JS


@pytest.mark.unit
def test_start_hands_session_setup_the_plan_and_exam_ids():
    assert "session_setup.html?planned_id=" in JS
    assert "&exam_id=" in JS


def test_a_hidden_modal_backdrop_is_not_displayed():
    """`display: flex` on `.cal-modal-backdrop` outranks the user agent's
    `[hidden] { display: none }`. Without an explicit attribute rule both
    dialogs painted on load and modal_dialog.js hid the rest of the page from
    assistive tech (measured: 18 exposed nodes, all the Remove dialog). The
    scenario measures it rendered; this pins the rule in the stylesheet."""
    css = (REPO / "src/web/css/calendar.css").read_text(encoding="utf-8")
    rule = re.search(r"\.cal-modal-backdrop\[hidden\]\s*\{([^}]*)\}", css)
    assert rule, "calendar.css has no .cal-modal-backdrop[hidden] rule"
    assert re.search(r"display\s*:\s*none", rule.group(1)), rule.group(0)
