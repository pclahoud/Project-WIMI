"""Quick Add's duplicate guard (#856, decision 3).

Before creating, the dialog looks for a subject of the typed name. On a
match it names each existing subject with its path and offers **Select it
instead** and **Create anyway**, plus the line that a second parent on the
existing subject is tree-editor work. It is a prompt and never a refusal:
the backend refuses a duplicate only under the same parent in the same axis
(#246), so a same name under another parent is legal data.

Seeded: two DISTINCT subjects named Pneumothorax under different parents
(the shape behind #850), and one multi-parent subject -- ONE node, two
parents -- which is the negative control. The subject list carries a
multi-parent node once per parent, so a guard that counted appearances
would call one subject two duplicates: two rows, two "Select it instead"
buttons, for one id. The control therefore drives the guard itself -- open
Quick Add, type the multi-parent name, Save -- and asserts ONE row naming
both places; a search of its name must show one subject and no creation
row as well, but that half alone passes against any build.

The near-exact rule (one edit away, five characters or more) is exercised
by name too: the manual promises it and the exact spelling never reaches
it. **Select it instead** reads the target row for itself, a second copy of
the #694 rule beside the create path's, so one case opens from the
Secondary box: with that read fixed to 'primary' every primary-opened case
stays green. The "Create anyway" answer holding across a save the parent
rule refuses lives in test_quick_add_parent_required_on_axes.
"""
from __future__ import annotations

import pytest

from _helpers.subject_search import (
    active_subject_count, dropdown_state, modal_state, open_entry_form, poll,
    seed_exam, selected, subject, type_query)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM = "Duplicate Guard Exam 856"


def _seed(db):
    exam_id, _axis, session_id = seed_exam(db, EXAM)
    resp = subject(db, EXAM, "Respiratory", level="System")
    pleura = subject(db, EXAM, "Disorders of the pleura", resp)
    trauma = subject(db, EXAM, "Trauma", level="System")
    cardio = subject(db, EXAM, "Cardiology", level="System")
    first = subject(db, EXAM, "Pneumothorax", pleura)
    subject(db, EXAM, "Pneumothorax", trauma)
    shock = subject(db, EXAM, "Shock", cardio)
    db.add_edge(trauma, shock, is_primary=False)   # one node, two parents
    return session_id, first, shock


def _open_quick_add_with(wimi_page, name: str, query: str = "Pneumo",
                         box: str = "primary") -> None:
    """Open the dialog from a partial query in ``box``, then type the full name."""
    type_query(wimi_page, box, query)
    wimi_page.locator(testid=f"entry-form-subject-create-{box}").click()
    poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["open"])
    wimi_page.locator(testid="entry-form-quick-add-name-input").fill(name)
    wimi_page.locator(testid="entry-form-quick-add-save-button").click()


def _guard_rows(wimi_page) -> list:
    """Each match row's subject id, sentence and Select-button count."""
    return wimi_page.eval_js(
        "Array.from(document.querySelectorAll("
        "'[data-testid=\"entry-form-quick-add-guard-match\"]')).map(r => ({"
        "  id: r.dataset.subjectId,"
        "  text: r.querySelector('.quick-add-guard-sentence').textContent.replace(/\\s+/g, ' ').trim(),"
        "  selects: r.querySelectorAll('.quick-add-guard-select').length}))")


@pytest.mark.slow
@pytest.mark.regression
def test_select_it_instead_selects_the_existing_subject_and_creates_nothing(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    session_id, first_id, _shock = _seed(db)
    open_entry_form(wimi_page, session_id)
    before = active_subject_count(db)

    _open_quick_add_with(wimi_page, "Pneumothorax")
    modal = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["guardShown"])
    assert modal["guardShown"], f"the guard did not appear: {modal!r}"
    assert "already exists under Respiratory › Disorders of the pleura" in modal["guardText"]
    assert "already exists under Trauma" in modal["guardText"]
    assert "second parent" in modal["guardText"] and "tree editor" in modal["guardText"]
    assert modal["open"], "the dialog must stay open behind the guard"

    rows = [r["id"] for r in _guard_rows(wimi_page)]
    assert len(rows) == 2 and str(first_id) in rows, rows

    wimi_page.locator(
        css=f'.quick-add-guard-select[data-subject-id="{first_id}"]').click()
    closed = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["open"])
    assert not closed["open"], "Select it instead must close the dialog"
    chips = selected(wimi_page)
    assert chips["primary"] == ["Pneumothorax"], chips
    chosen = wimi_page.eval_js("EntryState.formData.primarySubjects[0].id")
    assert chosen == first_id, f"a different subject was selected: {chosen}"
    assert active_subject_count(db) == before, "Select it instead created a subject"


