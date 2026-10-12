"""Regression: the deep dive's Recent Entries rows render stored values as text (#525).

``renderRecentEntries`` built each row with ``innerHTML`` and interpolated
``entry.subject_name`` and the reflection (or explanation) unescaped. A subject
name is plain text a student types or imports, so ``<img onerror=...>`` in one
became an element whose handler ran when the deep dive opened -- #324's class,
on another page. The reflection is stored rich-text HTML, and the panel now
shows it the way the entry browser's card does: reduced to its words by
``WimiTextPreview.htmlToPreviewText`` (an inert DOMParser parse) and set as
text.

Seeded through the database, not typed, because the subject importer and a
profile import can deliver a name or a reflection that never passed through
the tree editor or TinyMCE -- which is the path this guards.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

NAME_PAYLOAD = 'Cardio <img src=x onerror="window.__rec_name=1">'
NOTE_PAYLOAD = ('<p>Beta blockers <b>first</b>.</p>'
                '<img src=x onerror="window.__rec_note=1">')

ROW = """
(() => {
  const row = document.querySelector('[data-testid^="deep-dive-recent-entry-"]');
  if (!row) return null;
  const q = sel => row.querySelector(sel);
  return JSON.stringify({
    name_fired: window.__rec_name === 1,
    note_fired: window.__rec_note === 1,
    imgs: row.querySelectorAll('img').length,
    elements_in_subject: q('.recent-entry-subject').children.length,
    subject: q('.recent-entry-subject').textContent,
    note: q('.recent-entry-note').textContent,
  });
})()
"""


def _seed(db) -> tuple[int, int]:
    exam = db.create_exam_context(exam_name='Recent Exam', exam_description='#525')
    subject = db.create_subject_node(exam.exam_name, NAME_PAYLOAD, 'System')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='Recent session', date_encountered=date.today())
    db.create_question_entry(session.id, 'a', 'b', reflection=NOTE_PAYLOAD,
                             primary_subject_ids=[subject.id])
    db.conn.commit()
    return subject.id, exam.id


@pytest.mark.slow
@pytest.mark.regression
def test_recent_entry_values_are_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    subject_id, exam_id = _seed(wimi_session.user.db)

    wimi_page.goto('subject-deep-dive', query={'subject': subject_id, 'exam': exam_id})
    assert poll(wimi_page, '(%s) !== null' % ROW.strip(), timeout_ms=20000), (
        'the Recent Entries panel never drew its row')
    wimi_page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    state = json.loads(wimi_page.eval_js(ROW))

    assert not state['name_fired'], 'the subject name executed as markup (#525)'
    assert not state['note_fired'], 'the reflection executed as markup (#525)'
    assert state['imgs'] == 0, state
    # The other half: the student's text is shown, not mangled or dropped.
    assert state['subject'] == NAME_PAYLOAD, state
    assert state['elements_in_subject'] == 0, state
    assert state['note'] == 'Beta blockers first.', (
        f'the reflection should read as its words, as on the entry browser '
        f'card: {state["note"]!r}')
