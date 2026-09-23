"""#148 / #149 through the service: the base, and a choice that stays local.

``test_foldersync_lineage.py`` proves the heads rule with hand-written
parents. This file proves the service **writes** the right parents -- which
is where #149 actually lived. The transport was never wrong about what it
was told; the service told it the folder head, and a device that had never
fetched published its content as a child of work it never had.

The owner's decisions these encode (#148, 2026-09-22):

* choosing between two copies **stays on this device until the student
  sends** -- nothing reaches the folder on the choosing;
* the device whose copy was not kept is **told**, not left to find out;
* ``keep_remote`` on the open profile closes and reopens it (bridge-level;
  see ``test_foldersync_bridge.py``). Here it runs with no profile open.

Every scene is two app-data directories and one folder, as on hardware.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.foldersync import ProfileFolderSync, SyncJobs
from app.foldersync.resolution import KEEP_LOCAL, KEEP_REMOTE, resolve_fork
from app.foldersync.service import FolderMovedSinceResolution
from app.foldersync.state import SyncState
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


# ==================== scene ====================

def _seed(master: MasterDatabase, username: str, entries: int) -> int:
    user = master.create_user(username=username, display_name=username.title())
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    try:
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Lineage Exam"))
            cur = db.execute(
                "INSERT INTO review_sessions (user_id, exam_context_id,"
                " total_questions, total_incorrect) VALUES (?, ?, 10, 1)",
                (user.id, cur.lastrowid))
            for i in range(1, entries + 1):
                db.execute(
                    "INSERT INTO question_entries (review_session_id, entry_order,"
                    " user_answer, correct_answer) VALUES (?, ?, 'a', 'c')",
                    (cur.lastrowid, i))
    finally:
        db.close()
    return user.id


def _add(master: MasterDatabase, user_id: int, n: int) -> None:
    user = master.get_user(user_id=user_id)
    db = UserDatabase(db_path=master.ensure_user_database(user_id),
                      user_id=user_id, username=user.username)
    try:
        with db.transaction():
            session_id = db.execute(
                "SELECT id FROM review_sessions ORDER BY id LIMIT 1").fetchone()[0]
            start = db.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
            for i in range(start + 1, start + 1 + n):
                db.execute(
                    "INSERT INTO question_entries (review_session_id, entry_order,"
                    " user_answer, correct_answer) VALUES (?, ?, 'a', 'c')",
                    (session_id, i))
    finally:
        db.close()


def _entries(master: MasterDatabase, user_id: int) -> int:
    conn = sqlite3.connect(str(master.ensure_user_database(user_id)))
    try:
        return conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
    finally:
        conn.close()


def _files(folder: Path) -> list:
    return sorted(p.name for p in (folder / "WIMI").rglob("*") if p.is_file())


@pytest.fixture
def scene(tmp_path):
    """A (desktop) published generation 1; B (laptop) installed it from the folder."""
    folder = tmp_path / "cloud"
    folder.mkdir()
    a_master = MasterDatabase(data_dir=tmp_path / "A", error_logger=None)
    b_master = MasterDatabase(data_dir=tmp_path / "B", error_logger=None)

    a_id = _seed(a_master, "student", entries=4)
    a = ProfileFolderSync(a_master, timeout_s=10.0)
    a.link(a_id, folder, "generic")
    g1 = a.push(a_id)

    b = ProfileFolderSync(b_master, timeout_s=10.0)
    sync_id = a.state.get_link(a_id).sync_id
    b_id = int(b.install_from_folder(folder, sync_id, "generic")["installed"]["user_id"])
    b.link(b_id, folder, "generic")

    yield {"folder": folder, "tmp": tmp_path, "g1": g1, "sync_id": sync_id,
           "a": (a_master, a, a_id), "b": (b_master, b, b_id)}
    a_master.close()
    b_master.close()


def _diverge(scene):
    """Both devices work from generation 1; A publishes, then B publishes WITHOUT fetching.

    This is #149's exact reproduction from the two-machine test on
    2026-09-22, and before the fix it produced a linear history: B's
    generation claimed A's as its parent, and A's work silently stopped
    being the head.
    """
    a_master, a, a_id = scene["a"]
    b_master, b, b_id = scene["b"]
    _add(a_master, a_id, 20)
    ga = a.push(a_id)
    _add(b_master, b_id, 3)
    gb = b.push(b_id)          # B never fetched ga
    return ga, gb


# ==================== #149 ====================

@pytest.mark.unit
def test_149_a_device_that_never_fetched_publishes_a_fork_not_a_false_descendant(scene):
    ga, gb = _diverge(scene)
    assert gb.parent_generation == 1, (
        "#149: B's generation claimed a parent it never had -- it must name "
        f"generation 1, what B actually built on, not {gb.parent_generation}")

    _, a, a_id = scene["a"]
    _, b, b_id = scene["b"]
    for sync, uid in ((a, a_id), (b, b_id)):
        status = sync.status(uid)
        assert len(status.forks) == 1, "the divergence was not reported"
        blobs = {s["blob_name"] for s in status.forks[0]["sides"]}
        assert blobs == {ga.blob_name, gb.blob_name}, (
            "A's work must still be one of the heads, not silently dropped")
        assert status.forks[0]["parent_generation"] == 1


@pytest.mark.unit
def test_the_base_follows_what_this_device_published(scene):
    _, a, a_id = scene["a"]
    _add(scene["a"][0], a_id, 1)
    pushed = a.push(a_id)
    link = a.state.get_link(a_id)
    assert link.base_sha256 == pushed.sha256
    assert link.base_generation == pushed.generation


@pytest.mark.unit
def test_an_install_from_the_folder_records_its_base(scene):
    link = scene["b"][1].state.get_link(scene["b"][2])
    assert link.base_sha256 == scene["g1"].sha256
    assert link.base_generation == 1


@pytest.mark.unit
def test_every_push_has_its_own_digest_even_with_nothing_changed(scene):
    """Two builds inside one second were byte-identical before the nonce.

    A generation would then name itself as its parent and be refused as
    malformed -- a generation the student published, unreadable.
    """
    _, a, a_id = scene["a"]
    first = a.push(a_id)
    second = a.push(a_id)
    assert first.sha256 != second.sha256
    assert a.status(a_id).rejected == []


def _forget_base(sync, user_id):
    """Put a link back in the state a pre-#148 link is in: no recorded base."""
    link = sync.state.get_link(user_id)
    link.base_sha256 = None
    link.base_generation = 0
    link.pending = None
    sync.state.put_link(link)


