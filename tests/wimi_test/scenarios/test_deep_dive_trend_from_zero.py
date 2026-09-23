"""Regression: deep-dive trend banner reads "↑ 0%" when a subject grows
from zero (Forgejo issue #11, Priority/Low).

From the issue:

    with THIS WEEK: 9 and LAST WEEK: 0, the trend banner reads
    ``Change: +9 (↑ 0% - Need more review)``. The +9 is right; the 0%
    is not. Same on hypertension (+6, ↑ 0%) and VTE (+3, ↑ 0%): three
    subjects, three different +N, identical 0%.

The percentage is week-over-week *relative to last week*, so it is
undefined when last week had no entries. ``renderInfoAndTrend`` in
``src/web/js/subject_deep_dive.js`` used to fall back to ``0`` in that
branch, which rendered as "no change" beside a "+9" that said
otherwise. The fix drops the figure when last week is zero and keeps
the arrow, the signed count and the label; when last week is
non-zero the percentage is unchanged (second test).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_BANNER_JS = (
    "(() => { const el = document.querySelector("
    "'[data-testid=\"deep-dive-trend-change\"]'); "
    "return el ? el.textContent.trim() : null; })()"
)
_CARD_JS = (
    "(() => {{ const el = document.querySelector("
    "'[data-testid=\"deep-dive-trend-{which}-value\"]'); "
    "return el ? el.textContent.trim() : null; }})()"
)


def _seed(db, exam_name: str, subject_name: str, per_day: dict[date, int]) -> tuple[int, int]:
    """Create an exam + one subject and tag ``per_day[d]`` entries on it
    in a review session dated ``d``. Returns ``(subject_id, exam_id)``."""
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name=exam_name, exam_description="Issue #11")
    node = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name=subject_name, level_type="System",
        exam_weight_low=10, exam_weight_high=10, weight_source="user_defined",
    )
    ec_id = db.fetchone("SELECT id FROM exam_contexts WHERE exam_name = ?", (exam.exam_name,))["id"]
    for day, count in per_day.items():
        cur = db.execute(
            "INSERT INTO review_sessions (user_id, session_name, date_encountered, "
            "exam_context_id, total_questions, total_incorrect) VALUES (?, ?, ?, ?, ?, ?)",
            (db.user_id, f"#11 {day.isoformat()}", day.isoformat(), ec_id, count, count),
        )
        for order in range(1, count + 1):
            c = db.execute(
                "INSERT INTO question_entries (review_session_id, entry_order, user_answer, "
                "correct_answer) VALUES (?, ?, 'A', 'B')", (cur.lastrowid, order),
            )
            db.execute(
                "INSERT INTO entry_subject_mappings (question_entry_id, subject_node_id, "
                "mapping_type) VALUES (?, ?, 'primary')", (c.lastrowid, node.id),
            )
    db.conn.commit()
    return node.id, ec_id


def _open_deep_dive(wimi_page: WimiPage, subject_id: int, exam_id: int) -> str:
    wimi_page.goto("subject-deep-dive", query={"subject": subject_id, "exam": exam_id})
    banner = None
    for _ in range(40):  # bounded poll; the page's init() is async
        banner = wimi_page.eval_js(_BANNER_JS)
        if banner and (banner.startswith("Change:") or banner.startswith("No change")):
            return banner
        wimi_page.wait_for_timeout(250)
    pytest.fail(f"Trend banner never rendered; last text {banner!r}")


def _week_bounds() -> tuple[date, date]:
    """Same anchoring as ``get_subject_deep_dive``: Monday of this week,
    and a day that lands inside last week's ``[start-7, start)`` window."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    return today, week_start - timedelta(days=1)


@pytest.mark.slow
@pytest.mark.regression
def test_growth_from_zero_has_no_percentage(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    """THIS WEEK 9 / LAST WEEK 0 renders +9 with an arrow but no percentage."""
    # ---- Arrange -----------------------------------------------------
    today, _ = _week_bounds()
    subject_id, exam_id = _seed(wimi_session.user.db, "Issue 11 Growth", "I11 Sepsis", {today: 9})

    # ---- Act ---------------------------------------------------------
    banner = _open_deep_dive(wimi_page, subject_id, exam_id)
    this_week = wimi_page.eval_js(_CARD_JS.format(which="thisweek"))
    last_week = wimi_page.eval_js(_CARD_JS.format(which="lastweek"))

    # ---- Assert ------------------------------------------------------
    assert (this_week, last_week) == ("9", "0"), f"cards read {this_week!r}/{last_week!r}"
    assert "+9" in banner, f"signed count missing from banner: {banner!r}"
    assert "↑" in banner and "Need more review" in banner, f"arrow/label lost: {banner!r}"
    # The bug: a division-by-zero guard returned 0, so the banner read
    # "↑ 0%" beside "+9". Growth from zero has no percentage at all.
    assert "%" not in banner, f"banner still shows a percentage for growth from zero: {banner!r}"


@pytest.mark.slow
@pytest.mark.regression
def test_growth_from_nonzero_keeps_percentage(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    """THIS WEEK 9 / LAST WEEK 6 still renders the real +50% figure."""
    # ---- Arrange -----------------------------------------------------
    today, last_week_day = _week_bounds()
    subject_id, exam_id = _seed(
        wimi_session.user.db, "Issue 11 Nonzero", "I11 Hypertension", {today: 9, last_week_day: 6},
    )

    # ---- Act ---------------------------------------------------------
    banner = _open_deep_dive(wimi_page, subject_id, exam_id)
    this_week = wimi_page.eval_js(_CARD_JS.format(which="thisweek"))
    last_week = wimi_page.eval_js(_CARD_JS.format(which="lastweek"))

    # ---- Assert ------------------------------------------------------
    # Guards the fix's scope: only the last_week == 0 case loses the
    # figure; a real week-over-week ratio is still shown.
    assert (this_week, last_week) == ("9", "6"), f"cards read {this_week!r}/{last_week!r}"
    assert "+3" in banner and "50%" in banner, f"expected '+3 (↑ 50% ...' in banner: {banner!r}"
