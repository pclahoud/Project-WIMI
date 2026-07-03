"""
Tests for the profile transfer bridge mixin (bridge_domains/profile_transfer.py).

Covers all five ProfileTransferBridgeMixin slots: exportProfile happy paths
(with and without media), readProfileArchive preview shape (collision +
schema verdict + media reference fields), executeProfileImport create /
replace / error mapping, master_db=None guards, and the dialog slots'
param handling with QFileDialog monkeypatched (the native dialogs
themselves are never opened — headless-safe).
"""
import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Generator

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase
from database.migrations.user import MIGRATIONS as USER_MIGRATIONS
from app.bridge import DatabaseBridge
from app.profile_archive import (
    VERDICT_NEWER_APP_REQUIRED,
    VERDICT_OK,
    build_profile_archive,
)

LOCAL_MAX = max(m.version for m in USER_MIGRATIONS)

FLAT_IMG = "aaaaaaaa-1111-2222-3333-444444444444.png"
FLAT_THUMB = "aaaaaaaa-1111-2222-3333-444444444444_thumb.jpg"
LEGACY_IMG = "bbbbbbbb-5555-6666-7777-888888888888.png"


# ==================== helpers ====================

def _seed_user_db(master_db: MasterDatabase, user, n_entries: int = 3,
                  media_rows: int = 0) -> None:
    """Open the user's DB (runs migrations) and seed exam/session/entries."""
    db_path = master_db.ensure_user_database(user.id)
    db = UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
    try:
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
                (user.id, exam_id, 10, n_entries),
            )
            session_id = cur.lastrowid
            entry_ids = []
            for i in range(1, n_entries + 1):
                cur = db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, i, f"answer_{i}", f"correct_{i}"),
                )
                entry_ids.append(cur.lastrowid)
            for i in range(media_rows):
                db.execute(
                    "INSERT INTO entry_media (question_entry_id, file_uuid) "
                    "VALUES (?, ?)",
                    (entry_ids[0], f"cccccccc-0000-0000-0000-{i:012d}"),
                )
    finally:
        db.close()


def _make_media(master_db: MasterDatabase, user) -> Path:
    """Create a media dir with flat files and one legacy entry_N/ subdir file."""
    media_dir = master_db.data_dir / "media" / f"user_{user.id}_{user.username}"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / FLAT_IMG).write_bytes(b"flat-image-bytes")
    (media_dir / FLAT_THUMB).write_bytes(b"flat-thumb-bytes")
    legacy_dir = media_dir / "entry_5"
    legacy_dir.mkdir(exist_ok=True)
    (legacy_dir / LEGACY_IMG).write_bytes(b"legacy-image-bytes")
    return media_dir


def _extract_db(archive_path: Path, dest_dir: Path) -> Path:
    with zipfile.ZipFile(str(archive_path)) as zf:
        zf.extract("user.db", str(dest_dir))
    return dest_dir / "user.db"


def _rezip_with_db(original_archive: Path, modified_db: Path, dest: Path) -> Path:
    """Rebuild an archive replacing user.db (keeps manifest + media)."""
    with zipfile.ZipFile(str(original_archive)) as src, \
            zipfile.ZipFile(str(dest), "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            if item.filename == "user.db":
                continue
            out.writestr(item, src.read(item.filename))
        out.write(str(modified_db), "user.db")
    return dest


def _make_newer_archive(base_archive: Path, tmp_path: Path) -> Path:
    """Derive an archive whose user.db claims a from-the-future migration."""
    db = _extract_db(base_archive, tmp_path / "newer_mod")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO schema_migrations (version, name, checksum) "
        "VALUES (999, 'from_the_future', 'x')"
    )
    conn.commit()
    conn.close()
    return _rezip_with_db(base_archive, db, tmp_path / "newer.wimi")


def parse_response(json_str: str) -> dict:
    return json.loads(json_str)


def assert_success(response: str) -> dict:
    result = parse_response(response)
    assert result['success'] is True, \
        f"Expected success but got error: {result.get('error')}"
    return result.get('data')


def assert_error(response: str, expected_message: str = None) -> str:
    result = parse_response(response)
    assert result['success'] is False, "Expected error but got success"
    if expected_message:
        assert expected_message in result.get('error', ''), \
            f"Expected '{expected_message}' in error but got: {result.get('error')}"
    return result.get('error')


