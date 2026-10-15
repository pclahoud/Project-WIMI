"""Calendar and scheduling domain mixin (#778, Wave 0).

Composed into :class:`UserDatabase`. Owns ``planned_sessions`` and
``session_templates`` (m033) and the one read the calendar page needs,
:meth:`get_calendar_range`.

Decisions this module encodes (owner, 2026-10-12, #778 comments #10729 and
#10743; the plan is ``docs/planning/CALENDAR_SCHEDULING_IMPLEMENTATION_PLAN.md``):

- **A plan is its own row, never a ``review_sessions`` row.** Starting a plan
  goes through :meth:`SessionsMixin.create_review_session`, the single
  ``INSERT INTO review_sessions`` in the tree, so #286's local-day guarantee
  and the timer round come for free, and ``total_sessions`` counts nothing
  until a session really exists.
- **Exam-less plans are allowed** (``exam_context_id`` nullable); scoping is
  by ``user_id``.
- **Weekly recurrence is expanded on read**, never stored
  (:mod:`._calendar_recurrence`). A series row carries ``recurrence_rule``;
  an occurrence the student starts, skips or edits is *materialised* as a
  child row with ``recurrence_parent_id`` and the occurrence's date, and that
  child then shadows the generated occurrence for that date.
- **A missed plan stays ``planned`` and reads as overdue** until the student
  acts; nothing here flips state on a timer (#382's rule).
- **Starting a past-dated plan writes ``date_encountered = planned_date``**
  unless the caller overrides it; the streak and heatmap read that column.
- **The goal link is a display projection** (#70, #71 untouched):
  :meth:`get_goal_plan_summary` recounts and stores nothing.

Dates: ``planned_date`` is the student's LOCAL calendar day, handled as
:class:`datetime.date` in Python and compared in Python. Nothing here uses
SQLite's ``date('now')``, which is UTC (#286).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from app_logging import ErrorCategory

from ..exceptions import PlannedSessionError
from ._calendar_recurrence import (
    RecurrenceRuleError,
    WeeklyRule,
    expand_weekly,
    parse_rrule,
)

_PLAN_STATUSES = ("planned", "started", "skipped", "cancelled")
_EDITABLE_WHILE_PLANNED = (
    "title", "planned_date", "planned_start_time", "planned_duration_minutes",
    "planned_questions", "question_source_id", "goal_id", "notes",
    "exam_context_id", "recurrence_rule",
)
_TEMPLATE_FIELDS = (
    "question_source_id", "name", "default_start_time",
    "default_duration_minutes", "default_questions", "notes",
)


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d is not None else None


def _as_date(value: Any, what: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise PlannedSessionError(f"{what} must be a date written YYYY-MM-DD, not {value!r}") from None
    raise PlannedSessionError(f"{what} must be a date, not {type(value).__name__}")


def _check_time(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise PlannedSessionError(f"a start time is written HH:MM, not {value!r}")
    hh, mm = value[:2], value[3:]
    if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        raise PlannedSessionError(f"a start time is written HH:MM on a 24-hour clock, not {value!r}")
    return value


def _check_minutes(value: Optional[int], what: str) -> Optional[int]:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1440:
        raise PlannedSessionError(f"{what} must be a whole number of minutes between 1 and 1440")
    return value


def _check_positive(value: Optional[int], what: str) -> Optional[int]:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PlannedSessionError(f"{what} must be a whole number above zero")
    return value


class CalendarMixin:
    """Planned sessions, templates, the calendar range read and reminders."""

    # ------------------------------------------------------------- validation

    def _calendar_check_exam(self, exam_context_id: Optional[int]) -> None:
        if exam_context_id is None:
            return
        exam = self.get_exam_context_config(exam_context_id)
        if exam is None or exam.user_id != self.user_id:
            raise PlannedSessionError(f"Exam {exam_context_id} is not one of this profile's exams")

    def _calendar_check_source(self, question_source_id: Optional[int],
                               exam_context_id: Optional[int]) -> None:
        if question_source_id is None:
            return
        source = self.get_question_source(question_source_id)
        if source is None or source.user_id != self.user_id:
            raise PlannedSessionError(f"Question bank {question_source_id} does not exist")
        if exam_context_id is None:
            raise PlannedSessionError("A question bank belongs to an exam; choose the exam first")
        # question_sources links to an exam by NAME (`exam_context`, a
        # VARCHAR), not by id; a source with no exam name serves any exam.
        if source.exam_context and not self._calendar_source_fits_exam(source, exam_context_id):
            raise PlannedSessionError(
                f"Question bank {question_source_id} belongs to a different exam")

    def _calendar_source_fits_exam(self, source, exam_context_id: int) -> bool:
        exam = self.get_exam_context_config(exam_context_id)
        return bool(exam) and (not source.exam_context or source.exam_context == exam.exam_name)

    def _calendar_check_goal(self, goal_id: Optional[int]) -> None:
        if goal_id is None:
            return
        row = self.fetchone("SELECT id FROM user_goals WHERE id = ? AND user_id = ?",
                            (goal_id, self.user_id))
        if row is None:
            raise PlannedSessionError(f"Goal {goal_id} is not one of this profile's goals")

    def _calendar_check_template(self, template_id: Optional[int]) -> Optional[Dict[str, Any]]:
        if template_id is None:
            return None
        row = self.fetchone("SELECT * FROM session_templates WHERE id = ? AND user_id = ?",
                            (template_id, self.user_id))
        if row is None:
            raise PlannedSessionError(f"Template {template_id} is not one of this profile's templates")
        return row

    @staticmethod
    def _calendar_check_rule(rule: Optional[str], start: date) -> Optional[str]:
        if rule is None or rule == "":
            return None
        try:
            parsed = parse_rrule(rule)
        except RecurrenceRuleError as e:
            raise PlannedSessionError(str(e)) from None
        return parsed.to_rrule(start)

    # ------------------------------------------------------------- planned sessions

    def create_planned_session(
        self,
        planned_date: Any,
        *,
        exam_context_id: Optional[int] = None,
        question_source_id: Optional[int] = None,
        template_id: Optional[int] = None,
        goal_id: Optional[int] = None,
        title: Optional[str] = None,
        planned_start_time: Optional[str] = None,
        planned_duration_minutes: Optional[int] = None,
        planned_questions: Optional[int] = None,
        notes: Optional[str] = None,
        recurrence_rule: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a plan, or a weekly series when ``recurrence_rule`` is given.

        A template supplies any field the caller left ``None``. Every refusal
        is a :class:`PlannedSessionError` sentence, never an ``IntegrityError``
        from three frames down (#66 2.2).
        """
        day = _as_date(planned_date, "planned_date")
        template = self._calendar_check_template(template_id)
        if template is not None:
            if exam_context_id is None:
                exam_context_id = template["exam_context_id"]
            if question_source_id is None:
                question_source_id = template["question_source_id"]
            if planned_start_time is None:
                planned_start_time = template["default_start_time"]
            if planned_duration_minutes is None:
                planned_duration_minutes = template["default_duration_minutes"]
            if planned_questions is None:
                planned_questions = template["default_questions"]
            if title is None:
                title = template["name"]
        self._calendar_check_exam(exam_context_id)
        self._calendar_check_source(question_source_id, exam_context_id)
        self._calendar_check_goal(goal_id)
        start_time = _check_time(planned_start_time)
        duration = _check_minutes(planned_duration_minutes, "planned_duration_minutes")
        questions = _check_positive(planned_questions, "planned_questions")
        rule = self._calendar_check_rule(recurrence_rule, day)
        with self.transaction():
            cur = self.execute(
                "INSERT INTO planned_sessions (uid, user_id, exam_context_id, question_source_id, "
                "template_id, goal_id, recurrence_rule, title, planned_date, planned_start_time, "
                "planned_duration_minutes, planned_questions, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, self.user_id, exam_context_id, question_source_id,
                 template_id, goal_id, rule, title, day.isoformat(), start_time,
                 duration, questions, notes),
            )
            new_id = cur.lastrowid
        if self.error_logger:
            self.error_logger.info(f"Planned session {new_id} created for {day.isoformat()}",
                                   category=ErrorCategory.DATABASE)
        return self.get_planned_session(new_id)

    def get_planned_session(self, planned_id: int) -> Optional[Dict[str, Any]]:
        row = self.fetchone("SELECT * FROM planned_sessions WHERE id = ? AND user_id = ?",
                            (planned_id, self.user_id))
        return self._plan_dict(row) if row else None

    def _plan_dict(self, row: Dict[str, Any], *, occurrence_date: Optional[date] = None) -> Dict[str, Any]:
        """A plan row as the page sees it. A generated (unmaterialised)
        occurrence of a series is the series row with ``id`` None,
        ``series_id`` set and ``planned_date`` the occurrence's date."""
        out = dict(row)
        out["is_series"] = bool(row.get("recurrence_rule"))
        out["series_id"] = row.get("recurrence_parent_id")
        if occurrence_date is not None:
            out["id"] = None
            out["series_id"] = row["id"]
            out["planned_date"] = occurrence_date.isoformat()
            out["is_series"] = False
            out["recurrence_rule"] = None
            out["review_session_id"] = None
            out["status"] = "planned"
            out["started_at"] = None
        return out

    def _plan_row_or_raise(self, planned_id: int) -> Dict[str, Any]:
        row = self.fetchone("SELECT * FROM planned_sessions WHERE id = ? AND user_id = ?",
                            (planned_id, self.user_id))
        if row is None:
            raise PlannedSessionError(f"Planned session {planned_id} does not exist")
        return row

    def update_planned_session(self, planned_id: int, **fields: Any) -> Dict[str, Any]:
        """Change a plan that has not been started. Once ``status`` is anything
        but ``planned``, only ``notes`` may change: the plan is a record of
        what happened by then."""
        row = self._plan_row_or_raise(planned_id)
        unknown = set(fields) - set(_EDITABLE_WHILE_PLANNED)
        if unknown:
            raise PlannedSessionError(f"Cannot change {', '.join(sorted(unknown))} on a planned session")
        if row["status"] != "planned" and set(fields) - {"notes"}:
            raise PlannedSessionError(
                f"Planned session {planned_id} is {row['status']}; only its notes can change now")
        if "recurrence_rule" in fields and row["recurrence_parent_id"] is not None:
            raise PlannedSessionError("An occurrence cannot carry its own recurrence rule; edit the series")
        merged = {**row, **fields}
        day = _as_date(merged["planned_date"], "planned_date")
        self._calendar_check_exam(merged["exam_context_id"])
        self._calendar_check_source(merged["question_source_id"], merged["exam_context_id"])
        self._calendar_check_goal(merged["goal_id"])
        values = {
            "title": merged["title"],
            "planned_date": day.isoformat(),
            "planned_start_time": _check_time(merged["planned_start_time"]),
            "planned_duration_minutes": _check_minutes(merged["planned_duration_minutes"], "planned_duration_minutes"),
            "planned_questions": _check_positive(merged["planned_questions"], "planned_questions"),
            "question_source_id": merged["question_source_id"],
            "goal_id": merged["goal_id"],
            "notes": merged["notes"],
            "exam_context_id": merged["exam_context_id"],
            "recurrence_rule": self._calendar_check_rule(merged["recurrence_rule"], day),
        }
        with self.transaction():
            self.execute(
                "UPDATE planned_sessions SET " + ", ".join(f"{k} = ?" for k in values)
                + " WHERE id = ?",
                tuple(values.values()) + (planned_id,),
            )
        return self.get_planned_session(planned_id)

    def set_planned_session_status(self, planned_id: int, status: str) -> Dict[str, Any]:
        """``skipped``, ``cancelled``, or back to ``planned``. ``started`` is
        written only by :meth:`start_planned_session`."""
        if status not in ("planned", "skipped", "cancelled"):
            raise PlannedSessionError(
                f"A plan can be marked planned, skipped or cancelled here, not {status!r}; "
                "start it through start_planned_session")
        row = self._plan_row_or_raise(planned_id)
        if row["status"] == "started":
            raise PlannedSessionError(f"Planned session {planned_id} was started; it cannot be re-marked")
        if row["recurrence_rule"]:
            raise PlannedSessionError("Mark one occurrence of a series, not the series itself")
        with self.transaction():
            self.execute("UPDATE planned_sessions SET status = ? WHERE id = ?", (status, planned_id))
        return self.get_planned_session(planned_id)

    def delete_planned_session(self, planned_id: int) -> bool:
        """Delete a plan, or a whole series with its materialised occurrences
        (``recurrence_parent_id ... ON DELETE CASCADE``). The real session a
        started plan created is untouched: it is the student's study."""
        self._plan_row_or_raise(planned_id)
        with self.transaction():
            cur = self.execute("DELETE FROM planned_sessions WHERE id = ? AND user_id = ?",
                               (planned_id, self.user_id))
        return cur.rowcount > 0

    # ------------------------------------------------------------- recurrence

    def materialise_occurrence(self, series_id: int, occurrence_date: Any) -> Dict[str, Any]:
        """Give one generated occurrence of a series its own row, so it can be
        started, skipped or edited. Returns the existing row if the date was
        already materialised. The date must be one the rule generates."""
        series = self._plan_row_or_raise(series_id)
        if not series["recurrence_rule"]:
            raise PlannedSessionError(f"Planned session {series_id} is not a series")
        day = _as_date(occurrence_date, "occurrence_date")
        existing = self.fetchone(
            "SELECT * FROM planned_sessions WHERE recurrence_parent_id = ? AND planned_date = ?",
            (series_id, day.isoformat()))
        if existing:
            return self._plan_dict(existing)
        rule = parse_rrule(series["recurrence_rule"])
        start = date.fromisoformat(series["planned_date"])
        if day not in expand_weekly(start, rule, day, day):
            raise PlannedSessionError(
                f"{day.isoformat()} is not a day this series falls on")
        with self.transaction():
            cur = self.execute(
                "INSERT INTO planned_sessions (uid, user_id, exam_context_id, question_source_id, "
                "template_id, goal_id, recurrence_parent_id, title, planned_date, "
                "planned_start_time, planned_duration_minutes, planned_questions, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, self.user_id, series["exam_context_id"],
                 series["question_source_id"], series["template_id"], series["goal_id"],
                 series_id, series["title"], day.isoformat(), series["planned_start_time"],
                 series["planned_duration_minutes"], series["planned_questions"], series["notes"]),
            )
            new_id = cur.lastrowid
        return self.get_planned_session(new_id)

    def _expand_series_rows(self, rows: Iterable[Dict[str, Any]], range_start: date,
                            range_end: date) -> List[Dict[str, Any]]:
        """Plain rows pass through; a series row becomes its occurrences in
        range, each replaced by its materialised child where one exists."""
        rows = list(rows)
        children_by_key: Dict[tuple, Dict[str, Any]] = {}
        for r in rows:
            if r["recurrence_parent_id"] is not None:
                children_by_key[(r["recurrence_parent_id"], r["planned_date"])] = r
        out: List[Dict[str, Any]] = []
        for r in rows:
            if r["recurrence_rule"]:
                rule = parse_rrule(r["recurrence_rule"])
                start = date.fromisoformat(r["planned_date"])
                for day in expand_weekly(start, rule, range_start, range_end):
                    child = children_by_key.get((r["id"], day.isoformat()))
                    out.append(self._plan_dict(child) if child else
                               self._plan_dict(r, occurrence_date=day))
            elif r["recurrence_parent_id"] is not None:
                # A materialised occurrence is emitted by its series above,
                # unless the series is gone from the set (filtered); then on
                # its own.
                parent_present = any(p["id"] == r["recurrence_parent_id"] for p in rows if p["recurrence_rule"])
                if not parent_present and range_start.isoformat() <= r["planned_date"] <= range_end.isoformat():
                    out.append(self._plan_dict(r))
            else:
                if range_start.isoformat() <= r["planned_date"] <= range_end.isoformat():
                    out.append(self._plan_dict(r))
        out.sort(key=lambda p: (p["planned_date"], p["planned_start_time"] or "", p["id"] or 0))
        return out

    # ------------------------------------------------------------- starting

    def start_planned_session(
        self,
        planned_id: int,
        *,
        total_questions: int,
        total_incorrect: int,
        date_encountered: Any = None,
        session_name: Optional[str] = None,
        exam_context_id: Optional[int] = None,
        occurrence_date: Any = None,
    ) -> Dict[str, Any]:
        """Turn a plan into a real review session, in one transaction.

        Calls :meth:`create_review_session` (the one ``INSERT INTO
        review_sessions``), then stamps the plan ``started`` with the new
        session's id. ``date_encountered`` defaults to the planned day (owner
        decision 4). An exam-less plan must be given ``exam_context_id`` here,
        because a review session always has one. For a series, pass
        ``occurrence_date``; the occurrence is materialised first.
        """
        row = self._plan_row_or_raise(planned_id)
        if row["recurrence_rule"]:
            if occurrence_date is None:
                raise PlannedSessionError("Starting a series needs the occurrence_date to start")
            row = dict(self.materialise_occurrence(planned_id, occurrence_date))
            row = self._plan_row_or_raise(row["id"])
        if row["status"] == "started":
            raise PlannedSessionError(
                f"Planned session {row['id']} was already started as review session "
                f"{row['review_session_id']}")
        if row["status"] in ("skipped", "cancelled"):
            raise PlannedSessionError(
                f"Planned session {row['id']} is {row['status']}; mark it planned again before starting it")
        exam_id = exam_context_id if exam_context_id is not None else row["exam_context_id"]
        if exam_id is None:
            raise PlannedSessionError("This plan has no exam; choose one to start a session")
        self._calendar_check_exam(exam_id)
        source_id = row["question_source_id"]
        if source_id is not None:
            src = self.get_question_source(source_id)
            if src is None or not self._calendar_source_fits_exam(src, exam_id):
                source_id = None
        day = _as_date(date_encountered, "date_encountered") if date_encountered is not None \
            else date.fromisoformat(row["planned_date"])
        with self.transaction():
            session = self.create_review_session(
                exam_context_id=exam_id,
                question_source_id=source_id,
                session_name=session_name or row["title"],
                date_encountered=day,
                total_questions=total_questions,
                total_incorrect=total_incorrect,
                session_duration_minutes=row["planned_duration_minutes"],
            )
            self.execute(
                "UPDATE planned_sessions SET status = 'started', review_session_id = ?, "
                "started_at = CURRENT_TIMESTAMP, exam_context_id = ? WHERE id = ?",
                (session.id, exam_id, row["id"]),
            )
        return {"planned": self.get_planned_session(row["id"]), "review_session": session}

    # ------------------------------------------------------------- the range read

    def get_calendar_range(self, start: Any, end: Any, *,
                           exam_context_id: Optional[int] = None) -> Dict[str, Any]:
        """Everything the calendar page draws for ``[start, end]`` inclusive.

        ``planned``: plans and expanded series occurrences, any status.
        ``sessions``: real review sessions by ``date_encountered`` (local
        days), each with ``planned_session_id`` so a plan that became a
        session draws one card. ``entry_counts``: entries per day in the
        heatmap's own query shape, drafts included (#12). ``exam_dates``:
        each active exam's ``exam_date`` inside the range (owner decision 13).
        """
        range_start = _as_date(start, "start")
        range_end = _as_date(end, "end")
        if range_end < range_start:
            raise PlannedSessionError("The range ends before it starts")
        if (range_end - range_start).days > 800:
            raise PlannedSessionError("A calendar range is at most 800 days")
        exam_clause = ""
        params: List[Any] = [self.user_id]
        if exam_context_id is not None:
            exam_clause = " AND exam_context_id = ?"
            params.append(exam_context_id)
        # Series rows are fetched regardless of their start date: their
        # occurrences may fall in range. Plain rows are filtered by date.
        plan_rows = self.fetchall(
            "SELECT * FROM planned_sessions WHERE user_id = ?" + exam_clause
            + " AND (recurrence_rule IS NOT NULL OR planned_date BETWEEN ? AND ?)",
            tuple(params) + (range_start.isoformat(), range_end.isoformat()),
        )
        # Children of in-range series need fetching even when dated outside
        # the plain-row window; one extra query keyed on the series ids.
        series_ids = [r["id"] for r in plan_rows if r["recurrence_rule"]]
        if series_ids:
            marks = ",".join("?" for _ in series_ids)
            children = self.fetchall(
                f"SELECT * FROM planned_sessions WHERE recurrence_parent_id IN ({marks}) "
                "AND planned_date BETWEEN ? AND ?",
                tuple(series_ids) + (range_start.isoformat(), range_end.isoformat()),
            )
            known = {r["id"] for r in plan_rows}
            plan_rows.extend(c for c in children if c["id"] not in known)
        planned = self._expand_series_rows(plan_rows, range_start, range_end)

        sess_params: List[Any] = [self.user_id, range_start.isoformat(), range_end.isoformat()]
        sess_clause = ""
        if exam_context_id is not None:
            sess_clause = " AND rs.exam_context_id = ?"
            sess_params.append(exam_context_id)
        sessions = self.fetchall(
            "SELECT rs.id, rs.exam_context_id, ec.exam_name, rs.question_source_id, "
            "rs.session_name, rs.date_encountered, rs.total_questions, rs.total_incorrect, "
            "rs.entries_completed, rs.session_status, rs.session_duration_minutes, "
            "ps.id AS planned_session_id "
            "FROM review_sessions rs "
            "JOIN exam_contexts ec ON ec.id = rs.exam_context_id "
            "LEFT JOIN planned_sessions ps ON ps.review_session_id = rs.id "
            "WHERE rs.user_id = ? AND DATE(rs.date_encountered) BETWEEN ? AND ?" + sess_clause
            + " ORDER BY rs.date_encountered, rs.id",
            tuple(sess_params),
        )
        count_params: List[Any] = [self.user_id, range_start.isoformat(), range_end.isoformat()]
        count_clause = ""
        if exam_context_id is not None:
            count_clause = " AND rs.exam_context_id = ?"
            count_params.append(exam_context_id)
        entry_counts = self.fetchall(
            "SELECT DATE(rs.date_encountered) AS date, COUNT(DISTINCT qe.id) AS count "
            "FROM question_entries qe JOIN review_sessions rs ON qe.review_session_id = rs.id "
            "WHERE rs.user_id = ? AND DATE(rs.date_encountered) >= ? AND DATE(rs.date_encountered) <= ?"
            + count_clause + " GROUP BY DATE(rs.date_encountered) ORDER BY 1",
            tuple(count_params),
        )
        exam_params: List[Any] = [self.user_id, range_start.isoformat(), range_end.isoformat()]
        exam_date_clause = ""
        if exam_context_id is not None:
            exam_date_clause = " AND id = ?"
            exam_params.append(exam_context_id)
        exam_dates = self.fetchall(
            "SELECT id AS exam_context_id, exam_name, exam_date, color_hex FROM exam_contexts "
            "WHERE user_id = ? AND is_active = 1 AND exam_date IS NOT NULL "
            "AND DATE(exam_date) BETWEEN ? AND ?" + exam_date_clause + " ORDER BY exam_date",
            tuple(exam_params),
        )
        return {
            "range": {"start": range_start.isoformat(), "end": range_end.isoformat()},
            "planned": planned,
            "sessions": [dict(s) for s in sessions],
            "entry_counts": [dict(c) for c in entry_counts],
            "exam_dates": [dict(e) for e in exam_dates],
        }

    # ------------------------------------------------------------- reminders

    def get_session_reminders(self, today: Optional[date] = None) -> Dict[str, Any]:
        """Plans due ``today`` and plans overdue (dated before today, still
        ``planned``), series occurrences included. ``today`` is Python's
        LOCAL date; never SQLite's ``date('now')`` (#286). Pure read."""
        today = today or date.today()
        horizon = today - timedelta(days=366)
        rows = self.fetchall(
            "SELECT * FROM planned_sessions WHERE user_id = ? AND "
            "(recurrence_rule IS NOT NULL OR recurrence_parent_id IS NOT NULL "
            " OR (status = 'planned' AND planned_date <= ?))",
            (self.user_id, today.isoformat()),
        )
        expanded = self._expand_series_rows(rows, horizon, today)
        due = [p for p in expanded if p["status"] == "planned" and p["planned_date"] == today.isoformat()]
        overdue = [p for p in expanded if p["status"] == "planned" and p["planned_date"] < today.isoformat()]
        return {"today": today.isoformat(), "due_today": due, "overdue": overdue}

    # ------------------------------------------------------------- goals (display only)

    def get_goal_plan_summary(self, goal_id: int, today: Optional[date] = None) -> Dict[str, Any]:
        """What a plan's goal link shows: the goal's live count for the current
        week (Monday to Sunday, local, as ``get_user_goals`` computes it) via
        the one dispatch point ``_count_goal_progress_in_period`` (#58, #70),
        beside the questions still planned for that week. **Stores nothing.**"""
        goal = self.fetchone(
            "SELECT id, goal_type, target_value, exam_context_id FROM user_goals "
            "WHERE id = ? AND user_id = ?", (goal_id, self.user_id))
        if goal is None:
            raise PlannedSessionError(f"Goal {goal_id} is not one of this profile's goals")
        today = today or datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        current = self._count_goal_progress_in_period(
            goal["goal_type"], week_start, week_end, goal["exam_context_id"])
        plans = self.get_calendar_range(week_start, week_end,
                                        exam_context_id=goal["exam_context_id"])["planned"]
        remaining = [p for p in plans if p["status"] == "planned" and p["planned_date"] >= today.isoformat()]
        return {
            "goal_id": goal["id"],
            "goal_type": goal["goal_type"],
            "target_value": goal["target_value"],
            "period_start": week_start.isoformat(),
            "period_end": week_end.isoformat(),
            "current_value": current,
            "planned_sessions_remaining": len(remaining),
            "planned_questions_remaining": sum(p["planned_questions"] or 0 for p in remaining),
        }

    # ------------------------------------------------------------- templates

    def create_session_template(self, name: str, *, exam_context_id: Optional[int] = None,
                                question_source_id: Optional[int] = None,
                                default_start_time: Optional[str] = None,
                                default_duration_minutes: Optional[int] = None,
                                default_questions: Optional[int] = None,
                                notes: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise PlannedSessionError("A template needs a name")
        self._calendar_check_exam(exam_context_id)
        self._calendar_check_source(question_source_id, exam_context_id)
        values = (self.user_id, exam_context_id, question_source_id, name.strip(),
                  _check_time(default_start_time),
                  _check_minutes(default_duration_minutes, "default_duration_minutes"),
                  _check_positive(default_questions, "default_questions"), notes)
        clash = self.fetchone(
            "SELECT id FROM session_templates WHERE user_id = ? AND COALESCE(exam_context_id, 0) = "
            "COALESCE(?, 0) AND name = ? AND is_active = 1",
            (self.user_id, exam_context_id, name.strip()))
        if clash:
            raise PlannedSessionError(f"A template named {name.strip()!r} already exists for this exam")
        with self.transaction():
            cur = self.execute(
                "INSERT INTO session_templates (user_id, exam_context_id, question_source_id, name, "
                "default_start_time, default_duration_minutes, default_questions, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
            new_id = cur.lastrowid
        return self.get_session_template(new_id)

    def get_session_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        row = self.fetchone("SELECT * FROM session_templates WHERE id = ? AND user_id = ?",
                            (template_id, self.user_id))
        return dict(row) if row else None

    def get_session_templates(self, *, exam_context_id: Optional[int] = None,
                              include_archived: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM session_templates WHERE user_id = ?"
        params: List[Any] = [self.user_id]
        if exam_context_id is not None:
            sql += " AND (exam_context_id = ? OR exam_context_id IS NULL)"
            params.append(exam_context_id)
        if not include_archived:
            sql += " AND is_active = 1"
        sql += " ORDER BY name, id"
        return [dict(r) for r in self.fetchall(sql, tuple(params))]

    def update_session_template(self, template_id: int, **fields: Any) -> Dict[str, Any]:
        row = self.fetchone("SELECT * FROM session_templates WHERE id = ? AND user_id = ?",
                            (template_id, self.user_id))
        if row is None:
            raise PlannedSessionError(f"Template {template_id} does not exist")
        unknown = set(fields) - set(_TEMPLATE_FIELDS) - {"exam_context_id"}
        if unknown:
            raise PlannedSessionError(f"Cannot change {', '.join(sorted(unknown))} on a template")
        merged = {**row, **fields}
        name = merged["name"]
        if not isinstance(name, str) or not name.strip():
            raise PlannedSessionError("A template needs a name")
        self._calendar_check_exam(merged["exam_context_id"])
        self._calendar_check_source(merged["question_source_id"], merged["exam_context_id"])
        clash = self.fetchone(
            "SELECT id FROM session_templates WHERE user_id = ? AND COALESCE(exam_context_id, 0) = "
            "COALESCE(?, 0) AND name = ? AND is_active = 1 AND id != ?",
            (self.user_id, merged["exam_context_id"], name.strip(), template_id))
        if clash and row["is_active"]:
            raise PlannedSessionError(f"A template named {name.strip()!r} already exists for this exam")
        values = {
            "exam_context_id": merged["exam_context_id"],
            "question_source_id": merged["question_source_id"],
            "name": name.strip(),
            "default_start_time": _check_time(merged["default_start_time"]),
            "default_duration_minutes": _check_minutes(merged["default_duration_minutes"], "default_duration_minutes"),
            "default_questions": _check_positive(merged["default_questions"], "default_questions"),
            "notes": merged["notes"],
        }
        with self.transaction():
            self.execute(
                "UPDATE session_templates SET " + ", ".join(f"{k} = ?" for k in values) + " WHERE id = ?",
                tuple(values.values()) + (template_id,))
        return self.get_session_template(template_id)

    def archive_session_template(self, template_id: int) -> Dict[str, Any]:
        """Hide a template and free its name. Plans made from it keep their
        ``template_id``; nothing is deleted."""
        row = self.fetchone("SELECT id FROM session_templates WHERE id = ? AND user_id = ?",
                            (template_id, self.user_id))
        if row is None:
            raise PlannedSessionError(f"Template {template_id} does not exist")
        with self.transaction():
            self.execute("UPDATE session_templates SET is_active = 0 WHERE id = ?", (template_id,))
        return self.get_session_template(template_id)
