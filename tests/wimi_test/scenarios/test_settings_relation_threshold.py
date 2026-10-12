"""Regression: the relation-proposal cutoff is a slider that saves what it shows (#60, #380).

The owner decided on #380 that the confidence cutoff for relation proposals
is the student's: 0.80 by default, 0.10-0.95 in steps of 0.05, stored in
``user_preferences.relation_confidence_threshold`` (m028). Settings ->
Related Topics carries it as a range input.

This is the first range input on the Settings page, and the page's range
handling had never run against real markup: ``settings.js`` looked for a
``.range-input-group`` wrapper that neither the markup nor ``settings.css``
(``.range-group``) used, so a slider's value display would have stayed
frozen. So this drives the control the way a student does -- focus, then real
``ArrowDown`` presses through CDP -- and checks three things the page could
otherwise get wrong without any error:

* the visible value and ``aria-valuetext`` both say a percentage, and follow
  the slider as it moves;
* the slider is exposed to assistive tech as a slider with its label as its
  name;
* Save writes the number the slider shows, and a reload shows it back.

``el.focus()`` is the one programmatic step, because clicking a range input
moves its thumb to wherever the click lands, which would make the starting
value depend on layout.
"""
from __future__ import annotations

import json

import pytest

from _helpers import a11y
from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SLIDER = "#relation_confidence_threshold"
STATE = """
(() => {
  const el = document.querySelector('#relation_confidence_threshold');
  const shown = document.querySelector('[data-testid="settings-relation-threshold-value"]');
  return JSON.stringify({
    value: el ? el.value : null,
    valuetext: el ? el.getAttribute('aria-valuetext') : null,
    shown: shown ? shown.textContent.trim() : null,
    visible: !!el && el.getBoundingClientRect().height > 0,
    dirty: settingsPage.isDirty,
  });
})()
"""


def _state(page: WimiPage) -> dict:
    return json.loads(page.eval_js(STATE))


def _open_panel(page: WimiPage) -> None:
    page.goto("settings")
    assert poll(page, "(() => !!document.querySelector('%s'))()" % SLIDER), (
        "the Related Topics slider never rendered")
    wait_for_release(page)
    real_click(page, centre_of(page, '[data-testid="settings-nav-related-topics"]'))
    assert poll(page, "JSON.parse((%s)).visible" % STATE.strip()), (
        "the Related Topics panel never became visible")


@pytest.mark.slow
@pytest.mark.regression
def test_the_threshold_slider_shows_moves_and_saves_a_percentage(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    assert db.get_all_settings()['relation_confidence_threshold'] == 0.8, (
        "m028 must default the cutoff to the decided 0.80")

    _open_panel(wimi_page)
    start = _state(wimi_page)
    assert (start["value"], start["shown"], start["valuetext"]) == ("0.8", "80%", "80%"), (
        f"the slider does not show the stored default as a percentage: {start!r}")

    a11y.enable(wimi_page)
    node = a11y.ax_node(wimi_page, SLIDER)
    assert node["role"] == "slider" and "How sure WIMI must be" in (node["name"] or ""), (
        f"the slider is not exposed with its label: {a11y.describe(node)}")

    wimi_page.eval_js("document.querySelector('%s').focus()" % SLIDER)
    for _ in range(9):  # 0.80 -> 0.35 in steps of 0.05
        a11y.real_key(wimi_page, "ArrowDown", settle_ms=60)
    moved = _state(wimi_page)
    assert (moved["value"], moved["shown"], moved["valuetext"]) == ("0.35", "35%", "35%"), (
        f"nine ArrowDown presses did not land on 35%, or the display did not "
        f"follow the slider: {moved!r}")
    assert moved["dirty"] is True, f"moving the slider did not mark the page dirty: {moved!r}"

    real_click(wimi_page, centre_of(wimi_page, "#saveBtn"))
    assert poll(
        wimi_page, "JSON.parse((%s)).dirty === false" % STATE.strip(), timeout_ms=15000), (
        f"Save never completed: {_state(wimi_page)!r}")
    stored = db.get_all_settings()['relation_confidence_threshold']
    assert abs(stored - 0.35) < 1e-9, f"Save stored {stored!r}, the slider showed 35%"

    _open_panel(wimi_page)
    again = _state(wimi_page)
    assert (again["shown"], again["valuetext"]) == ("35%", "35%"), (
        f"a reload does not show the saved cutoff: {again!r}")
