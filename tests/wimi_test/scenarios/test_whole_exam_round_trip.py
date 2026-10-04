"""Regression: export the whole exam, import it back, change nothing (#66 Wave 4).

The **verification** half of `#66 Wave 4 — preview, entry point and
verification`. Every other piece of this feature was tested in isolation:
#241 the planner and apply, #237 the export, #252 the preview. This is the one
test that makes them agree with each other.

A round trip is the strongest single assertion available here, because it is
the only one that fails if **any** of the three has an inconsistent idea of
what the format means:

* the export must write each dimension's stable `id`, or the re-import matches
  by name and a renamed axis would be a remove-plus-add;
* the export must write **every** axis, or the re-import archives the ones it
  omitted -- #241 makes the file authoritative about exam structure, so a file
  is a statement that these are *all* the dimensions;
* the planner must match every axis and every subject it wrote out, or the
  re-import reports additions and removals for a file nothing has edited;
* the apply must be genuinely idempotent, not merely non-destructive.

**What makes this a real test and not a tautology** is that it goes through the
same public surface a student does -- `buildWholeExamExport` for the file, then
the `importSubjectHierarchy` bridge slot -- rather than handing the planner its
own output. And it asserts on the *database*, not on the report: row ids are
compared before and after, so a re-import that archived a subject and created
an identical one would fail even though every count read zero.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_RUNNER = """
window.__rt66 = async function (examContextId) {
    const dimensions = await window.api.getDimensions(examContextId);
    const axes = [];
    for (const dimension of dimensions) {
        axes.push({
            dimension,
            hierarchyData: await window.api.getDimensionHierarchy(
                examContextId, dimension.id),
        });
    }
    const file = window.buildWholeExamExport({
        axes,
        examContext: {exam_name: 'Round Trip'},
        examContextId,
        hierarchyLevels: [],
    });
    const result = await window.api.importSubjectHierarchy(
        examContextId, JSON.stringify(file));
    return {file: JSON.stringify(file), counts: result.counts,
            warnings: result.warnings || []};
};
true
"""


def _snapshot(db, exam_name):
    """Every active subject and dimension, by id, with what identifies it."""
    subjects = {
        row['id']: (row['name'], row['dimension_id'], row['import_id'],
                    row['exam_weight_low'], row['exam_weight_high'])
        for row in db.fetchall(
            "SELECT id, name, dimension_id, import_id, exam_weight_low, "
            "exam_weight_high FROM subject_nodes "
            "WHERE exam_context = ? AND status = 'active'", (exam_name,))
    }
    return subjects


def _axes(db, exam_id):
    return {
        row['id']: (row['name'], row['display_order'], bool(row['is_required']),
                    bool(row['allow_multiple']), row['import_id'])
        for row in db.get_exam_dimensions(exam_id)
    }


@pytest.mark.slow
@pytest.mark.regression
def test_export_all_then_import_changes_nothing(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange: three axes, one carrying a stable id, one hand-built ----
    #
    # The mixture is deliberate. An axis with an `import_id` round-trips by id;
    # one without has to round-trip by name, and both must be no-ops. A weight
    # band is included because #250 showed the band path is the one that gets
    # dropped.
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Round Trip", exam_description="#66 Wave 4")
    exam_id = db.get_exam_context_by_name("Round Trip").id

    axes = {}
    for order, (name, import_id) in enumerate(
        (("System", "ax-sys"), ("Discipline", "ax-disc"), ("Hand Built", None)),
        start=1,
    ):
        dim = db.create_dimension(exam_id=exam_id, name=name,
                                  display_order=order, is_required=(order != 3),
                                  allow_multiple=(order == 2))
        if import_id:
            db.execute("UPDATE exam_dimensions SET import_id = ? WHERE id = ?",
                       (import_id, dim))
        axes[name] = dim

    parent = db.create_subject_node(
        exam_context="Round Trip", name="Cardiovascular", level_type="System",
        dimension_id=axes["System"], exam_weight_low=8, exam_weight_high=12)
    db.execute("UPDATE subject_nodes SET import_id = 'sub-cv' WHERE id = ?",
               (parent.id,))
    db.create_subject_node(
        exam_context="Round Trip", name="Heart Failure", level_type="Topic",
        parent_id=parent.id, dimension_id=axes["System"])
    db.create_subject_node(
        exam_context="Round Trip", name="Pathology", level_type="System",
        dimension_id=axes["Discipline"], exam_weight_low=20, exam_weight_high=20)
    db.create_subject_node(
        exam_context="Round Trip", name="By Hand", level_type="System",
        dimension_id=axes["Hand Built"])
    db.conn.commit()

    before_subjects = _snapshot(db, "Round Trip")
    before_axes = _axes(db, exam_id)
    assert len(before_subjects) == 4
    assert len(before_axes) == 3

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    for _ in range(80):
        if wimi_page.eval_js("!!(window.buildWholeExamExport && window.api)"):
            wimi_page.eval_js(_RUNNER)
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError("the export builders never loaded")

    # ---- Act: export the whole exam, then import that exact file ----
    out = wimi_page.eval_js(f"window.__rt66({exam_id})", await_promise=True)
    file_obj = json.loads(out["file"])

    # The file has to declare every axis, or the import archives the rest.
    assert [a["name"] for a in file_obj["dimensions"]] == [
        "System", "Discipline", "Hand Built"]

    # ---- Assert: the import reports a no-op ----
    counts = out["counts"]
    assert counts["dimensions_added"] == 0, counts
    assert counts["dimensions_removed"] == 0, counts
    assert counts["dimensions_updated"] == 0, counts
    assert counts["dimensions_unchanged"] == 3, counts
    assert counts["added"] == 0, counts
    assert counts["removed"] == 0, counts
    assert counts["updated"] == 0, counts
    assert counts["unchanged"] == 4, counts

    # Every warning must be a **coverage** warning, and nothing else.
    #
    # My first version of this asserted no warnings at all and failed, and the
    # test was wrong rather than the code: this fixture's weights really do not
    # span 100% (8-12% in one axis, 20% in another), so #64's coverage warning
    # is the documented, correct behaviour -- surfaced, never corrected. The
    # band is kept in the fixture on purpose, because #250 showed the band path
    # is the one that gets dropped.
    #
    # What a round trip must not introduce is a warning about *structure* -- a
    # refused move, an alias that would not write. Those would mean the export
    # wrote something the importer cannot read back.
    non_coverage = [w for w in out["warnings"] if "does not span 100%" not in w]
    assert non_coverage == [], (
        f'the round trip produced warnings that are not about coverage: '
        f'{non_coverage}'
    )

    # ---- Assert: and the database agrees, by row id ----
    #
    # The counts alone would pass for a re-import that archived a subject and
    # created an identical one. Comparing ids is what rules that out.
    assert _snapshot(db, "Round Trip") == before_subjects
    assert _axes(db, exam_id) == before_axes


@pytest.mark.slow
@pytest.mark.regression
def test_a_renamed_axis_round_trips_by_id_not_by_name(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The reason dimensions needed an `import_id` at all (#66 2.3).

    Export, rename the axis in the file, import: the dimension must be the
    same row afterwards. Without the id this is an archive plus a create, and
    the archive takes every subject in the axis with it (#210).
    """
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Round Trip Rename", exam_description="x")
    exam_id = db.get_exam_context_by_name("Round Trip Rename").id
    dim = db.create_dimension(exam_id=exam_id, name="System", display_order=1,
                              is_required=True)
    db.execute("UPDATE exam_dimensions SET import_id = 'ax-sys' WHERE id = ?",
               (dim,))
    subject = db.create_subject_node(
        exam_context="Round Trip Rename", name="Cardiovascular",
        level_type="System", dimension_id=dim)
    db.conn.commit()

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    for _ in range(80):
        if wimi_page.eval_js("!!(window.buildWholeExamExport && window.api)"):
            wimi_page.eval_js(_RUNNER)
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError("the export builders never loaded")

    out = wimi_page.eval_js(f"window.__rt66({exam_id})", await_promise=True)
    file_obj = json.loads(out["file"])
    assert file_obj["dimensions"][0]["id"] == "ax-sys"

    # Rename the axis in the file and import it again.
    file_obj["dimensions"][0]["name"] = "Organ System"
    renamed = wimi_page.eval_js(
        f"window.api.importSubjectHierarchy({exam_id}, "
        f"{json.dumps(json.dumps(file_obj))})", await_promise=True)

    assert renamed["counts"]["dimensions_added"] == 0, renamed["counts"]
    assert renamed["counts"]["dimensions_removed"] == 0, renamed["counts"]
    assert renamed["counts"]["dimensions_updated"] == 1, renamed["counts"]

    after = db.get_exam_dimensions(exam_id)
    assert len(after) == 1
    assert after[0]["id"] == dim, "the dimension was replaced, not renamed"
    assert after[0]["name"] == "Organ System"
    assert db.fetchone(
        "SELECT status, dimension_id FROM subject_nodes WHERE id = ?",
        (subject.id,))["status"] == "active", "the subject was archived"
