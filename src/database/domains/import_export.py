"""WIMI Import/Export database operations."""

from typing import Optional, List


class ImportExportMixin:
    """Mixin for import/export operations. Composed into UserDatabase."""

    def get_saved_delimiters(self) -> List[dict]:
        """Get all saved delimiters ordered by sort_order."""
        rows = self.fetchall(
            "SELECT * FROM saved_delimiters ORDER BY sort_order, id"
        )
        return [dict(row) for row in rows]

    def create_saved_delimiter(self, name: str, value: str, hotkey: str = None) -> dict:
        """
        Create a new saved delimiter.

        Args:
            name: Display name for the delimiter
            value: The delimiter string value
            hotkey: Optional hotkey trigger string

        Returns:
            Created delimiter as dict
        """
        row = self.fetchone(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 as next_order FROM saved_delimiters"
        )
        next_order = row['next_order'] if row else 0

        with self.transaction():
            self.execute("""
                INSERT INTO saved_delimiters (name, value, hotkey, sort_order)
                VALUES (?, ?, ?, ?)
            """, (name, value, hotkey, next_order))

        delimiter_id = self.fetchone("SELECT last_insert_rowid() as id")['id']
        result = self.fetchone("SELECT * FROM saved_delimiters WHERE id = ?", (delimiter_id,))
        return dict(result)

    def delete_saved_delimiter(self, delimiter_id: int) -> bool:
        """
        Delete a saved delimiter.

        Args:
            delimiter_id: Delimiter ID

        Returns:
            True if deleted
        """
        with self.transaction():
            self.execute("DELETE FROM saved_delimiters WHERE id = ?", (delimiter_id,))
        return True

    # ==================== Import Mapping Profiles ====================

    def get_import_mapping_profiles(self) -> List[dict]:
        """Get all import mapping profiles ordered by name."""
        rows = self.fetchall(
            "SELECT * FROM import_mapping_profiles ORDER BY profile_name"
        )
        return [dict(row) for row in rows]

    def create_import_mapping_profile(self, profile_name: str, source_type: str, field_mappings: str) -> dict:
        """
        Create a new import mapping profile.

        Args:
            profile_name: Display name for the profile
            source_type: Source type identifier (e.g., 'amboss', 'uworld', 'custom')
            field_mappings: JSON string of field mappings

        Returns:
            Created profile as dict
        """
        with self.transaction():
            self.execute("""
                INSERT INTO import_mapping_profiles (profile_name, source_type, field_mappings)
                VALUES (?, ?, ?)
            """, (profile_name, source_type, field_mappings))

        profile_id = self.fetchone("SELECT last_insert_rowid() as id")['id']
        result = self.fetchone("SELECT * FROM import_mapping_profiles WHERE id = ?", (profile_id,))
        return dict(result)

    def update_import_mapping_profile(self, profile_id: int, profile_name: str = None,
                                       source_type: str = None, field_mappings: str = None) -> dict:
        """
        Update an import mapping profile.

        Args:
            profile_id: Profile ID
            profile_name: New profile name (optional)
            source_type: New source type (optional)
            field_mappings: New field mappings JSON (optional)

        Returns:
            Updated profile as dict
        """
        updates = []
        params = []
        if profile_name is not None:
            updates.append("profile_name = ?")
            params.append(profile_name)
        if source_type is not None:
            updates.append("source_type = ?")
            params.append(source_type)
        if field_mappings is not None:
            updates.append("field_mappings = ?")
            params.append(field_mappings)

        if not updates:
            result = self.fetchone("SELECT * FROM import_mapping_profiles WHERE id = ?", (profile_id,))
            return dict(result) if result else None

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(profile_id)

        with self.transaction():
            self.execute(
                f"UPDATE import_mapping_profiles SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )

        result = self.fetchone("SELECT * FROM import_mapping_profiles WHERE id = ?", (profile_id,))
        return dict(result) if result else None

    def delete_import_mapping_profile(self, profile_id: int) -> bool:
        """
        Delete an import mapping profile.

        Args:
            profile_id: Profile ID

        Returns:
            True if deleted
        """
        with self.transaction():
            self.execute("DELETE FROM import_mapping_profiles WHERE id = ?", (profile_id,))
        return True
