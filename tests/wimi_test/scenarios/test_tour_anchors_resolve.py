"""Every real tour step on a wired page renders in some reachable state (#430).

The owner decided on 2026-10-09 that a step is shown once its target is on
screen. So a step need not resolve in every state, but it must resolve in
**some** state a student can reach, or it can never be shown and the page
teaches less than its chapter claims. Measured on the dashboard: a true first
run can point at 1 of its 5 steps, one active exam at 3, Top mistake needs an
entry, and Delete exists only on a suspended exam.

Which pages are checked comes from the runner's own call sites
(`tests/test_tour_wiring.py: wired_pages`), not from a list kept here. Each
wired page needs a set of seeded states below, and a wired page without one
FAILS, so the second page cannot be wired without being checked. The reverse
fails too: states for a page that no longer starts its tour.

The states are seeded through the database and the anchors read in a real
WIMI, because every dashboard anchor is drawn by `landing.js` or
`analytics_preview.js`. A markup search would find none of them.
"""
from __future__ import annotations

from datetime import date

import pytest

from _helpers.analytics_tour_seed import seed_analytics_tour_exam
from _helpers.w114_form_ready import FORM_READY, poll, seed_session_with_draft
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from tests.test_tour_wiring import all_steps, wired_pages


def _no_exams(db) -> None:
    pass


def _one_active_exam_with_an_entry(db) -> None:
    seed_session_with_draft(db, name="Tour state")


def _a_suspended_exam(db) -> None:
    exam = db.create_exam_context(exam_name="Tour suspended", exam_description="")
    db.conn.execute("UPDATE exam_contexts SET is_active = 0 WHERE id = ?", (exam.id,))
    db.conn.commit()


def _an_exam_with_no_sessions(db) -> dict:
    exam = db.create_exam_context(exam_name="Tour setup, empty", exam_description="")
    db.conn.commit()
    return {"exam_id": exam.id}


def _an_exam_with_an_unfinished_session(db) -> dict:
    """In progress with 0 of 3 entries, so its card offers Continue, the
    control step 4 teaches. A complete or abandoned one offers Review."""
    exam = db.create_exam_context(exam_name="Tour setup, unfinished", exam_description="")
    db.create_review_session(exam_context_id=exam.id, total_questions=20,
                             total_incorrect=3, session_name="Tour unfinished",
                             date_encountered=date.today())
    db.conn.commit()
    return {"exam_id": exam.id}


def _an_exam_with_a_finished_session(db) -> dict:
    """One finished entry of one, so the card offers Review, and the Edit
    modal's Questions Incorrect field carries its step: lowering it can delete
    entries only once something is logged."""
    exam = db.create_exam_context(exam_name="Tour setup, finished", exam_description="")
    subject = db.create_subject_node(exam_context="Tour setup, finished", name="Cardio",
                                     level_type="System")
    session = db.create_review_session(exam_context_id=exam.id, total_questions=20,
                                       total_incorrect=1, session_name="Tour finished",
                                       date_encountered=date.today())
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        reflection="<p>R</p>", explanation="<p>E</p>", primary_subject_ids=[subject.id])
    assert not entry.is_draft
    db.conn.commit()
    return {"exam_id": exam.id}


_WIZARD_NEXT = "document.querySelector('#btn-next').click();"


def _wizard_to(step: str) -> str:
    """The student's Next presses on the Simple path, from Choose Exam Type to
    `step`. Each press is synchronous (nextStep -> updateUI), so one script
    walks the whole way: Start from Scratch on the template step, and an exam
    name before leaving Exam Information, which is the one field it needs."""
    path = [_WIZARD_NEXT,                                                # -> template
            "document.getElementById('template-scratch').click();" + _WIZARD_NEXT,  # -> info
            "document.getElementById('exam-name').value = 'Tour wizard';" + _WIZARD_NEXT,  # -> hierarchy
            _WIZARD_NEXT,                                                # -> length
            _WIZARD_NEXT,                                                # -> weights
            _WIZARD_NEXT]                                                # -> review
    stops = {"step-1-template": 1, "step-2": 2, "step-exam-length": 4, "step-5": 6}
    return "".join(path[:stops[step]])


