"""Regression: entry browser header counter disagrees with the rendered cards.

Forgejo issue #2 -- "Entry browser header reads '0 entries · 0 drafts'
while 11 cards render":

    the header counter reads `0 entries · 0 drafts` while 11 entry cards
    are rendered below it. [...] `document.body.innerText.match(/\\d+
    entries[^\\n]*/)` returned "0 entries" while
    `document.querySelectorAll('[data-entry-id]').length` returned 11, so
    it is not a render-order race that settles later.

Why it failed: the cards and the header read two different bridge slots.
``loadEntries`` calls ``getEntriesPaginated`` and only adds
``exam_context_id`` when the page was opened with ``?exam=N``.
``loadStatistics`` called ``getEntryStatistics(this.examContextId || -1)``;
the ``-1`` "no exam" sentinel survives ``String(-1 || '')`` in the JS
wrapper and ``int('-1')`` in the bridge, and ``get_entry_statistics`` then
adds ``AND rs.exam_context_id = -1`` -- a filter no session matches, so
both COUNT(*) queries return 0. Opening the browser without an exam in the
URL (the dashboard's "Browse" link, or ``wimi_page.goto('entry-browser')``)
is exactly that path.

What the fix changes: ``loadStatistics`` passes ``this.examContextId``
straight through; a null id becomes the wrapper's empty string, which the
bridge already maps to "all exams", matching the list query.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

CARD_COUNT = "document.querySelectorAll('#entryGrid [data-entry-id]').length"
HEADER = (
    "JSON.stringify({"
    " total: document.getElementById('totalEntries').textContent,"
    " drafts: document.getElementById('draftCount').textContent,"
    " footer: document.getElementById('totalCount').textContent,"
    " text: (document.body.innerText.match(/\\d+ entries[^\\n]*/) || [''])[0] })"
)

COMPLETE_ENTRIES = 4
DRAFT_ENTRIES = 1


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


def _seed(db) -> None:
    """One exam, one session, four complete entries and one draft.

    A shrunken copy of the reporter's seed (the counter's queries join
    only ``question_entries`` and ``review_sessions``, so the subject
    shape is incidental). The draft is an entry saved without
    reflection/explanation, which ``create_question_entry`` records as
    ``is_draft``.
    """
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name="Walkthrough Exam", exam_description="")
    cardio = db.create_subject_node(exam.exam_name, "Cardiovascular", "System")
    hypertension = db.create_subject_node(
        exam.exam_name, "Hypertension", "Topic", parent_id=cardio.id,
    )

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=40, total_incorrect=10,
        session_name="Walkthrough session", date_encountered=date.today(),
    )
    for i in range(COMPLETE_ENTRIES):
        db.create_question_entry(
            review_session_id=session.id, user_answer="A", correct_answer="B",
            reflection=f"Reflection {i}", explanation=f"Explanation {i}",
            primary_subject_ids=[hypertension.id],
        )
    for _ in range(DRAFT_ENTRIES):
        db.create_question_entry(
            review_session_id=session.id, user_answer="C", correct_answer="D",
        )


@pytest.mark.slow
@pytest.mark.regression
def test_header_counter_matches_rendered_cards(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    _seed(wimi_session.user.db)
    expected_total = COMPLETE_ENTRIES + DRAFT_ENTRIES

    # ---- Act: open the browser with no exam in the URL (no filters)
    wimi_page.goto('entry-browser')
    cards = _poll(wimi_page, CARD_COUNT, expected_total)
    assert cards == expected_total, f'Expected {expected_total} cards, got {cards!r}'

    # ---- Assert: the header agrees with the cards, in a single evaluation
    # ``loadEntries`` runs after ``loadStatistics`` resolves, so once the
    # cards are up the header has already been written; no race remains.
    header = json.loads(wimi_page.eval_js(HEADER))
    assert header['total'] == str(expected_total), (
        f"Header shows {header['text']!r} while {cards} cards render. The header "
        "reads getEntryStatistics; before the fix it sent exam_context_id=-1 "
        "when no exam was selected, and every COUNT(*) came back 0."
    )
    assert header['drafts'] == str(DRAFT_ENTRIES), (
        f"Draft count reads {header['drafts']!r}, expected {DRAFT_ENTRIES}: "
        f"{header['text']!r}"
    )
    assert header['footer'] == str(expected_total), (
        f"Pagination footer 'of N entries' reads {header['footer']!r}"
    )
    # The reporter's own probe, so the fixed page reads the way #2 expected.
    assert header['text'].startswith(f'{expected_total} entries'), header['text']
