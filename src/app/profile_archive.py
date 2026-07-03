"""
Profile archive engine — export/import of `.wimi` profile archives.

Archive format (format_version 1, plain zip):

    manifest.json          informational preview metadata (see below)
    user.db                snapshot of the per-user SQLite database
    media/<uuid>.<ext>     optional, flat (legacy entry_* subdirs are
    media/<uuid>_thumb.jpg flattened at export time)

Manifest schema (format_version 1)::

    {
      "format": "wimi-profile",
      "format_version": 1,
      "app_version": "<informational>",
      "created_at": "<UTC ISO-8601>",
      "user": {"username", "display_name", "email", "user_types"},
      "db": {"schema_max_version", "applied_versions"},
      "media": {"included", "file_count", "total_bytes"},
      "stats": {"entries", "sessions", "exam_contexts"}
    }

Permissions / ``is_primary_admin`` are deliberately NOT carried — importing
a profile must never mint a second primary admin. The manifest is
preview-informational only; import re-verifies everything against the
actual ``user.db``.

This module has NO Qt imports — pure stdlib + project database modules —
so it is unit-testable without a QApplication. The bridge layer
(``bridge_domains/profile_transfer.py``) is a thin wrapper around it.

All public functions accept an optional ``progress_cb`` callable. It is
ignored in v1 (synchronous execution + JS busy overlay); the parameter
exists so a later QThread upgrade doesn't require a signature redesign.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from database.master_db import MasterDatabase
from database.user_db import UserDatabase
from database.migration_runner import MigrationRunner, MigrationChecksumMismatchError
from database.migrations.user import MIGRATIONS as USER_MIGRATIONS


# ---------------------------------------------------------------------- constants

ARCHIVE_FORMAT = "wimi-profile"
ARCHIVE_FORMAT_VERSION = 1

MANIFEST_MEMBER = "manifest.json"
DB_MEMBER = "user.db"
MEDIA_PREFIX = "media/"

# Preflight verdicts
VERDICT_OK = "ok"
VERDICT_WILL_UPGRADE = "will_upgrade"
VERDICT_NEWER_APP_REQUIRED = "newer_app_required"

# Require free disk space >= uncompressed size x this factor before importing.
DISK_SPACE_SAFETY_FACTOR = 1.1

_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


# ---------------------------------------------------------------------- exceptions

class ProfileArchiveError(Exception):
    """Base error for profile archive operations."""


class ArchiveValidationError(ProfileArchiveError):
    """The archive file is not a valid WIMI profile archive."""


class ProfileImportError(ProfileArchiveError):
    """A profile import failed (state was rolled back where applicable)."""


# ---------------------------------------------------------------------- small helpers

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _app_version() -> str:
    """Best-effort app version for the (informational) manifest field."""
    try:
        from app import APP_VERSION
        return str(APP_VERSION)
    except Exception:
        return "unknown"


def _media_dir_for(master_db: MasterDatabase, user_id: int, username: str) -> Path:
    """Media directory for a user: {data_dir}/media/user_{id}_{username}.

    Mirrors ``MediaManager.user_media_path`` (media_manager.py:94) without
    importing the Qt-adjacent app layer.
    """
    return master_db.data_dir / "media" / f"user_{user_id}_{username}"


def _snapshot_database(source_db_path: Path, dest_path: Path) -> None:
    """Copy a SQLite database via ``Connection.backup`` (WAL-safe).

    Always used for export — it produces a consistent snapshot even while
    the profile is open in the app with uncommitted WAL frames.
    """
    src = sqlite3.connect(str(source_db_path))
    try:
        dst = sqlite3.connect(str(dest_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def _read_db_info(db_path: Path) -> Dict[str, Any]:
    """Read schema + stats info from a (closed) user database file."""
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            rows = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = [int(r[0]) for r in rows]
        except sqlite3.Error:
            applied = []
        return {
            "schema_max_version": max(applied) if applied else 0,
            "applied_versions": applied,
            "stats": {
                "entries": _count_rows(conn, "question_entries"),
                "sessions": _count_rows(conn, "review_sessions"),
                "exam_contexts": _count_rows(conn, "exam_contexts"),
            },
        }
    finally:
        conn.close()


def _collect_media_files(media_dir: Path) -> List[Tuple[Path, str]]:
    """List (source_path, flat_archive_name) pairs for a user's media dir.

    Flat files in the user media dir win; legacy ``entry_*`` subdirectory
    files are flattened into the same namespace (first occurrence wins,
    matching ``MediaManager._find_media_file``'s flat-first lookup order).
    """
    files: List[Tuple[Path, str]] = []
    seen: set = set()
    if not media_dir.is_dir():
        return files
    for item in sorted(media_dir.iterdir()):
        if item.is_file():
            files.append((item, item.name))
            seen.add(item.name)
    for item in sorted(media_dir.iterdir()):
        if item.is_dir() and item.name.startswith("entry_"):
            for legacy in sorted(item.iterdir()):
                if legacy.is_file() and legacy.name not in seen:
                    files.append((legacy, legacy.name))
                    seen.add(legacy.name)
    return files


def _reject_path_traversal(names) -> None:
    """Reject zip entries containing '..' path components.

    Same pattern as ``PluginManager.install_plugin`` (plugin_manager.py:221).
    """
    for entry in names:
        if '..' in entry.split('/') or '..' in entry.split('\\'):
            raise ArchiveValidationError(
                f'Archive contains a path-traversal entry: {entry}'
            )


def _remove_db_artifacts(db_path: Path) -> None:
    """Remove a user DB file and its WAL/SHM/graph side files (best-effort)."""
    for candidate in (
        db_path,
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
    ):
        try:
            if candidate.exists():
                candidate.unlink()
        except OSError:
            pass
    # Optional LadybugDB sibling (file or directory) — see GraphMixin.
    graph_path = db_path.with_suffix('.lbdb')
    try:
        if graph_path.is_dir():
            shutil.rmtree(str(graph_path), ignore_errors=True)
        elif graph_path.exists():
            graph_path.unlink()
    except OSError:
        pass


def _checkpoint_wal(db_path: Path) -> None:
    """Checkpoint a database's WAL (if any) so the .db file is self-contained."""
    if not Path(str(db_path) + "-wal").exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _ensure_disk_space(dest_dir: Path, required_bytes: int) -> None:
    free = shutil.disk_usage(str(dest_dir)).free
    needed = int(required_bytes * DISK_SPACE_SAFETY_FACTOR)
    if needed > free:
        raise ProfileImportError(
            f"Not enough disk space to import this profile: it needs about "
            f"{needed} bytes free but only {free} bytes are available."
        )


def _sanitize_candidate_username(raw: Optional[str]) -> str:
    """Reduce a manifest username to a valid one (>=3 chars of [a-zA-Z0-9_-])."""
    candidate = re.sub(r'[^a-zA-Z0-9_-]', '', str(raw or ''))
    if len(candidate) < 3:
        candidate = 'imported_profile'
    return candidate


def _next_free_username(master_db: MasterDatabase, base: str) -> str:
    """Return ``base`` or the first free ``base_N`` (N starting at 2)."""
    candidate = base
    suffix = 2
    while master_db.get_user_by_username(candidate) is not None:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _copy_flat_media(media_src: Path, media_dest: Path) -> int:
    """Copy top-level files from an extracted ``media/`` dir into place."""
    copied = 0
    if not media_src.is_dir():
        return copied
    media_dest.mkdir(parents=True, exist_ok=True)
    for item in sorted(media_src.iterdir()):
        if item.is_file():
            shutil.copy2(str(item), str(media_dest / item.name))
            copied += 1
    return copied


def _local_max_version() -> int:
    return max(m.version for m in USER_MIGRATIONS)


# ---------------------------------------------------------------------- export

def build_profile_archive(
    master_db: MasterDatabase,
    user_id: int,
    dest_path: str | Path,
    include_media: bool = False,
    progress_cb: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """
    Export a user's profile to a ``.wimi`` archive (plain zip).

    The user database is ALWAYS snapshotted via ``sqlite3.Connection.backup``
    to a temp file first — WAL-safe, and works even while the profile is
    open in the app. Stats and schema info in the manifest are computed
    from that snapshot, so they describe exactly the bytes shipped.

    Args:
        master_db: Master database (locates the user + files)
        user_id: User to export
        dest_path: Destination ``.wimi`` file path (overwritten if present)
        include_media: Also pack the user's media files (flattened)
        progress_cb: Ignored in v1 (reserved for a later async upgrade)

    Returns:
        {"dest_path", "manifest"}

    Raises:
        ProfileArchiveError: unknown user or missing user database file
    """
    del progress_cb  # v1: synchronous, no progress reporting

    user = master_db.get_user(user_id)
    if user is None:
        raise ProfileArchiveError(f"User {user_id} not found")

    source_db = master_db.users_dir / user.database_filename
    if not source_db.exists():
        raise ProfileArchiveError(
            f"User database file not found for '{user.username}': {source_db.name}"
        )

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix='wimi_export_'))
    try:
        snapshot = tmp_dir / DB_MEMBER
        _snapshot_database(source_db, snapshot)
        db_info = _read_db_info(snapshot)

        media_files: List[Tuple[Path, str]] = []
        if include_media:
            media_files = _collect_media_files(
                _media_dir_for(master_db, user.id, user.username)
            )
        media_total_bytes = sum(src.stat().st_size for src, _ in media_files)

        manifest = {
            "format": ARCHIVE_FORMAT,
            "format_version": ARCHIVE_FORMAT_VERSION,
            "app_version": _app_version(),
            "created_at": _utc_now_iso(),
            "user": {
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "user_types": list(user.user_type or []),
            },
            "db": {
                "schema_max_version": db_info["schema_max_version"],
                "applied_versions": db_info["applied_versions"],
            },
            "media": {
                "included": bool(include_media),
                "file_count": len(media_files),
                "total_bytes": media_total_bytes,
            },
            "stats": db_info["stats"],
        }

        with zipfile.ZipFile(str(dest_path), 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_MEMBER, json.dumps(manifest, indent=2))
            zf.write(str(snapshot), DB_MEMBER)
            for src, arc_name in media_files:
                zf.write(str(src), MEDIA_PREFIX + arc_name)

        return {"dest_path": str(dest_path), "manifest": manifest}
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


