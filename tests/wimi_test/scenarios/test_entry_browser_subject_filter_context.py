"""Regression: filtering the entry browser by a shared leaf hid scoped entries.

Forgejo issue #13 -- "Entry browser subject filter hides entries scoped to
a parent context when filtering by the leaf":

    1. Tag a question with a shared leaf subject (one that has two parents,
       e.g. DVT under both Cardiovascular and Pregnancy).
    2. Choose a parent context in the Tag context pill (say Pregnancy).
    3. In the entry browser, filter by the leaf subject (DVT).
    4. The entry disappears.

Why it failed: ``get_entries_paginated``'s subject predicate asked whether
the *chosen parent* was inside the filter scope. Filtering by the leaf
alone means it is not -- the scope is ``{DVT}`` and the mapping's
``primary_parent_id`` is Pregnancy.

What the fix changes: the browser's filter is a *finding* surface, so it
goes through ``_subject_filter_scope_sql``, which ORs an unconditional
"tagged this subject directly" clause in front of the §5.4 rollup
predicate. Decided by the owner on #13 (2026-09-14): a parent context says
which chain an entry rolls up through, it does not make the entry stop
being about DVT.

Why this needs a UI scenario: ``tests/database/test_primary_parent_context.py``
covers the predicate directly and is the faster guard, but nothing proved
the browser page reaches it with the ids the user picked -- the reported
symptom is a page reading "No entries found".

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

CARD_IDS = (
    "JSON.stringify([...document.querySelectorAll('#entryGrid [data-entry-id]')]"
    ".map(c => Number(c.dataset.entryId)).sort((x, y) => x - y))"
)
MARK = "window.__filterScenarioMark = 1"
MARK_GONE = "typeof window.__filterScenarioMark === 'undefined'"


def _poll(wimi_page: WimiPage, js: str, want, *, timeout_ms: int = 15000):
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


def _ids(*entry_ids: int) -> str:
    """The exact string ``CARD_IDS`` evaluates to for these entries."""
    return json.dumps(sorted(entry_ids), separators=(',', ':'))


def _seed(db) -> dict:
    """The issue's own repro: DVT under both Cardiovascular and Pregnancy.

    Two entries tagged DVT -- one pinned to the Pregnancy context (the one
    that used to vanish), one unpinned (the control that was always found,
    so a failure names which half broke).
    """
    db._ensure_phase2_schema()
    exam = db.create_exam_context(
        exam_name='Shared Leaf Filter Exam',
        exam_description='DVT sits under two systems',
    )
    cardio = db.create_subject_node(exam.exam_name, 'Cardiovascular', 'System')
    pregnancy = db.create_subject_node(exam.exam_name, 'Pregnancy', 'System')
    dvt = db.create_subject_node(
        exam.exam_name, 'DVT', 'Topic', parent_id=cardio.id,
    )
    db.add_edge(pregnancy.id, dvt.id, is_primary=False)
    db.conn.commit()

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=2,
        session_name='Shared leaf session', date_encountered=date.today(),
    )
    pinned = db.create_question_entry(
        review_session_id=session.id, user_answer='A', correct_answer='B',
        reflection='<p>The pregnancy one.</p>', explanation='<p>Virchow.</p>',
        primary_subject_ids=[dvt.id],
    )
    unpinned = db.create_question_entry(
        review_session_id=session.id, user_answer='C', correct_answer='D',
        reflection='<p>No context chosen.</p>', explanation='<p>Wells.</p>',
        primary_subject_ids=[dvt.id],
    )
    # What the Tag context pill writes when the student picks "Pregnancy".
    db.execute(
        "UPDATE entry_subject_mappings SET primary_parent_id = ? "
        "WHERE question_entry_id = ? AND subject_node_id = ?",
        (pregnancy.id, pinned.id, dvt.id),
    )
    db.conn.commit()

    return {
        'exam_id': exam.id, 'cardio_id': cardio.id, 'dvt_id': dvt.id,
        'pinned': pinned.id, 'unpinned': unpinned.id,
    }


@pytest.mark.slow
@pytest.mark.regression
def test_filtering_by_the_leaf_shows_entries_pinned_to_another_parent(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    seeded = _seed(wimi_session.user.db)

    # ---- Act: filter by the leaf. ?subject= is the browser's own filter
    # entry point -- parseUrlParams seeds this.filters.subjectIds from it
    # and loadEntries then sends exactly what the dropdown would.
    wimi_page.goto('entry-browser', query={
        'exam': seeded['exam_id'], 'subject': seeded['dvt_id'],
    })
    want_both = _ids(seeded['pinned'], seeded['unpinned'])
    cards = _poll(wimi_page, CARD_IDS, want_both)

    # ---- Assert ------------------------------------------------------
    assert cards == want_both, (
        f'Filtering by DVT rendered {cards!r}, expected {want_both!r}. The '
        f"missing entry ({seeded['pinned']}) is tagged DVT with its tag "
        'context pinned to Pregnancy; before #13 the predicate asked only '
        'whether Pregnancy was in the filter scope, so it vanished from the '
        'browser entirely.'
    )

    # ---- The other half: the fix must not flatten the rollup ---------
    # Filtering by Cardiovascular with descendants on still hides the entry
    # pinned to Pregnancy -- and proves the page is really filtering. If it
    # returns both, the direct-tag clause was widened to the whole
    # descendant set and §5.4 is gone.
    wimi_page.eval_js(MARK)
    wimi_page.goto('entry-browser', query={
        'exam': seeded['exam_id'], 'subject': seeded['cardio_id'],
        'include_children': 'true',
    })
    assert _poll(wimi_page, MARK_GONE, True) is True, (
        'the second navigation never committed a new document'
    )
    want_one = _ids(seeded['unpinned'])
    under_cardio = _poll(wimi_page, CARD_IDS, want_one)
    assert under_cardio == want_one, (
        f'Filtering by Cardiovascular rendered {under_cardio!r}, expected '
        f"only the unpinned entry {want_one!r}. The entry pinned to "
        'Pregnancy rolls up through Pregnancy only.'
    )
