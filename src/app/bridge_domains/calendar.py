"""WIMI calendar bridge operations (#778, Wave 1).

Thin slots over ``CalendarMixin`` (``database/domains/calendar.py``), plus
two things that belong at this layer and nowhere lower:

- **Reminder dismissal is bridge state, not a column** (owner decision 7:
  the dashboard notice shows once per profile per launch). The set of
  profiles that dismissed it this launch lives on the bridge, the way the
  folder-sync startup notice keeps its "once" here, because the dashboard
  reloads on every navigation and cannot keep it, and a stored flag would
  outlive the launch.
- **The iCal export is a dialog slot and a work slot**, split as
  ``profile_transfer.py`` splits them, so the native save dialog is never
  driven by a scenario and the work slot can be given a path and checked
  from the test process. The builder is Qt-free (``app/ical_export.py``).

Every slot keeps the bridge contract: ``@pyqtSlot`` outermost,
``@instrumented_slot`` beneath, a guard on ``self.user_db`` (resolved at
call time, since a profile switch swaps it), ``serialize_response`` with
``data`` absent when there is nothing to return.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Optional

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from app.ical_export import IcsEvent, build_ics
from database.domains._calendar_recurrence import expand_weekly, parse_rrule
from database.exceptions import PlannedSessionError, ValidationError

from ..bridge_helpers import serialize_response

_NO_DB = 'No user database connected'
ICS_SUFFIX = '.ics'
_PLAN_INPUT_KEYS = {
    'exam_context_id', 'question_source_id', 'template_id', 'goal_id', 'title',
    'planned_start_time', 'planned_duration_minutes', 'planned_questions', 'notes',
    'recurrence_rule',
}
_TEMPLATE_INPUT_KEYS = {
    'exam_context_id', 'question_source_id', 'default_start_time',
    'default_duration_minutes', 'default_questions', 'notes', 'name',
}


def _params(params_json: str, what: str) -> dict:
    if not params_json:
        return {}
    try:
        params = json.loads(params_json)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f'Invalid {what}: {e}') from None
    if not isinstance(params, dict):
        raise ValueError(f'Invalid {what}: must be a JSON object')
    return params


def _session_payload(session) -> dict:
    # ReviewSession is a dataclass with no to_dict; serialize_response's
    # DateTimeEncoder renders its date and datetime fields.
    if hasattr(session, 'to_dict'):
        return session.to_dict()
    if is_dataclass(session):
        return asdict(session)
    return dict(session)


class CalendarBridgeMixin:
    """Planned sessions, templates, the range read, reminders and iCal export."""

    # Profiles (by users.id) that dismissed the reminder notice this launch.
    _calendar_reminders_dismissed: set = set()

    # ------------------------------------------------------------- helpers

    def _calendar_call(self, label: str, fn, *args, **kwargs) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            return serialize_response(True, data=fn(*args, **kwargs))
        except (PlannedSessionError, ValidationError, ValueError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'{label} failed: {e}', {})
            return serialize_response(False, error=f'{label} failed: {e}')

    # ------------------------------------------------------------- range

    @pyqtSlot(str, str, str, result=str)
    @instrumented_slot
    def getCalendarRange(self, start: str, end: str, params_json: str) -> str:
        """Everything the calendar draws for [start, end] (YYYY-MM-DD, local
        days). params: {exam_context_id?}."""
        def run():
            p = _params(params_json, 'calendar range params')
            return self.user_db.get_calendar_range(start, end, exam_context_id=p.get('exam_context_id'))
        return self._calendar_call('getCalendarRange', run)

    # ------------------------------------------------------------- plans

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createPlannedSession(self, payload_json: str) -> str:
        def run():
            p = _params(payload_json, 'planned session payload')
            if 'planned_date' not in p:
                raise ValueError('planned_date is required')
            kwargs = {k: v for k, v in p.items() if k in _PLAN_INPUT_KEYS}
            return self.user_db.create_planned_session(p['planned_date'], **kwargs)
        return self._calendar_call('createPlannedSession', run)

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getPlannedSession(self, planned_id: int) -> str:
        if not self.user_db:
            return serialize_response(False, error=_NO_DB)
        try:
            plan = self.user_db.get_planned_session(planned_id)
        except Exception as e:
            self._log_error(f'getPlannedSession failed: {e}', {})
            return serialize_response(False, error=f'getPlannedSession failed: {e}')
        if plan is None:
            return serialize_response(False, error=f'Planned session {planned_id} not found')
        return serialize_response(True, data=plan)

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updatePlannedSession(self, planned_id: int, payload_json: str) -> str:
        def run():
            p = _params(payload_json, 'planned session payload')
            fields = {k: v for k, v in p.items() if k in _PLAN_INPUT_KEYS or k == 'planned_date'}
            return self.user_db.update_planned_session(planned_id, **fields)
        return self._calendar_call('updatePlannedSession', run)

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def setPlannedSessionStatus(self, planned_id: int, status: str) -> str:
        return self._calendar_call('setPlannedSessionStatus',
                                   self.user_db.set_planned_session_status if self.user_db else None,
                                   planned_id, status)

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deletePlannedSession(self, planned_id: int) -> str:
        def run():
            return {'deleted': self.user_db.delete_planned_session(planned_id)}
        return self._calendar_call('deletePlannedSession', run)

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def materialiseOccurrence(self, series_id: int, occurrence_date: str) -> str:
        """Give one occurrence of a series its own row, so the page can edit,
        skip or start that date alone."""
        def run():
            return self.user_db.materialise_occurrence(series_id, occurrence_date)
        return self._calendar_call('materialiseOccurrence', run)

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def startPlannedSession(self, planned_id: int, payload_json: str) -> str:
        """payload: {total_questions, total_incorrect, date_encountered?,
        session_name?, exam_context_id?, occurrence_date?}. Returns both the
        plan and the new review session so the page can navigate."""
        def run():
            p = _params(payload_json, 'start payload')
            for key in ('total_questions', 'total_incorrect'):
                if not isinstance(p.get(key), int) or isinstance(p.get(key), bool):
                    raise ValueError(f'{key} must be a whole number')
            out = self.user_db.start_planned_session(
                planned_id,
                total_questions=p['total_questions'],
                total_incorrect=p['total_incorrect'],
                date_encountered=p.get('date_encountered'),
                session_name=p.get('session_name'),
                exam_context_id=p.get('exam_context_id'),
                occurrence_date=p.get('occurrence_date'),
            )
            return {'planned': out['planned'], 'review_session': _session_payload(out['review_session'])}
        return self._calendar_call('startPlannedSession', run)

    # ------------------------------------------------------------- reminders

    @pyqtSlot(result=str)
    @instrumented_slot
    def getSessionReminders(self) -> str:
        """Plans due today and overdue, or an empty answer with
        ``dismissed: true`` once this profile pressed Dismiss this launch."""
        def run():
            key = self.user_db.user_id
            if key in self._calendar_reminders_dismissed:
                return {'today': date.today().isoformat(), 'due_today': [], 'overdue': [], 'dismissed': True}
            out = self.user_db.get_session_reminders()
            out['dismissed'] = False
            return out
        return self._calendar_call('getSessionReminders', run)

    @pyqtSlot(result=str)
    @instrumented_slot
    def dismissSessionReminders(self) -> str:
        def run():
            # A class-level default set would be shared by every bridge; give
            # this instance its own on first use.
            if '_calendar_reminders_dismissed' not in self.__dict__:
                self._calendar_reminders_dismissed = set()
            self._calendar_reminders_dismissed.add(self.user_db.user_id)
            return {'dismissed': True}
        return self._calendar_call('dismissSessionReminders', run)

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getGoalPlanSummary(self, goal_id: int) -> str:
        return self._calendar_call('getGoalPlanSummary',
                                   self.user_db.get_goal_plan_summary if self.user_db else None, goal_id)

    # ------------------------------------------------------------- templates

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def getSessionTemplates(self, params_json: str) -> str:
        def run():
            p = _params(params_json, 'template params')
            return self.user_db.get_session_templates(
                exam_context_id=p.get('exam_context_id'),
                include_archived=bool(p.get('include_archived', False)))
        return self._calendar_call('getSessionTemplates', run)

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createSessionTemplate(self, payload_json: str) -> str:
        def run():
            p = _params(payload_json, 'template payload')
            if 'name' not in p:
                raise ValueError('name is required')
            kwargs = {k: v for k, v in p.items() if k in _TEMPLATE_INPUT_KEYS and k != 'name'}
            return self.user_db.create_session_template(p['name'], **kwargs)
        return self._calendar_call('createSessionTemplate', run)

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def updateSessionTemplate(self, template_id: int, payload_json: str) -> str:
        def run():
            p = _params(payload_json, 'template payload')
            fields = {k: v for k, v in p.items() if k in _TEMPLATE_INPUT_KEYS}
            return self.user_db.update_session_template(template_id, **fields)
        return self._calendar_call('updateSessionTemplate', run)

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def archiveSessionTemplate(self, template_id: int) -> str:
        return self._calendar_call('archiveSessionTemplate',
                                   self.user_db.archive_session_template if self.user_db else None,
                                   template_id)

    # ------------------------------------------------------------- iCal export

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def openCalendarExportDialog(self, params_json: str) -> str:
        """Native save dialog for the .ics destination. ``data`` is absent
        when the student cancels. Never driven by a scenario."""
        try:
            params = _params(params_json, 'export dialog params')
        except ValueError as e:
            return serialize_response(False, error=str(e))
        default_filename = str(params.get('default_filename') or 'wimi-calendar.ics')
        try:
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getSaveFileName(
                None, 'Export calendar', default_filename, 'iCalendar (*.ics)')
            if not file_path:
                return serialize_response(True, data=None)
            if not file_path.lower().endswith(ICS_SUFFIX):
                file_path += ICS_SUFFIX
            return serialize_response(True, data={'file_path': file_path})
        except Exception as e:
            self._log_error(f'openCalendarExportDialog failed: {e}', {})
            return serialize_response(False, error=f'Failed to open save dialog: {e}')

    def _calendar_ics_events(self, start: date, end: date, *, exam_context_id: Optional[int],
                             include_past: bool) -> list:
        rng = self.user_db.get_calendar_range(start, end, exam_context_id=exam_context_id)
        exams = {e.id: e for e in self.user_db.get_all_exam_contexts(active_only=False)}
        profile = self.user_db.get_profile_uuid() if hasattr(self.user_db, 'get_profile_uuid') else 'profile'
        events: list = []
        # Series are exported once, as a rule, from their series row; the
        # expanded occurrences in `planned` carry series_id and are skipped
        # unless materialised with a status other than planned (EXDATE).
        series_rows = {}
        exdates: dict = {}
        plain: list = []
        for p in rng['planned']:
            if p['series_id'] is not None:
                sid = p['series_id']
                if sid not in series_rows:
                    series_rows[sid] = self.user_db.get_planned_session(sid)
                if p['status'] in ('skipped', 'cancelled'):
                    exdates.setdefault(sid, []).append(date.fromisoformat(p['planned_date']))
            else:
                plain.append(p)

        def exam_name(eid):
            ex = exams.get(eid)
            return ex.exam_name if ex else None

        def plan_event(p, *, rrule=None, occurrences=(), exd=()):
            name = exam_name(p['exam_context_id'])
            summary = 'WIMI session' + (f': {name}' if name else '')
            if p.get('title'):
                summary += f' – {p["title"]}'
            start_time = time.fromisoformat(p['planned_start_time']) if p.get('planned_start_time') else None
            desc_parts = []
            if p.get('planned_questions'):
                desc_parts.append(f"{p['planned_questions']} questions planned")
            if p.get('notes'):
                desc_parts.append(p['notes'])
            if p['status'] == 'started':
                desc_parts.append('Started in WIMI')
            return IcsEvent(
                uid=f"{p['uid']}@wimi",
                summary=summary,
                day=date.fromisoformat(p['planned_date']),
                start_time=start_time,
                duration_minutes=p.get('planned_duration_minutes') or (60 if start_time else None),
                description='\n'.join(desc_parts) or None,
                categories=[name] if name else (),
                rrule=rrule,
                exdates=tuple(exd),
                occurrences=tuple(occurrences),
                sequence=0,
            )

        for p in plain:
            if p['status'] == 'cancelled':
                continue
            events.append(plan_event(p))
        for sid, srow in series_rows.items():
            if srow is None:
                continue
            rule = parse_rrule(srow['recurrence_rule'])
            series_start = date.fromisoformat(srow['planned_date'])
            occurrences = expand_weekly(series_start, rule, series_start, end)
            events.append(plan_event(srow, rrule=srow['recurrence_rule'], occurrences=occurrences,
                                     exd=sorted(exdates.get(sid, []))))
        if include_past:
            for s in rng['sessions']:
                if s.get('planned_session_id') is not None:
                    continue  # the plan's event already represents it
                name = s.get('exam_name')
                events.append(IcsEvent(
                    uid=f"{profile}-session-{s['id']}@wimi",
                    summary=f"WIMI session: {name}" + (f" – {s['session_name']}" if s.get('session_name') else ''),
                    day=date.fromisoformat(str(s['date_encountered'])[:10]),
                    description=f"{s['total_questions']} questions, {s['total_incorrect']} missed",
                    categories=[name] if name else (),
                ))
        events.sort(key=lambda e: (e.day, e.start_time or time.min, e.uid))
        return events

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def exportCalendarIcs(self, params_json: str) -> str:
        """Write the .ics. params: {dest_path, start?, end?, exam_context_id?,
        include_past?}. Defaults to a year back and a year ahead of today.
        Returns {file_path, event_count}."""
        def run():
            p = _params(params_json, 'export params')
            dest = p.get('dest_path')
            if not dest or not isinstance(dest, str):
                raise ValueError('dest_path is required')
            today = date.today()
            start = date.fromisoformat(p['start']) if p.get('start') else today.replace(year=today.year - 1)
            end = date.fromisoformat(p['end']) if p.get('end') else today.replace(year=today.year + 1)
            events = self._calendar_ics_events(start, end, exam_context_id=p.get('exam_context_id'),
                                               include_past=bool(p.get('include_past', True)))
            data = build_ics(events, now=datetime.now(timezone.utc))
            with open(dest, 'wb') as fh:
                fh.write(data)
            return {'file_path': dest, 'event_count': len(events)}
        return self._calendar_call('exportCalendarIcs', run)
