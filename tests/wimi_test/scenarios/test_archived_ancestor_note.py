"""Regression: the deep dive's path drops an archived ancestor AND says so
(#301, owner's decision 2026-10-03).

`_build_subject_path` walked through archived ancestors, so an active `Child`
whose parent had been archived rendered "Parent > Child" while
`get_paths_to_root` (fixed in #262) answered `[[Child]]`. One of the two named
a subject the tree no longer shows, and this one was the string a student
reads.

The decision was **neither** of the issue's two options: filter the path *and*
explain the shortening in a hover tooltip. So this scenario has to assert both
halves, and the second half has to be asserted **only where something was
removed** -- an affordance that always appears means nothing, so the
negative-control test below is not optional decoration.

Three things this test does that a DOM-presence check would not
---------------------------------------------------------------
* It reads the **accessibility tree**, not `aria-label`. Per #121/#127 the
  `aria-*` attributes are exactly what stays correct when the node has been
  removed from the tree, and the whole reason `title=` was rejected for this
  is that it is unreliable to assistive tech. The gate is released by the time
  the deep dive renders, so the AX tree is not blind here -- unlike #121's
  case.
* It **focuses** the note and reads computed `display` on the tooltip. That is
  the measurable difference from `title=`, which never appears on keyboard
  focus. `el.focus()` is used rather than a synthetic Tab because CDP's
  synthetic Tab moves `document.activeElement` without setting a focus flag CSS
  can read (CLAUDE.md, 2026-10-03) -- `:focus` responds to the programmatic
  call, and the ring is a separate `:focus-visible` rule the static guard in
  `tests/test_web_archived_ancestor_note.py` covers.
* It runs `ArchivedAncestorNote.sentence` in the real page for the plural
  arities. The static test can only see that the branches exist.

And it pins the **placement**. The note is a sibling of `#fullPath`, never a
child, because that element's `textContent` is the value other scenarios read
-- `test_multi_parent_selector_refilter.py` asserts a subject name is *absent*
from it, so a nested note would let an archived subject's name turn that test
red for an unrelated reason. It was nested in the first draft of this change
and this test is what found it. (`display: none` does not help: `textContent`
returns hidden text, which is the inverse of the `innerText` distinction
#121 relies on.)
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_PATH_JS = (
    "(() => { const el = document.getElementById('fullPath'); "
    "return el ? el.textContent.trim() : null; })()"
)
_NOTE_JS = (
    "(() => { const el = document.querySelector("
    "'[data-testid=\"archived-ancestors-note\"]'); "
    "return el ? el.getAttribute('aria-label') : null; })()"
)
_NOTE_IS_A_SIBLING_JS = (
    "(() => { const path = document.getElementById('fullPath'); "
    "const note = document.querySelector("
    "'[data-testid=\"archived-ancestors-note\"]'); "
    "if (!path || !note) return 'missing'; "
    "if (path.contains(note)) return 'nested'; "
    "return path.nextElementSibling === note ? 'sibling' : 'elsewhere'; })()"
)
_NOTE_COUNT_JS = (
    "document.querySelectorAll("
    "'[data-testid=\"archived-ancestors-note\"]').length"
)
_TOOLTIP_DISPLAY_JS = (
    "(() => { const host = document.querySelector("
    "'[data-testid=\"archived-ancestors-note\"]'); "
    "if (!host) return 'no-host'; "
    "const tip = host.querySelector("
    "'[data-testid=\"archived-ancestors-tooltip\"]'); "
    "if (!tip) return 'no-tooltip'; "
    "const before = getComputedStyle(tip).display; "
    "host.focus(); "
    "const after = getComputedStyle(tip).display; "
    "return before + '|' + after; })()"
)


def _seed_exam(db, exam_name: str):
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()
    exam = db.create_exam_context(exam_name=exam_name,
                                  exam_description="Issue #301")
    ec_id = db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = ?",
        (exam.exam_name,))["id"]
    return exam, ec_id


def _node(db, exam, name, parent_id=None):
    n = db.create_subject_node(
        exam_context=exam.exam_name, name=name, parent_id=parent_id,
        level_type="Topic")
    return n.id if hasattr(n, "id") else n


def _entry_on(db, ec_id, subject_id):
    """One entry so the deep dive has something to render."""
    cur = db.execute(
        "INSERT INTO review_sessions (user_id, session_name, "
        "date_encountered, exam_context_id, total_questions, total_incorrect) "
        "VALUES (?, '#301', date('now'), ?, 1, 1)",
        (db.user_id, ec_id),
    )
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer) VALUES (?, 1, 'A', 'B')",
        (cur.lastrowid,),
    )
    db.execute(
        "INSERT INTO entry_subject_mappings (question_entry_id, "
        "subject_node_id, mapping_type) VALUES (?, ?, 'primary')",
        (entry.lastrowid, subject_id),
    )
    db.conn.commit()


def _orphan_under_archived_parent(db, exam):
    """`Parent` archived, `Child` active, the edge intact.

    Reached the way #37's restore reaches it rather than by writing rows, so
    the state under test is one the product can actually be in: delete the
    child (its edge survives, the parent is active), delete the parent (it
    survives again), restore the child.
    """
    parent = _node(db, exam, "W301 Parent")
    child = _node(db, exam, "W301 Child", parent_id=parent)
    batch = db.delete_subject_subtree(child)["batch_id"]
    db.delete_subject_subtree(parent)
    db.restore_subject_delete_batch(batch)
    db.conn.commit()
    assert db.fetchone(
        "SELECT status FROM subject_nodes WHERE id = ?",
        (parent,))["status"] == "archived"
    assert db.fetchone(
        "SELECT 1 FROM subject_edges WHERE parent_id = ? AND child_id = ?",
        (parent, child)) is not None, (
        "the surviving edge is what makes this the bug"
    )
    return parent, child


def _open_deep_dive(wimi_page: WimiPage, subject_id: int, exam_id: int) -> str:
    wimi_page.goto("subject-deep-dive",
                   query={"subject": subject_id, "exam": exam_id})
    path = None
    for _ in range(40):  # bounded poll; the page's init() is async
        path = wimi_page.eval_js(_PATH_JS)
        if path and path != "-":
            return path
        wimi_page.wait_for_timeout(250)
    pytest.fail(f"Full path never rendered; last text {path!r}")


def _ax_names(wimi_page: WimiPage) -> list[str]:
    """Every accessible name in the tree Chromium hands assistive tech."""
    tab = wimi_page.tab
    tab.Accessibility.enable()
    tree = tab.Accessibility.getFullAXTree()
    names = []
    for node in tree.get("nodes", []):
        name = (node.get("name") or {}).get("value")
        if name:
            names.append(name)
    return names


@pytest.mark.slow
@pytest.mark.regression
def test_an_archived_parent_leaves_the_path_and_leaves_a_note(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Both halves of the decision, on the page #314 is about to extend."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam, ec_id = _seed_exam(db, "Issue 301 Shortened")
    _parent, child = _orphan_under_archived_parent(db, exam)
    _entry_on(db, ec_id, child)

    # ---- Act ---------------------------------------------------------
    path = _open_deep_dive(wimi_page, child, ec_id)
    label = wimi_page.eval_js(_NOTE_JS)
    placement = wimi_page.eval_js(_NOTE_IS_A_SIBLING_JS)
    count = wimi_page.eval_js(_NOTE_COUNT_JS)
    displays = wimi_page.eval_js(_TOOLTIP_DISPLAY_JS)
    ax_names = _ax_names(wimi_page)

    # ---- Assert ------------------------------------------------------
    # Half one: the filter. Before #301 this read "W301 Parent > W301 Child".
    # `textContent`, exactly, is also what pins the placement -- a nested
    # note would append the whole sentence to this value.
    assert path == "W301 Child", (
        f"the rendered path still names the archived parent, or the note was "
        f"nested inside the value node: {path!r}"
    )
    assert "W301 Parent" not in path
    assert placement == "sibling", (
        f"the note sits {placement!r} relative to #fullPath; it must be the "
        f"next sibling, so that element's textContent stays the path"
    )
    assert count == 1, f"expected exactly one note on the page, found {count}"

    # Half two: the explanation, and it has to name the subject that went.
    assert label is not None, (
        "the path was shortened and nothing on the page says why -- that is "
        "the cost the owner's decision refused to accept (#301)"
    )
    assert "W301 Parent" in label, f"note does not name what went: {label!r}"
    assert "Archived subjects" in label, (
        f"the note must say where to undo -- #37 landed, and a warning that "
        f"denies an existing way forward is worse than none: {label!r}"
    )

    # The accessible name reaches the tree Chromium gives assistive tech.
    # Asserted through the AX tree rather than off `aria-label`, because the
    # attribute is what stays correct when the node has been removed from it.
    assert any("W301 Parent" in name for name in ax_names), (
        f"the note is not exposed to assistive tech; {len(ax_names)} names "
        f"in the tree"
    )

    # And it opens on keyboard focus, which is the whole reason `title=` was
    # rejected for this.
    assert displays == "none|block", (
        f"tooltip display before|after focus was {displays!r}; it must be "
        f"hidden until hovered or focused, and shown on focus"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_a_whole_path_gets_no_note(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The negative control, and the half that makes the affordance mean
    something.

    Without it, "always render the note" passes the test above. The owner's
    decision says it explicitly: only where a path was actually shortened.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam, ec_id = _seed_exam(db, "Issue 301 Whole")
    root = _node(db, exam, "W301 Root")
    leaf = _node(db, exam, "W301 Leaf", parent_id=root)
    db.conn.commit()
    _entry_on(db, ec_id, leaf)

    # ---- Act ---------------------------------------------------------
    path = _open_deep_dive(wimi_page, leaf, ec_id)
    label = wimi_page.eval_js(_NOTE_JS)

    # ---- Assert ------------------------------------------------------
    assert path == "W301 Root > W301 Leaf", (
        f"an active ancestor must still be named: {path!r}"
    )
    assert label is None, (
        f"a complete path carries an explanation it does not need, so the "
        f"affordance stops meaning anything: {label!r}"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_the_sentence_reads_correctly_for_every_arity(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Run the real `sentence()` in the real page.

    The static guard can only see that three joining branches exist. A branch
    rendering `"A"and"B"` would satisfy it and read wrong to a student.
    """
    wimi_page.goto("subject-deep-dive")
    for _ in range(40):
        if wimi_page.eval_js(
                "typeof window.ArchivedAncestorNote !== 'undefined'"):
            break
        wimi_page.wait_for_timeout(250)
    else:
        pytest.fail("ArchivedAncestorNote never loaded on the deep dive")

    empty = wimi_page.eval_js("window.ArchivedAncestorNote.sentence([])")
    one = wimi_page.eval_js(
        "window.ArchivedAncestorNote.sentence(['A'])")
    two = wimi_page.eval_js(
        "window.ArchivedAncestorNote.sentence(['A', 'B'])")
    three = wimi_page.eval_js(
        "window.ArchivedAncestorNote.sentence(['A', 'B', 'C'])")
    blank = wimi_page.eval_js(
        "window.ArchivedAncestorNote.sentence(['   '])")
    missing = wimi_page.eval_js(
        "window.ArchivedAncestorNote.sentence(undefined)")

    assert empty == "", f"empty list said something: {empty!r}"
    assert missing == "", f"missing argument said something: {missing!r}"
    assert blank == "", (
        f"a blank name is not a name, and would render an empty quote pair: "
        f"{blank!r}"
    )
    assert '"A" is archived' in one, one
    assert '"A" and "B" are archived' in two, two
    assert '"A", "B" and "C" are archived' in three, three
    # `create` is the other half of the same rule.
    assert wimi_page.eval_js(
        "window.ArchivedAncestorNote.create([]) === null"), (
        "create() must return null for an empty list, or every caller has to "
        "remember the check itself"
    )
