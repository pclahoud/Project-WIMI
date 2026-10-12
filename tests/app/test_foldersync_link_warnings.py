"""A folder's warnings are shown before the link is recorded (#412).

``preflight()`` returns two kinds of problem. Blocking ones -- the folder is
missing, unwritable, a file, or beyond Windows' path limit -- refuse a link.
The rest were computed and **discarded**: ``finish_link`` raised on the
blocking ones and recorded the link otherwise, so Box's 255-character path
budget never reached a student. Measured on Windows machine B before this
change: linking such a folder through Settings showed only "Cloud sync folder
set.".

Owner's decision on #412: show them in the link dialog, **before** the link is
recorded. So a link job with warnings, not yet acknowledged, records nothing
and returns them; an acknowledged one checks again and records.

The worker/main-thread split is unchanged and is asserted here with folder
sync's Landmine technique: the worker phase of a link still touches no
database, and the decision to record or ask is made in ``finish_link``.
"""
from __future__ import annotations

import time

import pytest

from app.foldersync import ProfileFolderSync
from app.foldersync.jobs import STATE_DONE, STATE_FAILED, STATE_RUNNING, SyncJobs
from app.foldersync.service import LinkNeedsConfirmation, split_problems
from app.foldersync.transport import PATH_TOO_LONG, TransportError
from database.master_db import MasterDatabase

BOX_BUDGET = ("path is 335 characters, over Box (Box Drive)'s 255-character limit. "
              "Choose a folder closer to the top of the drive.")


class Landmine:
    def __getattr__(self, name):  # noqa: D105
        raise AssertionError(f"the link's worker phase touched the database: master_db.{name}")


@pytest.fixture
def machine(tmp_path):
    db = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def user(machine):
    """A profile opened once, which is what records its stable identifier."""
    from database.user_db import UserDatabase

    created = machine.create_user(username="sam", display_name="Sam")
    db = UserDatabase(db_path=machine.ensure_user_database(created.id),
                      user_id=created.id, username=created.username)
    db.close()
    return created


@pytest.fixture
def box_deep_folder(tmp_path):
    """A folder ordinary APIs can reach whose generated paths exceed Box's 255.

    Its own path stays well under 248, so it is created normally on any
    machine; the longest name WIMI would write inside it is what is too long.
    """
    folder = tmp_path
    while len(str(folder)) < 205:
        folder = folder / ("b" * 30)
    folder.mkdir(parents=True)
    return folder


def _await(jobs, job_id, timeout_s=20.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        report = jobs.poll(job_id)
        if report["state"] != STATE_RUNNING:
            return report
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


# ---------------------------------------------------------------- the split

def test_blocking_problems_are_the_four_that_make_a_folder_unusable():
    problems = [
        "the folder does not exist: X",
        "WIMI cannot write to that folder: X",
        "that is a file, not a folder: X",
        f"that folder's path is 300 characters, {PATH_TOO_LONG} (...)",
        BOX_BUDGET,
        "folder component 'x' would not sync: reason",
    ]
    blocking, warnings = split_problems(problems)
    assert blocking == problems[:4]
    assert warnings == problems[4:]


def test_a_problem_nobody_has_written_yet_is_a_warning_not_lost():
    """Warnings are defined by exclusion, so the next one reaches the dialog too."""
    _, warnings = split_problems(["some future preflight finding"])
    assert warnings == ["some future preflight finding"]


# ---------------------------------------------------------------- finish_link

def _plan(user, folder, provider="box"):
    return {"user_id": user.id, "folder": str(folder), "provider_id": provider,
            "sync_id": "11111111-2222-3333-4444-555555555555"}


def test_warnings_unacknowledged_record_nothing_and_come_back(machine, user, tmp_path):
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    result = sync.finish_link(_plan(user, tmp_path), [BOX_BUDGET])
    assert isinstance(result, LinkNeedsConfirmation)
    assert result.warnings == [BOX_BUDGET]
    assert sync.state.get_link(user.id) is None


def test_acknowledged_warnings_record_the_link(machine, user, tmp_path):
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    link = sync.finish_link(_plan(user, tmp_path), [BOX_BUDGET], acknowledged=True)
    assert link.folder == str(tmp_path) and link.provider_id == "box"
    assert sync.state.get_link(user.id) is not None


def test_no_warnings_records_at_once(machine, user, tmp_path):
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    link = sync.finish_link(_plan(user, tmp_path, "generic"), [])
    assert not isinstance(link, LinkNeedsConfirmation)
    assert sync.state.get_link(user.id) is not None


def test_acknowledging_never_overrides_a_blocking_problem(machine, user, tmp_path):
    """Link anyway re-checks; a folder that became unusable meanwhile still refuses."""
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    with pytest.raises(TransportError, match="does not exist"):
        sync.finish_link(_plan(user, tmp_path), ["the folder does not exist: X", BOX_BUDGET],
                         acknowledged=True)
    assert sync.state.get_link(user.id) is None


# ---------------------------------------------------------------- the job

def test_the_link_job_asks_first_then_links_when_acknowledged(machine, user, box_deep_folder):
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    jobs = SyncJobs(sync)
    try:
        first = _await(jobs, jobs.submit_link(user.id, str(box_deep_folder), "box"))
        assert first["state"] == STATE_DONE
        assert isinstance(first["result"], LinkNeedsConfirmation)
        assert any("255-character limit" in w for w in first["result"].warnings)
        assert sync.state.get_link(user.id) is None

        second = _await(jobs, jobs.submit_link(
            user.id, str(box_deep_folder), "box", acknowledged=True))
        assert second["state"] == STATE_DONE
        assert second["result"].provider_id == "box"
        assert sync.state.get_link(user.id) is not None
    finally:
        jobs.shutdown()


def test_the_link_worker_still_touches_no_database(machine, user, box_deep_folder):
    """Carrying warnings to the dialog must not move work across the thread line."""
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    plan = sync.prepare_link(user.id, str(box_deep_folder), "box")
    real, sync.master_db = sync.master_db, Landmine()
    try:
        problems = sync.check_folder(plan)
    finally:
        sync.master_db = real
    assert any("255-character limit" in p for p in problems)


def test_a_blocking_folder_still_fails_the_job(machine, user, tmp_path):
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    jobs = SyncJobs(sync)
    try:
        report = _await(jobs, jobs.submit_link(user.id, str(tmp_path / "nope"), "box",
                                               acknowledged=True))
        assert report["state"] == STATE_FAILED
        assert "does not exist" in report["error"]
    finally:
        jobs.shutdown()


# ---------------------------------------------------------------- the bridge

def test_the_bridge_reports_a_confirmation_as_not_linked(machine, user, tmp_path):
    from app.bridge import DatabaseBridge

    bridge = DatabaseBridge.__new__(DatabaseBridge)
    payload = bridge._job_payload({
        "state": STATE_DONE, "kind": "link",
        "result": LinkNeedsConfirmation(folder=str(tmp_path), provider_id="box",
                                        warnings=[BOX_BUDGET]),
    })
    assert payload["result"] == {
        "linked": False, "needs_confirmation": True, "warnings": [BOX_BUDGET],
        "folder": str(tmp_path), "provider_id": "box",
    }
