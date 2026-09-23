"""
The thread split, and the invariant it exists to protect (#123).

``base_db.py`` says, in as many words, that ``check_same_thread=False`` is set
but that **nothing in the application writes from a second thread**, and that
transaction re-entrancy is tracked per connection with a plain counter. Folder
sync is the first feature that wants a worker thread, so it is the first that
could break that -- and the break would be an interleaved transaction depth:
silent, intermittent, and nothing like a crash.

So the rule is that the worker phase touches the sync folder and **nothing
else**. These tests hold it to that by handing the worker a ``master_db``
that raises on any attribute access at all. If a future edit moves a database
call from ``prepare_*`` or ``finish_*`` into ``perform_*``, this fails
immediately and loudly, which is the only way a rule like this survives.

Markers: ``@pytest.mark.unit`` -- no Qt and no network. ``_await`` polls
against a wall-clock deadline rather than spinning: a tight loop outran the
worker and reported a push as never finished while it was still copying.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.foldersync import ProfileFolderSync
from app.foldersync.jobs import STATE_DONE, STATE_FAILED, STATE_RUNNING, SyncJobs
from app.foldersync.transport import TransportError
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


class Landmine:
    """
    Stands in for ``master_db`` during the worker phase.

    Any attribute access is a failure, including ``repr`` during a traceback,
    so a stray database call cannot hide inside an exception path.
    """

    def __getattr__(self, name):  # noqa: D105
        raise AssertionError(
            f"the worker phase touched the database: master_db.{name}. "
            f"Database work belongs in prepare_* or finish_*, on the caller's "
            f"thread -- see base_db.py's note on check_same_thread."
        )


def _seed(master_db: MasterDatabase, user) -> None:
    """Open the user's DB (which runs migrations) and give it something to ship."""
    db_path = master_db.ensure_user_database(user.id)
    db = UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
    try:
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Threading Exam"),
            )
            exam_id = cur.lastrowid
            cur = db.execute(
                "INSERT INTO review_sessions "
                "(user_id, exam_context_id, total_questions, total_incorrect) "
                "VALUES (?, ?, ?, ?)",
                (user.id, exam_id, 10, 2),
            )
            session_id = cur.lastrowid
            for i in (1, 2):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, i, f"answer_{i}", f"correct_{i}"),
                )
    finally:
        db.close()


@pytest.fixture
def machine(tmp_path):
    db = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "CloudFolder"
    f.mkdir()
    return f


@pytest.fixture
def linked(machine, folder):
    user = machine.create_user(username="sam", display_name="Sam")
    _seed(machine, user)
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    sync.link(user.id, folder, "box")
    return sync, user


# ==================== the worker phase touches no database ====================

@pytest.mark.unit
def test_perform_push_touches_no_database(linked):
    """The load-bearing assertion. Phase 1 sealed the archive; phase 2 copies it."""
    sync, user = linked
    plan = sync.prepare_push(user.id)

    real, sync.master_db = sync.master_db, Landmine()
    try:
        result = sync.perform_push(plan)
    finally:
        sync.master_db = real

    assert result.generation == 1
    sync.finish_push(plan, result)


@pytest.mark.unit
def test_observe_folder_touches_no_database(linked):
    sync, user = linked
    sync.push(user.id)
    inputs = sync.prepare_status(user.id)

    real, sync.master_db = sync.master_db, Landmine()
    try:
        observed = sync.observe_folder(inputs.link)
    finally:
        sync.master_db = real

    assert observed["head"].manifest.generation == 1
    status = sync.finish_status(user.id, inputs, observed)
    assert status.head_generation == 1


@pytest.mark.unit
def test_fetch_from_touches_no_database(linked):
    """``fetch_from`` reads the folder, a staged zip and its user.db as files."""
    sync, user = linked
    sync.push(user.id)
    link = sync.state.get_link(user.id)

    real, sync.master_db = sync.master_db, Landmine()
    try:
        result = sync.fetch_from(link.folder, link.sync_id, link.provider_id)
    finally:
        sync.master_db = real

    assert result.generation == 1
    assert Path(result.archive_path).is_file()


# ==================== the job runner ====================

@pytest.mark.unit
def test_a_push_job_runs_and_reports_its_generation(linked):
    sync, user = linked
    jobs = SyncJobs(sync)
    try:
        job_id = jobs.submit_push(user.id)
        report = _await(jobs, job_id)
        assert report["state"] == STATE_DONE
        assert report["result"].generation == 1
    finally:
        jobs.shutdown()


@pytest.mark.unit
def test_the_work_really_happens_on_another_thread(linked):
    """Otherwise the whole exercise is decoration."""
    sync, user = linked
    seen: list[int] = []
    original = sync.perform_push

    def _spy(plan):
        seen.append(threading.get_ident())
        return original(plan)

    sync.perform_push = _spy
    jobs = SyncJobs(sync)
    try:
        _await(jobs, jobs.submit_push(user.id))
    finally:
        jobs.shutdown()

    assert seen and seen[0] != threading.get_ident()


