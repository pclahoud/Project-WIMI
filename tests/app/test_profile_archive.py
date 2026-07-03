"""
Tests for src/app/profile_archive.py — .wimi profile export/import engine.

Pure-Python module (no Qt), so these run without a QApplication.
"""
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase
from database.migrations.user import MIGRATIONS as USER_MIGRATIONS
from app import profile_archive
from app.profile_archive import (
    ArchiveValidationError,
    ProfileArchiveError,
    ProfileImportError,
    VERDICT_NEWER_APP_REQUIRED,
    VERDICT_OK,
    VERDICT_WILL_UPGRADE,
    build_profile_archive,
    install_profile_as_new,
    preflight_schema,
    read_profile_archive,
    replace_profile,
)

LOCAL_MAX = max(m.version for m in USER_MIGRATIONS)

FLAT_IMG = "aaaaaaaa-1111-2222-3333-444444444444.png"
FLAT_THUMB = "aaaaaaaa-1111-2222-3333-444444444444_thumb.jpg"
LEGACY_IMG = "bbbbbbbb-5555-6666-7777-888888888888.png"


# ==================== helpers ====================

def _seed_user_db(master_db: MasterDatabase, user, n_entries: int = 3) -> None:
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
            for i in range(1, n_entries + 1):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, i, f"answer_{i}", f"correct_{i}"),
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