def _settings_panel(panel: str) -> str:
    """The student's click on a Settings sidebar item."""
    return (f"document.querySelector('.settings-nav-item[data-panel=\"{panel}\"]')"
            ".click();")


def _a_question_bank_with_an_address(db) -> None:
    """A bank row gains its Desktop site switch only once it has an address."""
    db.create_question_source(source_name="Tour bank", url="https://example.org")
    db.conn.commit()


def _an_exam_with_an_entry_to_browse(db, name: str = "Tour browse") -> dict:
    session_id, _ = seed_session_with_draft(db, name=name)
    exam_id = db.conn.execute("SELECT exam_context_id FROM review_sessions WHERE id = ?",
                              (session_id,)).fetchone()[0]
    return {"exam": exam_id}


def _a_weighted_tree(db, name: str, deleted: bool = False) -> dict:
    """Weighted roots and a subject under two parents; optionally one subject
    deleted, which is the only thing that shows the Archived subjects panel."""
    exam = db.create_exam_context(exam_name=name, exam_description="")

    def subject(title, level, low, high, parent=None):
        return db.create_subject_node_with_weight(
            exam_context=name, name=title, level_type=level, parent_id=parent,
            exam_weight_low=low, exam_weight_high=high)

    cardiology = subject("Cardiology", "System", 10, 20)
    nephrology = subject("Nephrology", "System", 15, 25)
    shared = subject("Hypertension", "Topic", 5, 8, cardiology.id)
    db.add_edge(nephrology.id, shared.id, is_primary=False)
    if deleted:
        doomed = subject("Renal artery stenosis", "Topic", 1, 2, nephrology.id)
        db.conn.commit()
        db.delete_subject_subtree(doomed.id)
    db.conn.commit()
    return {"exam_id": exam.id}


def _a_dimensioned_exam(db) -> dict:
    exam = db.create_exam_context(exam_name="Tour tree axes", exam_description="")
    axis = db.create_dimension(exam_id=exam.id, name="System", display_order=1,
                               is_required=True)
    db.create_subject_node(exam_context="Tour tree axes", name="Cardio",
                           level_type="System", dimension_id=axis)
    db.conn.commit()
    return {"exam_id": exam.id}


def _a_parent_with_a_child_of_its_own(db) -> dict:
    """One root whose only child has no other parent, which is what grows the
    delete modal's Keep checkbox. Collapsed, the root is the only row, so the
    first row's buttons are its own."""
    name = "Tour tree delete"
    exam = db.create_exam_context(exam_name=name, exam_description="")
    cardiology = db.create_subject_node_with_weight(
        exam_context=name, name="Cardiology", level_type="System",
        exam_weight_low=10, exam_weight_high=20)
    db.create_subject_node_with_weight(
        exam_context=name, name="Heart failure", level_type="Topic",
        parent_id=cardiology.id)
    db.conn.commit()
    return {"exam_id": exam.id}


def _a_shared_subject_with_a_relative_weight(db) -> dict:
    """The details panel's richest state (#682): a subject whose weight is a
    share of its parent (so the weight panel shows Relative, the anchor box and,
    with the exam's length set, the Q toggle), with a sibling, and with a
    second parent that is not primary (so its row carries the circle)."""
    name = "Tour tree panel"
    exam = db.create_exam_context(exam_name=name, exam_description="")
    db.update_exam_length(exam.id, kind="fixed", min=100, max=100, typical=100)
    # Dimensioned on purpose: the plain load path drops relative_weight, so
    # Relative mode cannot appear there (#454).
    axis = db.create_dimension(exam_id=exam.id, name="System", display_order=1,
                               is_required=True)
    cardiology = db.create_subject_node_with_weight(
        exam_context=name, name="Cardiology", level_type="System",
        exam_weight_low=10, exam_weight_high=20, dimension_id=axis)
    nephrology = db.create_subject_node_with_weight(
        exam_context=name, name="Nephrology", level_type="System",
        exam_weight_low=15, exam_weight_high=25, dimension_id=axis)
    for title, share in (("Hypertension", 50.0), ("Heart failure", 25.0)):
        child = db.create_subject_node_with_weight(
            exam_context=name, name=title, level_type="Topic",
            parent_id=cardiology.id, relative_weight=share, weight_source="user_defined",
            dimension_id=axis)
        db.conn.execute("UPDATE subject_edges SET relative_weight = ? "
                        "WHERE parent_id = ? AND child_id = ?",
                        (share, cardiology.id, child.id))
        if title == "Hypertension":
            db.add_edge(nephrology.id, child.id, is_primary=False)
    db.conn.commit()
    return {"exam_id": exam.id}


