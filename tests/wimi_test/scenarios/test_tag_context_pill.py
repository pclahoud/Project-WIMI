"""Regression: Tag context pill on the question entry form.

Implements the UX specified in
``docs/planning/POLYHIERARCHY_MIGRATION.md`` §7.3: when an entry is
tagged with a subject that has ≥2 parents, a "Tag context: {parent}"
pill renders below the chip. Clicking the pill opens a parent picker;
selecting a non-primary parent writes
``entry_subject_mappings.primary_parent_id`` for that mapping (the
column added by ``m005_primary_parent_id`` and gated by the §5.4
rollup semantics that the Stage 9 deep-dive selector consumes).

This scenario proves the *wiring* — that the entry form exposes the
pill, that the pill switches contexts via the canonical
``api.setPrimaryParentForEntry`` slot, and that the chosen context
lands in SQLite. The pytest-only coverage in
``tests/database/test_primary_parent_context.py`` proves the
analytics math; this scenario is the end-to-end glue.

CDP click quirk
---------------

Per ``memory/feedback_cdp_click_quirks.md``: handler-logic regressions
on inline-styled / dynamically-injected buttons (pill, menu options,
modal save) use ``.click()`` from ``eval_js`` rather than
``locator.click()`` — CDP's ``Input.dispatchMouseEvent`` can drop
events on targets whose layout was synthesised after the initial
render.

Loader quirk
------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` → ``window.api`` then
deletes the source handle.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_tag_context_pill_persists_choice_to_db(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Tag a multi-parent leaf, switch the pill, save, assert DB row.

    Arrange
    -------
    Diamond DAG (the canonical multi-parent shape from
    ``tests/database/test_primary_parent_context.py::_build_diamond``):

        A
       / \\
      B   C
       \\ /
        D    (D has two parents — B and C, both rooted in A)

    B is the canonical primary parent (added first). One review
    session with a 1-entry budget gives us an exam-context to land on.

    Act
    ---
    1. Navigate to the entry form for the session.
    2. Fill the required fields (user answer, correct answer,
       reflection, explanation) and tag the form with D via JS state
       (the typeahead has its own UX quirks orthogonal to this test;
       calling ``addSubjectChip('primary', ...)`` exercises the same
       chip render path as the typeahead).
    3. Assert the pill rendered for D.
    4. Open the pill menu and pick C (the non-primary parent).
    5. Save the draft.
    6. Assert ``entry_subject_mappings.primary_parent_id == C.id`` for
       the (entry, D) mapping.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Tag Context Pill Regression",
        exam_description=(
            "POLYHIERARCHY_MIGRATION §7.3 — pill writes "
            "entry_subject_mappings.primary_parent_id"
        ),
    )

    # Diamond — A is the root, B + C are intermediate parents, D is
    # the multi-parent leaf. Names are scenario-tagged to avoid
    # collisions if a fuzzy-search seeder ever fires beside us.
    node_a = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="TCP A Root",
        level_type="System",
        weight_source="user_defined",
    )
    node_b = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="TCP B Branch",
        level_type="Subsystem",
        parent_id=node_a.id,
        weight_source="user_defined",
    )
    node_c = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="TCP C Branch",
        level_type="Subsystem",
        parent_id=node_a.id,
        weight_source="user_defined",
    )
    node_d = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="TCP D Multi-parent Leaf",
        level_type="Topic",
        parent_id=node_b.id,  # B becomes the canonical primary edge
        weight_source="user_defined",
    )
    # Add the second parent edge (C → D) so D has 2 parents and
    # getEdgesForChild returns ≥2 rows (the pill render gate).
    db.add_edge(node_c.id, node_d.id, is_primary=False)
    db.conn.commit()

    review_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name="TCP session",
        date_encountered=date.today(),
    )

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("entry-form", query={"session_id": review_session.id})

    # Bridge surface readiness probe — both wrappers must be present.
    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getEdgesForChild === 'function' "
        "&& typeof window.api.setPrimaryParentForEntry === 'function')()"
    )
    assert api_ready, (
        "window.api.getEdgesForChild / setPrimaryParentForEntry are not "
        "exposed. Check src/web/js/api/edges.js + weights.js loaded via "
        "_loader.js."
    )

    # The page's init() is async. Give it a beat to load the session
    # + render the empty form before tagging.
    wimi_page.wait_for_timeout(500)

    # Tag the entry with D via the chip-add helper. addSubjectChip
    # writes formData.primarySubjects and re-renders chips — the same
    # path the typeahead uses on its selectSubject callback.
    tag_result = wimi_page.eval_js(
        f"""
        (() => {{
            try {{
                addSubjectChip('primary', {{
                    id: {node_d.id},
                    name: 'TCP D Multi-parent Leaf',
                    path: 'TCP A Root > TCP B Branch > TCP D Multi-parent Leaf'
                }});
                return {{ok: true}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """
    )
    assert tag_result.get("ok"), (
        f"addSubjectChip failed: {tag_result!r}. The form's primary "
        f"subject add path must accept a {{id, name, path}} shape."
    )

    # The pill render is async — it fires getEdgesForChild then mounts
    # the pill into the slot. Settle wait for the bridge round-trip.
    wimi_page.wait_for_timeout(500)

    pill_present = wimi_page.eval_js(
        f"!!document.querySelector("
        f"'[data-testid=\"entry-form-tag-context-pill-{node_d.id}\"]')"
    )
    assert pill_present, (
        f"Tag context pill did not render for subject id={node_d.id}. "
        f"Subject has 2 parents (B={node_b.id}, C={node_c.id}); pill "
        f"render gate is getEdgesForChild(...).length >= 2. Verify the "
        f"slot markup in renderSubjectChips and the mountTagContextPill "
        f"async fetch path."
    )

    # Open the menu via direct .click() — CDP click on the pill button
    # works here (it's not modal-occluded), but going through the same
    # .click() seam as the menu items keeps the scenario consistent
    # with feedback_cdp_click_quirks.md.
    wimi_page.eval_js(
        f"document.querySelector("
        f"'[data-testid=\"entry-form-tag-context-pill-{node_d.id}\"]'"
        f").click()"
    )
    wimi_page.wait_for_timeout(100)

    # Menu should be present with C as an option.
    menu_present = wimi_page.eval_js(
        f"!!document.querySelector("
        f"'[data-testid=\"entry-form-tag-context-menu-{node_d.id}\"]')"
    )
    assert menu_present, "Tag context menu did not open after pill click."

    # Pick the C parent (the non-primary edge).
    pick_result = wimi_page.eval_js(
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
    assert pick_result.get("ok"), (
        f"Could not click the C-parent option in the menu: {pick_result!r}"
    )
    wimi_page.wait_for_timeout(100)

    # The pill value should now read the C parent name (visual sanity).
    pill_value = wimi_page.eval_js(
        f"""
        (() => {{
            const v = document.querySelector(
                '[data-testid="entry-form-tag-context-pill-{node_d.id}"] '
                + '.tag-context-pill-value'
            );
            return v ? v.textContent.trim() : null;
        }})()
        """
    )
    assert pill_value == "TCP C Branch", (
        f"Pill value did not update to the chosen parent. "
        f"expected 'TCP C Branch', got {pill_value!r}."
    )

    # Fill the required fields + trigger save. The form's
    # saveEntryAsDraft path is what we need to exercise to land the
    # primary_parent_id write. Use the form's own rich editors via
    # their state hooks rather than typing through CDP (typing into
    # TinyMCE iframes from headless CDP is its own can of worms).
    fill_result: Any = wimi_page.eval_js(
        """
        (async () => {
            try {
                document.getElementById('user-answer').value = 'A';
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
        """,
        await_promise=True,
    )
    assert fill_result.get("ok"), (
        f"saveEntryAsDraft raised: {fill_result!r}."
    )
    entry_id = fill_result.get("entryId")
    assert entry_id, (
        f"saveEntryAsDraft did not assign currentEntry.id: {fill_result!r}"
    )

    # ---- Assert ------------------------------------------------------
    # The mapping for D must carry primary_parent_id = C.id (the user's
    # picked context — §5.4 override).
    row = db.fetchone(
        "SELECT primary_parent_id FROM entry_subject_mappings "
        "WHERE question_entry_id = ? AND subject_node_id = ? "
        "AND mapping_type = 'primary'",
        (entry_id, node_d.id),
    )
    assert row is not None, (
        f"entry_subject_mappings row for entry={entry_id}, "
        f"subject={node_d.id} was not created."
    )
    assert row["primary_parent_id"] == node_c.id, (
        f"primary_parent_id mismatch: expected {node_c.id} (C), "
        f"got {row['primary_parent_id']!r}. The Tag context pill's "
        f"choice did not flow through setPrimaryParentForEntry."
    )

    # ---- Phase 2: untouched pill writes canonical primary -----------
    # Policy: every multi-parent subject on an entry gets a non-NULL
    # primary_parent_id on save. If the user doesn't touch the pill,
    # the canonical primary (B in this fixture) is written. This is
    # what makes the deep-dive selector behave as a genuine filter
    # rather than a no-op (NULL is now legacy-only for new entries).
    #
    # Navigate to entry slot 2 (a fresh slot), tag the same
    # multi-parent subject D, and save WITHOUT touching the pill.
    next_slot_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                await navigateToEntry(1);  // 0-indexed → slot 2
                const subj = {{
                    id: {node_d.id},
                    name: "TCP D Leaf",
                    level_type: "Topic",
                }};
                EntryState.formData.primarySubjects.push(subj);
                renderSubjectChips();
                document.getElementById('user-answer').value = 'X';
                document.getElementById('correct-answer').value = 'Y';
                if (EntryState.reflectionEditor) {{
                    EntryState.reflectionEditor.setContent('R2');
                }}
                if (EntryState.explanationEditor) {{
                    EntryState.explanationEditor.setContent('E2');
                }}
                markDirty();
                await saveEntryAsDraft(true);
                return {{ok: true, entryId: EntryState.currentEntry?.id}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert next_slot_result.get("ok"), (
        f"Second-entry save raised: {next_slot_result!r}"
    )
    entry_id_2 = next_slot_result.get("entryId")
    assert entry_id_2 and entry_id_2 != entry_id, (
        f"Second save did not create a fresh entry. "
        f"first={entry_id}, second={entry_id_2}."
    )

    # The mapping for D on the second entry must carry
    # primary_parent_id = B.id (the canonical primary, since the user
    # didn't touch the pill).
    row2 = db.fetchone(
        "SELECT primary_parent_id FROM entry_subject_mappings "
        "WHERE question_entry_id = ? AND subject_node_id = ? "
        "AND mapping_type = 'primary'",
        (entry_id_2, node_d.id),
    )
    assert row2 is not None, (
        f"entry_subject_mappings row for entry={entry_id_2}, "
        f"subject={node_d.id} was not created on the second save."
    )
    assert row2["primary_parent_id"] == node_b.id, (
        f"Untouched-pill default policy violated: expected "
        f"primary_parent_id={node_b.id} (canonical primary B), got "
        f"{row2['primary_parent_id']!r}. syncTagContextChoices should "
        f"always write a non-NULL id for multi-parent subjects, "
        f"defaulting to the canonical primary."
    )
