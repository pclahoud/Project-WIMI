"""
The folder-sync bridge surface (#123).

Constructs ``DatabaseBridge`` directly and calls slots as plain methods, per
the bridge-test convention -- no ``QApplication``. The job slots are driven
the way the page will drive them: start, then poll until the state changes.

What these are really guarding is the two rules the surface encodes:

1.  **Every folder touch goes through a job.** A slot that read the folder
    inline would freeze the window for up to the hydration timeout on every
    status refresh, and on Box eviction is scheduled rather than exceptional,
    so that is the common case and not the rare one.
2.  **No boolean is stored for "sync is on".** The owner settled on
    2026-09-21 that the checkbox reflects the link. There is a test asserting
    no such slot exists, because the tempting thing to add later is exactly
    the thing that was decided against -- and the column it would have used
    travels inside a ``.wimi``.
"""
from __future__ import annotations

import json
import time

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


def _seed(master_db: MasterDatabase, user) -> UserDatabase:
    db_path = master_db.ensure_user_database(user.id)
    db = UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
    with db.transaction():
        cur = db.execute(
            "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
            (user.id, "Bridge Exam"),
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
                (session_id, i, f"a{i}", f"c{i}"),
            )
    return db


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "CloudFolder"
    f.mkdir()
    return f


@pytest.fixture
def bridge(tmp_path):
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    user = master.create_user(username="sam", display_name="Sam")
    user_db = _seed(master, user)
    b = DatabaseBridge(master_db=master, user_db=user_db)
    yield b
    b.teardownFolderSync()
    user_db.close()
    master.close()


def _ok(raw: str):
    payload = json.loads(raw)
    assert payload["success"] is True, payload.get("error")
    return payload["data"]


def _err(raw: str) -> str:
    payload = json.loads(raw)
    assert payload["success"] is False, payload
    return payload["error"]


def _run(bridge, timeout_s: float = 20.0, **params):
    """Start a job and poll it the way the page will."""
    job_id = _ok(bridge.startFolderSyncJob(json.dumps(params)))["job_id"]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        report = _ok(bridge.pollFolderSyncJob(job_id))
        if report["state"] != "running":
            return report
        time.sleep(0.01)
    raise AssertionError(f"{params.get('kind')} job never finished")


# ==================== the checkbox ====================

@pytest.mark.unit
def test_an_unlinked_profile_reports_linked_false(bridge):
    """This is the checkbox's unchecked state, and it is not an error."""
    assert _ok(bridge.getFolderSyncLink()) == {"linked": False}


@pytest.mark.unit
def test_linking_then_reading_back_is_the_checkbox_becoming_checked(bridge, folder):
    report = _run(bridge, kind="link", folder=str(folder), provider_id="box")
    assert report["state"] == "done"
    assert report["result"]["linked"] is True

    link = _ok(bridge.getFolderSyncLink())
    assert link["linked"] is True
    assert link["folder"] == str(folder)
    assert link["provider_id"] == "box"
    # The panel's most useful sentence names the client's own setting.
    assert link["pin_hint"] == "Always keep on this device"


@pytest.mark.unit
def test_unlinking_leaves_the_folder_alone(bridge, folder):
    """Unticking a checkbox must never be destructive."""
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")
    before = sorted(p.name for p in (folder / "WIMI").rglob("*"))

    assert _ok(bridge.unlinkFolderSync()) == {"linked": False}
    assert _ok(bridge.getFolderSyncLink()) == {"linked": False}
    assert sorted(p.name for p in (folder / "WIMI").rglob("*")) == before


@pytest.mark.unit
def test_there_is_no_slot_that_stores_a_sync_enabled_boolean(bridge):
    """
    Settled 2026-09-21: the link IS the state.

    ``user_preferences.cloud_sync_enabled`` is user-level, so it travels
    inside a ``.wimi`` -- a profile exported with sync on would arrive on the
    next machine claiming to sync with no folder linked there. Storing the
    flag anywhere would be a second answer to a question ``state.json``
    already answers, free to disagree with it.
    """
    for name in dir(bridge):
        assert "cloudsync" not in name.lower().replace("_", ""), (
            f"{name} looks like a stored cloud-sync flag; the link is the state"
        )