def _entry_count(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
    finally:
        conn.close()


def _max_migration_version(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return row[0] or 0
    finally:
        conn.close()


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


# ==================== fixtures ====================

@pytest.fixture
def source_master(tmp_path):
    """Master DB 'A' — the export side."""
    db = MasterDatabase(data_dir=tmp_path / "data_a", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def dest_master(tmp_path):
    """A SECOND, fresh master DB 'B' — the import side (separate temp dir)."""
    db = MasterDatabase(data_dir=tmp_path / "data_b", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def alice(source_master):
    """Seeded source user with 3 entries and media (flat + one legacy subdir)."""
    user = source_master.create_user(
        username="alice",
        display_name="Alice Example",
        email="alice@example.com",
    )
    _seed_user_db(source_master, user, n_entries=3)
    _make_media(source_master, user)
    return user


@pytest.fixture
def alice_archive(source_master, alice, tmp_path):
    """Exported archive of alice, media included."""
    dest = tmp_path / "alice.wimi"
    build_profile_archive(
        source_master, alice.id, dest, include_media=True
    )
    return dest


# ==================== export ====================

class TestExport:
    def test_roundtrip_with_media_flattens_legacy_subdirs(
        self, source_master, alice, tmp_path
    ):
        dest = tmp_path / "out.wimi"
        result = build_profile_archive(
            source_master, alice.id, dest, include_media=True
        )

        assert dest.exists()
        with zipfile.ZipFile(str(dest)) as zf:
            names = set(zf.namelist())
        assert "manifest.json" in names
        assert "user.db" in names
        # Flat files kept flat; legacy entry_5/ file flattened to media/ root.
        assert f"media/{FLAT_IMG}" in names
        assert f"media/{FLAT_THUMB}" in names
        assert f"media/{LEGACY_IMG}" in names
        assert not any("entry_5" in n for n in names)

        manifest = result["manifest"]
        assert manifest["format"] == "wimi-profile"
        assert manifest["format_version"] == 1
        assert manifest["user"]["username"] == "alice"
        assert manifest["user"]["display_name"] == "Alice Example"
        assert manifest["user"]["email"] == "alice@example.com"
        assert "is_primary_admin" not in manifest["user"]
        assert manifest["db"]["schema_max_version"] == LOCAL_MAX
        assert manifest["db"]["applied_versions"] == sorted(
            m.version for m in USER_MIGRATIONS
        )
        assert manifest["media"] == {
            "included": True,
            "file_count": 3,
            "total_bytes": manifest["media"]["total_bytes"],
        }
        assert manifest["media"]["total_bytes"] > 0
        assert manifest["stats"] == {
            "entries": 3, "sessions": 1, "exam_contexts": 1,
        }

    def test_export_without_media(self, source_master, alice, tmp_path):
        dest = tmp_path / "no_media.wimi"
        result = build_profile_archive(
            source_master, alice.id, dest, include_media=False
        )
        with zipfile.ZipFile(str(dest)) as zf:
            names = zf.namelist()
        assert not any(n.startswith("media/") for n in names)
        assert result["manifest"]["media"] == {
            "included": False, "file_count": 0, "total_bytes": 0,
        }

    def test_snapshot_is_consistent_with_live_connection(
        self, source_master, alice, tmp_path
    ):
        """backup() must capture rows written through a still-open live DB."""
        db_path = source_master.users_dir / alice.database_filename
        live = UserDatabase(db_path=db_path, user_id=alice.id, username="alice")
        try:
            with live.transaction():
                cur = live.execute(
                    "SELECT id FROM review_sessions LIMIT 1"
                ).fetchone()
                live.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer) "
                    "VALUES (?, 99, 'live', 'live')",
                    (cur["id"],),
                )
            dest = tmp_path / "live.wimi"
            # Export while the live connection is still open (WAL not closed).
            build_profile_archive(source_master, alice.id, dest)
        finally:
            live.close()

        snapshot_db = _extract_db(dest, tmp_path / "live_extract")
        assert _entry_count(snapshot_db) == 4

    def test_export_unknown_user_raises(self, source_master, tmp_path):
        with pytest.raises(ProfileArchiveError, match="not found"):
            build_profile_archive(source_master, 999, tmp_path / "x.wimi")


# ==================== read / validation ====================

class TestReadArchive:
    def test_valid_archive_inventory(self, alice_archive):
        info = read_profile_archive(alice_archive)
        assert info["manifest"]["user"]["username"] == "alice"
        assert info["has_media"] is True
        assert info["media_file_count"] == 3
        assert info["media_total_bytes"] > 0
        assert info["db_uncompressed_bytes"] > 0
        assert info["total_uncompressed_bytes"] > info["media_total_bytes"]

    def test_rejects_corrupt_zip(self, tmp_path):
        bad = tmp_path / "corrupt.wimi"
        bad.write_bytes(b"this is definitely not a zip file")
        with pytest.raises(ArchiveValidationError, match="not a zip"):
            read_profile_archive(bad)

    def test_rejects_missing_file(self, tmp_path):
        with pytest.raises(ArchiveValidationError, match="not found"):
            read_profile_archive(tmp_path / "nope.wimi")

    def test_rejects_missing_manifest(self, tmp_path):
        path = tmp_path / "no_manifest.wimi"
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("user.db", b"whatever")
        with pytest.raises(ArchiveValidationError, match="manifest.json is missing"):
            read_profile_archive(path)

    def test_rejects_missing_user_db(self, tmp_path):
        path = tmp_path / "no_db.wimi"
        manifest = {"format": "wimi-profile", "format_version": 1}
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        with pytest.raises(ArchiveValidationError, match="user.db is missing"):
            read_profile_archive(path)

    def test_rejects_path_traversal_entry(self, tmp_path):
        path = tmp_path / "traversal.wimi"
        manifest = {"format": "wimi-profile", "format_version": 1}
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("user.db", b"whatever")
            zf.writestr("../evil.txt", b"escape attempt")
        with pytest.raises(ArchiveValidationError, match="traversal"):
            read_profile_archive(path)

    def test_rejects_wrong_format(self, tmp_path):
        path = tmp_path / "wrong_format.wimi"
        manifest = {"format": "some-other-thing", "format_version": 1}
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("user.db", b"whatever")
        with pytest.raises(ArchiveValidationError, match="Not a WIMI profile"):
            read_profile_archive(path)

    def test_rejects_newer_format_version(self, tmp_path):
        path = tmp_path / "future.wimi"
        manifest = {"format": "wimi-profile", "format_version": 2}
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("user.db", b"whatever")
        with pytest.raises(ArchiveValidationError, match="newer version of WIMI"):
            read_profile_archive(path)

    def test_rejects_invalid_manifest_json(self, tmp_path):
        path = tmp_path / "bad_json.wimi"
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("manifest.json", "{not json")
            zf.writestr("user.db", b"whatever")
        with pytest.raises(ArchiveValidationError, match="not valid JSON"):
            read_profile_archive(path)


# ==================== preflight ====================

class TestPreflight:
    def test_current_schema_is_ok(self, alice_archive, tmp_path):
        db = _extract_db(alice_archive, tmp_path / "pf_ok")
        result = preflight_schema(db)
        assert result["verdict"] == VERDICT_OK
        assert result["archive_max_version"] == LOCAL_MAX
        assert result["local_max_version"] == LOCAL_MAX
        assert result["pending_versions"] == []

    def test_newer_schema_blocked(self, alice_archive, tmp_path):
        db = _extract_db(alice_archive, tmp_path / "pf_newer")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO schema_migrations (version, name, checksum) "
            "VALUES (999, 'from_the_future', 'x')"
        )
        conn.commit()
        conn.close()

        result = preflight_schema(db)
        assert result["verdict"] == VERDICT_NEWER_APP_REQUIRED
        assert "newer version of WIMI" in result["reason"]

    def test_checksum_mismatch_blocked(self, alice_archive, tmp_path):
        db = _extract_db(alice_archive, tmp_path / "pf_cksum")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = "
            "(SELECT MAX(version) FROM schema_migrations)",
            ("0" * 64,),
        )
        conn.commit()
        conn.close()

        result = preflight_schema(db)
        assert result["verdict"] == VERDICT_NEWER_APP_REQUIRED
        assert "checksum" in result["reason"].lower()
        # The preflight copy must not have mutated the original file's stamp.
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT checksum FROM schema_migrations WHERE version = "
            "(SELECT MAX(version) FROM schema_migrations)"
        ).fetchone()
        conn.close()
        assert row[0] == "0" * 64

    def test_older_schema_will_upgrade(self, alice_archive, tmp_path):
        db = _extract_db(alice_archive, tmp_path / "pf_older")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "DELETE FROM schema_migrations WHERE version = "
            "(SELECT MAX(version) FROM schema_migrations)"
        )
        conn.commit()
        conn.close()

        result = preflight_schema(db)
        assert result["verdict"] == VERDICT_WILL_UPGRADE
        assert result["pending_versions"] == [LOCAL_MAX]


