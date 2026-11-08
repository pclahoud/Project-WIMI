"""Arrange and probe for #899: the tree editor follows a change in axis count.

Seeds through the user database, drives the import exactly as the file input
does (``handleImportFileEnhanced`` then ``executeImport``), and reads the
page's mode back as one dict so each test asserts the whole state at once.

``TreeState`` is assigned to ``window`` at the bottom of tree_editor.js, so it
is reachable from a scenario; ``window.api`` is the API global (not
``_wimiApi``, which ``_loader.js`` deletes).
"""
from __future__ import annotations

import json
from typing import Any, Callable

from wimi_test.page import WimiPage

STATE = """
(() => {
    const sel = document.getElementById('dimension-selector');
    const exp = document.getElementById('btn-export-whole-exam');
    const tabs = Array.from(document.querySelectorAll('#dimension-tabs .dimension-tab'));
    const active = tabs.find(t => t.classList.contains('active'));
    return {
        uses: window.TreeState.usesDimensions,
        current: window.TreeState.currentDimensionId,
        selectorShown: !!sel && !sel.classList.contains('hidden'),
        exportAllShown: !!exp && !exp.classList.contains('hidden'),
        tabs: sel && !sel.classList.contains('hidden')
            ? tabs.map(t => t.querySelector('.dimension-tab-name').textContent.trim())
            : [],
        activeTab: active
            ? active.querySelector('.dimension-tab-name').textContent.trim() : null,
        rows: Array.from(document.querySelectorAll('.tree-node-name'))
            .map(el => el.textContent.trim()).sort(),
    };
})()
"""

READY = ("!!window.TreeState && window.TreeState.isPageReady"
         " && document.querySelectorAll('[data-page-gated][inert]').length === 0")


def poll(page: WimiPage, read: Callable[[], Any], ok: Callable[[Any], bool],
         *, timeout_ms: int = 15000) -> Any:
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception as exc:  # a navigation in flight
            last = exc
        if not isinstance(last, Exception) and ok(last):
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def state(page: WimiPage) -> dict:
    return page.eval_js(STATE)


def wait_state(page: WimiPage, ok: Callable[[dict], bool]) -> dict:
    """Poll the mode until ``ok`` holds; return the last reading either way,
    so the caller's assertion reports what the page actually showed."""
    return poll(page, lambda: state(page), ok)


def open_tree(page: WimiPage, exam_id: int) -> None:
    page.goto("tree-editor", query={"exam_id": exam_id})
    if poll(page, lambda: page.eval_js(READY), bool) is not True:
        raise AssertionError("the tree editor never released its gate")


def reload_tree(page: WimiPage, exam_id: int) -> None:
    """The positive control: a fresh load runs the startup mode logic.

    A second goto to the same page can return before the new document
    commits, so the old document is marked and the mark must vanish."""
    page.eval_js("window.__w899_old_document = true")
    page.goto("tree-editor", query={"exam_id": exam_id})
    gone = poll(page, lambda: page.eval_js(
        "typeof window.__w899_old_document === 'undefined'"), bool)
    assert gone is True, "the reload never replaced the document"
    if poll(page, lambda: page.eval_js(READY), bool) is not True:
        raise AssertionError("the reloaded tree editor never released its gate")


FIRST_AXIS_DIALOG = '[data-testid="first-axis-dialog"]'


def start_import(page: WimiPage, file_obj: dict) -> None:
    """Open the preview and press Confirm, without waiting for the import.

    ``executeImport`` may stop to ask the first-axis question (#605 Wave 2),
    so it is started rather than awaited; ``window.__importDone`` turns true
    when it returns, whether it imported or the student went back."""
    text = json.dumps(json.dumps(file_obj))
    page.eval_js(f"""
        (async () => {{
            const f = new File([{text}], 'w899.json', {{type: 'application/json'}});
            await window.handleImportFileEnhanced({{target: {{files: [f], value: 'w899.json'}}}});
            window.__importDone = false;
            window.executeImport().then(() => {{ window.__importDone = true; }});
            return true;
        }})()
    """, await_promise=True)


def wait_for_first_axis_dialog(page: WimiPage) -> bool:
    return poll(page, lambda: page.eval_js(
        f"!!document.querySelector({json.dumps(FIRST_AXIS_DIALOG)})"), bool) is True


def wait_import_done(page: WimiPage) -> None:
    done = poll(page, lambda: page.eval_js("window.__importDone === true"), bool)
    assert done is True, (
        "executeImport never returned -- a first-axis dialog left unanswered?")


def import_file(page: WimiPage, file_obj: dict, *,
                first_axis: str | None = None) -> None:
    """Import through the same two handlers the file input and Confirm reach.

    ``first_axis`` answers the #605 question when the file gives the exam its
    first axis while subjects sit outside every axis: ``'aside'``, ``'move'``
    or ``'back'``, pressed by a hit-tested click. ``None`` means no question
    is expected, and an unanswered one fails ``wait_import_done``."""
    start_import(page, file_obj)
    if first_axis is not None:
        assert wait_for_first_axis_dialog(page), (
            "the first-axis dialog never appeared")
        page.locator(css=f'[data-testid="first-axis-{first_axis}"]').click()
    wait_import_done(page)


def restore_archived(page: WimiPage, batch_id: str) -> None:
    """Press Restore on the archived axis's row, once the panel has drawn it."""
    sel = f'.archived-item[data-batch-id="{batch_id}"] .archived-restore-btn'
    found = poll(page, lambda: page.eval_js(
        f"!!document.querySelector({json.dumps(sel)})"), bool)
    assert found is True, "the Archived panel never listed the archived axis"
    page.eval_js(f"document.querySelector({json.dumps(sel)}).click()")


def seed_exam(db, name: str, axes: dict[str, list[str]],
              plain: tuple[str, ...] = ()) -> tuple[int, dict[str, int], dict[str, int]]:
    """An exam with ``axes`` (name -> root subject names, in display order)
    and ``plain`` subjects that belong to no axis.

    Returns ``(exam_id, {axis: dimension_id}, {subject: node_id})``."""
    exam = db.create_exam_context(exam_name=name, exam_description="#899")
    dims, nodes = {}, {}
    for subject in plain:
        nodes[subject] = db.create_subject_node(
            exam_context=exam.exam_name, name=subject, level_type="System").id
    for order, (axis, subjects) in enumerate(axes.items(), start=1):
        dims[axis] = db.create_dimension(exam_id=exam.id, name=axis,
                                         display_order=order)
        for subject in subjects:
            nodes[subject] = db.create_subject_node(
                exam_context=exam.exam_name, name=subject, level_type="System",
                dimension_id=dims[axis]).id
    db.conn.commit()
    return exam.id, dims, nodes
