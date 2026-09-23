"""Regression: session progress draws past 100% when entries outnumber the estimate.

Forgejo issue #8 -- "Session progress renders '11/10' and '110% complete'
with the bar past its track":

    A session declaring ``total_incorrect = 10`` that has 11 logged entries
    renders ``LOGGED 11/10``, ``110% complete`` and a progress bar filled
    past the end of its track. The entry form header shows the other half
    of the same assumption: ``Entry 1 of 10``, above a pager with 11 dots.
    [...] a student hits the same state by logging one more mistake than
    they first counted, which is ordinary.

Why it failed: ``renderPreviousSessionCard`` in ``session_setup.js`` computes
``entries_completed / total_incorrect`` and pours the unclamped figure into
both the ``progress-text`` and the fill's ``width``. In ``question_entry.js``
the ``Entry N of M`` counter, the pager and the Save & Next bounds all read
``session.total_incorrect`` -- the session's *estimate* -- so an entry past
that estimate is neither counted nor reachable.

What the fix changes: the card clamps the percentage (and so the bar) at
100 while the raw ``11/10`` count stays honest; the entry form derives one
slot count shared by the header and the pager -- the declared count widened
to cover every entry that exists -- so the header reads ``Entry 1 of 11``
over 11 dots.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

DECLARED, LOGGED = 10, 11

CARD_STATE = """
(() => {
  const card = document.querySelector('[data-testid="session-card-%d"]');
  if (!card) return null;
  const fill = card.querySelector('.progress-fill');
  const text = card.querySelector('.progress-text');
  if (!fill || !text || !text.textContent.trim()) return null;
  const stats = [...card.querySelectorAll('.prev-session-stat')]
    .map(s => [s.querySelector('.prev-session-stat-label').textContent.trim(),
               s.querySelector('.prev-session-stat-value').textContent.trim()]);
  return JSON.stringify({
    logged: Object.fromEntries(stats)['Logged'],
    text: text.textContent.trim(),
    width: fill.style.width,
    fillPx: fill.getBoundingClientRect().width,
    trackPx: fill.parentElement.getBoundingClientRect().width,
  });
})()
"""
HEADER_STATE = """
(() => {
  const counter = document.getElementById('entry-counter');
  const dots = document.querySelectorAll('#entry-dots .entry-dot').length;
  if (!counter || !dots) return null;
  return JSON.stringify({counter: counter.textContent.trim(), dots});
})()
"""


def _poll(wimi_page: WimiPage, js: str, *, timeout_ms: int = 15000):
    """Poll ``js`` until it returns something other than ``null``."""
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last is not None:
            return json.loads(last)
        wimi_page.wait_for_timeout(200)
        elapsed += 200
    return None


def _seed(db) -> tuple[int, int]:
    """One exam, one session declaring 10 incorrect, 11 complete entries."""
    exam = db.create_exam_context(exam_name='Progress Overflow Exam', exam_description='')
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name='Overflow topic', level_type='System',
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=40, total_incorrect=DECLARED,
        session_name='Overflow session', date_encountered=date.today(),
    )
    for i in range(LOGGED):
        # reflection + explanation + a primary subject make the entry
        # non-draft, so each one bumps entries_completed.
        db.create_question_entry(
            review_session_id=session.id, user_answer='a', correct_answer='b',
            reflection=f'<p>r{i}</p>', explanation=f'<p>e{i}</p>',
            primary_subject_ids=[subject.id],
        )
    assert db.get_review_session(session.id).entries_completed == LOGGED
    return exam.id, session.id


@pytest.mark.slow
@pytest.mark.regression
def test_session_card_progress_clamps_at_100(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, session_id = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('session-setup', query={'exam_id': exam_id})
    card = _poll(wimi_page, CARD_STATE % session_id)
    assert card is not None, f'Session card {session_id} never rendered'

    # ---- Assert ------------------------------------------------------
    # The raw count is honest and stays; the percentage and the bar clamp.
    assert card['logged'] == f'{LOGGED}/{DECLARED}', card
    assert card['text'] == '100% complete', (
        f"Card reads {card['text']!r}: the percentage was not clamped ({card})")
    width_pct = float(card['width'].rstrip('%'))
    assert width_pct <= 100, f"Bar width {card['width']} exceeds its track ({card})"
    assert card['fillPx'] <= card['trackPx'] + 0.5, (
        f"Bar fill {card['fillPx']}px is wider than its {card['trackPx']}px track")


@pytest.mark.slow
@pytest.mark.regression
def test_entry_form_header_counts_existing_entries(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    _exam_id, session_id = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('entry-form', query={'session_id': session_id})
    header = _poll(wimi_page, HEADER_STATE)
    assert header is not None, 'Entry navigation never rendered'

    # ---- Assert: header and pager read the same slot count ----------
    assert header['dots'] == LOGGED, f'Pager drew {header["dots"]} dots, expected {LOGGED}'
    assert header['counter'] == f'Entry 1 of {LOGGED}', (
        f"Header reads {header['counter']!r}; its denominator must be the number "
        f"of entries that exist ({LOGGED}), not the session's estimate ({DECLARED})")