# ==================== jobs ====================

@pytest.mark.unit
def test_status_on_an_unlinked_profile_is_a_normal_answer(bridge):
    report = _run(bridge, kind="status")
    assert report["state"] == "done"
    assert report["result"]["linked"] is False


@pytest.mark.unit
def test_push_then_status_reports_the_generation_it_published(bridge, folder):
    _run(bridge, kind="link", folder=str(folder), provider_id="box")

    pushed = _run(bridge, kind="push")
    assert pushed["result"]["generation"] == 1

    status = _run(bridge, kind="status")["result"]
    assert status["head_generation"] == 1
    assert status["last_pushed_generation"] == 1
    assert status["problems"] == []


@pytest.mark.unit
def test_the_status_payload_never_claims_a_state_it_cannot_observe(bridge, folder):
    """
    #123's UI-honesty acceptance criterion, enforced at the wire.

    You cannot force a sync or know when one finished, so "nothing new" and
    "the other device has not uploaded yet" are indistinguishable from the
    filesystem. Every field is an observation with a timestamp.
    """
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")
    status = _run(bridge, kind="status")["result"]

    for forbidden in ("synced", "up_to_date", "in_sync", "ok", "healthy"):
        assert forbidden not in status, (
            f"status carries {forbidden!r}, which implies knowledge the "
            f"filesystem cannot give"
        )
    assert status["last_seen_at"] is not None


@pytest.mark.unit
def test_fetch_stages_an_archive_and_reports_the_schema_verdict(bridge, folder):
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")

    fetched = _run(bridge, kind="fetch")["result"]
    assert fetched["generation"] == 1
    assert fetched["blocked"] is False
    assert fetched["schema_verdict"]
    # Nothing was installed: that choice is the caller's, and #124's.
    assert fetched["archive_path"].endswith(".wimi")


@pytest.mark.unit
def test_discover_reports_a_profile_this_machine_holds(bridge, folder):
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")

    found = _run(bridge, kind="discover", folder=str(folder), provider_id="box")["result"]
    assert len(found) == 1
    assert [p["username"] for p in found[0]["local_profiles"]] == ["sam"]


@pytest.mark.unit
def test_discover_on_an_empty_folder_is_empty_not_an_error(bridge, tmp_path):
    empty = tmp_path / "Nothing"
    empty.mkdir()
    assert _run(bridge, kind="discover", folder=str(empty))["result"] == []


# ==================== refusals ====================

@pytest.mark.unit
def test_an_unknown_job_kind_is_named_rather_than_ignored(bridge):
    """#138's accept-and-silently-drop is a recent enough memory."""
    error = _err(bridge.startFolderSyncJob(json.dumps({"kind": "sync-everything"})))
    assert "sync-everything" in error and "status" in error


@pytest.mark.unit
def test_malformed_params_are_refused(bridge):
    assert "Invalid sync job params" in _err(bridge.startFolderSyncJob("{not json"))


@pytest.mark.unit
def test_link_without_a_folder_is_refused(bridge):
    assert "needs a folder" in _err(bridge.startFolderSyncJob(json.dumps({"kind": "link"})))


@pytest.mark.unit
def test_pushing_an_unlinked_profile_says_so(bridge):
    assert "not linked" in _err(bridge.startFolderSyncJob(json.dumps({"kind": "push"})))


@pytest.mark.unit
def test_polling_an_unknown_job_reports_failure_without_raising(bridge):
    report = _ok(bridge.pollFolderSyncJob("nope"))
    assert report["state"] == "failed" and "no such sync job" in report["error"]


@pytest.mark.unit
def test_slots_degrade_when_no_profile_is_open(tmp_path):
    """The profile picker runs before any user database is attached."""
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    b = DatabaseBridge(master_db=master, user_db=None)
    try:
        assert "No user database" in _err(b.getFolderSyncLink())
        assert "No user database" in _err(
            b.startFolderSyncJob(json.dumps({"kind": "status"})))
        # Providers are static data and must answer regardless.
        assert _ok(b.getFolderSyncProviders())
    finally:
        b.teardownFolderSync()
        master.close()