# ---------------------------------------------------------------------- read / validate

def read_profile_archive(
    zip_path: str | Path,
    progress_cb: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """
    Validate a ``.wimi`` archive and inventory its contents WITHOUT extracting.

    Checks performed: file exists, is a zip, no path-traversal entries,
    ``manifest.json`` + ``user.db`` present, manifest is valid JSON with
    ``format == "wimi-profile"`` and a supported ``format_version``.

    Returns:
        {"path", "manifest", "has_media", "media_file_count",
         "media_total_bytes", "db_uncompressed_bytes",
         "total_uncompressed_bytes"}

    Raises:
        ArchiveValidationError: on any validation failure
    """
    del progress_cb  # v1: synchronous, no progress reporting

    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise ArchiveValidationError(f"File not found: {zip_path}")
    if not zipfile.is_zipfile(str(zip_path)):
        raise ArchiveValidationError(
            "Not a valid WIMI profile archive (the file is not a zip archive)."
        )

    with zipfile.ZipFile(str(zip_path), 'r') as zf:
        names = zf.namelist()
        _reject_path_traversal(names)

        if MANIFEST_MEMBER not in names:
            raise ArchiveValidationError(
                "Not a WIMI profile archive: manifest.json is missing."
            )
        if DB_MEMBER not in names:
            raise ArchiveValidationError(
                "Invalid WIMI profile archive: user.db is missing."
            )

        try:
            manifest = json.loads(zf.read(MANIFEST_MEMBER).decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as e:
            raise ArchiveValidationError(
                f"Invalid WIMI profile archive: manifest.json is not valid JSON ({e})."
            ) from e

        if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT:
            raise ArchiveValidationError(
                "Not a WIMI profile archive (unexpected manifest format)."
            )

        fmt_version = manifest.get("format_version")
        if not isinstance(fmt_version, int) or fmt_version < 1:
            raise ArchiveValidationError(
                "Invalid WIMI profile archive: bad format_version in manifest."
            )
        if fmt_version > ARCHIVE_FORMAT_VERSION:
            raise ArchiveValidationError(
                "This profile archive was exported from a newer version of "
                "WIMI. Please update WIMI and try again."
            )

        media_bytes = 0
        media_count = 0
        db_bytes = 0
        for zinfo in zf.infolist():
            if zinfo.is_dir():
                continue
            if zinfo.filename == DB_MEMBER:
                db_bytes = zinfo.file_size
            elif zinfo.filename.startswith(MEDIA_PREFIX):
                media_count += 1
                media_bytes += zinfo.file_size
        total_bytes = sum(z.file_size for z in zf.infolist() if not z.is_dir())

    return {
        "path": str(zip_path),
        "manifest": manifest,
        "has_media": media_count > 0,
        "media_file_count": media_count,
        "media_total_bytes": media_bytes,
        "db_uncompressed_bytes": db_bytes,
        "total_uncompressed_bytes": total_bytes,
    }


# ---------------------------------------------------------------------- preflight

def preflight_schema(
    db_path: str | Path,
    progress_cb: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """
    Decide whether an archive's user database can be opened by this app.

    Compares ``MAX(version) FROM schema_migrations`` against the local user
    migration registry, and runs ``MigrationRunner.verify_checksums`` on a
    temp COPY of the database (the runner's constructor writes the
    ``schema_migrations`` table, so it must never touch the original).

    This must run BEFORE any ``UserDatabase.__init__`` verify-open so a
    newer-schema or checksum-divergent database is turned into a friendly
    verdict instead of the runner's hard failure.

    Returns:
        {"verdict": "ok" | "will_upgrade" | "newer_app_required",
         "archive_max_version", "local_max_version",
         "pending_versions", "reason"}
    """
    del progress_cb  # v1: synchronous, no progress reporting

    db_path = Path(db_path)
    local_max = _local_max_version()

    conn = sqlite3.connect(str(db_path))
    try:
        try:
            rows = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = [int(r[0]) for r in rows]
        except sqlite3.Error:
            applied = []
    finally:
        conn.close()

    archive_max = max(applied) if applied else 0
    result = {
        "verdict": VERDICT_OK,
        "archive_max_version": archive_max,
        "local_max_version": local_max,
        "pending_versions": [],
        "reason": "",
    }

    if archive_max > local_max:
        result["verdict"] = VERDICT_NEWER_APP_REQUIRED
        result["reason"] = (
            "This profile was exported from a newer version of WIMI "
            f"(database schema v{archive_max}; this app supports up to "
            f"v{local_max}). Please update WIMI and try again."
        )
        return result

    # Checksum verification on a throwaway copy — MigrationRunner's
    # constructor creates the schema_migrations table (a write), so never
    # point it at the caller's file.
    tmp_dir = Path(tempfile.mkdtemp(prefix='wimi_preflight_'))
    try:
        copy_path = tmp_dir / 'preflight_copy.db'
        shutil.copy2(str(db_path), str(copy_path))
        copy_conn = sqlite3.connect(str(copy_path))
        try:
            runner = MigrationRunner(copy_conn, USER_MIGRATIONS, scope="user")
            try:
                runner.verify_checksums()
            except MigrationChecksumMismatchError as e:
                result["verdict"] = VERDICT_NEWER_APP_REQUIRED
                result["reason"] = (
                    "This profile's database has a migration checksum mismatch "
                    "— it was likely exported from a newer or modified version "
                    f"of WIMI ({e}). Please update WIMI and try again."
                )
                return result
            result["pending_versions"] = [m.version for m in runner.pending()]
        finally:
            copy_conn.close()
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)

    if result["pending_versions"]:
        result["verdict"] = VERDICT_WILL_UPGRADE
        result["reason"] = (
            "This profile was exported from an older version of WIMI and "
            "will be upgraded automatically on import."
        )
    return result


# ---------------------------------------------------------------------- import: create new

def install_profile_as_new(
    master_db: MasterDatabase,
    archive_path: str | Path,
    display_name: Optional[str] = None,
    progress_cb: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """
    Import a ``.wimi`` archive as a brand-new profile.

    Flow: validate + extract to temp -> schema preflight -> disk-space check
    -> collision-safe username -> email-collision check -> ``create_user``
    -> copy the archive DB straight into the new slot (deliberately NOT
    calling ``ensure_user_database`` first — that would create an
    empty-schema file) -> copy media into ``media/user_{id}_{username}/``
    -> verify-open with ``UserDatabase`` (auto-migrates older schemas) +
    sanity count -> close.

    ROLLBACK on any failure after user creation: the DB file (+wal/shm),
    media directory, and the registry row (``remove_user_record``) are all
    removed — a failed import leaves zero residue.

    Args:
        master_db: Target master database
        archive_path: Path to the ``.wimi`` archive
        display_name: Optional override for the new profile's display name
        progress_cb: Ignored in v1

    Returns:
        {"user_id", "username", "display_name", "email", "warnings",
         "schema_verdict", "entries", "media_files_copied"}

    Raises:
        ArchiveValidationError: invalid archive (no state changed)
        ProfileImportError: preflight/disk-space failure (no state changed)
            or a mid-import failure (state rolled back)
    """
    del progress_cb  # v1: synchronous, no progress reporting

    info = read_profile_archive(archive_path)
    manifest = info["manifest"]
    manifest_user = manifest.get("user") or {}
    warnings: List[str] = []

    tmp_dir = Path(tempfile.mkdtemp(prefix='wimi_import_'))
    try:
        with zipfile.ZipFile(str(archive_path), 'r') as zf:
            # Entry names were traversal-checked in read_profile_archive.
            zf.extractall(str(tmp_dir))

        db_temp = tmp_dir / DB_MEMBER
        preflight = preflight_schema(db_temp)
        if preflight["verdict"] == VERDICT_NEWER_APP_REQUIRED:
            raise ProfileImportError(preflight["reason"])

        _ensure_disk_space(master_db.users_dir, info["total_uncompressed_bytes"])

        # Collision-safe username within ^[a-zA-Z0-9_-]+$
        requested = manifest_user.get("username")
        base = _sanitize_candidate_username(requested)
        username = _next_free_username(master_db, base)
        if requested and username != requested:
            warnings.append(
                f"Username '{requested}' was taken or invalid — imported as "
                f"'{username}'."
            )

        # Email collision: users.email is UNIQUE — drop it rather than fail.
        email = manifest_user.get("email")
        if email and master_db.email_in_use(email):
            warnings.append(
                f"Email '{email}' is already used by another profile — the "
                f"imported profile has no email set."
            )
            email = None

        user_types = [
            t for t in (manifest_user.get("user_types") or [])
            if t in MasterDatabase.VALID_USER_TYPES
        ] or ['student']
        resolved_display = (
            display_name or manifest_user.get("display_name") or username
        )

        user = master_db.create_user(
            username=username,
            display_name=resolved_display,
            email=email,
            user_types=user_types,
        )

        dest_db = master_db.users_dir / user.database_filename
        media_dest = _media_dir_for(master_db, user.id, user.username)
        verify_db: Optional[UserDatabase] = None
        try:
            # Copy the archive DB into the slot directly — ensure_user_database
            # would create an empty-schema file we'd immediately clobber.
            shutil.copy2(str(db_temp), str(dest_db))

            media_copied = _copy_flat_media(tmp_dir / 'media', media_dest)

            # Verify-open: runs pending migrations for older-schema archives.
            verify_db = UserDatabase(
                db_path=dest_db, user_id=user.id, username=user.username
            )
            row = verify_db.fetchone("SELECT COUNT(*) AS n FROM question_entries")
            entry_count = int(row['n']) if row else 0
            verify_db.close()
            verify_db = None

            expected = (manifest.get("stats") or {}).get("entries")
            if expected is not None and entry_count != expected:
                warnings.append(
                    f"Imported entry count ({entry_count}) differs from the "
                    f"manifest ({expected})."
                )
        except Exception as exc:
            # Rollback: leave zero residue.
            if verify_db is not None:
                try:
                    verify_db.close()
                except Exception:
                    pass
            _remove_db_artifacts(dest_db)
            shutil.rmtree(str(media_dest), ignore_errors=True)
            try:
                master_db.remove_user_record(user.id)
            except Exception:
                pass
            raise ProfileImportError(
                f"Profile import failed and was rolled back: {exc}"
            ) from exc

        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": resolved_display,
            "email": email,
            "warnings": warnings,
            "schema_verdict": preflight["verdict"],
            "entries": entry_count,
            "media_files_copied": media_copied,
        }
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


# ---------------------------------------------------------------------- import: replace existing

def replace_profile(
    master_db: MasterDatabase,
    archive_path: str | Path,
    target_user_id: int,
    active_user_id: Optional[int] = None,
    confirm_replace: bool = False,
    progress_cb: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """
    Replace an existing profile's data with a ``.wimi`` archive's contents.

    Guards: requires ``confirm_replace=True``, and the target must not be
    the currently open profile (``active_user_id``) — switch profiles first.

    Safety net: the target's DB is backed up to
    ``{archive_dir}/pre_replace_{filename}.{ts}.db`` and KEPT on success;
    its media dir is renamed to ``{name}.pre_replace_{ts}`` and DELETED on
    success (media can be gigabytes and this flow repeats). The new DB is
    installed via a ``.importing`` temp file + ``os.replace``. The target
    keeps its username and ``database_filename`` (structural); only
    display_name/email are updated from the manifest.

    ROLLBACK on failure: pure file moves back (DB from the safety backup,
    media dir rename undone) plus a single row UPDATE restoring the
    original display_name/email.

    Args:
        master_db: Master database
        archive_path: Path to the ``.wimi`` archive
        target_user_id: The profile to replace
        active_user_id: The currently open profile's ID, if any
        confirm_replace: Must be True — explicit confirmation flag
        progress_cb: Ignored in v1

    Returns:
        {"user_id", "username", "display_name", "email", "warnings",
         "schema_verdict", "entries", "media_files_copied",
         "backup_db_path"}
    """
    del progress_cb  # v1: synchronous, no progress reporting

    if not confirm_replace:
        raise ProfileImportError(
            "Replacing a profile requires explicit confirmation."
        )
    if active_user_id is not None and int(target_user_id) == int(active_user_id):
        raise ProfileImportError(
            "This profile is currently open — switch to another profile "
            "before replacing it."
        )

    user = master_db.get_user(target_user_id)
    if user is None:
        raise ProfileImportError(f"User {target_user_id} not found")
    if user.account_status != 'active':
        raise ProfileImportError(
            f"Only active profiles can be replaced (status: {user.account_status})."
        )

    info = read_profile_archive(archive_path)
    manifest = info["manifest"]
    manifest_user = manifest.get("user") or {}
    warnings: List[str] = []

    target_db = master_db.users_dir / user.database_filename
    media_dir = _media_dir_for(master_db, user.id, user.username)
    orig_display = user.display_name
    orig_email = user.email

    tmp_dir = Path(tempfile.mkdtemp(prefix='wimi_replace_'))
    backup_db: Optional[Path] = None
    media_backup: Optional[Path] = None
    moved_media = False
    installed_db = False
    row_updated = False
    verify_db: Optional[UserDatabase] = None
    importing = Path(str(target_db) + '.importing')

    try:
        with zipfile.ZipFile(str(archive_path), 'r') as zf:
            zf.extractall(str(tmp_dir))

        db_temp = tmp_dir / DB_MEMBER
        preflight = preflight_schema(db_temp)
        if preflight["verdict"] == VERDICT_NEWER_APP_REQUIRED:
            raise ProfileImportError(preflight["reason"])

        _ensure_disk_space(master_db.users_dir, info["total_uncompressed_bytes"])

        ts = time.strftime('%Y%m%d_%H%M%S')

        try:
            # ---- Safety backups (before any destructive step) ----
            if target_db.exists():
                _checkpoint_wal(target_db)
                backup_db = master_db.archive_dir / (
                    f"pre_replace_{user.database_filename}.{ts}.db"
                )
                counter = 1
                while backup_db.exists():
                    backup_db = master_db.archive_dir / (
                        f"pre_replace_{user.database_filename}.{ts}_{counter}.db"
                    )
                    counter += 1
                shutil.copy2(str(target_db), str(backup_db))

            if media_dir.exists():
                media_backup = media_dir.with_name(
                    media_dir.name + f".pre_replace_{ts}"
                )
                counter = 1
                while media_backup.exists():
                    media_backup = media_dir.with_name(
                        media_dir.name + f".pre_replace_{ts}_{counter}"
                    )
                    counter += 1
                os.rename(str(media_dir), str(media_backup))
                moved_media = True

            # ---- Install the new DB via .importing temp + os.replace ----
            shutil.copy2(str(db_temp), str(importing))
            os.replace(str(importing), str(target_db))
            for suffix in ('-wal', '-shm'):
                stale = Path(str(target_db) + suffix)
                if stale.exists():
                    stale.unlink()
            installed_db = True

            # ---- Media ----
            media_copied = _copy_flat_media(tmp_dir / 'media', media_dir)

            # ---- Row update (keep username/database_filename; they are
            #      structural — baked into the filename and media dir) ----
            new_display = manifest_user.get("display_name") or orig_display
            new_email = manifest_user.get("email")
            if new_email and new_email != orig_email:
                other = master_db.fetchone(
                    "SELECT id FROM users WHERE email = ? AND id != ?",
                    (new_email, user.id),
                )
                if other is not None:
                    warnings.append(
                        f"Email '{new_email}' is already used by another "
                        f"profile — the existing email was kept."
                    )
                    new_email = orig_email
            with master_db.transaction():
                master_db.execute(
                    "UPDATE users SET display_name = ?, email = ? WHERE id = ?",
                    (new_display, new_email, user.id),
                )
            row_updated = True

            # ---- Verify-open (auto-migrates older schemas) ----
            verify_db = UserDatabase(
                db_path=target_db, user_id=user.id, username=user.username
            )
            row = verify_db.fetchone("SELECT COUNT(*) AS n FROM question_entries")
            entry_count = int(row['n']) if row else 0
            verify_db.close()
            verify_db = None

        except Exception as exc:
            # ---- Rollback: pure file moves back + one row UPDATE ----
            if verify_db is not None:
                try:
                    verify_db.close()
                except Exception:
                    pass
            try:
                if importing.exists():
                    importing.unlink()
            except OSError:
                pass
            if installed_db or backup_db is not None:
                _remove_db_artifacts(target_db)
                if backup_db is not None and backup_db.exists():
                    os.replace(str(backup_db), str(target_db))
            if moved_media:
                shutil.rmtree(str(media_dir), ignore_errors=True)
                if media_backup is not None and media_backup.exists():
                    os.rename(str(media_backup), str(media_dir))
            elif media_dir.exists():
                # No pre-existing media dir; remove the one we created.
                shutil.rmtree(str(media_dir), ignore_errors=True)
            if row_updated:
                with master_db.transaction():
                    master_db.execute(
                        "UPDATE users SET display_name = ?, email = ? WHERE id = ?",
                        (orig_display, orig_email, user.id),
                    )
            raise ProfileImportError(
                f"Profile replace failed and was rolled back: {exc}"
            ) from exc

        # ---- Success: media backup is deleted; the DB backup is KEPT ----
        if moved_media and media_backup is not None:
            shutil.rmtree(str(media_backup), ignore_errors=True)

        updated = master_db.get_user(user.id)
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": updated.display_name if updated else new_display,
            "email": updated.email if updated else new_email,
            "warnings": warnings,
            "schema_verdict": preflight["verdict"],
            "entries": entry_count,
            "media_files_copied": media_copied,
            "backup_db_path": str(backup_db) if backup_db else None,
        }
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
