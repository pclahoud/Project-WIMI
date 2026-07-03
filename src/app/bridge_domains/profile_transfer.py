"""WIMI Profile transfer bridge operations (.wimi export/import).

Thin bridge wrapper around ``app.profile_archive`` — the Qt-free engine
that builds, validates and installs ``.wimi`` profile archives. Dialog
slots are split from work slots (session-import pattern) so headless
regression tests can drive the work slots with plain path params.

All slots are master-DB-backed and work with ``self.user_db is None``
(the profile picker runs before any user database is attached).
"""
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response
from app.profile_archive import (
    DB_MEMBER,
    DISK_SPACE_SAFETY_FACTOR,
    ProfileArchiveError,
    build_profile_archive,
    install_profile_as_new,
    preflight_schema,
    read_profile_archive,
    replace_profile,
    # Same-feature private helpers: the preview's collision report must
    # match exactly what install_profile_as_new will do on import.
    _next_free_username,
    _sanitize_candidate_username,
)

ARCHIVE_SUFFIX = '.wimi'


class ProfileTransferBridgeMixin:
    """Bridge mixin for profile export/import. Composed into DatabaseBridge."""

    # ==================== Helpers (not slots) ====================

    def _count_db_media_references(self, db_path: Path) -> int:
        """Count entry_media rows in an extracted archive DB (0 on any error)."""
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute("SELECT COUNT(*) FROM entry_media").fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except sqlite3.Error:
            return 0

    # ==================== Dialog slots ====================

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def openProfileExportDialog(self, params_json: str) -> str:
        """Open a native save dialog for a ``.wimi`` export destination.

        Args:
            params_json: JSON object with optional ``default_filename``

        Returns:
            JSON response with {file_path} or data=None if cancelled
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            params = json.loads(params_json) if params_json else {}
            if not isinstance(params, dict):
                raise ValueError('params must be a JSON object')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid export dialog params: {e}')

        default_filename = str(params.get('default_filename') or '')

        try:
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getSaveFileName(
                None,
                "Export WIMI Profile",
                default_filename,
                "WIMI Profile (*.wimi)"
            )
            if not file_path:
                return serialize_response(True, data=None)
            if not file_path.lower().endswith(ARCHIVE_SUFFIX):
                file_path += ARCHIVE_SUFFIX
            return serialize_response(True, data={'file_path': file_path})
        except Exception as e:
            self._log_error(f'openProfileExportDialog failed: {e}')
            return serialize_response(False, error=f'Failed to open save dialog: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def openProfileImportDialog(self) -> str:
        """Open a native file dialog for selecting a ``.wimi`` archive.

        Returns:
            JSON response with {file_path} or data=None if cancelled
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            from PyQt6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                None,
                "Import WIMI Profile",
                "",
                "WIMI Profile (*.wimi *.zip);;All Files (*)"
            )
            if not file_path:
                return serialize_response(True, data=None)
            return serialize_response(True, data={'file_path': file_path})
        except Exception as e:
            # openProfileImportDialog takes no params.
            self._log_error(f'openProfileImportDialog failed: {e}')
            return serialize_response(False, error=f'Failed to open file dialog: {e}')

    # ==================== Work slots ====================

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def exportProfile(self, params_json: str) -> str:
        """Export a profile to a ``.wimi`` archive.

        Args:
            params_json: JSON object {user_id, include_media?, dest_path}

        Returns:
            JSON response with {archive_path, media_files, total_bytes, stats}
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            params = json.loads(params_json)
            if not isinstance(params, dict):
                raise ValueError('params must be a JSON object')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid export params: {e}')

        user_id = params.get('user_id')
        dest_path = params.get('dest_path')
        include_media = bool(params.get('include_media'))
        if not isinstance(user_id, int):
            return serialize_response(False, error='Export requires a numeric user_id')
        if not dest_path:
            return serialize_response(False, error='Export requires a dest_path')

        try:
            # build_profile_archive always snapshots the on-disk DB via
            # sqlite3 Connection.backup() — WAL-safe even while the profile
            # is the currently open one, so no live-connection branch needed.
            result = build_profile_archive(
                self.master_db,
                user_id,
                dest_path,
                include_media=include_media,
            )
            manifest = result['manifest']
            archive_path = result['dest_path']
            return serialize_response(True, data={
                'archive_path': archive_path,
                'media_files': manifest['media']['file_count'],
                'total_bytes': Path(archive_path).stat().st_size,
                'stats': manifest['stats'],
            })
        except ProfileArchiveError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'exportProfile failed: {e}', {'user_id': user_id})
            return serialize_response(False, error=f'Failed to export profile: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def readProfileArchive(self, file_path: str) -> str:
        """Validate a ``.wimi`` archive and build the import-preview payload.

        Args:
            file_path: Path to the ``.wimi`` archive

        Returns:
            JSON response with:
            - manifest: the full archive manifest
            - schema: {archive_version, local_version, verdict, reason,
              pending_versions}
            - media: {included, file_count, total_bytes, db_references_media}
            - collision: {username_exists, suggested_username}
            - replace_targets: active profiles [{user_id, username,
              display_name, is_current}]
            - required_bytes, free_bytes
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            info = read_profile_archive(file_path)
            manifest = info['manifest']
            manifest_user = manifest.get('user') or {}
            manifest_media = manifest.get('media') or {}

            # Schema preflight needs the archive DB on disk — extract just
            # user.db to a temp dir, preflight, count media references,
            # then clean up.
            tmp_dir = Path(tempfile.mkdtemp(prefix='wimi_preview_'))
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    zf.extract(DB_MEMBER, str(tmp_dir))
                db_temp = tmp_dir / DB_MEMBER
                preflight = preflight_schema(db_temp)
                db_references_media = self._count_db_media_references(db_temp)
            finally:
                shutil.rmtree(str(tmp_dir), ignore_errors=True)

            # Collision preview — mirrors install_profile_as_new exactly.
            base = _sanitize_candidate_username(manifest_user.get('username'))
            username_exists = self.master_db.get_user_by_username(base) is not None
            suggested_username = _next_free_username(self.master_db, base)

            current_user_id = self._current_user_id()
            replace_targets = [
                {
                    'user_id': u.id,
                    'username': u.username,
                    'display_name': u.display_name,
                    'is_current': u.id == current_user_id,
                }
                for u in self.master_db.get_all_users(account_status='active')
            ]

            required_bytes = int(
                info['total_uncompressed_bytes'] * DISK_SPACE_SAFETY_FACTOR
            )
            free_bytes = shutil.disk_usage(str(self.master_db.users_dir)).free

            return serialize_response(True, data={
                'path': info['path'],
                'manifest': manifest,
                'schema': {
                    'archive_version': preflight['archive_max_version'],
                    'local_version': preflight['local_max_version'],
                    'verdict': preflight['verdict'],
                    'reason': preflight['reason'],
                    'pending_versions': preflight['pending_versions'],
                },
                'media': {
                    'included': bool(
                        manifest_media.get('included', info['has_media'])
                    ),
                    'file_count': info['media_file_count'],
                    'total_bytes': info['media_total_bytes'],
                    'db_references_media': db_references_media > 0,
                },
                'collision': {
                    'username_exists': username_exists,
                    'suggested_username': suggested_username,
                },
                'replace_targets': replace_targets,
                'required_bytes': required_bytes,
                'free_bytes': free_bytes,
            })
        except ProfileArchiveError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'readProfileArchive failed: {e}', {'file_path': file_path})
            return serialize_response(False, error=f'Failed to read profile archive: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def executeProfileImport(self, params_json: str) -> str:
        """Import a ``.wimi`` archive as a new profile or over an existing one.

        Args:
            params_json: JSON object {archive_path, mode: 'create'|'replace',
                target_user_id?, confirm_replace?, display_name?}

        Returns:
            JSON response with {user_id, username, display_name, mode,
            media_files_restored, warnings, entries, schema_verdict}
            (+ backup_db_path for replace mode)
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            params = json.loads(params_json)
            if not isinstance(params, dict):
                raise ValueError('params must be a JSON object')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid import params: {e}')

        archive_path = params.get('archive_path')
        mode = params.get('mode')
        if not archive_path:
            return serialize_response(False, error='Import requires an archive_path')
        if mode not in ('create', 'replace'):
            return serialize_response(
                False, error="Import mode must be 'create' or 'replace'"
            )

        active_user_id = (
            self.user_db.user_id if self.user_db is not None else None
        )

        try:
            if mode == 'create':
                result = install_profile_as_new(
                    self.master_db,
                    archive_path,
                    display_name=params.get('display_name'),
                )
            else:
                target_user_id = params.get('target_user_id')
                if not isinstance(target_user_id, int):
                    return serialize_response(
                        False, error='Replace mode requires a numeric target_user_id'
                    )
                result = replace_profile(
                    self.master_db,
                    archive_path,
                    target_user_id=target_user_id,
                    active_user_id=active_user_id,
                    confirm_replace=bool(params.get('confirm_replace')),
                )

            data = {
                'user_id': result['user_id'],
                'username': result['username'],
                'display_name': result['display_name'],
                'mode': mode,
                'media_files_restored': result['media_files_copied'],
                'warnings': result['warnings'],
                'entries': result['entries'],
                'schema_verdict': result['schema_verdict'],
            }
            if mode == 'replace':
                data['backup_db_path'] = result.get('backup_db_path')
            return serialize_response(True, data=data)
        # ArchiveValidationError and ProfileImportError both subclass
        # ProfileArchiveError — all three carry user-friendly messages.
        except ProfileArchiveError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'executeProfileImport failed: {e}',
                {'archive_path': archive_path, 'mode': mode},
            )
            return serialize_response(False, error=f'Failed to import profile: {e}')
