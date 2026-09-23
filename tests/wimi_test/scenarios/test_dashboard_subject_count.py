"""Regression: dashboard exam card counted tree positions, not subjects.

Bug source: Forgejo issue #7 on the private tracker,
``[bug] Dashboard says "9 topics" where the tree editor says "6 subjects"``.

Quoting the report:

    For one exam, on the same data:

    - Dashboard exam card: ``SUBJECTS  9 topics``
    - Tree editor header: ``6 subjects`` [...]

    ``6`` is the node count. ``9`` is the number of *positions* — every
    parent→child edge plus the roots [...] So the dashboard is counting a
    shared subject once per parent.

    Needs at least one multi-parent subject — a single-parent tree makes
    the two counts agree and hides this.

Owner decision (2026-09-14): the dashboard changes. It shows the distinct
subject count and spells the unit "subjects", matching the tree editor.

Why it failed before the fix: ``DatabaseBridge.getExamContextStats``
walked ``get_subject_hierarchy`` and added 1 per visited node. That walk
is polyhierarchy-aware — a shared child appears once under *each* parent
— so the counter returned positions. The tree editor flattens the same
payload into ``TreeState.flatNodes``, a ``Map`` keyed by node id, so
duplicates collapse and its header reads the distinct count.

The seed below is the issue's reproducer verbatim: 6 nodes / 6 edges / 3
roots, one child under two parents and another under three. A
single-parent tree would make both surfaces agree by accident and this
scenario would pass vacuously, so the shared children are load-bearing —
the closing assertion pins the edge count for that reason.
"""

from __future__ import annotations

import re

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


# 6 distinct subjects in the seed (3 roots + 3 children); the pre-fix
# dashboard reported 9 positions (6 edges + 3 parentless roots).
_EXPECTED_SUBJECTS = 6
_PRE_FIX_POSITIONS = 9


def _count_in(text: str) -> int:
    """Pull the leading integer out of a stat string like ``"6 subjects"``."""
    match = re.search(r"\d+", text)
    assert match is not None, f"No number in stat text {text!r}"
    return int(match.group())


def _read_stat(page: WimiPage, testid: str) -> str:
    """Poll a stat element until its async-loaded value replaces the seed."""
    # TODO(Phase 3 / T3.6): replace with
    #     page.wait_for_bridge_call("getExamContextStats")
    locator = page.locator(testid=testid)
    text = ""
    for _ in range(40):
        try:
            text = locator.text().strip()
        except Exception:
            text = ""
        if text and not text.startswith("0 "):
            return text
        page.wait_for_timeout(250)
    return text


@pytest.mark.slow
@pytest.mark.regression
def test_dashboard_and_tree_editor_agree_on_subject_count(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Both surfaces must read the distinct subject count, spelled "subjects"."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 7 Polyhierarchy Repro",
        exam_description="Regression scenario for Forgejo issue #7",
    )

    def node(name: str, parent_id: int | None = None) -> int:
        return db.create_subject_node(
            exam_context=exam.exam_name,
            name=name,
            level_type="System" if parent_id is None else "Topic",
            parent_id=parent_id,
        ).id

    cardio = node("Issue7 Cardiovascular")
    preg = node("Issue7 Pregnancy")
    resp = node("Issue7 Respiratory")

    # hypertension: 2 parents. VTE: 3 parents. asthma: 1 parent.
    # create_subject_node inserts the primary edge; add_edge adds the rest.
    hypertension = node("Issue7 hypertension", cardio)
    db.add_edge(preg, hypertension)

    vte = node("Issue7 VTE", cardio)
    db.add_edge(preg, vte)
    db.add_edge(resp, vte)

    node("Issue7 asthma", resp)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("dashboard")
    dashboard_text = _read_stat(wimi_page, f"dashboard-exam-{exam.id}-subject-count")

    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    tree_text = _read_stat(wimi_page, "tree-node-count")

    # ---- Assert ------------------------------------------------------
    # Pre-fix the dashboard read "9 topics": the bridge counted every
    # appearance of a shared child, and the unit did not match the tree's.
    assert _count_in(dashboard_text) == _EXPECTED_SUBJECTS, (
        f"Dashboard exam card reads {dashboard_text!r}; expected "
        f"{_EXPECTED_SUBJECTS} distinct subjects. {_PRE_FIX_POSITIONS} means "
        "it is still counting tree positions (issue #7)."
    )
    assert _count_in(tree_text) == _EXPECTED_SUBJECTS, (
        f"Tree editor header reads {tree_text!r}; the seed has "
        f"{_EXPECTED_SUBJECTS} distinct subjects."
    )
    # Owner decision: the unit is spelled "subjects" on both.
    assert "subject" in dashboard_text.lower(), (
        f"Dashboard should spell the unit 'subjects', got {dashboard_text!r}."
    )
    assert "subject" in tree_text.lower(), (
        f"Tree editor should spell the unit 'subjects', got {tree_text!r}."
    )

    # Belt and braces: prove the seed really is a polyhierarchy, so the two
    # counts cannot have agreed by accident (6 edges + 3 roots = 9 positions).
    edge_count = db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_edges se "
        "JOIN subject_nodes sn ON sn.id = se.child_id "
        "WHERE sn.exam_context = ?",
        (exam.exam_name,),
    )["n"]
    assert edge_count == 6, (
        f"Seed drifted: expected 6 parent→child edges, found {edge_count}. "
        "Without a shared child this scenario passes vacuously."
    )