#: Selecting a subject is the student's click into the details panel. The
#: weight panel loads after it, and keeps the PREVIOUS subject's markup until
#: then, so the state is settled on content naming this subject (#346's
#: measuring hazard), never on an element existing.
_SELECT_HYPERTENSION = (
    "selectNode([...TreeState.flatNodes.values()]"
    ".find(n => n.name === 'Hypertension').id);")
_PANEL_SETTLED_ON_HYPERTENSION = (
    "(() => { const w = document.getElementById('weight-modal-child-name');"
    " return !!w && w.textContent.trim() === 'Hypertension'"
    " && !!document.querySelector('[data-tour-anchor=\"tree-parent-make-primary\"]'); })()")


def _a_draft_entry(db) -> dict:
    session_id, _ = seed_session_with_draft(db, name="Tour entry")
    return {"session_id": session_id}


def _a_draft_on_a_shared_subject(db) -> dict:
    """A draft whose primary subject has two parents, which is the only thing
    that mounts the tag-context pill. Loading the draft draws its chips."""
    exam = db.create_exam_context(exam_name="Tour entry shared", exam_description="")

    def subject(title, level, parent=None):
        return db.create_subject_node_with_weight(
            exam_context="Tour entry shared", name=title, level_type=level, parent_id=parent)

    cardiology = subject("Cardiology", "System")
    nephrology = subject("Nephrology", "System")
    shared = subject("Hypertension", "Topic", cardiology.id)
    db.add_edge(nephrology.id, shared.id, is_primary=False)
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=3,
        session_name="Tour entry shared", date_encountered=date.today())
    db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        question_id="Q-TOUR", reflection="<p>R</p>", primary_subject_ids=[shared.id])
    db.conn.commit()
    return {"session_id": session.id}


def _a_timed_draft_with_a_note_and_an_image(db) -> dict:
    """A timed session, which is the only thing that draws the timer and its
    Pause button, holding a draft that carries a note and an image, which are
    what draw a note card's Delete and a thumbnail's Delete."""
    exam = db.create_exam_context(exam_name="Tour entry timed", exam_description="")
    subject = db.create_subject_node(exam_context="Tour entry timed", name="Cardio",
                                     level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=3,
        session_name="Tour entry timed", date_encountered=date.today(),
        session_duration_minutes=30)
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        reflection="<p>R</p>")
    assert entry.is_draft
    db.add_entry_note(entry.id, content_html="<p>A note</p>")
    db.add_entry_media(entry.id, "no-such-file-uuid", original_filename="tour.png",
                       mime_type="image/png", file_size_bytes=10,
                       linked_subject_ids=[subject.id])
    db.conn.commit()
    return {"session_id": session.id}


#: The student picks a file in the operating system's dialog, which CDP cannot
#: drive, so this hands the page's own handler the File that dialog would. The
#: file then goes through the real reader, validator and planner. It is a third
#: kind of action beside a click: still the student's input, never a stub.
_PREVIEW_A_WHOLE_EXAM_FILE = (
    "(() => { const f = new File([JSON.stringify({dimensions: [{name: 'System',"
    " root_nodes: [{name: 'Cardio'}]}]})], 'whole.json', {type: 'application/json'});"
    " window.handleImportFileEnhanced({target: {files: [f], value: 'whole.json'}}); })();")

#: Five levels deep, one more than the preview draws, so it ends in the
#: "... and 1 more nested node" line the preview's tour step points at.
_PREVIEW_A_FIVE_LEVEL_FILE = (
    "(() => { const n = (name, c) => c ? {name, children: [c]} : {name};"
    " const f = new File([JSON.stringify({root_nodes: [n('A', n('B', n('C', n('D', n('E')))))]})],"
    " 'deep.json', {type: 'application/json'});"
    " window.handleImportFileEnhanced({target: {files: [f], value: 'deep.json'}}); })();")