# ==================== providers ====================

@pytest.mark.unit
def test_providers_carry_the_pin_setting_each_client_actually_calls_it(bridge):
    providers = {p["id"]: p for p in _ok(bridge.getFolderSyncProviders())}
    assert providers["box"]["pin_setting_label"] == "Always keep on this device"
    assert providers["google_drive"]["pin_setting_label"] == "Available offline"
    assert providers["icloud"]["pin_setting_label"] == 'Turn off "Optimize Mac Storage"'


@pytest.mark.unit
def test_box_is_reported_as_streaming_and_scheduled_eviction(bridge):
    """
    Both flags drive copy the student needs to read.

    Box streams by default *and* evicts after 30 days without modification --
    and generation files are never modified, so they start that clock on
    arrival. An immutable-file design is the worst case for Box's cache
    policy, which is why pinning is worth nagging about.
    """
    box = {p["id"]: p for p in _ok(bridge.getFolderSyncProviders())}["box"]
    assert box["streaming_by_default"] is True
    assert box["scheduled_eviction"] is True
    assert box["caveats"]


# ==================== fork slots (#124) ====================

def _fork_scene(bridge, folder, tmp_path):
    """Make a real fork in the bridge's own folder, the only way it happens.

    Both devices must push while neither has seen the other's file, so each
    pushes into its own copy of the folder and the two are merged. A device
    that can see the other's generation chains onto it and produces a linear
    history instead.
    """
    import shutil

    from app.foldersync import ProfileFolderSync
    from app.profile_archive import build_profile_archive, install_profile_as_new
    from database.master_db import MasterDatabase

    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")                      # generation 1, the ancestor

    # A second machine takes the profile out of the folder.
    other_root = tmp_path / "otherdevice"
    other_master = MasterDatabase(data_dir=other_root, error_logger=None)
    archive = tmp_path / "seed.wimi"
    build_profile_archive(bridge.master_db, bridge.user_db.user_id, archive,
                          include_media=False)
    installed = install_profile_as_new(other_master, archive)
    other_sync = ProfileFolderSync(other_master, timeout_s=10.0)

    view = tmp_path / "otherview"
    shutil.copytree(folder, view)
    other_sync.link(installed["user_id"], view, "box")
    pushed = other_sync.push(installed["user_id"])

    for src in (view / "WIMI").rglob("*"):
        if src.is_file():
            dest = folder / src.relative_to(view)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(src, dest)

    # And this device publishes its own generation 2 from the same parent.
    link = bridge._folder_sync().sync.state.get_link(bridge.user_db.user_id)
    link.last_seen_generation = 1
    link.last_pushed_generation = 1
    bridge._folder_sync().sync.state.put_link(link)
    other_master.close()
    return pushed.blob_name


@pytest.mark.unit
def test_no_fork_reports_null_not_an_empty_report(bridge, folder):
    """The ordinary case, and it must be distinguishable from a failed compare."""
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")
    report = _run(bridge, kind="fork_report")
    assert report["state"] == "done"
    assert report["result"] is None


@pytest.mark.unit
def test_resolve_without_a_blob_name_is_refused_and_says_why(bridge, folder):
    """A generation number cannot name a side; the error has to explain that."""
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    error = _err(bridge.startFolderSyncJob(json.dumps(
        {"kind": "resolve", "choice": "keep_local"})))
    assert "blob_name" in error
    assert "share a generation" in error


@pytest.mark.unit
def test_the_page_cannot_choose_where_the_safety_export_goes(bridge, folder):
    """It must be durable and outside the sync folder; a page could supply neither.

    Writing the backup into the folder whose conflict is being resolved is
    how the backup becomes part of the conflict.
    """
    safety = bridge._safety_dir()
    assert safety.is_dir()
    assert "foldersync" in str(safety) and "safety" in str(safety)
    assert str(folder) not in str(safety)


