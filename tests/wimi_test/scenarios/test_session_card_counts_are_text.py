"""Regression: a previous session's counts render as text, never markup (#548).

``renderPreviousSessionCard`` drew ``total_questions``, ``total_incorrect`` and
``entries_completed`` raw. They are INTEGER-affinity columns, and affinity is
not enforcement: SQLite stores text that will not convert *as text*, and text
compares greater than any integer, so ``CHECK (total_questions > 0)`` passes
it. A profile arriving by ``.wimi`` import, restore or folder-sync install is
copied byte for byte, and #593's schema check compares structure, not values,
so such a row reaches this page unchanged.

The values are written with plain SQL, past the domain layer, because that is
the only way such a row exists: WIMI's own writers never produce one. The
#548 re-read found this sink among the 57 judged safe "on a database WIMI
wrote", and that premise is exactly what an installed profile does not keep.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# One payload per column, each marking where it ran, so a failure names the
# column rather than "something executed".
PAYLOADS = {
    col: f'<img src=x data-testid="injected-{col}" onerror="window.__card_{col}=1">'
    for col in ('total_questions', 'total_incorrect', 'entries_completed')
}

CARD_STATE = """
(() => {
  const card = document.querySelector('[data-testid="session-card-%d"]');
  if (!card) return null;
  return JSON.stringify({
    injected: card.querySelectorAll('[data-testid^="injected-"]').length,
    ran: %s.filter(c => window['__card_' + c] === 1),
    values: [...card.querySelectorAll('.prev-session-stat-value')].map(v => v.textContent),
  });
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_counts_carrying_markup_render_as_their_own_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Counts Exam', exam_description='#548')
    hostile = db.create_review_session(
        exam_context_id=exam.id, total_questions=2, total_incorrect=1,
        session_name='Hostile counts', date_encountered=date.today())
    honest = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=4,
        session_name='Honest counts', date_encountered=date.today())
    db.conn.execute(
        'UPDATE review_sessions SET total_questions = ?, total_incorrect = ?,'
        ' entries_completed = ? WHERE id = ?',
        (PAYLOADS['total_questions'], PAYLOADS['total_incorrect'],
         PAYLOADS['entries_completed'], hostile.id))
    db.conn.commit()
    # The premise of the test, checked rather than assumed: SQLite kept text.
    kinds = db.conn.execute(
        'SELECT typeof(total_questions), typeof(total_incorrect),'
        ' typeof(entries_completed) FROM review_sessions WHERE id = ?',
        (hostile.id,)).fetchone()
    assert tuple(kinds) == ('text', 'text', 'text'), kinds

    wimi_page.goto('session-setup', query={'exam_id': exam.id})
    assert poll(wimi_page, "!!document.querySelector('[data-testid=\"session-card-%d\"]')"
                " && !document.querySelector('[data-page-gated][inert]')" % honest.id,
                timeout_ms=20000), 'the previous-session cards never drew'
    wimi_page.wait_for_timeout(500)   # a broken <img>'s onerror fires async

    # Positive control: the honest card drew its numbers.
    honest_state = json.loads(wimi_page.eval_js(CARD_STATE % (honest.id, '[]')))
    assert honest_state['values'] == ['10', '4', '0/4'], honest_state

    state = wimi_page.eval_js(CARD_STATE % (hostile.id, json.dumps(list(PAYLOADS))))
    assert state is not None, 'the card for the session with text counts never drew'
    state = json.loads(state)
    assert state['injected'] == 0, f'a count became an element on the card: {state}'
    assert state['ran'] == [], f'an injected handler ran for {state["ran"]}'
    assert state['values'] == [
        PAYLOADS['total_questions'],
        PAYLOADS['total_incorrect'],
        f"{PAYLOADS['entries_completed']}/{PAYLOADS['total_incorrect']}",
    ], state
