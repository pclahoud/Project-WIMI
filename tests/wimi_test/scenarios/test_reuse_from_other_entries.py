"""Regression: Attach-Existing header button + picker modal (Wave R5).

This scenario replaces the original "Reuse from other entries" section
test. The action surface was pivoted from a passive in-page section
with per-row Attach/Detach buttons to two compact header buttons
("+ Add existing") sitting beside the Notes and Media labels on the
entry form, opening a multi-select picker modal on click.

Wave R5 shipped:

- `question_entry.html`: removed `#section-reuse-from-other-entries`,
  added two `.section-header-action` buttons (notes + media) and a
  single `#attach-existing-modal` reused for both kinds.
- `question_entry.js`: removed `renderReuseFromOtherEntries`,
  `handleReuseAttach/Detach`, `scheduleReuseRender` and friends.
  Added `refreshAttachCandidates`, `updateAttachButtonState`,
  `openAttachExistingPicker`, `confirmAttachExistingSelected`,
  `refreshAfterAttach`.
- `entry.css`: removed the `#section-reuse-from-other-entries` block
  and `.reuse-*` rules. Added `.section-header-action`,
  `.attach-existing-*` blocks (theme variables only).

The backend (DB writers + bridge slots + JS API wrappers + m009
junction) is unchanged from Wave R4 and remains correct.

What this scenario locks down:

1. **Header buttons reflect candidates.** Tagging entry B with
   subject S that already owns note N + media M on entry A enables
   both header buttons with count `(1)`.
2. **Notes picker exercise.** Open picker → select N → confirm →
   modal closes, note card renders on B, notes button reverts to
   disabled (no more candidates).
3. **Media picker exercise.** Same for media M.
4. **Detail page reflects attachments.** Navigating to entry B's
   detail page shows N and M.
5. **Edit-propagation.** Editing N's content on B's edit page and
   saving propagates to A's detail page (proves many-to-many).

CDP click quirk
---------------
Per `feedback_cdp_click_quirks.md`, modal buttons inside force-visible
containers can have CDP synthetic clicks silently dropped. The modal
confirm button is therefore clicked via `eval_js(".click()")`. The
header `+ Add existing` buttons are mounted via the normal flow so a
direct `.click()` works there too — we use `eval_js` for consistency.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _wait_for(
    wimi_page: WimiPage,
    js_expression: str,
    *,
    timeout_ms: int = 3000,
    poll_step_ms: int = 100,
    description: str = "",
) -> Any:
    """Poll ``js_expression`` until truthy or ``timeout_ms`` elapses."""
    elapsed = 0
    last: Any = None
    while elapsed < timeout_ms:
        last = wimi_page.eval_js(js_expression)
        if last:
            return last
        wimi_page.wait_for_timeout(poll_step_ms)
        elapsed += poll_step_ms
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_attach_existing_header_buttons_and_picker(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Header attach buttons + picker modal end-to-end.

    Arrange
    -------
    - One exam context.
    - Subject ``S`` under that context.
    - Entry A on a single-entry seed session with one note ``N`` and
      one media row ``M`` (both linked to S).
    - A second 1-entry session B used for the interactive form drive
      (so the form lands on a fresh blank slot).
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Attach Existing Header Button Regression",
        exam_description=(
            "Wave R5 — header attach buttons + picker modal, replacing "
            "the legacy Reuse section. Backend (m009 junction + bridge "
            "attach/detach slots) unchanged from Wave R4."
        ),
    )

    subject_s = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="AEHB Subject S",
        level_type="System",
        weight_source="user_defined",
    )

    seed_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name="AEHB seed session",
        date_encountered=date.today(),
    )
    entry_a = db.create_question_entry(
        review_session_id=seed_session.id,
        user_answer="A-ua",
        correct_answer="A-ca",
        reflection="Entry A reflection",
        explanation="Entry A explanation",
        primary_subject_ids=[subject_s.id],
    )

    note_a_original = "AEHB seed note from entry A — picker-attach-able on B."
    note_a = db.add_entry_note(
        entry_id=entry_a.id,
        content_html=f"<p>{note_a_original}</p>",
        linked_subject_ids=[subject_s.id],
    )

    media_a = db.add_entry_media(
        entry_id=entry_a.id,
        file_uuid="aehb2222-bbbb-3333-cccc-444444444444",
        original_filename="aehb_seed.png",
        mime_type="image/png",
        file_size_bytes=512,
        linked_subject_ids=[subject_s.id],
    )

    interactive_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name="AEHB interactive session",
        date_encountered=date.today(),
    )
    db.conn.commit()

    # =================================================================
    # Block 1 — Header buttons enable + counts update after tagging S
    # =================================================================
    wimi_page.goto(
        "entry-form",
        query={"session_id": interactive_session.id},
    )

    # Bridge surface + new page-scope helper readiness probe.
    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.attachExistingNoteToEntry === 'function' "
        "&& typeof window.api.detachNoteFromEntry === 'function' "
        "&& typeof window.api.attachExistingMediaToEntry === 'function' "
        "&& typeof window.api.detachMediaFromEntry === 'function' "
        "&& typeof selectSubject === 'function' "
        "&& typeof refreshAttachCandidates === 'function' "
        "&& typeof openAttachExistingPicker === 'function')()"
    )
    assert api_ready, (
        "Bridge wrappers and/or the new page-scope attach-existing "
        "helpers (refreshAttachCandidates, openAttachExistingPicker) "
        "are not exposed. Check src/web/js/api/* and that "
        "question_entry.js is included by question_entry.html."
    )

    # Both header buttons must exist and start disabled (no primaries
    # tagged yet → nothing to attach).
    initial_state: Any = wimi_page.eval_js(
        """
        (() => {
            const noteBtn = document.querySelector(
                '[data-testid="entry-form-notes-attach-existing-button"]');
            const mediaBtn = document.querySelector(
                '[data-testid="entry-form-media-attach-existing-button"]');
            return {
                noteBtnPresent: !!noteBtn,
                mediaBtnPresent: !!mediaBtn,
                noteBtnDisabled: noteBtn ? noteBtn.disabled : null,
                mediaBtnDisabled: mediaBtn ? mediaBtn.disabled : null,
            };
        })()
        """
    )
    assert initial_state.get("noteBtnPresent"), (
        "Notes header attach button "
        "(data-testid=entry-form-notes-attach-existing-button) not "
        "found in DOM. Check question_entry.html Section F markup."
    )
    assert initial_state.get("mediaBtnPresent"), (
        "Media header attach button "
        "(data-testid=entry-form-media-attach-existing-button) not "
        "found in DOM. Check question_entry.html Section F markup."
    )
    assert initial_state.get("noteBtnDisabled") is True, (
        f"Notes header button should start disabled (no primary "
        f"subjects yet). state={initial_state!r}"
    )
    assert initial_state.get("mediaBtnDisabled") is True, (
        f"Media header button should start disabled (no primary "
        f"subjects yet). state={initial_state!r}"
    )

    # initializeEntryPage is async — let session populate.
    wimi_page.wait_for_timeout(500)
    session_loaded = wimi_page.eval_js(
        "(() => !!(EntryState && EntryState.session "
        "&& EntryState.session.exam_context_id))()"
    )
    assert session_loaded, (
        "EntryState.session was not populated after navigating to the "
        "entry form for the interactive session."
    )

    # Tag the interactive entry with subject S — the selectSubject
    # handler schedules refreshAttachCandidates with a 250ms debounce.
    select_result: Any = wimi_page.eval_js(
        f"""
        (() => {{
            try {{
                selectSubject(
                    {subject_s.id},
                    'AEHB Subject S',
                    'AEHB Subject S',
                    'primary'
                );
                return {{ok: true}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """
    )
    assert select_result.get("ok"), (
        f"selectSubject raised: {select_result!r}"
    )

    # Wait for the notes button to become enabled with the right count.
    notes_btn_enabled = _wait_for(
        wimi_page,
        """
        (() => {
            const btn = document.querySelector(
                '[data-testid="entry-form-notes-attach-existing-button"]');
            if (!btn || btn.disabled) return false;
            const count = document.getElementById(
                'btn-attach-existing-notes-count');
            return !!(count && !count.hidden
                      && count.textContent.includes('1'));
        })()
        """,
        timeout_ms=4000,
        description="notes attach button enabled with count (1)",
    )
    assert notes_btn_enabled, (
        "Notes header attach button never enabled with count (1) "
        "after tagging subject S. Check the scheduleRefreshAttachCandidates "
        "debounce wiring in selectSubject and that getNotesBySubjects "
        "resolved with note A."
    )

    media_btn_enabled = _wait_for(
        wimi_page,
        """
        (() => {
            const btn = document.querySelector(
                '[data-testid="entry-form-media-attach-existing-button"]');
            if (!btn || btn.disabled) return false;
            const count = document.getElementById(
                'btn-attach-existing-media-count');
            return !!(count && !count.hidden
                      && count.textContent.includes('1'));
        })()
        """,
        timeout_ms=4000,
        description="media attach button enabled with count (1)",
    )
    assert media_btn_enabled, (
        "Media header attach button never enabled with count (1) "
        "after tagging subject S. Check getMediaBySubjects resolution."
    )

    # =================================================================
    # Block 2 — Notes picker: open, select, confirm, settle
    # =================================================================
    wimi_page.eval_js(
        "document.querySelector("
        "'[data-testid=\"entry-form-notes-attach-existing-button\"]'"
        ").click()"
    )

    modal_visible = _wait_for(
        wimi_page,
        "(() => {"
        " const m = document.getElementById('attach-existing-modal');"
        " return !!(m && m.classList.contains('active'));"
        "})()",
        timeout_ms=3000,
        description="attach-existing modal becomes visible",
    )
    assert modal_visible, (
        "attach-existing-modal did not become visible after clicking "
        "the notes header attach button. Check openAttachExistingPicker "
        "calls Modal.open('attach-existing-modal')."
    )

    note_row_present = wimi_page.eval_js(
        f"!!document.querySelector("
        f"'[data-testid=\"attach-existing-item-notes-{note_a.id}\"]')"
    )
    assert note_row_present, (
        f"Note row testid=attach-existing-item-notes-{note_a.id} did "
        f"not render in the picker. Check _attachBuildNoteRow output "
        f"in renderAttachExistingList."
    )

    # Tick the checkbox.
    wimi_page.eval_js(
        f"""
        (() => {{
            const cb = document.querySelector(
                '[data-testid="attach-existing-checkbox-notes-{note_a.id}"]');
            cb.checked = true;
            cb.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()
        """
    )

    confirm_enabled = _wait_for(
        wimi_page,
        "(() => {"
        " const b = document.getElementById('btn-attach-existing-confirm');"
        " return !!(b && !b.disabled);"
        "})()",
        timeout_ms=2000,
        description="confirm button enabled after checkbox tick",
    )
    assert confirm_enabled, (
        "Confirm button did not enable after ticking a checkbox. "
        "Check updateAttachExistingConfirmButton wiring on change."
    )

    # Click confirm via eval_js per the CDP modal-click quirk.
    wimi_page.eval_js(
        "document.getElementById('btn-attach-existing-confirm').click()"
    )

    modal_closed = _wait_for(
        wimi_page,
        "(() => {"
        " const m = document.getElementById('attach-existing-modal');"
        " return !!(m && !m.classList.contains('active'));"
        "})()",
        timeout_ms=4000,
        description="attach-existing modal closes after confirm",
    )
    assert modal_closed, (
        "attach-existing-modal did not close after confirm. "
        "confirmAttachExistingSelected should Modal.close() after "
        "the bridge call resolves."
    )

    # Note should now appear in the form's note state.
    note_attached = _wait_for(
        wimi_page,
        f"(() => {{"
        f" const noteIds = (EntryState.formData.notesList || [])"
        f"   .map(n => n.id);"
        f" const editorIds = (EntryState.noteEditors || [])"
        f"   .map(n => n.id).filter(Boolean);"
        f" return noteIds.includes({note_a.id})"
        f"        || editorIds.includes({note_a.id});"
        f"}})()",
        timeout_ms=4000,
        description="note attached and rendered in form state",
    )
    assert note_attached, (
        f"After picker confirm, note {note_a.id} did not appear in "
        f"EntryState.formData.notesList or EntryState.noteEditors. "
        f"refreshAfterAttach should re-fetch via api.getEntryNotes "
        f"and addNoteCard the new note."
    )

    # Form must have a currentEntry id after attach (autosave fired).
    entry_b_id = wimi_page.eval_js(
        "EntryState.currentEntry ? EntryState.currentEntry.id : null"
    )
    assert entry_b_id, (
        "After picker confirm, EntryState.currentEntry.id was not "
        "populated. confirmAttachExistingSelected should call "
        "saveEntryAsDraft(true) before issuing attach calls when no "
        "currentEntry exists."
    )
    assert entry_b_id != entry_a.id, (
        f"Attach autosaved to entry A's id ({entry_a.id}) instead of "
        f"creating entry B. interactive_session should be a separate "
        f"review_session so a fresh slot is created."
    )

    # Notes header button should revert to disabled (no more candidates).
    notes_btn_disabled_again = _wait_for(
        wimi_page,
        """
        (() => {
            const btn = document.querySelector(
                '[data-testid="entry-form-notes-attach-existing-button"]');
            return !!(btn && btn.disabled);
        })()
        """,
        timeout_ms=3000,
        description="notes attach button disabled again post-attach",
    )
    assert notes_btn_disabled_again, (
        "Notes header attach button should be disabled after attaching "
        "the only candidate. Check scheduleRefreshAttachCandidates is "
        "called after confirmAttachExistingSelected resolves."
    )

    # =================================================================
    # Block 3 — Media picker: same drill for media M
    # =================================================================
    # Wait for media button to still be enabled (it has its own candidate).
    media_btn_still_enabled = _wait_for(
        wimi_page,
        """
        (() => {
            const btn = document.querySelector(
                '[data-testid="entry-form-media-attach-existing-button"]');
            return !!(btn && !btn.disabled);
        })()
        """,
        timeout_ms=3000,
        description="media button still enabled after notes attach",
    )
    assert media_btn_still_enabled, (
        "Media header attach button should still be enabled after the "
        "notes attach (independent candidate set)."
    )

    wimi_page.eval_js(
        "document.querySelector("
        "'[data-testid=\"entry-form-media-attach-existing-button\"]'"
        ").click()"
    )

    media_modal_visible = _wait_for(
        wimi_page,
        "(() => {"
        " const m = document.getElementById('attach-existing-modal');"
        " return !!(m && m.classList.contains('active'));"
        "})()",
        timeout_ms=3000,
        description="modal re-opens for media picker",
    )
    assert media_modal_visible, (
        "Modal did not re-open for media kind."
    )

    media_row_present = wimi_page.eval_js(
        f"!!document.querySelector("
        f"'[data-testid=\"attach-existing-item-media-{media_a.id}\"]')"
    )
    assert media_row_present, (
        f"Media row testid=attach-existing-item-media-{media_a.id} "
        f"did not render in the picker."
    )

    wimi_page.eval_js(
        f"""
        (() => {{
            const cb = document.querySelector(
                '[data-testid="attach-existing-checkbox-media-{media_a.id}"]');
            cb.checked = true;
            cb.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()
        """
    )
    wimi_page.eval_js(
        "document.getElementById('btn-attach-existing-confirm').click()"
    )

    media_attached = _wait_for(
        wimi_page,
        f"(() => {{"
        f" const ids = (EntryState.formData.media || [])"
        f"   .map(m => m.id);"
        f" return ids.includes({media_a.id});"
        f"}})()",
        timeout_ms=4000,
        description="media attached and reflected in form state",
    )
    assert media_attached, (
        f"After picker confirm, media {media_a.id} did not appear in "
        f"EntryState.formData.media. refreshAfterAttach should reload "
        f"via mediaUpload.loadMedia or api.getQuestionMedia."
    )

    # =================================================================
    # Block 4 — Detail page reflects both attachments
    # =================================================================
    wimi_page.goto("entry-detail", query={"id": entry_b_id})
    wimi_page.wait_for_timeout(800)

    detail_state: Any = wimi_page.eval_js(
        """
        (() => {
            const grid = document.getElementById('attachments-grid');
            const notesTab = document.getElementById('notes-tab-content');
            return {
                attachmentCount: grid ? grid.children.length : 0,
                notesText: notesTab ? notesTab.textContent : '',
            };
        })()
        """
    )
    assert detail_state.get("attachmentCount", 0) >= 1, (
        f"Entry B detail page showed "
        f"{detail_state.get('attachmentCount')} attachments — "
        f"expected ≥1 (media A should surface via the entry_media "
        f"mapping). detail_state={detail_state!r}"
    )
    notes_text = detail_state.get("notesText") or ""
    assert note_a_original in notes_text, (
        f"Entry B detail page notes tab did not render note A. The "
        f"entry_note_attachments junction (m009) should surface "
        f"note {note_a.id} on entry {entry_b_id}. "
        f"notes_text={notes_text!r}"
    )

    # =================================================================
    # Block 5 — Edit propagation across attached entries
    # =================================================================
    wimi_page.goto(
        "entry-form",
        query={
            "session": interactive_session.id,
            "entry": entry_b_id,
            "edit": "true",
        },
    )

    note_editor_ready = _wait_for(
        wimi_page,
        f"(() => {{"
        f" return (EntryState.noteEditors || [])"
        f"   .some(ne => ne.id === {note_a.id});"
        f"}})()",
        timeout_ms=5000,
        description="note editor for attached note appears on re-edit",
    )
    assert note_editor_ready, (
        f"On re-entering entry B's edit page, noteEditors did not "
        f"contain note {note_a.id}. populateFormWithEntry / addNoteCard "
        f"should mount a card for every attached note returned by "
        f"get_entry_notes (m009 read path)."
    )

    edited_content = "EDITED note content — should propagate to entry A."
    edit_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const ne = (EntryState.noteEditors || [])
                    .find(n => n.id === {note_a.id});
                if (!ne) return {{ok: false, error: 'noteEditor not found'}};
                if (!ne.editor) return {{ok: false, error: 'editor missing'}};
                ne.editor.setContent('<p>{edited_content}</p>');
                markDirty();
                await saveEntryAsDraft(true);
                return {{ok: true}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert edit_result.get("ok"), (
        f"Editing the attached note + saveEntryAsDraft raised: "
        f"{edit_result!r}"
    )

    wimi_page.goto("entry-detail", query={"id": entry_a.id})
    wimi_page.wait_for_timeout(800)

    a_notes_text = wimi_page.eval_js(
        "(() => {"
        " const t = document.getElementById('notes-tab-content');"
        " return t ? t.textContent : '';"
        "})()"
    )
    assert edited_content in (a_notes_text or ""), (
        f"Edit did NOT propagate to entry A. Expected to see "
        f"{edited_content!r} on entry A's notes tab, got: "
        f"{(a_notes_text or '')[:300]!r}. The many-to-many should "
        f"point both A and B at the same entry_notes row."
    )