@pytest.mark.unit
def test_an_unknown_resolve_choice_is_refused_before_anything_is_staged(
    bridge, folder,
):
    """And the error is about the choice, not about whatever happened next.

    Validated in phase 3 it was still caught -- but only after a download,
    and the message was then "not in this folder": true, unhelpful, and
    about the wrong problem.
    """
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")
    error = _err(bridge.startFolderSyncJob(json.dumps(
        {"kind": "resolve", "choice": "merge",
         "blob_name": "profile-x-00000000-gen-0001.wimi"})))
    assert "unknown choice" in error and "merge" in error


def _entry_count(user_db) -> int:
    return int(user_db.fetchone("SELECT COUNT(*) AS n FROM question_entries")["n"])


@pytest.mark.unit
def test_keep_remote_on_the_open_profile_closes_replaces_and_reopens_it(
    bridge, folder, tmp_path,
):
    """The owner's decision on #148, replacing a refusal this test used to assert.

    ``replace_profile`` still refuses to swap a file under a live connection,
    and that guard is untouched: the bridge closes the profile first, so the
    guard is satisfied by the fact rather than defeated by a parameter. The
    student ends with the same profile open, holding the other copy.
    """
    other_blob = _fork_scene(bridge, folder, tmp_path)
    user_id = bridge.user_db.user_id
    before = bridge.user_db
    # Make the local copy distinguishable from the one about to replace it.
    with before.transaction():
        session_id = before.fetchone("SELECT id FROM review_sessions")["id"]
        before.execute(
            "INSERT INTO question_entries "
            "(review_session_id, entry_order, user_answer, correct_answer) "
            "VALUES (?, 3, 'local-only', 'x')", (session_id,))
    assert _entry_count(before) == 3

    report = _run(bridge, kind="resolve", choice="keep_remote",
                  blob_name=other_blob)

    assert report["state"] == "done", report.get("error")
    assert report["result"]["replaced_local"] is True
    assert report["result"]["safety_export"]["entries"] == 3
    after = bridge.user_db
    assert after is not None, "the profile was left closed"
    assert after is not before, "the old connection was reused, not reopened"
    assert after.user_id == user_id
    assert _entry_count(after) == 2, "the replace did not take"
    assert before.conn is None, "the old connection was never closed"


@pytest.mark.unit
def test_a_failed_keep_remote_still_reopens_the_untouched_profile(
    bridge, folder, tmp_path, monkeypatch,
):
    """A refusal must not become an outage.

    ``replace_profile`` rolls back on failure, so the file on disk is the
    original -- and the student must be looking at it again, not at a
    profile picker because a replace went wrong.
    """
    import app.foldersync.resolution as resolution

    other_blob = _fork_scene(bridge, folder, tmp_path)
    user_id = bridge.user_db.user_id

    def _boom(*_a, **_k):
        raise RuntimeError("disk full, say")

    monkeypatch.setattr(resolution, "replace_profile", _boom)
    report = _run(bridge, kind="resolve", choice="keep_remote",
                  blob_name=other_blob)

    assert report["state"] == "failed"
    assert "disk full" in report["error"]
    assert bridge.user_db is not None and bridge.user_db.user_id == user_id
    assert _entry_count(bridge.user_db) == 2


@pytest.mark.unit
def test_keep_remote_on_a_profile_that_is_not_open_touches_no_connection(
    bridge, folder, tmp_path,
):
    """Only the profile being replaced is closed. The open one is left alone."""
    from app.foldersync.resolution import ProfileIsOpen, resolve_fork

    # The library guard is unchanged: called directly with the open profile
    # named as active, it still refuses.
    other_blob = _fork_scene(bridge, folder, tmp_path)
    sync = bridge._folder_sync().sync
    link = sync.state.get_link(bridge.user_db.user_id)
    staged = sync.stage_other_side(link, other_blob)
    with pytest.raises(ProfileIsOpen):
        resolve_fork(
            bridge.master_db, user_id=bridge.user_db.user_id,
            choice="keep_remote", incoming_archive=staged,
            safety_dir=tmp_path / "safety",
            active_user_id=bridge.user_db.user_id,
        )


