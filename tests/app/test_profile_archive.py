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
from tests import _schema_mutations
from app.profile_archive import (
    ArchiveValidationError,
    ProfileArchiveError,
    ProfileImportError,
    VERDICT_NEWER_APP_REQUIRED,
    VERDICT_OK,
    VERDICT_UNRECOGNISED_STRUCTURE,
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


def _logical_dump(db_path: Path) -> str:
    """Every schema statement and row, as SQL text.

    Compares what a database *holds* rather than how it is laid out, which is
    what "restored exactly" means to a student. See
    ``test_rollback_restores_the_database_and_media_exactly``.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        return "\n".join(conn.iterdump())
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
        # Subset, not equality: #124 added date ranges and a subject count to
        # these stats so a fork report can tell "a month of work" from "a stale
        # copy". Asserting the whole dict would make every future addition a
        # failure here, in a test that is about media flattening.
        assert manifest["stats"]["entries"] == 3
        assert manifest["stats"]["sessions"] == 1
        assert manifest["stats"]["exam_contexts"] == 1
        for added in ("subjects", "encountered_first", "encountered_last",
                      "logged_first", "logged_last"):
            assert added in manifest["stats"], f"{added} missing from stats"

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

    def test_rollback_restores_the_database_and_media_exactly(
        self, alice_archive, dest_master, replace_setup, monkeypatch
    ):
        """Logically identical, to the row. Not byte-identical any more (#155).

        This asserted byte-identity until the safety backup moved from
        ``PRAGMA wal_checkpoint`` + ``shutil.copy2`` to
        ``Connection.backup()``. Byte-identity was never the guarantee -- it
        was a side effect of the restore being a raw file copy, and it held
        here only because the fixture's database has no ``-wal`` at all. With
        a WAL present the old path produced a file byte-identical to a
        database *separated from its most recent commits*, which is #155:
        the check would have passed while the student's newest entries were
        missing from the only copy left of them.

        So the assertion is now the stronger one -- every row, via
        ``iterdump`` -- plus a characterisation of the bytes that do differ,
        measured rather than waved at. ``Connection.backup()`` rewrites three
        header fields and nothing else: the file change counter (offsets
        24-27), the schema cookie (40-43) and the version-valid-for number
        (92-95). All three exist so that a *different* connection can tell
        the file moved under it; none of them is data. Length, page size and
        page count are unchanged, so this is a page-for-page copy and not a
        VACUUM.

        The schema cookie is the one worth naming. A database with a trivial
        schema can come back differing at only 27 and 95, so a check written
        against a toy fixture passes and then fails on a real profile that
        has run twenty migrations. Measured both ways while writing this.
        """
        bob, carol = replace_setup
        db_path = dest_master.users_dir / bob.database_filename
        media_dir = dest_master.data_dir / "media" / f"user_{bob.id}_bob"
        db_bytes_before = db_path.read_bytes()
        dump_before = _logical_dump(db_path)
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

        # DB restored to the row; no .importing/-wal/-shm leftovers.
        assert _logical_dump(db_path) == dump_before
        db_bytes_after = db_path.read_bytes()
        assert len(db_bytes_after) == len(db_bytes_before)
        differing = [
            i for i in range(len(db_bytes_before))
            if db_bytes_before[i] != db_bytes_after[i]
        ]
        # file change counter | schema cookie | version-valid-for number
        header_bookkeeping = set(range(24, 28)) | set(range(40, 44)) \
            | set(range(92, 96))
        assert set(differing) <= header_bookkeeping, (
            "the restored database differs outside SQLite's header "
            f"bookkeeping, at offsets "
            f"{sorted(set(differing) - header_bookkeeping)}"
        )
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


# ==================== structure check (#593) ====================
#
# The owner's decision on #593: compare an incoming database's structure with
# the one WIMI creates, and refuse it on a mismatch. Every foreign database
# here is a real export plus one named mutation from tests/_schema_mutations.py,
# built at runtime. The comparison's own rules are tested in
# tests/database/test_schema_fingerprint.py; these tests cover the routes in.

def _mutated_archive(alice_archive, tmp_path, mutation, name, *, older=False):
    db = _extract_db(alice_archive, tmp_path / f"mut_{name}")
    conn = sqlite3.connect(str(db))
    try:
        mutation(conn)
        if older:
            # The same mutation, on an archive that will be migrated first:
            # the check must see the database as it will be once installed.
            conn.execute(
                "DELETE FROM schema_migrations WHERE version = "
                "(SELECT MAX(version) FROM schema_migrations)")
            conn.commit()
    finally:
        conn.close()
    return db, _rezip_with_db(alice_archive, db, tmp_path / f"{name}.wimi")


class TestStructureCheck:
    @pytest.mark.parametrize("mutation, table", [
        (_schema_mutations.drop_alias_type_check, "subject_aliases"),
        (_schema_mutations.alias_id_as_text, "subject_aliases"),
        (_schema_mutations.add_trigger, "mutation_trigger"),
    ], ids=["variant-A", "variant-D", "extra-trigger"])
    def test_preflight_refuses_and_names_what_it_found(
        self, alice_archive, tmp_path, mutation, table
    ):
        db, _ = _mutated_archive(alice_archive, tmp_path, mutation, table)

        result = preflight_schema(db)

        assert result["verdict"] == VERDICT_UNRECOGNISED_STRUCTURE
        assert result["blocked"] is True
        assert table in result["reason"], result["reason"]
        # Not the newer-app advice: updating WIMI fixes nothing here (#174).
        assert "Update WIMI" not in result["reason"]
        assert "Nothing on this computer has been changed" in result["reason"]

    def test_an_unchanged_export_is_not_blocked(self, alice_archive, tmp_path):
        """Positive control: without it the refusals above could be a check
        that refuses every archive."""
        result = preflight_schema(_extract_db(alice_archive, tmp_path / "clean"))
        assert result["verdict"] == VERDICT_OK
        assert result["blocked"] is False

    def test_an_older_archive_is_checked_after_it_is_migrated(
        self, alice_archive, tmp_path
    ):
        clean, _ = _mutated_archive(
            alice_archive, tmp_path, lambda conn: None, "older_clean",
            older=True)
        assert preflight_schema(clean)["verdict"] == VERDICT_WILL_UPGRADE

        mutated, _ = _mutated_archive(
            alice_archive, tmp_path, _schema_mutations.alias_id_as_text,
            "older_mutated", older=True)
        result = preflight_schema(mutated)
        assert result["verdict"] == VERDICT_UNRECOGNISED_STRUCTURE
        assert result["blocked"] is True

    def test_a_value_that_fits_its_column_is_not_this_checks_business(
        self, alice_archive, tmp_path
    ):
        """Option 2's stated boundary (#593 variant B): text stored in a REAL
        column changes no DDL, so the structure check passes it. It is
        recorded here so that nobody reads this check as covering values."""
        def text_in_a_real_column(conn):
            conn.execute(
                "UPDATE user_preferences SET font_size_scale = 'not a number'")
            conn.commit()

        db, _ = _mutated_archive(
            alice_archive, tmp_path, text_in_a_real_column, "variant_b")
        assert preflight_schema(db)["blocked"] is False

    def test_install_as_new_refuses_before_any_state_change(
        self, alice_archive, dest_master, tmp_path
    ):
        _, archive = _mutated_archive(
            alice_archive, tmp_path, _schema_mutations.alias_id_as_text,
            "install")

        with pytest.raises(ProfileImportError, match="subject_aliases"):
            install_profile_as_new(dest_master, archive)

        assert dest_master.get_all_users(include_deleted=True) == []
        assert list(dest_master.users_dir.iterdir()) == []

    def test_replace_refuses_and_leaves_the_target_as_it_was(
        self, alice_archive, dest_master, replace_setup, tmp_path
    ):
        bob, carol = replace_setup
        bob_db = dest_master.users_dir / bob.database_filename
        before = _logical_dump(bob_db)
        _, archive = _mutated_archive(
            alice_archive, tmp_path, _schema_mutations.drop_alias_type_check,
            "replace")

        with pytest.raises(ProfileImportError, match="subject_aliases"):
            replace_profile(dest_master, archive, target_user_id=bob.id,
                            active_user_id=carol.id, confirm_replace=True)

        assert _logical_dump(bob_db) == before
        assert dest_master.get_user(bob.id).display_name == "Bob Target"


# ==================== #776: an installed profile is rehomed to its new id ====================

USER_ID_TABLES_2026_10_12 = {
    "entry_media", "exam_contexts", "question_sources", "reflection_themes",
    "review_sessions", "user_assessment_preferences", "user_assessments",
    "user_goals", "user_preferences",
    # #778 Wave 0 (m033): exam-less plans are allowed, so both tables scope
    # by user_id and are rehomed on install like the rest.
    "planned_sessions", "session_templates",
}


def _user_id_tables(db_path: Path) -> set:
    conn = sqlite3.connect(str(db_path))
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t for t in names
                if any(c[1] == 'user_id' for c in conn.execute(f'PRAGMA table_info("{t}")'))}
    finally:
        conn.close()


def _foreign_user_ids(db_path: Path, own_id: int) -> dict:
    """{table: [other user_ids]} for every table still naming somebody else."""
    conn = sqlite3.connect(str(db_path))
    try:
        out = {}
        for t in _user_id_tables(db_path):
            others = [r[0] for r in conn.execute(
                f'SELECT DISTINCT user_id FROM "{t}" WHERE user_id IS NOT NULL AND user_id != ?',
                (own_id,))]
            if others:
                out[t] = others
        return out
    finally:
        conn.close()


class TestInstallRehomesUserId:
    """#776. The archive's user database names the SENDER's ``users.id``;
    every read filters on the receiver's. Each test here installs under an
    id that differs from the one the profile left with, because the round
    trip into a fresh master (1 -> 1) is exactly the case that hid this."""

    def test_the_user_id_tables_are_the_ones_the_fix_was_written_against(self, dest_master):
        """Discovery, not a pin on the fix: the rehome reads the list from
        sqlite_master, so a new table is covered automatically. This test
        exists so a schema change shows up here with a sentence, rather than
        silently widening what the fix touches."""
        u = dest_master.create_user(username="probe", display_name="P")
        db_path = dest_master.ensure_user_database(u.id)
        UserDatabase(db_path=db_path, user_id=u.id, username="probe").close()
        assert _user_id_tables(db_path) == USER_ID_TABLES_2026_10_12

    def test_installed_under_a_different_id_the_exams_are_visible(self, alice_archive, dest_master):
        dest_master.create_user(username="occupant", display_name="Already Here")
        result = install_profile_as_new(dest_master, alice_archive)
        user = dest_master.get_user(result["user_id"])
        assert user.id != 1, "the test needs the new id to differ from alice's (1)"

        db_path = dest_master.users_dir / user.database_filename
        assert _foreign_user_ids(db_path, user.id) == {}
        db = UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
        try:
            exams = db.get_all_exam_contexts()
            assert [e.exam_name for e in exams] == ["Sample Exam"]
            sessions = db.fetchone(
                "SELECT COUNT(*) AS n FROM review_sessions WHERE user_id = ?", (user.id,))
            assert sessions["n"] == 1
        finally:
            db.close()
        assert result["warnings"] == []

    def test_the_archives_preferences_win_over_the_fresh_defaults(
            self, source_master, alice, dest_master, tmp_path):
        src_db = UserDatabase(db_path=source_master.users_dir / alice.database_filename,
                              user_id=alice.id, username=alice.username)
        try:
            src_db.update_preferences(theme_name="midnight")
        finally:
            src_db.close()
        archive = tmp_path / "alice_prefs.wimi"
        build_profile_archive(source_master, alice.id, archive, include_media=False)

        dest_master.create_user(username="occupant", display_name="Already Here")
        result = install_profile_as_new(dest_master, archive)
        user = dest_master.get_user(result["user_id"])
        db_path = dest_master.users_dir / user.database_filename

        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute("SELECT user_id, theme_name FROM user_preferences").fetchall()
        finally:
            conn.close()
        assert rows == [(user.id, "midnight")], (
            "the verify-open's default row must yield to the archive's, and only one may remain")

    def test_replace_profile_rehomes_to_the_target_id(self, alice_archive, dest_master):
        dest_master.create_user(username="occupant", display_name="Already Here")
        bob = dest_master.create_user(username="bob", display_name="Bob")
        bob_db = dest_master.ensure_user_database(bob.id)
        UserDatabase(db_path=bob_db, user_id=bob.id, username="bob").close()
        assert bob.id != 1

        replace_profile(dest_master, alice_archive, target_user_id=bob.id,
                        active_user_id=None, confirm_replace=True)

        assert _foreign_user_ids(bob_db, bob.id) == {}
        db = UserDatabase(db_path=bob_db, user_id=bob.id, username="bob")
        try:
            assert [e.exam_name for e in db.get_all_exam_contexts()] == ["Sample Exam"]
        finally:
            db.close()

    def test_an_install_under_the_same_id_rewrites_nothing(self, alice_archive, dest_master):
        """The control: 1 -> 1 was always fine, and must stay a no-op."""
        result = install_profile_as_new(dest_master, alice_archive)
        user = dest_master.get_user(result["user_id"])
        assert user.id == 1
        db_path = dest_master.users_dir / user.database_filename
        assert _foreign_user_ids(db_path, 1) == {}
        db = UserDatabase(db_path=db_path, user_id=1, username=user.username)
        try:
            assert [e.exam_name for e in db.get_all_exam_contexts()] == ["Sample Exam"]
        finally:
            db.close()

    def test_two_foreign_ids_collapse_to_one_preferences_row_with_a_warning(
            self, alice_archive, dest_master, tmp_path):
        """An archive exported from an install this bug had already touched
        carries the real preferences under the old id AND a default row the
        buggy install created under its own id. Deterministic outcome: one
        row, and the caller is told."""
        db_tmp = _extract_db(alice_archive, tmp_path / "x")
        conn = sqlite3.connect(str(db_tmp))
        try:
            # alice never read her preferences, so the seeded archive has no
            # row for her at all; write both rows explicitly, with dates.
            conn.execute("DELETE FROM user_preferences")
            conn.execute(
                "INSERT INTO user_preferences (user_id, theme_name, updated_at) "
                "VALUES (1, 'midnight', '2026-06-01 00:00:00')")
            conn.execute(
                "INSERT INTO user_preferences (user_id, theme_name, updated_at) "
                "VALUES (9, 'default', '2000-01-01 00:00:00')")
            conn.commit()
        finally:
            conn.close()
        tampered = _rezip_with_db(alice_archive, db_tmp, tmp_path / "two_ids.wimi")

        dest_master.create_user(username="occupant", display_name="Already Here")
        result = install_profile_as_new(dest_master, tampered)
        user = dest_master.get_user(result["user_id"])
        conn = sqlite3.connect(str(dest_master.users_dir / user.database_filename))
        try:
            rows = conn.execute("SELECT user_id, theme_name FROM user_preferences").fetchall()
        finally:
            conn.close()
        assert rows == [(user.id, "midnight")]
        assert any("different profile ids" in w for w in result["warnings"])
