"""Regression: Settings -> Anki never shows a state the database refused, and
names the port a job really dialled (#802 review notes 3 and 5).

Note 5: only the field-visibility checkbox put itself back when its save
failed; the switch, the display mode and the rest stayed where the student
left them, claiming a setting that was never stored. The save is made to fail
from inside the page (``api.updateUserPreferences`` rejects), which is the
only failure a student can meet here -- the bridge's own refusals are covered
by the database tests.

Note 3: "Fetch this exam's cards now" said which port answered nothing by
reading the box, which may hold a typed value that was never saved, while the
job dialled the saved one.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.anki_settings import (
    closed_port, open_panel, poll_true, preferences, set_and_change, text_of,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

REFUSE = ("window.__realUpdate = api.updateUserPreferences;"
          " api.updateUserPreferences = async () => { throw new Error('disk full'); };")
RESTORE = "api.updateUserPreferences = window.__realUpdate;"


@pytest.mark.slow
@pytest.mark.regression
def test_a_refused_save_puts_the_control_back(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.create_exam_context(exam_name='Step X')
    db.create_question_source(source_name='Bank', exam_context='Step X')
    open_panel(wimi_page, banks=1)
    assert not wimi_page.eval_js("document.getElementById('anki-enabled').checked")
    assert wimi_page.eval_js("document.getElementById('anki-display-mode').value") == 'card'

    wimi_page.eval_js(REFUSE)
    wimi_page.locator(css='#anki-enabled').click()
    assert poll_true(wimi_page, "document.getElementById('anki-connection-status')"
                                ".textContent.startsWith('Could not save')")
    assert not wimi_page.eval_js("document.getElementById('anki-enabled').checked"), \
        'the switch kept a state that was not stored'

    set_and_change(wimi_page, 'anki-display-mode', 'note')
    assert poll_true(wimi_page, "document.getElementById('anki-prefs-status')"
                                ".textContent.startsWith('Could not save')")
    assert wimi_page.eval_js("document.getElementById('anki-display-mode').value") == 'card'

    # Control: with the save working again the same press sticks.
    wimi_page.eval_js(RESTORE)
    wimi_page.locator(css='#anki-enabled').click()
    assert poll_true(wimi_page, "document.getElementById('anki-connection-status')"
                                ".textContent === 'Saved.'")
    assert wimi_page.eval_js("document.getElementById('anki-enabled').checked")
    assert preferences(wimi_page)['anki_integration_enabled'] is True


@pytest.mark.slow
@pytest.mark.regression
def test_a_failed_fetch_names_the_saved_port_not_the_typed_one(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Step X')
    bank = db.create_question_source(source_name='Bank', exam_context='Step X')
    db.anki_add_template(exam.id, bank.id, 'tag:Bank::{{qid}}')
    session = db.create_review_session(exam_context_id=exam.id, total_questions=5,
                                       total_incorrect=1, question_source_id=bank.id)
    db.create_question_entry(session.id, 'A', 'B', question_id='7')
    open_panel(wimi_page, banks=1)

    saved = closed_port()
    wimi_page.locator(css='#anki-enabled').click()
    assert poll_true(wimi_page, "document.getElementById('anki-connection-status')"
                                ".textContent === 'Saved.'")
    set_and_change(wimi_page, 'anki-port', str(saved))
    assert poll_true(wimi_page, "document.getElementById('anki-connection-status')"
                                ".textContent === 'Saved.'")
    # Typed and never saved: no change event, so the job still dials `saved`.
    wimi_page.eval_js("document.getElementById('anki-port').value = '9999'")

    wimi_page.locator(css='#anki-sync-exam').click()
    assert poll_true(wimi_page, "document.getElementById('anki-sync-status')"
                                ".textContent.startsWith('Nothing answered on port')"), \
        text_of(wimi_page, 'anki-sync-status')
    message = text_of(wimi_page, 'anki-sync-status')
    assert f'port {saved}.' in message and '9999' not in message, message