@pytest.mark.unit
def test_keep_local_through_the_bridge_exports_first_and_sets_the_other_aside(
    bridge, folder, tmp_path,
):
    other_blob = _fork_scene(bridge, folder, tmp_path)
    report = _run(bridge, kind="resolve", choice="keep_local",
                  blob_name=other_blob)
    assert report["state"] == "done"
    result = report["result"]
    assert result["safety_export"]["verified"] is True
    assert result["set_aside_path"]
    assert result["replaced_local"] is False


# ==================== the startup notice (#148) ====================

def _poll_job(bridge, job_id, timeout_s: float = 20.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        report = _ok(bridge.pollFolderSyncJob(job_id))
        if report["state"] != "running":
            return report
        time.sleep(0.01)
    raise AssertionError("startup check never finished")


@pytest.mark.unit
def test_the_startup_check_looks_once_per_profile_per_launch(bridge, folder):
    """The owner's decision: the notice fires once, at startup.

    The dashboard reloads on every navigation, so "once" is kept by the
    bridge, not trusted to the page.
    """
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")

    first = _ok(bridge.startFolderSyncStartupCheck())
    assert "job_id" in first
    report = _poll_job(bridge, first["job_id"])
    assert report["state"] == "done"
    assert report["result"]["base_relation"] == "current"
    assert report["result"]["pending"] is None

    again = _ok(bridge.startFolderSyncStartupCheck())
    assert again == {"skipped": "already checked"}


@pytest.mark.unit
def test_the_startup_check_skips_an_unlinked_profile_without_a_job(bridge):
    assert _ok(bridge.startFolderSyncStartupCheck()) == {"skipped": "not linked"}


@pytest.mark.unit
def test_the_startup_check_without_a_profile_is_an_error_not_a_crash(bridge):
    bridge.user_db = None
    assert "No user database" in _err(bridge.startFolderSyncStartupCheck())


@pytest.mark.unit
def test_the_status_payload_carries_the_lineage_fields(bridge, folder):
    """The panel and the notice both read these; a missing key renders as nothing."""
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")
    result = _run(bridge, kind="status")["result"]
    for key in ("base_generation", "base_relation", "relation_detail",
                "pending", "pending_state"):
        assert key in result, key
    assert result["base_generation"] == 1
    assert _ok(bridge.getFolderSyncLink())["pending"] is None


# ==================== taking a copy from the folder (#151) ====================

@pytest.mark.unit
def test_install_runs_with_no_profile_open_and_links(bridge, folder, tmp_path):
    """The picker has no profile open; that is the second computer's normal state."""
    from database.master_db import MasterDatabase

    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")
    sync_id = _ok(bridge.getFolderSyncLink())["sync_id"]

    other_master = MasterDatabase(data_dir=tmp_path / "second_computer", error_logger=None)
    picker = DatabaseBridge(master_db=other_master, user_db=None)
    try:
        report = _run(picker, kind="install", folder=str(folder),
                      provider_id="box", sync_id=sync_id)
        assert report["state"] == "done", report.get("error")
        result = report["result"]
        assert result["linked"] is True and result["generation"] == 1
        assert result["profile_uuid"] == sync_id

        # And the same profile is not installed twice.
        error = _err(picker.startFolderSyncJob(json.dumps(
            {"kind": "install", "folder": str(folder), "provider_id": "box",
             "sync_id": sync_id})))
        assert "already on this computer" in error
    finally:
        picker.teardownFolderSync()
        other_master.close()


@pytest.mark.unit
def test_install_without_a_sync_id_is_refused_by_name(bridge, folder):
    assert "sync_id" in _err(bridge.startFolderSyncJob(json.dumps(
        {"kind": "install", "folder": str(folder)})))


@pytest.mark.unit
def test_status_carries_local_changes(bridge, folder):
    _run(bridge, kind="link", folder=str(folder), provider_id="box")
    _run(bridge, kind="push")
    changes = _run(bridge, kind="status")["result"]["local_changes"]
    assert changes["checked"] is True and changes["differs"] == []
