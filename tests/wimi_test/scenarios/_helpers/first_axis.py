"""Driving the exam wizard to its first-axis prompt (#605 Wave 1, #444).

Everything a student does is a real click: the info step's **Add dimensions
to this exam** (#444's control, the only way a Simple exam reaches the Define
Dimensions step), **Next**, the axis-name fields and **Save Changes**. Wave 0
reached the step with ``examWizard.selectExamType(...)`` from a script; a
scenario that still did would prove nothing about the route a student has.
"""
from __future__ import annotations

from wimi_test.page import WimiPage

DIALOG = '[data-testid="first-axis-dialog"]'

READY = (
    "typeof examWizard !== 'undefined' && !!examWizard"
    " && examWizard.currentStep === 3 && !!examWizard.data.examName"
)


def poll(page: WimiPage, read, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def seed_plain(db, exam_name: str, roots: list[str], *, child_of_first: str | None = None):
    """A Simple exam whose top-level subjects are ``roots``. Returns (exam, ids)."""
    exam = db.create_exam_context(exam_name=exam_name, exam_description="#605")
    ids = {name: db.create_subject_node(exam_name, name, "System").id for name in roots}
    if child_of_first:
        ids[child_of_first] = db.create_subject_node(
            exam_name, child_of_first, "Topic", parent_id=ids[roots[0]]).id
    db.conn.commit()
    return exam, ids


def open_edit(page: WimiPage, exam_id: int) -> None:
    page.goto("exam-wizard", query={"edit": exam_id})
    assert poll(page, lambda: page.eval_js(READY), True) is True, (
        "the wizard never opened the exam in edit mode")


def dialog_open(page: WimiPage) -> bool:
    return bool(page.eval_js(f"!!document.querySelector('{DIALOG}')"))


def css(page: WimiPage, selector: str):
    return page.locator(css=selector)


def name_axes(page: WimiPage, names: list[str], *, start: int = 0) -> None:
    """On the Define Dimensions step, name ``names`` from card ``start`` on."""
    def cards():
        return page.eval_js("document.querySelectorAll('.dimension-name').length")

    for offset, name in enumerate(names):
        index = start + offset
        if index >= cards():
            css(page, '[data-testid="wizard-step3-add-dimension-button"]').click()
            assert poll(page, cards, index + 1) == index + 1, (
                f"Add Dimension did not draw card {index + 1}")
        css(page, f'[data-testid="wizard-step3-dimension-{index}-name-input"]').fill(name)


def next_until_save(page: WimiPage) -> None:
    for _ in range(8):
        if page.eval_js("!document.getElementById('btn-create').classList.contains('hidden')"):
            return
        css(page, "#btn-next").click()
        page.wait_for_timeout(150)
    raise AssertionError("never reached the Review step's Save Changes")


def add_axes_and_save(page: WimiPage, names: list[str]) -> None:
    """From the info step of a Simple exam: Add dimensions, name them, Save."""
    css(page, '[data-testid="wizard-add-dimensions-button"]').click()
    assert poll(page, lambda: page.eval_js("examWizard.data.examType"),
                "multi_dimensional") == "multi_dimensional", (
        "Add dimensions to this exam did not make the exam multi-dimensional")
    css(page, "#btn-next").click()
    assert poll(page, lambda: page.eval_js("examWizard.getCurrentStepType()"),
                "dimensions") == "dimensions", "Next did not reach Define Dimensions"
    name_axes(page, names)
    next_until_save(page)
    css(page, "#btn-create").click()


def success_shown(page: WimiPage) -> bool:
    return bool(page.eval_js(
        "!document.getElementById('success-modal').classList.contains('hidden')"))


def visible(page: WimiPage, selector: str) -> bool:
    return bool(page.eval_js(
        f"(() => {{ const e = document.querySelector('{selector}');"
        " return !!e && e.getClientRects().length > 0; })()"))


def axes_of(db, exam_id: int) -> list[str]:
    return [d["name"] for d in sorted(db.get_exam_dimensions(exam_id),
                                      key=lambda d: d["display_order"])]


def dims_of(db, exam_name: str) -> dict[str, int | None]:
    return {r["name"]: r["dimension_id"] for r in db.fetchall(
        "SELECT name, dimension_id FROM subject_nodes WHERE exam_context = ?",
        (exam_name,))}
