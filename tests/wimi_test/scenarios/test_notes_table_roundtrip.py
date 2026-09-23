"""Regression: a table typed into a note survives reopen and renders as a table.

Forgejo issue #18 -- "Notes: a table inserted in the rich editor loses its
formatting on reopen and renders as raw HTML in the entry browser":

    A table inserted into the notes editor does not come back formatted
    when the session is reopened, and the entry browser shows the same
    note's table as raw HTML text instead of a rendered table.

Storage is not the problem: ``tests/database/test_entry_notes.py``
(``TestNoteTableMarkup``) shows ``entry_notes.content_html`` keeps the
``<table>`` verbatim through add and update. What is lost is on the way
back into the editor, and only for notes that predate the TinyMCE switch.

Why the legacy case fails today: the m001 baseline copied every Quill-era
``question_entries.notes_json`` (a Quill Delta) into
``entry_notes.content_json``. TinyMCE has no JSON twin, so the form saves
``{content_html: <new html>, content_json: null}`` and
``update_entry_note`` treats ``None`` as "skip" -- the old Delta stays next
to the new HTML. ``addNoteCard`` then prefers ``content_json``, feeds the
Delta to ``RichEditor._convertDeltaToHtml``, and the editor shows the
pre-edit text with no table. The fix makes the form load ``content_html``
first and keep the Delta as a fallback for rows with no HTML.

The detail page (the surface the entry browser opens) already renders
note bodies through ``RichContentRenderer`` -- that half is a guard.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

CELL_TEXT = 'NTR cell one'
TABLE_HTML = (
    '<p>Before the table</p>'
    '<table border="1" style="border-collapse: collapse; width: 100%;">'
    f'<tbody><tr><td>{CELL_TEXT}</td><td>NTR cell two</td></tr></tbody></table>'
    '<p>After the table</p>'
)
LEGACY_TEXT = 'NTR legacy text'
QUILL_DELTA = json.dumps({'ops': [{'insert': LEGACY_TEXT + '\n'}]})

# Every note editor on the form, once all of them have finished TinyMCE init.
EDITOR_PROBE = (
    "(() => { const eds = (typeof EntryState !== 'undefined' && EntryState.noteEditors) || [];"
    " const ready = eds.length > 0 && eds.every(ne => ne.editor && ne.editor.isInitialized);"
    " return JSON.stringify({ ready, count: eds.length,"
    " entryId: (typeof EntryState !== 'undefined' && EntryState.currentEntry) ? EntryState.currentEntry.id : null,"
    " html: ready ? eds.map(ne => ne.editor.getContent().html).join('\\n') : null }); })()"
)
# The detail page's notes tab, once showContent() has revealed the page.
DETAIL_PROBE = (
    "(() => { const main = document.getElementById('main-content');"
    " const box = document.getElementById('notes-tab-content');"
    " const table = box ? box.querySelector('table') : null;"
    " return JSON.stringify({ ready: !!main && getComputedStyle(main).display !== 'none',"
    " hasTable: !!table,"
    " cells: table ? Array.from(table.querySelectorAll('td')).map(td => td.textContent.trim()) : [],"
    " text: box ? box.textContent : null }); })()"
)


def _poll(wimi_page: WimiPage, probe: str, done, *, timeout_ms: int = 15000) -> dict:
    elapsed, last = 0, {}
    while elapsed < timeout_ms:
        try:
            last = json.loads(wimi_page.eval_js(probe))
        except Exception:  # document torn down mid-navigation
            last = {}
        if done(last):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db, *, legacy: bool) -> tuple[int, int]:
    """One exam, one session, one entry with one table-bearing note.

    ``legacy=True`` reproduces a Quill-era note after a TinyMCE edit: the
    HTML holds the table, ``content_json`` still holds the old Delta."""
    exam = db.create_exam_context(exam_name='Notes Table Exam', exam_description='')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=1,
        session_name='Notes table session', date_encountered=date.today(),
    )
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer='a', correct_answer='b',
    )
    db.add_entry_note(
        entry_id=entry.id, content_html=TABLE_HTML,
        content_json=QUILL_DELTA if legacy else None,
    )
    db.conn.commit()
    return session.id, entry.id


def _reopen_in_form(wimi_page: WimiPage, session_id: int, entry_id: int) -> dict:
    wimi_page.goto('entry-form', query={'session_id': session_id, 'entry': entry_id})
    state = _poll(wimi_page, EDITOR_PROBE,
                  lambda s: s.get('ready') and s.get('entryId') == entry_id)
    assert state.get('ready') and state.get('entryId') == entry_id, (
        f'note editor for entry {entry_id} never became ready: {state!r}'
    )
    # RichEditor re-checks (and retries) table content ~100 ms after setContent.
    wimi_page.wait_for_timeout(400)
    return json.loads(wimi_page.eval_js(EDITOR_PROBE))


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize('legacy', [False, True], ids=['fresh_note', 'quill_era_note'])
def test_note_table_reopens_in_editor(
    wimi_session: WimiTestSession, wimi_page: WimiPage, legacy: bool,
) -> None:
    # ---- Arrange -----------------------------------------------------
    session_id, entry_id = _seed(wimi_session.user.db, legacy=legacy)

    # ---- Act ---------------------------------------------------------
    state = _reopen_in_form(wimi_page, session_id, entry_id)
    html = state.get('html') or ''

    # ---- Assert: the editor shows the stored table, not older text ----
    assert '<table' in html and CELL_TEXT in html, (
        f'Reopened note editor lost the table. Stored content_html has it; '
        f'editor getContent() returned: {html!r}'
    )
    assert LEGACY_TEXT not in html, (
        'Editor rebuilt the note from the stale Quill Delta in content_json '
        f'instead of the saved HTML: {html!r}'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_note_table_renders_as_element_on_detail_page(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    _, entry_id = _seed(wimi_session.user.db, legacy=True)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('entry-detail', query={'id': entry_id})
    state = _poll(wimi_page, DETAIL_PROBE, lambda s: s.get('ready'))

    # ---- Assert: a real <table>, not escaped markup -------------------
    assert state.get('ready'), f'detail page never showed its content: {state!r}'
    assert state.get('hasTable') and CELL_TEXT in state.get('cells', []), (
        f'Detail page did not render the note table as an element: {state!r}'
    )
    assert '<table' not in (state.get('text') or ''), (
        f'Detail page shows the note table as raw HTML text: {state.get("text")!r}'
    )