# ==================== fixtures ====================

@pytest.fixture
def source_master(tmp_path) -> Generator[MasterDatabase, None, None]:
    """Master DB 'A' — the export side (no bridge attached)."""
    db = MasterDatabase(data_dir=tmp_path / "data_a", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def master_db(tmp_path) -> Generator[MasterDatabase, None, None]:
    """Master DB 'B' — the bridge's master (import side)."""
    db = MasterDatabase(data_dir=tmp_path / "data_b", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(master_db: MasterDatabase) -> Generator[DatabaseBridge, None, None]:
    """Bridge with a master DB but no user DB (profile-picker state)."""
    b = DatabaseBridge(master_db=master_db, user_db=None)
    yield b
    # selectProfile may have attached a user DB inside the temp dir —
    # close it so temp-dir cleanup doesn't hit Windows file locks.
    if b.user_db is not None:
        b.user_db.close()


@pytest.fixture
def bridge_no_master() -> DatabaseBridge:
    """Bridge with no databases at all."""
    return DatabaseBridge(master_db=None, user_db=None)


@pytest.fixture
def alice(source_master):
    """Seeded source user with 3 entries and media (flat + legacy subdir)."""
    user = source_master.create_user(
        username="alice",
        display_name="Alice Example",
        email="alice@example.com",
    )
    _seed_user_db(source_master, user, n_entries=3)
    _make_media(source_master, user)
    return user


@pytest.fixture
def alice_archive(source_master, alice, tmp_path) -> Path:
    """Exported archive of alice, media included."""
    dest = tmp_path / "alice.wimi"
    build_profile_archive(source_master, alice.id, dest, include_media=True)
    return dest


@pytest.fixture
def local_user(master_db):
    """A seeded user in the BRIDGE's master (for exportProfile tests)."""
    user = master_db.create_user(
        username="localexporter",
        display_name="Local Exporter",
    )
    _seed_user_db(master_db, user, n_entries=3)
    return user


# ==================== master_db=None guard ====================

class TestNoMasterDb:
    """Every transfer slot must fail cleanly when master_db is None."""

    @pytest.mark.parametrize("slot_name,args", [
        ("openProfileExportDialog", ('{}',)),
        ("openProfileImportDialog", ()),
        ("exportProfile", ('{"user_id": 1, "dest_path": "x.wimi"}',)),
        ("readProfileArchive", ("x.wimi",)),
        ("executeProfileImport", ('{"archive_path": "x.wimi", "mode": "create"}',)),
    ])
    def test_slot_errors_without_master_db(self, bridge_no_master, slot_name, args):
        response = getattr(bridge_no_master, slot_name)(*args)
        assert_error(response, "master DB not available")


# ==================== dialog slots ====================
# The native QFileDialog statics are monkeypatched so no dialog (and no
# QApplication) is ever needed — these tests cover param handling, the
# .wimi suffix append, and cancel behavior only.

class TestExportDialog:

    def test_appends_wimi_suffix(self, bridge, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog
        captured = {}

        def fake_get_save(parent, title, default, file_filter):
            captured['title'] = title
            captured['default'] = default
            captured['filter'] = file_filter
            return ("C:/exports/my_profile", "WIMI Profile (*.wimi)")

        monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_get_save)

        data = assert_success(bridge.openProfileExportDialog(
            json.dumps({"default_filename": "my_profile.wimi"})
        ))

        assert data['file_path'] == "C:/exports/my_profile.wimi"
        assert captured['title'] == "Export WIMI Profile"
        assert captured['default'] == "my_profile.wimi"
        assert captured['filter'] == "WIMI Profile (*.wimi)"

    def test_keeps_existing_wimi_suffix(self, bridge, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName",
            lambda *a: ("C:/exports/done.wimi", "WIMI Profile (*.wimi)"),
        )

        data = assert_success(bridge.openProfileExportDialog('{}'))

        assert data['file_path'] == "C:/exports/done.wimi"

    def test_cancel_returns_no_data(self, bridge, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *a: ("", "")
        )

        result = parse_response(bridge.openProfileExportDialog('{}'))

        assert result['success'] is True
        assert result.get('data') is None

    def test_malformed_params_fail_before_dialog(self, bridge):
        # No monkeypatch: a bad payload must error out before any dialog.
        response = bridge.openProfileExportDialog("{not json")
        assert_error(response, "Invalid export dialog params")

    def test_non_object_params_fail(self, bridge):
        response = bridge.openProfileExportDialog("[1, 2]")
        assert_error(response, "Invalid export dialog params")


class TestImportDialog:

    def test_returns_selected_path(self, bridge, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog
        captured = {}

        def fake_get_open(parent, title, start_dir, file_filter):
            captured['title'] = title
            captured['filter'] = file_filter
            return ("C:/downloads/other.wimi", "WIMI Profile (*.wimi *.zip)")

        monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_get_open)

        data = assert_success(bridge.openProfileImportDialog())

        assert data['file_path'] == "C:/downloads/other.wimi"
        assert captured['title'] == "Import WIMI Profile"
        assert "*.wimi *.zip" in captured['filter']

    def test_cancel_returns_no_data(self, bridge, monkeypatch):
        from PyQt6.QtWidgets import QFileDialog
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a: ("", "")
        )

        result = parse_response(bridge.openProfileImportDialog())

        assert result['success'] is True
        assert result.get('data') is None


# ==================== exportProfile ====================

class TestExportProfile:

    def test_export_without_media(self, bridge, local_user, tmp_path):
        dest = tmp_path / "local_no_media.wimi"

        data = assert_success(bridge.exportProfile(json.dumps({
            "user_id": local_user.id,
            "include_media": False,
            "dest_path": str(dest),
        })))

        assert data['archive_path'] == str(dest)
        assert dest.exists()
        assert data['media_files'] == 0
        assert data['total_bytes'] == dest.stat().st_size
        assert data['total_bytes'] > 0
        assert data['stats'] == {"entries": 3, "sessions": 1, "exam_contexts": 1}
        with zipfile.ZipFile(str(dest)) as zf:
            names = zf.namelist()
        assert "manifest.json" in names
        assert "user.db" in names
        assert not any(n.startswith("media/") for n in names)

    def test_export_with_media(self, bridge, master_db, local_user, tmp_path):
        _make_media(master_db, local_user)
        dest = tmp_path / "local_media.wimi"

        data = assert_success(bridge.exportProfile(json.dumps({
            "user_id": local_user.id,
            "include_media": True,
            "dest_path": str(dest),
        })))

        # Two flat files + one flattened legacy entry_5/ file.
        assert data['media_files'] == 3
        with zipfile.ZipFile(str(dest)) as zf:
            names = set(zf.namelist())
        assert f"media/{FLAT_IMG}" in names
        assert f"media/{LEGACY_IMG}" in names

    def test_export_unknown_user_fails(self, bridge, tmp_path):
        response = bridge.exportProfile(json.dumps({
            "user_id": 99999,
            "dest_path": str(tmp_path / "ghost.wimi"),
        }))
        assert_error(response, "not found")

    def test_export_missing_dest_path_fails(self, bridge, local_user):
        response = bridge.exportProfile(json.dumps({"user_id": local_user.id}))
        assert_error(response, "dest_path")

    def test_export_non_numeric_user_id_fails(self, bridge, tmp_path):
        response = bridge.exportProfile(json.dumps({
            "user_id": "abc",
            "dest_path": str(tmp_path / "x.wimi"),
        }))
        assert_error(response, "user_id")

    def test_export_malformed_json_fails(self, bridge):
        response = bridge.exportProfile("{not json")
        assert_error(response, "Invalid export params")


# ==================== readProfileArchive ====================

class TestReadProfileArchive:

    def test_preview_shape(self, bridge, alice_archive):
        data = assert_success(bridge.readProfileArchive(str(alice_archive)))

        # Full manifest passed through.
        manifest = data['manifest']
        assert manifest['format'] == "wimi-profile"
        assert manifest['user']['username'] == "alice"
        assert manifest['stats'] == {
            "entries": 3, "sessions": 1, "exam_contexts": 1,
        }

        # Schema preflight.
        assert data['schema']['verdict'] == VERDICT_OK
        assert data['schema']['archive_version'] == LOCAL_MAX
        assert data['schema']['local_version'] == LOCAL_MAX
        assert data['schema']['pending_versions'] == []

        # Media inventory (alice's DB has no entry_media rows).
        assert data['media']['included'] is True
        assert data['media']['file_count'] == 3
        assert data['media']['total_bytes'] > 0
        assert data['media']['db_references_media'] is False

        # No 'alice' in the bridge's (dest) master → no collision.
        assert data['collision'] == {
            'username_exists': False,
            'suggested_username': 'alice',
        }

        # Empty dest master → no replace targets.
        assert data['replace_targets'] == []

        # Disk space figures.
        assert data['required_bytes'] > 0
        assert data['free_bytes'] > 0

    def test_collision_suggests_suffixed_username(
        self, bridge, master_db, alice_archive
    ):
        master_db.create_user(username="alice", display_name="Other Alice")

        data = assert_success(bridge.readProfileArchive(str(alice_archive)))

        assert data['collision']['username_exists'] is True
        assert data['collision']['suggested_username'] == "alice_2"

    def test_replace_targets_flag_current_profile(
        self, bridge, master_db, alice_archive
    ):
        bob = master_db.create_user(username="bob", display_name="Bob Target")
        carol = master_db.create_user(username="carol", display_name="Carol Active")
        assert_success(bridge.selectProfile(carol.id))

        data = assert_success(bridge.readProfileArchive(str(alice_archive)))

        targets = {t['user_id']: t for t in data['replace_targets']}
        assert set(targets) == {bob.id, carol.id}
        assert targets[bob.id]['is_current'] is False
        assert targets[bob.id]['username'] == "bob"
        assert targets[bob.id]['display_name'] == "Bob Target"
        assert targets[carol.id]['is_current'] is True

    def test_db_references_media_detected(
        self, bridge, source_master, tmp_path
    ):
        user = source_master.create_user(
            username="mediaref", display_name="Media Ref"
        )
        _seed_user_db(source_master, user, n_entries=1, media_rows=2)
        dest = tmp_path / "mediaref.wimi"
        # Media rows in the DB but media files NOT included in the archive —
        # the preview must still flag the dangling references.
        build_profile_archive(source_master, user.id, dest, include_media=False)

        data = assert_success(bridge.readProfileArchive(str(dest)))

        assert data['media']['included'] is False
        assert data['media']['file_count'] == 0
        assert data['media']['db_references_media'] is True

    def test_newer_schema_archive_gets_blocking_verdict(
        self, bridge, alice_archive, tmp_path
    ):
        newer = _make_newer_archive(alice_archive, tmp_path)

        data = assert_success(bridge.readProfileArchive(str(newer)))

        assert data['schema']['verdict'] == VERDICT_NEWER_APP_REQUIRED
        assert "newer version of WIMI" in data['schema']['reason']

    def test_corrupt_zip_fails(self, bridge, tmp_path):
        bad = tmp_path / "corrupt.wimi"
        bad.write_bytes(b"this is definitely not a zip file")

        response = bridge.readProfileArchive(str(bad))

        assert_error(response, "not a zip")

    def test_missing_file_fails(self, bridge, tmp_path):
        response = bridge.readProfileArchive(str(tmp_path / "nope.wimi"))
        assert_error(response, "not found")


# ==================== executeProfileImport ====================

@pytest.fixture
def replace_setup(master_db):
    """Target 'bob' (1 entry) and 'carol' in the bridge's master."""
    bob = master_db.create_user(
        username="bob", display_name="Bob Target", email="bob@example.com"
    )
    _seed_user_db(master_db, bob, n_entries=1)
    carol = master_db.create_user(username="carol", display_name="Carol Active")
    _seed_user_db(master_db, carol, n_entries=1)
    return bob, carol


class TestExecuteProfileImportCreate:

    def test_create_mode_happy_path(self, bridge, master_db, alice_archive):
        data = assert_success(bridge.executeProfileImport(json.dumps({
            "archive_path": str(alice_archive),
            "mode": "create",
        })))

        assert data['mode'] == "create"
        assert data['username'] == "alice"
        assert data['display_name'] == "Alice Example"
        assert data['media_files_restored'] == 3
        assert data['warnings'] == []
        assert data['entries'] == 3
        assert data['schema_verdict'] == VERDICT_OK

        user = master_db.get_user(data['user_id'])
        assert user is not None
        assert user.account_status == 'active'
        assert (master_db.users_dir / user.database_filename).exists()

    def test_create_mode_username_collision_warns(
        self, bridge, master_db, alice_archive
    ):
        master_db.create_user(username="alice", display_name="Other Alice")

        data = assert_success(bridge.executeProfileImport(json.dumps({
            "archive_path": str(alice_archive),
            "mode": "create",
        })))

        assert data['username'] == "alice_2"
        assert any("alice_2" in w for w in data['warnings'])


class TestExecuteProfileImportReplace:

    def test_replace_mode_happy_path(
        self, bridge, master_db, alice_archive, replace_setup
    ):
        bob, carol = replace_setup
        assert_success(bridge.selectProfile(carol.id))

        data = assert_success(bridge.executeProfileImport(json.dumps({
            "archive_path": str(alice_archive),
            "mode": "replace",
            "target_user_id": bob.id,
            "confirm_replace": True,
        })))

        assert data['mode'] == "replace"
        assert data['user_id'] == bob.id
        assert data['username'] == "bob"  # structural identity kept
        assert data['display_name'] == "Alice Example"
        assert data['entries'] == 3
        assert data['media_files_restored'] == 3
        assert data['backup_db_path']
        assert Path(data['backup_db_path']).exists()

        updated = master_db.get_user(bob.id)
        assert updated.display_name == "Alice Example"
        assert updated.email == "alice@example.com"

    def test_replace_currently_open_profile_refused(
        self, bridge, master_db, alice_archive, replace_setup
    ):
        bob, carol = replace_setup
        assert_success(bridge.selectProfile(bob.id))

        response = bridge.executeProfileImport(json.dumps({
            "archive_path": str(alice_archive),
            "mode": "replace",
            "target_user_id": bob.id,
            "confirm_replace": True,
        }))

        assert_error(response, "switch")
        assert master_db.get_user(bob.id).display_name == "Bob Target"

    def test_replace_requires_confirmation(
        self, bridge, alice_archive, replace_setup
    ):
        bob, carol = replace_setup

        response = bridge.executeProfileImport(json.dumps({
            "archive_path": str(alice_archive),
            "mode": "replace",
            "target_user_id": bob.id,
        }))

        assert_error(response, "confirmation")

    def test_replace_requires_target_user_id(self, bridge, alice_archive):
        response = bridge.executeProfileImport(json.dumps({
            "archive_path": str(alice_archive),
            "mode": "replace",
            "confirm_replace": True,
        }))

        assert_error(response, "target_user_id")


class TestExecuteProfileImportErrors:

    def test_corrupt_zip_clean_error(self, bridge, master_db, tmp_path):
        bad = tmp_path / "corrupt.wimi"
        bad.write_bytes(b"this is definitely not a zip file")

        response = bridge.executeProfileImport(json.dumps({
            "archive_path": str(bad),
            "mode": "create",
        }))

        assert_error(response, "not a zip")
        assert master_db.get_all_users(include_deleted=True) == []

    def test_missing_archive_clean_error(self, bridge, tmp_path):
        response = bridge.executeProfileImport(json.dumps({
            "archive_path": str(tmp_path / "nope.wimi"),
            "mode": "create",
        }))

        assert_error(response, "not found")

    def test_newer_schema_blocked_with_clean_error(
        self, bridge, master_db, alice_archive, tmp_path
    ):
        newer = _make_newer_archive(alice_archive, tmp_path)

        response = bridge.executeProfileImport(json.dumps({
            "archive_path": str(newer),
            "mode": "create",
        }))

        assert_error(response, "newer version of WIMI")
        # Blocked before any state change.
        assert master_db.get_all_users(include_deleted=True) == []

    def test_invalid_mode_fails(self, bridge, alice_archive):
        response = bridge.executeProfileImport(json.dumps({
            "archive_path": str(alice_archive),
            "mode": "merge",
        }))

        assert_error(response, "mode")

    def test_missing_archive_path_fails(self, bridge):
        response = bridge.executeProfileImport(json.dumps({"mode": "create"}))
        assert_error(response, "archive_path")

    def test_malformed_json_fails(self, bridge):
        response = bridge.executeProfileImport("{not json")
        assert_error(response, "Invalid import params")
