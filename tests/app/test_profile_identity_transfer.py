"""Two identifiers with opposite travel rules, tested across a real transfer.

#126 and #129 are the same problem twice — WIMI had no stable notion of
which *device* it is running on, and none of which *profile* it is
looking at — and the two answers must travel in opposite directions:

* the **device id** names a machine and must NOT ride along in a
  ``.wimi``;
* the **profile id** names a profile and must survive export, import,
  rename and re-install.

Swapping them would be silent, so every assertion here is about a value
crossing (or refusing to cross) a real archive boundary. Two
``MasterDatabase`` instances on separate app-data directories stand in
for two machines, which is exactly what they are: master is per-install
and is what mints the device id.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.profile_archive import (
    build_profile_archive,
    install_profile_as_new,
    read_profile_archive,
    replace_profile,
)
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


# ==================== helpers ====================

def _machine(tmp_path: Path, name: str) -> MasterDatabase:
    """A separate installation: its own app-data dir, its own device id."""
    return MasterDatabase(tmp_path / name)


def _open(master: MasterDatabase, user) -> UserDatabase:
    return UserDatabase(
        db_path=master.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
        error_logger=None,
        device_id=master.get_device_id(),
    )


def _seed_alice(master: MasterDatabase):
    """A profile with both kinds of setting deliberately non-default."""
    user = master.create_user(username="alice", display_name="Alice")
    db = _open(master, user)
    try:
        db.update_settings(
            # follows the student
            theme_name="dark",
            font_size_scale=1.25,
            default_session_duration_minutes=90,
            hotkey_timer_pause_resume="Alt+Z",
            pane_open_mode="blank",
            # #133 -- a display preference denotes no machine, so it
            # travels. Non-default here precisely so a receiving machine
            # resetting it to the default would fail.
            efficiency_show_confidence_band=True,
            # stays on this machine
            pane_zoom_pct=135,
            pane_split_app_pct=62,
            pane_last_url="https://desktop.example.com/q/1",
            ankiconnect_host="desktop-box",
            ankiconnect_port=9999,
            mcp_server_enabled=True,
            mcp_server_port=8123,
        )
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Sample Exam"),
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
        # A question bank with pane state, so the per-source half of the
        # split is exercised too: name and url are shared facts, the MRU
        # stamp and the desktop-site flag belong to this machine.
        source = db.create_question_source(
            source_name="UWorld", url="https://uworld.com"
        )
        db.touch_pane_source(source.id)
        db.set_pane_desktop_site(source.id, False)
        profile_uuid = db.get_profile_uuid()
    finally:
        db.close()
    master.record_profile_uuid(user.id, profile_uuid)
    return user, profile_uuid


@pytest.fixture
def device_a(tmp_path):
    return _machine(tmp_path, "device_a")


@pytest.fixture
def device_b(tmp_path):
    return _machine(tmp_path, "device_b")


# ==================== the device id stays home ====================

def test_two_installs_mint_different_device_ids(device_a, device_b):
    """Two app-data directories are two machines."""
    assert device_a.get_device_id() != device_b.get_device_id()
    assert len(device_a.get_device_id()) == 36


def test_device_id_survives_a_restart(tmp_path):
    """It is a row in users.db, so closing and reopening finds the same one."""
    first = _machine(tmp_path, "desk")
    minted = first.get_device_id()
    first.close()

    second = _machine(tmp_path, "desk")
    try:
        assert second.get_device_id() == minted
    finally:
        second.close()


def test_the_authoritative_device_id_is_absent_from_the_archive(
    device_a, tmp_path
):
    """The half most likely to regress, so it is asserted directly.

    The device id is authoritative in master's ``app_settings``, and
    ``users.db`` is not packed at all — so nothing an installing machine
    could mistake for its own identity travels. What *does* travel is the
    id used as a **key** on this machine's ``device_settings`` row, which
    is the design: a foreign key is ignored, not adopted. This test pins
    both halves, so "strip the rows" and "ship the authority" are each
    caught.
    """
    user, _ = _seed_alice(device_a)
    device_id = device_a.get_device_id()

    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user.id, archive)

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        # The authority is a row in users.db, and users.db is not packed.
        assert not any(n.endswith("users.db") for n in names)
        manifest = json.loads(zf.read("manifest.json"))
        assert device_id not in json.dumps(manifest)
        zf.extract("user.db", tmp_path / "unpacked")

    # Inside the packed profile the id appears ONLY as a row key.
    conn = sqlite3.connect(str(tmp_path / "unpacked" / "user.db"))
    try:
        conn.row_factory = sqlite3.Row
        tables = [
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        carrying = []
        for table in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            for col in cols:
                hit = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" = ?',
                    (device_id,),
                ).fetchone()[0]
                if hit:
                    carrying.append(f"{table}.{col}")
    finally:
        conn.close()

    assert sorted(carrying) == [
        "device_settings.device_id",
        "device_source_settings.device_id",
    ]


def test_the_handover_row_never_reaches_an_archive(device_a, tmp_path):
    """m021's handover row is claimed at open, before anything can export it.

    The row holds the migrating machine's values under a reserved id, for
    that machine to adopt. If it survived into an archive, the RECEIVING
    machine would claim it and inherit the sender's AnkiConnect host —
    precisely the bug #126 exists to remove. ``UserDatabase.__init__``
    claims it immediately after the migration runs, so the window has no
    export path through it.
    """
    user, _ = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user.id, archive)

    with zipfile.ZipFile(archive) as zf:
        zf.extract("user.db", tmp_path / "unpacked2")
    conn = sqlite3.connect(str(tmp_path / "unpacked2" / "user.db"))
    try:
        for table in ("device_settings", "device_source_settings"):
            left = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE device_id = '__pre_m021__'"
            ).fetchone()[0]
            assert left == 0, table
    finally:
        conn.close()


def test_installed_profile_takes_device_defaults_on_a_new_machine(
    device_a, device_b, tmp_path
):
    """The acceptance criterion, end to end.

    Theme, font scale and session defaults survive the move. Pane
    geometry, pane state and the AnkiConnect host/port do not — the
    second machine gets its own defaults, not the first machine's
    values.
    """
    user_a, _ = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)

    result = install_profile_as_new(device_b, archive)
    user_b = device_b.get_user(result["user_id"])
    db_b = _open(device_b, user_b)
    try:
        prefs = db_b.get_preferences()
        assert prefs.theme_name == "dark"
        assert prefs.font_size_scale == 1.25
        assert prefs.default_session_duration_minutes == 90
        assert prefs.hotkey_timer_pause_resume == "Alt+Z"
        assert prefs.pane_open_mode == "blank"
        assert prefs.efficiency_show_confidence_band is True

        device = db_b.get_device_settings()
        assert device.device_id == device_b.get_device_id()
        assert device.pane_zoom_pct == 100
        assert device.pane_split_app_pct is None
        assert device.pane_last_url is None
        assert device.ankiconnect_host == "localhost"
        assert device.ankiconnect_port == 8765
        assert device.mcp_server_enabled is False
        assert device.mcp_server_port == 8000

        # The per-source half moves the same way: the bank itself is a
        # shared fact and arrives, but this machine has never opened it
        # and has its own view of whether it needs a desktop user-agent.
        (bank,) = db_b.get_pane_sources()
        assert bank["source_name"] == "UWorld"
        assert bank["url"] == "https://uworld.com"
        assert bank["last_opened_at"] is None
        assert bank["desktop_site"] is True
    finally:
        db_b.close()


def test_the_efficiency_band_preference_travels(device_a, device_b, tmp_path):
    """#133's third acceptance criterion, across a real archive.

    Whether the study-efficiency score is drawn as one number or as a
    band is a stated display preference: it means the same thing on any
    machine, so it belongs beside ``theme_name`` and ``pane_open_mode``
    rather than beside ``ankiconnect_host``. Asserted through the merged
    view the UI actually reads, not just the dataclass, because
    ``get_all_settings`` is where a mis-filed field would surface.
    """
    user_a, _ = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)

    result = install_profile_as_new(device_b, archive)
    user_b = device_b.get_user(result["user_id"])
    db_b = _open(device_b, user_b)
    try:
        assert db_b.get_all_settings()["efficiency_show_confidence_band"] is True
        # And it is still a preference on the other machine, not a
        # frozen import: the receiving student can turn it off.
        db_b.update_settings(efficiency_show_confidence_band=False)
        assert db_b.get_all_settings()["efficiency_show_confidence_band"] is False
    finally:
        db_b.close()


def test_the_other_machines_row_travels_but_is_ignored(
    device_a, device_b, tmp_path
):
    """Rows for other devices ride along, which is what makes it self-healing.

    Nothing has to strip them on export or on import: they are keyed by a
    device id this machine does not have, so they are invisible here and
    still intact if the profile goes home.
    """
    user_a, _ = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)

    result = install_profile_as_new(device_b, archive)
    user_b = device_b.get_user(result["user_id"])
    db_b = _open(device_b, user_b)
    try:
        db_b.get_device_settings()  # the app's first read mints this row
        rows = db_b.fetchall(
            "SELECT device_id, pane_zoom_pct FROM device_settings "
            "ORDER BY device_id"
        )
        by_device = {r["device_id"]: r["pane_zoom_pct"] for r in rows}
        assert by_device[device_a.get_device_id()] == 135
        assert by_device[device_b.get_device_id()] == 100
    finally:
        db_b.close()


# ==================== the profile id travels ====================

def test_profile_uuid_survives_export_install_and_the_rename(
    device_a, device_b, tmp_path
):
    """Install renames on collision by design; identity must not follow the name."""
    user_a, uuid_a = _seed_alice(device_a)
    # Device B already has an 'alice', so the import must rename.
    device_b.create_user(username="alice", display_name="Someone Else")

    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)
    result = install_profile_as_new(device_b, archive)

    assert result["username"] == "alice_2"
    assert result["profile_uuid"] == uuid_a

    user_b = device_b.get_user(result["user_id"])
    db_b = _open(device_b, user_b)
    try:
        assert db_b.get_profile_uuid() == uuid_a
    finally:
        db_b.close()

    # ... and exporting again from the renamed copy carries the same id.
    round_trip = tmp_path / "alice_again.wimi"
    built = build_profile_archive(device_b, user_b.id, round_trip)
    assert built["manifest"]["profile"]["uuid"] == uuid_a
    assert read_profile_archive(round_trip)["manifest"]["profile"]["uuid"] == uuid_a


def test_two_installs_of_one_archive_are_recognisably_the_same_profile(
    device_a, device_b, tmp_path
):
    """A duplicate is reported, not refused.

    ``install_profile_as_new`` forks on a name collision by design, so a
    second install is a legitimate outcome. The import path detects the
    shared identity, warns, and hands the caller both rows — choosing
    between them is fork resolution (#124) and is not done here.
    """
    user_a, uuid_a = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)

    first = install_profile_as_new(device_b, archive)
    assert first["already_installed_as"] == []

    second = install_profile_as_new(device_b, archive)
    assert second["profile_uuid"] == uuid_a
    assert [u["user_id"] for u in second["already_installed_as"]] == [
        first["user_id"]
    ]
    assert any("already installed" in w for w in second["warnings"])

    # Both copies exist, independently, and both answer to the same id.
    found = device_b.find_users_by_profile_uuid(uuid_a)
    assert sorted(u.id for u in found) == sorted(
        [first["user_id"], second["user_id"]]
    )


def test_master_mirror_is_rederived_from_the_user_database(
    device_a, device_b, tmp_path
):
    """Master holds an index, never the authority.

    A mirror that has drifted — or was never written — is corrected by
    opening the profile, because the user database is what travels with
    the data and so cannot be out of step with it.
    """
    user_a, uuid_a = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)
    result = install_profile_as_new(device_b, archive)

    with device_b.transaction():
        device_b.execute(
            "UPDATE users SET profile_uuid = 'stale-value' WHERE id = ?",
            (result["user_id"],),
        )
    assert device_b.get_user(result["user_id"]).profile_uuid == "stale-value"

    user_b = device_b.get_user(result["user_id"])
    db_b = _open(device_b, user_b)
    try:
        device_b.record_profile_uuid(user_b.id, db_b.get_profile_uuid())
    finally:
        db_b.close()

    assert device_b.get_user(result["user_id"]).profile_uuid == uuid_a


def test_replace_profile_adopts_the_archives_identity(
    device_a, device_b, tmp_path
):
    """"Replace" means this slot now holds that profile's data.

    An identifier naming the discarded data would name nothing, so
    identity follows the bytes even though username and
    database_filename stay structural.
    """
    user_a, uuid_a = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)

    target = device_b.create_user(username="bob", display_name="Bob")
    db_b = _open(device_b, target)
    try:
        bob_uuid = db_b.get_profile_uuid()
    finally:
        db_b.close()
    device_b.record_profile_uuid(target.id, bob_uuid)
    assert bob_uuid != uuid_a

    result = replace_profile(
        device_b, archive, target_user_id=target.id, confirm_replace=True
    )
    assert result["profile_uuid"] == uuid_a
    assert device_b.get_user(target.id).profile_uuid == uuid_a
    # Structural facts are untouched.
    assert device_b.get_user(target.id).username == "bob"


def test_manifest_uuid_is_informational_and_user_db_wins(
    device_a, device_b, tmp_path
):
    """The manifest is a preview; ``user.db`` is the authority.

    A tampered or stale manifest must be ignored rather than obeyed —
    otherwise the identifier could be changed from outside the thing it
    identifies.
    """
    user_a, uuid_a = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)

    # Rewrite the manifest with a bogus uuid, leaving user.db alone.
    tampered = tmp_path / "tampered.wimi"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(
        tampered, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "manifest.json":
                manifest = json.loads(data)
                manifest["profile"]["uuid"] = "00000000-dead-beef-0000-000000000000"
                data = json.dumps(manifest, indent=2).encode()
            dst.writestr(item.filename, data)

    result = install_profile_as_new(device_b, tampered)
    assert result["profile_uuid"] == uuid_a


def test_a_pre_m021_archive_is_given_an_identity_on_install(
    device_a, device_b, tmp_path
):
    """No synthetic id is invented at the manifest layer.

    An archive built before m021 has no identity to recognise. It gets
    one where identities belong — inside the installed copy, minted by
    the migration the verify-open runs — and the copy on the exporting
    machine keeps its own, different one. Those are genuinely two
    profiles now: nothing ever related them.
    """
    user_a, _ = _seed_alice(device_a)
    archive = tmp_path / "alice.wimi"
    build_profile_archive(device_a, user_a.id, archive)

    stripped = tmp_path / "legacy.wimi"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(
        stripped, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "manifest.json":
                manifest = json.loads(data)
                manifest.pop("profile", None)
                data = json.dumps(manifest, indent=2).encode()
            dst.writestr(item.filename, data)

    result = install_profile_as_new(device_b, stripped)
    assert result["already_installed_as"] == []
    assert result["profile_uuid"]
    assert device_b.get_user(result["user_id"]).profile_uuid == \
        result["profile_uuid"]
