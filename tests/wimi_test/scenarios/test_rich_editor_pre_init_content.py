"""Regression: a RichEditor answers with its queued content before TinyMCE inits.

Forgejo issue #47. ``test_reuse_from_other_entries`` failed roughly one run
in four with entry A's notes tab reading "No notes in this category" -- not
stale text, an *empty* note. Instrumenting a failing run showed why:

    edit_result before: isInitialized=False,
                        pending='<p>AEHB seed note from entry A ...</p>'
    collectedLen: 0
    entry_notes row: (1, '', None)          <- blanked in the database
    attachments:     [(1, 1), (2, 1)]       <- both entries still attached

``addNoteCard`` mounts a note card and calls ``editor.setContent(...)``,
which queues into ``_pendingContent`` because TinyMCE's ``init`` has not
fired yet. ``getContent()`` used to answer ``{html: ''}`` for the whole of
that window, and ``collectFormData()`` treats ``getContent()`` as the truth
-- so a save landing in the window wrote ``content_html = ''`` over a note
that had content. Because notes are many-to-many (m009), that blanked the
row for every entry sharing it. ``entry_detail``'s ``showNoteTab`` skips
notes with empty ``content_html``, which is the "No notes in this category"
the scenario saw.

The fix makes the editor honest during the window: ``getContent()`` and
``isEmpty()`` answer from the queued content instead of pretending the
editor is empty. Same defect class as #32 (state derived from an editor
that has not initialised), and it also fixes ``applyAutofillData``, whose
``isEmpty()`` guard would previously overwrite queued content.

Timing this through the entry form is inherently racy, so this scenario
drives ``RichEditor`` directly: everything between ``new RichEditor(...)``
and the probe is synchronous, so the pre-init window is entered
deterministically on every run.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

QUEUED_HTML = '<p>Queued before TinyMCE was ready.</p>'

# One synchronous block: construct three editors, feed them, and read them
# back without ever yielding to the event loop, so ``init`` cannot have
# fired for any of them. ``probe`` records what a caller like
# ``collectFormData()`` would see at that instant.
PRE_INIT_PROBE = """
(() => {
    const mk = (id) => {
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
        return el;
    };
    const probe = (ed) => ({
        initialized: !!ed.isInitialized,
        html: (ed.getContent() || {}).html,
        empty: ed.isEmpty(),
    });

    const withContent = new RichEditor(mk('re47-with-content'), {});
    withContent.setContent('%(queued)s');

    const untouched = new RichEditor(mk('re47-untouched'), {});

    const cleared = new RichEditor(mk('re47-cleared'), {});
    cleared.setContent('%(queued)s');
    cleared.clear();

    const viaOption = new RichEditor(mk('re47-initial-option'), {
        initialContent: '%(queued)s',
    });

    window.__re47 = [withContent, untouched, cleared, viaOption];
    return JSON.stringify({
        withContent: probe(withContent),
        untouched: probe(untouched),
        cleared: probe(cleared),
        viaOption: probe(viaOption),
    });
})()
""" % {'queued': QUEUED_HTML}

CLEANUP = (
    "(() => { (window.__re47 || []).forEach(ed => { try { ed.destroy(); }"
    " catch (e) {} }); window.__re47 = null; return true; })()"
)


def _seed(db) -> int:
    """One exam holding one session, enough for the entry form to load."""
    exam = db.create_exam_context(
        exam_name='RichEditor Pre-Init Exam', exam_description='',
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='Pre-init session', date_encountered=date.today(),
    )
    db.conn.commit()
    return session.id


@pytest.mark.slow
@pytest.mark.regression
def test_pre_init_editor_reports_queued_content_not_empty(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange: any page that loads rich_editor.js + TinyMCE --------
    session_id = _seed(wimi_session.user.db)
    wimi_page.goto('entry-form', query={'session_id': session_id})

    ready = None
    for _ in range(100):
        ready = wimi_page.eval_js("typeof window.RichEditor === 'function'")
        if ready:
            break
        wimi_page.wait_for_timeout(100)
    assert ready, 'RichEditor was never exposed on the entry form page'

    # ---- Act ----------------------------------------------------------
    state = json.loads(wimi_page.eval_js(PRE_INIT_PROBE))
    try:
        # ---- Assert: the window really is the pre-init one ------------
        for name, probe in state.items():
            assert probe['initialized'] is False, (
                f'{name} had already initialised, so this run never entered '
                f'the pre-init window and proves nothing: {state!r}'
            )

        # A save landing here must see the content, not a blank (#47).
        assert state['withContent']['html'] == QUEUED_HTML, (
            'Editor reported empty content while a setContent() was still '
            f'queued -- a save here blanks the row: {state!r}'
        )
        assert state['withContent']['empty'] is False, (
            f'isEmpty() called a queued-content editor empty: {state!r}'
        )
        assert state['viaOption']['html'] == QUEUED_HTML, (
            f'initialContent was not reported before init: {state!r}'
        )
        assert state['viaOption']['empty'] is False, (
            f'isEmpty() called an initialContent editor empty: {state!r}'
        )

        # ...and an editor that genuinely holds nothing still reads empty,
        # so a real "the user emptied this" save is not turned into a
        # no-op rewrite.
        assert state['untouched']['html'] == '', (
            f'Editor with no queued content invented some: {state!r}'
        )
        assert state['untouched']['empty'] is True, (
            f'Editor with no queued content did not read empty: {state!r}'
        )
        assert state['cleared']['html'] == '', (
            f'clear() before init did not take effect: {state!r}'
        )
        assert state['cleared']['empty'] is True, (
            f'clear() before init left the editor reading non-empty: {state!r}'
        )
    finally:
        wimi_page.eval_js(CLEANUP)
