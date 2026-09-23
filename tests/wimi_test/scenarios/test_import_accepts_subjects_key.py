"""Regression: both subject-tree import entry points accept both keys.

Issue #61 — "a file using the documented ``subjects`` key is rejected by
the tree editor but accepted by the import panel".

    ``rules.txt`` — the import spec given to users — documents the
    top-level shape as ``{ exam_context, subjects[] }``. [...] So a file
    written exactly to spec imports through one UI and fails with a
    format error in the other.

``tree_editor.js`` threw *"Invalid file format: missing root_nodes
array"*; ``import_export.js`` accepted the file and rewrote the key
itself; the bridge slot read only ``root_nodes``, so it depended
entirely on the caller having normalised. The fix normalises in the
slot — the one place both entry points converge — and gives the two UI
handlers a single shared reader (``api.getImportRootNodes``) instead of
one rewriting and one rejecting.

Four combinations: {tree editor handler, import panel handler} x
{``root_nodes``, ``subjects``}. Each writes a differently named subject
so the database can say exactly which combination got through. Both
handlers are reached by name rather than through a file picker, because
``import_export.js`` overwrites ``window.handleImportFile`` at load
time and the tree editor's own handler is only reachable through the
reference the override stashed.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_COMBINATIONS = [
    ("editor", "root_nodes", "Editor RootNodes"),
    ("editor", "subjects", "Editor Subjects"),
    ("panel", "root_nodes", "Panel RootNodes"),
    ("panel", "subjects", "Panel Subjects"),
]

# Drives whichever handler is asked for with a synthetic change event,
# and reports back anything the handler surfaced as a failure. The
# handlers swallow their own errors into a toast, so the toast is the
# only in-page evidence that a file was rejected. ``Toast`` on this page
# is a top-level ``const`` in tree_editor.js — a global *lexical*
# binding, so it is reachable by bare name but is not a window property.
_RUNNER = """
window.__i61 = async function (which, key, name) {
    window.confirm = () => true;
    const report = { toasts: [], validation: [], preview: false };
    const realError = Toast.error;
    Toast.error = (title, msg) => { report.toasts.push(title + ': ' + msg); };
    try {
        const payload = {};
        payload[key] = [{ name: name, level_type: 'Topic' }];
        const file = new File([JSON.stringify(payload)], 'i61.json',
                              { type: 'application/json' });
        const evt = { target: { files: [file], value: 'i61.json' } };
        if (which === 'editor') {
            await _originalHandleImportFile(evt);
        } else {
            await window.handleImportFileEnhanced(evt);
            report.validation = (window.ImportExportState.validationErrors || [])
                .map(e => e.message);
            const modal = document.getElementById('import-preview-modal');
            report.preview = !!modal && modal.classList.contains('active');
            if (report.preview) {
                await window.executeImport();
            }
        }
    } finally {
        Toast.error = realError;
    }
    return report;
};
true
"""


def _wait_for(page: WimiPage, expression: str, *, what: str, tries: int = 50) -> None:
    for _ in range(tries):
        if page.eval_js(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}: {expression}")


@pytest.mark.slow
@pytest.mark.regression
def test_both_import_paths_accept_both_top_level_keys(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 61 Import Keys",
        exam_description="Regression — root_nodes and subjects both import",
    )
    exam_id = db.get_exam_context_by_name(exam.exam_name).id

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _wait_for(
        wimi_page,
        "!!(window.handleImportFileEnhanced && typeof Toast === 'object' "
        "&& typeof _originalHandleImportFile === 'function')",
        what="both import handlers to be loaded",
    )
    wimi_page.eval_js(_RUNNER)

    # ---- Act + Assert: four combinations ------------------------------
    #
    # Each combination is checked the moment it lands, not at the end.
    # Import became a *merge* in issue #67: a file that does not list a
    # subject removes it, so the next combination's one-subject file
    # retires the previous combination's subject. Four imports into one
    # exam therefore leave one subject behind, and only a per-import
    # check can still tell all four apart.
    failures = []
    for which, key, name in _COMBINATIONS:
        report = wimi_page.eval_js(
            f"window.__i61('{which}', '{key}', '{name}')", await_promise=True
        )
        landed = db.fetchone(
            "SELECT COUNT(*) AS n FROM subject_nodes "
            "WHERE exam_context = ? AND name = ? AND status = 'active'",
            (exam.exam_name, name),
        )["n"]
        # Exactly one: a handler that normalised and then re-normalised
        # would write the subject twice, which is what `== 1` catches
        # and `is not None` would not.
        if report["toasts"] or report["validation"] or landed != 1:
            failures.append(
                f"{which} handler + {key!r} key: rows={landed} (expected 1), "
                f"toasts={report['toasts']}, validation={report['validation']}"
            )

    assert not failures, (
        "an import file was rejected, dropped or duplicated:\n  "
        + "\n  ".join(failures)
    )

    # And the merge left exactly the last file's tree standing — stated
    # positively, so a change back to append-on-import fails here rather
    # than quietly passing.
    surviving = [
        row["name"] for row in db.fetchall(
            "SELECT name FROM subject_nodes WHERE exam_context = ? "
            "AND status = 'active'",
            (exam.exam_name,),
        )
    ]
    assert surviving == [_COMBINATIONS[-1][2]], (
        f"after four one-subject imports the tree holds {surviving}; "
        f"a merge leaves only the last file's subject (issue #67)"
    )


# ---------------------------------------------------------------------
# Bug context
# ---------------------------------------------------------------------
# Before the fix the "editor + subjects" combination raised "Invalid
# file format: missing root_nodes array" (captured here as a toast),
# and the bridge slot on its own imported nothing at all from a
# `subjects` file — a silent success with imported_count 0, which
# `tests/app/test_bridge_hierarchy_import.py` pins directly. The other
# three combinations passed before the fix and must keep passing:
# `root_nodes` is still the canonical key and export still writes it.