@pytest.mark.unit
def test_phase_three_runs_on_the_polling_thread(linked):
    """Database work must come back to the caller, not stay on the worker."""
    sync, user = linked
    seen: list[int] = []
    original = sync.finish_push

    def _spy(plan, result):
        seen.append(threading.get_ident())
        return original(plan, result)

    sync.finish_push = _spy
    jobs = SyncJobs(sync)
    try:
        _await(jobs, jobs.submit_push(user.id))
    finally:
        jobs.shutdown()

    assert seen == [threading.get_ident()]


@pytest.mark.unit
def test_an_unlinked_profile_reports_rather_than_raises(machine, folder):
    """A page asks for status before anything is linked. That is a normal state."""
    user = machine.create_user(username="nolink", display_name="N")
    _seed(machine, user)
    sync = ProfileFolderSync(machine, timeout_s=10.0)
    jobs = SyncJobs(sync)
    try:
        report = _await(jobs, jobs.submit_status(user.id))
        assert report["state"] == STATE_DONE
        assert report["result"].linked is False
    finally:
        jobs.shutdown()


@pytest.mark.unit
def test_a_failed_push_reports_the_error_and_cleans_up_staging(linked):
    """A sealed copy of the profile per failed push would accumulate."""
    sync, user = linked
    plan_dirs: list[Path] = []
    original = sync.prepare_push

    def _capture(uid):
        plan = original(uid)
        plan_dirs.append(plan.staged_dir)
        return plan

    sync.prepare_push = _capture
    sync.perform_push = lambda plan: (_ for _ in ()).throw(TransportError("folder went away"))

    jobs = SyncJobs(sync)
    try:
        report = _await(jobs, jobs.submit_push(user.id))
    finally:
        jobs.shutdown()

    assert report["state"] == STATE_FAILED
    assert "folder went away" in report["error"]
    assert plan_dirs and not plan_dirs[0].exists()


@pytest.mark.unit
def test_polling_twice_after_completion_does_not_rerun_anything(linked):
    sync, user = linked
    jobs = SyncJobs(sync)
    try:
        job_id = jobs.submit_push(user.id)
        first = _await(jobs, job_id)
        second = jobs.poll(job_id)
        assert second == first
        # One generation published, not two.
        assert sync.state.get_link(user.id).last_pushed_generation == 1
    finally:
        jobs.shutdown()


@pytest.mark.unit
def test_shutdown_discards_a_push_that_was_never_collected(linked):
    """The window was closed mid-sync. The staged archive must not survive it."""
    sync, user = linked
    plan_dirs: list[Path] = []
    original = sync.prepare_push

    def _capture(uid):
        plan = original(uid)
        plan_dirs.append(plan.staged_dir)
        return plan

    sync.prepare_push = _capture
    jobs = SyncJobs(sync)
    jobs.submit_push(user.id)
    jobs.shutdown()

    assert plan_dirs and not plan_dirs[0].exists()


@pytest.mark.unit
def test_an_unknown_job_id_is_an_error_not_a_crash(linked):
    sync, _user = linked
    jobs = SyncJobs(sync)
    try:
        report = jobs.poll("nope")
        assert report["state"] == STATE_FAILED and "no such sync job" in report["error"]
    finally:
        jobs.shutdown()


def _await(jobs: SyncJobs, job_id: str, timeout_s: float = 20.0) -> dict:
    """
    Poll the way the page will, against a deadline.

    A tight spin here raced the worker and reported "never finished" while the
    push was still copying, so this waits on wall-clock rather than on a
    number of iterations.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        report = jobs.poll(job_id)
        if report["state"] != STATE_RUNNING:
            return report
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished within {timeout_s:g}s")


@pytest.mark.unit
def test_perform_install_touches_no_database(linked, tmp_path):
    """#151's worker phase: fetch, verify and probe the folder. No registry.

    The duplicate check is phase 1 and phase 3 -- both master_db reads,
    both on the caller's thread.
    """
    sync, user = linked
    sync.push(user.id)
    other = MasterDatabase(data_dir=tmp_path / "other_machine", error_logger=None)
    try:
        receiving = ProfileFolderSync(other, timeout_s=10.0)
        link = sync.state.get_link(user.id)
        plan = receiving.prepare_install(link.folder, link.sync_id, "box")

        real, receiving.master_db = receiving.master_db, Landmine()
        try:
            performed = receiving.perform_install(plan)
        finally:
            receiving.master_db = real

        assert performed["fetched"].generation == 1
        result = receiving.finish_install(plan, performed)
        assert result["linked"] is True
    finally:
        other.close()
