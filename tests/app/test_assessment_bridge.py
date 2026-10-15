"""AssessmentBridgeMixin (#766 Wave 1): every slot keeps the bridge contract,
the item flow is shaped the way the page needs it, and the JS module cannot
drift from the Python surface.

Plain-method bridge tests, no QApplication, as tests/app/test_bridge_*.py do.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

REPO = Path(__file__).resolve().parents[2]

SLOTS = [
    'startAssessment', 'getInFlightAssessment', 'submitResponse',
    'finishAssessment', 'getLatestScores', 'getAssessmentHistory',
    'getAssessmentResponses', 'getReassessmentStatus', 'snoozeReassessment',
    'setReassessmentCadence', 'getReassessmentCadence',
]

# Minimal valid arguments per slot, for the user_db=None sweep.
SLOT_ARGS = {
    'startAssessment': ('v1',),
    'getInFlightAssessment': (),
    'submitResponse': (1, 'nfc_01', 3, 0),
    'finishAssessment': (1,),
    'getLatestScores': (),
    'getAssessmentHistory': (10,),
    'getAssessmentResponses': (1,),
    'getReassessmentStatus': (),
    'snoozeReassessment': (7,),
    'setReassessmentCadence': (180,),
    'getReassessmentCadence': (),
}


@pytest.fixture
def bridge(tmp_path):
    master = MasterDatabase(data_dir=tmp_path / "data", error_logger=None)
    user = master.create_user(username="assessee", display_name="Assessee")
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


def _ok(response: str):
    payload = json.loads(response)
    assert payload["success"] is True, payload
    # serialize_response omits the key entirely when data is None, so a
    # "no record" answer arrives as an absent key, not a null.
    return payload.get("data")


def _err(response: str) -> str:
    payload = json.loads(response)
    assert payload["success"] is False, payload
    assert payload["error"], payload
    return payload["error"]


def _flow_items(data):
    return [it for sec in data['sections'] for it in sec['items']]


def _answer_everything(bridge, data, *, attention_correct=True):
    """Answer every item with 3 (valid on 5-, 6- and 7-point scales) and
    each attention check with its instructed value (or a wrong one)."""
    expected = {'atc_01': 3, 'atc_02': 4}
    for it in _flow_items(data):
        if it['kind'] == 'attention':
            raw = expected[it['item_code']] if attention_correct else 1
        else:
            raw = 3
        _ok(bridge.submitResponse(data['assessment_id'], it['item_code'], raw, 100))


# --------------------------------------------------------------- contract

def test_every_slot_is_registered(bridge):
    for name in SLOTS:
        assert callable(getattr(bridge, name, None)), name


@pytest.mark.parametrize('name', SLOTS)
def test_every_slot_refuses_without_a_user_database(no_db_bridge, name):
    error = _err(getattr(no_db_bridge, name)(*SLOT_ARGS[name]))
    assert error == 'No user database connected'


def test_the_js_module_names_only_slots_that_exist(bridge):
    """A JS wrapper calling a slot the bridge does not have fails at runtime
    with a generic message; this catches it at test time, on both sides."""
    src = (REPO / 'src/web/js/api/assessments.js').read_text(encoding='utf-8')
    called = set(re.findall(r"_callBridge\('(\w+)'", src))
    assert called, "the JS module calls no slot at all"
    missing = sorted(called - set(SLOTS))
    assert not missing, f"JS calls slots the bridge lacks: {missing}"
    uncalled = sorted(set(SLOTS) - called)
    assert not uncalled, f"bridge slots the JS never exposes: {uncalled}"


def test_the_loader_loads_the_module():
    loader = (REPO / 'src/web/js/api/_loader.js').read_text(encoding='utf-8')
    assert "'assessments.js'" in loader


# ------------------------------------------------------------------- flow

def test_start_returns_three_sections_in_order(bridge):
    data = _ok(bridge.startAssessment('v1'))
    assert [s['name'] for s in data['sections']] == ['nfc', 'lgo', 'importance']
    assert data['instrument_version'] == 'v1'
    assert data['is_resumed'] is False
    assert data['answered_item_codes'] == []


def test_section_item_counts_include_the_spliced_attention_checks(bridge):
    data = _ok(bridge.startAssessment('v1'))
    counts = {s['name']: len(s['items']) for s in data['sections']}
    assert counts == {'nfc': 35, 'lgo': 14, 'importance': 8}
    assert data['total_items'] == 57


def test_positions_are_contiguous_across_the_whole_flow(bridge):
    data = _ok(bridge.startAssessment('v1'))
    positions = [it['position'] for it in _flow_items(data)]
    assert positions == list(range(1, 58))


def test_attention_checks_sit_directly_after_their_anchor_items(bridge):
    """The fixture pins atc_01 after nfc_17 and atc_02 after lgo_learning_03.
    Without the loader carrying insert_after_item_code both would fall into
    the orphan path and land at the end of the last section."""
    bridge_data = _ok(bridge.startAssessment('v1'))
    codes = [it['item_code'] for it in _flow_items(bridge_data)]
    assert codes[codes.index('nfc_17') + 1] == 'atc_01'
    assert codes[codes.index('lgo_learning_03') + 1] == 'atc_02'
    kinds = {it['item_code']: it['kind'] for it in _flow_items(bridge_data)}
    assert kinds['atc_01'] == 'attention' and kinds['nfc_17'] == 'item'


def test_the_payload_carries_no_scoring_metadata(bridge):
    data = _ok(bridge.startAssessment('v1'))
    for it in _flow_items(data):
        assert 'reverse_scored' not in it
        assert 'expected_response' not in it
        assert set(it) == {'item_code', 'prompt', 'kind', 'subscale', 'scale', 'position'}


def test_prompts_pass_through_verbatim_from_the_fixture(bridge):
    """Every prompt the page receives is the fixture's own text, unchanged --
    populated items and placeholders alike. The bridge must neither paper over
    a placeholder nor touch a published item (#766 decisions 2, 7, 8)."""
    from database.domains._assessment_scoring import load_fixture
    fixture = load_fixture('v1')
    expected = {it.item_code: it.prompt for it in fixture.all_items}
    data = _ok(bridge.startAssessment('v1'))
    got = {it['item_code']: it['prompt'] for it in _flow_items(data)}
    assert got == expected


def test_a_section_carries_its_scale_with_anchors(bridge):
    data = _ok(bridge.startAssessment('v1'))
    lgo = next(s for s in data['sections'] if s['name'] == 'lgo')
    assert lgo['scale']['min'] == 1 and lgo['scale']['max'] == 6
    assert len(lgo['scale']['anchors']) == 6
    assert lgo['subscales'] == ['learning', 'prove', 'avoid']


# ----------------------------------------------------------------- resume

def test_starting_twice_resumes_the_same_administration(bridge):
    first = _ok(bridge.startAssessment('v1'))
    _ok(bridge.submitResponse(first['assessment_id'], 'nfc_01', 4, 50))
    second = _ok(bridge.startAssessment('v1'))
    assert second['assessment_id'] == first['assessment_id']
    assert second['is_resumed'] is True
    assert second['answered_item_codes'] == ['nfc_01']


def test_in_flight_is_null_then_the_open_record(bridge):
    assert _ok(bridge.getInFlightAssessment()) is None
    data = _ok(bridge.startAssessment('v1'))
    rec = _ok(bridge.getInFlightAssessment())
    assert rec['id'] == data['assessment_id'] and rec['is_complete'] is False


# ---------------------------------------------------------------- answers

def test_an_out_of_range_response_is_a_sentence_not_an_exception(bridge):
    data = _ok(bridge.startAssessment('v1'))
    error = _err(bridge.submitResponse(data['assessment_id'], 'nfc_01', 10, 0))
    assert 'nfc_01' in error or '10' in error


def test_an_unknown_item_code_is_refused(bridge):
    data = _ok(bridge.startAssessment('v1'))
    _err(bridge.submitResponse(data['assessment_id'], 'nope_99', 3, 0))


def test_responses_read_back(bridge):
    data = _ok(bridge.startAssessment('v1'))
    _ok(bridge.submitResponse(data['assessment_id'], 'nfc_02', 5, 120))
    rows = _ok(bridge.getAssessmentResponses(data['assessment_id']))
    assert [r['item_code'] for r in rows] == ['nfc_02']
    assert rows[0]['raw_response'] == 5


# ----------------------------------------------------------------- finish

def test_a_fully_answered_administration_scores_and_passes_attention(bridge):
    data = _ok(bridge.startAssessment('v1'))
    _answer_everything(bridge, data)
    rec = _ok(bridge.finishAssessment(data['assessment_id']))
    assert rec['is_complete'] is True
    assert rec['attention_check_pass'] is True
    for key in ('nfc_total', 'lgo_learning', 'lgo_prove', 'lgo_avoid',
                'importance_exam', 'importance_clinical',
                'importance_mastery', 'importance_reflection'):
        assert rec[key] is not None, key


def test_wrong_attention_answers_fail_the_check_but_still_score(bridge):
    data = _ok(bridge.startAssessment('v1'))
    _answer_everything(bridge, data, attention_correct=False)
    rec = _ok(bridge.finishAssessment(data['assessment_id']))
    assert rec['attention_check_pass'] is False
    assert rec['nfc_total'] is not None


def test_finishing_with_no_answers_gives_null_scores(bridge):
    data = _ok(bridge.startAssessment('v1'))
    rec = _ok(bridge.finishAssessment(data['assessment_id']))
    assert rec['is_complete'] is True
    assert rec['nfc_total'] is None
    assert rec['attention_check_pass'] is False


def test_finishing_twice_is_refused(bridge):
    data = _ok(bridge.startAssessment('v1'))
    _ok(bridge.finishAssessment(data['assessment_id']))
    _err(bridge.finishAssessment(data['assessment_id']))


# ------------------------------------------------------------------ reads

def test_latest_scores_is_null_until_a_completion(bridge):
    assert _ok(bridge.getLatestScores()) is None
    data = _ok(bridge.startAssessment('v1'))
    _answer_everything(bridge, data)
    _ok(bridge.finishAssessment(data['assessment_id']))
    latest = _ok(bridge.getLatestScores())
    assert latest['id'] == data['assessment_id']


def test_history_is_newest_first_and_honours_limit(bridge):
    ids = []
    for _ in range(3):
        data = _ok(bridge.startAssessment('v1'))
        _ok(bridge.finishAssessment(data['assessment_id']))
        ids.append(data['assessment_id'])
    hist = _ok(bridge.getAssessmentHistory(2))
    assert len(hist) == 2
    assert [h['id'] for h in hist] == ids[::-1][:2]
    assert len(_ok(bridge.getAssessmentHistory(0))) == 3


# ---------------------------------------------------------------- cadence

def test_status_flips_once_an_administration_completes(bridge):
    before = _ok(bridge.getReassessmentStatus())
    assert before['has_completed_administration'] is False
    data = _ok(bridge.startAssessment('v1'))
    _ok(bridge.finishAssessment(data['assessment_id']))
    after = _ok(bridge.getReassessmentStatus())
    assert after['has_completed_administration'] is True


def test_snoozes_stack_and_count(bridge):
    _ok(bridge.startAssessment('v1'))           # creates the preferences row
    one = _ok(bridge.snoozeReassessment(7))
    two = _ok(bridge.snoozeReassessment(30))
    assert two['snooze_count'] == one['snooze_count'] + 1 == 2
    assert two['next_due_at'] > one['next_due_at']


def test_a_non_positive_snooze_is_refused(bridge):
    _ok(bridge.startAssessment('v1'))
    _err(bridge.snoozeReassessment(0))


def test_cadence_range_is_enforced_with_a_sentence(bridge):
    _ok(bridge.startAssessment('v1'))
    _err(bridge.setReassessmentCadence(29))
    _err(bridge.setReassessmentCadence(731))
    prefs = _ok(bridge.setReassessmentCadence(30))
    assert prefs['cadence_days'] == 30
    assert _ok(bridge.getReassessmentCadence()) == {'cadence_days': 30}
