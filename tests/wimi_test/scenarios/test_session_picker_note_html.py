"""Regression: the session-setup remove-entries picker prints note HTML as text.

Forgejo issue #34 -- "[bug] Session setup: the remove-entries picker shows
legacy note HTML as escaped text":

    Each row of the picker shows the entry's legacy ``entry.notes`` field
    passed through ``escapeHtml``, so any note stored as HTML shows its
    tags as literal text -- the same symptom as #3 on the entry browser
    cards. [...] What should have happened: a plain-text preview (tags
    stripped, as PR #25 did for the reflection preview) or no note
    preview at all.

Why it failed: ``showEntryPicker`` in ``session_setup.js`` builds each row
with ``escapeHtml(notes.substring(0, 80))``. The legacy ``notes`` column is
rich-text HTML for every entry written by the old single-notes editor, so
``escapeHtml`` faithfully renders ``<p>`` and ``<span style=...>`` as
visible text. Truncating first compounds it: the 80-character window is
spent on markup, so the words the student wrote can be cut off entirely.

What the fix changes: the row reduces the stored HTML to plain text before
truncating and escaping -- parsed in an inert ``DOMParser`` document (no
scripts run, no images load, nothing injected into the live page), block
boundaries turned into spaces, exactly as ``EntryBrowser.htmlToPreviewText``
does for the card preview. The result is still escaped on the way into the
row template, so the rendered preview stays inert.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Nested markup, comfortably inside the row's 80-character window.
NOTES_NESTED = (
    '<p>Anchored on <strong>the wrong</strong> feature.</p>'
    '<ul><li>item</li></ul>'
)
# The opening tags alone eat 49 of the first 80 characters, so a preview
# that truncates before stripping loses the end of the sentence.
NOTES_SENTENCE = 'The tags alone fill the first eighty characters.'
NOTES_TAG_HEAVY = (
    f'<p style="margin:0"><span class="note-highlight">{NOTES_SENTENCE}</span></p>'
)

CARD = "!!document.querySelector('[data-testid=\"session-card-%d\"]')"
OPEN_PICKER = """
(() => {
  if (typeof editSession !== 'function') return false;
  editSession(%d);
  const field = document.getElementById('edit-session-total-incorrect');
  if (!field) return false;
  field.value = '1';
  field.dispatchEvent(new Event('input', {bubbles: true}));
  return true;
})()
"""
PICKER_ROW = """
(() => {
  const row = document.querySelector('.entry-picker-item[data-entry-id="%d"]');
  if (!row) return null;
  const note = row.querySelector('.entry-picker-notes');
  if (!note) return null;
  return JSON.stringify({
    text: note.textContent,
    rowText: row.textContent,
    elementChildren: note.children.length,
    markupDescendants: note.querySelectorAll('p, strong, ul, li, span').length,
  });
})()
"""


def _poll(wimi_page: WimiPage, js: str, *, timeout_ms: int = 15000):
    """Poll ``js`` until it returns something other than ``None``/``False``."""
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last:
            return last
        wimi_page.wait_for_timeout(200)
        elapsed += 200
    return last


def _seed(db) -> tuple[int, int, int, int]:
    """One exam, one session, two complete entries with legacy HTML notes."""
    exam = db.create_exam_context(exam_name='Picker Notes Exam', exam_description='')
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name='Picker topic', level_type='System',
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=2,
        session_name='Picker notes session', date_encountered=date.today(),
    )
    entries = [
        db.create_question_entry(
            review_session_id=session.id, user_answer='a', correct_answer='b',
            reflection=f'<p>r{i}</p>', explanation=f'<p>e{i}</p>',
            notes=notes, primary_subject_ids=[subject.id],
        ).id
        for i, notes in enumerate((NOTES_NESTED, NOTES_TAG_HEAVY))
    ]
    # entries_completed drives the picker: it only opens when the edited
    # incorrect count drops below the number of entries already logged.
    assert db.get_review_session(session.id).entries_completed == 2
    return exam.id, session.id, entries[0], entries[1]


@pytest.mark.slow
@pytest.mark.regression
def test_entry_picker_shows_notes_as_plain_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, session_id, nested_id, tag_heavy_id = _seed(wimi_session.user.db)

    # ---- Act: open the edit modal, then drop the incorrect count -----
    wimi_page.goto('session-setup', query={'exam_id': exam_id})
    assert _poll(wimi_page, CARD % session_id), f'Session card {session_id} never rendered'
    assert _poll(wimi_page, OPEN_PICKER % session_id), 'Edit modal never opened'
    nested = json.loads(_poll(wimi_page, PICKER_ROW % nested_id))
    tag_heavy = json.loads(_poll(wimi_page, PICKER_ROW % tag_heavy_id))

    # ---- Assert: the words survive, the markup does not --------------
    for word in ('Anchored on', 'the wrong', 'feature.', 'item'):
        assert word in nested['text'], f'Preview lost {word!r}: {nested["text"]!r}'
    # The reporter's symptom: '<' and '>' from the stored HTML shown as text.
    for row in (nested, tag_heavy):
        assert '<' not in row['text'] and '>' not in row['text'], (
            f'Picker row prints note markup as text: {row["text"]!r}. '
            'showEntryPicker escaped the stored HTML instead of stripping it.'
        )
        assert '<' not in row['rowText'], row['rowText']
        # Stripped, not rendered: nothing in the row was built from the markup.
        assert row['elementChildren'] == 0 and row['markupDescendants'] == 0, (
            f'Note markup was rendered into the picker row: {row!r}'
        )
    # Block boundaries become spaces, so the list item does not fuse onto
    # the paragraph ("feature.item").
    assert 'feature. item' in nested['text'], nested['text']
    # Stripping happens before the 80-character truncation, so a note whose
    # tags are longer than its text keeps the whole sentence.
    assert tag_heavy['text'].strip() == NOTES_SENTENCE, (
        f'Tag-heavy note truncated to {tag_heavy["text"]!r}: the 80-character '
        'window was spent on markup, so the preview cut the student\'s words.'
    )
