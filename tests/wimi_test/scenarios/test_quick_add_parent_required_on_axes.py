"""On an exam with axes Quick Add requires a parent and offers no Root; on a
plain exam Root stays (#856, decision 5; owner 2026-11-04).

``createSubjectNode`` derives a new subject's axis from its parent and from
nothing else (``bridge_domains/hierarchy.py``), so a parentless Quick Add on
a dimensioned exam made a subject in NO axis -- the population the tree
editor's "Subjects not in any axis" panel (#605) exists to repair. The entry
form was manufacturing the state another feature cleans up.

The flag is read once at load through ``api.examUsesDimensions`` (the same
derived rule the tree editor uses), never inferred from the subject list.

Asserted from the database, not the page: the new subject's ``dimension_id``
equals its parent's, and a refused save leaves the row count unchanged.
"""
from __future__ import annotations

import pytest

from _helpers.subject_search import (
    active_subject_count, modal_state, open_entry_form, poll, seed_exam,
    selected, subject, type_query)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _open_quick_add(wimi_page, query: str) -> None:
    type_query(wimi_page, "primary", query)
    wimi_page.locator(testid="entry-form-subject-create-primary").click()
    modal = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["open"])
    assert modal["open"], "Quick Add did not open"
    # Focusing the parent field draws its list; it is hit-tested so the
    # dropdown opens the way it does for a student.
    wimi_page.locator(testid="entry-form-quick-add-parent-search").click()
    poll(wimi_page,
         lambda: wimi_page.eval_js(
             "document.getElementById('quick-add-parent-dropdown').classList.contains('visible')"),
         lambda v: v is True)


@pytest.mark.slow
@pytest.mark.regression
def test_an_exam_with_an_axis_requires_a_parent_and_inherits_its_axis(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = "Axis Exam 856"
    _exam_id, axis_id, session_id = seed_exam(db, exam, dimensioned=True)
    resp = subject(db, exam, "Respiratory", level="System", dimension_id=axis_id)
    subject(db, exam, "Asthma", resp, dimension_id=axis_id)
    open_entry_form(wimi_page, session_id)
    assert wimi_page.eval_js("EntryState.examUsesDimensions") is True, (
        "the form did not read the exam's axis flag at load")

    _open_quick_add(wimi_page, "Bronchiectasis")
    modal = modal_state(wimi_page)
    assert modal["parentRequired"] == "true", modal
    assert modal["rootOffered"] is False, (
        "Root (Top Level) must not be offered on an exam with axes: a root "
        "created here would belong to no axis")

    # Save with no parent: refused with a sentence, and nothing is created.
    before = active_subject_count(db)
    wimi_page.locator(testid="entry-form-quick-add-save-button").click()
    refused = poll(wimi_page, lambda: modal_state(wimi_page),
                   lambda m: m and m["parentError"])
    assert refused["parentError"] and "parent" in refused["parentError"], refused
    assert refused["open"], "the dialog must stay open for the student to pick a parent"
    assert active_subject_count(db) == before, "a parentless save created a subject"

    # Pick a parent, save: the new subject carries the parent's axis.
    wimi_page.locator(testid="entry-form-quick-add-parent-search").click()
    wimi_page.locator(
        css=f'#quick-add-parent-dropdown .subject-option[data-id="{resp}"]').click()
    wimi_page.locator(testid="entry-form-quick-add-save-button").click()
    closed = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["open"])
    assert not closed["open"], f"the save with a parent did not go through: {closed!r}"

    row = db.fetchone(
        "SELECT parent_id, dimension_id FROM subject_nodes "
        "WHERE name = 'Bronchiectasis' AND status = 'active'")
    assert row is not None, "Bronchiectasis was not created"
    assert row["parent_id"] == resp, row
    assert row["dimension_id"] == axis_id, (
        f"the new subject must inherit its parent's axis, got {row!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_a_plain_exam_keeps_root_and_a_parentless_save_works(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = "Plain Exam 856"
    _exam_id, _axis, session_id = seed_exam(db, exam)
    subject(db, exam, "Respiratory", level="System")
    open_entry_form(wimi_page, session_id)
    assert wimi_page.eval_js("EntryState.examUsesDimensions") is False

    _open_quick_add(wimi_page, "Nephrology")
    modal = modal_state(wimi_page)
    assert modal["parentRequired"] == "false", modal
    assert modal["rootOffered"] is True, "a plain exam keeps Root (Top Level)"

    wimi_page.locator(css="#quick-add-parent-dropdown .root-option").click()
    before = active_subject_count(db)
    wimi_page.locator(testid="entry-form-quick-add-save-button").click()
    closed = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["open"])
    assert not closed["open"] and closed["parentError"] is None, closed
    assert active_subject_count(db) == before + 1
    row = db.fetchone(
        "SELECT parent_id, dimension_id FROM subject_nodes "
        "WHERE name = 'Nephrology' AND status = 'active'")
    assert row["parent_id"] is None and row["dimension_id"] is None, row


def _parent_dropdown(wimi_page) -> dict:
    return wimi_page.eval_js(
        "(() => {"
        "  const d = document.getElementById('quick-add-parent-dropdown');"
        "  const empty = d.querySelector('[data-testid=\"entry-form-quick-add-parent-empty-text\"]');"
        "  return {"
        "    visible: d.classList.contains('visible'),"
        "    listboxes: d.querySelectorAll('[role=\"listbox\"]').length,"
        "    options: d.querySelectorAll('.subject-option').length,"
        "    emptyText: empty ? empty.textContent.replace(/\\s+/g, ' ').trim() : null,"
        "    emptyRole: empty ? empty.parentElement.getAttribute('role') : null,"
        "  };"
        "})()")


