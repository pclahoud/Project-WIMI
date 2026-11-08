"""Shared seeding and waiting for the #856 entry-form subject-search scenarios.

Four scenario files drive the two subject search boxes and the Quick Add
dialog; this holds what they share so each stays about one behaviour.

Three harness facts they all rely on:

* ``EntryState`` is a top-level ``const`` -- a global *binding*, so the bare
  name resolves from ``eval_js`` and ``window.EntryState`` is ``undefined``.
* The form ships ``inert`` until ``markEntryFormReady()`` releases it
  (#114). ``inert`` blocks hit-tested clicks and focus but not a value
  assignment, and the harness's ``fill`` IS a value assignment (``el.value =
  v`` plus synthetic ``input``/``change`` events, ``wimi_test/locator.py``;
  only ``click`` is hit-tested). So the ready wait in ``open_entry_form`` is
  what keeps these scenarios honest, not how they type: one that skipped it
  would fill an inert form and pass.
* ``locator()`` takes exactly one keyword strategy.
"""
from __future__ import annotations

from datetime import date

from wimi_test.page import WimiPage

READY_JS = (
    "(() => typeof EntryState !== 'undefined' && EntryState.isFormReady === true"
    " && Array.isArray(EntryState.subjects) && EntryState.subjects.length > 0)()"
)


def poll(wimi_page: WimiPage, read, predicate, *, timeout_ms: int = 10000):
    """Re-read until ``predicate`` holds; return the last value either way."""
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:  # noqa: BLE001 - a mid-render read may throw
            last = None
        if predicate(last):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def seed_exam(db, exam_name: str, *, dimensioned: bool = False):
    """An exam, optionally with one active axis, and a one-slot session.

    Returns ``(exam_id, axis_id_or_None, session_id)``. Subjects are the
    scenario's own business, so none are created here.
    """
    exam = db.create_exam_context(
        exam_name=exam_name,
        exam_description="#856 subject search scenario",
    )
    axis_id = None
    if dimensioned:
        axis_id = db.create_dimension(exam_id=exam.id, name="System", display_order=1)
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name=f"{exam_name} session",
        date_encountered=date.today(),
    )
    return exam.id, axis_id, session.id


def subject(db, exam_name: str, name: str, parent_id=None, *, level="Topic",
            dimension_id=None):
    """One active subject; returns its id."""
    node = db.create_subject_node(
        exam_context=exam_name,
        name=name,
        level_type=level,
        parent_id=parent_id,
        sort_order=1,
        dimension_id=dimension_id,
    )
    return node.id


def open_entry_form(wimi_page: WimiPage, session_id: int) -> None:
    """Land on the form and wait for it to be released and indexed."""
    wimi_page.goto("entry-form", query={"session_id": session_id})
    ready = poll(wimi_page, lambda: wimi_page.eval_js(READY_JS), lambda v: v is True,
                 timeout_ms=20000)
    assert ready is True, (
        "the entry form never reported ready with a populated subject index; "
        "nothing below can be measured against an inert page")


def type_query(wimi_page: WimiPage, box: str, text: str) -> None:
    """Type into the primary or secondary search box through the harness."""
    wimi_page.locator(testid=f"entry-form-subject-{box}-search").fill(text)
    shown = poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            f"document.getElementById('{box}-subject-dropdown')"
            ".classList.contains('visible')"),
        lambda v: v is True,
    )
    assert shown is True, f"the {box} dropdown did not open for {text!r}"


def dropdown_state(wimi_page: WimiPage, box: str) -> dict:
    """What the dropdown shows: option ids, creation row, empty-state text."""
    return wimi_page.eval_js(
        "(() => {"
        f"  const d = document.getElementById('{box}-subject-dropdown');"
        "  const opts = Array.from(d.querySelectorAll('.subject-option:not(.subject-create-option)'));"
        f"  const create = d.querySelector('[data-testid=\"entry-form-subject-create-{box}\"]');"
        f"  const empty = d.querySelector('[data-testid=\"entry-form-subject-empty-text-{box}\"]');"
        "  return {"
        "    optionIds: opts.map(o => o.dataset.id),"
        "    createText: create ? create.querySelector('.subject-create-option-text').textContent.replace(/\\s+/g, ' ').trim() : null,"
        "    createIsLast: create ? create === d.querySelector('.dropdown-results')?.lastElementChild : null,"
        "    emptyText: empty ? empty.textContent.trim() : null,"
        "  };"
        "})()"
    )


def modal_state(wimi_page: WimiPage) -> dict:
    return wimi_page.eval_js(
        "(() => {"
        "  const m = document.getElementById('quick-add-subject-modal');"
        "  const guard = document.getElementById('quick-add-guard');"
        "  const err = document.getElementById('quick-add-parent-error');"
        "  return {"
        "    open: m.classList.contains('active'),"
        "    target: m.dataset.target || null,"
        "    parentRequired: m.dataset.parentRequired || null,"
        "    name: document.getElementById('quick-add-name').value,"
        "    guardShown: !guard.hidden,"
        "    guardText: guard.hidden ? '' : guard.textContent.replace(/\\s+/g, ' ').trim(),"
        "    parentError: err.hidden ? null : err.textContent.trim(),"
        "    rootOffered: !!document.querySelector('#quick-add-parent-dropdown .root-option'),"
        "  };"
        "})()"
    )


def selected(wimi_page: WimiPage) -> dict:
    """The names in each chip row, read from the form's own state."""
    return wimi_page.eval_js(
        "({primary: EntryState.formData.primarySubjects.map(s => s.name),"
        "  secondary: EntryState.formData.secondarySubjects.map(s => s.name)})"
    )


def active_subject_count(db) -> int:
    return db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_nodes WHERE status = 'active'")["n"]
