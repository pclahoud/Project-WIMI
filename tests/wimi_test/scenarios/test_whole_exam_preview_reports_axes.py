"""Regression: the import preview reports what happens to dimensions (#252).

Issue #252 — the preview showed only subject-level counts, so a whole-exam file
that archived two dimensions and every subject tree inside them told the student
**"0 removed"**. Measured on `master` at `767dc2b`:

    AXES TO GO  : ['Discipline', 'Task']
    COUNTS      : {"dimensions_removed": 2, ..., "removed": 0, ...}
    WHAT THE STUDENT SEES:
        0 added 0 updated 0 removed 1 unchanged

`counts.removed` is the subject figure for the axes the file *declares*.
Subjects removed by a dimension archive go through `archive_dimension`'s
cascade instead, so they are not in it — the one number a student reads to
answer "will this delete anything" said zero when the answer was two whole
axes. Under #210 that cascade takes the tree.

**Updated when #37 landed.** While restore was open the panel said the archive
"cannot be undone", and the test below pinned that sentence. It is now false:
the tree editor's Archived panel restores a dimension archive as one event. A
test that kept pinning the old wording would have held a true-when-written
claim in place after it stopped being true, which is the exact failure mode the
rest of this file exists to catch one layer up.

**What these tests assert is the presence of specific claims, not layout.** The
panel is HTML built by string concatenation; asserting on markup would break on
any styling change while the information was still there. So each test reads
`textContent` and looks for the fact the student needs: the count, the names,
and — for the two cases that read as "nothing will happen" — that the file is
*not* interpreted destructively.

The axis table is checked for **per-axis coverage bands and the absence of a
combined one**, because #64's rule survives into the UI: the axes are
overlapping partitions of one item pool, so one total would describe nothing.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_RUNNER = """
window.__w252 = async function (examId, file) {
    const plan = await window.api.previewSubjectHierarchyImport(examId, file);
    const host = document.createElement('div');
    host.innerHTML = window.renderImportMergePlan(plan);
    const cell = (row, i) => row.children[i] ? row.children[i].textContent.trim() : null;
    const rows = Array.from(host.querySelectorAll('.import-axis-table tbody tr'))
        .map(r => ({name: cell(r, 0), action: cell(r, 1), added: cell(r, 2),
                    updated: cell(r, 3), removed: cell(r, 4), coverage: cell(r, 5)}));
    return {
        text: host.textContent.replace(/\\s+/g, ' ').trim(),
        hasTable: !!host.querySelector('.import-axis-table'),
        axisRows: rows,
        stats: Array.from(host.querySelectorAll('.import-plan-stat')).map(
            el => el.textContent.replace(/\\s+/g, ' ').trim()),
        keptLinks: Array.from(host.querySelectorAll('.import-plan-kept-list li'))
            .map(el => el.textContent.replace(/\\s+/g, ' ').trim()),
        planCounts: plan.counts,
    };
};
true
"""


@pytest.fixture
def preview(wimi_session: WimiTestSession, wimi_page: WimiPage):
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Issue 252", exam_description="axis preview")
    exam_id = db.get_exam_context_by_name("Issue 252").id

    axes = {}
    for order, name in enumerate(("System", "Discipline", "Task"), start=1):
        axes[name] = db.create_dimension(exam_id=exam_id, name=name,
                                         display_order=order, is_required=True)
    db.create_subject_node(exam_context="Issue 252", name="Cardiovascular",
                          level_type="System", dimension_id=axes["System"])
    for name in ("Discipline", "Task"):
        db.create_subject_node(exam_context="Issue 252", name=f"In {name}",
                              level_type="System", dimension_id=axes[name])
    db.conn.commit()

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    for _ in range(60):
        if wimi_page.eval_js("!!(window.renderImportMergePlan && window.api)"):
            wimi_page.eval_js(_RUNNER)
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError("the preview renderer never loaded")

    def run(file_obj):
        return wimi_page.eval_js(
            f"window.__w252({exam_id}, {json.dumps(json.dumps(file_obj))})",
            await_promise=True)

    run.exam_id = exam_id
    run.db = db
    run.axes = axes
    return run


def _one_axis_file():
    return {"dimensions": [
        {"name": "System", "display_order": 1,
         "root_nodes": [{"name": "Cardiovascular"}]},
    ]}


@pytest.mark.slow
@pytest.mark.regression
def test_an_archived_dimension_is_reported_with_its_subject_count(preview):
    """The headline. This panel said "0 removed" before the fix."""
    out = preview(_one_axis_file())

    assert out["planCounts"]["dimensions_removed"] == 2
    assert "2 dimensions archived" in " ".join(out["stats"])
    assert "will be archived" in out["text"]
    assert "Discipline" in out["text"] and "Task" in out["text"]


@pytest.mark.slow
@pytest.mark.regression
def test_it_says_where_the_archive_can_be_undone(preview):
    """#210 cascades to the whole tree, so the student is told before confirming.

    This asserted "cannot be undone" until #37 landed the Archived panel. The
    warning still has to be loud -- the cascade takes whole trees -- but it now
    has to point at the way back rather than deny one exists. Telling a student
    an action is irreversible when it is not would talk them out of an import
    that is in fact safe, which is worse than the original omission.
    """
    out = preview(_one_axis_file())

    assert "undo" in out["text"].lower(), (
        f"the panel must say the archive is undoable; got {out['text']!r}"
    )
    assert "Archived subjects" in out["text"], (
        "and must name where -- a way back nobody can find is not a way back"
    )
    assert "cannot be undone" not in out["text"], (
        "restore exists now (#37); this claim is stale and would discourage a "
        "reversible import"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_it_says_how_to_keep_a_dimension(preview):
    """A warning with no way forward is half a warning."""
    out = preview(_one_axis_file())

    assert "add them to the file's" in out["text"]
    assert "dimensions" in out["text"]


@pytest.mark.slow
@pytest.mark.regression
def test_the_subject_figures_are_labelled_as_subjects(preview):
    """Two rows of numbers must not read as one.

    The axis row and the subject row both carry "added/updated/removed", and
    on a whole-exam file they are different quantities at different levels.
    """
    out = preview(_one_axis_file())
    stats = " ".join(out["stats"])

    assert "subjects removed" in stats or "subject removed" in stats
    assert "dimensions archived" in stats


@pytest.mark.slow
@pytest.mark.regression
def test_a_new_dimension_is_reported(preview):
    out = preview({"dimensions": [
        {"name": "System", "display_order": 1,
         "root_nodes": [{"name": "Cardiovascular"}]},
        {"name": "Discipline", "display_order": 2, "root_nodes": [{"name": "In Discipline"}]},
        {"name": "Task", "display_order": 3, "root_nodes": [{"name": "In Task"}]},
        {"name": "Brand New", "display_order": 4, "root_nodes": [{"name": "Fresh"}]},
    ]})

    assert "1 dimension added" in " ".join(out["stats"]), out["stats"]
    assert "Brand New" in out["text"]
    assert "will be archived" not in out["text"], (
        "a file listing every axis reported an archive"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_coverage_is_shown_per_axis_and_never_combined(preview):
    """#64 in the UI. The axes describe the same questions, so a total of
    their bands would describe nothing."""
    out = preview({"dimensions": [
        {"name": "System", "display_order": 1,
         "root_nodes": [{"name": "Cardiovascular", "weight": {"low": 40, "high": 80}}]},
        {"name": "Discipline", "display_order": 2,
         "root_nodes": [{"name": "In Discipline", "weight": {"low": 38, "high": 60}}]},
        {"name": "Task", "display_order": 3,
         "root_nodes": [{"name": "In Task", "weight": 10}]},
    ]})

    assert out["hasTable"]
    coverage = {r["name"]: r["coverage"] for r in out["axisRows"]}
    assert coverage["System"] == "40–80%"
    assert coverage["Discipline"] == "38–60%"
    assert coverage["Task"] == "10–10%"
    # 88-150% would be the combined band. It must appear nowhere.
    assert "88" not in out["text"] and "150" not in out["text"], (
        "a combined coverage figure reached the panel"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_an_axis_with_no_subjects_is_reported_as_changing_nothing(preview):
    """A misspelled `root_nodes` inside an axis (#67's hazard, one level up).

    It removes nothing, and the panel has to say so rather than showing a row
    of zeros that could equally mean "already up to date".
    """
    out = preview({"dimensions": [
        {"name": "System", "display_order": 1, "root_ndoes": [{"name": "Typo"}]},
        {"name": "Discipline", "display_order": 2, "root_nodes": [{"name": "In Discipline"}]},
        {"name": "Task", "display_order": 3, "root_nodes": [{"name": "In Task"}]},
    ]})

    assert "lists no subjects" in out["text"]
    assert "root_nodes" in out["text"], "the panel does not name the likely cause"


@pytest.mark.slow
@pytest.mark.regression
def test_an_empty_dimensions_list_says_it_changes_nothing(preview):
    """The most expensive way to misread a file: `"dimensions": []` must not be
    presented as, or acted on as, "remove every dimension"."""
    out = preview({"dimensions": []})

    assert "lists no dimensions" in out["text"]
    assert "not" in out["text"] and "remove every dimension" in out["text"]
    assert "will be archived" not in out["text"]


@pytest.mark.slow
@pytest.mark.regression
def test_a_kept_dimension_is_reported_with_its_entries(preview):
    """Decision 2.1: a dimension carrying entries is never removed, and the
    student is told which and why."""
    db, axes = preview.db, preview.axes
    node = db.fetchone(
        "SELECT id FROM subject_nodes WHERE dimension_id = ?", (axes["Task"],))
    cursor = db.execute(
        "INSERT INTO review_sessions (user_id, session_name, date_encountered, "
        "exam_context_id, total_questions, total_incorrect) "
        "VALUES (?, 'S', date('now'), ?, 1, 1)", (db.user_id, preview.exam_id))
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer) VALUES (?, 1, 'A', 'B')",
        (cursor.lastrowid,)).lastrowid
    db.execute("INSERT INTO entry_subject_mappings (question_entry_id, "
               "subject_node_id, mapping_type) VALUES (?, ?, 'primary')",
               (entry, node["id"]))
    db.conn.commit()

    out = preview(_one_axis_file())

    assert "1 dimension kept" in " ".join(out["stats"]), out["stats"]
    assert "kept because your entries are tagged inside" in out["text"]
    assert any("Task" in link for link in out["keptLinks"])


@pytest.mark.slow
@pytest.mark.regression
def test_a_single_tree_file_still_renders_the_old_panel(preview):
    """Negative control. Every file written today is a single tree, and the
    axis block must not appear for one."""
    out = preview({"root_nodes": [{"name": "Cardiovascular"}]})

    assert not out["hasTable"], "a single-tree file grew an axis table"
    stats = " ".join(out["stats"])
    assert "dimensions archived" not in stats
    assert "added" in stats and "subjects added" not in stats


@pytest.mark.slow
@pytest.mark.regression
def test_a_kept_subject_inside_a_declared_axis_is_listed(preview):
    """The second defect in #252, and it needed its own test.

    A *subject* kept because entries point at it lives on the axis that
    declares it, so the panel read `plan.kept_in_use` — a key only a
    single-tree payload has. `counts.kept_in_use` was non-zero while the list
    was `undefined`, so the student was told subjects were kept and shown
    **none of them**.

    This case is not the same as a kept *dimension*: here the axis is in the
    file and one of its subjects is not. Mutating the pooling killed nothing
    until this existed, which is how I found out the earlier test was covering
    the other level.
    """
    db, axes = preview.db, preview.axes
    dropped = db.create_subject_node(
        exam_context="Issue 252", name="Dropped But Tagged",
        level_type="System", dimension_id=axes["System"])
    cursor = db.execute(
        "INSERT INTO review_sessions (user_id, session_name, date_encountered, "
        "exam_context_id, total_questions, total_incorrect) "
        "VALUES (?, 'S', date('now'), ?, 1, 1)", (db.user_id, preview.exam_id))
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer) VALUES (?, 1, 'A', 'B')",
        (cursor.lastrowid,)).lastrowid
    db.execute("INSERT INTO entry_subject_mappings (question_entry_id, "
               "subject_node_id, mapping_type) VALUES (?, ?, 'primary')",
               (entry, dropped.id))
    db.conn.commit()

    # System is declared, but no longer lists "Dropped But Tagged".
    out = preview({"dimensions": [
        {"name": "System", "display_order": 1,
         "root_nodes": [{"name": "Cardiovascular"}]},
        {"name": "Discipline", "display_order": 2,
         "root_nodes": [{"name": "In Discipline"}]},
        {"name": "Task", "display_order": 3, "root_nodes": [{"name": "In Task"}]},
    ]})

    assert out["planCounts"]["kept_in_use"] >= 1
    assert "because your entries are tagged to" in out["text"]
    assert any("Dropped But Tagged" in link for link in out["keptLinks"]), (
        f'the kept subject was counted but not listed: {out["keptLinks"]}'
    )
