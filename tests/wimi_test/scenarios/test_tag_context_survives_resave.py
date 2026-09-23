"""Regression: a chosen tag context must survive the *second* save.

Companion to ``test_tag_context_pill.py``, which proves the pill writes
``entry_subject_mappings.primary_parent_id`` on the first save. This one
proves the value is still there after saving again — which it was not.

The bug
-------

Two halves that were individually reasonable:

* ``update_question_entry`` replaces subject mappings wholesale
  (``DELETE ... WHERE mapping_type = 'primary'`` then re-``INSERT``).
  The insert did not carry ``primary_parent_id``, so every save reset
  the column to NULL. The mapping row survived, so nothing looked
  wrong.
* ``syncTagContextChoices`` memoises the last value it wrote per
  subject (``EntryState.primaryParentSynced``) and skips the bridge
  round-trip when the desired value matches. On the second save the
  memo still said "already synced", so nothing restored the column the
  server had just cleared.

Net effect: a deliberate "this DVT is the pregnancy one" choice
survived exactly one save and then silently became NULL. Nothing
errored, nothing logged, and the entry still rolled up — just through
the lenient NULL pass-through instead of the chosen parent, which is a
*wrong* rollup rather than a missing one.

Found by watching the bridge log during a live session: the first save
issued ``setPrimaryParentForEntry`` for both tagged subjects, the second
issued it for only the one whose pill had been changed.

Why this needs a UI scenario
----------------------------

``tests/database/test_primary_parent_context.py`` covers the SQL half
directly and is the faster guard. It cannot catch the memo: that lives
in ``question_entry.js`` and only misbehaves against a server that
drops the column. Restoring either half alone makes the symptom
disappear, so the end-to-end path needs its own test.

Loader quirk
------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` -> ``window.api`` then
deletes the source handle.
"""
from __future__ import annotations

from typing import Any

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession



def _wait_for(
    wimi_page: WimiPage,
    js_expression: str,
    *,
    timeout_ms: int = 5000,
    poll_step_ms: int = 100,
) -> Any:
    """Poll ``js_expression`` until it returns something truthy.

    Returns the last value seen rather than raising, so the caller's own
    assertion still reports what it actually found. This replaces a fixed
    ``wait_for_timeout`` that was "enough on an idle box" and a race under
    load -- the #84 shape.
    """
    elapsed = 0
    last: Any = None
    while elapsed < timeout_ms:
        last = wimi_page.eval_js(js_expression)
        if last:
            return last
        wimi_page.wait_for_timeout(poll_step_ms)
        elapsed += poll_step_ms
    return last


