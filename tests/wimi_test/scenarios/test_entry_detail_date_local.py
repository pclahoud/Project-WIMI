"""Regression: entry detail page dates the session one day early.

Forgejo issue #27 -- "Entry detail page dates the session one day early
(same naive ISO-date parse as #4)":

    ``formatDate`` in entry_detail.js [...] passes the bare ``YYYY-MM-DD``
    string to ``new Date(dateStr)``. ECMAScript parses a date-only string
    as UTC midnight and ``toLocaleDateString`` renders it in local time,
    which in any UTC-negative zone [...] is the previous evening. So the
    date shown is one day earlier than stored, at every hour.

Why it fails today: two defects stack on the same lines of ``renderEntry``.
``getEntryWithContext`` returns the session as ``{id, name, date, ...}``
(``get_entry_with_context`` in ``src/database/domains/entries.py``), but
the page reads ``session?.date_encountered`` -- a key that slot has never
emitted -- so the date meta item is hidden outright.  Behind that,
``formatDate`` is the naive ``new Date('YYYY-MM-DD')`` parse from #4,
which prints the previous day anywhere west of Greenwich.  Fixing only
the key would turn a missing date into a wrong one.

What the fix changes: the page reads ``session.date`` and ``formatDate``
builds a local ``new Date(y, m - 1, d)`` from the ISO components (the
pattern ``session_setup.js`` already uses), so the rendered day equals
the stored ``date_encountered`` in every timezone.

Decisiveness: on a UTC-negative machine (the reporter's is
America/New_York) the day-equality assertion is decisive.  On a UTC or
UTC-positive runner the naive parse happens to print the stored day, so
that half of the check is vacuous there; the "date is rendered at all"
half is decisive everywhere.

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
# ``marker`` tells a freshly committed document apart from the one the
# previous goto() left behind; ``ready`` is showContent(), which runs
# after renderEntry() has filled the meta row.
DATE_META = (
    "(() => { const main = document.getElementById('main-content');"
    " const el = document.getElementById('entry-date');"
    " return JSON.stringify({"
    " marker: window.__wimiDetailProbe === 1,"
    " ready: !!main && getComputedStyle(main).display !== 'none',"
    " shown: !!el && getComputedStyle(el).display !== 'none',"
    " text: el ? el.querySelector('.meta-text').textContent.trim() : null"
    " }); })()"
)


def _expected(d: date) -> str:
    """What ``toLocaleDateString('en-US', {month:'short', day:'numeric',
    year:'numeric'})`` prints for a calendar day, e.g. ``Mar 15, 2026``."""
    return f'{MONTHS[d.month - 1]} {d.day}, {d.year}'


def _wait_for_render(wimi_page: WimiPage, *, timeout_ms: int = 10000) -> dict:
    """Poll until the new document has committed and shown its content."""
    elapsed, last = 0, {}
    while elapsed < timeout_ms:
        try:
            last = json.loads(wimi_page.eval_js(DATE_META))
        except Exception:  # context torn down mid-navigation
            last = {}
        if last.get('ready') and not last.get('marker'):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db) -> dict[int, date]:
    """One exam, two sessions (today and a fixed past day), one entry each.

    Returns ``{entry_id: seeded date_encountered}``."""
    exam = db.create_exam_context(exam_name='Detail Date Exam', exam_description='')
    seeded: dict[int, date] = {}
    for label, when in (('today', date.today()), ('fixed', FIXED_DATE)):
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=10, total_incorrect=1,
            session_name=f'Detail date session ({label})', date_encountered=when,
        )
        entry = db.create_question_entry(
            review_session_id=session.id, user_answer='a', correct_answer='b',
            reflection=f'<p>{label}</p>',
        )
        seeded[entry.id] = when
    return seeded


@pytest.mark.slow
@pytest.mark.regression
def test_detail_date_matches_seeded_date_encountered(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    seeded = _seed(wimi_session.user.db)

    for visit, (entry_id, when) in enumerate(seeded.items()):
        # ---- Act -----------------------------------------------------
        if visit:
            # A second goto() to the same page returns before the new
            # document commits: mark the old one and wait for it to vanish.
            wimi_page.eval_js('window.__wimiDetailProbe = 1')
        # ?id= is how the entry browser links to the detail page.
        wimi_page.goto('entry-detail', query={'id': entry_id})
        meta = _wait_for_render(wimi_page)

        # ---- Assert: the stored day is rendered, and rendered as-is ---
        assert meta.get('ready'), (
            f'Entry {entry_id}: detail page never showed its content: {meta!r}'
        )
        assert meta.get('shown'), (
            f'Entry {entry_id} seeded date_encountered={when.isoformat()} but the '
            'date meta item is hidden. renderEntry reads session.date_encountered; '
            'getEntryWithContext emits the session date under session.date.'
        )
        assert meta.get('text') == _expected(when), (
            f'Entry {entry_id} seeded date_encountered={when.isoformat()} but the '
            f'detail page reads {meta.get("text")!r} (expected {_expected(when)!r}). '
            'formatDate parsed the bare ISO date as UTC midnight, which renders '
            'as the previous day in any timezone west of Greenwich.'
        )