@pytest.mark.unit
def test_a_legacy_link_with_no_recorded_base_claims_no_ancestor(scene):
    """No guessing the base from the last push -- found on hardware.

    This test used to assert the opposite. Machine A's round-two link
    predated recorded bases: it had pushed generation 2 and then taken the
    other side with a pre-#148 keep_remote, which recorded nothing. The
    guess named A's own generation while A held B's rows, so a push built on
    it would claim a descent that is not true -- #149's class of error. An
    unrecorded base is unknown, and the next push says so by being a root.
    """
    _, a, a_id = scene["a"]
    _forget_base(a, a_id)             # last_pushed_generation is still 1

    _add(scene["a"][0], a_id, 1)
    pushed = a.push(a_id)
    assert pushed.parent_generation == 0


@pytest.mark.unit
def test_with_no_recorded_base_no_side_is_called_this_computers(scene):
    """Machine A's exact state: it published a side, and holds nobody knows what.

    The device-id fallback labelled A's own generation "this computer's copy".
    Neither side is known to be held, so neither is labelled -- in status or
    in the report the student chooses from.
    """
    ga, _gb = _diverge(scene)
    _, a, a_id = scene["a"]
    _forget_base(a, a_id)

    status = a.status(a_id)
    assert status.forks, "precondition: the fork is still there"
    assert not [s for s in status.forks[0]["sides"] if s["is_local"]], (
        "a side was labelled this computer's copy on the strength of who published it")
    report = a.fork_report(a_id)
    assert not [s for s in report.sides if s.is_local]


@pytest.mark.unit
def test_a_side_this_device_published_but_gave_up_is_not_called_its_own(scene):
    """After keep_remote the device holds the OTHER side. The label follows the rows."""
    ga, gb = _diverge(scene)
    _, b, b_id = scene["b"]
    _resolve(b, b_id, KEEP_REMOTE, ga.blob_name, scene["tmp"])

    sides = {s["blob_name"]: s["is_local"] for s in b.status(b_id).forks[0]["sides"]}
    assert sides == {ga.blob_name: True, gb.blob_name: False}, (
        f"B published {gb.blob_name} but holds {ga.blob_name}: {sides}")


