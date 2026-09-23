"""Regression: Add Child must suggest a level from ``level_type``, not depth.

Forgejo issue #82 — "[bug] Tree editor's Add Child modal defaults the new
subject's level by depth, not by the parent's level_type". Split out of
#49 because this is the fifth site and the only one on a **write** path:
it decides what ``subject_nodes.level_type`` actually gets stored.

From the report::

    const parentLevel = getNodeLevel(parentNode);        // depth: walks node._parent
    if (TreeState.hierarchyLevels[parentLevel]) {
        levelSelect.value = TreeState.hierarchyLevels[parentLevel].level_name;
    }

    Parent ``Cardiovascular`` at depth 2 but stored ``level_type='System'``
    -> pre-selects ``hierarchyLevels[2]`` = **Topic**, skipping Subsystem.

Most users accept the pre-filled default, so the wrong name is what lands
in the database. That is why these assertions read ``subject_nodes`` after
saving rather than stopping at the dropdown's displayed value.

The two cases, per the decision recorded in issue comment #1065
-------------------------------------------------------------

1. **Known vocabulary.** The suggestion is one step below the parent's
   *stored* level, so a ``System`` sitting at depth 2 suggests
   ``Subsystem`` — never the depth-derived ``Topic``.
2. **Unknown vocabulary — option (d).** An imported outline brings its own
   level names (the in-app SAT example uses Section / Domain / Skill), so a
   parent stored as ``Domain`` gets ``Domain`` *appended to the dropdown*
   and pre-selected: there is no derivable "one below Domain", and
   repeating it keeps the student's own word. The appended option is for
   that modal instance only — it must not be written into
   ``hierarchy_level_definitions``.

Because the suggestion now reads a per-node column, it is also immune to
the polyhierarchy ambiguity ``getNodeLevel`` inherits: ``buildFlatNodeMap``
sets ``_parent`` "to the parent of whichever appearance was visited last
and is best-effort", so the pre-fix suggestion for a multi-parent parent
depended on flat-map traversal order. The first test seeds exactly that.

Markers / fixtures: ``@pytest.mark.slow`` + ``@pytest.mark.regression``;
``wimi_session`` + ``wimi_page``, seeding through ``wimi_session.user.db``.
"""

from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _wait_for(page: WimiPage, js: str, *, timeout_ms: int = 8000) -> Any:
    """Poll ``js`` until truthy; return the last value seen either way.

    Returning rather than raising leaves the caller's own assertion to
    report what it actually found (#84 shape).
    """
    elapsed = 0
    last: Any = None
    while elapsed < timeout_ms:
        last = page.eval_js(js)
        if last:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _open_add_child(page: WimiPage, parent_id: int) -> None:
    """Expand the tree and click the parent row's "+" button."""
    _wait_for(page, "(() => !!document.querySelector('.tree-node'))()")
    page.eval_js("expandAll()")
    page.locator(testid=f"tree-node-add-child-{parent_id}").click()
    _wait_for(
        page,
        "(() => document.getElementById('node-modal')"
        ".classList.contains('active'))()",
    )


def _save_child(page: WimiPage, name: str) -> None:
    page.locator(testid="tree-node-modal-name-input").fill(name)
    page.locator(testid="tree-node-modal-save").click()


def _stored_level(
    page: WimiPage, db: Any, name: str, *, timeout_ms: int = 8000
) -> str | None:
    """Poll ``subject_nodes`` for the row the modal just wrote.

    The save is a bridge round-trip and the modal closes optimistically,
    so no DOM predicate proves the INSERT committed — the row itself is
    the signal. ``page.wait_for_timeout`` is the sanctioned step wait.
    """
    elapsed = 0
    while elapsed < timeout_ms:
        row = db.fetchone(
            "SELECT level_type FROM subject_nodes WHERE name = ?", (name,)
        )
        if row:
            return row["level_type"]
        page.wait_for_timeout(100)
        elapsed += 100
    return None


