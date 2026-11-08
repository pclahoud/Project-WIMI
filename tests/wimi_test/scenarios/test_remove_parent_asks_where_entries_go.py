"""Removing a parent asks where the entries filed under it go (#738).

The owner's decision (2026-11-06): ask each time. Removing parent B from a
subject that also has A (primary) and C, when an entry is filed under B,
shows how many entries are affected and a picker of the remaining parents,
primary preselected. Confirming moves the entry to the chosen parent.

The control is the parent with nothing filed under it: no picker and the
original sentence, so the picker in the first half is the impact read
working, not a picker that is always drawn.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.tree_details import open_tree_editor, select_subject, wait_for


def _seed(db):
    exam = db.create_exam_context(exam_name="W738 Tree", exam_description="")
    mk = lambda name: db.create_subject_node(exam_context=exam.exam_name, name=name,
                                             level_type="System")
    a, b, c, child = mk("Cardiology"), mk("Pharmacology"), mk("Emergencies"), mk("Beta blockers")
    db.add_edge(a.id, child.id, is_primary=True)
    db.add_edge(b.id, child.id)
    db.add_edge(c.id, child.id)
    session = db.create_review_session(exam_context_id=exam.id, session_name="S",
                                       date_encountered=date.today(),
                                       total_questions=2, total_incorrect=1)
    entry = db.create_question_entry(review_session_id=session.id, user_answer="x",
                                     correct_answer="y", primary_subject_ids=[child.id])
    db.execute("UPDATE entry_subject_mappings SET primary_parent_id = ?"
               " WHERE question_entry_id = ?", (b.id, entry.id))
    db.conn.commit()
    return exam.id, a.id, b.id, c.id, child.id, entry.id


@pytest.mark.slow
@pytest.mark.regression
def test_removing_a_parent_asks_where_its_entries_go_and_moves_them(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, a, b, c, child, entry = _seed(db)
    open_tree_editor(wimi_page, exam_id)
    select_subject(wimi_page, child)
    wait_for(wimi_page, f"!!document.querySelector('[data-testid=\"tree-parent-remove-{b}\"]')",
             what="the details panel's parent rows")

    # ---- Control: a parent nothing is filed under asks nothing --------------
    wimi_page.locator(testid=f"tree-parent-remove-{c}").click()
    wait_for(wimi_page, f"!!document.querySelector('[data-testid=\"tree-parent-remove-confirm-{c}\"]')",
             what="the confirmation on parent C")
    wimi_page.wait_for_timeout(300)
    assert wimi_page.eval_js(
        f"!!document.querySelector('[data-testid=\"tree-parent-remove-target-{c}\"]')") is False, (
        "a parent with nothing filed under it must not draw a picker")
    assert "only this link goes away" in wimi_page.eval_js(
        "document.querySelector('.parent-row.confirming .parent-row-confirm-text').textContent")
    wimi_page.locator(testid=f"tree-parent-remove-cancel-{c}").click()

    # ---- The parent an entry is filed under asks, and moves it -----------
    wimi_page.locator(testid=f"tree-parent-remove-{b}").click()
    picker = f'[data-testid="tree-parent-remove-target-{b}"]'
    wait_for(wimi_page, f"!!document.querySelector('{picker}')",
             what="the picker of remaining parents")
    text = wimi_page.eval_js(
        "document.querySelector('.parent-row.confirming .parent-row-confirm-text').textContent")
    assert "1 entry is filed under it" in text, text
    options = wimi_page.eval_js(
        f"Array.from(document.querySelector('{picker}').options).map(o => [o.value, o.textContent])")
    assert options == [[str(a), "Cardiology (primary)"], [str(c), "Emergencies"]], options
    assert wimi_page.eval_js(f"document.querySelector('{picker}').value") == str(a), (
        "the primary parent must be preselected")

    wimi_page.eval_js(f"(() => {{ const s = document.querySelector('{picker}');"
                      f" s.value = '{c}'; s.dispatchEvent(new Event('change')); }})()")
    wimi_page.locator(testid=f"tree-parent-remove-confirm-{b}").click()

    moved = None
    for _ in range(50):
        moved = db.fetchone("SELECT primary_parent_id FROM entry_subject_mappings"
                            " WHERE question_entry_id = ?", (entry,))["primary_parent_id"]
        if moved == c:
            break
        wimi_page.wait_for_timeout(100)
    assert moved == c, f"the entry went to {moved}, not the chosen parent {c}"
    assert db.fetchone("SELECT 1 FROM subject_edges WHERE parent_id = ? AND child_id = ?",
                       (b, child)) is None, "the parent edge was not removed"
