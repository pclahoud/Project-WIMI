"""Regression: a whole-exam import is announced as exam-wide, not dimension-scoped (#66 Wave 4).

`docs/planning/WHOLE_EXAM_IMPORT.md` §7 puts the entry point in this wave and
says why it is not merely a button: *"the copy has to say what will happen to
axes they did not mention"*, and it must be **an exam-level action rather than
a button inside one dimension's tree view**.

Functionally a whole-exam file already imports through the tree editor's
Import button -- the bridge dispatches on the file (#241) and the preview
reports the axis level (#252). What was wrong is the *framing*: the modal's
dimension notice keys on `TreeState.currentDimension` and never on the file,
so a file that creates, renames and archives dimensions across the whole exam
was announced as

    Importing into dimension: System

which is false in the most expensive direction. A student reading it would
believe the blast radius is one axis when it is all of them.

These tests drive the real handler with a real file, so they assert what the
modal actually says rather than what the code appears to say.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_RUNNER = """
window.__e66 = async function (file) {
    const f = new File([file], 'w.json', {type: 'application/json'});
    await window.handleImportFileEnhanced({target: {files: [f], value: 'w.json'}});
    const notice = document.getElementById('import-dimension-notice');
    return {
        noticeHidden: !notice || notice.classList.contains('hidden'),
        noticeText: notice ? notice.textContent.replace(/\\s+/g, ' ').trim() : null,
        nodeCount: document.getElementById('import-node-count').textContent,
    };
};
true
"""


@pytest.fixture
def modal(wimi_session: WimiTestSession, wimi_page: WimiPage):
    db = wimi_session.user.db
    db.create_exam_context(exam_name="Entry 66", exam_description="entry point")
    exam_id = db.get_exam_context_by_name("Entry 66").id
    axes = {}
    for order, name in enumerate(("System", "Discipline"), start=1):
        axes[name] = db.create_dimension(exam_id=exam_id, name=name,
                                         display_order=order, is_required=True)
    for name, dim in axes.items():
        db.create_subject_node(exam_context="Entry 66", name=f"In {name}",
                              level_type="System", dimension_id=dim)
    db.conn.commit()

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    for _ in range(80):
        if wimi_page.eval_js(
                "!!(window.handleImportFileEnhanced && window.TreeState "
                "&& window.TreeState.currentDimensionId)"):
            wimi_page.eval_js(_RUNNER)
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError("the tree editor never reached dimension mode")

    def run(file_obj):
        return wimi_page.eval_js(
            f"window.__e66({json.dumps(json.dumps(file_obj))})",
            await_promise=True)

    return run


@pytest.mark.slow
@pytest.mark.regression
def test_a_whole_exam_file_is_not_announced_as_one_dimension(modal):
    """The headline. This said "Importing into dimension: System"."""
    out = modal({"dimensions": [
        {"name": "System", "display_order": 1, "root_nodes": [{"name": "In System"}]},
        {"name": "Discipline", "display_order": 2, "root_nodes": [{"name": "In Discipline"}]},
    ]})

    assert "Importing into dimension" not in (out["noticeText"] or ""), (
        f'a whole-exam file was announced as dimension-scoped: '
        f'{out["noticeText"]!r}'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_it_says_the_file_covers_the_whole_exam(modal):
    """Saying what it is NOT is not enough; the student needs the scope."""
    out = modal({"dimensions": [
        {"name": "System", "display_order": 1, "root_nodes": [{"name": "In System"}]},
    ]})

    assert out["noticeHidden"] is False, "the notice was hidden entirely"
    text = out["noticeText"] or ""
    assert "every dimension" in text or "whole exam" in text, text


@pytest.mark.slow
@pytest.mark.regression
def test_a_single_tree_file_is_still_announced_as_dimension_scoped(modal):
    """Negative control. A file with `root_nodes` really does import into the
    dimension on screen, and that notice is the only thing that says so."""
    out = modal({"root_nodes": [{"name": "In System"}]})

    assert out["noticeHidden"] is False
    assert "Importing into dimension" in (out["noticeText"] or "")
    assert "System" in (out["noticeText"] or "")
