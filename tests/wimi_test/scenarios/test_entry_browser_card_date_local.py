"""Regression: entry browser cards are dated one day early.

Forgejo issue #4 -- "Entry cards are dated one day early":

    entry cards show ``Sep 10, 2026`` for entries created on
    ``2026-09-11``. [...] other surfaces render the same day correctly --
    the session setup card (``Sep 11, 2026``), the dashboard exam card's
    CREATED (``Sep 11, 2026``), the deep dive's LAST MISTAKE (``Today``).
    Only the entry browser card is wrong.

Why it failed: the card shows the session's ``date_encountered``, which
the bridge emits as ``date.isoformat()`` -- a bare ``YYYY-MM-DD``.
``formatDate`` in ``entry_browser.js`` passed that straight to
``new Date(dateStr)``. ECMAScript parses a date-only ISO string as UTC
midnight, and ``toLocaleDateString`` then renders it in local time, which
in any zone west of Greenwich is the previous evening -- so the day is
one less, at every hour of the day, not only after 20:00.

What the fix changes: ``formatDate`` splits the ``YYYY-MM-DD`` prefix and
builds a local ``new Date(y, m - 1, d)`` (the pattern ``session_setup.js``
and ``landing.js`` already use), so the rendered day equals the stored
day in every timezone.

The test seeds one entry dated today and one on a fixed date far from
today, and compares each card's text with the exact string the page's
rule must produce for the seeded date. The fixed date makes the check
independent of when the suite runs.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FIXED_DATE = date(2026, 3, 15)
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
CARD_COUNT = "document.querySelectorAll('#entryGrid [data-entry-id]').length"
CARD_DATES = (
    "JSON.stringify([...document.querySelectorAll('#entryGrid [data-entry-id]')]"
    ".map(c => ({id: Number(c.dataset.entryId),"
    " date: c.querySelector('.entry-date').textContent.trim()})))"
)
SESSION_META = (
    "JSON.stringify([...document.querySelectorAll("
    "'#sessionList [data-testid^=\"browser-session-item-\"] .session-meta')]"
    ".map(m => m.textContent.trim()))"
)


def _expected(d: date) -> str:
    """What ``toLocaleDateString('en-US', {month:'short', day:'numeric',
    year:'numeric'})`` prints for a calendar day, e.g. ``Mar 15, 2026``."""
    return f'{MONTHS[d.month - 1]} {d.day}, {d.year}'


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


def _seed(db) -> tuple[int, dict[int, date]]:
    """One exam, two sessions (today and a fixed past day), one entry each.

    Returns ``(exam_id, {entry_id: seeded date_encountered})``."""
    exam = db.create_exam_context(exam_name='Card Date Exam', exam_description='')
    seeded: dict[int, date] = {}
    for label, when in (('today', date.today()), ('fixed', FIXED_DATE)):
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=10, total_incorrect=1,
            session_name=f'Card date session ({label})', date_encountered=when,
        )
        entry = db.create_question_entry(
            review_session_id=session.id, user_answer='a', correct_answer='b',
            reflection=f'<p>{label}</p>',
        )
        seeded[entry.id] = when
    return exam.id, seeded


@pytest.mark.slow
@pytest.mark.regression
def test_card_date_matches_seeded_date_encountered(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, seeded = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    # ?exam= is what populates the session filter's sidebar.
    wimi_page.goto('entry-browser', query={'exam': exam_id})
    cards = _poll(wimi_page, CARD_COUNT, len(seeded))
    assert cards == len(seeded), f'Expected {len(seeded)} cards, got {cards!r}'
    rendered = {c['id']: c['date'] for c in json.loads(wimi_page.eval_js(CARD_DATES))}
    session_meta = json.loads(wimi_page.eval_js(SESSION_META))

    # ---- Assert: each card prints the day that was stored -----------
    assert set(rendered) == set(seeded), (rendered, seeded)
    for entry_id, when in seeded.items():
        assert rendered[entry_id] == _expected(when), (
            f'Entry {entry_id} seeded date_encountered={when.isoformat()} but the '
            f'card reads {rendered[entry_id]!r} (expected {_expected(when)!r}). '
            'formatDate parsed the bare ISO date as UTC midnight, which renders '
            'as the previous day in any timezone west of Greenwich.'
        )
    # The session filter's sidebar renders session.date through the same
    # helper; it must agree with the card for the fixed-date session.
    assert any(m.startswith(_expected(FIXED_DATE)) for m in session_meta), (
        f'Session filter list does not show {_expected(FIXED_DATE)!r}: {session_meta!r}'
    )
