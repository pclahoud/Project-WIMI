"""Regression: a whole-exam import that gives an exam its first axis asks about
the subjects it already has (#605 Wave 2).

The owner's decisions (Forgejo #605, comments 12206 and 12211): the import
offers the move too (decision 2); a subject whose ``import_id`` the file
already holds keeps its existing copy outside the axes, with a note (decision
7); a name-only match moves anyway, with a note (decision 8); Escape and the
backdrop are Go back (decision 3). Before this, the import created the axis
and the student's own tree vanished from the tree editor, left in no axis
with only the panel to find it by (Wave 0, #605 comment 12257).

The dialog is the wizard's (``first_axis_dialog.js``, Wave 1), opened over the
import preview, so the stacked-modal case is checked here: the topmost dialog
holds focus and the preview behind it is hidden from assistive tech, and
Escape answers the dialog without closing the preview.

On master ``49eced4`` every test but the control fails: no dialog ever appears
(the tree editor does not load the module, and ``executeImport`` never asks).
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.a11y import real_key
from _helpers.axis_mode import (
    FIRST_AXIS_DIALOG, open_tree, poll, seed_exam, start_import, state,
    wait_for_first_axis_dialog, wait_import_done, wait_state,
)

ROW = '[data-testid="first-axis-row"]'
PANEL = '[data-testid="tree-unassigned-panel"]'
IMPORT_SLOTS = ("importSubjectHierarchy", "importSubjectHierarchyWithChoice")


def _import_calls(page: WimiPage, since: float) -> list[str]:
    return [c.get("method") for c in page.get_bridge_calls(since_ts=since)
            if c.get("method") in IMPORT_SLOTS]


def _panel_shown(page: WimiPage) -> bool:
    return page.eval_js(
        f"(() => {{ const p = document.querySelector({json.dumps(PANEL)});"
        " return !!p && p.getClientRects().length > 0; })()")


def _rows(page: WimiPage) -> list[dict]:
    return page.eval_js(
        f"[...document.querySelectorAll({json.dumps(ROW)})].map(r => ({{"
        " name: r.querySelector('.first-axis-row-name').textContent,"
        " notes: [...r.querySelectorAll('.first-axis-row-note')]"
        "   .map(n => n.textContent)}))")


def _stacking(page: WimiPage) -> dict:
    return page.eval_js(f"""(() => {{
        const surface = document.querySelector({json.dumps(FIRST_AXIS_DIALOG)});
        const preview = document.getElementById('import-preview-modal');
        return {{
            topmostIsDialog: !!surface && window.ModalDialog.topmost() === surface,
            focusInDialog: !!surface && surface.contains(document.activeElement),
            previewOpen: !!preview && preview.classList.contains('active'),
            previewHidden: !!preview && preview.getAttribute('aria-hidden') === 'true',
        }};
    }})()""")


def _preview_open(page: WimiPage) -> bool:
    return page.eval_js(
        "!!document.getElementById('import-preview-modal')"
        "?.classList.contains('active')")


def _dimension_of(db, node_id: int):
    return db.fetchone("SELECT dimension_id FROM subject_nodes WHERE id = ?",
                       (node_id,))["dimension_id"]


@pytest.mark.slow
@pytest.mark.regression
def test_a_move_lands_in_the_axis_view_without_a_reload(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, _, nodes = seed_exam(db, "W605 Move", {},
                                  plain=("Cardiology", "Renal"))
    open_tree(wimi_page, exam_id)
    assert state(wimi_page)["uses"] is False, "premise: the exam starts plain"

    since = wimi_page.mark_bridge_calls()
    start_import(wimi_page, {"dimensions": [
        {"name": "System", "root_nodes": [{"name": "Hematology"}]}]})
    assert wait_for_first_axis_dialog(wimi_page), (
        "no first-axis dialog: the import gave the exam its first axis "
        "without asking about Cardiology and Renal")

    rows = _rows(wimi_page)
    assert [r["name"] for r in rows] == ["Cardiology", "Renal"], rows
    stack = poll(wimi_page, lambda: _stacking(wimi_page),
                 lambda s: s["focusInDialog"] and s["previewHidden"])
    assert stack == {"topmostIsDialog": True, "focusInDialog": True,
                     "previewOpen": True, "previewHidden": True}, (
        f"stacked modals: the dialog must be topmost, hold focus and hide the "
        f"preview behind it: {stack}")
    assert _import_calls(wimi_page, since) == [], "imported before the answer"

    wimi_page.locator(css='[data-testid="first-axis-move"]').click()
    wait_import_done(wimi_page)

    after = wait_state(wimi_page, lambda s: s["uses"] and s["rows"] == [
        "Cardiology", "Hematology", "Renal"])
    assert after["uses"] is True and after["tabs"] == ["System"] \
        and after["rows"] == ["Cardiology", "Hematology", "Renal"], (
        f"the moved subjects are not drawn in the System view: {after}")
    assert poll(wimi_page, lambda: _panel_shown(wimi_page),
                lambda v: v is False) is False, (
        "the Subjects not in any axis panel is still shown after the move")
    assert not _preview_open(wimi_page), "the preview stayed open"

    system = db.fetchone(
        "SELECT id FROM exam_dimensions WHERE exam_id = ? AND name = 'System'",
        (exam_id,))["id"]
    assert _dimension_of(db, nodes["Cardiology"]) == system
    assert _dimension_of(db, nodes["Renal"]) == system
    assert _import_calls(wimi_page, since) == [
        "importSubjectHierarchyWithChoice"]


@pytest.mark.slow
@pytest.mark.regression
def test_an_import_id_clash_is_shown_kept_aside_with_its_note(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, _, nodes = seed_exam(db, "W605 Clash", {},
                                  plain=("Cardiology", "Renal"))
    db.execute("UPDATE subject_nodes SET import_id = 'sys-1' WHERE id = ?",
               (nodes["Cardiology"],))
    db.conn.commit()
    open_tree(wimi_page, exam_id)

    start_import(wimi_page, {"dimensions": [
        {"name": "System", "root_nodes": [
            {"name": "Cardiovascular", "id": "sys-1"}, {"name": "Renal"}]}]})
    assert wait_for_first_axis_dialog(wimi_page), "no first-axis dialog"

    rows = {r["name"]: r["notes"] for r in _rows(wimi_page)}
    assert rows["Cardiology"] == [
        "The file already contains this subject, so it stays outside the axes."
    ], rows
    assert rows["Renal"] == [
        "The file also has a subject called Renal in System."], rows

    wimi_page.locator(css='[data-testid="first-axis-move"]').click()
    wait_import_done(wimi_page)

    system = db.fetchone(
        "SELECT id FROM exam_dimensions WHERE exam_id = ? AND name = 'System'",
        (exam_id,))["id"]
    assert _dimension_of(db, nodes["Cardiology"]) is None, (
        "decision 7: the existing copy must stay outside the axes")
    assert _dimension_of(db, nodes["Renal"]) == system, (
        "decision 8: a name-only match moves anyway")
    assert poll(wimi_page, lambda: _panel_shown(wimi_page), bool) is True, (
        "the kept-aside subject is not listed in the panel")


@pytest.mark.slow
@pytest.mark.regression
def test_go_back_imports_nothing_and_leaves_the_preview_open(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam_id, _, _ = seed_exam(db, "W605 Back", {}, plain=("Cardiology",))
    open_tree(wimi_page, exam_id)

    since = wimi_page.mark_bridge_calls()
    start_import(wimi_page, {"dimensions": [
        {"name": "System", "root_nodes": [{"name": "Hematology"}]}]})
    assert wait_for_first_axis_dialog(wimi_page), "no first-axis dialog"
    poll(wimi_page, lambda: _stacking(wimi_page)["focusInDialog"], bool)

    # Escape is Go back (decision 3), and it answers the dialog only.
    real_key(wimi_page, "Escape")
    wait_import_done(wimi_page)
    assert not wimi_page.eval_js(
        f"!!document.querySelector({json.dumps(FIRST_AXIS_DIALOG)})"), (
        "Escape did not close the dialog")
    assert _preview_open(wimi_page), "Escape closed the import preview too"

    # The Go back button, from a second confirm on the same preview.
    wimi_page.eval_js(
        "window.__importDone = false;"
        " window.executeImport().then(() => { window.__importDone = true; })")
    assert wait_for_first_axis_dialog(wimi_page), (
        "a second confirm did not ask again")
    wimi_page.locator(css='[data-testid="first-axis-back"]').click()
    wait_import_done(wimi_page)

    assert _preview_open(wimi_page), "Go back closed the import preview"
    button = wimi_page.eval_js(
        "(() => { const b = document.getElementById('import-confirm-btn');"
        " return [b.disabled, b.textContent.trim()]; })()")
    assert button == [False, "Import"], f"confirm button left as {button}"
    assert _import_calls(wimi_page, since) == [], "Go back imported anyway"
    assert db.get_exam_dimensions(exam_id) == []


@pytest.mark.slow
@pytest.mark.regression
def test_no_dialog_when_the_exam_already_has_an_axis(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Control: only a FIRST axis asks. The file adds a second one here."""
    db = wimi_session.user.db
    exam_id, _, _ = seed_exam(db, "W605 Control", {"System": ["Renal"]},
                              plain=("Cardiology",))
    open_tree(wimi_page, exam_id)

    since = wimi_page.mark_bridge_calls()
    start_import(wimi_page, {"dimensions": [
        {"name": "System", "root_nodes": [{"name": "Renal"}]},
        {"name": "Task", "root_nodes": [{"name": "Diagnosis"}]}]})
    wait_import_done(wimi_page)

    assert not wimi_page.eval_js(
        f"!!document.querySelector({json.dumps(FIRST_AXIS_DIALOG)})")
    assert _import_calls(wimi_page, since) == ["importSubjectHierarchy"]
    after = wait_state(wimi_page, lambda s: "Task" in s["tabs"])
    assert after["tabs"] == ["System", "Task"], f"the import did not run: {after}"


