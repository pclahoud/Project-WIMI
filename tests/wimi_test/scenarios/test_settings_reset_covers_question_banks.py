"""Regression: Reset what Save covers resets the three Question Banks choices (#509).

``resetToDefaults()`` posts ``SettingsPage.DEFAULTS`` wholesale, and the
three pane preferences were not in it, so a student who pressed the Reset
button (then **Reset to Defaults**, #652 renamed it) kept their old choices -- and ``populateForm`` redrew them from
the response, so the panel positively confirmed a reset that skipped it.

The static guard (``tests/test_settings_defaults_cover_the_page.py``) holds
DEFAULTS to the page; this drives the real button and reads the database.

The page asks ``confirm()`` first, and QtWebEngine raises a real modal dialog
for it that nothing in the harness answers, so the scenario answers it by
replacing ``window.confirm`` on the loaded page.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FRESH_DOC = "typeof window.__wimiPrevDoc === 'undefined' && typeof window.api === 'object'"
PICKER_FILLED = "document.querySelectorAll('#pane_default_source_id option[value]:not([value=\"\"])').length"


def _poll(wimi_page: WimiPage, read, want, *, timeout_ms: int = 10000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_reset_to_defaults_resets_the_question_bank_choices(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    bank = db.create_question_source(source_name='UWorld', url='https://uworld.com')
    db.update_settings(pane_open_mode='source', pane_shortcut_opens='new',
                       pane_default_source_id=bank.id, theme_name='midnight')

    def stored():
        p = db.get_preferences()
        return (p.pane_open_mode, p.pane_shortcut_opens, p.pane_default_source_id,
                p.theme_name)

    assert stored() == ('source', 'new', bank.id, 'midnight'), "arrange did not stick"

    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('settings')
    assert _poll(wimi_page, lambda: wimi_page.eval_js(FRESH_DOC), True) is True
    assert _poll(wimi_page, lambda: wimi_page.eval_js(PICKER_FILLED), 1) == 1, (
        "the question bank picker never filled")
    assert wimi_page.eval_js("document.getElementById('pane_open_mode').value") == 'source', (
        "positive control: the page did not show the non-default choice it was given")

    wimi_page.eval_js("window.confirm = () => true")
    wimi_page.eval_js("document.getElementById('resetDefaultsBtn').click()")

    # theme_name was always in DEFAULTS: it proves the reset ran at all, so a
    # pane value left behind is the reset skipping it, not the reset not firing.
    assert _poll(wimi_page, lambda: stored()[3], 'default') == 'default', (
        "the reset never reached the database")
    assert stored()[:3] == ('last', 'current', None), (
        f"Reset what Save covers left the Question Banks choices alone: {stored()[:3]!r}")
    assert wimi_page.eval_js("document.getElementById('pane_open_mode').value") == 'last'
    assert wimi_page.eval_js("document.getElementById('pane_shortcut_opens').value") == 'current'
