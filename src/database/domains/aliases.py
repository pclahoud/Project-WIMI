"""WIMI Aliases database operations."""

from typing import Optional, List, Dict, Any, Tuple
from ..base_db import DatabaseIntegrityError
from ..exceptions import ValidationError, SubjectNodeError
from ..models import SubjectNode, SubjectAlias
from app_logging import ErrorCategory


class AliasesMixin:
    """Mixin for alias operations. Composed into UserDatabase."""

    def create_subject_alias(
        self,
        subject_node_id: int,
        exam_context: str,
        alias_name: str,
        alias_type: str = 'alternate_name',
        is_primary: bool = False,
        notes: Optional[str] = None
    ) -> SubjectAlias:
        """
        Create a new alias for a subject node.

        Args:
            subject_node_id: ID of the subject node
            exam_context: Exam context name (for scoping)
            alias_name: The alias name/term
            alias_type: Type of alias ('eponym', 'acronym', 'alternate_name', 'colloquial')
            is_primary: Whether this is the primary/preferred alias
            notes: Optional notes about the alias

        Returns:
            Created SubjectAlias object

        Raises:
            ValidationError: If alias_type is invalid
            SubjectNodeError: If subject node doesn't exist or alias already exists
        """
        # Validate alias type
        if alias_type not in SubjectAlias.VALID_ALIAS_TYPES:
            raise ValidationError(
                f"Invalid alias type: {alias_type}. Must be one of {SubjectAlias.VALID_ALIAS_TYPES}"
            )

        # Verify subject node exists
        node = self.get_subject_node(subject_node_id)
        if not node:
            raise SubjectNodeError(f"Subject node {subject_node_id} not found")

        try:
            with self.transaction():
                cursor = self.execute("""
                    INSERT INTO subject_aliases (
                        subject_node_id, exam_context, alias_name, alias_type, is_primary, notes
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (subject_node_id, exam_context, alias_name.strip(), alias_type, is_primary, notes))

                alias_id = cursor.lastrowid

                if hasattr(self, 'error_logger') and self.error_logger:
                    self.error_logger.debug(
                        f"Created alias '{alias_name}' for subject {subject_node_id}",
                        category=ErrorCategory.DATABASE
                    )

                return self.get_subject_alias(alias_id)

        except DatabaseIntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise SubjectNodeError(
                    f"Alias '{alias_name}' already exists for this subject"
                ) from e
            raise

    def get_subject_alias(self, alias_id: int) -> Optional[SubjectAlias]:
        """Get a subject alias by ID"""
        row = self.fetchone(
            "SELECT * FROM subject_aliases WHERE id = ?",
            (alias_id,)
        )
        return SubjectAlias.from_db_row(row)

    def get_aliases_for_subject(self, subject_node_id: int) -> List[SubjectAlias]:
        """
        Get all aliases for a specific subject node.

        Args:
            subject_node_id: ID of the subject node

        Returns:
            List of SubjectAlias objects
        """
        rows = self.fetchall("""
            SELECT * FROM subject_aliases
            WHERE subject_node_id = ?
            ORDER BY is_primary DESC, alias_type, alias_name
        """, (subject_node_id,))

        return [SubjectAlias.from_db_row(row) for row in rows]

    def get_aliases_for_exam(self, exam_context: str) -> List[SubjectAlias]:
        """
        Get all aliases for an exam context.

        Args:
            exam_context: Exam context name

        Returns:
            List of SubjectAlias objects
        """
        rows = self.fetchall("""
            SELECT * FROM subject_aliases
            WHERE exam_context = ?
            ORDER BY subject_node_id, is_primary DESC, alias_name
        """, (exam_context,))

        return [SubjectAlias.from_db_row(row) for row in rows]

    def update_subject_alias(
        self,
        alias_id: int,
        alias_name: Optional[str] = None,
        alias_type: Optional[str] = None,
        is_primary: Optional[bool] = None,
        notes: Optional[str] = None
    ) -> Optional[SubjectAlias]:
        """
        Update a subject alias.

        Args:
            alias_id: ID of the alias to update
            alias_name: New alias name (optional)
            alias_type: New alias type (optional)
            is_primary: New primary status (optional)
            notes: New notes (optional, pass empty string to clear)

        Returns:
            Updated SubjectAlias object, or None if not found

        Raises:
            ValidationError: If alias_type is invalid
        """
        # Validate alias type if provided
        if alias_type is not None and alias_type not in SubjectAlias.VALID_ALIAS_TYPES:
            raise ValidationError(
                f"Invalid alias type: {alias_type}. Must be one of {SubjectAlias.VALID_ALIAS_TYPES}"
            )

        # Build update query
        updates = []
        params = []

        if alias_name is not None:
            updates.append("alias_name = ?")
            params.append(alias_name.strip())
        if alias_type is not None:
            updates.append("alias_type = ?")
            params.append(alias_type)
        if is_primary is not None:
            updates.append("is_primary = ?")
            params.append(is_primary)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes if notes else None)

        if not updates:
            return self.get_subject_alias(alias_id)

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(alias_id)

        query = f"""
            UPDATE subject_aliases
            SET {', '.join(updates)}
            WHERE id = ?
        """

        try:
            with self.transaction():
                self.execute(query, tuple(params))

            return self.get_subject_alias(alias_id)

        except DatabaseIntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise SubjectNodeError(
                    f"Alias '{alias_name}' already exists for this subject"
                ) from e
            raise

    def delete_subject_alias(self, alias_id: int) -> bool:
        """
        Delete a subject alias.

        Args:
            alias_id: ID of the alias to delete

        Returns:
            True if deleted, False if not found
        """
        with self.transaction():
            cursor = self.execute(
                "DELETE FROM subject_aliases WHERE id = ?",
                (alias_id,)
            )
            return cursor.rowcount > 0

    def check_alias_conflicts(
        self,
        exam_context: str,
        alias_name: str,
        exclude_subject_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Check for existing subjects with the same or similar alias.

        This is used to warn users about potential duplicates when creating aliases.
        The check is case-insensitive.

        Args:
            exam_context: Exam context to search in
            alias_name: Alias name to check
            exclude_subject_id: Optionally exclude a subject from the results

        Returns:
            List of dicts with subject info that have conflicting aliases
        """
        alias_lower = alias_name.strip().lower()

        # Find exact alias matches (case-insensitive)
        if exclude_subject_id:
            rows = self.fetchall("""
                SELECT sa.*, sn.name as subject_name
                FROM subject_aliases sa
                JOIN subject_nodes sn ON sa.subject_node_id = sn.id
                WHERE sa.exam_context = ?
                AND LOWER(sa.alias_name) = ?
                AND sa.subject_node_id != ?
            """, (exam_context, alias_lower, exclude_subject_id))
        else:
            rows = self.fetchall("""
                SELECT sa.*, sn.name as subject_name
                FROM subject_aliases sa
                JOIN subject_nodes sn ON sa.subject_node_id = sn.id
                WHERE sa.exam_context = ?
                AND LOWER(sa.alias_name) = ?
            """, (exam_context, alias_lower))

        conflicts = []
        for row in rows:
            conflicts.append({
                'alias_id': row['id'],
                'alias_name': row['alias_name'],
                'alias_type': row['alias_type'],
                'subject_node_id': row['subject_node_id'],
                'subject_name': row['subject_name']
            })

        # Also check if alias matches a subject name exactly
        if exclude_subject_id:
            name_rows = self.fetchall("""
                SELECT id, name FROM subject_nodes
                WHERE exam_context = ?
                AND LOWER(name) = ?
                AND id != ?
                AND status = 'active'
            """, (exam_context, alias_lower, exclude_subject_id))
        else:
            name_rows = self.fetchall("""
                SELECT id, name FROM subject_nodes
                WHERE exam_context = ?
                AND LOWER(name) = ?
                AND status = 'active'
            """, (exam_context, alias_lower))

        for row in name_rows:
            conflicts.append({
                'alias_id': None,
                'alias_name': row['name'],
                'alias_type': 'subject_name',
                'subject_node_id': row['id'],
                'subject_name': row['name']
            })

        return conflicts

    def increment_alias_usage(self, alias_id: int) -> None:
        """
        Increment the usage count for an alias.

        Called when an alias is used in a search to track popularity.

        Args:
            alias_id: ID of the alias
        """
        self.execute("""
            UPDATE subject_aliases
            SET usage_count = usage_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (alias_id,))
        self.conn.commit()

    def get_all_subjects_with_aliases_for_exam(
        self,
        exam_context: str
    ) -> List[Dict[str, Any]]:
        """
        Get all subjects for an exam with their aliases.

        This is optimized for initializing the client-side fuzzy search index
        with alias support. Returns a flat list suitable for Fuse.js.

        Args:
            exam_context: Exam context name

        Returns:
            List of subject dicts with 'aliases' and 'aliasesString' fields
        """
        # Get all subjects
        all_subjects = []

        def collect_subjects(nodes, parent_path=''):
            for node in nodes:
                current_path = f"{parent_path} > {node.name}" if parent_path else node.name

                # Get aliases for this subject
                aliases = self.get_aliases_for_subject(node.id)
                aliases_list = [a.alias_name for a in aliases]

                all_subjects.append({
                    'id': node.id,
                    'name': node.name,
                    'path': current_path,
                    'level_type': node.level_type,
                    'weight': node.exam_weight_low or 0,
                    'aliases': [a.to_dict() for a in aliases],
                    'aliasesString': ' | '.join(aliases_list) if aliases_list else ''
                })

                if node.children:
                    collect_subjects(node.children, current_path)

        root_nodes = self.get_subject_hierarchy(exam_context)
        collect_subjects(root_nodes)

        return all_subjects

    def create_subject_with_aliases(
        self,
        exam_context: str,
        name: str,
        level_type: str,
        parent_id: Optional[int] = None,
        aliases: Optional[List[Dict[str, str]]] = None,
        **kwargs
    ) -> Tuple[SubjectNode, List[SubjectAlias]]:
        """
        Create a subject node with optional aliases in a single transaction.

        This is a convenience method for creating a subject with its aliases
        atomically, typically used in the quick-add subject modal.

        Args:
            exam_context: Exam context name
            name: Subject name
            level_type: Hierarchy level type
            parent_id: Parent node ID (optional)
            aliases: List of alias dicts with 'name' and optional 'type'
            **kwargs: Additional args for create_subject_node

        Returns:
            Tuple of (created SubjectNode, list of created SubjectAlias objects)
        """
        with self.transaction():
            # Create the subject node
            node = self.create_subject_node(
                exam_context=exam_context,
                name=name,
                level_type=level_type,
                parent_id=parent_id,
                **kwargs
            )

            # Create aliases if provided
            created_aliases = []
            if aliases:
                for alias_data in aliases:
                    alias_name = alias_data.get('name', '').strip()
                    if alias_name:
                        alias = self.create_subject_alias(
                            subject_node_id=node.id,
                            exam_context=exam_context,
                            alias_name=alias_name,
                            alias_type=alias_data.get('type', 'alternate_name'),
                            notes=alias_data.get('notes')
                        )
                        created_aliases.append(alias)

            return node, created_aliases
