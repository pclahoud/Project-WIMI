"""Regression: the tag-context pill must not default to a deleted parent.

Issue #57. ``EdgesMixin.get_edges_for_child`` joined ``subject_nodes``
with no ``status`` filter, so an edge into a soft-deleted parent came back
like any other — the same defect #15 fixed on ``get_parents``.

The query orders ``is_primary DESC, parent_id ASC``, and
``mountTagContextPill`` in ``src/web/js/question_entry.js`` takes
``cached[0].parent_id`` as the **default** parent context. Per CLAUDE.md
every multi-parent subject gets a non-NULL ``primary_parent_id`` on save,
defaulting to exactly that first edge. So an archived parent at the head
of the list silently pinned a **new** entry to a deleted parent: per §5.4
the entry then rolls up through a chain that is in no scope set, counting
nowhere on every analytics surface while still appearing in the entry
browser.

That consequence is what this scenario pins, and it is the half a status
filter alone could pass without — a naive unit test on the query would go
green while the pill still wrote the archived id. The query-level
assertions live in ``tests/database/test_edges_status_filter.py``.

Fixture shape (the legacy pre-#15 state, reconstructed by flipping
``status`` by hand — since #15 a real delete also removes the dangling
edge, so this shape can no longer be created by the delete path):

::

        Barch     Ckeep   Ekeep      Barch is archived and holds the
            \\       |     /          ``is_primary`` edge, so it led the
             \\      |    /           list and became the pill's default.
                 Dleaf                After the fix the default is Ckeep.

Loader quirk: probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases the latter to the former and deletes the source
handle.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _wait_for_entry_form_ready(wimi_page: WimiPage) -> None:
    """Block until ``initializeEntryPage`` has finished.

    ``EntryState.isLoading`` starts ``true`` and is cleared on the last
    line of init. Polling the DOM instead is a trap: ``#user-answer`` is
    static markup present from the first paint, so a chip added on that
    signal is wiped a moment later by init's own ``resetFormForNewEntry``
    → ``renderSubjectChips``, and the failure reads as "the pill never
    rendered" rather than "the chip was removed".
    """
    for _ in range(60):
        if wimi_page.eval_js(
            "(() => typeof EntryState !== 'undefined' "
            "&& EntryState.isLoading === false)()"
        ):
            return
        wimi_page.wait_for_timeout(250)
    raise AssertionError("entry form never finished initialising")


@pytest.mark.slow
@pytest.mark.regression
def test_untouched_pill_defaults_to_the_surviving_parent(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Save without touching the pill; the archived parent must not win."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Archived Parent Pill Regression",
        exam_description="Issue #57 — get_edges_for_child status filter",
    )

    def _subject(name: str, parent_id=None):
        return db.create_subject_node_with_weight(
            exam_context=exam.exam_name,
            name=name,
            level_type="Topic",
            parent_id=parent_id,
            weight_source="user_defined",
        )

    barch = _subject("APP Barch Deleted Parent")
    ckeep = _subject("APP Ckeep Surviving Parent")
    ekeep = _subject("APP Ekeep Other Parent")
    dleaf = _subject("APP Dleaf Multi-parent Leaf", parent_id=barch.id)
    db.add_edge(ckeep.id, dleaf.id, is_primary=False)
    db.add_edge(ekeep.id, dleaf.id, is_primary=False)
    # Archive the primary parent directly — see the module docstring for
    # why this cannot go through delete_subject_subtree any more.
    db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?",
        (barch.id,),
    )
    db.conn.commit()

    review_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name="APP session",
        date_encountered=date.today(),
    )

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("entry-form", query={"session_id": review_session.id})
    assert wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getEdgesForChild === 'function')()"
    ), "window.api.getEdgesForChild is not exposed (src/web/js/api/weights.js)."

    # init() is async and ends by clearing EntryState.isLoading. Waiting
    # on a DOM node is not enough — the static markup is there from the
    # first paint, and init's own resetFormForNewEntry re-renders the
    # chips, wiping a chip added too early.
    _wait_for_entry_form_ready(wimi_page)

    saved: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                addSubjectChip('primary', {{
                    id: {dleaf.id},
                    name: 'APP Dleaf Multi-parent Leaf',
                    level_type: 'Topic'
                }});
                // Let mountTagContextPill's getEdgesForChild round-trip
                // land before reading the rendered default.
                for (let i = 0; i < 40; i++) {{
                    if (EntryState.subjectParentEdges[{dleaf.id}]) break;
                    await new Promise(r => setTimeout(r, 50));
                }}
                // The cache assignment and the re-mount it triggers are
                // separate ticks; let the re-mount land before reading.
                await new Promise(r => setTimeout(r, 100));
                const slot = document.querySelector(
                    '.tag-context-pill-slot[data-subject-id="{dleaf.id}"]');
                const value = slot
                    ? slot.querySelector('.tag-context-pill-value')
                    : null;
                document.getElementById('user-answer').value = 'A';
                document.getElementById('correct-answer').value = 'B';
                if (EntryState.reflectionEditor) {{
                    EntryState.reflectionEditor.setContent('Reflected.');
                }}
                if (EntryState.explanationEditor) {{
                    EntryState.explanationEditor.setContent('Explained.');
                }}
                markDirty();
                await saveEntryAsDraft(true);
                return {{
                    ok: true,
                    entryId: EntryState.currentEntry?.id,
                    parentIds: (EntryState.subjectParentEdges[{dleaf.id}] || [])
                        .map(e => e.parent_id),
                    pillValue: value ? value.textContent.trim() : null,
                }};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert saved.get("ok"), f"entry-form save path raised: {saved!r}"

    # ---- Assert ------------------------------------------------------
    # 1. The archived parent is not even offered as a choice.
    assert barch.id not in saved["parentIds"], (
        f"getEdgesForChild still returns the archived parent "
        f"{barch.id}: {saved['parentIds']!r}."
    )
    assert saved["parentIds"] == [ckeep.id, ekeep.id], (
        f"Surviving edges or their order changed: {saved['parentIds']!r}, "
        f"expected [{ckeep.id}, {ekeep.id}] (is_primary DESC, parent_id ASC)."
    )

    # 2. The rendered default is the first survivor, not the dead parent.
    assert saved["pillValue"] == "APP Ckeep Surviving Parent", (
        f"Pill defaulted to {saved['pillValue']!r}. mountTagContextPill "
        f"takes cached[0].parent_id, so a leading archived edge shows the "
        f"deleted parent as the entry's context."
    )

    # 3. The consequence that matters: what actually landed in SQLite.
    #    Before the fix this row carried the archived parent's id, which
    #    makes the entry roll up nowhere under §5.4 while still listing in
    #    the entry browser — the silent mis-scoping #15 exists to close,
    #    arriving through a different door.
    entry_id = saved.get("entryId")
    assert entry_id, f"saveEntryAsDraft did not assign an entry id: {saved!r}"
    row = db.fetchone(
        "SELECT primary_parent_id FROM entry_subject_mappings "
        "WHERE question_entry_id = ? AND subject_node_id = ? "
        "AND mapping_type = 'primary'",
        (entry_id, dleaf.id),
    )
    assert row is not None, (
        f"No entry_subject_mappings row for entry={entry_id}, "
        f"subject={dleaf.id}."
    )
    assert row["primary_parent_id"] == ckeep.id, (
        f"primary_parent_id is {row['primary_parent_id']!r}; expected "
        f"{ckeep.id} (Ckeep). The untouched pill wrote the archived "
        f"parent {barch.id} — issue #57's silent data-loss mode."
    )


@pytest.mark.slow
@pytest.mark.regression
def test_a_subject_whose_parents_are_all_archived_does_not_break_the_form(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """#57's acceptance 3, at the surface that consumes the empty list.

    With every parent archived ``get_edges_for_child`` returns ``[]``, the
    pill's ``cached.length < 2`` gate clears the slot, and
    ``syncTagContextChoices`` skips the subject — the chip must still
    render and the entry must still save (with a NULL context, which §5.4
    reads as "roll up through every ancestor").
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="All Parents Archived Regression",
        exam_description="Issue #57 — empty edge list must not break the pill",
    )
    dead_a = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="APA Dead A",
        level_type="Topic", weight_source="user_defined",
    )
    dead_b = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="APA Dead B",
        level_type="Topic", weight_source="user_defined",
    )
    orphan = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="APA Stranded Leaf",
        level_type="Topic", parent_id=dead_a.id, weight_source="user_defined",
    )
    db.add_edge(dead_b.id, orphan.id, is_primary=False)
    db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id IN (?, ?)",
        (dead_a.id, dead_b.id),
    )
    db.conn.commit()

    review_session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name="APA session", date_encountered=date.today(),
    )

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("entry-form", query={"session_id": review_session.id})
    _wait_for_entry_form_ready(wimi_page)

    saved: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                addSubjectChip('primary', {{
                    id: {orphan.id},
                    name: 'APA Stranded Leaf',
                    level_type: 'Topic'
                }});
                for (let i = 0; i < 40; i++) {{
                    if (EntryState.subjectParentEdges[{orphan.id}]) break;
                    await new Promise(r => setTimeout(r, 50));
                }}
                await new Promise(r => setTimeout(r, 100));
                // Read the rendered state before saving — the save path
                // re-renders, and this assertion is about what the pill
                // did with an empty edge list, not what survives a save.
                const slot = document.querySelector(
                    '.tag-context-pill-slot[data-subject-id="{orphan.id}"]');
                const chipPresent = !!slot;
                const pillPresent = !!(slot
                    && slot.querySelector('.tag-context-pill'));
                document.getElementById('user-answer').value = 'A';
                document.getElementById('correct-answer').value = 'B';
                if (EntryState.reflectionEditor) {{
                    EntryState.reflectionEditor.setContent('Reflected.');
                }}
                if (EntryState.explanationEditor) {{
                    EntryState.explanationEditor.setContent('Explained.');
                }}
                markDirty();
                await saveEntryAsDraft(true);
                return {{
                    ok: true,
                    entryId: EntryState.currentEntry?.id,
                    edges: EntryState.subjectParentEdges[{orphan.id}],
                    chipPresent: chipPresent,
                    pillPresent: pillPresent,
                }};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )

    # ---- Assert ------------------------------------------------------
    assert saved.get("ok"), f"entry-form save path raised: {saved!r}"
    assert saved["edges"] == [], (
        f"Expected no parent edges for a subject whose parents are all "
        f"archived; got {saved['edges']!r}."
    )
    assert saved["chipPresent"], "The subject chip did not render."
    assert not saved["pillPresent"], (
        "A tag-context pill rendered for a parentless subject; the "
        "cached.length < 2 gate should have cleared the slot."
    )
    entry_id = saved.get("entryId")
    assert entry_id, f"saveEntryAsDraft did not assign an entry id: {saved!r}"
    row = db.fetchone(
        "SELECT primary_parent_id FROM entry_subject_mappings "
        "WHERE question_entry_id = ? AND subject_node_id = ?",
        (entry_id, orphan.id),
    )
    assert row is not None, "The entry saved without its subject mapping."
    assert row["primary_parent_id"] is None, (
        f"primary_parent_id is {row['primary_parent_id']!r}; a subject with "
        f"no selectable parent must stay in §5.4's NULL branch."
    )
