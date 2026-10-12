"""#501: the profile-deletion grace period is measured on one clock, UTC.

``soft_deleted_at`` is written by SQLite's ``CURRENT_TIMESTAMP`` (UTC) and
read back naive. Its three readers -- the purge, the restore guard and the
picker's countdown -- compared it with ``datetime.now()``, which is local, so
east of UTC the only irreversible profile deletion in WIMI fired early by the
machine's offset.

Every test here runs on a simulated local clock of **UTC+14** (Kiritimati),
by replacing ``datetime`` in the two modules that read it. That makes the
result independent of the machine the suite runs on -- the development box is
west of UTC, which is the harmless direction -- and leaves SQLite's own
``datetime('now')`` on real UTC, which is the point.

Plus the two literal "10 days" the picker carried where the constant belongs.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.bridge_domains.profiles as profiles_module
import database.master_db as master_db_module
from app.bridge import DatabaseBridge
from database.exceptions import DeletionError
from database.master_db import MasterDatabase

REPO = Path(__file__).resolve().parents[2]
GRACE = MasterDatabase.DELETION_GRACE_PERIOD_DAYS


class _Kiritimati(datetime):
    """``datetime`` whose naive ``now()`` is local time at UTC+14."""

    @classmethod
    def now(cls, tz=None):
        real = datetime.now(timezone.utc)
        if tz is None:
            return (real + timedelta(hours=14)).replace(tzinfo=None)
        return real.astimezone(tz)


@pytest.fixture
def far_east(monkeypatch):
    monkeypatch.setattr(master_db_module, "datetime", _Kiritimati)
    # master's profiles.py imported datetime for its countdown; the fix does not.
    monkeypatch.setattr(profiles_module, "datetime", _Kiritimati, raising=False)


@pytest.fixture
def master(tmp_path):
    db = MasterDatabase(data_dir=tmp_path, error_logger=None)
    db.bootstrap_first_user(username="admin", display_name="Admin",
                            email="admin@test.com")
    yield db
    db.close()


def _deleted(master: MasterDatabase, stamp_sql: str) -> int:
    """A confirmed soft-deleted profile whose stamp is ``datetime('now', ...)``."""
    user = master.create_user(username="leaving", display_name="Leaving")
    master.soft_delete_user(user.id)
    master.confirm_user_deletion(user.id)
    with master.transaction():
        master.execute(f"UPDATE users SET soft_deleted_at = {stamp_sql} WHERE id = ?",
                       (user.id,))
    return user.id


def test_the_clock_is_really_moved(far_east):
    """Control: without this the far-east tests below prove nothing."""
    gap = master_db_module.datetime.now() - datetime.now(timezone.utc).replace(tzinfo=None)
    assert timedelta(hours=13, minutes=59) < gap < timedelta(hours=14, minutes=1)


# ---------------------------------------------------------------- purge

def test_the_purge_waits_for_the_whole_grace_period(master, far_east):
    uid = _deleted(master, f"datetime('now', '-{GRACE} days', '+3 hours')")

    assert master.permanently_delete_expired_users() == []
    assert master.get_user(uid) is not None


def test_the_purge_still_fires_once_the_grace_period_is_over(master, far_east):
    """Positive control: the purge is not simply switched off."""
    uid = _deleted(master, f"datetime('now', '-{GRACE} days', '-1 minutes')")

    assert master.permanently_delete_expired_users() == [uid]


# ---------------------------------------------------------------- restore

def test_restore_is_allowed_until_the_grace_period_ends(master, far_east):
    uid = _deleted(master, f"datetime('now', '-{GRACE} days', '+3 hours')")

    assert master.restore_user(uid).account_status == "active"


def test_restore_is_refused_after_it(master, far_east):
    uid = _deleted(master, f"datetime('now', '-{GRACE} days', '-1 hours')")

    with pytest.raises(DeletionError, match="Grace period expired"):
        master.restore_user(uid)


# ---------------------------------------------------------------- countdown

def _listed(master: MasterDatabase) -> dict:
    bridge = DatabaseBridge(master_db=master, user_db=None)
    response = json.loads(bridge.listProfiles())
    assert response["success"], response
    return response["data"]


def test_a_profile_deleted_ten_hours_ago_has_the_whole_period_left(master, far_east):
    """Local time says 24 hours have passed; UTC says 10. Only UTC is true."""
    _deleted(master, "datetime('now', '-10 hours')")

    deleted, = _listed(master)["deleted"]
    assert deleted["days_remaining"] == GRACE


def test_the_countdown_moves_on_whole_days(master, far_east):
    _deleted(master, "datetime('now', '-3 days', '-1 hours')")

    deleted, = _listed(master)["deleted"]
    assert deleted["days_remaining"] == GRACE - 3


# ---------------------------------------------------------------- the page

def test_the_picker_is_told_the_grace_period(master):
    assert _listed(master)["grace_period_days"] == GRACE


@pytest.mark.parametrize("path", ["src/web/html/profile_select.html",
                                  "src/web/js/profile_select.js"])
def test_the_picker_states_no_grace_period_of_its_own(path):
    text = (REPO / path).read_text(encoding="utf-8")
    assert not re.search(rf"\b{GRACE}\s*days?\b", text), (
        f"{path} hardcodes the grace period instead of reading it from the bridge")
