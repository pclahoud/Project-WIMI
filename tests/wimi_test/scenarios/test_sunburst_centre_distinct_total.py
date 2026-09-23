"""Regression: the sunburst centre disagrees with the "Total Entries"
card on the same screen (Forgejo issue #6, Priority/Medium).

From the issue:

    The "By Subject" sunburst shows ``14`` above the word ``TOTAL`` in
    its centre, while the OVERVIEW card at the top of the same screen
    reads ``TOTAL ENTRIES 11``. Both are visible without scrolling.

``14`` is the sum of the per-parent rollups (``POLYHIERARCHY_MIGRATION``
§5.4): a shared subject counts under every parent it routes through, and
3 of the 11 entries are counted twice or three times. The owner's
decision (2026-09-14) keeps the arcs and changes the centre:

    The centre shows the distinct entry count (11). The arcs keep their
    overlapping per-parent values. [...] The arcs will therefore visibly
    sum to more than the centre. That is intended, not a rounding bug.

This scenario asserts **both halves in one run**, which is the point:
the centre and the arcs are now different numbers on purpose, so a
future change that "tidies" either one into agreement with the other
breaks this test rather than shipping.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM = "Issue 6 Sunburst Centre"

_TEXT_JS = (
    "(() => {{ const el = document.querySelector('{selector}'); "
    "return el ? el.textContent.trim() : null; }})()"
)


def _seed(db) -> dict:
    """The issue's "How to reproduce" seed, verbatim."""
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name=EXAM, exam_description="Issue #6")

    def node(name, parent=None, level="System"):
        return db.create_subject_node(
            exam_context=EXAM, name=name, level_type=level,
            parent_id=parent, sort_order=1,
        )

    cardio, preg, resp = node("Cardiovascular"), node("Pregnancy"), node("Respiratory")
    # The first parent passed is the canonical edge; the rest are extra.
    htn = node("hypertension", parent=cardio.id, level="Topic")
    db.add_edge(preg.id, htn.id, is_primary=False)
    vte = node("venous thromboembolism", parent=cardio.id, level="Topic")
    db.add_edge(preg.id, vte.id, is_primary=False)
    db.add_edge(resp.id, vte.id, is_primary=False)
    asthma = node("asthma", parent=resp.id, level="Topic")

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=11, total_incorrect=11,
        session_name="issue 6", date_encountered=date.today(),
    )
    order = iter(range(1, 100))

    def entries(subject_id, primary_parent_id, count):
        for _ in range(count):
            cur = db.execute(
                "INSERT INTO question_entries (review_session_id, entry_order, "
                "user_answer, correct_answer, is_draft) VALUES (?, ?, 'a', 'b', 0)",
                (session.id, next(order)),
            )
            db.execute(
                "INSERT INTO entry_subject_mappings (question_entry_id, "
                "subject_node_id, mapping_type, primary_parent_id) "
                "VALUES (?, ?, 'primary', ?)",
                (cur.lastrowid, subject_id, primary_parent_id),
            )

    entries(htn.id, cardio.id, 3)
    entries(htn.id, preg.id, 2)
    entries(htn.id, None, 1)
    entries(vte.id, preg.id, 2)
    entries(vte.id, None, 1)
    entries(asthma.id, None, 2)
    db.conn.commit()
    return {"exam_id": exam.id, "cardio": cardio.id, "preg": preg.id, "resp": resp.id}


def _poll_text(wimi_page: WimiPage, selector: str, attempts: int = 60) -> str | None:
    """Bounded poll — the dashboard's init() loads every card async."""
    text = None
    for _ in range(attempts):
        text = wimi_page.eval_js(_TEXT_JS.format(selector=selector))
        if text and text not in ("-", "0"):
            return text
        wimi_page.wait_for_timeout(250)
    return text


@pytest.mark.slow
@pytest.mark.regression
def test_sunburst_centre_agrees_with_card_while_arcs_stay_overlapping(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    ids = _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("analytics", query={"exam": ids["exam_id"]})
    centre = _poll_text(wimi_page, "#totalEntriesCenter")
    card = _poll_text(wimi_page, "#totalEntries")

    def legend(subject_id: int) -> str | None:
        return wimi_page.eval_js(_TEXT_JS.format(
            selector=f'[data-testid="analytics-subject-legend-{subject_id}"] .legend-count'
        ))

    # ---- Assert ------------------------------------------------------
    # The bug: the centre re-used the chart's summed ``value`` (14) under
    # a label reading TOTAL, inches below a card computing 11 a different
    # way. The centre now renders the payload's own distinct count.
    assert card == "11", f"'Total Entries' card reads {card!r}"
    assert centre == "11", f"sunburst centre reads {centre!r}, card reads {card!r}"

    # ...and the arcs are untouched. 5 + 6 + 3 = 14 > 11 because the three
    # undisambiguated entries route through more than one parent. The
    # decision forbids "fixing" these to sum to the centre.
    arcs = {name: legend(ids[key]) for name, key in
            (("Cardiovascular", "cardio"), ("Pregnancy", "preg"), ("Respiratory", "resp"))}
    assert arcs == {"Cardiovascular": "5", "Pregnancy": "6", "Respiratory": "3"}, arcs

    # The tooltip is what makes the mismatch honest rather than a bug
    # report. It must be in the DOM, not only in a CSS ::after.
    note = wimi_page.eval_js(_TEXT_JS.format(
        selector='[data-testid="analytics-sunburst-total-tooltip"]'
    ))
    assert note, "no explanatory tooltip next to the sunburst"
    assert "add up to more than" in note.lower(), f"tooltip text reads {note!r}"
