"""Regression: a complete, saved entry must not reopen as "Draft - missing required fields".

Forgejo issue #32 -- "Entry form: a fully saved entry shows 'Draft - missing
required fields' in the footer when its session is reopened":

    An entry saved with "Save & Next" (database: ``is_draft = false``, session
    ``completed``) was reopened later via ``question_entry.html?session_id=<id>``.
    The footer read ``Draft - missing required fields`` even though every
    required field was populated and the stored row is not a draft.

Why it failed: ``validateForm()`` asks the rich text editors whether they hold
content, guarded on the *editor object* existing rather than on TinyMCE having
initialised (``EntryState.reflectionEditor ? !....isEmpty() : ...``).
``initRichTextEditors()`` constructs both editors synchronously so the object
is always there, but ``isEmpty()`` returns ``true`` until the ``init`` event
fires. ``populateFormWithEntry`` therefore queues the stored HTML into
``_pendingContent`` and validates against two editors that both still report
empty -- and nothing re-validates once TinyMCE flushes that queue, so the
footer kept claiming the entry was an incomplete draft (and Save & Next stayed
disabled) until the student typed something.

What the fix changes: ``RichEditor`` gained an ``onReady`` callback fired after
the ``init`` event has applied any queued content, and the entry form passes
it ``validateForm``. The verdict is recomputed once the editors can actually
answer, without marking the form dirty.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

REFLECTION = '<p>I pattern-matched on the fever and skipped the timeline.</p>'
EXPLANATION = '<p>Onset within 72h of admission makes it hospital-acquired.</p>'

# Returns null until the form has finished loading the stored entry AND both
# TinyMCE instances are live with their queued content applied -- i.e. the
# moment at which the footer has every fact it needs to be correct.
FOOTER_STATE = """
(() => {
  if (typeof EntryState === 'undefined') return null;
  const refl = EntryState.reflectionEditor, expl = EntryState.explanationEditor;
  if (!refl || !expl || !refl.isInitialized || !expl.isInitialized) return null;
  if (!refl.getContent().html.trim() || !expl.getContent().html.trim()) return null;
  const answer = document.getElementById('user-answer');
  if (!answer || !answer.value.trim()) return null;
  const indicator = document.getElementById('draft-indicator');
  const saveBtn = document.getElementById('btn-save-next');
  if (!indicator || !saveBtn) return null;
  return JSON.stringify({
    draftVisible: !indicator.classList.contains('hidden'),
    draftText: indicator.textContent.replace(/\\s+/g, ' ').trim(),
    saveText: saveBtn.textContent.trim(),
    saveDisabled: saveBtn.disabled,
    dirty: EntryState.isDirty === true,
  });
})()
"""


def _poll(wimi_page: WimiPage, js: str, *, timeout_ms: int = 20000):
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
    """One session declaring a single incorrect, holding one complete entry."""
    exam = db.create_exam_context(exam_name='Draft Footer Exam', exam_description='')
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name='Pneumonia', level_type='System',
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=1,
        session_name='Draft footer session', date_encountered=date.today(),
    )
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer='B', correct_answer='D',
        reflection=REFLECTION, explanation=EXPLANATION,
        primary_subject_ids=[subject.id],
    )
    # The premise of the bug: the stored row is not a draft.
    assert db.get_question_entry(entry.id).is_draft is False
    return session.id, entry.id


def _assert_reads_as_complete(footer: dict) -> None:
    assert footer['draftVisible'] is False, (
        f"Footer reads {footer['draftText']!r} for an entry stored with "
        f'is_draft=false and every required field populated ({footer})')
    assert footer['saveDisabled'] is False, (
        f'Save button is disabled on a complete entry ({footer})')
    assert footer['saveText'] != 'Complete required fields', (
        f"Save button reads {footer['saveText']!r} on a complete entry ({footer})")
    # Re-validating on editor-ready must not pretend the student edited anything.
    assert footer['dirty'] is False, (
        f'Merely loading an entry left the form dirty ({footer})')


@pytest.mark.slow
@pytest.mark.regression
def test_reopened_session_entry_is_not_flagged_as_draft(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    session_id, _entry_id = _seed(wimi_session.user.db)

    # ---- Act: the issue's repro -- reopen the session's entry form ----
    wimi_page.goto('entry-form', query={'session_id': session_id})
    footer = _poll(wimi_page, FOOTER_STATE)
    assert footer is not None, 'Entry form never finished loading the stored entry'

    # ---- Assert ------------------------------------------------------
    _assert_reads_as_complete(footer)


@pytest.mark.slow
@pytest.mark.regression
def test_edit_mode_entry_is_not_flagged_as_draft(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Same entry, the other load path: ?entry=N&edit=true from entry detail."""
    # ---- Arrange -----------------------------------------------------
    session_id, entry_id = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('entry-form', query={
        'session_id': session_id, 'entry': entry_id, 'edit': 'true',
    })
    footer = _poll(wimi_page, FOOTER_STATE)
    assert footer is not None, 'Entry form never finished loading the stored entry'

    # ---- Assert ------------------------------------------------------
    _assert_reads_as_complete(footer)
