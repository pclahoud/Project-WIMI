"""CalendarMixin: planned sessions, series, starting, the range read, reminders
and the goal projection (#778 Wave 0).

Each test names the decision it pins (owner, 2026-10-12, #778 comments
#10729 and #10743). The two that matter most to the rest of WIMI:
``test_plans_add_nothing_to_total_sessions`` is the reason a plan is its own
table, and ``test_starting_a_plan_goes_through_create_review_session`` is
why #286's local-day guarantee holds for a started plan.
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta

import pytest

from database.exceptions import PlannedSessionError, ValidationError
from database.user_db import UserDatabase

TUE = date(2026, 10, 13)
WED = date(2026, 10, 14)


@pytest.fixture
def db(tmp_path):
    instance = UserDatabase(tmp_path / "cal.db", user_id=1, username="cal_user")
    yield instance
    try:
        instance.close()
    except Exception:
        pass


@pytest.fixture
def exam(db):
    return db.create_exam_context(exam_name="Step X")


@pytest.fixture
def bank(db, exam):
    return db.create_question_source(source_name="Bank A", exam_context=exam.exam_name)


# ---------------------------------------------------------------- create / read / update


@pytest.mark.database
def test_create_and_read_a_plain_plan(db, exam, bank):
    p = db.create_planned_session(WED, exam_context_id=exam.id, question_source_id=bank.id,
                                  title="Cardio", planned_start_time="09:00",
                                  planned_duration_minutes=60, planned_questions=40, notes="n")
    assert p["status"] == "planned" and p["planned_date"] == "2026-10-14"
    assert p["is_series"] is False and p["series_id"] is None
    assert len(p["uid"]) == 32 and p["review_session_id"] is None
    assert db.get_planned_session(p["id"])["title"] == "Cardio"
    assert db.get_planned_session(9999) is None


@pytest.mark.database
def test_exam_less_plans_are_allowed_and_scoped_by_user(db):
    """Owner decision 1."""
    p = db.create_planned_session("2026-10-14", title="Any exam")
    assert p["exam_context_id"] is None
    rows = db.fetchall("SELECT user_id FROM planned_sessions")
    assert [r["user_id"] for r in rows] == [1]


@pytest.mark.database
@pytest.mark.parametrize("kwargs, fragment", [
    ({"planned_start_time": "9am"}, "HH:MM"),
    ({"planned_start_time": "25:00"}, "24-hour"),
    ({"planned_duration_minutes": 0}, "between 1 and 1440"),
    ({"planned_questions": -1}, "above zero"),
    ({"exam_context_id": 777}, "not one of this profile's exams"),
    ({"goal_id": 777}, "not one of this profile's goals"),
    ({"recurrence_rule": "FREQ=DAILY"}, "FREQ=WEEKLY"),
])
def test_refusals_are_sentences(db, kwargs, fragment):
    with pytest.raises(PlannedSessionError) as exc:
        db.create_planned_session(WED, **kwargs)
    assert fragment in str(exc.value)


@pytest.mark.database
def test_a_bank_from_another_exam_is_refused_and_an_unbound_bank_is_not(db, exam, bank):
    other = db.create_exam_context(exam_name="Other")
    with pytest.raises(PlannedSessionError, match="different exam"):
        db.create_planned_session(WED, exam_context_id=other.id, question_source_id=bank.id)
    with pytest.raises(PlannedSessionError, match="choose the exam first"):
        db.create_planned_session(WED, question_source_id=bank.id)
    loose = db.create_question_source(source_name="Loose")
    assert db.create_planned_session(WED, exam_context_id=other.id, question_source_id=loose.id)["question_source_id"] == loose.id


@pytest.mark.database
def test_update_while_planned_and_frozen_after(db, exam):
    p = db.create_planned_session(WED, exam_context_id=exam.id, title="a")
    p = db.update_planned_session(p["id"], title="b", planned_date="2026-10-16", notes="x")
    assert (p["title"], p["planned_date"], p["notes"]) == ("b", "2026-10-16", "x")
    with pytest.raises(PlannedSessionError, match="Cannot change"):
        db.update_planned_session(p["id"], status="skipped")
    db.start_planned_session(p["id"], total_questions=5, total_incorrect=1)
    db.update_planned_session(p["id"], notes="after")        # notes still allowed
    with pytest.raises(PlannedSessionError, match="only its notes"):
        db.update_planned_session(p["id"], title="c")


@pytest.mark.database
def test_status_marks_and_their_limits(db, exam):
    p = db.create_planned_session(WED, exam_context_id=exam.id)
    assert db.set_planned_session_status(p["id"], "skipped")["status"] == "skipped"
    assert db.set_planned_session_status(p["id"], "planned")["status"] == "planned"
    with pytest.raises(PlannedSessionError, match="not 'started'"):
        db.set_planned_session_status(p["id"], "started")
    db.start_planned_session(p["id"], total_questions=5, total_incorrect=1)
    with pytest.raises(PlannedSessionError, match="was started"):
        db.set_planned_session_status(p["id"], "skipped")


@pytest.mark.database
def test_delete_removes_the_plan_but_never_the_real_session(db, exam):
    p = db.create_planned_session(WED, exam_context_id=exam.id)
    out = db.start_planned_session(p["id"], total_questions=5, total_incorrect=1)
    assert db.delete_planned_session(p["id"]) is True
    assert db.get_planned_session(p["id"]) is None
    assert db.get_review_session(out["review_session"].id) is not None
    with pytest.raises(PlannedSessionError, match="does not exist"):
        db.delete_planned_session(p["id"])


# ---------------------------------------------------------------- starting


@pytest.mark.database
def test_plans_add_nothing_to_total_sessions(db, exam):
    """The reason a plan is its own table: total_sessions is a row count."""
    for d in range(3):
        db.create_planned_session(WED + timedelta(days=d), exam_context_id=exam.id)
    assert db.get_analytics_overview()["total_sessions"] == 0


@pytest.mark.database
def test_starting_a_plan_goes_through_create_review_session(db, exam, bank):
    """One INSERT INTO review_sessions in the tree; the plan reuses it, so the
    local day, the generated name and the timer round all come with it.
    date_encountered defaults to the planned day (owner decision 4)."""
    yesterday = date.today() - timedelta(days=1)
    p = db.create_planned_session(yesterday, exam_context_id=exam.id, question_source_id=bank.id,
                                  planned_duration_minutes=45, title="Planned name")
    out = db.start_planned_session(p["id"], total_questions=20, total_incorrect=4)
    session = out["review_session"]
    assert session.date_encountered == yesterday
    assert session.session_name == "Planned name"
    assert session.question_source_id == bank.id
    assert out["planned"]["status"] == "started" and out["planned"]["review_session_id"] == session.id
    assert out["planned"]["started_at"] is not None
    rounds = db.fetchall("SELECT duration_minutes FROM session_timer_rounds WHERE review_session_id = ?", (session.id,))
    assert [r["duration_minutes"] for r in rounds] == [45]
    assert db.get_analytics_overview()["total_sessions"] == 1


@pytest.mark.database
def test_the_start_day_can_be_overridden(db, exam):
    p = db.create_planned_session(WED, exam_context_id=exam.id)
    out = db.start_planned_session(p["id"], total_questions=5, total_incorrect=1, date_encountered="2026-10-16")
    assert out["review_session"].date_encountered == date(2026, 10, 16)


@pytest.mark.database
def test_a_second_start_and_a_skipped_start_are_refused(db, exam):
    p = db.create_planned_session(WED, exam_context_id=exam.id)
    db.start_planned_session(p["id"], total_questions=5, total_incorrect=1)
    with pytest.raises(PlannedSessionError, match="already started as review session"):
        db.start_planned_session(p["id"], total_questions=5, total_incorrect=1)
    q = db.create_planned_session(WED, exam_context_id=exam.id)
    db.set_planned_session_status(q["id"], "skipped")
    with pytest.raises(PlannedSessionError, match="mark it planned again"):
        db.start_planned_session(q["id"], total_questions=5, total_incorrect=1)


@pytest.mark.database
def test_an_exam_less_plan_needs_an_exam_to_start(db, exam):
    p = db.create_planned_session(WED, title="free")
    with pytest.raises(PlannedSessionError, match="no exam"):
        db.start_planned_session(p["id"], total_questions=5, total_incorrect=1)
    out = db.start_planned_session(p["id"], total_questions=5, total_incorrect=1, exam_context_id=exam.id)
    assert out["planned"]["exam_context_id"] == exam.id
    assert out["review_session"].exam_context_id == exam.id


@pytest.mark.database
def test_deleting_the_real_session_leaves_an_honest_started_plan(db, exam):
    p = db.create_planned_session(WED, exam_context_id=exam.id)
    out = db.start_planned_session(p["id"], total_questions=5, total_incorrect=1)
    db.execute("DELETE FROM review_sessions WHERE id = ?", (out["review_session"].id,))
    db.conn.commit()
    plan = db.get_planned_session(p["id"])
    assert plan["status"] == "started" and plan["review_session_id"] is None


# ---------------------------------------------------------------- series (owner decision 2)


@pytest.mark.database
def test_a_series_expands_on_read_and_stores_one_row(db, exam):
    s = db.create_planned_session(TUE, exam_context_id=exam.id,
                                  recurrence_rule="freq=weekly;byday=TU,TH;count=4", title="Series")
    assert s["recurrence_rule"] == "FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4" and s["is_series"] is True
    rng = db.get_calendar_range(date(2026, 10, 12), date(2026, 11, 8))
    dates = [p["planned_date"] for p in rng["planned"]]
    assert dates == ["2026-10-13", "2026-10-15", "2026-10-20", "2026-10-22"]
    assert all(p["id"] is None and p["series_id"] == s["id"] for p in rng["planned"])
    assert db.fetchone("SELECT COUNT(*) AS n FROM planned_sessions")["n"] == 1


@pytest.mark.database
def test_starting_an_occurrence_materialises_only_that_date(db, exam):
    s = db.create_planned_session(TUE, exam_context_id=exam.id, recurrence_rule="FREQ=WEEKLY;BYDAY=TU;COUNT=3")
    with pytest.raises(PlannedSessionError, match="occurrence_date"):
        db.start_planned_session(s["id"], total_questions=5, total_incorrect=1)
    out = db.start_planned_session(s["id"], total_questions=5, total_incorrect=1, occurrence_date="2026-10-20")
    assert out["review_session"].date_encountered == date(2026, 10, 20)
    rng = db.get_calendar_range(date(2026, 10, 12), date(2026, 11, 8))
    by_date = {p["planned_date"]: p for p in rng["planned"]}
    assert by_date["2026-10-20"]["status"] == "started" and by_date["2026-10-20"]["id"] is not None
    assert by_date["2026-10-20"]["series_id"] == s["id"]
    assert by_date["2026-10-13"]["status"] == "planned" and by_date["2026-10-13"]["id"] is None
    assert db.fetchone("SELECT COUNT(*) AS n FROM planned_sessions")["n"] == 2
    assert [x["planned_session_id"] for x in rng["sessions"]] == [by_date["2026-10-20"]["id"]]


@pytest.mark.database
def test_an_occurrence_off_the_rule_is_refused_and_marking_the_series_is_refused(db, exam):
    s = db.create_planned_session(TUE, exam_context_id=exam.id, recurrence_rule="FREQ=WEEKLY;BYDAY=TU")
    with pytest.raises(PlannedSessionError, match="not a day this series falls on"):
        db.materialise_occurrence(s["id"], "2026-10-14")
    with pytest.raises(PlannedSessionError, match="one occurrence of a series"):
        db.set_planned_session_status(s["id"], "skipped")
    occ = db.materialise_occurrence(s["id"], "2026-10-20")
    assert db.set_planned_session_status(occ["id"], "skipped")["status"] == "skipped"
    assert db.materialise_occurrence(s["id"], "2026-10-20")["id"] == occ["id"]


@pytest.mark.database
def test_deleting_a_series_removes_its_materialised_occurrences(db, exam):
    s = db.create_planned_session(TUE, exam_context_id=exam.id, recurrence_rule="FREQ=WEEKLY;BYDAY=TU")
    db.materialise_occurrence(s["id"], "2026-10-20")
    db.delete_planned_session(s["id"])
    assert db.fetchone("SELECT COUNT(*) AS n FROM planned_sessions")["n"] == 0


# ---------------------------------------------------------------- the range read


@pytest.mark.database
def test_range_carries_sessions_with_their_plan_entry_counts_and_exam_dates(db, exam):
    db.update_exam_context_settings(exam.id, exam_date=date(2026, 10, 30), color_hex="#aabbcc")
    p = db.create_planned_session(WED, exam_context_id=exam.id)
    out = db.start_planned_session(p["id"], total_questions=5, total_incorrect=1)
    db.create_review_session(exam_context_id=exam.id, date_encountered=date(2026, 10, 20),
                             total_questions=10, total_incorrect=2)
    rng = db.get_calendar_range("2026-10-01", "2026-10-31")
    assert [(s["date_encountered"], s["planned_session_id"]) for s in rng["sessions"]] == [
        ("2026-10-14", p["id"]), ("2026-10-20", None)]
    assert rng["exam_dates"] == [{"exam_context_id": exam.id, "exam_name": "Step X",
                                  "exam_date": "2026-10-30", "color_hex": "#aabbcc"}]
    assert rng["entry_counts"] == []
    assert rng["range"] == {"start": "2026-10-01", "end": "2026-10-31"}
    assert out["planned"]["id"] == p["id"]


@pytest.mark.database
def test_range_refuses_a_reversed_or_huge_window(db):
    with pytest.raises(PlannedSessionError, match="ends before it starts"):
        db.get_calendar_range("2026-10-20", "2026-10-13")
    with pytest.raises(PlannedSessionError, match="at most 800 days"):
        db.get_calendar_range("2026-01-01", "2028-06-01")


@pytest.mark.database
def test_range_filters_by_exam_including_series(db, exam):
    other = db.create_exam_context(exam_name="Other")
    db.create_planned_session(WED, exam_context_id=exam.id)
    db.create_planned_session(WED, exam_context_id=other.id)
    db.create_planned_session(TUE, exam_context_id=other.id, recurrence_rule="FREQ=WEEKLY;BYDAY=TU")
    rng = db.get_calendar_range("2026-10-12", "2026-10-18", exam_context_id=exam.id)
    assert len(rng["planned"]) == 1 and rng["planned"][0]["exam_context_id"] == exam.id


# ---------------------------------------------------------------- reminders (owner decisions 3 and 7)


@pytest.mark.database
def test_reminders_report_today_and_overdue_from_a_python_local_date(db, exam):
    db.create_planned_session("2026-10-10", exam_context_id=exam.id, title="missed")
    db.create_planned_session("2026-10-14", exam_context_id=exam.id, title="today")
    db.create_planned_session("2026-10-15", exam_context_id=exam.id, title="tomorrow")
    skipped = db.create_planned_session("2026-10-09", exam_context_id=exam.id, title="skipped")
    db.set_planned_session_status(skipped["id"], "skipped")
    db.create_planned_session("2026-10-06", exam_context_id=exam.id, recurrence_rule="FREQ=WEEKLY;BYDAY=TU", title="weekly")
    rem = db.get_session_reminders(today=WED)
    assert rem["today"] == "2026-10-14"
    assert [p["title"] for p in rem["due_today"]] == ["today"]
    assert [(p["title"], p["planned_date"]) for p in rem["overdue"]] == [
        ("weekly", "2026-10-06"), ("missed", "2026-10-10"), ("weekly", "2026-10-13")]


@pytest.mark.database
def test_a_missed_plan_stays_planned_until_the_student_acts(db, exam):
    """Owner decision 3: nothing auto-flips. Reading reminders twice changes
    no row."""
    db.create_planned_session("2026-10-10", exam_context_id=exam.id)
    before = db.fetchall("SELECT status, updated_at FROM planned_sessions")
    db.get_session_reminders(today=WED)
    db.get_session_reminders(today=WED)
    assert db.fetchall("SELECT status, updated_at FROM planned_sessions") == before


# ---------------------------------------------------------------- goal projection (owner decision 5, reading b)


@pytest.mark.database
def test_goal_summary_recounts_and_stores_nothing(db, exam):
    goal = db.set_weekly_goal(target_questions=20, exam_context_id=exam.id)
    goal_id = goal["goal_id"] if "goal_id" in goal else goal["id"]
    monday = WED - timedelta(days=WED.weekday())
    db.create_planned_session(WED, exam_context_id=exam.id, goal_id=goal_id, planned_questions=10)
    db.create_planned_session(monday + timedelta(days=5), exam_context_id=exam.id, planned_questions=15)
    db.create_planned_session(monday - timedelta(days=1), exam_context_id=exam.id, planned_questions=99)  # last week
    periods_before = db.fetchall("SELECT * FROM goal_periods")
    s = db.get_goal_plan_summary(goal_id, today=WED)
    assert (s["period_start"], s["period_end"]) == (monday.isoformat(), (monday + timedelta(days=6)).isoformat())
    assert s["target_value"] == 20 and s["current_value"] == 0
    assert s["planned_sessions_remaining"] == 2 and s["planned_questions_remaining"] == 25
    assert db.fetchall("SELECT * FROM goal_periods") == periods_before
    with pytest.raises(PlannedSessionError):
        db.get_goal_plan_summary(999)


# ---------------------------------------------------------------- exam colour (owner decision 9)


@pytest.mark.database
def test_exam_colour_is_validated_normalised_and_clearable(db, exam):
    assert exam.color_hex is None
    assert db.update_exam_context_settings(exam.id, color_hex=" #AABBCC ").color_hex == "#aabbcc"
    with pytest.raises(ValidationError, match="#rrggbb"):
        db.update_exam_context_settings(exam.id, color_hex="red")
    assert db.update_exam_context_settings(exam.id, clear_color=True).color_hex is None


# ---------------------------------------------------------------- a real logger


@pytest.mark.database
def test_every_calendar_write_path_survives_a_real_logger(tmp_path):
    """The unit fixtures pass error_logger=None, so guarded log calls never
    run under them (CLAUDE.md logging invariant 2). Attach a real logger and
    exercise each write once."""
    from app_logging import ErrorLogger
    logger = ErrorLogger(app_name="CalendarWriteTest", log_dir=tmp_path / "logs", flush_interval=60.0)
    db = UserDatabase(tmp_path / "cal_logged.db", user_id=1, username="u", error_logger=logger)
    try:
        exam = db.create_exam_context(exam_name="E")
        t = db.create_session_template("T", exam_context_id=exam.id)
        p = db.create_planned_session(WED, template_id=t["id"])
        db.update_planned_session(p["id"], title="x")
        s = db.create_planned_session(TUE, exam_context_id=exam.id, recurrence_rule="FREQ=WEEKLY;BYDAY=TU")
        db.materialise_occurrence(s["id"], "2026-10-20")
        db.set_planned_session_status(p["id"], "skipped")
        db.set_planned_session_status(p["id"], "planned")
        db.start_planned_session(p["id"], total_questions=3, total_incorrect=1)
        db.update_session_template(t["id"], name="T2")
        db.archive_session_template(t["id"])
        db.delete_planned_session(s["id"])
    finally:
        db.close()
        logger.cleanup()