# ==================== import: create new ====================

class TestInstallAsNew:
    def test_roundtrip_into_second_master(self, alice_archive, dest_master):
        result = install_profile_as_new(dest_master, alice_archive)

        assert result["warnings"] == []
        assert result["username"] == "alice"
        assert result["schema_verdict"] == VERDICT_OK
        assert result["entries"] == 3
        assert result["media_files_copied"] == 3

        user = dest_master.get_user(result["user_id"])
        assert user is not None
        assert user.display_name == "Alice Example"
        assert user.email == "alice@example.com"
        assert user.is_primary_admin is False

        db_path = dest_master.users_dir / user.database_filename
        assert db_path.exists()
        assert _entry_count(db_path) == 3
        assert _max_migration_version(db_path) == LOCAL_MAX

        media_dir = (
            dest_master.data_dir / "media" / f"user_{user.id}_{user.username}"
        )
        assert (media_dir / FLAT_IMG).read_bytes() == b"flat-image-bytes"
        assert (media_dir / FLAT_THUMB).exists()
        # Legacy file arrives flattened, no entry_* subdirs recreated.
        assert (media_dir / LEGACY_IMG).read_bytes() == b"legacy-image-bytes"
        assert not any(p.is_dir() for p in media_dir.iterdir())

    def test_username_collision_gets_suffix(self, alice_archive, dest_master):
        dest_master.create_user(username="alice", display_name="Other Alice")

        result = install_profile_as_new(dest_master, alice_archive)

        assert result["username"] == "alice_2"
        assert any("alice_2" in w for w in result["warnings"])
        user = dest_master.get_user(result["user_id"])
        assert user.username == "alice_2"
        # Email of the imported profile is unaffected by the username clash.
        assert user.email == "alice@example.com"

    def test_email_collision_drops_email_with_warning(
        self, alice_archive, dest_master
    ):
        dest_master.create_user(
            username="phil_test",
            display_name="Phil Test",
            email="alice@example.com",
        )

        result = install_profile_as_new(dest_master, alice_archive)

        assert result["email"] is None
        assert any("email" in w.lower() for w in result["warnings"])
        user = dest_master.get_user(result["user_id"])
        assert user.email is None

    def test_rollback_leaves_zero_residue(
        self, alice_archive, dest_master, monkeypatch
    ):
        users_before = {u.id for u in dest_master.get_all_users(include_deleted=True)}
        files_before = set(dest_master.users_dir.iterdir())

        def boom(*args, **kwargs):
            raise RuntimeError("verify-open exploded")

        monkeypatch.setattr(profile_archive, "UserDatabase", boom)

        with pytest.raises(ProfileImportError, match="rolled back"):
            install_profile_as_new(dest_master, alice_archive)

        users_after = {u.id for u in dest_master.get_all_users(include_deleted=True)}
        assert users_after == users_before
        assert set(dest_master.users_dir.iterdir()) == files_before
        media_root = dest_master.data_dir / "media"
        assert not media_root.exists() or not any(media_root.iterdir())

    def test_newer_archive_blocked_before_any_state_change(
        self, alice_archive, dest_master, tmp_path
    ):
        db = _extract_db(alice_archive, tmp_path / "newer_mod")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO schema_migrations (version, name, checksum) "
            "VALUES (999, 'from_the_future', 'x')"
        )
        conn.commit()
        conn.close()
        newer_archive = _rezip_with_db(
            alice_archive, db, tmp_path / "newer.wimi"
        )

        with pytest.raises(ProfileImportError, match="newer version of WIMI"):
            install_profile_as_new(dest_master, newer_archive)

        assert dest_master.get_all_users(include_deleted=True) == []
        assert list(dest_master.users_dir.iterdir()) == []

    def test_older_schema_archive_auto_migrates(
        self, alice_archive, dest_master, tmp_path
    ):
        # Strip the last migration's stamp so the archive DB reads as older.
        db = _extract_db(alice_archive, tmp_path / "older_mod")
        conn = sqlite3.connect(str(db))
        conn.execute(
            "DELETE FROM schema_migrations WHERE version = "
            "(SELECT MAX(version) FROM schema_migrations)"
        )
        conn.commit()
        conn.close()
        assert _max_migration_version(db) < LOCAL_MAX
        older_archive = _rezip_with_db(alice_archive, db, tmp_path / "older.wimi")

        result = install_profile_as_new(dest_master, older_archive)

        assert result["schema_verdict"] == VERDICT_WILL_UPGRADE
        assert result["entries"] == 3
        user = dest_master.get_user(result["user_id"])
        installed_db = dest_master.users_dir / user.database_filename
        # Verify-open re-applied the pending migration and stamped it.
        assert _max_migration_version(installed_db) == LOCAL_MAX


