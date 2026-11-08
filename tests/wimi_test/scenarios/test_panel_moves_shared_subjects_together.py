"""The "Subjects not in any axis" panel keeps a shared subject in one axis (#903).

The issue's repro, on ``master`` ``a58fec4``: RootA and RootB are top-level
subjects outside every axis and share SharedC (RootA primary, RootB a second
parent). The panel listed both rows. AxisX on RootA's row, Move in, then
AxisY on RootB's row, Move in -- both succeeded, leaving RootB (AxisY) over
SharedC (AxisX), an edge crossing two axes. Cross-dimensional edges are a
Non-Goal. After the first press RootB's row read "on its own", so nothing
said its child had already gone.

The rule now (the owner's #605 decision 6, applied to the panel): top-level
subjects that share a subject move together. The row says so before the
press -- "Moves with RootB, because they share subjects." -- and one press
puts all three in AxisX. Recorded failing on ``master`` ``d80efd4``: no link
line on the row, and RootB was still outside every axis after the press.

The second test is the state the old two-press flow left behind (SharedC in
AxisX under RootA, RootB still outside): RootB's row says it can only go
into AxisX and pre-selects it, and a press into AxisY is refused with a
sentence through the error toast, moving nothing. On ``d80efd4`` that press
succeeded and wrote the crossing edge.

Presses are hit-tested clicks (``locator(...).click()``), never ``el.click()``.
``Toast`` is a top-level ``const`` on this page, so it is wrapped by its bare
name; ``window.Toast`` is undefined here.
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


def _seed(db, *, first_move_done: bool):
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name="Panel 903 Exam",
                                  exam_description="#903")
    x = db.create_dimension(exam_id=exam.id, name="AxisX", display_order=1)
    y = db.create_dimension(exam_id=exam.id, name="AxisY", display_order=2)
    ids = {}
    for order, name in enumerate(("RootA", "RootB", "SharedC")):
        ids[name] = db.execute(
            "INSERT INTO subject_nodes (exam_context, name, level_type, "
            "dimension_id, sort_order, status) "
            "VALUES (?, ?, 'System', NULL, ?, 'active')",
            (exam.exam_name, name, order)).lastrowid
    db.conn.commit()
    db.add_edge(ids["RootA"], ids["SharedC"], is_primary=True)
    db.add_edge(ids["RootB"], ids["SharedC"], is_primary=False)
    if first_move_done:
        db.execute("UPDATE subject_nodes SET dimension_id = ? WHERE id IN (?, ?)",
                   (x, ids["RootA"], ids["SharedC"]))
    db.conn.commit()
    return exam.id, x, y, ids


def _axes(db, ids):
    return {name: db.fetchone(
        "SELECT dimension_id FROM subject_nodes WHERE id = ?",
        (sid,))["dimension_id"] for name, sid in ids.items()}


def _open_panel(page: WimiPage, exam_id: int, row_id: int) -> None:
    page.goto("tree-editor", query={"exam_id": exam_id})
    _poll(page, lambda: page.eval_js(
        "(() => { const el = document.querySelector("
        "'[data-testid=\"tree-unassigned-count\"]');"
        " return el ? el.textContent.trim() : null; })()"),
        lambda t: t not in (None, "", "0"))
    page.locator(testid="tree-unassigned-toggle").click()
    ok = _poll(page, lambda: page.eval_js(
        f"!!document.querySelector('[data-testid=\"tree-unassigned-move-{row_id}\"]')"),
        lambda v: v is True)
    assert ok, "the panel never drew the row's Move in button"


def _row_text(page: WimiPage, row_id: int) -> str:
    return page.eval_js(
        f"(() => {{ const el = document.querySelector("
        f"'[data-testid=\"tree-unassigned-row-{row_id}\"]');"
        f" return el ? el.textContent.replace(/\\s+/g, ' ').trim() : null; }})()")


@pytest.mark.slow
@pytest.mark.regression
def test_one_press_moves_both_roots_and_the_row_says_so_first(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, x, y, ids = _seed(db, first_move_done=False)
    _open_panel(wimi_page, exam_id, ids["RootA"])

    # Positive control: the defect's precondition -- both roots listed.
    assert wimi_page.eval_js(
        "document.querySelectorAll('[data-testid^=\"tree-unassigned-row-\"]')"
        ".length") == 2

    text = _row_text(wimi_page, ids["RootA"])
    assert "Moves with RootB, because they share subjects." in (text or ""), (
        f"the row must name the link before the press: {text!r}")

    wimi_page.eval_js(
        f"(() => {{ const s = document.querySelector("
        f"'[data-testid=\"tree-unassigned-select-{ids['RootA']}\"]');"
        f" s.value = '{x}'; }})()")
    wimi_page.locator(testid=f"tree-unassigned-move-{ids['RootA']}").click()

    final = _poll(wimi_page, lambda: _axes(db, ids),
                  lambda a: a and all(v is not None for v in a.values()))
    assert final == {"RootA": x, "RootB": x, "SharedC": x}, (
        f"RootB stayed outside, so a second press could still split SharedC "
        f"across two axes (#903): {final!r}")

    hidden = _poll(wimi_page, lambda: wimi_page.eval_js(
        "document.querySelector('[data-testid=\"tree-unassigned-panel\"]')"
        ".classList.contains('hidden')"), lambda h: h is True)
    assert hidden is True, "nothing is stranded, so the panel must hide"


@pytest.mark.slow
@pytest.mark.regression
def test_a_root_bound_to_another_axis_is_refused_with_a_sentence(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, x, y, ids = _seed(db, first_move_done=True)
    _open_panel(wimi_page, exam_id, ids["RootB"])

    text = _row_text(wimi_page, ids["RootB"]) or ""
    assert "Can only go into AxisX" in text, (
        f"the row must say which axis it can go into: {text!r}")
    preselected = wimi_page.eval_js(
        f"document.querySelector("
        f"'[data-testid=\"tree-unassigned-select-{ids['RootB']}\"]').value")
    assert preselected == str(x), f"AxisX should be pre-selected: {preselected!r}"

    wimi_page.eval_js(
        "(() => { window.__w903Errors = [];"
        " const orig = Toast.error.bind(Toast);"
        " Toast.error = (t, m) => { window.__w903Errors.push([t, m]);"
        " return orig(t, m); }; })()")
    wimi_page.eval_js(
        f"(() => {{ const s = document.querySelector("
        f"'[data-testid=\"tree-unassigned-select-{ids['RootB']}\"]');"
        f" s.value = '{y}'; }})()")
    wimi_page.locator(testid=f"tree-unassigned-move-{ids['RootB']}").click()

    errors = _poll(wimi_page, lambda: wimi_page.eval_js("window.__w903Errors"),
                   lambda e: isinstance(e, list) and len(e) > 0)
    assert errors, (
        f"no refusal was shown; the move went through and RootB is now in "
        f"{_axes(db, ids)['RootB']!r} over SharedC in AxisX (#903)")
    message = errors[0][1]
    for word in ('"RootB"', '"AxisY"', '"SharedC"', '"AxisX"'):
        assert word in message, f"the refusal must name {word}: {message!r}"
    assert _axes(db, ids)["RootB"] is None, "the refused move still wrote"