#: Per wired page: the states a student can reach, as (name, seeder, route),
#: plus an optional fourth element: an in-page action, run once the page has
#: settled, and an optional fifth: a predicate polled after the action, for a
#: view that loads asynchronously once it is opened. A seeder may return the
#: route's query (session setup needs ``exam_id``).
#:
#: THE ACTION IS NAVIGATION, NOT SEEDING. It is the click a student makes to
#: reach a view the page shows without a new document (a Settings panel, a
#: wizard step). The data still comes from the seeder. A stubbed bridge call
#: would be seeding by another route, and is not what this slot is for (see
#: the unknown-state note below).
#:
#: IF YOUR PAGE HAS A FORK, check what it paints while its predicate is
#: UNKNOWN (data not loaded, or a failed load). The runner folds unknown into
#: false and points at the unforked anchor (`anchorFor` in tour.js). The
#: dashboard is safe because its failed load paints neither side, so the step
#: waits. If your page's unknown state paints the unforked anchor, the tour
#: would state the no-X case while the truth is unknown (#289, #174). The fix
#: is a runner change, not a seeder. That state is a failed bridge call, not a
#: database state, so it is deliberately not seeded here.
def _a_week_with_a_logged_and_a_planned_session(db) -> None:
    """One chip of each kind on today, so the grid, the Plan button and a
    populated legend (hidden with no exams) are all on screen (#778)."""
    exam = db.create_exam_context(exam_name="Tour calendar", exam_description="")
    db.create_review_session(exam_context_id=exam.id, total_questions=10,
                             total_incorrect=2, session_name="Tour logged",
                             date_encountered=date.today())
    db.create_planned_session(date.today(), exam_context_id=exam.id, title="Tour planned")
    db.conn.commit()


