"""The deep dive says which axis it is showing, links its exam, and does
not report a trend when nothing happened (#314, owner 2026-10-10).

Three items, grouped in the issue because they are all *the page states
something that does not mean what it appears to*.

1. **The heading never said which axis a subject was on.** On a
   multi-dimensional exam the title read "18 to 65" and "Full path: 18 to
   65" repeated it, because a dimension root has nothing above it. Nothing
   said it was a **Patient Age** group rather than a topic or a Site of
   Care value.

2. **The exam name was a <span> styled as a button that did nothing.** It
   is a real link now. The owner chose this over restyling it as plain
   text, which matters beyond taste: plain text is the option that would
   have reached for ``--text-muted`` and so waited on #326, and a link
   keeps the existing emphasis instead of reducing it.

3. **"No change from last week" with both weeks at zero.** A 0-vs-0
   comparison fell into the same branch as a genuine 4-vs-4, so a subject
   whose last mistake was 122 days ago reported no change -- in a
   highlighted box, which implies something is being tracked and is
   steady. #289's and #174's class.

Why item 3 is a third BRANCH and not a reworded string: the two states
have to stay distinguishable to anything reading the page later, and a
copy change merges them again the moment somebody wants to style,
announce or count them separately. The test asserts both texts for that
reason -- a mutant that returns the new string unconditionally fails the
second case.

**Positive controls.** An assertion that a qualifier is absent passes
against a page that never rendered (#121), so the dimensionless case
asserts the title rendered the subject's own name first. And the axis
case asserts the qualifier's *text*, not merely its presence, because an
empty revealed span satisfies presence.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``): ``_loader.js``
aliases it and deletes the source handle.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

AXIS_NAME = "Patient Age"
AXIS_SUBJECT = "18 to 65"
PLAIN_SUBJECT = "Cardiovascular System"


def _poll(wimi_page: WimiPage, read, predicate, *, timeout_ms: int = 20000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if predicate(last):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _title(wimi_page: WimiPage):
    return wimi_page.eval_js(
        "(() => { const el = document.querySelector("
        "'[data-testid=\"deep-dive-subject-title\"]');"
        " return el ? el.textContent.trim() : null; })()")


def _dimension(wimi_page: WimiPage):
    return wimi_page.eval_js(
        "(() => { const el = document.querySelector("
        "'[data-testid=\"deep-dive-subject-dimension\"]');"
        " if (!el) return null;"
        " return {text: el.textContent.trim(),"
        "         shown: el.getClientRects().length > 0}; })()")


def _seed_dimensioned(db):
    """An exam with one axis, one subject in it, and one subject outside."""
    db._ensure_phase2_schema()
    exam = db.create_exam_context(
        exam_name="Axis Exam 314",
        exam_description="#314 - the heading must name the axis",
    )
    axis = db.create_dimension(
        exam_id=exam.id, name=AXIS_NAME, display_order=1)
    in_axis = db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, dimension_id, sort_order, status) "
        "VALUES (?, ?, 'System', ?, 0, 'active')",
        (exam.exam_name, AXIS_SUBJECT, axis),
    ).lastrowid
    outside = db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, dimension_id, sort_order, status) "
        "VALUES (?, ?, 'System', NULL, 1, 'active')",
        (exam.exam_name, PLAIN_SUBJECT),
    ).lastrowid
    db.conn.commit()
    return exam.id, in_axis, outside


@pytest.mark.slow
@pytest.mark.regression
def test_the_heading_names_the_axis_and_says_nothing_when_there_is_none(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    exam_id, in_axis, outside = _seed_dimensioned(wimi_session.user.db)

    # ---- A subject in an axis: the qualifier is drawn and names it.
    wimi_page.goto("subject-deep-dive",
                   query={"subject": in_axis, "exam": exam_id})
    assert _poll(wimi_page, lambda: _title(wimi_page),
                 lambda t: t == AXIS_SUBJECT) == AXIS_SUBJECT, (
        "the deep dive never rendered the subject title")

    dim = _poll(wimi_page, lambda: _dimension(wimi_page),
                lambda d: isinstance(d, dict) and d.get("shown"))
    assert dim and dim["shown"], (
        f"'{AXIS_SUBJECT}' is a {AXIS_NAME} group and the page says so "
        f"nowhere: {dim!r}")
    assert AXIS_NAME in dim["text"], (
        f"the qualifier is drawn but does not name the axis: {dim!r}")

    # ---- A subject in NO axis: nothing is drawn, and the title still is.
    # The title assertion is the positive control -- without it this passes
    # against a page that failed to load (#121).
    wimi_page.goto("subject-deep-dive",
                   query={"subject": outside, "exam": exam_id})
    assert _poll(wimi_page, lambda: _title(wimi_page),
                 lambda t: t == PLAIN_SUBJECT) == PLAIN_SUBJECT, (
        "the deep dive never rendered the second subject's title")

    dim = _dimension(wimi_page)
    assert dim is not None, "the qualifier element should exist, hidden"
    assert not dim["shown"], (
        f"a subject in no axis must carry no axis qualifier: {dim!r}")
    assert dim["text"] == "", (
        f"the hidden qualifier still holds text, which would be announced "
        f"if it were ever revealed: {dim!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_the_exam_name_is_a_link_that_goes_to_the_exam(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """It was a <span> bordered like a button and inert on click."""
    exam_id, in_axis, _ = _seed_dimensioned(wimi_session.user.db)

    wimi_page.goto("subject-deep-dive",
                   query={"subject": in_axis, "exam": exam_id})

    label = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "(() => { const el = document.querySelector("
            "'[data-testid=\"deep-dive-exam-label\"]');"
            " if (!el) return null;"
            " return {tag: el.tagName.toLowerCase(),"
            "         text: el.textContent.trim(),"
            "         href: el.getAttribute('href'),"
            "         cursor: getComputedStyle(el).cursor}; })()"),
        lambda d: isinstance(d, dict) and d.get("text") not in (None, "", "Loading..."),
    )
    assert label, "the exam label never rendered"

    assert label["tag"] == "a", (
        f"the exam name must be a real link, not a <{label['tag']}> styled "
        f"like one: {label!r}")
    assert label["href"], f"the link has no destination: {label!r}"
    assert f"exam_id={exam_id}" in label["href"], (
        "the tree editor reads `exam_id`; `exam` is the analytics and entry "
        f"browser key and yields 'No exam ID provided': {label['href']!r}")
    assert label["cursor"] == "pointer", (
        f"it looks like a control but does not act like one: {label!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_two_empty_weeks_report_no_activity_rather_than_no_change(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """0-vs-0 is not a trend, and 4-vs-4 still is.

    Both are asserted. A mutant that returns the new string
    unconditionally passes the first case and fails the second, which is
    what makes this a test of the BRANCH rather than of the copy.
    """
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    exam = db.create_exam_context(
        exam_name="Quiet Exam 314",
        exam_description="#314 item 3 - nothing happened is not no change",
    )
    quiet = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="Dormant Topic",
        level_type="System", exam_weight_low=10, exam_weight_high=10,
        weight_source="user_defined")
    steady = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="Steady Topic",
        level_type="System", exam_weight_low=10, exam_weight_high=10,
        weight_source="user_defined")
    ec_id = db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = ?",
        (exam.exam_name,))["id"]

    # `steady` gets one entry this week and one in last week's window, so
    # its change is 0 with both weeks non-zero -- the real "no change".
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    for when in (today, week_start - timedelta(days=1)):
        s = db.execute(
            "INSERT INTO review_sessions (user_id, session_name, "
            "date_encountered, exam_context_id, total_questions, "
            "total_incorrect) VALUES (?, 'S', ?, ?, 1, 1)",
            (db.user_id, when.isoformat(), ec_id),
        ).lastrowid
        e = db.execute(
            "INSERT INTO question_entries (review_session_id, entry_order, "
            "user_answer, correct_answer) VALUES (?, 1, 'A', 'B')", (s,),
        ).lastrowid
        db.execute(
            "INSERT INTO entry_subject_mappings "
            "(question_entry_id, subject_node_id, mapping_type) "
            "VALUES (?, ?, 'primary')", (e, steady.id))
    db.conn.commit()

    read_banner = lambda: wimi_page.eval_js(  # noqa: E731
        "(() => { const el = document.querySelector("
        "'[data-testid=\"deep-dive-trend-change\"]');"
        " return el ? el.textContent.trim() : null; })()")

    # The banner's markup placeholder is "-", which is a non-empty string
    # and will satisfy any "has it rendered yet" predicate at t=0. Waiting
    # for a SETTLED prefix is what makes this a read of the render rather
    # than of the markup -- the same trap as polling for an element's
    # existence instead of its content (#672).
    settled = lambda t: isinstance(t, str) and t.startswith(  # noqa: E731
        ("Change:", "No change", "No activity"))

    # ---- Nothing ever happened on this subject.
    wimi_page.goto("subject-deep-dive",
                   query={"subject": quiet.id, "exam": exam.id})
    quiet_banner = _poll(wimi_page, read_banner, settled)
    assert quiet_banner == "No activity this week or last", (
        "a subject with nothing in either week must not report a trend: "
        f"{quiet_banner!r}")

    # ---- Genuinely unchanged: one entry each week.
    wimi_page.goto("subject-deep-dive",
                   query={"subject": steady.id, "exam": exam.id})
    steady_banner = _poll(
        wimi_page, read_banner,
        lambda t: isinstance(t, str) and t.startswith("No change"))
    assert steady_banner == "No change from last week", (
        "1 this week against 1 last week IS no change, and must still say "
        f"so: {steady_banner!r}")
