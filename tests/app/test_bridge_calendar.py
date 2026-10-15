"""CalendarBridgeMixin (#778 Wave 1): every slot keeps the bridge contract,
the dismissal is per profile per launch and lives on the bridge, the export
work slot writes a parseable .ics to a given path, and the JS module cannot
drift from the Python surface.

Plain-method bridge tests, no QApplication, as tests/app/test_bridge_*.py do.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.bridge import DatabaseBridge
from app.ical_export import parse_ics
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

REPO = Path(__file__).resolve().parents[2]

SLOTS = [
    'getCalendarRange', 'createPlannedSession', 'getPlannedSession', 'updatePlannedSession',
    'setPlannedSessionStatus', 'deletePlannedSession', 'materialiseOccurrence',
    'startPlannedSession', 'getSessionReminders', 'dismissSessionReminders',
    'getGoalPlanSummary', 'getSessionTemplates', 'createSessionTemplate',
    'updateSessionTemplate', 'archiveSessionTemplate', 'exportCalendarIcs',
]

# Minimal valid arguments per slot, for the user_db=None sweep. The dialog
# slot is excluded: it has no user_db guard (it opens a dialog), and it is
# never driven from a test.
SLOT_ARGS = {
    'getCalendarRange': ('2026-10-01', '2026-10-31', '{}'),
    'createPlannedSession': ('{"planned_date": "2026-10-14"}',),
    'getPlannedSession': (1,),
    'updatePlannedSession': (1, '{"title": "x"}'),
    'setPlannedSessionStatus': (1, 'skipped'),
    'deletePlannedSession': (1,),
    'materialiseOccurrence': (1, '2026-10-20'),
    'startPlannedSession': (1, '{"total_questions": 5, "total_incorrect": 1}'),
    'getSessionReminders': (),
    'dismissSessionReminders': (),
    'getGoalPlanSummary': (1,),
    'getSessionTemplates': ('{}',),
    'createSessionTemplate': ('{"name": "T"}',),
    'updateSessionTemplate': (1, '{"name": "T2"}'),
    'archiveSessionTemplate': (1,),
    'exportCalendarIcs': ('{"dest_path": "/dev/null"}',),
}


@pytest.fixture
def bridge(tmp_path):
    master = MasterDatabase(data_dir=tmp_path / "data", error_logger=None)
    user = master.create_user(username="planner", display_name="Planner")
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    b = DatabaseBridge(master_db=master, user_db=db)
    yield b
    db.close()
    master.close()


@pytest.fixture
def no_db_bridge(tmp_path):
    master = MasterDatabase(data_dir=tmp_path / "data", error_logger=None)
    b = DatabaseBridge(master_db=master, user_db=None)
    yield b
    master.close()


@pytest.fixture
def exam(bridge):
    return bridge.user_db.create_exam_context(exam_name="Step X")


def _ok(response: str):
    payload = json.loads(response)
    assert payload["success"] is True, payload
    return payload.get("data")


def _err(response: str) -> str:
    payload = json.loads(response)
    assert payload["success"] is False, payload
    assert payload["error"], payload
    return payload["error"]


# ---------------------------------------------------------------- contract


@pytest.mark.unit
@pytest.mark.parametrize("slot", SLOTS)
def test_every_slot_guards_a_missing_user_db(no_db_bridge, slot):
    assert _err(getattr(no_db_bridge, slot)(*SLOT_ARGS[slot])) == 'No user database connected'


@pytest.mark.unit
def test_every_slot_is_instrumented():
    src = (REPO / 'src/app/bridge_domains/calendar.py').read_text(encoding='utf-8')
    for slot in SLOTS + ['openCalendarExportDialog']:
        i = src.index(f'def {slot}(')
        head = src[max(0, i - 200):i]
        assert '@pyqtSlot' in head and '@instrumented_slot' in head, slot


@pytest.mark.unit
def test_the_js_module_names_only_slots_that_exist(bridge):
    src = (REPO / 'src/web/js/api/calendar.js').read_text(encoding='utf-8')
    called = set(re.findall(r"_callBridge\('(\w+)'", src))
    assert called == set(SLOTS) | {'openCalendarExportDialog'}
    for name in called:
        assert callable(getattr(bridge, name)), name
    loader = (REPO / 'src/web/js/api/_loader.js').read_text(encoding='utf-8')
    assert "'calendar.js'" in loader


# ---------------------------------------------------------------- plans through the bridge


@pytest.mark.unit
def test_create_read_update_status_delete(bridge, exam):
    plan = _ok(bridge.createPlannedSession(json.dumps({
        'planned_date': '2026-10-14', 'exam_context_id': exam.id, 'title': 'Cardio',
        'planned_start_time': '09:00', 'planned_duration_minutes': 60, 'planned_questions': 40})))
    assert plan['status'] == 'planned' and plan['exam_context_id'] == exam.id
    assert _ok(bridge.getPlannedSession(plan['id']))['title'] == 'Cardio'
    assert _ok(bridge.updatePlannedSession(plan['id'], json.dumps({'title': 'Renal'})))['title'] == 'Renal'
    assert _ok(bridge.setPlannedSessionStatus(plan['id'], 'skipped'))['status'] == 'skipped'
    assert _ok(bridge.deletePlannedSession(plan['id'])) == {'deleted': True}
    assert 'not found' in _err(bridge.getPlannedSession(plan['id']))


@pytest.mark.unit
def test_refusals_arrive_as_sentences_not_tracebacks(bridge, exam):
    assert 'planned_date is required' in _err(bridge.createPlannedSession('{}'))
    assert 'HH:MM' in _err(bridge.createPlannedSession(json.dumps({'planned_date': '2026-10-14', 'planned_start_time': '9am'})))
    assert 'Invalid planned session payload' in _err(bridge.createPlannedSession('not json'))
    assert 'YYYY-MM-DD' in _err(bridge.getCalendarRange('yesterday', '2026-10-31', '{}'))
    assert 'whole number' in _err(bridge.startPlannedSession(1, json.dumps({'total_questions': 'five', 'total_incorrect': 1})))


@pytest.mark.unit
def test_start_returns_the_plan_and_the_session(bridge, exam):
    plan = _ok(bridge.createPlannedSession(json.dumps({'planned_date': '2026-10-14', 'exam_context_id': exam.id})))
    out = _ok(bridge.startPlannedSession(plan['id'], json.dumps({'total_questions': 20, 'total_incorrect': 4})))
    assert out['planned']['status'] == 'started'
    assert out['review_session']['id'] == out['planned']['review_session_id']
    assert str(out['review_session']['date_encountered'])[:10] == '2026-10-14'


@pytest.mark.unit
def test_series_occurrence_through_the_bridge(bridge, exam):
    series = _ok(bridge.createPlannedSession(json.dumps({
        'planned_date': '2026-10-13', 'exam_context_id': exam.id, 'recurrence_rule': 'FREQ=WEEKLY;BYDAY=TU;COUNT=3'})))
    rng = _ok(bridge.getCalendarRange('2026-10-12', '2026-11-01', json.dumps({'exam_context_id': exam.id})))
    assert [p['planned_date'] for p in rng['planned']] == ['2026-10-13', '2026-10-20', '2026-10-27']
    occ = _ok(bridge.materialiseOccurrence(series['id'], '2026-10-20'))
    assert occ['series_id'] == series['id'] and occ['planned_date'] == '2026-10-20'
    assert 'not a day this series falls on' in _err(bridge.materialiseOccurrence(series['id'], '2026-10-21'))


# ---------------------------------------------------------------- reminders


@pytest.mark.unit
def test_reminders_and_dismissal_are_per_profile_per_bridge(bridge, exam, tmp_path):
    today = date.today()
    _ok(bridge.createPlannedSession(json.dumps({'planned_date': today.isoformat(), 'exam_context_id': exam.id, 'title': 'today'})))
    _ok(bridge.createPlannedSession(json.dumps({'planned_date': (today - timedelta(days=2)).isoformat(),
                                                'exam_context_id': exam.id, 'title': 'missed'})))
    rem = _ok(bridge.getSessionReminders())
    assert rem['dismissed'] is False
    assert [p['title'] for p in rem['due_today']] == ['today'] and [p['title'] for p in rem['overdue']] == ['missed']
    assert _ok(bridge.dismissSessionReminders()) == {'dismissed': True}
    rem2 = _ok(bridge.getSessionReminders())
    assert rem2['dismissed'] is True and rem2['due_today'] == [] and rem2['overdue'] == []
    # Another bridge (another launch) is not dismissed; nothing was stored.
    other = DatabaseBridge(master_db=bridge.master_db, user_db=bridge.user_db)
    assert _ok(other.getSessionReminders())['dismissed'] is False
    # Another profile on the same bridge is not dismissed either.
    user2 = bridge.master_db.create_user(username="second", display_name="Second")
    db2 = UserDatabase(db_path=bridge.master_db.ensure_user_database(user2.id), user_id=user2.id, username="second")
    try:
        bridge.user_db = db2
        assert _ok(bridge.getSessionReminders())['dismissed'] is False
    finally:
        db2.close()


# ---------------------------------------------------------------- templates


@pytest.mark.unit
def test_templates_through_the_bridge(bridge, exam):
    t = _ok(bridge.createSessionTemplate(json.dumps({'name': 'Morning', 'exam_context_id': exam.id, 'default_questions': 20})))
    assert [x['name'] for x in _ok(bridge.getSessionTemplates(json.dumps({'exam_context_id': exam.id})))] == ['Morning']
    assert _ok(bridge.updateSessionTemplate(t['id'], json.dumps({'name': 'Early'})))['name'] == 'Early'
    assert _ok(bridge.archiveSessionTemplate(t['id']))['is_active'] == 0
    assert _ok(bridge.getSessionTemplates('{}')) == []
    assert 'name is required' in _err(bridge.createSessionTemplate('{}'))


# ---------------------------------------------------------------- export


@pytest.mark.unit
def test_export_writes_a_parseable_ics_with_plans_series_and_past_sessions(bridge, exam, tmp_path):
    db = bridge.user_db
    _ok(bridge.createPlannedSession(json.dumps({'planned_date': '2026-10-14', 'exam_context_id': exam.id,
                                                'title': 'Cardio', 'planned_start_time': '09:00'})))
    series = _ok(bridge.createPlannedSession(json.dumps({'planned_date': '2026-10-13', 'exam_context_id': exam.id,
                                                          'recurrence_rule': 'FREQ=WEEKLY;BYDAY=TU;COUNT=3'})))
    occ = _ok(bridge.materialiseOccurrence(series['id'], '2026-10-20'))
    _ok(bridge.setPlannedSessionStatus(occ['id'], 'skipped'))
    cancelled = _ok(bridge.createPlannedSession(json.dumps({'planned_date': '2026-10-16', 'exam_context_id': exam.id})))
    _ok(bridge.setPlannedSessionStatus(cancelled['id'], 'cancelled'))
    db.create_review_session(exam_context_id=exam.id, date_encountered=date(2026, 10, 1),
                             total_questions=10, total_incorrect=2, session_name='Bank run')
    dest = tmp_path / 'out.ics'
    out = _ok(bridge.exportCalendarIcs(json.dumps({'dest_path': str(dest), 'start': '2026-09-01', 'end': '2026-12-31'})))
    assert out == {'file_path': str(dest), 'event_count': 3}
    events = parse_ics(dest.read_bytes())
    summaries = sorted(e['SUMMARY'][0] for e in events)
    assert summaries == ['WIMI session: Step X', 'WIMI session: Step X – Bank run', 'WIMI session: Step X – Cardio']
    series_ev = next(e for e in events if 'RRULE' in e)
    assert series_ev['RRULE'] == ['FREQ=WEEKLY;BYDAY=TU;COUNT=3'] and series_ev['EXDATE'] == ['20261020']
    timed = next(e for e in events if 'Cardio' in e['SUMMARY'][0])
    assert timed['DTSTART'][0].endswith('Z') and timed['DURATION'] == ['PT60M']
    assert not any('ORGANIZER' in e or 'ATTENDEE' in e for e in events)
    assert 'dest_path is required' in _err(bridge.exportCalendarIcs('{}'))


@pytest.mark.unit
def test_export_with_nothing_planned_is_a_valid_empty_calendar(bridge, tmp_path):
    dest = tmp_path / 'empty.ics'
    out = _ok(bridge.exportCalendarIcs(json.dumps({'dest_path': str(dest), 'include_past': False})))
    assert out['event_count'] == 0
    text = dest.read_bytes().decode('utf-8')   # read_text would translate the CRLFs
    assert text.startswith('BEGIN:VCALENDAR\r\n') and text.endswith('END:VCALENDAR\r\n')
    assert parse_ics(dest.read_bytes()) == []
