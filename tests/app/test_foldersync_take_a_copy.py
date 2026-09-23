"""#151: taking a copy from the folder when there is no conflict.

Two moments, one operation:

* **First install.** A computer with no copy of the profile gets it from
  the folder -- installed, its base recorded, and linked to the folder it
  came from (owner's decision: auto-link).
* **Catching up.** A linked computer takes the newer copy another computer
  built on its own. That is ``keep_remote`` pointed at the head, and it
  needs no send.

Plus the owner's rule for the second: **detect unsent work and offer both**
-- which needs an honest answer to "has this computer changed since it last
synced?" That answer is ``local_changes``, and it says only what it checked.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.foldersync import ProfileFolderSync
from app.foldersync.resolution import KEEP_REMOTE, resolve_fork
from app.foldersync.transport import TransportError
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


def _seed(master: MasterDatabase, username: str, entries: int) -> int:
    user = master.create_user(username=username, display_name=username.title())
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    try:
        with db.transaction():
            exam = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, 'Copy Exam')",
                (user.id,)).lastrowid
            session = db.execute(
                "INSERT INTO review_sessions (user_id, exam_context_id,"
                " total_questions, total_incorrect) VALUES (?, ?, 10, 1)",
                (user.id, exam)).lastrowid
            for i in range(1, entries + 1):
                db.execute(
                    "INSERT INTO question_entries (review_session_id, entry_order,"
                    " user_answer, correct_answer) VALUES (?, ?, 'a', 'c')", (session, i))
    finally:
        db.close()
    return user.id


def _add(master: MasterDatabase, user_id: int, n: int) -> None:
    user = master.get_user(user_id=user_id)
    db = UserDatabase(db_path=master.ensure_user_database(user_id),
                      user_id=user_id, username=user.username)
    try:
        with db.transaction():
            session = db.execute("SELECT id FROM review_sessions LIMIT 1").fetchone()[0]
            start = db.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
            for i in range(start + 1, start + 1 + n):
                db.execute(
                    "INSERT INTO question_entries (review_session_id, entry_order,"
                    " user_answer, correct_answer) VALUES (?, ?, 'a', 'c')", (session, i))
    finally:
        db.close()


def _entries(master: MasterDatabase, user_id: int) -> int:
    conn = sqlite3.connect(str(master.ensure_user_database(user_id)))
    try:
        return conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def two(tmp_path):
    """A has a linked profile with one published generation; B has nothing yet."""
    folder = tmp_path / "cloud"
    folder.mkdir()
    a_master = MasterDatabase(data_dir=tmp_path / "A", error_logger=None)
    b_master = MasterDatabase(data_dir=tmp_path / "B", error_logger=None)
    a_id = _seed(a_master, "student", entries=10)
    a = ProfileFolderSync(a_master, timeout_s=10.0)
    a.link(a_id, folder, "generic")
    g1 = a.push(a_id)
    b = ProfileFolderSync(b_master, timeout_s=10.0)
    yield {"folder": folder, "g1": g1, "sync_id": a.state.get_link(a_id).sync_id,
           "a": (a_master, a, a_id), "b": (b_master, b), "tmp": tmp_path}
    a_master.close()
    b_master.close()


# ==================== first install ====================

@pytest.mark.unit
def test_first_install_is_installed_based_and_linked(two):
    b_master, b = two["b"]
    result = b.install_from_folder(two["folder"], two["sync_id"], "generic")

    b_id = int(result["installed"]["user_id"])
    assert result["linked"] is True and result["link_error"] is None
    link = b.state.get_link(b_id)
    assert link.folder == str(Path(two["folder"]))
    assert link.base_sha256 == two["g1"].sha256, "the installed generation is not its base (#149)"
    assert _entries(b_master, b_id) == 10

    _add(b_master, b_id, 1)
    assert b.push(b_id).parent_generation == 1, "the first push must build on what was installed"


@pytest.mark.unit
def test_a_profile_already_here_is_refused_before_anything_downloads(two):
    """A second copy sharing a uuid must never be linked (#124's keep-both rule)."""
    a_master, a, _a_id = two["a"]
    staging = a.staging_dir
    before = sorted(p.name for p in staging.iterdir())

    with pytest.raises(TransportError, match="already on this computer"):
        a.prepare_install(two["folder"], two["sync_id"], "generic")

    assert sorted(p.name for p in staging.iterdir()) == before, "it downloaded first"


@pytest.mark.unit
def test_the_duplicate_check_runs_again_after_the_download(two):
    """Another install may land while the worker fetches."""
    b_master, b = two["b"]
    plan = b.prepare_install(two["folder"], two["sync_id"], "generic")
    performed = b.perform_install(plan)
    b.install_from_folder(two["folder"], two["sync_id"], "generic")   # lands meanwhile

    with pytest.raises(TransportError, match="already on this computer"):
        b.finish_install(plan, performed)
    assert len(b_master.find_users_by_profile_uuid(two["sync_id"])) == 1


@pytest.mark.unit
def test_a_copy_that_needs_a_newer_wimi_installs_nothing(two):
    b_master, b = two["b"]
    plan = b.prepare_install(two["folder"], two["sync_id"], "generic")
    performed = b.perform_install(plan)
    performed["fetched"].blocked = True
    performed["fetched"].schema_reason = "made by a newer WIMI"

    with pytest.raises(TransportError, match="newer WIMI"):
        b.finish_install(plan, performed)
    assert b_master.find_users_by_profile_uuid(two["sync_id"]) == []
    assert not Path(performed["fetched"].archive_path).exists(), "staging left behind"


@pytest.mark.unit
def test_a_link_that_fails_leaves_a_usable_install_and_says_so(two):
    """Undoing an install the student can use would be worse than an unlinked profile."""
    b_master, b = two["b"]
    plan = b.prepare_install(two["folder"], two["sync_id"], "generic")
    performed = b.perform_install(plan)
    performed["problems"] = [f"{two['folder']} does not exist"]

    result = b.finish_install(plan, performed)
    assert result["linked"] is False and "does not exist" in result["link_error"]
    b_id = int(result["installed"]["user_id"])
    assert _entries(b_master, b_id) == 10
    assert b.state.get_link(b_id) is None


# ==================== has this computer changed? ====================

@pytest.mark.unit
def test_an_unchanged_copy_reports_checked_and_no_difference(two):
    b_master, b = two["b"]
    b_id = int(b.install_from_folder(two["folder"], two["sync_id"], "generic")["installed"]["user_id"])
    changes = b.status(b_id).local_changes
    assert changes["checked"] is True and changes["differs"] == []
    assert changes["base_generation"] == 1


@pytest.mark.unit
def test_work_added_here_is_named_figure_by_figure(two):
    b_master, b = two["b"]
    b_id = int(b.install_from_folder(two["folder"], two["sync_id"], "generic")["installed"]["user_id"])
    _add(b_master, b_id, 3)

    differs = {d["field"]: d for d in b.status(b_id).local_changes["differs"]}
    assert differs["entries"]["here"] == 13 and differs["entries"]["then"] == 10
    # logged_last is not asserted: it has one-second resolution, and this
    # test adds entries inside the second it seeded them. On a real computer
    # the work comes minutes later and the date differs too.


@pytest.mark.unit
def test_with_no_base_it_says_it_cannot_tell(two):
    """A profile linked but never synced: nothing to compare against."""
    b_master, b = two["b"]
    b_id = _seed(b_master, "other", entries=2)
    changes = b.local_changes(b_id, None, "unknown")
    assert changes["checked"] is False and "no copy recorded" in changes["reason"]


# ==================== catching up ====================

@pytest.mark.unit
def test_catching_up_takes_the_head_and_needs_no_send(two):
    """The ordinary case #151 exists for: the other computer built on mine."""
    a_master, a, a_id = two["a"]
    b_master, b = two["b"]
    b_id = int(b.install_from_folder(two["folder"], two["sync_id"], "generic")["installed"]["user_id"])
    _add(a_master, a_id, 5)
    g2 = a.push(a_id)

    status = b.status(b_id)
    assert status.base_relation == "behind"
    assert status.relation_detail["blob_name"] == g2.blob_name
    assert status.forks == []

    link = b.state.get_link(b_id)
    staged = b.stage_for_resolution(link, g2.blob_name, b._device_identity().device_id)
    resolution = resolve_fork(b_master, user_id=b_id, choice=KEEP_REMOTE,
                              incoming_archive=staged["archive_path"],
                              safety_dir=two["tmp"] / "safety")
    send = b.finish_resolution(b_id, KEEP_REMOTE, staged, resolution)

    assert send["send_needed"] is False
    assert _entries(b_master, b_id) == 15
    after = b.status(b_id)
    assert after.base_relation == "current" and after.local_changes["differs"] == []
