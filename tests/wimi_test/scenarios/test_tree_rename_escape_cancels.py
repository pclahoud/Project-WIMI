"""Regression: Escape during an inline subject rename cancels it (#727).

``startInlineEdit`` gave the rename input an ``onblur`` that saves, and the
Escape handler called ``cancelInlineEdit``, which calls ``renderTree()``.
Re-rendering removes the input while it has focus, removing a focused
element fires its ``blur``, and the blur handler saved the typed name. So
Escape wrote exactly the rename the student had just cancelled. Measured in
the running app during the #682 tree-editor tour pass: rename, type
"Renamed", Escape, and the database held "Renamed".

The key presses here are real ``Input.dispatchKeyEvent`` presses into the
focused input, the shape ``test_tree_rows_are_keyboard_operable.py`` uses for
F2 and Enter. A synthetic ``KeyboardEvent`` would not do: the defect lives in
what the browser does to focus when the tree re-renders, and only a real key
reaches the handler with the input still focused.

Enter is driven as a control in the same test. Without it, a change that
stopped the input from saving at all would pass the Escape half. The Enter
half also counts the ``updateSubjectNode`` calls. The re-render after Enter
fires the same blur, which on master re-entered ``finishInlineEdit`` a second
time. Only its "name already matches" check stopped a second write, so one
call per rename is asserted rather than assumed.

Both load paths are driven (CLAUDE.md, *Dimension code path symmetry*). The
rename code is shared, but the tree it re-renders is built by
``loadHierarchy`` on one arm and by ``loadDimensionHierarchy`` on the other.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers import a11y
from _helpers.tree_details import open_tree_editor, wait_for

#: Count every rename the page sends, wherever it comes from.
SPY = """
(() => {
    window.__renames = [];
    const real = api.updateSubjectNode;
    api.updateSubjectNode = (...args) => {
        window.__renames.push(args);
        return real.apply(api, args);
    };
})()
"""


def _seed(db, *, dimensioned: bool) -> tuple[int, int]:
    exam = db.create_exam_context(exam_name="W727 Tree", exam_description="")
    root = db.create_subject_node(
        exam_context=exam.exam_name, name="Cardiology", level_type="System")
    db.create_subject_node(
        exam_context=exam.exam_name, name="Arrhythmia", level_type="Topic",
        parent_id=root.id)
    db.conn.commit()
    if dimensioned:
        dim = db.create_dimension(exam_id=exam.id, name="System",
                                  display_order=1, is_required=True)
        db.move_subjects_into_axis([root.id], dim)
    assert db.exam_uses_dimensions(exam.id) == dimensioned, "seed drifted"
    return exam.id, root.id


def _open_rename(page: WimiPage, node_id: int) -> None:
    page.eval_js(f"startInlineEdit({node_id})")
    wait_for(page,
             "document.activeElement && document.activeElement.classList"
             ".contains('tree-node-name-input')",
             what="the rename input to take focus")
    page.eval_js("document.activeElement.select()")


def _stored_name(db, node_id: int) -> str:
    return db.fetchone(
        "SELECT name FROM subject_nodes WHERE id = ?", (node_id,))["name"]


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("dimensioned", [False, True],
                         ids=["loadHierarchy", "loadDimensionHierarchy"])
def test_escape_cancels_an_inline_rename_and_enter_saves_it_once(
    wimi_session: WimiTestSession, wimi_page: WimiPage, dimensioned: bool,
) -> None:
    db = wimi_session.user.db
    exam_id, node_id = _seed(db, dimensioned=dimensioned)

    open_tree_editor(wimi_page, exam_id)
    assert wimi_page.eval_js("TreeState.usesDimensions") == dimensioned
    wait_for(wimi_page, f"!!document.getElementById('name-{node_id}')",
             what="the subject row to render")
    wimi_page.eval_js(SPY)

    # ---- Escape: nothing is written, the old name is back on the row ----
    _open_rename(wimi_page, node_id)
    a11y.real_type(wimi_page, "Renamed")
    a11y.real_key(wimi_page, "Escape", settle_ms=1200)

    assert _stored_name(db, node_id) == "Cardiology", (
        f"#727: Escape saved the typed name (the database holds "
        f"{_stored_name(db, node_id)!r}). Re-rendering removed the focused "
        f"input, and its blur handler saved what Escape had just cancelled.")
    assert wimi_page.eval_js("window.__renames.length") == 0, (
        f"#727: Escape sent {wimi_page.eval_js('JSON.stringify(window.__renames)')}"
        f" to updateSubjectNode. Cancelling must write nothing.")
    shown = wimi_page.eval_js(
        f"(document.getElementById('name-{node_id}') || {{}}).textContent")
    assert shown == "Cardiology", (
        f"#727: after Escape the row reads {shown!r}, not the old name")
    assert not wimi_page.eval_js(
        "!!document.querySelector('.tree-node-name-input')"), (
        "#727: Escape left the rename input open")

    # ---- Enter, the control: the rename is saved, and saved once --------
    _open_rename(wimi_page, node_id)
    a11y.real_type(wimi_page, "Electrophysiology")
    a11y.real_key(wimi_page, "Enter", settle_ms=1200)

    assert _stored_name(db, node_id) == "Electrophysiology", (
        "#727: Enter no longer saves the rename, so the Escape half above "
        "proves nothing (an input that never saves passes it too)")
    calls = wimi_page.eval_js("window.__renames.length")
    assert calls == 1, (
        f"#727: one Enter sent {calls} renames. Re-rendering after the save "
        f"removes the focused input and fires its blur; that blur must not "
        f"end the rename a second time.")
