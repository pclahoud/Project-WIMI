"""WIMI Plugin data database operations."""

import json
from typing import Any, Optional

from app_logging import ErrorCategory


class PluginDataMixin:
    """Mixin for plugin data operations. Composed into UserDatabase."""

    def _ensure_plugin_data_table(self) -> None:
        """Create the plugin_data table if it doesn't exist."""
        self.execute("""
            CREATE TABLE IF NOT EXISTS plugin_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plugin_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(plugin_id, key)
            )
        """)

    def get_plugin_data(self, plugin_id: str, key: str) -> Optional[Any]:
        """
        Get a single value for a plugin key.

        Args:
            plugin_id: Plugin identifier
            key: Data key

        Returns:
            Deserialized value, or None if not found
        """
        row = self.fetchone(
            "SELECT value FROM plugin_data WHERE plugin_id = ? AND key = ?",
            (plugin_id, key)
        )
        if not row:
            return None
        try:
            return json.loads(row['value'])
        except (json.JSONDecodeError, TypeError):
            return row['value']

    def get_all_plugin_data(self, plugin_id: str) -> dict:
        """
        Get all key-value pairs for a plugin.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Dict of key -> deserialized value
        """
        rows = self.fetchall(
            "SELECT key, value FROM plugin_data WHERE plugin_id = ?",
            (plugin_id,)
        )
        result = {}
        for row in rows:
            try:
                result[row['key']] = json.loads(row['value'])
            except (json.JSONDecodeError, TypeError):
                result[row['key']] = row['value']
        return result

    def set_plugin_data(self, plugin_id: str, key: str, value: Any) -> None:
        """
        Set a value for a plugin key (upsert).

        Args:
            plugin_id: Plugin identifier
            key: Data key
            value: Value to store (will be JSON-serialized)
        """
        serialized = json.dumps(value)
        with self.transaction():
            self.execute("""
                INSERT INTO plugin_data (plugin_id, key, value, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(plugin_id, key)
                DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """, (plugin_id, key, serialized))

    def delete_plugin_data(self, plugin_id: str, key: str) -> bool:
        """
        Delete a single key for a plugin.

        Args:
            plugin_id: Plugin identifier
            key: Data key

        Returns:
            True if a row was deleted
        """
        with self.transaction():
            cursor = self.execute(
                "DELETE FROM plugin_data WHERE plugin_id = ? AND key = ?",
                (plugin_id, key)
            )
        return cursor.rowcount > 0

    def clear_plugin_data(self, plugin_id: str) -> int:
        """
        Delete all data for a plugin.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Number of rows deleted
        """
        with self.transaction():
            cursor = self.execute(
                "DELETE FROM plugin_data WHERE plugin_id = ?",
                (plugin_id,)
            )
        return cursor.rowcount

    def get_plugin_enabled(self, plugin_id: str) -> bool:
        """
        Check if a plugin is enabled. Defaults to True if no record exists.

        Args:
            plugin_id: Plugin identifier

        Returns:
            True if enabled (or no record), False if explicitly disabled
        """
        val = self.get_plugin_data(plugin_id, '_enabled')
        if val is None:
            return True
        return bool(val)

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        """
        Set whether a plugin is enabled.

        Args:
            plugin_id: Plugin identifier
            enabled: True to enable, False to disable
        """
        self.set_plugin_data(plugin_id, '_enabled', enabled)

    def get_plugin_settings(self, plugin_id: str) -> dict:
        """
        Get plugin settings (stored as a JSON blob under key '_settings').

        Args:
            plugin_id: Plugin identifier

        Returns:
            Settings dict, or empty dict if none stored
        """
        val = self.get_plugin_data(plugin_id, '_settings')
        if isinstance(val, dict):
            return val
        return {}

    def set_plugin_settings(self, plugin_id: str, settings: dict) -> None:
        """
        Save plugin settings as a JSON blob.

        Args:
            plugin_id: Plugin identifier
            settings: Settings dict
        """
        self.set_plugin_data(plugin_id, '_settings', settings)