@pytest.mark.unit
def test_seen_is_never_mistaken_for_have(scene):
    """The substitution #149 made, guarded directly.

    B has *looked* at generation 2 (a status call records it as seen) but
    never fetched it. Its next push must still parent to what it has.
    """
    a_master, a, a_id = scene["a"]
    _, b, b_id = scene["b"]
    _add(a_master, a_id, 5)
    a.push(a_id)
    b.status(b_id)
    assert b.state.get_link(b_id).last_seen_generation == 2

    pushed = b.push(b_id)
    assert pushed.parent_generation == 1


# ==================== a choice stays local until sent ====================

def _resolve(sync, user_id, choice, other_blob, tmp):
    """Resolve exactly as the job does: stage, apply, record."""
    link = sync.state.get_link(user_id)
    device_id = sync._device_identity().device_id
    staged = sync.stage_for_resolution(link, other_blob, device_id)
    resolution = resolve_fork(
        sync.master_db, user_id=user_id, choice=choice,
        incoming_archive=staged["archive_path"], safety_dir=tmp / "safety")
    return sync.finish_resolution(user_id, choice, staged, resolution)


@pytest.mark.unit
def test_choosing_writes_nothing_to_the_folder(scene):
    ga, _gb = _diverge(scene)
    _, b, b_id = scene["b"]
    before = _files(scene["folder"])

    send = _resolve(b, b_id, KEEP_LOCAL, ga.blob_name, scene["tmp"])

    assert _files(scene["folder"]) == before, "choosing reached the folder"
    assert send["send_needed"] is True
    assert b.state.get_link(b_id).pending is not None


@pytest.mark.unit
def test_the_chooser_sees_it_as_chosen_and_the_other_device_still_sees_a_fork(scene):
    """Until the send, the other device has not been told anything -- by design."""
    ga, _gb = _diverge(scene)
    _, a, a_id = scene["a"]
    _, b, b_id = scene["b"]
    _resolve(b, b_id, KEEP_LOCAL, ga.blob_name, scene["tmp"])

    mine = b.status(b_id)
    assert mine.pending_state == "ready"
    assert mine.forks and mine.forks[0]["resolved_here"] is True

    theirs = a.status(a_id)
    assert theirs.forks and theirs.forks[0]["resolved_here"] is False
    assert theirs.pending is None


@pytest.mark.unit
def test_sending_clears_the_fork_for_both_devices_and_tells_the_other_it_lost(scene):
    ga, gb = _diverge(scene)
    _, a, a_id = scene["a"]
    _, b, b_id = scene["b"]
    _resolve(b, b_id, KEEP_LOCAL, ga.blob_name, scene["tmp"])

    sent = b.push(b_id)

    assert b.state.get_link(b_id).pending is None, "a sent choice was not cleared"
    assert b.status(b_id).forks == []
    assert b.status(b_id).base_relation == "current"

    theirs = a.status(a_id)
    assert theirs.base_relation == "superseded", (
        "the device whose copy was not kept must be told")
    assert theirs.relation_detail["blob_name"] == sent.blob_name
    # Offered as the same three-way choice, through the same report.
    assert len(theirs.forks) == 1 and theirs.forks[0]["set_aside"] is True
    local = [s for s in theirs.forks[0]["sides"] if s["is_local"]]
    assert [s["blob_name"] for s in local] == [ga.blob_name]


@pytest.mark.unit
def test_a_send_is_refused_when_the_folder_moved_after_the_choice(scene):
    """A head the student never saw must not be retired, or left to re-fork unannounced."""
    a_master, a, a_id = scene["a"]
    ga, _gb = _diverge(scene)
    _, b, b_id = scene["b"]
    _resolve(b, b_id, KEEP_LOCAL, ga.blob_name, scene["tmp"])

    _add(a_master, a_id, 2)
    late = a.push(a_id)                 # A keeps working after B chose
    before = _files(scene["folder"])

    with pytest.raises(FolderMovedSinceResolution) as caught:
        b.push(b_id)

    assert [m.blob_name for m in caught.value.unseen] == [late.blob_name]
    assert _files(scene["folder"]) == before, "a refused send wrote something"
    assert b.state.get_link(b_id).pending is not None, "the choice was thrown away"
    status = b.status(b_id)
    assert status.pending_state == "folder_moved"
    assert status.forks[0]["resolved_here"] is False
    assert [u["blob_name"] for u in status.pending["unseen"]] == [late.blob_name]


