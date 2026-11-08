"""The tree editor re-derives axis mode after a write changes the axes (#899).

`exam_uses_dimensions` is derived from the count of active axes, but the tree
editor only asked at startup. So a whole-exam import or an axis Restore that
gave a plain exam its first axis left the page in the plain view -- both
trees drawn mixed, no tabs, and Add Subject creating subjects outside every
axis until a reload. On an exam that already had axes, a restored or imported
axis got no tab. Measured live on #899 comment 12255.

Every test ends with the same positive control: a reload, which runs the
startup mode logic, must show the state the page reached in place. If the
reload disagreed, the in-page assertion would be testing something other
than "the page matches a fresh load".
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.axis_mode import (
    import_file, open_tree, poll, reload_tree, restore_archived, seed_exam,
    state, wait_state,
)


@pytest.mark.slow
@pytest.mark.regression
def test_a_whole_exam_import_on_a_plain_exam_lands_in_the_axis_view(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, _, nodes = seed_exam(db, "W899 Import", {}, plain=("Cardiology",))
    open_tree(wimi_page, exam_id)
    before = state(wimi_page)
    assert before["uses"] is False and before["rows"] == ["Cardiology"], (
        f"premise: the exam starts plain, {before}")

    # Keep them aside (#605 Wave 2): this test is about the panel offering
    # the new axis afterwards, which is the path that answer leads to.
    import_file(wimi_page, {"dimensions": [
        {"name": "System", "root_nodes": [{"name": "Renal"}]}]},
        first_axis="aside")

    after = wait_state(wimi_page, lambda s: s["uses"] and s["rows"] == ["Renal"])
    assert after["uses"] is True and after["tabs"] == ["System"] \
        and after["activeTab"] == "System" and after["exportAllShown"] \
        and after["rows"] == ["Renal"], (
        f"#899: still plain / no tab after the import gave the exam its first "
        f"axis: {after}")

    # The panel offers the new axis rather than "No active axis".
    wimi_page.locator(css='[data-testid="tree-unassigned-toggle"]').click()
    move = f'[data-testid="tree-unassigned-move-{nodes["Cardiology"]}"]'
    offered = poll(wimi_page, lambda: wimi_page.eval_js(
        f"!!document.querySelector('{move}')"), bool)
    assert offered is True, (
        "the unassigned panel does not offer an axis to move Cardiology into")
    wimi_page.locator(css=move).click()

    moved = wait_state(wimi_page, lambda s: s["rows"] == ["Cardiology", "Renal"])
    assert moved["rows"] == ["Cardiology", "Renal"] and moved["tabs"] == ["System"], (
        f"Move in did not put Cardiology into the System tree: {moved}")
    system_id = db.fetchone(
        "SELECT id FROM exam_dimensions WHERE exam_id = ? AND name = 'System'",
        (exam_id,))["id"]
    assert db.fetchone("SELECT dimension_id FROM subject_nodes WHERE id = ?",
                       (nodes["Cardiology"],))["dimension_id"] == system_id

    reload_tree(wimi_page, exam_id)
    fresh = wait_state(wimi_page, lambda s: s["rows"] == ["Cardiology", "Renal"])
    assert (fresh["uses"], fresh["tabs"], fresh["rows"]) == (
        True, ["System"], ["Cardiology", "Renal"]), f"reload control: {fresh}"


@pytest.mark.slow
@pytest.mark.regression
def test_restoring_the_only_axis_lands_in_the_axis_view(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, dims, _ = seed_exam(db, "W899 Restore", {"System": ["Renal"]},
                                 plain=("Cardiology",))
    batch = db.archive_dimension(dims["System"])["batch_id"]
    assert batch and not db.exam_uses_dimensions(exam_id), "premise drifted"

    open_tree(wimi_page, exam_id)
    assert state(wimi_page)["uses"] is False, "premise: the exam opens plain"

    restore_archived(wimi_page, batch)

    after = wait_state(wimi_page, lambda s: s["uses"] and s["rows"] == ["Renal"])
    assert after["uses"] is True and after["tabs"] == ["System"] \
        and after["rows"] == ["Renal"], (
        f"#899: still plain / no tab after restoring the exam's only axis: {after}")

    reload_tree(wimi_page, exam_id)
    fresh = wait_state(wimi_page, lambda s: s["rows"] == ["Renal"])
    assert (fresh["uses"], fresh["tabs"], fresh["rows"]) == (
        True, ["System"], ["Renal"]), f"reload control: {fresh}"


@pytest.mark.slow
@pytest.mark.regression
def test_restoring_a_second_axis_adds_its_tab_and_keeps_the_current_one(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, dims, _ = seed_exam(db, "W899 Second", {
        "System": ["Renal"], "Task": ["Diagnosis"], "Discipline": ["Pharmacology"]})
    batch = db.archive_dimension(dims["Discipline"])["batch_id"]

    open_tree(wimi_page, exam_id)
    # Select the axis that is NOT first, so "kept the current one" cannot be
    # satisfied by falling back to the first tab.
    wimi_page.eval_js(f"selectDimension({dims['Task']})", await_promise=True)
    picked = wait_state(wimi_page, lambda s: s["rows"] == ["Diagnosis"])
    assert picked["tabs"] == ["System", "Task"] and picked["activeTab"] == "Task", (
        f"premise: {picked}")

    restore_archived(wimi_page, batch)

    after = wait_state(wimi_page, lambda s: "Discipline" in s["tabs"])
    assert after["tabs"] == ["System", "Task", "Discipline"], (
        f"#899: no tab for the restored axis: {after}")
    assert after["activeTab"] == "Task" and after["current"] == dims["Task"] \
        and after["rows"] == ["Diagnosis"], (
        f"the restore moved the student off the axis they were on: {after}")

    reload_tree(wimi_page, exam_id)
    fresh = wait_state(wimi_page, lambda s: len(s["tabs"]) == 3)
    assert fresh["tabs"] == ["System", "Task", "Discipline"], f"reload control: {fresh}"


@pytest.mark.slow
@pytest.mark.regression
def test_a_whole_exam_import_that_adds_an_axis_adds_its_tab(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, dims, _ = seed_exam(db, "W899 Add Axis", {"System": ["Renal"]})
    open_tree(wimi_page, exam_id)
    before = wait_state(wimi_page, lambda s: s["rows"] == ["Renal"])
    assert before["tabs"] == ["System"], f"premise: {before}"

    import_file(wimi_page, {"dimensions": [
        {"name": "System", "root_nodes": [{"name": "Renal"}]},
        {"name": "Task", "root_nodes": [{"name": "Diagnosis"}]},
    ]})

    after = wait_state(wimi_page, lambda s: "Task" in s["tabs"])
    assert after["tabs"] == ["System", "Task"], (
        f"#899: no tab for the axis the import added: {after}")
    assert after["activeTab"] == "System" and after["rows"] == ["Renal"], (
        f"the import moved the student off the axis they were on: {after}")

    reload_tree(wimi_page, exam_id)
    fresh = wait_state(wimi_page, lambda s: len(s["tabs"]) == 2)
    assert fresh["tabs"] == ["System", "Task"], f"reload control: {fresh}"
