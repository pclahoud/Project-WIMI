"""Regression: the import preview names the file's exam, and only when it differs.

Issue #103 — "Import preview says the file was written for
``[object Object]``".

The published import format spells ``exam_context`` as an *object*
(``{"name": ..., "description": ..., "source": {...}}``), which is what
every file written to the guide carries — the guide's own worked
examples included. ``_read_import_request`` handed the whole dict on as
``file_exam_name``; ``_import_preview_payload`` then compared it as a
string, so ``file_exam_matches`` was ``False`` for *every* such file and
the modal rendered ``String(dict)``:

    ℹ️ This file was written for **[object Object]**; you are importing
    it into **USMLE Step 1**.

Which makes the one case the note exists to catch — a file merged into
the wrong tree — indistinguishable from the normal case.

The bridge half is pinned by ``tests/app/test_bridge_import_preview.py``.
What only a rendered assertion can prove is what the student reads, and
this scenario is built so the two halves are each other's control: the
same handler, the same modal, two files differing **only** in the name
inside ``exam_context``. The matching file must render no note at all;
the mismatched one must render the note *and* the name in it. Neither
assertion can pass by accident while the bug is present — with the bug,
the first fails; and a "fix" that simply dropped the note would fail the
second.
"""

from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


_EXAM_NAME = "Issue 103 Import Exam"

# Shaped like the guide's Example 1: an `exam_context` object, then
# `root_nodes`. The name is filled in per case.
def _guide_shaped_file(exam_name: str) -> dict:
    return {
        "exam_context": {
            "name": exam_name,
            "description": "Written to the published import format",
            "source": {"title": "Content Outline", "year": 2025},
        },
        "root_nodes": [
            {
                "id": "1",
                "name": "Cardiovascular",
                "level_type": "System",
                "children": [
                    {"id": "1.1", "name": "Arrhythmia", "level_type": "Topic"},
                ],
            }
        ],
    }


# Feeds the real file-input handler a synthetic change event, the way
# `test_import_preview_shows_merge_plan.py` does — `handleImportFileEnhanced`
# is what the page's file input actually reaches.
_RUNNER = """
window.__i103 = async function (payload) {
    window.hideImportPreviewModal();
    const file = new File([JSON.stringify(payload)], 'outline.json',
                          { type: 'application/json' });
    await window.handleImportFileEnhanced(
        { target: { files: [file], value: 'outline.json' } }
    );
    const modal = document.getElementById('import-preview-modal');
    return !!modal && modal.classList.contains('active');
};
true
"""


def _wait_for(page: WimiPage, expression: str, *, what: str, tries: int = 60) -> None:
    for _ in range(tries):
        if page.eval_js(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}: {expression}")


def _open_preview(page: WimiPage, payload: dict) -> str:
    """Hand a file to the real handler and return the rendered plan text."""
    opened = page.eval_js(
        f"window.__i103({json.dumps(payload)})", await_promise=True
    )
    assert opened is True, "the import preview modal did not open"
    _wait_for(
        page,
        "!!document.querySelector('#import-merge-plan .import-plan-stats')",
        what="the merge plan to render in the modal",
    )
    return page.eval_js("document.getElementById('import-merge-plan').innerText")


@pytest.mark.slow
@pytest.mark.regression
def test_import_preview_names_the_file_exam_only_when_it_differs(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name=_EXAM_NAME,
        exam_description="Regression — issue #103",
    )
    exam_id = db.get_exam_context_by_name(exam.exam_name).id

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _wait_for(
        wimi_page,
        "!!(window.api && window.api.importSubjectHierarchy "
        "&& window.handleImportFileEnhanced && window.hideImportPreviewModal)",
        what="the tree editor's import layer to come up",
    )
    wimi_page.eval_js(_RUNNER)

    # ---- The normal case: the file names this very exam ---------------
    same_text = _open_preview(wimi_page, _guide_shaped_file(_EXAM_NAME))

    assert "[object Object]" not in same_text, (
        "the preview rendered the exam_context object instead of its name: "
        f"{same_text!r}"
    )
    assert "written for" not in same_text.lower(), (
        "a file naming the exam it is being imported into still claimed to "
        f"be written for another one: {same_text!r}"
    )

    # ---- The case the note exists for: a different exam ---------------
    other_text = _open_preview(wimi_page, _guide_shaped_file("NBME Shelf: Medicine"))

    assert "[object Object]" not in other_text, other_text
    assert "written for" in other_text.lower(), (
        "a file written for a different exam produced no note at all — the "
        f"note has gone silent rather than got accurate: {other_text!r}"
    )
    assert "NBME Shelf: Medicine" in other_text, (
        f"the note did not name the file's exam: {other_text!r}"
    )
    assert _EXAM_NAME in other_text, (
        f"the note did not name the exam being imported into: {other_text!r}"
    )

    # A bare string is still accepted — files may spell it either way.
    bare = dict(_guide_shaped_file(_EXAM_NAME), exam_context=_EXAM_NAME)
    assert "written for" not in _open_preview(wimi_page, bare).lower()

    # Nothing has been imported: every case above stopped at the preview.
    assert db.fetchone(
        "SELECT COUNT(*) AS c FROM subject_nodes WHERE exam_context = ?",
        (exam.exam_name,),
    )["c"] == 0, "the preview wrote rows"
