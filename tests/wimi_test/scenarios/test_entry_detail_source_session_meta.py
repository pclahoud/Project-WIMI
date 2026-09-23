"""Regression: entry detail never names the source or the session.

Forgejo issue #31 -- "[bug] Entry detail page never shows the source or
session name (reads source_name / session_name; the bridge emits name)":

    The meta item is empty for every entry.  ``renderEntry`` [...] reads
    ``this.context.source.source_name`` and
    ``this.context.session.session_name``, but the ``getEntryWithContext``
    slot [...] emits both under the key ``name``.  Neither key the page
    reads has ever been present, so the branch is skipped and nothing
    renders.

Why it fails today: ``get_entry_with_context``
(``src/database/domains/entries.py``) returns
``{'session': {'id', 'name', 'date', ...}, 'exam': {'name', 'description'},
'source': {'name', 'type'} | None}``.  The page reads three keys off that
payload that it has never carried:

* ``source.source_name`` -- with a source attached the meta text is set to
  ``undefined`` and the item renders the literal string "undefined";
* ``session.session_name`` -- with no source the fallback branch is falsy,
  so ``renderMetaInfo`` hides the item outright;
* ``exam.id`` (in ``loadEntryData``, same payload, same class of defect) --
  ``this.examContextId`` is parsed from the ``?exam=`` query string and then
  unconditionally overwritten with ``undefined``.  That silently disables
  Related Topics, exam-subject name resolution, and the exam-scoped Back
  and per-subject browser links.

What the fix changes: the page reads ``source.name`` / ``session.name``, the
DB layer emits the exam context id it already joins on, and the page only
overwrites ``examContextId`` when the payload actually carries one.

Decisiveness: all three assertions read committed DOM / page state after
``showContent()``, so they are decisive on every platform and timezone.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SOURCE_NAME = 'UWorld Step 1 Qbank'
SOURCED_SESSION_NAME = 'Sourced block (has a question source)'
BARE_SESSION_NAME = 'Bare block (no question source)'

# ``marker`` tells a freshly committed document apart from the one the
# previous goto() left behind; ``ready`` is showContent(), which runs after
# renderEntry() has filled the meta row.  ``examContextId`` is read off the
# page's own instance -- entry_detail.js assigns ``window.entryDetail`` in
# its DOMContentLoaded handler, in the same world as eval_js.
META_PROBE = (
    "(() => { const main = document.getElementById('main-content');"
    " const el = document.getElementById('source-name');"
    " return JSON.stringify({"
    " marker: window.__wimiDetailProbe === 1,"
    " ready: !!main && getComputedStyle(main).display !== 'none',"
    " shown: !!el && getComputedStyle(el).display !== 'none',"
    " text: el ? el.querySelector('.meta-text').textContent.trim() : null,"
    " examContextId: window.entryDetail ? window.entryDetail.examContextId : null"
    " }); })()"
)


def _wait_for_render(wimi_page: WimiPage, *, timeout_ms: int = 10000) -> dict:
    """Poll until the new document has committed and shown its content."""
    elapsed, last = 0, {}
    while elapsed < timeout_ms:
        try:
            last = json.loads(wimi_page.eval_js(META_PROBE))
        except Exception:  # context torn down mid-navigation
            last = {}
        if last.get('ready') and not last.get('marker'):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db):
    """One exam, two sessions -- one with a question source, one without."""
    exam = db.create_exam_context(exam_name='Detail Meta Exam', exam_description='')
    source = db.create_question_source(
        source_name=SOURCE_NAME, source_type='online_platform', exam_context=exam.exam_name,
    )

    cases = []
    for session_name, source_id, expected in (
        (SOURCED_SESSION_NAME, source.id, SOURCE_NAME),
        (BARE_SESSION_NAME, None, BARE_SESSION_NAME),
    ):
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=10, total_incorrect=1,
            question_source_id=source_id, session_name=session_name,
        )
        entry = db.create_question_entry(
            review_session_id=session.id, user_answer='a', correct_answer='b',
            reflection='<p>meta</p>',
        )
        cases.append((entry.id, expected))
    return exam.id, cases


@pytest.mark.slow
@pytest.mark.regression
def test_detail_meta_names_the_source_then_the_session(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, cases = _seed(wimi_session.user.db)

    for visit, (entry_id, expected) in enumerate(cases):
        # ---- Act -----------------------------------------------------
        if visit:
            # A second goto() to the same page returns before the new
            # document commits: mark the old one and wait for it to vanish.
            wimi_page.eval_js('window.__wimiDetailProbe = 1')
        # ?id= is how the entry browser links to the detail page.  No
        # ?exam= here: the payload is the page's only source for it.
        wimi_page.goto('entry-detail', query={'id': entry_id})
        meta = _wait_for_render(wimi_page)

        # ---- Assert: the source, else the session, is named ----------
        assert meta.get('ready'), (
            f'Entry {entry_id}: detail page never showed its content: {meta!r}'
        )
        assert meta.get('shown'), (
            f'Entry {entry_id} expected meta text {expected!r} but the '
            'source/session meta item is hidden. renderMetaInfo reads '
            'session.session_name; getEntryWithContext emits session.name.'
        )
        assert meta.get('text') == expected, (
            f'Entry {entry_id}: source/session meta reads {meta.get("text")!r}, '
            f'expected {expected!r}. renderMetaInfo reads source.source_name / '
            'session.session_name; getEntryWithContext emits source.name / '
            'session.name.'
        )

        # ---- Assert: the exam context id survives the payload --------
        assert meta.get('examContextId') == exam_id, (
            f'Entry {entry_id}: examContextId is {meta.get("examContextId")!r}, '
            f'expected {exam_id}. loadEntryData overwrites it with '
            'result.exam.id, a key get_entry_with_context has never emitted, '
            'which disables Related Topics and the exam-scoped nav links.'
        )
