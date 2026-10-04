"""#304: a subject row can be reached, selected and renamed from the keyboard.

What was wrong
--------------
``tree_editor.js`` rendered every row as::

    <div class="tree-node-content" onclick="selectNode(id)"
         ondblclick="startInlineEdit(id)">

No ``role``, no ``tabindex``, no key handler, so selecting a subject was
**mouse-only** and the double-click inline rename had no keyboard route at
all. Measured on this box at ``c8a904b`` with a real Tab walk of the tree
editor holding one root subject -- ten stops, none of them the row::

    tree-back-button -> tree-collapse-all -> tree-expand-all -> tree-import
    -> tree-import-help -> tree-export -> tree-add-root -> tree-search-input
    -> tree-node-add-child-1 -> tree-node-delete-1 -> BODY

and the row's name element reported ``role='generic' name='' name_from=[]``
to the accessibility tree.

Why the fix is on the name, not on the row container
----------------------------------------------------
``role="button"`` on ``.tree-node-content`` was tried and **measured**
first, because that is the element the issue names. It works -- the three
nested buttons stay exposed (button count 9 -> 10, not 9 -> 7) -- but the
row's computed accessible name becomes the concatenation of everything
inside it::

    '▶ 📁 Cardio System 0.0% + 🗑️'

i.e. the row announces the toggle, the icon, the level, the weight and
both action buttons as its own name. So the control is the **name span**,
whose contents are exactly the subject's name. The row keeps its mouse
handlers; nothing about the pointer path changes.

Why these assertions and not easier ones
----------------------------------------
Every assertion here is a *consequence*, never a handler firing:

* reachability is a real ``Input.dispatchKeyEvent`` Tab walk, because
  ``el.click()`` and ``el.focus()`` both succeed on an element that no
  keyboard user can get to (CLAUDE.md, #114/#285);
* Enter is checked by the details panel naming the subject, not by a spy;
* F2 is checked by the rename **reaching the database**, through the real
  inline input taking focus and real typed text -- which is the whole route
  that did not exist.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers import a11y
from _helpers import page_gate as pg


@pytest.mark.slow
@pytest.mark.regression
def test_a_subject_row_is_reachable_selectable_and_renameable_by_keyboard(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange ------------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W304 Tree", exam_description="")
    root = db.create_subject_node(
        exam_context=exam.exam_name, name="Cardiology", level_type="System")
    # A child on purpose: selecting a row WITH children expands it, which
    # calls renderTree() and destroys the focused control. A leaf would let
    # the focus assertions below pass without the restoration the fix adds.
    db.create_subject_node(
        exam_context=exam.exam_name, name="Arrhythmia", level_type="Topic",
        parent_id=root.id)
    db.conn.commit()

    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    pg.wait_for_release(wimi_page)
    # Poll for the row rather than sleeping on it.
    for _ in range(60):
        if wimi_page.eval_js(
            "document.querySelectorAll('.tree-node-content').length > 0"
        ):
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError("the tree never rendered a row to test")

    # ---- Act / Assert 1: the row is in the tab order -------------------
    #
    # `walk_to`, not `tab_walk`: the walk has to STOP on the row, because
    # everything from Assert 3 down presses keys at whatever has focus. An
    # earlier draft collected 16 stops and then pressed Enter, by which time
    # focus had walked past the row and wrapped round to the toolbar -- and
    # the failure read "Enter on the focused row did not select the subject"
    # while Enter was never sent to the row at all.
    a11y.start_tab_walk(wimi_page)
    row_stop = a11y.walk_to(
        wimi_page,
        lambda s: s.get("testid") == f"tree-node-name-{root.id}",
        presses=16,
    )
    if row_stop is None:
        a11y.start_tab_walk(wimi_page)
        order = a11y.summarise(a11y.tab_walk(wimi_page, presses=16))
        raise AssertionError(
            f"#304: no Tab press landed on the subject row. The whole tab "
            f"order was: {order}. A row that is not in the tab order cannot "
            f"be selected by a keyboard or screen-reader user at all -- and "
            f"note that `el.click()` on it would still have worked, which is "
            f"why this is measured with real Tab presses."
        )
    # The ring is drawn on the ROW, not on the name span that holds the
    # focus: an outline on `.tree-node-name` (which is `flex: 1`) is almost
    # indistinguishable from `.tree-node-name-input`, so a focused row read
    # as a row already in rename mode. Read where the ring actually is.
    ring = a11y.focus_within_ring(
        wimi_page, ".tree-node-content:has(> .tree-node-name:focus-visible)")
    assert ring["found"] and a11y.has_focus_ring(ring), (
        f"#304: the row takes focus with no visible indicator "
        f"(row ring: {ring}; the focused span itself reports outline "
        f"{row_stop['outlineStyle']} {row_stop['outlineWidth']}). A focus "
        f"stop nobody can see is only half a keyboard route."
    )

    # ---- Assert 2: assistive tech is told what it is -------------------
    a11y.enable(wimi_page)
    node = a11y.ax_node(wimi_page, f'[data-testid="tree-node-name-{root.id}"]')
    assert node["role"] == "button", (
        f"#304: the row is not exposed as an activatable control: "
        f"{a11y.describe(node)}. Before the fix this measured "
        f"role='generic' name='' -- a screen reader had nothing to announce "
        f"and nothing to press."
    )
    assert node["name"] == "Cardiology", (
        f"#304: the row's accessible name is not the subject: "
        f"{a11y.describe(node)}"
    )

    # ---- Assert 3: Enter selects it (by consequence) -------------------
    selected_before = wimi_page.eval_js(
        "window.TreeState ? TreeState.selectedNodeId : 'no TreeState'")
    assert selected_before != root.id, (
        "arrange is void: the row is already selected, so Enter could not "
        "be shown to do anything"
    )
    holding = a11y.active_element(wimi_page)
    assert holding.get("testid") == f"tree-node-name-{root.id}", (
        f"the probe lost the row before pressing Enter (focus is on "
        f"{holding.get('testid') or holding['tag']}); reading the AX tree "
        f"above must not move focus, or this measures the wrong element"
    )
    a11y.real_key(wimi_page, "Enter", settle_ms=600)
    assert wimi_page.eval_js("TreeState.selectedNodeId") == root.id, (
        "#304: Enter on the focused row did not select the subject"
    )
    assert wimi_page.eval_js(
        "(() => { const p = document.querySelector('.details-panel');"
        " return !!p && (p.innerText || '').includes('Cardiology'); })()"
    ) is True, (
        "#304: Enter reported a selection but the details panel does not "
        "name the subject, so nothing the student can see happened. This "
        "asserts the consequence rather than the handler on purpose."
    )

    # ---- Assert 4: F2 opens the rename and a typed name is saved -------
    # Focus is still on the row (selectNode re-renders the tree, so the fix
    # has to put focus back -- which is exactly what this checks).
    focused = a11y.active_element(wimi_page)
    assert focused.get("testid") == f"tree-node-name-{root.id}", (
        f"#304: selecting the row lost keyboard focus (it is now on "
        f"{focused.get('testid') or focused['tag']}). renderTree() replaces "
        f"the row, so the keyboard user is dumped at the top of the document "
        f"after every Enter -- a route that cannot be used twice is not a "
        f"route."
    )
    a11y.real_key(wimi_page, "F2", settle_ms=400)
    editing = a11y.active_element(wimi_page)
    assert "tree-node-name-input" in (editing.get("cls") or ""), (
        f"#304: F2 did not open the inline rename, or opened it without "
        f"moving focus into it (focus is on "
        f"{editing.get('cls') or editing['tag']}). The double-click rename "
        f"had no keyboard equivalent at all before this."
    )
    wimi_page.eval_js(
        "(() => { const i = document.querySelector('.tree-node-name-input');"
        " if (i) { i.select(); } })()")
    a11y.real_type(wimi_page, "Electrophysiology")
    a11y.real_key(wimi_page, "Enter", settle_ms=1200)

    renamed = db.fetchone(
        "SELECT name FROM subject_nodes WHERE id = ?", (root.id,))
    assert renamed["name"] == "Electrophysiology", (
        f"#304: the keyboard rename did not reach the database "
        f"(still {renamed['name']!r}). This is the end of the route the "
        f"issue says does not exist: Tab to the row, F2, type, Enter."
    )
    after_rename = a11y.active_element(wimi_page)
    assert after_rename.get("testid") == f"tree-node-name-{root.id}", (
        f"#304: focus went to {after_rename.get('testid') or after_rename['tag']} "
        f"after the rename. Committing a rename re-renders the tree, so "
        f"without handing focus back the student has to Tab in from the top "
        f"of the document to fix a typo -- the route works exactly once."
    )

    # ---- Assert 5: the per-row actions are visible once focused --------
    # They live in a group at `opacity: 0` revealed on row hover, so Tab
    # landed on a focusable, accessible-tree-exposed, INVISIBLE button --
    # and an outline on that button would have been transparent too. Only
    # the effective-opacity term in has_focus_ring() can tell.
    action = a11y.walk_to(
        wimi_page,
        lambda s: s.get("testid") == f"tree-node-add-child-{root.id}",
        presses=12)
    assert action is not None, (
        "the per-row Add Child button is not reachable by Tab")
    assert action["opacity"] > 0.05, (
        f"#304: the focused Add Child button renders at opacity "
        f"{action['opacity']} -- `.tree-node-actions` is revealed on row "
        f"HOVER only, so a keyboard user operates an invisible control. No "
        f"outline can fix that; the group needs `:focus-within`."
    )
    assert a11y.has_focus_ring(action), (
        f"#304: the focused Add Child button draws no visible ring "
        f"(outline {action['outlineStyle']} {action['outlineWidth']}, "
        f"opacity {action['opacity']})."
    )