@pytest.mark.slow
@pytest.mark.regression
def test_select_it_instead_lands_in_the_row_the_dialog_was_opened_for(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The discriminator for the Select path's copy of the #694 rule.

    The guard's Select handler reads ``EntryState.quickAddTarget`` for
    itself, beside the create path's read that the empty-state scenario
    already proves. Every other guard case opens from the Primary box, so
    with that one read replaced by ``'primary'`` the rest of this file stays
    green while a student who chose Select it instead from the Secondary
    box gets a primary chip. Opened from the Secondary box, the existing
    subject must land there and nowhere else.
    """
    db = wimi_session.user.db
    session_id, first_id, _shock = _seed(db)
    open_entry_form(wimi_page, session_id)
    before = active_subject_count(db)

    _open_quick_add_with(wimi_page, "Pneumothorax", box="secondary")
    modal = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["guardShown"])
    assert modal["guardShown"] and modal["target"] == "secondary", modal

    wimi_page.locator(
        css=f'.quick-add-guard-select[data-subject-id="{first_id}"]').click()
    closed = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["open"])
    assert not closed["open"], "Select it instead must close the dialog"
    chips = selected(wimi_page)
    assert chips == {"primary": [], "secondary": ["Pneumothorax"]}, chips
    assert wimi_page.eval_js("EntryState.formData.secondarySubjects[0].id") == first_id
    assert active_subject_count(db) == before, "Select it instead created a subject"


@pytest.mark.slow
@pytest.mark.regression
def test_create_anyway_creates_a_third(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    session_id, _first, _shock = _seed(db)
    open_entry_form(wimi_page, session_id)
    before = active_subject_count(db)

    _open_quick_add_with(wimi_page, "Pneumothorax")
    poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["guardShown"])
    wimi_page.locator(testid="entry-form-quick-add-guard-create").click()
    closed = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["open"])
    assert not closed["open"], f"Create anyway did not proceed: {closed!r}"
    assert active_subject_count(db) == before + 1, "Create anyway must create"
    assert db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_nodes WHERE name = 'Pneumothorax' "
        "AND status = 'active'")["n"] == 3
    assert selected(wimi_page)["primary"] == ["Pneumothorax"]


@pytest.mark.slow
@pytest.mark.regression
def test_a_one_letter_misspelling_is_caught_as_a_near_duplicate(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The near-exact rule the manual promises ("one a letter away from it").

    Typing the stored spelling satisfies the exact branch, so without this
    the Levenshtein clause and its five-character floor could go and every
    guard test would stay green. "Respiratry" is one deletion from the
    seeded root "Respiratory" and near nothing else, so the guard must show
    exactly one row, naming the existing spelling and its place.
    """
    db = wimi_session.user.db
    session_id, _first, _shock = _seed(db)
    open_entry_form(wimi_page, session_id)
    before = active_subject_count(db)

    _open_quick_add_with(wimi_page, "Respiratry", query="Respir")
    modal = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["guardShown"])
    assert modal["guardShown"], (
        f"a name one letter off an existing subject did not raise the guard: {modal!r}")
    rows = _guard_rows(wimi_page)
    assert len(rows) == 1, rows
    assert "A subject named 'Respiratory' already exists at the top level" in rows[0]["text"], rows
    assert modal["open"] and active_subject_count(db) == before, (
        "the guard must prompt, not create")

    # A changed spelling resets the guard. The hyphenated form is the loose
    # key's business (letters and digits only) and matches both distinct
    # Pneumothorax nodes.
    wimi_page.locator(testid="entry-form-quick-add-name-input").fill("pneumo-thorax")
    hidden = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["guardShown"])
    assert hidden["guardShown"] is False, "editing the name must clear the old guard"
    wimi_page.locator(testid="entry-form-quick-add-save-button").click()
    again = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["guardShown"])
    assert again["guardShown"], f"'pneumo-thorax' did not raise the guard: {again!r}"
    rows = _guard_rows(wimi_page)
    assert len(rows) == 2 and {r["text"].split("'")[1] for r in rows} == {"Pneumothorax"}, rows
    assert active_subject_count(db) == before


@pytest.mark.slow
@pytest.mark.regression
def test_a_multi_parent_subject_is_one_subject_and_not_a_duplicate(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The negative control: one node reached through two parents.

    ``get_subject_hierarchy`` lists Shock once under Cardiology and once
    under Trauma, so ``EntryState.subjects`` holds the one id twice. The
    guard must fold those into ONE row that names both places and whose
    "Select it instead" selects that id; keyed by appearance it would show
    two rows and two buttons for one subject, which says two duplicates
    exist when there is one.
    """
    db = wimi_session.user.db
    session_id, _first, shock_id = _seed(db)
    open_entry_form(wimi_page, session_id)
    before = active_subject_count(db)

    appearances = wimi_page.eval_js(
        f"EntryState.subjects.filter(s => s.id === {shock_id}).map(s => s.path)")
    assert len(appearances) == 2, (
        f"the control needs Shock listed once per parent, got {appearances!r}")

    type_query(wimi_page, "primary", "Shock")
    state = dropdown_state(wimi_page, "primary")
    assert state["optionIds"] and set(state["optionIds"]) == {str(shock_id)}, (
        f"searching a multi-parent subject's name must find that one subject "
        f"and nothing else: {state!r}")
    assert state["createText"] is None, (
        "an exact match of an existing name must not offer to create it")
    assert modal_state(wimi_page)["guardShown"] is False and not modal_state(wimi_page)["open"], (
        "the guard belongs to Quick Add and must not fire from the search box")

    # Now the guard itself, from a partial query so a creation row exists.
    _open_quick_add_with(wimi_page, "Shock", query="Sho")
    modal = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and m["guardShown"])
    assert modal["guardShown"], f"the guard did not appear for 'Shock': {modal!r}"
    rows = _guard_rows(wimi_page)
    assert len(rows) == 1 and rows[0]["id"] == str(shock_id), (
        f"one subject reached through two parents must be ONE row: {rows!r}")
    assert rows[0]["selects"] == 1, rows
    text = rows[0]["text"]
    assert ("under Cardiology and under Trauma" in text
            or "under Trauma and under Cardiology" in text), text
    assert text.startswith("A subject named 'Shock' already exists "), text

    wimi_page.locator(
        css=f'.quick-add-guard-select[data-subject-id="{shock_id}"]').click()
    closed = poll(wimi_page, lambda: modal_state(wimi_page), lambda m: m and not m["open"])
    assert not closed["open"], "Select it instead must close the dialog"
    assert selected(wimi_page)["primary"] == ["Shock"]
    assert wimi_page.eval_js("EntryState.formData.primarySubjects[0].id") == shock_id
    assert active_subject_count(db) == before, "Select it instead created a subject"
