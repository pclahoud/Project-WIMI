"""The subject search's empty state names the query and offers to create it,
and Quick Add selects into the row it was opened for (#856, #694).

Before this the dropdown said "No subjects found" and offered nothing, and
the one way to create a subject from the form was a button in the Secondary
row that selected the new subject as **primary** whichever row the student
was in (#694). Now:

1. a query matching nothing shows *No subject in <exam> matches '<query>'
   by name or alias* and a button *Add '<query>' as a new subject*;
2. the button opens Quick Add with the name prefilled and the target row
   set to the one the student was typing in;
3. saving selects the subject into THAT row -- the secondary half of this
   file is the discriminator for #694, because a primary-only fix passes
   the first test;
4. the old ``#btn-quick-add-subject`` is gone (owner, 2026-11-04).

Input goes through the harness after the form reports ready (#114): ``click``
is hit-tested, ``fill`` assigns the value, and it is the ready wait in
``open_entry_form`` that stops either from driving an inert page. A probe
built from ``el.click()`` would pass against a page that refuses the student.
"""
from __future__ import annotations

import pytest

from _helpers.subject_search import (
    active_subject_count, dropdown_state, modal_state, open_entry_form, poll,
    seed_exam, selected, subject, type_query)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM = "Empty State Exam 856"


def _seed(db):
    exam_id, _axis, session_id = seed_exam(db, EXAM)
    cardio = subject(db, EXAM, "Cardiology", level="System")
    subject(db, EXAM, "Heart failure", cardio)
    return session_id


def _create_from_empty_state(wimi_session, wimi_page, box: str, query: str) -> None:
    db = wimi_session.user.db
    type_query(wimi_page, box, query)

    state = dropdown_state(wimi_page, box)
    assert state["optionIds"] == [], f"{query!r} matched something: {state!r}"
    assert state["emptyText"] == (
        f"No subject in {EXAM} matches '{query}' by name or alias."), state["emptyText"]
    assert state["createText"] == f"Add '{query}' as a new subject", state["createText"]

    wimi_page.locator(testid=f"entry-form-subject-create-{box}").click()
    modal = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["open"])
    assert modal["open"], "the empty state's button did not open Quick Add"
    assert modal["name"] == query, f"the name is not prefilled: {modal!r}"
    assert modal["target"] == box, f"Quick Add was opened for {modal['target']!r}"

    before = active_subject_count(db)
    wimi_page.locator(testid="entry-form-quick-add-save-button").click()
    closed = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["open"])
    assert not closed["open"], f"Quick Add stayed open: {closed!r}"
    assert active_subject_count(db) == before + 1, "no subject was created"


@pytest.mark.slow
@pytest.mark.regression
def test_the_primary_box_creates_a_primary_subject(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    session_id = _seed(wimi_session.user.db)
    open_entry_form(wimi_page, session_id)

    # The old button is gone from the form (decision 6).
    assert wimi_page.eval_js(
        "document.getElementById('btn-quick-add-subject') === null"), (
        "#btn-quick-add-subject is still on the form; the creation rows are "
        "the way in now")

    _create_from_empty_state(wimi_session, wimi_page, "primary", "Nephrology")
    chips = selected(wimi_page)
    assert chips == {"primary": ["Nephrology"], "secondary": []}, chips

    # A plain exam: the new subject is a root in no axis.
    row = wimi_session.user.db.fetchone(
        "SELECT parent_id, dimension_id FROM subject_nodes "
        "WHERE name = 'Nephrology' AND status = 'active'")
    assert row is not None and row["parent_id"] is None and row["dimension_id"] is None, row


@pytest.mark.slow
@pytest.mark.regression
def test_the_secondary_box_creates_a_secondary_subject(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#694's discriminator: from the Secondary box the subject must land as
    secondary and NOT as primary."""
    session_id = _seed(wimi_session.user.db)
    open_entry_form(wimi_page, session_id)

    _create_from_empty_state(wimi_session, wimi_page, "secondary", "Hepatology")
    chips = selected(wimi_page)
    assert chips["secondary"] == ["Hepatology"], (
        f"the subject created from the Secondary box is not a secondary chip: {chips!r}")
    assert chips["primary"] == [], (
        f"it landed as PRIMARY, which is #694 -- Quick Add must select into "
        f"the row it was opened for: {chips!r}")
