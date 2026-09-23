"""#124 end to end: a real fork in a real folder, detected, reported, resolved.

The unit tests above build fork *inputs* by hand. This one makes an actual
fork the way two devices do — two app-data directories pointed at one
directory, both pushing from the same parent — and then drives detection,
the report and each resolution through the same code the bridge will call.

It exists because the pieces are individually tested and their *seams* are
not: a fork that is detected but whose sides cannot be staged, a report
built from manifests that were never written to disk, a resolution handed an
archive nobody verified. Those only show up when the whole path runs.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.foldersync import ProfileFolderSync
from app.foldersync.resolution import KEEP_BOTH, KEEP_LOCAL, KEEP_REMOTE, resolve_fork
from app.profile_archive import build_profile_archive  # noqa: F401 - used by later tests
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


def _add_entries(master: MasterDatabase, user_id: int, username: str, n: int,
                 subject: str | None = None) -> None:
    db = UserDatabase(db_path=master.ensure_user_database(user_id),
                      user_id=user_id, username=username)
    try:
        with db.transaction():
            row = db.execute(
                "SELECT id FROM review_sessions ORDER BY id LIMIT 1").fetchone()
            session_id = row[0]
            start = db.execute(
                "SELECT COUNT(*) FROM question_entries").fetchone()[0]
            for i in range(start + 1, start + 1 + n):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer)"
                    " VALUES (?, ?, ?, ?)",
                    (session_id, i, f"a{i}", f"c{i}"))
            if subject:
                db.execute(
                    "INSERT INTO subject_nodes (exam_context, name, level_type, status)"
                    " VALUES (?, ?, 'Topic', 'active')", ("Fork Exam", subject))
    finally:
        db.close()


def _seed(master: MasterDatabase, username: str, entries: int = 4):
    user = master.create_user(username=username, display_name=username.title())
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    try:
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Fork Exam"))
            exam_id = cur.lastrowid
            db.execute(
                "INSERT INTO subject_nodes (exam_context, name, level_type, status)"
                " VALUES (?, ?, 'Topic', 'active')", ("Fork Exam", "Shared Topic"))
            cur = db.execute(
                "INSERT INTO review_sessions "
                "(user_id, exam_context_id, date_encountered, total_questions,"
                " total_incorrect) VALUES (?, ?, '2026-01-01', ?, ?)",
                (user.id, exam_id, 10, entries))
            session_id = cur.lastrowid
            for i in range(1, entries + 1):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer)"
                    " VALUES (?, ?, ?, ?)",
                    (session_id, i, f"a{i}", f"c{i}"))
    finally:
        db.close()
    return user


def _entries(master: MasterDatabase, user_id: int) -> int:
    conn = sqlite3.connect(str(master.ensure_user_database(user_id)))
    try:
        return conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def forked(tmp_path):
    """Two devices, one folder, both building on generation 1.

    A is the desktop and keeps its link; B installs A's profile into its own
    app-data, links, and pushes. Then BOTH add work and BOTH push from
    parent 1 -- which is a fork, by the only definition #124 allows: two
    manifests naming the same parent.
    """
    folder = tmp_path / "cloud"
    folder.mkdir()

    a_master = MasterDatabase(data_dir=tmp_path / "A", error_logger=None)
    b_master = MasterDatabase(data_dir=tmp_path / "B", error_logger=None)

    alice = _seed(a_master, "forkuser", entries=4)
    sync_a = ProfileFolderSync(a_master, timeout_s=10.0)
    sync_a.link(alice.id, folder, "generic")
    sync_a.push(alice.id)                      # generation 1, the ancestor

    # B takes the profile out of the folder, exactly as a second device does
    # -- which now includes recording that its copy descends from generation
    # 1 (#149). This used to install a hand-built export instead, which the
    # lineage model rightly reads as a copy with no shared history.
    sync_b = ProfileFolderSync(b_master, timeout_s=10.0)
    sync_id = sync_a.state.get_link(alice.id).sync_id
    installed = sync_b.install_from_folder(folder, sync_id, "generic")["installed"]
    b_id = installed["user_id"]
    sync_b.link(b_id, folder, "generic")

    # Both work independently from generation 1.
    _add_entries(a_master, alice.id, alice.username, 20, subject="Desktop Only")
    _add_entries(b_master, b_id, installed["username"], 3, subject="Laptop Only")

    yield {
        "folder": folder, "a": (a_master, sync_a, alice.id),
        "b": (b_master, sync_b, b_id), "tmp": tmp_path,
    }
    a_master.close()
    b_master.close()


def _make_fork(forked):
    """Both devices push while neither has seen the other's file.

    This is the only way a fork actually happens, and it cannot be faked by
    editing local state: ``perform_push`` reads the folder and chains onto
    whatever head is really there, so a device that can see the other's
    generation will build on it and produce a linear history rather than a
    fork. My first attempt did exactly that and detected nothing.

    So each device pushes into its own view of the folder -- both holding
    only generation 1 -- and the two results are then merged, which is what
    a cloud client does when two machines worked offline and synced later.
    Both write generation 2 with parent 1; the device name is in the
    filename, so they do not collide, and that non-collision is the property
    the whole design rests on.
    """
    import shutil

    folder = forked["folder"]
    tmp = forked["tmp"]
    _a_master, sync_a, a_id = forked["a"]
    _b_master, sync_b, b_id = forked["b"]

    view_a, view_b = tmp / "viewA", tmp / "viewB"
    shutil.copytree(folder, view_a)
    shutil.copytree(folder, view_b)

    sync_a.link(a_id, view_a, "generic")
    gen_a = sync_a.push(a_id).generation
    sync_b.link(b_id, view_b, "generic")
    pushed_b = sync_b.push(b_id)
    gen_b, blob_b = pushed_b.generation, pushed_b.blob_name

    # The cloud client catches up and both files land in the shared folder.
    for view in (view_a, view_b):
        for src in (view / "WIMI").rglob("*"):
            if src.is_file():
                dest = folder / src.relative_to(view)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.copy2(src, dest)

    sync_a.link(a_id, folder, "generic")
    sync_b.link(b_id, folder, "generic")
    return gen_a, gen_b, blob_b


@pytest.mark.unit
def test_two_devices_from_one_parent_make_a_detectable_fork(forked):
    gen_a, gen_b, _blob_b = _make_fork(forked)
    # Both claim generation 2 -- and that is fine, because the device name is
    # in the filename. Two devices never write the same path, which is what
    # makes a fork visible instead of a silent overwrite.
    assert gen_a == gen_b == 2
    segment = forked["folder"] / "WIMI"
    blobs = sorted(p.name for p in segment.rglob("*.wimi"))
    assert len(blobs) == 3, f"expected gen 1 plus two gen 2s, got {blobs}"

    _a_master, sync_a, a_id = forked["a"]
    status = sync_a.status(a_id)
    assert status.forks, "two manifests naming parent 1 is a fork and was not seen"
    assert status.forks[0]["parent_generation"] == 1


@pytest.mark.unit
def test_the_report_names_what_each_side_uniquely_has(forked):
    """The four figures, from a fork that actually happened."""
    _make_fork(forked)
    _a_master, sync_a, a_id = forked["a"]

    report = sync_a.fork_report(a_id)
    assert report is not None and report.compared is True
    assert report.parent_generation == 1

    by_entries = {s.entries: s for s in report.sides}
    big, small = max(by_entries), min(by_entries)
    assert by_entries[big].subjects_only_here == ["Desktop Only (Topic)"]
    assert by_entries[small].subjects_only_here == ["Laptop Only (Topic)"]
    # 4 seeded + 20 vs 4 seeded + 3.
    assert (big, small) == (24, 7)


@pytest.mark.unit
def test_no_fork_reports_none_rather_than_an_empty_report(forked):
    """The ordinary case, and it must be distinguishable from a failure."""
    _a_master, sync_a, a_id = forked["a"]
    assert sync_a.fork_report(a_id) is None


@pytest.mark.unit
def test_keep_remote_end_to_end_adopts_the_other_side(forked):
    """Stage the chosen generation out of the folder, then replace behind an export."""
    _gen_a, _gen_b, blob_b = _make_fork(forked)
    a_master, sync_a, a_id = forked["a"]
    link = sync_a.state.get_link(a_id)

    staged = sync_a.stage_other_side(link, blob_b)
    assert Path(staged).is_file()

    result = resolve_fork(
        a_master, user_id=a_id, choice=KEEP_REMOTE, incoming_archive=staged,
        safety_dir=forked["tmp"] / "safety", active_user_id=None)

    assert result.replaced_local is True
    assert _entries(a_master, a_id) == 7, "B's side did not take effect"
    assert result.safety_export.entries == 24, (
        "the export must hold what A had before the replace, or there is no undo")


@pytest.mark.unit
def test_keep_both_end_to_end_leaves_two_profiles_and_one_link(forked):
    """The trap: two profiles, one uuid, and only one may sync."""
    _gen_a, _gen_b, blob_b = _make_fork(forked)
    a_master, sync_a, a_id = forked["a"]
    link = sync_a.state.get_link(a_id)
    staged = sync_a.stage_other_side(link, blob_b)

    result = resolve_fork(
        a_master, user_id=a_id, choice=KEEP_BOTH, incoming_archive=staged,
        safety_dir=forked["tmp"] / "safety", active_user_id=a_id)

    assert _entries(a_master, a_id) == 24, "the original must be untouched"
    assert _entries(a_master, result.installed_user_id) == 7
    assert result.installed_profile_must_not_sync is True

    # The engine does not link it, and nothing else may either.
    assert sync_a.state.get_link(result.installed_user_id) is None


@pytest.mark.unit
def test_keep_local_end_to_end_keeps_the_other_side_on_disk(forked):
    _gen_a, _gen_b, blob_b = _make_fork(forked)
    a_master, sync_a, a_id = forked["a"]
    link = sync_a.state.get_link(a_id)
    staged = sync_a.stage_other_side(link, blob_b)

    result = resolve_fork(
        a_master, user_id=a_id, choice=KEEP_LOCAL, incoming_archive=staged,
        safety_dir=forked["tmp"] / "safety", active_user_id=a_id)

    assert _entries(a_master, a_id) == 24
    assert Path(result.set_aside_path).is_file(), (
        "the rejected side was deleted; a student must be able to change their mind")


@pytest.mark.unit
def test_staging_a_generation_that_is_not_there_says_so(forked):
    _make_fork(forked)
    _a_master, sync_a, a_id = forked["a"]
    link = sync_a.state.get_link(a_id)

    from app.foldersync.transport import TransportError

    with pytest.raises(TransportError, match="not in this folder"):
        sync_a.stage_other_side(link, "profile-nobody-00000000-gen-0099.wimi")


# ==================== the collision this test found ====================

@pytest.mark.unit
def test_two_machines_with_the_same_hostname_do_not_write_the_same_path():
    """The load-bearing claim, held to directly.

    #123's design rests on "two devices never write the same path", and the
    file name carried only the device NAME -- which is the hostname, and
    hostnames are not unique. Two machines from one corporate image, two VMs
    from one template, a cloned laptop, or two `DESKTOP-PC`s sharing a Box
    account all produce the same slug and then the same filename, and one
    device's generation silently replaces another's.

    Found by the fork test above: two app-data directories on one machine
    are two devices by every measure the code uses, and they wrote one file.
    The device id is a UUID, so eight of its hex characters now ride in the
    name beside the readable part.
    """
    from app.foldersync import naming

    same_name = "DESKTOP-PC"
    a = naming.blob_name(same_name, 2, "aaaaaaaa-1111-2222-3333-444444444444")
    b = naming.blob_name(same_name, 2, "bbbbbbbb-5555-6666-7777-888888888888")
    assert a != b, "two machines sharing a hostname collide again"

    ma = naming.manifest_name(same_name, 2, "aaaaaaaa-1111-2222-3333-444444444444")
    mb = naming.manifest_name(same_name, 2, "bbbbbbbb-5555-6666-7777-888888888888")
    assert ma != mb

    # The readable half survives -- a folder a student can make sense of is
    # worth the eight characters.
    assert same_name in a and "gen-0002" in a


@pytest.mark.unit
def test_a_name_written_before_the_device_tag_still_parses():
    """A folder must not go unreadable because the scheme gained a field."""
    from app.foldersync import naming

    legacy = naming.parse_blob_name("profile-DESKTOP-PC-gen-0042.wimi")
    assert legacy is not None
    assert legacy.generation == 42 and legacy.device == "DESKTOP-PC"
    assert legacy.device_tag == "", (
        "an untagged name must report no tag rather than inventing one -- it "
        "genuinely does not say which installation wrote it")

    tagged = naming.parse_blob_name("profile-DESKTOP-PC-d1a6be98-gen-0042.wimi")
    assert tagged.device == "DESKTOP-PC" and tagged.device_tag == "d1a6be98"