@pytest.mark.unit
def test_the_refused_send_goes_through_the_job_as_a_failure_with_the_reason(scene):
    a_master, a, a_id = scene["a"]
    ga, _gb = _diverge(scene)
    _, b, b_id = scene["b"]
    _resolve(b, b_id, KEEP_LOCAL, ga.blob_name, scene["tmp"])
    _add(a_master, a_id, 1)
    a.push(a_id)

    jobs = SyncJobs(b)
    try:
        job = jobs.submit_push(b_id)
        import time
        deadline = time.monotonic() + 30
        report = jobs.poll(job)
        while report["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
            report = jobs.poll(job)
    finally:
        jobs.shutdown()
    assert report["state"] == "failed"
    assert "changed since you chose" in report["error"]


# ==================== keep_remote ====================

@pytest.mark.unit
def test_keep_remote_on_a_fork_replaces_locally_and_still_needs_a_send(scene):
    """B takes A's copy. B's own generation is still a head until B retires it."""
    ga, gb = _diverge(scene)
    a_master, a, a_id = scene["a"]
    b_master, b, b_id = scene["b"]

    send = _resolve(b, b_id, KEEP_REMOTE, ga.blob_name, scene["tmp"])

    assert _entries(b_master, b_id) == _entries(a_master, a_id) == 24
    assert send["send_needed"] is True
    link = b.state.get_link(b_id)
    assert link.base_sha256 == ga.sha256, "B now holds A's copy; that is its base"
    assert link.pending["supersedes"] == [gb.sha256]

    b.push(b_id)
    assert a.status(a_id).forks == []
    assert a.status(a_id).base_relation == "behind", (
        "B built on A's copy, so A is simply behind -- not set aside")


@pytest.mark.unit
def test_accepting_the_kept_copy_on_the_losing_device_needs_no_send(scene):
    """The common end of a fork: the other device just takes what was kept."""
    ga, _gb = _diverge(scene)
    a_master, a, a_id = scene["a"]
    b_master, b, b_id = scene["b"]
    _resolve(b, b_id, KEEP_LOCAL, ga.blob_name, scene["tmp"])
    sent = b.push(b_id)

    send = _resolve(a, a_id, KEEP_REMOTE, sent.blob_name, scene["tmp"])

    assert send["send_needed"] is False
    assert a.state.get_link(a_id).pending is None
    assert _entries(a_master, a_id) == _entries(b_master, b_id)
    status = a.status(a_id)
    assert status.base_relation == "current"
    assert status.forks == []


# ==================== state edge cases ====================

@pytest.mark.unit
def test_a_malformed_pending_does_not_unlink_the_profile(tmp_path):
    state = SyncState(tmp_path)
    state.link_or_create(7, "11111111-2222-3333-4444-555555555555", str(tmp_path))
    raw = json.loads(state.state_path.read_text())
    raw["links"]["7"]["pending"] = {"parents": "not a list"}
    state.state_path.write_text(json.dumps(raw))

    link = SyncState(tmp_path).get_link(7)
    assert link is not None, "a bad pending made the profile look unlinked"
    assert link.pending is None


@pytest.mark.unit
def test_a_push_clears_only_the_choice_it_carried(tmp_path):
    """A student who chose again while a send was in flight keeps the newer choice."""
    state = SyncState(tmp_path)
    state.link_or_create(7, "11111111-2222-3333-4444-555555555555", str(tmp_path))
    old = {"choice": "keep_local", "parents": [], "supersedes": ["a" * 64],
           "saw_heads": ["a" * 64], "resolved_at": "t1"}
    new = dict(old, resolved_at="t2")
    state.record_resolution(7, new)

    state.record_push(7, 3, "b" * 64, sent_pending=SyncState(tmp_path).get_link(7).pending | {"resolved_at": "t1"})
    assert state.get_link(7).pending["resolved_at"] == "t2"

    state.record_push(7, 4, "c" * 64, sent_pending=state.get_link(7).pending)
    assert state.get_link(7).pending is None


@pytest.mark.unit
def test_an_install_base_for_another_profile_segment_is_not_adopted(tmp_path):
    state = SyncState(tmp_path)
    state.record_install_base(7, "aaaaaaaa-0000-0000-0000-000000000000", "d" * 64, 5)
    link = state.link_or_create(7, "bbbbbbbb-0000-0000-0000-000000000000", str(tmp_path))
    assert link.base_sha256 is None
