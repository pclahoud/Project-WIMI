"""WIMI Multi-dimensional analysis database operations."""

import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, date, timedelta
from ..base_db import DatabaseIntegrityError
from ..exceptions import ValidationError
from app_logging import ErrorCategory

logger = logging.getLogger('wimi.graph')


class DimensionsMixin:
    """Mixin providing multi-dimensional analysis database operations."""

    def create_dimension(
        self,
        exam_id: int,
        name: str,
        display_order: int,
        is_required: bool = True,
        allow_multiple: bool = False,
        description: Optional[str] = None
    ) -> int:
        """
        Create a new dimension for an exam.

        Dimensions are independent categories for classifying questions in
        multi-dimensional exams (e.g., Site of Care, Physician Task, System).

        Args:
            exam_id (int): ID of the exam context (from exam_contexts table)
            name (str): Dimension name (e.g., "Site of Care")
            display_order (int): UI ordering (1, 2, 3, ...)
            is_required (bool): Must tag in this dimension? Default True
            allow_multiple (bool): Allow multiple selections? Default False
            description (str, optional): Help text for users

        Returns:
            int: dimension_id of the created dimension

        Raises:
            sqlite3.IntegrityError: If dimension name or display_order already
                                    exists for this exam
            sqlite3.IntegrityError: If exam_id does not exist

        Example:
            >>> dimension_id = db.create_dimension(
            ...     exam_id=5,
            ...     name="Site of Care",
            ...     display_order=1,
            ...     is_required=True,
            ...     description="Where the patient encounter occurs"
            ... )
            >>> print(dimension_id)
            1
        """
        cursor = self.execute("""
            INSERT INTO exam_dimensions (
                exam_id, name, display_order, is_required, allow_multiple, description
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (exam_id, name, display_order, int(is_required), int(allow_multiple), description))

        self.conn.commit()
        dimension_id = cursor.lastrowid

        # Dual-write to graph database
        def _graph_write():
            self._graph_execute(
                "MERGE (d:Dimension {sqlite_id: $id}) SET d.name = $name",
                {"id": dimension_id, "name": name}
            )
            self._graph_execute(
                "MATCH (ec:ExamContext {sqlite_id: $ecid}), (d:Dimension {sqlite_id: $did}) "
                "MERGE (ec)-[:HAS_DIMENSION]->(d)",
                {"ecid": exam_id, "did": dimension_id}
            )
        self._dual_write_graph("create_dimension", _graph_write)

        if hasattr(self, 'error_logger') and self.error_logger:
            self.error_logger.debug(
                f"Created dimension '{name}' (ID: {dimension_id}) for exam {exam_id}",
                category='DATABASE'
            )

        return dimension_id

    def get_exam_dimensions(self, exam_id: int) -> List[Dict[str, Any]]:
        """
        Get all dimensions for an exam, ordered by display_order.

        Args:
            exam_id (int): ID of the exam context

        Returns:
            list: List of dimension dicts with keys:
                  - id, exam_id, name, display_order, is_required,
                    allow_multiple, description, created_at

        Example:
            >>> dimensions = db.get_exam_dimensions(exam_id=5)
            >>> for dim in dimensions:
            ...     print(f"{dim['display_order']}. {dim['name']}")
            1. Site of Care
            2. Physician Task
            3. System
        """
        cursor = self.conn.execute("""
            SELECT id, exam_id, name, display_order, is_required,
                   allow_multiple, description, created_at
            FROM exam_dimensions
            WHERE exam_id = ?
            ORDER BY display_order ASC
        """, (exam_id,))

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        return [dict(zip(columns, row)) for row in rows]

    def get_dimension(self, dimension_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a single dimension by ID.

        Args:
            dimension_id (int): ID of the dimension

        Returns:
            dict or None: Dimension dict with all fields, or None if not found

        Example:
            >>> dim = db.get_dimension(dimension_id=1)
            >>> if dim:
            ...     print(f"Dimension: {dim['name']}")
            Dimension: Site of Care
        """
        cursor = self.conn.execute("""
            SELECT id, exam_id, name, display_order, is_required,
                   allow_multiple, description, created_at
            FROM exam_dimensions
            WHERE id = ?
        """, (dimension_id,))

        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

    def update_dimension(
        self,
        dimension_id: int,
        name: Optional[str] = None,
        display_order: Optional[int] = None,
        is_required: Optional[bool] = None,
        allow_multiple: Optional[bool] = None,
        description: Optional[str] = None
    ) -> int:
        """
        Update dimension properties. Only updates provided fields.

        Args:
            dimension_id (int): ID of dimension to update
            name (str, optional): New name
            display_order (int, optional): New display order
            is_required (bool, optional): New is_required value
            allow_multiple (bool, optional): New allow_multiple value
            description (str, optional): New description

        Returns:
            int: Number of rows affected (1 if success, 0 if not found)

        Raises:
            sqlite3.IntegrityError: If new name or display_order conflicts
                                    with existing dimension in same exam

        Example:
            >>> rows = db.update_dimension(
            ...     dimension_id=1,
            ...     name="Clinical Setting",
            ...     description="Updated help text"
            ... )
            >>> print(f"Updated {rows} row(s)")
            Updated 1 row(s)
        """
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if display_order is not None:
            updates.append("display_order = ?")
            params.append(display_order)
        if is_required is not None:
            updates.append("is_required = ?")
            params.append(int(is_required))
        if allow_multiple is not None:
            updates.append("allow_multiple = ?")
            params.append(int(allow_multiple))
        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if not updates:
            return 0

        params.append(dimension_id)
        cursor = self.execute(f"""
            UPDATE exam_dimensions
            SET {', '.join(updates)}
            WHERE id = ?
        """, tuple(params))

        self.conn.commit()

        # Dual-write to graph database
        def _graph_write():
            if name is not None:
                self._graph_execute(
                    "MATCH (d:Dimension {sqlite_id: $id}) SET d.name = $name",
                    {"id": dimension_id, "name": name}
                )
        self._dual_write_graph("update_dimension", _graph_write)

        return cursor.rowcount

    def delete_dimension(self, dimension_id: int) -> int:
        """
        Delete a dimension. Cascades to delete all tags in that dimension.

        WARNING: This will also delete all question_hierarchy_tags entries
        for this dimension due to the foreign key CASCADE constraint.

        Args:
            dimension_id (int): ID of dimension to delete

        Returns:
            int: Number of rows affected (1 if success, 0 if not found)

        Note:
            This operation is irreversible. All tags in this dimension
            will be permanently deleted.

        Example:
            >>> rows = db.delete_dimension(dimension_id=3)
            >>> print(f"Deleted {rows} dimension(s)")
            Deleted 1 dimension(s)
        """
        cursor = self.execute("""
            DELETE FROM exam_dimensions WHERE id = ?
        """, (dimension_id,))

        self.conn.commit()

        # Dual-write to graph database
        if cursor.rowcount > 0:
            def _graph_write():
                self._graph_execute(
                    "MATCH (d:Dimension {sqlite_id: $id}) DETACH DELETE d",
                    {"id": dimension_id}
                )
            self._dual_write_graph("delete_dimension", _graph_write)

        if cursor.rowcount > 0 and hasattr(self, 'error_logger') and self.error_logger:
            self.error_logger.info(
                f"Deleted dimension {dimension_id} and its tags",
                category='DATABASE'
            )

        return cursor.rowcount

    # ==================== Tag CRUD Methods ====================

    def create_hierarchy_tag(
        self,
        entry_id: int,
        hierarchy_id: int,
        dimension_id: int
    ) -> int:
        """
        Tag a question entry with a hierarchy node in a specific dimension.

        This creates a link between a question entry and a hierarchy node,
        within the context of a specific dimension.

        Args:
            entry_id (int): ID of the question entry (from question_entries table)
            hierarchy_id (int): ID of the hierarchy node (from subject_nodes table)
            dimension_id (int): ID of the dimension (from exam_dimensions table)

        Returns:
            int: tag_id of the created tag

        Raises:
            sqlite3.IntegrityError: If tag already exists (same entry + dimension + hierarchy)
            sqlite3.IntegrityError: If entry_id, hierarchy_id, or dimension_id don't exist

        Example:
            >>> tag_id = db.create_hierarchy_tag(
            ...     entry_id=123,
            ...     hierarchy_id=45,  # "Emergency Department"
            ...     dimension_id=1    # "Site of Care"
            ... )
            >>> print(f"Created tag with ID: {tag_id}")
            Created tag with ID: 1
        """
        cursor = self.execute("""
            INSERT INTO question_hierarchy_tags (entry_id, hierarchy_id, dimension_id)
            VALUES (?, ?, ?)
        """, (entry_id, hierarchy_id, dimension_id))

        self.conn.commit()
        return cursor.lastrowid

    def get_entry_tags(self, entry_id: int) -> List[Dict[str, Any]]:
        """
        Get all tags for a question entry, with dimension and hierarchy names.

        Returns tags ordered by dimension display_order, allowing consistent
        display of tags across the UI.

        Args:
            entry_id (int): ID of the question entry

        Returns:
            list: List of tag dicts with keys:
                  - id, entry_id, hierarchy_id, dimension_id, tagged_at
                  - dimension_name (from exam_dimensions join)
                  - hierarchy_name (from subject_nodes join)

        Example:
            >>> tags = db.get_entry_tags(entry_id=123)
            >>> for tag in tags:
            ...     print(f"{tag['dimension_name']}: {tag['hierarchy_name']}")
            Site of Care: Emergency Department
            Physician Task: Diagnosis
            System: Cardiovascular
        """
        cursor = self.conn.execute("""
            SELECT
                qht.id,
                qht.entry_id,
                qht.hierarchy_id,
                qht.dimension_id,
                qht.tagged_at,
                d.name as dimension_name,
                h.name as hierarchy_name
            FROM question_hierarchy_tags qht
            JOIN exam_dimensions d ON qht.dimension_id = d.id
            JOIN subject_nodes h ON qht.hierarchy_id = h.id
            WHERE qht.entry_id = ?
            ORDER BY d.display_order ASC
        """, (entry_id,))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_tags_by_dimension(self, exam_id: int, dimension_id: int) -> List[Dict[str, Any]]:
        """
        Get all tags for a specific dimension across all entries in an exam.

        Useful for analytics to see how questions are distributed across
        hierarchy nodes within a dimension.

        Args:
            exam_id (int): ID of the exam context
            dimension_id (int): ID of the dimension

        Returns:
            list: List of tag dicts with entry and hierarchy info

        Example:
            >>> tags = db.get_tags_by_dimension(exam_id=5, dimension_id=1)
            >>> # Count entries per hierarchy node
            >>> from collections import Counter
            >>> counts = Counter(t['hierarchy_name'] for t in tags)
            >>> print(counts)
            Counter({'Emergency': 45, 'Inpatient': 30, 'Ambulatory': 25})
        """
        cursor = self.conn.execute("""
            SELECT
                qht.id,
                qht.entry_id,
                qht.hierarchy_id,
                qht.dimension_id,
                qht.tagged_at,
                h.name as hierarchy_name
            FROM question_hierarchy_tags qht
            JOIN subject_nodes h ON qht.hierarchy_id = h.id
            JOIN question_entries qe ON qht.entry_id = qe.id
            JOIN review_sessions rs ON qe.review_session_id = rs.id
            WHERE rs.exam_context_id = ? AND qht.dimension_id = ?
            ORDER BY qht.tagged_at DESC
        """, (exam_id, dimension_id))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def delete_hierarchy_tag(self, tag_id: int) -> int:
        """
        Delete a single hierarchy tag.

        Args:
            tag_id (int): ID of the tag to delete

        Returns:
            int: Number of rows affected (1 if success, 0 if not found)

        Example:
            >>> rows = db.delete_hierarchy_tag(tag_id=1)
            >>> print(f"Deleted {rows} tag(s)")
            Deleted 1 tag(s)
        """
        cursor = self.execute("""
            DELETE FROM question_hierarchy_tags WHERE id = ?
        """, (tag_id,))

        self.conn.commit()
        return cursor.rowcount

    def delete_entry_tags_by_dimension(self, entry_id: int, dimension_id: int) -> int:
        """
        Delete all tags for a question entry in a specific dimension.

        This is useful when a user changes their selection for a dimension,
        allowing the old selection(s) to be removed before adding new one(s).

        Args:
            entry_id (int): ID of the question entry
            dimension_id (int): ID of the dimension

        Returns:
            int: Number of rows affected

        Example:
            >>> # User wants to change from "Emergency" to "Inpatient"
            >>> deleted = db.delete_entry_tags_by_dimension(entry_id=123, dimension_id=1)
            >>> print(f"Removed {deleted} old tag(s)")
            Removed 1 old tag(s)
            >>> # Now add the new tag
            >>> db.create_hierarchy_tag(entry_id=123, hierarchy_id=46, dimension_id=1)
        """
        cursor = self.execute("""
            DELETE FROM question_hierarchy_tags
            WHERE entry_id = ? AND dimension_id = ?
        """, (entry_id, dimension_id))

        self.conn.commit()
        return cursor.rowcount

    # ==================== Detection Method ====================

    def exam_uses_dimensions(self, exam_id: int) -> bool:
        """
        Determine if an exam uses the multi-dimensional system.

        Simple exams (SAT, GRE) don't have dimensions and use single-path
        hierarchies. Complex exams (NBME, USMLE) have dimensions defined.

        This method is used to determine which UI and logic paths to use
        when displaying and managing questions for an exam.

        Args:
            exam_id (int): ID of the exam context

        Returns:
            bool: True if exam has dimensions (multi-dimensional),
                  False if no dimensions (simple hierarchy)

        Example:
            >>> # Check if NBME Surgery exam uses dimensions
            >>> if db.exam_uses_dimensions(exam_id=5):
            ...     print("Multi-dimensional exam - show dimension selectors")
            ... else:
            ...     print("Simple exam - show standard hierarchy picker")
            Multi-dimensional exam - show dimension selectors
        """
        cursor = self.conn.execute("""
            SELECT COUNT(*) FROM exam_dimensions WHERE exam_id = ?
        """, (exam_id,))

        count = cursor.fetchone()[0]
        return count > 0

    # ==================== Convenience Methods ====================

    def get_entry_tags_by_dimension(self, entry_id: int) -> Dict[int, List[Dict[str, Any]]]:
        """
        Get all tags for an entry, grouped by dimension.

        Args:
            entry_id (int): ID of the question entry

        Returns:
            dict: Dictionary mapping dimension_id to list of tags for that dimension

        Example:
            >>> tags_by_dim = db.get_entry_tags_by_dimension(entry_id=123)
            >>> for dim_id, tags in tags_by_dim.items():
            ...     print(f"Dimension {dim_id}: {len(tags)} tags")
            Dimension 1: 1 tags
            Dimension 2: 1 tags
            Dimension 3: 1 tags
        """
        tags = self.get_entry_tags(entry_id)

        grouped = {}
        for tag in tags:
            dim_id = tag['dimension_id']
            if dim_id not in grouped:
                grouped[dim_id] = []
            grouped[dim_id].append(tag)

        return grouped

    def validate_entry_dimensions_complete(
        self,
        entry_id: int,
        exam_id: int
    ) -> Dict[str, Any]:
        """
        Validate that an entry has all required dimension tags.

        Args:
            entry_id (int): ID of the question entry
            exam_id (int): ID of the exam context

        Returns:
            dict: Validation result with keys:
                  - is_complete (bool): True if all required dimensions are tagged
                  - missing_dimensions (list): List of missing required dimension IDs
                  - tagged_dimensions (list): List of tagged dimension IDs

        Example:
            >>> result = db.validate_entry_dimensions_complete(entry_id=123, exam_id=5)
            >>> if result['is_complete']:
            ...     print("All required dimensions are tagged!")
            >>> else:
            ...     print(f"Missing: {result['missing_dimensions']}")
        """
        dimensions = self.get_exam_dimensions(exam_id)
        entry_tags = self.get_entry_tags(entry_id)

        tagged_dim_ids = {tag['dimension_id'] for tag in entry_tags}
        required_dim_ids = {d['id'] for d in dimensions if d['is_required']}

        missing = required_dim_ids - tagged_dim_ids

        return {
            'is_complete': len(missing) == 0,
            'missing_dimensions': list(missing),
            'tagged_dimensions': list(tagged_dim_ids)
        }

    def get_hierarchy_nodes_by_dimension(
        self,
        exam_id: int,
        dimension_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get all hierarchy nodes (subject_nodes) that belong to a specific dimension.

        This is useful for populating dimension-specific hierarchy pickers in the UI.

        Args:
            exam_id (int): ID of the exam context
            dimension_id (int): ID of the dimension

        Returns:
            list: List of subject node dicts filtered by dimension

        Note:
            Nodes are filtered by dimension_id column in subject_nodes.
            Nodes with dimension_id = NULL are legacy (simple hierarchy) nodes.
        """
        cursor = self.conn.execute("""
            SELECT * FROM subject_nodes
            WHERE exam_context = (
                SELECT exam_name FROM exam_contexts WHERE id = ?
            ) AND dimension_id = ?
            AND status = 'active'
            ORDER BY sort_order, name
        """, (exam_id, dimension_id))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # =========================================================================
    # PHASE 7.4-7.6: MULTI-DIMENSIONAL ANALYTICS
    # =========================================================================

    # -------------------------------------------------------------------------
    # Hierarchy Aggregation Helpers
    # -------------------------------------------------------------------------

    def _aggregate_hierarchy_counts(
        self,
        nodes_with_direct_counts: List[Dict[str, Any]],
        count_field: str = 'direct_count'
    ) -> Dict[int, int]:
        """
        Aggregate direct counts up through the hierarchy using bottom-up traversal.

        This method takes a list of nodes with their direct counts and calculates
        the total count for each node (including all descendants). Useful for
        dashboard views where we need aggregated stats for all nodes at once.

        Polyhierarchy migration (POLYHIERARCHY_MIGRATION.md §5.2):
        children/parents are sourced from ``subject_edges`` rather than
        ``subject_nodes.parent_id``. A node with multiple parents in
        ``subject_edges`` will contribute its count to each parent's
        rollup; this matches the OMOP "honest non-additivity" pattern
        documented in §5.3 of the plan. The legacy fallback uses the
        per-row ``parent_id`` field if ``subject_edges`` doesn't exist.

        Args:
            nodes_with_direct_counts: List of dicts, each containing:
                - 'id': node ID (int)
                - 'parent_id': parent node ID (int or None for roots)
                  — used as a legacy fallback only.
                - count_field: the direct count for this node (int)
            count_field: Name of the field containing direct counts (default: 'direct_count')

        Returns:
            Dict mapping node_id -> total_count (including all descendants)

        Example:
            nodes = [
                {'id': 1, 'parent_id': None, 'direct_count': 5},
                {'id': 2, 'parent_id': 1, 'direct_count': 10},
                {'id': 3, 'parent_id': 1, 'direct_count': 15},
            ]
            totals = db._aggregate_hierarchy_counts(nodes)
            # totals = {1: 30, 2: 10, 3: 15}
        """
        from collections import defaultdict

        if not nodes_with_direct_counts:
            return {}

        # Build lookup structures
        nodes = {n['id']: n for n in nodes_with_direct_counts}
        node_ids = list(nodes.keys())

        children = defaultdict(list)
        # Cache parent lookups (used for depth and for legacy fallback)
        node_parents: Dict[int, List[int]] = {nid: [] for nid in node_ids}

        edges_available = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subject_edges'"
        ) is not None

        # Source-of-truth selection: per node, prefer subject_edges if
        # it has any rows for that node (polyhierarchy-aware). Fall back
        # to the per-row ``parent_id`` field for nodes without any
        # corresponding edges (legacy single-parent shape, or callers
        # that pass synthetic node lists not backed by real DB rows).
        edge_parents: Dict[int, List[int]] = defaultdict(list)
        if edges_available and node_ids:
            placeholders = ','.join(['?'] * len(node_ids))
            edge_rows = self.fetchall(
                f"""
                SELECT parent_id, child_id
                FROM subject_edges
                WHERE child_id IN ({placeholders})
                """,
                tuple(node_ids),
            )
            for er in edge_rows:
                pid = er['parent_id']
                cid = er['child_id']
                edge_parents[cid].append(pid)

        for n in nodes_with_direct_counts:
            cid = n['id']
            pids_from_edges = [p for p in edge_parents.get(cid, []) if p in nodes]
            if pids_from_edges:
                # Edges win: a node listed in subject_edges has its
                # complete parent set there, not in the per-row field.
                # De-dup defensively (UNIQUE(parent_id, child_id) makes
                # this impossible from the table side, but trim anyway).
                seen = set()
                for pid in pids_from_edges:
                    if pid in seen:
                        continue
                    seen.add(pid)
                    children[pid].append(cid)
                    node_parents.setdefault(cid, []).append(pid)
            else:
                # No edges for this child — use the per-row parent_id
                # field (legacy single-parent shape; or synthetic-data
                # tests that pass node lists not backed by DB rows).
                pid = n.get('parent_id')
                if pid is not None and pid in nodes:
                    children[pid].append(cid)
                    node_parents.setdefault(cid, []).append(pid)

        # Calculate depths for topological ordering (bottom-up processing).
        # In a DAG, depth is the longest path from any root to this node.
        depth_memo: Dict[int, int] = {}

        def get_depth(node_id: int, in_progress: Optional[set] = None) -> int:
            if node_id in depth_memo:
                return depth_memo[node_id]
            if node_id not in nodes:
                return -1
            if in_progress is None:
                in_progress = set()
            if node_id in in_progress:
                # Cycle defense — treat as root.
                return 0
            in_progress = in_progress | {node_id}
            parents_for_node = node_parents.get(node_id, [])
            # Filter parents that aren't in our node set (orphan-rooted)
            relevant_parents = [p for p in parents_for_node if p in nodes]
            if not relevant_parents:
                depth_memo[node_id] = 0
            else:
                depth_memo[node_id] = max(
                    get_depth(p, in_progress) for p in relevant_parents
                ) + 1
            return depth_memo[node_id]

        # Calculate depth for all nodes
        for nid in node_ids:
            get_depth(nid)

        # Bottom-up aggregation: process deepest nodes first.
        # When a node has multiple parents, both parents' totals
        # accumulate the same descendant subtree — that's the OMOP
        # "honest non-additivity" pattern (sums of siblings may exceed
        # the parent because shared descendants count once per parent).
        totals: Dict[int, int] = {}
        for node_id in sorted(node_ids, key=lambda x: -depth_memo.get(x, 0)):
            direct = nodes[node_id].get(count_field, 0) or 0
            # Distinct child set under this parent (a child can technically
            # appear twice in `children[parent]` if duplicate edges exist;
            # dedup defensively).
            distinct_children = set(children.get(node_id, []))
            child_sum = sum(totals.get(cid, 0) for cid in distinct_children)
            totals[node_id] = direct + child_sum

        return totals

    # -------------------------------------------------------------------------
    # Dimension Analytics Methods
    # -------------------------------------------------------------------------

    def get_dimension_performance(
        self,
        exam_context_id: int,
        dimension_id: int,
        include_children: bool = True
    ) -> Dict[str, Any]:
        """
        Aggregate performance by hierarchy nodes within one dimension.

        Args:
            exam_context_id: ID of the exam context
            dimension_id: ID of the dimension to analyze
            include_children: If True, aggregate counts from child nodes (default: True)

        Returns:
            Dict with dimension_name, nodes array with stats, and total count.
            Each node includes:
            - direct_entries: entries mapped directly to this node
            - total_entries: entries mapped to this node OR any descendant
            - percentage: based on total_entries
        """
        # Get dimension info
        dimension = self.get_dimension(dimension_id)
        if not dimension:
            return {'dimension_name': '', 'nodes': [], 'total': 0}

        # Get nodes in this dimension with their DIRECT entry counts
        # Also fetch parent_id for hierarchy aggregation
        cursor = self.conn.execute("""
            SELECT
                sn.id as hierarchy_id,
                sn.name,
                sn.parent_id,
                COUNT(DISTINCT esm.question_entry_id) as direct_entries,
                ROUND(AVG(qe.perceived_difficulty), 2) as avg_difficulty
            FROM subject_nodes sn
            LEFT JOIN entry_subject_mappings esm ON esm.subject_node_id = sn.id
            LEFT JOIN question_entries qe ON qe.id = esm.question_entry_id
            WHERE sn.exam_context = (
                SELECT exam_name FROM exam_contexts WHERE id = ?
            )
            AND sn.dimension_id = ?
            AND sn.status = 'active'
            GROUP BY sn.id, sn.name, sn.parent_id
            ORDER BY direct_entries DESC
        """, (exam_context_id, dimension_id))

        # Build node list with direct counts
        nodes_data = []
        for row in cursor.fetchall():
            nodes_data.append({
                'id': row[0],
                'parent_id': row[2],
                'direct_count': row[3] or 0,
                'name': row[1],
                'avg_difficulty': row[4] or 0
            })

        # Aggregate counts up through hierarchy if requested
        if include_children and nodes_data:
            totals = self._aggregate_hierarchy_counts(nodes_data, count_field='direct_count')
        else:
            totals = {n['id']: n['direct_count'] for n in nodes_data}

        # Build final node list with both direct and total counts
        nodes = []
        grand_total = 0
        for node_data in nodes_data:
            node_id = node_data['id']
            direct = node_data['direct_count']
            total = totals.get(node_id, direct)
            grand_total += direct  # Sum of direct counts (no double counting)
            nodes.append({
                'hierarchy_id': node_id,
                'name': node_data['name'],
                'direct_entries': direct,
                'total_entries': total,
                'avg_difficulty': node_data['avg_difficulty']
            })

        # Sort by total_entries descending
        nodes.sort(key=lambda x: x['total_entries'], reverse=True)

        # Calculate percentages based on total_entries
        # Use sum of all total_entries for percentage base (accounts for hierarchy)
        total_for_percentage = sum(n['total_entries'] for n in nodes if n['total_entries'] > 0)
        for node in nodes:
            node['percentage'] = round(
                (node['total_entries'] / total_for_percentage * 100), 1
            ) if total_for_percentage > 0 else 0

        return {
            'dimension_name': dimension['name'],
            'dimension_id': dimension_id,
            'nodes': nodes,
            'total': grand_total  # Total unique entries (direct count sum)
        }

    def get_subject_hierarchy_with_mistakes_by_dimension(
        self,
        exam_context_id: int,
        dimension_id: int
    ) -> Dict[str, Any]:
        """
        Get hierarchical data for sunburst filtered by dimension.

        Args:
            exam_context_id: ID of the exam context
            dimension_id: ID of the dimension to filter by

        Returns:
            Hierarchical dict structure suitable for D3 sunburst
        """
        dimension = self.get_dimension(dimension_id)
        if not dimension:
            return {'name': 'Root', 'children': [], 'value': 0}

        # Get all nodes in this dimension
        # Uses entry_subject_mappings which links entries to subjects
        cursor = self.conn.execute("""
            SELECT
                sn.id,
                sn.name,
                sn.parent_id,
                COUNT(DISTINCT esm.question_entry_id) as direct_mistakes
            FROM subject_nodes sn
            LEFT JOIN entry_subject_mappings esm ON esm.subject_node_id = sn.id
            WHERE sn.exam_context = (
                SELECT exam_name FROM exam_contexts WHERE id = ?
            )
            AND sn.dimension_id = ?
            AND sn.status = 'active'
            GROUP BY sn.id
            ORDER BY sn.sort_order, sn.name
        """, (exam_context_id, dimension_id))

        nodes = {}
        for row in cursor.fetchall():
            nodes[row[0]] = {
                'id': row[0],
                'name': row[1],
                'parent_id': row[2],
                'direct_mistakes': row[3] or 0,
                'children': []
            }

        # Build tree structure
        root_nodes = []
        for node_id, node in nodes.items():
            parent_id = node['parent_id']
            if parent_id and parent_id in nodes:
                nodes[parent_id]['children'].append(node)
            else:
                root_nodes.append(node)

        def calculate_value(node):
            """Calculate total value including children"""
            total = node['direct_mistakes']
            for child in node['children']:
                total += calculate_value(child)
            node['value'] = total
            return total

        total_value = 0
        for root in root_nodes:
            total_value += calculate_value(root)

        return {
            'name': dimension['name'],
            'children': root_nodes,
            'value': total_value
        }

    def get_cross_dimension_performance(
        self,
        exam_context_id: int,
        dimension_a_id: int,
        dimension_b_id: int,
        min_entries: int = 1,
        level_type_a: Optional[str] = None,
        level_type_b: Optional[str] = None,
        parent_node_a_id: Optional[int] = None,
        parent_node_b_id: Optional[int] = None,
        include_children: bool = True
    ) -> Dict[str, Any]:
        """
        Get 2D matrix of performance at dimension intersections.

        When include_children=True (default), entries tagged to descendant nodes
        are aggregated into their ancestor display-level cells using recursive
        CTEs. Each entry is counted once per (root_a, root_b) pair via DISTINCT
        deduplication. This matches single-dimension include_children behavior.

        Args:
            exam_context_id: ID of the exam context
            dimension_a_id: First dimension ID (rows)
            dimension_b_id: Second dimension ID (columns)
            min_entries: Minimum entries for cell to be included
            level_type_a: Filter dimension A nodes by hierarchy level (e.g., 'System', 'Subsystem')
            level_type_b: Filter dimension B nodes by hierarchy level
            parent_node_a_id: Filter dimension A to children of this node (drill-down)
            parent_node_b_id: Filter dimension B to children of this node (drill-down)
            include_children: If True, aggregate descendant entries into parent cells

        Returns:
            Dict with dimension info and matrix data
        """
        dim_a = self.get_dimension(dimension_a_id)
        dim_b = self.get_dimension(dimension_b_id)

        if not dim_a or not dim_b:
            return {'dimension_a': None, 'dimension_b': None, 'matrix': [], 'total': 0}

        if include_children:
            cursor = self._cross_dimension_query_with_children(
                dimension_a_id, dimension_b_id,
                level_type_a, level_type_b,
                parent_node_a_id, parent_node_b_id,
                min_entries
            )
        else:
            cursor = self._cross_dimension_query_direct(
                dimension_a_id, dimension_b_id,
                level_type_a, level_type_b,
                parent_node_a_id, parent_node_b_id,
                min_entries
            )

        matrix = []
        total = 0
        for row in cursor.fetchall():
            count = row[4] or 0
            total += count
            matrix.append({
                'dim_a_hierarchy_id': row[0],
                'dim_a_value': row[1],
                'dim_b_hierarchy_id': row[2],
                'dim_b_value': row[3],
                'count': count,
                'avg_difficulty': row[5] or 0
            })

        # Get filtered dimension values for the response
        dim_a_nodes = self._get_filtered_dimension_nodes(
            exam_context_id, dimension_a_id, level_type_a, parent_node_a_id
        )
        dim_b_nodes = self._get_filtered_dimension_nodes(
            exam_context_id, dimension_b_id, level_type_b, parent_node_b_id
        )

        return {
            'dimension_a': {
                'id': dimension_a_id,
                'name': dim_a['name'],
                'values': [{'id': n['id'], 'name': n['name']} for n in dim_a_nodes],
                'level_type': level_type_a,
                'parent_node_id': parent_node_a_id
            },
            'dimension_b': {
                'id': dimension_b_id,
                'name': dim_b['name'],
                'values': [{'id': n['id'], 'name': n['name']} for n in dim_b_nodes],
                'level_type': level_type_b,
                'parent_node_id': parent_node_b_id
            },
            'matrix': matrix,
            'total': total,
            'min_entries': min_entries,
            'include_children': include_children
        }

    def _cross_dimension_query_direct(
        self,
        dimension_a_id: int,
        dimension_b_id: int,
        level_type_a: Optional[str],
        level_type_b: Optional[str],
        parent_node_a_id: Optional[int],
        parent_node_b_id: Optional[int],
        min_entries: int
    ):
        """Direct-mapping cross-dimension query (no descendant aggregation)."""
        where_a_parts = ["sn_a.dimension_id = ?"]
        where_b_parts = ["sn_b.dimension_id = ?"]
        params_a = [dimension_a_id]
        params_b = [dimension_b_id]

        if level_type_a:
            where_a_parts.append("sn_a.level_type = ?")
            params_a.append(level_type_a)
        if level_type_b:
            where_b_parts.append("sn_b.level_type = ?")
            params_b.append(level_type_b)

        if parent_node_a_id is not None:
            where_a_parts.append("sn_a.parent_id = ?")
            params_a.append(parent_node_a_id)
        if parent_node_b_id is not None:
            where_b_parts.append("sn_b.parent_id = ?")
            params_b.append(parent_node_b_id)

        params = params_a + params_b + [min_entries]
        where_a_clause = " AND ".join(where_a_parts)
        where_b_clause = " AND ".join(where_b_parts)

        return self.conn.execute(f"""
            SELECT
                esm_a.subject_node_id as dim_a_hierarchy_id,
                sn_a.name as dim_a_value,
                esm_b.subject_node_id as dim_b_hierarchy_id,
                sn_b.name as dim_b_value,
                COUNT(DISTINCT esm_a.question_entry_id) as count,
                ROUND(AVG(qe.perceived_difficulty), 2) as avg_difficulty
            FROM entry_subject_mappings esm_a
            INNER JOIN entry_subject_mappings esm_b ON esm_a.question_entry_id = esm_b.question_entry_id
            INNER JOIN subject_nodes sn_a ON sn_a.id = esm_a.subject_node_id AND {where_a_clause}
            INNER JOIN subject_nodes sn_b ON sn_b.id = esm_b.subject_node_id AND {where_b_clause}
            INNER JOIN question_entries qe ON qe.id = esm_a.question_entry_id
            WHERE sn_a.status = 'active' AND sn_b.status = 'active'
            GROUP BY esm_a.subject_node_id, esm_b.subject_node_id
            HAVING COUNT(DISTINCT esm_a.question_entry_id) >= ?
        """, tuple(params))

    def _cross_dimension_query_with_children(
        self,
        dimension_a_id: int,
        dimension_b_id: int,
        level_type_a: Optional[str],
        level_type_b: Optional[str],
        parent_node_a_id: Optional[int],
        parent_node_b_id: Optional[int],
        min_entries: int
    ):
        """Cross-dimension query with recursive descendant aggregation."""
        # Build seed WHERE clauses for each dimension's CTE
        seed_a_parts = ["sn.dimension_id = ?", "sn.status = 'active'"]
        seed_b_parts = ["sn.dimension_id = ?", "sn.status = 'active'"]
        params_a = [dimension_a_id]
        params_b = [dimension_b_id]

        if level_type_a:
            seed_a_parts.append("sn.level_type = ?")
            params_a.append(level_type_a)
        if level_type_b:
            seed_b_parts.append("sn.level_type = ?")
            params_b.append(level_type_b)

        if parent_node_a_id is not None:
            seed_a_parts.append("sn.parent_id = ?")
            params_a.append(parent_node_a_id)
        if parent_node_b_id is not None:
            seed_b_parts.append("sn.parent_id = ?")
            params_b.append(parent_node_b_id)

        seed_a_clause = " AND ".join(seed_a_parts)
        seed_b_clause = " AND ".join(seed_b_parts)

        # Params order: seed_a params, seed_b params, min_entries
        params = params_a + params_b + [min_entries]

        # Polyhierarchy migration: traverse via subject_edges (junction
        # table) instead of subject_nodes.parent_id. Use UNION (not
        # UNION ALL) defensively to prevent infinite loops on accidental
        # data cycles. Cross-dimensional polyhierarchy is OUT OF SCOPE
        # for this migration (§2 plan); the dual-CTE shape and
        # dimension_id filter on the seed are preserved unchanged. The
        # outer aggregation deduplicates entries via DISTINCT in
        # matched_entries so a leaf reachable through multiple paths
        # within a single dimension only counts once per (root_a, root_b)
        # bucket.
        return self.conn.execute(f"""
            WITH RECURSIVE
            dim_a_tree AS (
                SELECT sn.id as root_id, sn.id as descendant_id
                FROM subject_nodes sn
                WHERE {seed_a_clause}
                UNION
                SELECT t.root_id, child.id
                FROM dim_a_tree t
                JOIN subject_edges se ON se.parent_id = t.descendant_id
                JOIN subject_nodes child ON child.id = se.child_id
                WHERE child.status = 'active'
            ),
            dim_b_tree AS (
                SELECT sn.id as root_id, sn.id as descendant_id
                FROM subject_nodes sn
                WHERE {seed_b_clause}
                UNION
                SELECT t.root_id, child.id
                FROM dim_b_tree t
                JOIN subject_edges se ON se.parent_id = t.descendant_id
                JOIN subject_nodes child ON child.id = se.child_id
                WHERE child.status = 'active'
            ),
            matched_entries AS (
                SELECT DISTINCT ta.root_id as root_a, tb.root_id as root_b,
                                esm_a.question_entry_id as entry_id
                FROM entry_subject_mappings esm_a
                INNER JOIN dim_a_tree ta ON esm_a.subject_node_id = ta.descendant_id
                INNER JOIN entry_subject_mappings esm_b
                    ON esm_a.question_entry_id = esm_b.question_entry_id
                INNER JOIN dim_b_tree tb ON esm_b.subject_node_id = tb.descendant_id
            )
            SELECT
                me.root_a as dim_a_hierarchy_id, sn_a.name as dim_a_value,
                me.root_b as dim_b_hierarchy_id, sn_b.name as dim_b_value,
                COUNT(DISTINCT me.entry_id) as count,
                ROUND(AVG(qe.perceived_difficulty), 2) as avg_difficulty
            FROM matched_entries me
            INNER JOIN subject_nodes sn_a ON sn_a.id = me.root_a
            INNER JOIN subject_nodes sn_b ON sn_b.id = me.root_b
            INNER JOIN question_entries qe ON qe.id = me.entry_id
            GROUP BY me.root_a, me.root_b
            HAVING COUNT(DISTINCT me.entry_id) >= ?
        """, tuple(params))
        # TODO (P2.5): Graph switchover deferred for _cross_dimension_query_with_children.
        # This complex aggregation (dual CTE + GROUP BY + HAVING) needs a
        # dedicated graph query with careful testing before it can be switched.
        # SQLite remains primary for now.

    def _get_filtered_dimension_nodes(
        self,
        exam_context_id: int,
        dimension_id: int,
        level_type: Optional[str] = None,
        parent_node_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get dimension nodes with optional level_type and parent filtering.

        Args:
            exam_context_id: ID of the exam context
            dimension_id: ID of the dimension
            level_type: Optional filter by hierarchy level (e.g., 'System')
            parent_node_id: Optional filter to children of this node

        Returns:
            List of filtered subject node dicts
        """
        where_parts = [
            "exam_context = (SELECT exam_name FROM exam_contexts WHERE id = ?)",
            "dimension_id = ?",
            "status = 'active'"
        ]
        params = [exam_context_id, dimension_id]

        if level_type:
            where_parts.append("level_type = ?")
            params.append(level_type)

        if parent_node_id is not None:
            where_parts.append("parent_id = ?")
            params.append(parent_node_id)

        where_clause = " AND ".join(where_parts)

        cursor = self.conn.execute(f"""
            SELECT id, name, parent_id, level_type
            FROM subject_nodes
            WHERE {where_clause}
            ORDER BY sort_order, name
        """, tuple(params))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_dimension_nodes(
        self,
        exam_context_id: int,
        dimension_id: int,
        level_type: Optional[str] = None,
        parent_node_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Public wrapper for _get_filtered_dimension_nodes.
        Used by scope dropdown to list parent-level nodes."""
        return self._get_filtered_dimension_nodes(
            exam_context_id, dimension_id, level_type, parent_node_id
        )

    def get_hierarchy_levels_for_dimension(
        self,
        exam_context_id: int,
        dimension_id: int
    ) -> Dict[str, Any]:
        """
        Get available hierarchy levels for a dimension with counts.

        This helps populate level selector dropdowns in the UI.

        Args:
            exam_context_id: ID of the exam context
            dimension_id: ID of the dimension

        Returns:
            Dict with dimension info and levels array:
            {
                'dimension_id': int,
                'dimension_name': str,
                'levels': [
                    {'level_type': 'System', 'count': 27, 'depth': 0},
                    {'level_type': 'Subsystem', 'count': 214, 'depth': 1},
                    ...
                ]
            }
        """
        dimension = self.get_dimension(dimension_id)
        if not dimension:
            return {'dimension_id': dimension_id, 'dimension_name': '', 'levels': []}

        # Get distinct level_types with counts
        cursor = self.conn.execute("""
            SELECT
                level_type,
                COUNT(*) as count
            FROM subject_nodes
            WHERE exam_context = (SELECT exam_name FROM exam_contexts WHERE id = ?)
            AND dimension_id = ?
            AND status = 'active'
            GROUP BY level_type
            ORDER BY
                CASE level_type
                    WHEN 'System' THEN 0
                    WHEN 'Subsystem' THEN 1
                    WHEN 'Topic' THEN 2
                    WHEN 'Subtopic' THEN 3
                    WHEN 'Child' THEN 4
                    ELSE 5
                END
        """, (exam_context_id, dimension_id))

        levels = []
        for idx, row in enumerate(cursor.fetchall()):
            levels.append({
                'level_type': row[0],
                'count': row[1],
                'depth': idx
            })

        return {
            'dimension_id': dimension_id,
            'dimension_name': dimension['name'],
            'levels': levels
        }

    def get_intersection_entries(
        self,
        exam_context_id: int,
        hierarchy_a_id: int,
        dimension_a_id: int,
        hierarchy_b_id: int,
        dimension_b_id: int,
        limit: int = 50,
        include_children: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get entries at specific dimension intersection for drill-down.

        Graph-primary (P2.5): uses graph for entry ID retrieval, then fetches
        full entry content from SQLite.

        Args:
            exam_context_id: ID of the exam context
            hierarchy_a_id: Hierarchy node ID in dimension A
            dimension_a_id: Dimension A ID
            hierarchy_b_id: Hierarchy node ID in dimension B
            dimension_b_id: Dimension B ID
            limit: Maximum entries to return
            include_children: If True, include entries tagged to descendant nodes

        Returns:
            List of entry dicts at this intersection
        """
        # Try graph first for entry ID retrieval (P2.5)
        # Only trust non-empty results — empty could mean unpopulated graph edges
        if getattr(self, '_graph_read_ready', False):
            try:
                graph_ids = self._graph_get_intersection_entries(
                    hierarchy_a_id, hierarchy_b_id, include_children,
                )
                if graph_ids:
                    # Fetch full entry content from SQLite using graph-provided IDs
                    placeholders = ','.join(['?'] * len(graph_ids))
                    cursor = self.conn.execute(f"""
                        SELECT DISTINCT
                            qe.id,
                            qe.user_answer,
                            qe.correct_answer,
                            qe.reflection,
                            qe.perceived_difficulty,
                            qe.created_at,
                            rs.session_name
                        FROM question_entries qe
                        LEFT JOIN review_sessions rs ON rs.id = qe.review_session_id
                        WHERE qe.id IN ({placeholders})
                        ORDER BY qe.created_at DESC
                        LIMIT ?
                    """, tuple(graph_ids) + (limit,))
                    columns = [desc[0] for desc in cursor.description]
                    return [dict(zip(columns, row)) for row in cursor.fetchall()]
            except Exception as e:
                logger.warning("Graph read failed for get_intersection_entries, falling back to SQLite: %s", e)

        # SQLite fallback
        if include_children:
            # Polyhierarchy migration: descend via subject_edges with
            # UNION dedup. Both inner CTEs walk the junction table; the
            # outer SELECT keeps DISTINCT on qe.id so a leaf reachable
            # through multiple paths still only counts once.
            query = f"""
                WITH RECURSIVE descendants_a AS (
                    SELECT id FROM subject_nodes WHERE id = ? AND status = 'active'
                    UNION
                    SELECT sn.id FROM subject_nodes sn
                    JOIN subject_edges se ON se.child_id = sn.id
                    JOIN descendants_a d ON se.parent_id = d.id
                    WHERE sn.status = 'active'
                ),
                descendants_b AS (
                    SELECT id FROM subject_nodes WHERE id = ? AND status = 'active'
                    UNION
                    SELECT sn.id FROM subject_nodes sn
                    JOIN subject_edges se ON se.child_id = sn.id
                    JOIN descendants_b d ON se.parent_id = d.id
                    WHERE sn.status = 'active'
                )
                SELECT DISTINCT
                    qe.id,
                    qe.user_answer,
                    qe.correct_answer,
                    qe.reflection,
                    qe.perceived_difficulty,
                    qe.created_at,
                    rs.session_name
                FROM question_entries qe
                INNER JOIN entry_subject_mappings esm_a ON esm_a.question_entry_id = qe.id
                INNER JOIN entry_subject_mappings esm_b ON esm_b.question_entry_id = qe.id
                INNER JOIN subject_nodes sn_a ON sn_a.id = esm_a.subject_node_id AND sn_a.dimension_id = ?
                INNER JOIN subject_nodes sn_b ON sn_b.id = esm_b.subject_node_id AND sn_b.dimension_id = ?
                LEFT JOIN review_sessions rs ON rs.id = qe.review_session_id
                WHERE esm_a.subject_node_id IN (SELECT id FROM descendants_a)
                AND esm_b.subject_node_id IN (SELECT id FROM descendants_b)
                ORDER BY qe.created_at DESC
                LIMIT ?
            """
            cursor = self.conn.execute(
                query,
                (hierarchy_a_id, hierarchy_b_id, dimension_a_id, dimension_b_id, limit)
            )
        else:
            cursor = self.conn.execute("""
                SELECT DISTINCT
                    qe.id,
                    qe.user_answer,
                    qe.correct_answer,
                    qe.reflection,
                    qe.perceived_difficulty,
                    qe.created_at,
                    rs.session_name
                FROM question_entries qe
                INNER JOIN entry_subject_mappings esm_a ON esm_a.question_entry_id = qe.id
                INNER JOIN entry_subject_mappings esm_b ON esm_b.question_entry_id = qe.id
                INNER JOIN subject_nodes sn_a ON sn_a.id = esm_a.subject_node_id AND sn_a.dimension_id = ?
                INNER JOIN subject_nodes sn_b ON sn_b.id = esm_b.subject_node_id AND sn_b.dimension_id = ?
                LEFT JOIN review_sessions rs ON rs.id = qe.review_session_id
                WHERE esm_a.subject_node_id = ?
                AND esm_b.subject_node_id = ?
                ORDER BY qe.created_at DESC
                LIMIT ?
            """, (dimension_a_id, dimension_b_id, hierarchy_a_id, hierarchy_b_id, limit))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_triple_dimension_performance(
        self,
        exam_context_id: int,
        dim_a_id: int,
        dim_b_id: int,
        dim_c_id: int,
        min_entries: int = 1,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get ranked 3-way dimension combinations (weakest first).

        Note: This method counts DIRECT mappings only. Entries tagged to child
        nodes are not aggregated to parent nodes. This keeps the analysis focused
        on specific topic combinations rather than broad category overlaps.

        Args:
            exam_context_id: ID of the exam context
            dim_a_id: First dimension ID
            dim_b_id: Second dimension ID
            dim_c_id: Third dimension ID
            min_entries: Minimum entries for combination to be included
            limit: Maximum combinations to return

        Returns:
            List of 3-way combinations ranked by count (highest first)
        """
        # Uses entry_subject_mappings to find entries with subjects in all three dimensions
        cursor = self.conn.execute("""
            SELECT
                sn_a.name as dim_a_value,
                sn_b.name as dim_b_value,
                sn_c.name as dim_c_value,
                esm_a.subject_node_id as dim_a_hierarchy_id,
                esm_b.subject_node_id as dim_b_hierarchy_id,
                esm_c.subject_node_id as dim_c_hierarchy_id,
                COUNT(DISTINCT esm_a.question_entry_id) as count,
                ROUND(AVG(qe.perceived_difficulty), 2) as avg_difficulty
            FROM entry_subject_mappings esm_a
            INNER JOIN entry_subject_mappings esm_b ON esm_a.question_entry_id = esm_b.question_entry_id
            INNER JOIN entry_subject_mappings esm_c ON esm_a.question_entry_id = esm_c.question_entry_id
            INNER JOIN subject_nodes sn_a ON sn_a.id = esm_a.subject_node_id AND sn_a.dimension_id = ?
            INNER JOIN subject_nodes sn_b ON sn_b.id = esm_b.subject_node_id AND sn_b.dimension_id = ?
            INNER JOIN subject_nodes sn_c ON sn_c.id = esm_c.subject_node_id AND sn_c.dimension_id = ?
            INNER JOIN question_entries qe ON qe.id = esm_a.question_entry_id
            GROUP BY esm_a.subject_node_id, esm_b.subject_node_id, esm_c.subject_node_id
            HAVING COUNT(DISTINCT esm_a.question_entry_id) >= ?
            ORDER BY count DESC
            LIMIT ?
        """, (dim_a_id, dim_b_id, dim_c_id, min_entries, limit))

        results = []
        for row in cursor.fetchall():
            results.append({
                'dim_a_value': row[0],
                'dim_b_value': row[1],
                'dim_c_value': row[2],
                'dim_a_hierarchy_id': row[3],
                'dim_b_hierarchy_id': row[4],
                'dim_c_hierarchy_id': row[5],
                'count': row[6] or 0,
                'avg_difficulty': row[7] or 0,
                'combination': f"{row[0]} \u00d7 {row[1]} \u00d7 {row[2]}"
            })

        return results

    def detect_interaction_effects(
        self,
        exam_context_id: int,
        dimension_a_id: int,
        dimension_b_id: int,
        threshold: float = 0.10
    ) -> List[Dict[str, Any]]:
        """
        Detect where A x B differs from expected (avg of A and B marginals).

        An interaction effect exists when performance at the intersection
        differs significantly from what would be expected based on individual
        dimension performance.

        Args:
            exam_context_id: ID of the exam context
            dimension_a_id: First dimension ID
            dimension_b_id: Second dimension ID
            threshold: Minimum interaction magnitude to report

        Returns:
            List of detected interaction effects with severity
        """
        # Get marginal (individual dimension) performance
        dim_a_perf = self.get_dimension_performance(exam_context_id, dimension_a_id)
        dim_b_perf = self.get_dimension_performance(exam_context_id, dimension_b_id)

        if not dim_a_perf['nodes'] or not dim_b_perf['nodes']:
            return []

        # Create lookup for marginal rates
        total_entries = 0
        cursor = self.conn.execute("""
            SELECT COUNT(DISTINCT id) FROM question_entries
            WHERE review_session_id IN (
                SELECT id FROM review_sessions WHERE exam_context_id = ?
            )
        """, (exam_context_id,))
        row = cursor.fetchone()
        total_entries = row[0] if row else 0

        if total_entries == 0:
            return []

        dim_a_rates = {n['hierarchy_id']: n['total_entries'] / total_entries
                       for n in dim_a_perf['nodes']}
        dim_b_rates = {n['hierarchy_id']: n['total_entries'] / total_entries
                       for n in dim_b_perf['nodes']}

        # Get actual intersection performance
        cross_perf = self.get_cross_dimension_performance(
            exam_context_id, dimension_a_id, dimension_b_id, min_entries=1
        )

        interactions = []
        for cell in cross_perf['matrix']:
            dim_a_hid = cell['dim_a_hierarchy_id']
            dim_b_hid = cell['dim_b_hierarchy_id']
            actual_count = cell['count']
            actual_rate = actual_count / total_entries if total_entries > 0 else 0

            # Expected rate = product of marginal rates (independence assumption)
            expected_rate = dim_a_rates.get(dim_a_hid, 0) * dim_b_rates.get(dim_b_hid, 0)
            expected_count = expected_rate * total_entries

            if expected_count > 0:
                interaction = (actual_count - expected_count) / expected_count

                if abs(interaction) >= threshold:
                    severity = 'high' if abs(interaction) >= 0.5 else 'medium' if abs(interaction) >= 0.25 else 'low'
                    interactions.append({
                        'dim_a_value': cell['dim_a_value'],
                        'dim_b_value': cell['dim_b_value'],
                        'dim_a_hierarchy_id': dim_a_hid,
                        'dim_b_hierarchy_id': dim_b_hid,
                        'expected': round(expected_count, 1),
                        'actual': actual_count,
                        'interaction': round(interaction, 3),
                        'severity': severity,
                        'direction': 'over' if interaction > 0 else 'under'
                    })

        # Sort by absolute interaction magnitude
        interactions.sort(key=lambda x: abs(x['interaction']), reverse=True)
        return interactions

    def get_mistake_type_by_dimension(
        self,
        exam_context_id: int,
        dimension_id: int
    ) -> Dict[str, Any]:
        """
        Get mistake type breakdown per dimension value for stacked bar chart.

        Args:
            exam_context_id: ID of the exam context
            dimension_id: ID of the dimension

        Returns:
            Dict with dimension values and their mistake type distributions
        """
        dimension = self.get_dimension(dimension_id)
        if not dimension:
            return {'dimension_name': '', 'values': [], 'mistake_types': []}

        # Get mistake types distribution by dimension value
        # Uses entry_subject_mappings to link entries to dimension subjects
        cursor = self.conn.execute("""
            SELECT
                sn.name as dim_value,
                sn.id as hierarchy_id,
                t.tag_name as mistake_type,
                t.color_hex,
                COUNT(DISTINCT esm.question_entry_id) as count
            FROM entry_subject_mappings esm
            INNER JOIN subject_nodes sn ON sn.id = esm.subject_node_id AND sn.dimension_id = ?
            INNER JOIN entry_tags et ON et.question_entry_id = esm.question_entry_id
            INNER JOIN tags t ON t.id = et.tag_id
            WHERE t.tag_category = 'mistake_type'
            GROUP BY sn.id, t.id
            ORDER BY sn.name, count DESC
        """, (dimension_id,))

        # Organize data by dimension value
        values_data = {}
        all_mistake_types = set()

        for row in cursor.fetchall():
            dim_value = row[0]
            hierarchy_id = row[1]
            mistake_type = row[2]
            color = row[3]
            count = row[4]

            if dim_value not in values_data:
                values_data[dim_value] = {
                    'name': dim_value,
                    'hierarchy_id': hierarchy_id,
                    'mistake_types': {}
                }

            values_data[dim_value]['mistake_types'][mistake_type] = {
                'count': count,
                'color': color
            }
            all_mistake_types.add(mistake_type)

        return {
            'dimension_name': dimension['name'],
            'dimension_id': dimension_id,
            'values': list(values_data.values()),
            'mistake_types': list(all_mistake_types)
        }

    def get_weighted_study_recommendations(
        self,
        exam_context_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Generate priority-ranked study recommendations.

        Priority = weight x gap x context_penalty
        - weight: exam weight of the subject
        - gap: mistake rate vs expected performance
        - context_penalty: multiplier for recent mistakes

        Args:
            exam_context_id: ID of the exam context
            limit: Maximum recommendations to return

        Returns:
            List of recommendations with priority scores
        """
        # Check if exam uses dimensions
        if not self.exam_uses_dimensions(exam_context_id):
            return []

        # Get dimensions for this exam
        dimensions = self.get_exam_dimensions(exam_context_id)
        if len(dimensions) < 2:
            return []

        # Get cross-dimension performance for first two dimensions
        dim_a_id = dimensions[0]['id']
        dim_b_id = dimensions[1]['id']

        cross_perf = self.get_cross_dimension_performance(
            exam_context_id, dim_a_id, dim_b_id, min_entries=2
        )

        # Get weights for subjects
        dim_a_nodes = self.get_hierarchy_nodes_by_dimension(exam_context_id, dim_a_id)
        dim_b_nodes = self.get_hierarchy_nodes_by_dimension(exam_context_id, dim_b_id)

        weights_a = {n['id']: n.get('exam_weight_low', 0) + n.get('exam_weight_high', 0) / 2
                     for n in dim_a_nodes}
        weights_b = {n['id']: n.get('exam_weight_low', 0) + n.get('exam_weight_high', 0) / 2
                     for n in dim_b_nodes}

        total_entries = cross_perf['total'] or 1
        recommendations = []

        for cell in cross_perf['matrix']:
            dim_a_hid = cell['dim_a_hierarchy_id']
            dim_b_hid = cell['dim_b_hierarchy_id']
            count = cell['count']

            # Calculate weight (average of both dimensions)
            weight = (weights_a.get(dim_a_hid, 5) + weights_b.get(dim_b_hid, 5)) / 2

            # Calculate gap (mistake rate)
            gap = count / total_entries

            # Context penalty (higher difficulty = more penalty)
            avg_diff = cell.get('avg_difficulty', 3) or 3
            context_penalty = 1 + (avg_diff - 3) * 0.2  # 0.8 to 1.4

            # Priority score
            priority = weight * gap * context_penalty

            recommendations.append({
                'combination': f"{cell['dim_a_value']} \u00d7 {cell['dim_b_value']}",
                'dim_a_value': cell['dim_a_value'],
                'dim_b_value': cell['dim_b_value'],
                'dim_a_hierarchy_id': dim_a_hid,
                'dim_b_hierarchy_id': dim_b_hid,
                'count': count,
                'priority_score': round(priority, 3),
                'weight': round(weight, 1),
                'gap': round(gap, 3),
                'avg_difficulty': avg_diff,
                'recommendation': self._generate_recommendation_text(
                    cell['dim_a_value'], cell['dim_b_value'], count, avg_diff
                )
            })

        # Sort by priority score (highest first)
        recommendations.sort(key=lambda x: x['priority_score'], reverse=True)
        return recommendations[:limit]

    def _generate_recommendation_text(
        self,
        dim_a_value: str,
        dim_b_value: str,
        count: int,
        avg_difficulty: float
    ) -> str:
        """Generate human-readable recommendation text"""
        difficulty_label = 'challenging' if avg_difficulty >= 4 else 'moderate' if avg_difficulty >= 3 else 'manageable'
        return f"Focus on {dim_a_value} questions related to {dim_b_value}. You have {count} mistakes here with {difficulty_label} difficulty."

    def get_temporal_trends_by_dimension(
        self,
        exam_context_id: int,
        dimension_id: int,
        hierarchy_id: int = None,
        weeks: int = 12
    ) -> Dict[str, Any]:
        """
        Get time series performance filtered by dimension.

        Args:
            exam_context_id: ID of the exam context
            dimension_id: ID of the dimension
            hierarchy_id: Optional specific hierarchy node ID
            weeks: Number of weeks to include

        Returns:
            Dict with weekly data points and trend info
        """
        dimension = self.get_dimension(dimension_id)
        if not dimension:
            return {'dimension_name': '', 'data': [], 'trend': 'stable'}

        # Build query based on whether specific hierarchy is requested
        # Uses entry_subject_mappings to link entries to dimension subjects
        if hierarchy_id:
            cursor = self.conn.execute("""
                SELECT
                    strftime('%Y-%W', qe.created_at) as week,
                    COUNT(DISTINCT qe.id) as count,
                    ROUND(AVG(qe.perceived_difficulty), 2) as avg_difficulty
                FROM question_entries qe
                INNER JOIN entry_subject_mappings esm ON esm.question_entry_id = qe.id
                INNER JOIN subject_nodes sn ON sn.id = esm.subject_node_id AND sn.dimension_id = ?
                WHERE esm.subject_node_id = ?
                AND qe.created_at >= date('now', ?)
                GROUP BY week
                ORDER BY week
            """, (dimension_id, hierarchy_id, f'-{weeks} weeks'))
        else:
            cursor = self.conn.execute("""
                SELECT
                    strftime('%Y-%W', qe.created_at) as week,
                    COUNT(DISTINCT qe.id) as count,
                    ROUND(AVG(qe.perceived_difficulty), 2) as avg_difficulty
                FROM question_entries qe
                INNER JOIN entry_subject_mappings esm ON esm.question_entry_id = qe.id
                INNER JOIN subject_nodes sn ON sn.id = esm.subject_node_id AND sn.dimension_id = ?
                WHERE qe.created_at >= date('now', ?)
                GROUP BY week
                ORDER BY week
            """, (dimension_id, f'-{weeks} weeks'))

        data = []
        counts = []
        for row in cursor.fetchall():
            count = row[1] or 0
            counts.append(count)
            data.append({
                'week': row[0],
                'count': count,
                'avg_difficulty': row[2] or 0
            })

        # Calculate trend
        trend = 'stable'
        if len(counts) >= 4:
            first_half = sum(counts[:len(counts)//2])
            second_half = sum(counts[len(counts)//2:])
            if second_half > first_half * 1.2:
                trend = 'increasing'
            elif second_half < first_half * 0.8:
                trend = 'decreasing'

        return {
            'dimension_name': dimension['name'],
            'dimension_id': dimension_id,
            'hierarchy_id': hierarchy_id,
            'data': data,
            'trend': trend,
            'total': sum(counts)
        }
