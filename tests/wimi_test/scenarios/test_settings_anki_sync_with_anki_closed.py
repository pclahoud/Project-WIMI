"""Regression: "Fetch this exam's cards now" with Anki closed changes nothing.

The cache already holds two cards for an entry. Anki is switched on in the
panel and pointed at a port with nothing listening, and Fetch is pressed. The
student must be told, in the error style, that nothing answered and that what
was fetched before is unchanged -- and the database must agree: the same
match, the same card ids, the same review log. A closed Anki that read as
"no cards" would wipe the cache, which is the failure this guards (#784 Wave 2
finding 1, now seen through the page a student actually presses).

The positive control runs first in the same session: with the fake
AnkiConnect answering, the same button fetches, so the negative arm cannot
pass on a button that never reached the bridge.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.anki_settings import (
    closed_port, is_error, open_panel, poll_true, set_and_change, text_of,
)
from tests._fake_ankiconnect import FakeAnkiConnect
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

STATUS = 'anki-sync-status'


def _snapshot(db, entry_id: int) -> tuple:
    cache = db.anki_get_entry_cache(entry_id)
    cards = cache.get('cards') or []
    return (sorted(db.anki_entry_card_ids(entry_id)),
            sorted((c['card_id'], len(c.get('reviews') or [])) for c in cards))


def _enable_on(wimi_page: WimiPage, port: int) -> None:
    if not wimi_page.eval_js("document.getElementById('anki-enabled').checked"):
        wimi_page.locator(css='#anki-enabled').click()
    assert poll_true(wimi_page, "document.getElementById('anki-connection-status')"
                                ".textContent === 'Saved.'")
    set_and_change(wimi_page, 'anki-port', str(port))
    assert poll_true(wimi_page, "document.getElementById('anki-connection-status')"
                                ".textContent === 'Saved.'")


def _press_fetch(wimi_page: WimiPage) -> None:
    wimi_page.eval_js(f"document.getElementById('{STATUS}').textContent = ''")
    wimi_page.locator(css='#anki-sync-exam').click()


@pytest.mark.slow
@pytest.mark.regression
def test_fetch_with_anki_closed_keeps_what_was_fetched(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Step X')
    bank = db.create_question_source(source_name='Bank', exam_context='Step X')
    db.anki_add_template(exam.id, bank.id, 'tag:Bank::{{qid}}')
    session = db.create_review_session(exam_context_id=exam.id, total_questions=5,
                                       total_incorrect=1, question_source_id=bank.id)
    entry = db.create_question_entry(session.id, 'A', 'B', question_id='7')
    open_panel(wimi_page, banks=1)

    # ---- Positive control: the fake answers and the button fetches two cards
    with FakeAnkiConnect() as anki:
        anki.searches['tag:Bank::7'] = [101, 102]
        anki.add_card(101, note_id=10, interval=12, queue=2,
                      fields={'Front': {'value': 'Front', 'order': 0}})
        anki.add_card(102, note_id=10, interval=3, queue=0)
        anki.reviews[101] = [{'id': 1_700_000_000_000, 'ivl': 12, 'factor': 2500,
                              'time': 4000, 'ease': 3, 'lastIvl': 4, 'type': 1}]
        _enable_on(wimi_page, anki.port)
        _press_fetch(wimi_page)
        assert poll_true(wimi_page, f"document.getElementById('{STATUS}')"
                                    ".textContent.startsWith('Fetched cards for 1 of 1')"), \
            text_of(wimi_page, STATUS)
        assert not is_error(wimi_page, STATUS)
    before = _snapshot(db, entry.id)
    assert before == ([101, 102], [(101, 1), (102, 0)]), before

    # ---- Act: Anki closed -- nothing listening on the saved port
    _enable_on(wimi_page, closed_port())
    _press_fetch(wimi_page)

    # ---- Assert: a sentence in the error style, and the cache untouched
    assert poll_true(wimi_page, f"document.getElementById('{STATUS}')"
                                ".textContent.startsWith('Nothing answered on port')"), \
        text_of(wimi_page, STATUS)
    assert 'Nothing that was fetched before has changed.' in text_of(wimi_page, STATUS)
    assert is_error(wimi_page, STATUS)
    assert _snapshot(db, entry.id) == before
    assert not wimi_page.eval_js("document.getElementById('anki-sync-exam').disabled")