@pytest.mark.slow
@pytest.mark.regression
def test_a_parent_query_matching_nothing_says_so_on_an_axis_exam(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """With Root suppressed, an unmatched parent query used to paint an empty
    role="listbox": a bordered strip a few pixels tall, nothing in it and
    nothing announced. The box must say what it found, as the subject boxes'
    empty state does, and a query that matches must still list it.

    And the sentence may only appear when a search ran: the fuzzy index
    returns nothing for a query under two characters, so a one-character
    query must show the whole list, as no query does, rather than announce
    that no subject matches 'R' while Respiratory exists."""
    db = wimi_session.user.db
    exam = "Axis Exam 856 empty parent"
    _exam_id, axis_id, session_id = seed_exam(db, exam, dimensioned=True)
    subject(db, exam, "Respiratory", level="System", dimension_id=axis_id)
    subject(db, exam, "Cardiology", level="System", dimension_id=axis_id)
    open_entry_form(wimi_page, session_id)

    _open_quick_add(wimi_page, "Bronchiectasis")
    wimi_page.locator(testid="entry-form-quick-add-parent-search").fill("Zxqv")
    state = poll(wimi_page, lambda: _parent_dropdown(wimi_page),
                 lambda s: s and s["emptyText"])
    assert state["visible"], state
    assert state["listboxes"] == 0 and state["options"] == 0, (
        f"an empty listbox is the defect this guards against: {state!r}")
    assert state["emptyText"] == (
        f"No subject in {exam} matches 'Zxqv' by name or alias."), state
    assert state["emptyRole"] == "status", state

    wimi_page.locator(testid="entry-form-quick-add-parent-search").fill("Respir")
    found = poll(wimi_page, lambda: _parent_dropdown(wimi_page),
                 lambda s: s and s["options"] > 0)
    assert found["options"] == 1 and found["emptyText"] is None, found

    # One character is under the fuzzy index's floor (searchSubjects returns
    # [] below two), so it is not a search that found nothing. Two subjects
    # are seeded so that the whole list, and not a prefix match on 'R', is
    # what distinguishes the right answer from a false "no subject matches".
    wimi_page.locator(testid="entry-form-quick-add-parent-search").fill("R")
    one = poll(wimi_page, lambda: _parent_dropdown(wimi_page),
               lambda s: s and s["options"] == 2)
    assert one["visible"] and one["options"] == 2 and one["emptyText"] is None, (
        f"a one-character parent query must show the list, never a sentence: {one!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_create_anyway_holds_across_a_refused_parentless_save(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The guard runs before the parent rule. On an exam with axes, "Create
    anyway" pressed before a parent is chosen is refused by the parent rule;
    the student then picks a parent and presses Save. That save must go
    through: it used to re-fire the same guard, so Save did nothing however
    often it was pressed and only a second "Create anyway" created."""
    db = wimi_session.user.db
    exam = "Axis Exam 856 guard"
    _exam_id, axis_id, session_id = seed_exam(db, exam, dimensioned=True)
    resp = subject(db, exam, "Respiratory", level="System", dimension_id=axis_id)
    trauma = subject(db, exam, "Trauma", level="System", dimension_id=axis_id)
    subject(db, exam, "Pneumothorax", resp, dimension_id=axis_id)
    open_entry_form(wimi_page, session_id)
    before = active_subject_count(db)

    # Open from a partial query; the prefilled name is then completed to the
    # existing one and saved with no parent chosen.
    type_query(wimi_page, "primary", "Pneumo")
    wimi_page.locator(testid="entry-form-subject-create-primary").click()
    poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["open"])
    wimi_page.locator(testid="entry-form-quick-add-name-input").fill("Pneumothorax")
    wimi_page.locator(testid="entry-form-quick-add-save-button").click()
    guarded = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["guardShown"])
    assert guarded["guardShown"] and guarded["parentError"] is None, guarded

    wimi_page.locator(testid="entry-form-quick-add-guard-create").click()
    refused = poll(wimi_page, lambda: modal_state(wimi_page),
                   lambda m: m and m["parentError"])
    assert refused["parentError"], f"the parent rule did not refuse: {refused!r}"
    assert refused["guardShown"] is False, (
        "an answered guard must not stay on screen under the parent error")
    assert refused["open"] and active_subject_count(db) == before

    wimi_page.locator(testid="entry-form-quick-add-parent-search").click()
    wimi_page.locator(
        css=f'#quick-add-parent-dropdown .subject-option[data-id="{trauma}"]').click()
    wimi_page.locator(testid="entry-form-quick-add-save-button").click()
    closed = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["open"])
    assert not closed["open"], (
        f"Save after choosing a parent re-asked or did nothing: {closed!r}")
    assert active_subject_count(db) == before + 1
    row = db.fetchone(
        "SELECT parent_id, dimension_id FROM subject_nodes WHERE name = 'Pneumothorax' "
        f"AND parent_id = {trauma} AND status = 'active'")
    assert row is not None and row["dimension_id"] == axis_id, row
    assert selected(wimi_page)["primary"] == ["Pneumothorax"]