# ==================== import: replace existing ====================

@pytest.fixture
def replace_setup(dest_master):
    """Target user 'bob' (1 entry + media) and active user 'carol' in master B."""
    bob = dest_master.create_user(
        username="bob", display_name="Bob Target", email="bob@example.com"
    )
    _seed_user_db(dest_master, bob, n_entries=1)
    bob_media = dest_master.data_dir / "media" / f"user_{bob.id}_{bob.username}"
    bob_media.mkdir(parents=True, exist_ok=True)
    (bob_media / "old-media-file.png").write_bytes(b"bob-old-media")

    carol = dest_master.create_user(username="carol", display_name="Carol Active")
    return bob, carol


class TestReplaceProfile:
    def test_happy_path(self, alice_archive, dest_master, replace_setup):
        bob, carol = replace_setup
        original_filename = bob.database_filename

        result = replace_profile(
            dest_master,
            alice_archive,
            target_user_id=bob.id,
            active_user_id=carol.id,
            confirm_replace=True,
        )

        # Structural identity kept, descriptive fields updated.
        updated = dest_master.get_user(bob.id)
        assert updated.username == "bob"
        assert updated.database_filename == original_filename
        assert updated.display_name == "Alice Example"
        assert updated.email == "alice@example.com"

        # Data replaced.
        db_path = dest_master.users_dir / original_filename
        assert _entry_count(db_path) == 3
        assert result["entries"] == 3

        # Safety DB backup kept in archive_dir.
        backups = list(
            dest_master.archive_dir.glob(f"pre_replace_{original_filename}.*.db")
        )
        assert len(backups) == 1
        assert result["backup_db_path"] == str(backups[0])
        assert _entry_count(backups[0]) == 1  # bob's old data

        # Media swapped: old file gone, archive media in, backup dir deleted.
        media_dir = dest_master.data_dir / "media" / f"user_{bob.id}_bob"
        assert not (media_dir / "old-media-file.png").exists()
        assert (media_dir / FLAT_IMG).exists()
        assert (media_dir / LEGACY_IMG).exists()
        assert not list(
            (dest_master.data_dir / "media").glob("*.pre_replace_*")
        )

    def test_replace_active_profile_forbidden(
        self, alice_archive, dest_master, replace_setup
    ):
        bob, _ = replace_setup
        with pytest.raises(ProfileImportError, match="[Ss]witch"):
            replace_profile(
                dest_master,
                alice_archive,
                target_user_id=bob.id,
                active_user_id=bob.id,
                confirm_replace=True,
            )

    def test_replace_requires_confirmation(
        self, alice_archive, dest_master, replace_setup
    ):
        bob, carol = replace_setup
        with pytest.raises(ProfileImportError, match="confirmation"):
            replace_profile(
                dest_master,
                alice_archive,
                target_user_id=bob.id,
                active_user_id=carol.id,
                confirm_replace=False,
            )

    def test_rollback_restores_byte_identical_state(
        self, alice_archive, dest_master, replace_setup, monkeypatch
    ):
        bob, carol = replace_setup
        db_path = dest_master.users_dir / bob.database_filename
        media_dir = dest_master.data_dir / "media" / f"user_{bob.id}_bob"
        db_bytes_before = db_path.read_bytes()
        media_before = {
            p.name: p.read_bytes() for p in media_dir.iterdir() if p.is_file()
        }

        def boom(*args, **kwargs):
            raise RuntimeError("verify-open exploded")

        monkeypatch.setattr(profile_archive, "UserDatabase", boom)

        with pytest.raises(ProfileImportError, match="rolled back"):
            replace_profile(
                dest_master,
                alice_archive,
                target_user_id=bob.id,
                active_user_id=carol.id,
                confirm_replace=True,
            )

        # DB restored byte-identically; no .importing/-wal/-shm leftovers.
        assert db_path.read_bytes() == db_bytes_before
        assert not Path(str(db_path) + ".importing").exists()
        assert not Path(str(db_path) + "-wal").exists()
        assert not Path(str(db_path) + "-shm").exists()

        # Media dir restored exactly; the pre_replace backup dir was moved back.
        media_after = {
            p.name: p.read_bytes() for p in media_dir.iterdir() if p.is_file()
        }
        assert media_after == media_before
        assert not list(
            (dest_master.data_dir / "media").glob("*.pre_replace_*")
        )

        # Row restored by the rollback UPDATE.
        restored = dest_master.get_user(bob.id)
        assert restored.display_name == "Bob Target"
        assert restored.email == "bob@example.com"
        assert restored.username == "bob"

    def test_replace_unknown_target_raises(self, alice_archive, dest_master):
        with pytest.raises(ProfileImportError, match="not found"):
            replace_profile(
                dest_master,
                alice_archive,
                target_user_id=12345,
                confirm_replace=True,
            )