STATES: dict[str, list[tuple]] = {
    "calendar": [
        ("a week with a logged and a planned session",
         _a_week_with_a_logged_and_a_planned_session, "calendar"),
    ],
    "dashboard": [
        ("no exams", _no_exams, "dashboard"),
        ("an active exam with an entry", _one_active_exam_with_an_entry, "dashboard"),
        ("a suspended exam", _a_suspended_exam, "dashboard"),
    ],
    "exam-wizard": [
        ("Choose Exam Type, on load", _no_exams, "exam-wizard"),
        ("Choose a Template", _no_exams, "exam-wizard", _wizard_to("step-1-template")),
        ("Exam Information", _no_exams, "exam-wizard", _wizard_to("step-2")),
        ("Exam Length", _no_exams, "exam-wizard", _wizard_to("step-exam-length")),
        ("Review & Create", _no_exams, "exam-wizard", _wizard_to("step-5")),
    ],
    "session-setup": [
        ("an exam with no sessions", _an_exam_with_no_sessions, "session-setup"),
        ("an exam with an unfinished session", _an_exam_with_an_unfinished_session,
         "session-setup"),
        # Edit is the student's click that opens the modal holding the field.
        ("a finished session, Edit open", _an_exam_with_a_finished_session, "session-setup",
         "document.querySelector('.prev-session-actions [onclick^=\"editSession\"]').click();"),
    ],
    "entry-browser": [
        ("an exam with an entry", _an_exam_with_an_entry_to_browse, "entry-browser"),
        ("the Subject filter panel open",
         lambda db: _an_exam_with_an_entry_to_browse(db, name="Tour browse panel"), "entry-browser",
         "document.getElementById('subjectFilterBtn').click();"),
        # Export IDs is the student's click that shows the selection toolbar.
        ("selection mode, after Export IDs",
         lambda db: _an_exam_with_an_entry_to_browse(db, name="Tour browse select"),
         "entry-browser", "document.getElementById('enterSelectionBtn').click();"),
    ],
    "settings": [
        ("the Appearance panel, on load", _no_exams, "settings"),
        ("the Question Banks panel, a bank with an address", _a_question_bank_with_an_address,
         "settings", _settings_panel("question_banks")),
        ("the Data & Backup panel", _no_exams, "settings", _settings_panel("data_backup")),
        ("the MCP Server panel", _no_exams, "settings", _settings_panel("mcp_server")),
        ("the Profile panel", _no_exams, "settings", _settings_panel("profile")),
        ("the Addons panel", _no_exams, "settings", _settings_panel("addons")),
        ("an exam chosen for Per-Exam Analytics", _an_exam_with_no_sessions, "settings",
         _settings_panel("dashboard_analytics")
         + "(() => { const s = document.getElementById('analytics_exam_selector');"
           " s.selectedIndex = 1; s.dispatchEvent(new Event('change')); })();"),
    ],
    # The draft's chips are drawn as it loads; the pill only for a primary
    # subject with two parents; the timer only for a timed session; a note
    # card's and a thumbnail's Delete only for a draft that carries one.
    "entry-form": [
        ("a draft entry", _a_draft_entry, "entry-form"),
        ("a draft on a shared subject", _a_draft_on_a_shared_subject, "entry-form"),
        ("a timed session, a draft with a note and an image",
         _a_timed_draft_with_a_note_and_an_image, "entry-form"),
    ],
    # Rows are collapsed on load, and the shared-parents chip sits on a child,
    # so Expand All is the student's click that reaches it.
    "tree-editor": [
        ("a weighted tree, expanded", lambda db: _a_weighted_tree(db, "Tour tree"),
         "tree-editor", "expandAll();"),
        # Opening the panel is the click that shows its Restore buttons.
        ("a deleted subject, the Archived panel opened",
         lambda db: _a_weighted_tree(db, "Tour tree deleted", deleted=True), "tree-editor",
         "document.getElementById('archived-panel-toggle').click();"),
        ("a whole-exam file in the import preview", _a_dimensioned_exam, "tree-editor",
         _PREVIEW_A_WHOLE_EXAM_FILE),
        ("a file deeper than the preview draws",
         lambda db: _a_weighted_tree(db, "Tour tree deep file"), "tree-editor",
         _PREVIEW_A_FIVE_LEVEL_FILE),
        # A row's + and bin are the student's clicks into the two modals.
        ("the Add Child modal",
         lambda db: _a_weighted_tree(db, "Tour tree add child"), "tree-editor",
         "document.querySelector('[data-testid^=\"tree-node-add-child-\"]').click();"),
        ("the delete modal, for a subject with a child of its own",
         _a_parent_with_a_child_of_its_own, "tree-editor",
         "document.querySelector('[data-testid^=\"tree-node-delete-\"]').click();"),
        ("the details panel, a shared subject with a relative weight",
         _a_shared_subject_with_a_relative_weight, "tree-editor",
         _SELECT_HYPERTENSION, _PANEL_SETTLED_ON_HYPERTENSION),
    ],
    # Every analytics card is drawn on load, empty states included, so one
    # state reached the first seven steps (measured, #430 comment #9434).
    # #682's steps on the cross-dimension key, Interaction Effects and the
    # weight card need two dimensions, weights and entries on them.
    "analytics": [
        ("an exam with an entry", _one_active_exam_with_an_entry, "analytics"),
        ("two dimensions, weights and lopsided mistakes",
         lambda db: seed_analytics_tour_exam(db, "Tour analytics axes"), "analytics"),
    ],
}

READY = {
    # Released on every exit of init(); isLoading is cleared in the same place.
    "calendar": ("(() => { const g = document.querySelector('[data-page-gated]');"
                 " return !!g && !g.hasAttribute('inert') && !!window.CalendarState"
                 " && window.CalendarState.isLoading === false; })()"),
    "dashboard": ("(() => { try { return LandingState.isLoading === false"
                  " && LandingState.hasExams !== null; } catch (e) { return false; } })()"),
    # Released in a `finally` after both loaders resolve (session_setup.js).
    # The wizard is not gated; the template cards load asynchronously.
    "exam-wizard": ("(() => { try { return !!examWizard.currentConfig"
                    " && (examWizard.templates || []).length > 0; }"
                    " catch (e) { return false; } })()"),
    "session-setup": ("(() => { try { return SessionState.isPageReady === true; }"
                      " catch (e) { return false; } })()"),
    # Released at the end of init(), after every loader (settings.js).
    # Released in init()'s `finally`, after loadInitialData() (entry_browser.js).
    "entry-browser": ("(() => { try { return entryBrowser.isPageReady === true; }"
                      " catch (e) { return false; } })()"),
    "settings": ("(() => { try { return settingsPage.isPageReady === true; }"
                 " catch (e) { return false; } })()"),
    # Released by markEntryFormReady(), after the editors report ready (#114).
    "entry-form": FORM_READY,
    # Released in initializeTreeEditor()'s `finally`, after both load paths.
    "tree-editor": ("(() => { try { return TreeState.isPageReady === true; }"
                    " catch (e) { return false; } })()"),
    # Set at the end of init(), after every card and both visibility passes.
    "analytics": ("(() => { try { return window.dashboard.isReady === true; }"
                  " catch (e) { return false; } })()"),
}