@pytest.mark.slow
@pytest.mark.regression
def test_add_child_suggests_one_below_the_parents_stored_level(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """A ``System`` at depth 2 must suggest (and store) ``Subsystem``."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 82 Level Suggestion",
        exam_description="Regression scenario for Forgejo issue #82",
    )

    def node(name: str, level_type: str, parent_id: int | None = None) -> int:
        return db.create_subject_node(
            exam_context=exam.exam_name,
            name=name,
            level_type=level_type,
            parent_id=parent_id,
        ).id

    foundations = node("I82 Foundations", "System")
    # Stored 'System' but sitting at depth 2, where the default level
    # definitions say 'Subsystem'. Depth and level_type disagree, which
    # is the whole point.
    cardio = node("I82 Cardiovascular", "System", foundations)
    # A second parent at a different depth: pre-fix the suggestion
    # depended on which appearance buildFlatNodeMap visited last.
    renal = node("I82 Renal", "System")
    db.add_edge(renal, cardio)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    _open_add_child(wimi_page, cardio)
    suggested = wimi_page.eval_js(
        "document.getElementById('modal-node-level').value"
    )
    _save_child(wimi_page, "I82 Coronary Circulation")
    stored = _stored_level(wimi_page, db, "I82 Coronary Circulation")

    # ---- Assert ------------------------------------------------------
    assert suggested == "Subsystem", (
        f"Add Child pre-selected {suggested!r} under a parent whose stored "
        "level_type is 'System'. 'Topic' means the modal is still counting "
        "tree depth (the parent renders at depth 2 under Foundations); the "
        "suggestion must come from the parent's own level_type (#82)."
    )
    assert stored == "Subsystem", (
        f"subject_nodes.level_type for the new child is {stored!r}. This is "
        "a write path — the dropdown's displayed value is only half of it, "
        "and most users accept the pre-filled default."
    )


@pytest.mark.slow
@pytest.mark.regression
def test_a_level_name_outside_the_configured_list_survives(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Option (d): append the unknown level and default the child to it."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 82 Imported Vocabulary",
        exam_description="Regression scenario for Forgejo issue #82",
    )
    # 'Domain' is from the in-app SAT example (Section / Domain / Skill)
    # and is not one of System/Subsystem/Topic/Subtopic/Child.
    domain = db.create_subject_node(
        exam_context=exam.exam_name,
        name="I82 Reading and Writing",
        level_type="Domain",
    ).id

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    _open_add_child(wimi_page, domain)
    modal = wimi_page.eval_js(
        """
        (() => {
            const sel = document.getElementById('modal-node-level');
            return {
                value: sel.value,
                options: Array.from(sel.options).map(o => o.value),
            };
        })()
        """
    )
    _save_child(wimi_page, "I82 Craft and Structure")
    stored = _stored_level(wimi_page, db, "I82 Craft and Structure")
    persisted = [
        l.level_name for l in db.get_hierarchy_levels(exam.id)
    ]

    # ---- Assert ------------------------------------------------------
    assert "Domain" in modal["options"], (
        f"Level Type options are {modal['options']!r}. The parent already "
        "carries 'Domain', so the dropdown must offer it — every other "
        "option silently substitutes the app's vocabulary for the user's "
        "(issue #82, decision comment #1065)."
    )
    assert modal["value"] == "Domain", (
        f"Add Child pre-selected {modal['value']!r} under a parent stored as "
        "'Domain'. There is no derivable 'one below Domain', so repeating "
        "the parent's own level is the honest default."
    )
    assert stored == "Domain", (
        f"subject_nodes.level_type for the new child is {stored!r}; pre-fix "
        "an unknown parent level fell through to the literal 'System'."
    )
    assert persisted == ["System", "Subsystem", "Topic", "Subtopic", "Child"], (
        f"hierarchy_level_definitions now reads {persisted!r}. The appended "
        "option exists for this modal instance only because a node in the "
        "tree already carries it — it must not be written to the exam's "
        "configured levels."
    )
