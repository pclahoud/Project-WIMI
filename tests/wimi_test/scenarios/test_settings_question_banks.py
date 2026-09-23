"""Regression: Settings -> Question Banks, the browser pane's control panel.

The panel (``settings.html``, ``data-panel="question_banks"``) is the only
place a student fills in a question bank's web address, toggles its
per-site "Desktop site" user-agent, and chooses where the pane opens.
Nothing drove it before this scenario; the pane's own scenario covers
the entry-form toggle button only.

Three JS-side rules that backend tests cannot see:

1. Rows: every source is listed, but only one with an address gets the
   Desktop site checkbox, and only those populate the "Question bank to
   open" picker.
2. A bare host ("amboss.com") is normalised to https:// and saved on
   change through ``updateQuestionSource``; the row then earns its
   checkbox without a reload.
3. The three preference selects save through the page's ordinary Save
   button and are restored on the next visit -- including the source
   picker, whose options do not exist yet when ``populateForm`` runs.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

ROW_COUNT = "document.querySelectorAll('#questionBankList .qbank-row').length"
FRESH_DOC = "typeof window.__wimiPrevDoc === 'undefined' && typeof window.api === 'object'"


def _poll(wimi_page: WimiPage, js: str, want, *, timeout_ms: int = 10000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _poll_db(wimi_page: WimiPage, read, want, *, timeout_ms: int = 10000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        last = read()
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _open_panel(wimi_page: WimiPage, expected_rows: int) -> None:
    # Mark the current document so a re-visit cannot pass on the stale page:
    # Page.navigate returns before the new document commits.
    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('settings')
    assert _poll(wimi_page, FRESH_DOC, True) is True, 'Settings page did not (re)load'
    assert _poll(wimi_page, ROW_COUNT, expected_rows) == expected_rows, \
        'Question bank rows never rendered'
    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"settings-nav-question-banks\"]').click()"
    )
    assert wimi_page.eval_js(
        "document.querySelector('.settings-panel[data-panel=\"question_banks\"]')"
        ".classList.contains('active')"
    ), 'Question Banks panel did not activate'


def _rows(wimi_page: WimiPage) -> list[dict]:
    return json.loads(wimi_page.eval_js(
        "JSON.stringify(Array.from(document.querySelectorAll('#questionBankList .qbank-row'))"
        ".map(r => ({ id: r.dataset.sourceId, url: r.querySelector('.qbank-row-url').value,"
        " desktop: (cb => cb ? cb.checked : null)(r.querySelector('input[type=checkbox]')) })))"
    ))


def _picker_options(wimi_page: WimiPage) -> list[str]:
    return json.loads(wimi_page.eval_js(
        "JSON.stringify(Array.from(document.getElementById('pane_default_source_id').options)"
        ".map(o => o.value))"
    ))


def _set_and_change(wimi_page: WimiPage, element_id: str, value: str) -> None:
    wimi_page.eval_js(
        "(() => { const el = document.getElementById(" + json.dumps(element_id) + ");"
        " el.value = " + json.dumps(value) + ";"
        " el.dispatchEvent(new Event('change', {bubbles: true})); return el.value; })()"
    )


def _seed(db):
    uworld = db.create_question_source(source_name='UWorld', url='https://uworld.com')
    amboss = db.create_question_source(source_name='Amboss')
    return uworld, amboss


@pytest.mark.slow
@pytest.mark.regression
def test_rows_address_entry_and_desktop_site(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    uworld, amboss = _seed(db)
    _open_panel(wimi_page, 2)

    # ---- Assert: addressed banks first, then the rest; checkbox only with an address
    assert _rows(wimi_page) == [
        {'id': str(uworld.id), 'url': 'https://uworld.com', 'desktop': True},
        {'id': str(amboss.id), 'url': '', 'desktop': None},
    ]
    assert _picker_options(wimi_page) == [str(uworld.id)]

    # ---- Act: give Amboss a bare host; https:// is added and it is saved on change
    _set_and_change(wimi_page, f'qbank-url-{amboss.id}', 'amboss.com')
    assert _poll_db(wimi_page, lambda: db.get_question_source(amboss.id).url,
                    'https://amboss.com') == 'https://amboss.com'
    assert _poll(wimi_page, f"!!document.getElementById('qbank-desktop-{amboss.id}')", True) \
        is True, 'Row did not re-render with a Desktop site checkbox after gaining an address'
    assert sorted(_picker_options(wimi_page)) == sorted([str(uworld.id), str(amboss.id)])

    # ---- Act: turn Desktop site off for UWorld; persisted per source
    wimi_page.eval_js(f"document.getElementById('qbank-desktop-{uworld.id}').click()")
    flags = lambda: {s['id']: s['desktop_site'] for s in db.get_pane_sources()}
    assert _poll_db(wimi_page, flags, {uworld.id: False, amboss.id: True}) == \
        {uworld.id: False, amboss.id: True}


@pytest.mark.slow
@pytest.mark.regression
def test_pane_preferences_save_and_restore(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    uworld, amboss = _seed(db)
    db.update_question_source(amboss.id, url='https://amboss.com')
    _open_panel(wimi_page, 2)
    # Never-opened banks list alphabetically, so Amboss is the picker's first option.
    assert _picker_options(wimi_page) == [str(amboss.id), str(uworld.id)]

    # ---- Act: pick the SECOND option, so a restore that falls back to the first is caught
    _set_and_change(wimi_page, 'pane_open_mode', 'source')
    _set_and_change(wimi_page, 'pane_shortcut_opens', 'new')
    _set_and_change(wimi_page, 'pane_default_source_id', str(uworld.id))
    wimi_page.eval_js("document.getElementById('saveBtn').click()")

    def saved():
        p = db.get_preferences()
        return (p.pane_open_mode, p.pane_shortcut_opens, p.pane_default_source_id)
    assert _poll_db(wimi_page, saved, ('source', 'new', uworld.id)) == ('source', 'new', uworld.id)

    # ---- Assert: a fresh visit shows exactly what was saved
    _open_panel(wimi_page, 2)
    shown = json.loads(wimi_page.eval_js(
        "JSON.stringify(['pane_open_mode', 'pane_shortcut_opens', 'pane_default_source_id']"
        ".map(id => document.getElementById(id).value))"
    ))
    assert shown == ['source', 'new', str(uworld.id)], (
        f'Saved pane preferences were not restored on reload: {shown!r}. populateForm '
        'runs before the source picker has options, so the saved id must be re-applied '
        'once renderPaneOpenMode fills them.'
    )
