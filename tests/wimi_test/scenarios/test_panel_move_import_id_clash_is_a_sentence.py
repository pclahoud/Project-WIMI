"""Moving a subject in from the "not in any axis" panel never shows a raw
UNIQUE-constraint error on an import-id clash (#904).

The issue's repro, on ``master`` ``a58fec4``: an exam with one axis, AxisX,
holding "Held in X"; "Stranded" outside every axis; both carrying
``import_id = 'dup-1'``. Pressing Move in on Stranded showed:

    Could not move them -- Failed to move subjects into the axis: Integrity
    constraint violated: UNIQUE constraint failed: index
    'idx_subject_nodes_import_id'

m020's partial unique index is per exam and axis, so a NULL-axis row and an
AxisX row may share an id and the move is what collides. The fix checks
before any write and refuses with a sentence naming the subject and the
axis. Recorded failing on ``master`` ``d80efd4`` with that same raw text.

The toast is captured by wrapping ``Toast.error`` by its bare name (a top-level ``const`` on this
page, so ``window.Toast`` is undefined); the press is a
hit-tested click.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _poll(page: WimiPage, read, predicate, *, timeout_ms: int = 20000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if predicate(last):
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_an_import_id_clash_reads_as_a_sentence_and_moves_nothing(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name="Panel 904 Exam",
                                  exam_description="#904")
    axis = db.create_dimension(exam_id=exam.id, name="AxisX", display_order=1)
    held = db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, dimension_id,"
        " sort_order, status) VALUES (?, 'Held in X', 'System', ?, 0, 'active')",
        (exam.exam_name, axis)).lastrowid
    stranded = db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, dimension_id,"
        " sort_order, status) VALUES (?, 'Stranded', 'System', NULL, 1, 'active')",
        (exam.exam_name,)).lastrowid
    db.execute("UPDATE subject_nodes SET import_id = 'dup-1' WHERE id IN (?, ?)",
               (held, stranded))
    db.conn.commit()

    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    _poll(wimi_page, lambda: wimi_page.eval_js(
        "(() => { const el = document.querySelector("
        "'[data-testid=\"tree-unassigned-count\"]');"
        " return el ? el.textContent.trim() : null; })()"),
        lambda t: t == "1")
    wimi_page.locator(testid="tree-unassigned-toggle").click()
    ready = _poll(wimi_page, lambda: wimi_page.eval_js(
        f"!!document.querySelector('[data-testid=\"tree-unassigned-move-{stranded}\"]')"),
        lambda v: v is True)
    assert ready, "the panel never drew Stranded's Move in button"

    wimi_page.eval_js(
        "(() => { window.__w904 = { errors: [], successes: [] };"
        " const e = Toast.error.bind(Toast);"
        " const s = Toast.success.bind(Toast);"
        " Toast.error = (t, m) => { window.__w904.errors.push([t, m]);"
        " return e(t, m); };"
        " Toast.success = (t, m) => { window.__w904.successes.push([t, m]);"
        " return s(t, m); }; })()")
    wimi_page.locator(testid=f"tree-unassigned-move-{stranded}").click()

    seen = _poll(wimi_page, lambda: wimi_page.eval_js("window.__w904"),
                 lambda v: v and (v["errors"] or v["successes"]))
    assert seen and seen["errors"], f"expected a refusal, got {seen!r}"
    message = seen["errors"][0][1]
    assert "UNIQUE" not in message and "idx_subject_nodes" not in message, (
        f"the student was shown the database's own text (#904): {message!r}")
    assert message == ('"Stranded" cannot move into "AxisX": a subject there '
                       "already carries the same import id."), message

    row = db.fetchone("SELECT dimension_id FROM subject_nodes WHERE id = ?",
                      (stranded,))
    assert row["dimension_id"] is None, "the refused move still wrote"
    assert wimi_page.eval_js(
        f"!!document.querySelector('[data-testid=\"tree-unassigned-row-{stranded}\"]')"
    ), "the row must stay, since nothing moved"