_SAVE_JS = """
(async () => {
    try {
        document.getElementById('user-answer').value = %(answer)s;
        document.getElementById('correct-answer').value = 'B';
        if (EntryState.reflectionEditor) {
            EntryState.reflectionEditor.setContent('Reflected.');
        }
        if (EntryState.explanationEditor) {
            EntryState.explanationEditor.setContent('Explained.');
        }
        markDirty();
        await saveEntryAsDraft(true);
        return {ok: true, entryId: EntryState.currentEntry?.id};
    } catch (e) {
        return {ok: false, error: String(e)};
    }
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_tag_context_survives_a_second_save(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Pick a non-canonical parent, save twice, assert it is still set.

    Arrange
    -------
    The same diamond as ``test_tag_context_pill``: ``A -> {B, C} -> D``,
    with B the canonical (first-added) parent of D.

    Act
    ---
    Tag D, switch its context to C, save, then save again with an edit.

    Assert
    ------
    ``primary_parent_id`` is C after BOTH saves. The first assertion is
    the existing contract; the second is the regression.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Tag Context Resave Regression",
        exam_description=(
            "primary_parent_id must survive update_question_entry's "
            "mapping replacement"
        ),
    )
    node_a = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="TCR A Root",
        level_type="System", weight_source="user_defined",
    )
    node_b = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="TCR B Branch",
        level_type="Subsystem", parent_id=node_a.id,
        weight_source="user_defined",
    )
    node_c = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="TCR C Branch",
        level_type="Subsystem", parent_id=node_a.id,
        weight_source="user_defined",
    )
    node_d = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="TCR D Multi-parent Leaf",
        level_type="Topic", parent_id=node_b.id,
        weight_source="user_defined",
    )
    # Second parent edge, so D has 2 parents and the pill renders.
    db.add_edge(node_c.id, node_d.id, is_primary=False)
    db.conn.commit()

    review_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name="TCR session",
        date_encountered=date.today(),
    )

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("entry-form", query={"session_id": review_session.id})
    # The page's init() is async, and this used to be a fixed 500 ms
    # settle because the obvious signal — ``EntryState.session`` — goes
    # truthy several bridge calls too early, so polling on it made
    # ``addSubjectChip`` fire before the form could mount a pill.
    #
    # That comment was right about the signal and wrong about the
    # conclusion. ``EntryState.isLoading`` is the proper "form ready"
    # signal it wished for: it is cleared by the last statement of
    # ``initializeEntryPage``, after ``resetFormForNewEntry()`` has
    # replaced ``EntryState.formData`` and after the footer handlers
    # bind. Tagging before that point is not merely early, it is
    # discarded — see #105, where the same 500 ms guess at this exact
    # step lost a subject in 3 of 6 measured runs.
    form_ready = _wait_for(
        wimi_page,
        "(() => { try { return typeof EntryState !== 'undefined' "
        "&& EntryState.isLoading === false; } catch (e) { return false; } })()",
        timeout_ms=20000,
    )
    assert form_ready, (
        "initializeEntryPage never finished (EntryState.isLoading stayed "
        "true). Either it threw — look for an 'Initialization Failed' "
        "toast — or one of its awaited bridge calls never resolved."
    )

    tag_result = wimi_page.eval_js(
        f"""
        (() => {{
            try {{
                addSubjectChip('primary', {{
                    id: {node_d.id},
                    name: 'TCR D Multi-parent Leaf',
                    path: 'TCR A Root > TCR B Branch > TCR D Multi-parent Leaf'
                }});
                return {{ok: true}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """
    )
    assert tag_result.get("ok"), f"addSubjectChip failed: {tag_result!r}"
    # The pill mounts after an async getEdgesForChild; poll for it (#84).
    _wait_for(
        wimi_page,
        f"!!document.querySelector("
        f"'[data-testid=\"entry-form-tag-context-pill-{node_d.id}\"]')",
    )

    # Switch the context to C, the non-canonical parent. Per
    # feedback_cdp_click_quirks.md these go through .click() in JS
    # rather than locator.click().
    wimi_page.eval_js(
        f"document.querySelector("
        f"'[data-testid=\"entry-form-tag-context-pill-{node_d.id}\"]').click()"
    )
    # Poll for the menu to open rather than sleeping (#84).
    _wait_for(
        wimi_page,
        f"!!document.querySelector("
        f"'[data-testid=\"entry-form-tag-context-menu-{node_d.id}\"]')",
    )
    pick = wimi_page.eval_js(
        f"""
        (() => {{
            const opt = document.querySelector(
                '[data-testid="entry-form-tag-context-option-{node_d.id}-{node_c.id}"]'
            );
            if (!opt) return {{ok: false, error: 'C option not found'}};
            opt.click();
            return {{ok: true}};
        }})()
        """
    )
    assert pick.get("ok"), f"Could not choose the C parent: {pick!r}"
    # The choice must reach the pill (and formData) before we save (#84).
    _wait_for(
        wimi_page,
        f"""
        (() => {{
            const v = document.querySelector(
                '[data-testid="entry-form-tag-context-pill-{node_d.id}"] '
                + '.tag-context-pill-value'
            );
            return !!v && v.textContent.trim() === 'TCR C Branch';
        }})()
        """,
    )

    first = wimi_page.eval_js(_SAVE_JS % {"answer": "'first save'"},
                              await_promise=True)
    assert first.get("ok"), f"first saveEntryAsDraft raised: {first!r}"
    entry_id = first.get("entryId")
    assert entry_id, f"no entry id after first save: {first!r}"

    def context_of() -> int | None:
        row = db.fetchone(
            "SELECT primary_parent_id FROM entry_subject_mappings "
            "WHERE question_entry_id = ? AND subject_node_id = ? "
            "AND mapping_type = 'primary'",
            (entry_id, node_d.id),
        )
        return row["primary_parent_id"] if row else None

    assert context_of() == node_c.id, (
        f"After the FIRST save, primary_parent_id should be C "
        f"({node_c.id}) but was {context_of()!r}. This is the existing "
        "tag-context-pill contract; if this fails, the pill itself is "
        "broken rather than the resave path."
    )

    # ---- The regression ----------------------------------------------
    # Edit and save again, exactly as autosave or Save-as-Draft would.
    second = wimi_page.eval_js(_SAVE_JS % {"answer": "'second save'"},
                               await_promise=True)
    assert second.get("ok"), f"second saveEntryAsDraft raised: {second!r}"

    assert context_of() == node_c.id, (
        f"primary_parent_id was lost on the SECOND save (now "
        f"{context_of()!r}, expected C={node_c.id}).\n\n"
        "Two things must both hold:\n"
        "  1. update_question_entry (src/database/domains/entries.py) "
        "carries primary_parent_id through its DELETE+INSERT of the "
        "mapping rows.\n"
        "  2. syncTagContextChoices (question_entry.js) may only skip "
        "its round-trip while (1) is true -- its "
        "EntryState.primaryParentSynced memo assumes the server kept "
        "the value.\n"
        "Restoring either one alone hides the symptom; both are needed."
    )
