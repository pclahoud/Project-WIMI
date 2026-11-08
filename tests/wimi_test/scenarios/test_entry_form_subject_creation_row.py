"""Every non-empty subject result list ends in a creation row, unless the
query is exactly a name the exam already has (#856, decision 2).

The standard combobox pattern, and what makes a creation path reachable
from the Primary box at all: the old button lived in the Secondary row.
The row reads *Add 'X' as a new subject…*, is the LAST row of the list,
and carries ``.subject-option`` so the keyboard controller's arrow keys
reach it and Enter opens the dialog -- the Enter half is asserted here by
pressing the keys the way a student does.

The negative half is the exact-match rule: typing ``cardiology`` against a
subject named ``Cardiology`` (case differs) draws no row, because offering
to create a subject that exists is how duplicates get made (#850).
"""
from __future__ import annotations

import pytest

from _helpers.subject_search import (
    dropdown_state, modal_state, open_entry_form, poll, seed_exam, subject,
    type_query)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM = "Creation Row Exam 856"


def _seed(db):
    exam_id, _axis, session_id = seed_exam(db, EXAM)
    cardio = subject(db, EXAM, "Cardiology", level="System")
    subject(db, EXAM, "Cardiomyopathy", cardio)
    return session_id


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("box", ["primary", "secondary"])
def test_a_partial_query_gets_a_creation_row_and_an_exact_one_does_not(
    wimi_session: WimiTestSession, wimi_page: WimiPage, box: str,
) -> None:
    session_id = _seed(wimi_session.user.db)
    open_entry_form(wimi_page, session_id)

    # Non-empty, not exact: results AND the row, and the row is last.
    type_query(wimi_page, box, "Cardio")
    state = dropdown_state(wimi_page, box)
    assert len(state["optionIds"]) == 2, f"expected both Cardio* subjects: {state!r}"
    assert state["createText"] == "Add 'Cardio' as a new subject…", state
    assert state["createIsLast"] is True, (
        "the creation row must be the last row of the list, after every match")

    # Exact name, case-insensitive: the row is gone and the match remains.
    type_query(wimi_page, box, "cardiology")
    state = dropdown_state(wimi_page, box)
    assert len(state["optionIds"]) >= 1, state
    assert state["createText"] is None, (
        f"'cardiology' is exactly a subject the exam has, so offering to "
        f"create it again is the duplicate path #850 came from: {state!r}")

    # Back to a partial query, and the dropdown recovers the row.
    type_query(wimi_page, box, "Cardiom")
    state = dropdown_state(wimi_page, box)
    assert state["createText"] == "Add 'Cardiom' as a new subject…", state


@pytest.mark.slow
@pytest.mark.regression
def test_the_creation_row_is_reachable_by_arrow_keys_and_enter(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """ArrowDown past the two matches lands on the row; Enter opens Quick Add
    with the query prefilled, through the same path as a click."""
    session_id = _seed(wimi_session.user.db)
    open_entry_form(wimi_page, session_id)

    type_query(wimi_page, "primary", "Cardio")
    tab = wimi_page.tab
    # Two matches, then the row: three ArrowDowns.
    for _ in range(3):
        tab.Input.dispatchKeyEvent(type="rawKeyDown", key="ArrowDown",
                                   code="ArrowDown", windowsVirtualKeyCode=40)
        tab.Input.dispatchKeyEvent(type="keyUp", key="ArrowDown",
                                   code="ArrowDown", windowsVirtualKeyCode=40)
    highlighted = wimi_page.eval_js(
        "(() => { const el = document.querySelector("
        "'#primary-subject-dropdown .subject-option.selected');"
        " return el ? el.dataset.testid || el.getAttribute('data-testid') : null; })()")
    assert highlighted == "entry-form-subject-create-primary", (
        f"three ArrowDowns should highlight the creation row, got {highlighted!r}")

    tab.Input.dispatchKeyEvent(type="rawKeyDown", key="Enter", code="Enter",
                               windowsVirtualKeyCode=13)
    tab.Input.dispatchKeyEvent(type="keyUp", key="Enter", code="Enter",
                               windowsVirtualKeyCode=13)
    modal = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["open"])
    assert modal["open"] and modal["name"] == "Cardio" and modal["target"] == "primary", (
        f"Enter on the highlighted creation row did not open Quick Add for "
        f"the primary row with the query prefilled: {modal!r}")
