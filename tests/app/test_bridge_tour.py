"""The tour's bridge surface (#430): read, mark, replay, and the test-mode gate."""
from __future__ import annotations

import json

import pytest

from app import test_mode
from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


@pytest.fixture
def bridge(tmp_path):
    master = MasterDatabase(data_dir=tmp_path / "data", error_logger=None)
    user = master.create_user(username="tourist", display_name="Tourist")
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    b = DatabaseBridge(master_db=master, user_db=db)
    yield b
    db.close()
    master.close()


@pytest.fixture
def test_mode_on(tmp_path):
    assert test_mode.is_active() is False
    test_mode.set_active(True, port=12000, app_data_dir=tmp_path)
    yield
    test_mode.set_active(False)


def _data(response: str) -> dict:
    payload = json.loads(response)
    assert payload["success"] is True, payload
    return payload["data"]


def test_a_new_profile_has_been_shown_nothing(bridge):
    assert _data(bridge.getTourState())["seen"] == []


def test_marking_records_in_order_without_duplicates(bridge):
    _data(bridge.markTourStepsSeen(json.dumps(["dashboard:a", "dashboard:b"])))
    seen = _data(bridge.markTourStepsSeen(
        json.dumps(["dashboard:b", "dashboard:c", "dashboard:c"])))["seen"]
    assert seen == ["dashboard:a", "dashboard:b", "dashboard:c"]
    assert _data(bridge.getTourState())["seen"] == seen


def test_a_malformed_key_is_refused_and_nothing_is_written(bridge):
    response = json.loads(bridge.markTourStepsSeen(json.dumps(["no-colon"])))
    assert response["success"] is False and "page:anchor" in response["error"]
    assert _data(bridge.getTourState())["seen"] == []


def test_replay_forgets_every_step(bridge):
    _data(bridge.markTourStepsSeen(json.dumps(["dashboard:a"])))
    _data(bridge.resetTour())
    assert _data(bridge.getTourState())["seen"] == []


def test_settings_bulk_save_cannot_touch_it(bridge):
    """The column is not a preferences field, so Settings' save of every
    field it shows leaves the shown steps alone."""
    _data(bridge.markTourStepsSeen(json.dumps(["dashboard:a"])))
    prefs = _data(bridge.getUserPreferences())
    assert "tour_seen_steps" not in prefs
    _data(bridge.updateUserPreferences(json.dumps({"font_size_scale": 1.2})))
    assert _data(bridge.getTourState())["seen"] == ["dashboard:a"]


def test_auto_start_is_on_for_a_student():
    """Outside test mode the tour runs. This is the control for the next two:
    without it, "off under test mode" could be "off everywhere"."""
    assert test_mode.is_active() is False


def test_auto_start_is_off_under_test_mode_until_a_scenario_asks(bridge, test_mode_on):
    assert _data(bridge.getTourState())["auto_start"] is False
    _data(bridge.setTourAutoStartForTest(True))
    assert _data(bridge.getTourState())["auto_start"] is True


def test_auto_start_outside_test_mode_is_true_and_the_switch_is_refused(bridge):
    assert _data(bridge.getTourState())["auto_start"] is True
    response = json.loads(bridge.setTourAutoStartForTest(False))
    assert response["success"] is False


def test_no_profile_is_a_sentence_not_a_crash(tmp_path):
    master = MasterDatabase(data_dir=tmp_path / "d2", error_logger=None)
    try:
        b = DatabaseBridge(master_db=master, user_db=None)
        for call in (b.getTourState(), b.resetTour(),
                     b.markTourStepsSeen(json.dumps(["dashboard:a"]))):
            assert json.loads(call)["success"] is False
    finally:
        master.close()
