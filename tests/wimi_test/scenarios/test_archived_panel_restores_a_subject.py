"""A student deletes a subject, restores it from the panel, and the tree is back.

Issue #37's own acceptance criterion, last line: *"A regression scenario
deletes a subject, restores it from the panel, and asserts the tree matches
the pre-delete state."*

This is the only test in #37 that goes through the surface a student actually
uses. Waves 1 and 2 pin the database layer and the bridge slots; neither can
tell you that the panel is reachable, that it lists the deletion, that its
Restore button is wired, or that the tree redraws afterwards. Every one of
those has been a real defect class in this project:

* A panel rendered at **zero pixels** because of `:empty` (#134/#136/#141) —
  present in the DOM, invisible, and passing any presence test.
* A bridge call that reported success while doing nothing (#240).
* A dimension code path that was never mirrored, so the common case broke
  while the plain case passed (CLAUDE.md, *Dimension code path symmetry*).

So the assertions are deliberately about **what the tree shows**, before and
after, compared by subject name — not about the panel's internals.

The comparison is by **row identity, not counts.** A restore that archived
something and created a lookalike would satisfy a count. The pre-delete
subject ids are captured and asserted to be the same ids afterwards, which is
the same reasoning `test_whole_exam_round_trip.py` uses for the import.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _visible_subject_names(page: WimiPage) -> list[str]:
    """Every subject name the tree is currently drawing, in DOM order.

    Read from the DOM rather than from `TreeState`, because `TreeState` is what
    the page *believes* and the point of a scenario is what it *renders*.
    """
    # `.tree-node-name` rather than a test id: the test id is per-node
    # (`tree-node-name-<id>`), so there is no stable selector for "all of
    # them". The class is what `renderNode` emits for every name span.
    return page.eval_js(
        """
        Array.from(document.querySelectorAll('.tree-node-name'))
             .map(el => el.textContent.trim())
        """
    )


def _expand_all(page: WimiPage) -> None:
    """Expand every node, through the toolbar button a student would use.

    The tree renders collapsed, so a child subject is simply not in the DOM
    until its ancestors are open -- and this test compares *drawn* names, which
    is the whole point of doing it here rather than in a unit test.
    """
    page.locator(testid="tree-expand-all").click()


def _wait_for_tree(page: WimiPage, expected: str, *, present: bool) -> list[str]:
    """Poll until ``expected`` is (or is not) among the drawn subject names."""
    names: list[str] = []
    for _ in range(40):
        names = _visible_subject_names(page) or []
        if (expected in names) is present:
            return names
        page.wait_for_timeout(250)
    return names


@pytest.mark.slow
@pytest.mark.regression
def test_deleting_then_restoring_from_the_panel_puts_the_tree_back(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Delete through the database, restore through the panel, compare the tree."""
    # ---- Arrange -----------------------------------------------------
    # Seeded through the database per the scenario conventions; the *restore*
    # is what this test drives through the UI.
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 37 Restore Panel",
        exam_description="Regression scenario for Forgejo issue #37 Wave 3",
    )

    def node(name: str, parent_id: int | None = None) -> int:
        return db.create_subject_node(
            exam_context=exam.exam_name,
            name=name,
            level_type="System" if parent_id is None else "Topic",
            parent_id=parent_id,
        ).id

    cardio = node("W3 Cardiovascular System")
    valvular = node("W3 Valvular Disease", cardio)
    node("W3 Aortic Stenosis", valvular)
    node("W3 Renal System")

    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    _wait_for_tree(wimi_page, "W3 Cardiovascular System", present=True)
    _expand_all(wimi_page)
    before = _wait_for_tree(wimi_page, "W3 Valvular Disease", present=True)
    assert "W3 Valvular Disease" in before, (
        f"the seeded tree never rendered; saw {before!r}"
    )
    assert "W3 Aortic Stenosis" in before

    ids_before = {
        row["id"]: row["name"]
        for row in db.fetchall(
            "SELECT id, name FROM subject_nodes "
            "WHERE exam_context = ? AND status = 'active' ORDER BY id",
            (exam.exam_name,),
        )
    }

    # ---- Act 1: delete, and confirm the panel notices ----------------
    batch = db.delete_subject_subtree(valvular)["batch_id"]
    assert batch, "the delete must open a journal batch for there to be anything to restore"

    # A second goto returns before the new document commits, so mark the old
    # one and wait for it to go (scenario convention).
    wimi_page.eval_js("window.__w37_old_document = true")
    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    for _ in range(40):
        if not wimi_page.eval_js("window.__w37_old_document === true"):
            break
        wimi_page.wait_for_timeout(250)

    _wait_for_tree(wimi_page, "W3 Cardiovascular System", present=True)
    _expand_all(wimi_page)
    after_delete = _wait_for_tree(wimi_page, "W3 Valvular Disease", present=False)
    assert "W3 Valvular Disease" not in after_delete
    assert "W3 Aortic Stenosis" not in after_delete, (
        "the exclusive child goes with it (#15's cascade)"
    )

    # The panel must be visible and must carry the deletion. Asserted through
    # `offsetParent`, not presence: a panel that renders at zero pixels is in
    # the DOM and satisfies a presence check (#134/#136/#141).
    panel_visible = False
    for _ in range(40):
        panel_visible = wimi_page.eval_js(
            """
            (() => {
                const el = document.querySelector('[data-testid="tree-archived-panel"]');
                if (!el) return false;
                if (el.classList.contains('hidden')) return false;
                return el.offsetParent !== null && el.getBoundingClientRect().height > 0;
            })()
            """
        )
        if panel_visible:
            break
        wimi_page.wait_for_timeout(250)
    assert panel_visible, "the Archived panel never became visible after a delete"

    assert wimi_page.eval_js(
        'document.querySelector("[data-testid=tree-archived-count]").textContent.trim()'
    ) == "1"

    # ---- Act 2: expand it and restore through the button -------------
    # It is collapsed by default (#37), so the body must be closed first --
    # otherwise the expand step below would pass against an always-open panel.
    assert wimi_page.eval_js(
        'document.querySelector("[data-testid=tree-archived-body]").hidden'
    ) is True, "the panel must start collapsed"

    wimi_page.locator(testid="tree-archived-toggle").click()
    for _ in range(20):
        if wimi_page.eval_js(
            'document.querySelector("[data-testid=tree-archived-body]").hidden'
        ) is False:
            break
        wimi_page.wait_for_timeout(100)

    row_text = wimi_page.eval_js(
        'document.querySelector("[data-testid=tree-archived-item]").innerText'
    )
    assert "W3 Valvular Disease" in row_text
    assert "was under" in row_text and "W3 Cardiovascular System" in row_text, (
        f"the row must say what it was under (#37); got {row_text!r}"
    )

    wimi_page.locator(testid="tree-archived-restore").click()

    # ---- Assert: the tree is back, by id and not by count ------------
    # The restore reloads the tree, which redraws it collapsed again.
    _wait_for_tree(wimi_page, "W3 Cardiovascular System", present=True)
    for _ in range(40):
        _expand_all(wimi_page)
        if "W3 Valvular Disease" in (_visible_subject_names(wimi_page) or []):
            break
        wimi_page.wait_for_timeout(250)
    after_restore = _wait_for_tree(wimi_page, "W3 Valvular Disease", present=True)
    assert "W3 Valvular Disease" in after_restore, (
        f"restore did not bring the subject back; tree shows {after_restore!r}"
    )
    assert "W3 Aortic Stenosis" in after_restore, (
        "the whole batch comes back, not just its root"
    )
    assert after_restore == before, (
        "the tree must match its pre-delete state exactly (#37's acceptance)\n"
        f"  before: {before!r}\n  after:  {after_restore!r}"
    )

    ids_after = {
        row["id"]: row["name"]
        for row in db.fetchall(
            "SELECT id, name FROM subject_nodes "
            "WHERE exam_context = ? AND status = 'active' ORDER BY id",
            (exam.exam_name,),
        )
    }
    assert ids_after == ids_before, (
        "same rows, not lookalikes -- a restore that archived one subject and "
        "created an identical one would pass a count comparison"
    )

    # And the panel empties itself, because a resolved batch has no claimant.
    for _ in range(40):
        if wimi_page.eval_js(
            """
            (() => {
                const el = document.querySelector('[data-testid="tree-archived-panel"]');
                return !el || el.classList.contains('hidden');
            })()
            """
        ):
            return
        wimi_page.wait_for_timeout(250)
    pytest.fail("the Archived panel stayed visible after its only batch was restored")
