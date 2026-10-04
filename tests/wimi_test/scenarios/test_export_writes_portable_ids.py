"""Regression: the export writes portable ids, never database row ids (#237).

Issue #237 — *"the tree export writes a raw dimension row id as a portable
identifier, so a file cannot round-trip between profiles"*.

The subject half of this rule was settled in #67 and its reasoning is four
lines of comment in ``import_export.js``:

    *"the file's stable id, when this subject has one. NOT ``node.id`` -- that
    is the database row id, which means nothing in another profile and would
    claim to identify subjects that were never imported."*

**Nothing asserted it.** Before this file the only tests touching
``import_export.js`` were the guide-sync test and two import scenarios, so the
rule was protected by a comment — which is exactly how the dimension-level
version of it came to be violated, where a mis-identified dimension costs an
entire subject tree rather than one subject.

Two things this scenario is shaped around.

**The builders are called directly, not through a download.** ``a.click()`` on
a blob URL is not observable from CDP, so #237 split the file *building* out of
the file *downloading*. ``window.buildSingleTreeExport`` and
``window.buildWholeExamExport`` are pure, and that is what makes what the
export writes testable at all.

**A per-dimension export must carry no dimension id, and that is an absence.**
#241 makes a file's ``dimensions`` list authoritative about exam structure, so
a file declaring one axis says "this exam has one dimension" and archives the
rest. Measured on a three-axis exam, importing a one-axis file archived the
other two axes and their trees. So the single-tree form deliberately has no
place to put a dimension id, and the whole-exam form -- which declares every
axis and is a no-op on re-import -- is the only one that carries them.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Builds both file shapes from the page's own data and hands them back, so the
# assertions run against exactly what a download would have contained.
_RUNNER = """
window.__e237 = async function (examContextId) {
    const dimensions = await window.api.getDimensions(examContextId);
    const axes = [];
    for (const dimension of dimensions) {
        axes.push({
            dimension,
            hierarchyData: await window.api.getDimensionHierarchy(
                examContextId, dimension.id),
        });
    }
    const examContext = { exam_name: 'Issue 237 Export' };
    const whole = window.buildWholeExamExport({
        axes, examContext, examContextId, hierarchyLevels: [],
    });
    const single = window.buildSingleTreeExport({
        hierarchyData: axes[0].hierarchyData,
        examContext, examContextId, hierarchyLevels: [],
        dimension: axes[0].dimension,
    });
    return { whole: JSON.stringify(whole), single: JSON.stringify(single),
             rowIds: dimensions.map(d => d.id) };
};
true
"""


def _wait_for(page: WimiPage, expression: str, *, what: str, tries: int = 50) -> None:
    for _ in range(tries):
        if page.eval_js(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}: {expression}")


def _walk(nodes):
    for node in nodes or []:
        yield node
        yield from _walk(node.get("children"))


@pytest.mark.slow
@pytest.mark.regression
def test_the_export_writes_portable_ids_not_row_ids(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    #
    # Three axes, because the hazard this protects against only shows up
    # when there is more than one: a one-axis file archives the others.
    # Two axes carry an `import_id` and one does not, so the "id-free
    # export of a hand-built axis" case is covered by the same fixture.
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 237 Export",
        exam_description="Regression — export writes portable ids",
    )
    exam_id = db.get_exam_context_by_name(exam.exam_name).id

    axes = {}
    for order, (name, import_id) in enumerate(
        (("System", "axis-system"), ("Discipline", "axis-discipline"),
         ("Hand Built", None)),
        start=1,
    ):
        dimension_id = db.create_dimension(
            exam_id=exam_id, name=name, display_order=order, is_required=True)
        if import_id:
            db.execute(
                "UPDATE exam_dimensions SET import_id = ? WHERE id = ?",
                (import_id, dimension_id))
        axes[name] = dimension_id

    db.conn.commit()

    # One subject per axis; the System one carries a stable id and the
    # others do not, mirroring the dimension arrangement one level down.
    imported = db.create_subject_node(
        exam_context=exam.exam_name, name="Cardiovascular",
        level_type="System", dimension_id=axes["System"])
    db.execute("UPDATE subject_nodes SET import_id = 'subj-cv' WHERE id = ?",
               (imported.id,))
    db.create_subject_node(
        exam_context=exam.exam_name, name="Pathology",
        level_type="System", dimension_id=axes["Discipline"])
    db.create_subject_node(
        exam_context=exam.exam_name, name="By Hand",
        level_type="System", dimension_id=axes["Hand Built"])
    db.conn.commit()

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _wait_for(
        wimi_page,
        "!!(window.buildWholeExamExport && window.buildSingleTreeExport "
        "&& window.api)",
        what="the export builders to be loaded",
    )
    wimi_page.eval_js(_RUNNER)

    # ---- Act ---------------------------------------------------------
    result = wimi_page.eval_js(
        f"window.__e237({exam_id})", await_promise=True)
    whole = json.loads(result["whole"])
    single = json.loads(result["single"])
    row_ids = {str(i) for i in result["rowIds"]}

    # ---- Assert: the whole-exam file -------------------------------------
    assert [axis["name"] for axis in whole["dimensions"]] == [
        "System", "Discipline", "Hand Built"
    ], "a whole-exam export must declare EVERY axis, or re-importing archives one"

    by_name = {axis["name"]: axis for axis in whole["dimensions"]}
    assert by_name["System"]["id"] == "axis-system"
    assert by_name["Discipline"]["id"] == "axis-discipline"
    assert "id" not in by_name["Hand Built"], (
        "an axis with no import_id must export id-free, exactly as a "
        "hand-built subject tree does"
    )

    # The row ids must appear nowhere as an identifier. Checked against the
    # actual ids this profile happened to allocate rather than a literal,
    # because the bug was writing whatever number the row had.
    for axis in whole["dimensions"]:
        assert str(axis.get("id", "")) not in row_ids, (
            f'axis {axis["name"]!r} exported a database row id as its id'
        )

    # ---- Assert: the per-dimension file ---------------------------------
    #
    # An absence, and the one that matters most: a single-tree file carrying
    # a `dimensions` list would archive the other two axes on re-import.
    assert "dimensions" not in single, (
        "a per-dimension export declared a dimensions list, which on "
        "re-import would archive every axis it did not mention"
    )
    metadata = single["_metadata"]
    assert metadata["dimension_name"] == "System"
    assert metadata.get("dimension_import_id") == "axis-system"
    assert "dimension_id" not in metadata, (
        "the raw exam_dimensions.id is back in _metadata (#237)"
    )

    # ---- Assert: subjects follow the same rule (#67, never asserted before)
    subjects = list(_walk(by_name["System"]["root_nodes"]))
    assert [s["name"] for s in subjects] == ["Cardiovascular"]
    assert subjects[0]["id"] == "subj-cv"
    assert subjects[0]["id"] != imported.id

    hand_built = list(_walk(by_name["Hand Built"]["root_nodes"]))
    assert [s["name"] for s in hand_built] == ["By Hand"]
    assert "id" not in hand_built[0], (
        "a subject with no import_id exported one anyway (#67)"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_export_all_is_offered_only_when_the_exam_has_dimensions(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """A whole-exam file means nothing for an exam with no dimensions.

    The two exports write files that mean different things, so they are two
    buttons rather than one button with a mode — and the second one is hidden
    where it would produce a file describing an exam structure that does not
    exist.
    """
    db = wimi_session.user.db

    plain = db.create_exam_context(
        exam_name="Issue 237 Plain", exam_description="no dimensions")
    plain_id = db.get_exam_context_by_name(plain.exam_name).id

    wimi_page.goto("tree-editor", query={"exam_id": plain_id})
    _wait_for(wimi_page, "!!document.getElementById('btn-export')",
              what="the tree editor toolbar")
    wimi_page.wait_for_timeout(500)

    assert wimi_page.eval_js(
        "document.getElementById('btn-export-whole-exam')"
        ".classList.contains('hidden')"
    ) is True, "Export all was offered for an exam with no dimensions"

    dimensional = db.create_exam_context(
        exam_name="Issue 237 Dimensional", exam_description="two axes")
    dimensional_id = db.get_exam_context_by_name(dimensional.exam_name).id
    for order, name in enumerate(("System", "Task"), start=1):
        db.create_dimension(exam_id=dimensional_id, name=name,
                            display_order=order, is_required=True)
    db.conn.commit()

    wimi_page.goto("tree-editor", query={"exam_id": dimensional_id})
    _wait_for(
        wimi_page,
        "!!document.getElementById('btn-export-whole-exam') && "
        "!document.getElementById('dimension-selector')"
        ".classList.contains('hidden')",
        what="the dimension selector to appear",
    )

    assert wimi_page.eval_js(
        "document.getElementById('btn-export-whole-exam')"
        ".classList.contains('hidden')"
    ) is False, "Export all was hidden for a multi-dimensional exam"
