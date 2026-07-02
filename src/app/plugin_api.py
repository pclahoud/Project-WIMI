"""
WIMI PluginAPI — Scoped facade for plugin access to the database.

Each plugin instance gets its own PluginAPI with permission-gated access.
Read methods are always available. Write methods require explicit permissions.
Delete operations are not exposed to plugins.
"""

import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class PluginAPI:
    """
    Scoped API facade for a single plugin.

    Provides read access (always), permission-gated write access,
    plugin-private key-value storage, and scoped file storage.
    """

    def __init__(self, plugin_id: str, user_db, permissions: List[str],
                 plugin_dir: Optional[Path] = None, media_manager=None):
        self._plugin_id = plugin_id
        self._db = user_db
        self._permissions = set(permissions)
        self._plugin_dir = plugin_dir
        self._media_manager = media_manager

    def _require(self, permission: str):
        """Raise PermissionError if the plugin lacks the given permission."""
        if permission not in self._permissions:
            raise PermissionError(
                f'Plugin "{self._plugin_id}" lacks permission "{permission}"'
            )

    def _model_to_dict(self, obj):
        """Convert a dataclass model to dict, or return as-is if already dict."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, '__dataclass_fields__'):
            return asdict(obj)
        # Fallback: try __dict__
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        return obj

    # =========================================================================
    # Tier 1: Read (always available)
    # =========================================================================

    def get_entry(self, entry_id: int) -> Optional[dict]:
        """Get a single entry by ID with full context."""
        result = self._db.get_entry_with_context(entry_id)
        return result  # already a dict

    def get_entries(self, exam_id: int = None, page: int = 1, per_page: int = 50) -> dict:
        """
        Get paginated entries.

        Args:
            exam_id: Filter by exam context ID
            page: Page number (1-based)
            per_page: Entries per page

        Returns:
            Dict with 'entries' (list of entry dicts) and 'total' (int)
        """
        entries, total = self._db.get_entries_paginated(
            exam_context_id=exam_id,
            page=page,
            per_page=per_page,
        )
        return {
            'entries': [self._model_to_dict(e) for e in entries],
            'total': total,
            'page': page,
            'per_page': per_page,
        }

    def search_entries(self, query: str, exam_id: int = None) -> list:
        """Full-text search entries."""
        entries = self._db.search_entries_fulltext(query, exam_context_id=exam_id)
        return [self._model_to_dict(e) for e in entries]

    def get_sessions(self, exam_id: int = None) -> list:
        """Get review sessions."""
        sessions = self._db.get_review_sessions(exam_context_id=exam_id)
        return [self._model_to_dict(s) for s in sessions]

    def get_session(self, session_id: int) -> Optional[dict]:
        """Get a single session by ID."""
        session = self._db.get_review_session(session_id)
        return self._model_to_dict(session)

    def get_subject_tree(self, exam_id: int) -> list:
        """Get the subject hierarchy for an exam."""
        # get_subject_hierarchy expects exam_context name, but we have an ID
        # Use get_exam_context_config to get the name
        config = self._db.get_exam_context_config(exam_id)
        if not config:
            return []
        nodes = self._db.get_subject_hierarchy(config.exam_name)
        return [self._model_to_dict(n) for n in nodes]

    def get_subject_path(self, subject_id: int) -> str:
        """Get the full path string for a subject node."""
        node = self._db.get_subject_node(subject_id)
        if not node:
            return ''
        return node.full_path if hasattr(node, 'full_path') and node.full_path else node.name

    def search_subjects(self, exam_id: int, query: str) -> list:
        """Search subjects within an exam."""
        results = self._db.search_subjects(exam_id, query)
        return results  # already list of dicts

    def get_tags(self, exam_context_name: str) -> list:
        """Get tags for an exam context."""
        tags = self._db.get_tags_by_exam(exam_context_name)
        return [self._model_to_dict(t) for t in tags]

    def get_entry_media(self, entry_id: int) -> list:
        """Get media attachments for an entry."""
        media = self._db.get_entry_media_list(entry_id)
        return [self._model_to_dict(m) for m in media]

    def get_entry_notes(self, entry_id: int) -> list:
        """Get notes for an entry."""
        notes = self._db.get_entry_notes_list(entry_id)
        return [self._model_to_dict(n) for n in notes]

    def get_exams(self) -> list:
        """Get all exam contexts."""
        # get_all_exam_contexts returns list of ExamContextConfig
        exams = self._db.get_all_exam_contexts()
        return [self._model_to_dict(e) for e in exams]

    def get_exam(self, exam_id: int) -> Optional[dict]:
        """Get a single exam context."""
        config = self._db.get_exam_context_config(exam_id)
        return self._model_to_dict(config)

    def get_overview(self, exam_id: int = None) -> dict:
        """Get analytics overview."""
        return self._db.get_analytics_overview(exam_context_id=exam_id)

    def get_subject_analytics(self, **params) -> list:
        """Get subject analytics."""
        return self._db.get_subject_analytics(**params)

    def get_activity(self, **params) -> list:
        """Get activity over time."""
        return self._db.get_activity_over_time(**params)

    def get_streak(self, exam_id: int = None) -> dict:
        """Get study streak info."""
        return self._db.get_study_streak(exam_context_id=exam_id)

    def get_sources(self, exam_context_name: str = '') -> list:
        """Get question sources."""
        sources = self._db.get_question_sources(
            exam_context=exam_context_name or None
        )
        return [self._model_to_dict(s) for s in sources]

    # =========================================================================
    # Tier 2: Write (permission-gated, return created/updated object)
    # =========================================================================

    def create_entry(self, data: dict) -> dict:
        """Create a new question entry. Requires 'write:entries'."""
        self._require('write:entries')
        entry = self._db.create_question_entry(**data)
        return self._model_to_dict(entry)

    def update_entry(self, entry_id: int, data: dict) -> dict:
        """Update an existing entry. Requires 'write:entries'."""
        self._require('write:entries')
        entry = self._db.update_question_entry(entry_id, **data)
        return self._model_to_dict(entry)

    def create_session(self, data: dict) -> dict:
        """Create a review session. Requires 'write:sessions'."""
        self._require('write:sessions')
        session = self._db.create_review_session(**data)
        return self._model_to_dict(session)

    def add_note(self, entry_id: int, data: dict) -> dict:
        """Add a note to an entry. Requires 'write:notes'."""
        self._require('write:notes')
        note = self._db.add_entry_note(entry_id, **data)
        return self._model_to_dict(note)

    def update_note(self, note_id: int, data: dict) -> dict:
        """Update a note. Requires 'write:notes'."""
        self._require('write:notes')
        note = self._db.update_entry_note(note_id, **data)
        return self._model_to_dict(note)

    def create_goal(self, target: int, **params) -> dict:
        """Create/update weekly goal. Requires 'write:goals'."""
        self._require('write:goals')
        result = self._db.set_weekly_goal(target, **params)
        return result  # already a dict

    def upload_media(self, entry_id: int, base64_data: str, filename: str, mime_type: str) -> dict:
        """
        Upload media to an entry. Requires 'write:media'.

        Args:
            entry_id: Question entry ID to attach media to
            base64_data: Base64-encoded image data (raw base64 or data URL)
            filename: Original filename (e.g., 'card_front.png')
            mime_type: MIME type (image/png, image/jpeg, etc.)

        Returns:
            Full media record dict with id, file_uuid, thumbnail_url, full_url, etc.
            On error, returns {'error': '...'}.
        """
        self._require('write:media')

        if not self._media_manager:
            return {'error': 'Media manager not available'}

        try:
            media_info = self._media_manager.save_media_from_base64(
                entry_id=entry_id,
                base64_data=base64_data,
                original_filename=filename,
                mime_type=mime_type if mime_type else None
            )

            entry_media = self._db.add_entry_media(
                entry_id=entry_id,
                file_uuid=media_info.file_uuid,
                original_filename=media_info.original_filename,
                mime_type=media_info.mime_type,
                file_size_bytes=media_info.file_size
            )

            # Build data URLs for the response
            thumb_url = self._media_manager.get_thumbnail_as_base64(entry_id, media_info.file_uuid) or ''
            full_url = self._media_manager.get_file_as_base64(entry_id, media_info.file_uuid) or ''

            return {
                'id': entry_media.id,
                'file_uuid': media_info.file_uuid,
                'original_filename': media_info.original_filename,
                'user_filename': media_info.user_filename,
                'mime_type': media_info.mime_type,
                'file_size': media_info.file_size,
                'sort_order': entry_media.sort_order,
                'dimension_id': entry_media.dimension_id,
                'linked_subject_ids': entry_media.linked_subject_ids,
                'thumbnail_url': thumb_url,
                'full_url': full_url,
            }

        except ValueError as e:
            return {'error': str(e)}
        except Exception as e:
            logger.error(f'Plugin "{self._plugin_id}" upload_media failed: {e}')
            return {'error': f'Failed to upload media: {e}'}

    # =========================================================================
    # Tier 3: Plugin-private storage (always available)
    # =========================================================================

    def get_data(self, key: str) -> Any:
        """Get a value from plugin-private storage."""
        return self._db.get_plugin_data(self._plugin_id, key)

    def set_data(self, key: str, value: Any) -> None:
        """Set a value in plugin-private storage."""
        self._db.set_plugin_data(self._plugin_id, key, value)

    def get_settings(self) -> dict:
        """Get this plugin's settings."""
        return self._db.get_plugin_settings(self._plugin_id)

    # =========================================================================
    # Tier 4: File storage (requires 'storage' permission)
    # =========================================================================

    def _resolve_storage_path(self, relative_path: str) -> Path:
        """
        Resolve and validate a path within the plugin's data/ directory.

        Raises:
            PermissionError: If plugin lacks 'storage' permission or path escapes sandbox.
            RuntimeError: If plugin has no directory.
            ValueError: If relative_path is empty.
        """
        self._require('storage')
        if not self._plugin_dir:
            raise RuntimeError(f'Plugin "{self._plugin_id}" has no directory')
        if not relative_path or not relative_path.strip():
            raise ValueError('File path must not be empty')

        data_root = (self._plugin_dir / 'data').resolve()
        target = (data_root / relative_path).resolve()

        # Traversal check — resolved path must be inside data_root
        if not (str(target) + os.sep).startswith(str(data_root) + os.sep) and target != data_root:
            raise PermissionError(
                f'Plugin "{self._plugin_id}": path escapes storage directory: {relative_path}'
            )

        return target

    def read_file(self, path: str, binary: bool = False) -> Union[str, bytes, None]:
        """
        Read a file from plugin storage.

        Args:
            path: Relative path within the plugin's data/ directory.
            binary: If True, return bytes. Otherwise return str (UTF-8).

        Returns:
            File contents, or None if the file does not exist.
        """
        target = self._resolve_storage_path(path)
        if not target.exists() or not target.is_file():
            return None
        if binary:
            return target.read_bytes()
        return target.read_text(encoding='utf-8')

    def write_file(self, path: str, content: Union[str, bytes]) -> int:
        """
        Write a file to plugin storage.

        Args:
            path: Relative path within the plugin's data/ directory.
                  Parent directories are created automatically.
            content: String or bytes to write.

        Returns:
            Number of bytes written.
        """
        target = self._resolve_storage_path(path)

        # Create parent directories
        target.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, str):
            encoded = content.encode('utf-8')
            target.write_text(content, encoding='utf-8')
            return len(encoded)
        else:
            target.write_bytes(content)
            return len(content)

    def delete_file(self, path: str) -> bool:
        """
        Delete a file from plugin storage.

        Args:
            path: Relative path within the plugin's data/ directory.

        Returns:
            True if the file was deleted, False if it did not exist.
        """
        target = self._resolve_storage_path(path)
        if not target.exists() or not target.is_file():
            return False
        target.unlink()
        return True

    def list_files(self, subdir: str = '') -> List[str]:
        """
        List files in a subdirectory of plugin storage.

        Args:
            subdir: Relative subdirectory path. Empty string for the root data/ dir.

        Returns:
            List of relative file paths (relative to data/).
        """
        self._require('storage')
        if not self._plugin_dir:
            raise RuntimeError(f'Plugin "{self._plugin_id}" has no directory')

        data_root = (self._plugin_dir / 'data').resolve()
        if subdir:
            target = self._resolve_storage_path(subdir)
        else:
            target = data_root

        if not target.exists() or not target.is_dir():
            return []

        results = []
        for f in target.rglob('*'):
            if f.is_file():
                rel = f.relative_to(data_root)
                results.append(str(rel).replace(os.sep, '/'))
        return sorted(results)

    def file_exists(self, path: str) -> bool:
        """
        Check if a file exists in plugin storage.

        Args:
            path: Relative path within the plugin's data/ directory.

        Returns:
            True if the file exists.
        """
        target = self._resolve_storage_path(path)
        return target.exists() and target.is_file()