@pytest.mark.slow
@pytest.mark.regression
def test_an_unreadable_offer_imports_nothing_and_says_so(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """If the question cannot be built, the import must not run.

    Importing without asking would quietly choose Keep them aside, against
    the owner's *ask each time, defaulting to moving them in*. The preview
    read is stubbed to fail for the preview's own load AND the confirm-time
    retry, so the offer is unreadable both times."""
    db = wimi_session.user.db
    exam_id, _, _ = seed_exam(db, "W605 Unreadable", {}, plain=("Cardiology",))
    open_tree(wimi_page, exam_id)
    wimi_page.eval_js(
        "window.__previewReads = 0;"
        " window.api.previewSubjectHierarchyImport = async () => {"
        "   window.__previewReads += 1;"
        "   throw new Error('stubbed preview failure'); };")

    since = wimi_page.mark_bridge_calls()
    start_import(wimi_page, {"dimensions": [
        {"name": "System", "root_nodes": [{"name": "Hematology"}]}]})
    wait_import_done(wimi_page)

    toast = poll(wimi_page, lambda: wimi_page.eval_js(
        "document.querySelector('.toast-container')?.textContent || ''"),
        lambda t: "Nothing was imported." in t)
    assert ("Nothing was imported. WIMI could not check the subjects this "
            "exam already has, so it could not ask where they go. Try the "
            "import again.") in toast, f"error toast read: {toast!r}"
    assert wimi_page.eval_js("window.__previewReads") >= 2, (
        "premise: the confirm-time retry did not run")
    assert not wimi_page.eval_js(
        f"!!document.querySelector({json.dumps(FIRST_AXIS_DIALOG)})"), (
        "a dialog was drawn without an offer")
    assert _import_calls(wimi_page, since) == [], (
        "the import ran although the question could not be asked")
    assert _preview_open(wimi_page), "the preview closed"
    assert db.get_exam_dimensions(exam_id) == []