@pytest.mark.slow
@pytest.mark.regression
def test_every_wired_page_has_seeded_states():
    missing = sorted(set(wired_pages()) - set(STATES))
    assert not missing, (
        f"{missing} start a tour but have no states here, so nothing checks "
        f"that their steps can ever be shown. Add a seeder per reachable state")


@pytest.mark.slow
@pytest.mark.regression
def test_every_seeded_page_is_wired():
    """The other direction. A page whose start() call was removed keeps
    passing its resolve check here, which then certifies a tour nobody sees."""
    unwired = sorted(set(STATES) - set(wired_pages()))
    assert not unwired, (
        f"{unwired} have states here but no WimiTour.start() call, so their "
        f"tour is checked and never shown")


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("page", sorted(STATES))
def test_every_step_resolves_in_some_reachable_state(
    wimi_session: WimiTestSession, wimi_page: WimiPage, page: str,
) -> None:
    steps = all_steps()[page]
    db = wimi_session.user.db
    resolved: dict[str, list[str]] = {}
    forks = {s["fork"] for s in steps if s.get("fork")}
    # Per state, each fork predicate's value, read from the page itself.
    predicate_in: dict[str, dict[str, bool]] = {}
    for name, seed, route, *action in STATES[page]:
        wimi_page.goto(route, query=seed(db))
        assert poll(wimi_page, READY[page], timeout_ms=30000), f"{page} never settled"
        if action:
            wimi_page.eval_js(action[0])
        if len(action) > 1:
            assert poll(wimi_page, action[1], timeout_ms=15000), (
                f"{page}, {name!r}: the view the action opens never settled")
        wimi_page.wait_for_timeout(500)  # Quick Analytics renders after the exams
        predicate_in[name] = {f: wimi_page.eval_js(f"WimiTour.predicateValue({f!r})")
                              for f in forks}
        for row in wimi_page.eval_js(f"WimiTour.inspect('{page}')"):
            for anchor in filter(None, (row["anchor"], row["fork_anchor"])):
                if wimi_page.eval_js(f"!!WimiTour.resolveAnchor({anchor!r})"):
                    resolved.setdefault(anchor, []).append(name)

    # A fork must fork: its unforked side resolves where the predicate is
    # false and its forked side where it is true. Both resolving in one state
    # alone would pass the check below while selecting nothing, and this is
    # also the control on the predicate's value, read through its second reader.
    for step in (s for s in steps if s.get("fork")):
        fork = step["fork"]
        when_false = [n for n in resolved.get(step["anchor"], [])
                      if predicate_in[n][fork] is False]
        when_true = [n for n in resolved.get(step["fork_anchor"], [])
                     if predicate_in[n][fork] is True]
        assert when_false and when_true, (
            f"{page}'s fork on {fork!r} does not fork: {step['anchor']!r} "
            f"resolved where it is false in {when_false}, {step['fork_anchor']!r} "
            f"where it is true in {when_true}. Predicate by state: {predicate_in}")

    expected = {a for s in steps for a in (s["anchor"], s.get("fork_anchor")) if a}
    never = sorted(expected - set(resolved))
    assert not never, (
        f"On {page}, these anchors rendered in none of "
        f"{[s[0] for s in STATES[page]]}, so their steps can never be shown: "
        f"{never}. Resolved: {resolved}")
