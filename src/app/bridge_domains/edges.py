"""WIMI subject-edge (polyhierarchy) bridge operations.

Wraps the methods in :mod:`database.domains.edges` for the WebChannel
frontend. See ``docs/planning/POLYHIERARCHY_MIGRATION.md`` Section 6 for
the slot specs. ``setPrimaryParentForEntry`` lives in
:class:`EntryBridgeMixin` (it writes to ``entry_subject_mappings``) — the
five slots here cover edge CRUD and traversal.
"""
from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from database.exceptions import CircularReferenceError

from ..bridge_helpers import serialize_response


class EdgesBridgeMixin:
    """Bridge mixin for ``subject_edges`` operations. Composed into DatabaseBridge."""

    @pyqtSlot(int, int, bool, result=str)
    @instrumented_slot
    def addParent(self, child_id: int, parent_id: int, is_primary: bool = False) -> str:
        """
        Add a parent edge to a subject node.

        Args:
            child_id: ID of the child node.
            parent_id: ID of the new parent.
            is_primary: If True, sets this as the canonical parent.

        Returns:
            JSON response with edge data, or ``error: 'cycle'`` if the
            edge would create a cycle.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            edge = self.user_db.add_edge(parent_id, child_id, is_primary=is_primary)
            return serialize_response(True, data={
                'edge_id': edge.id,
                'parent_id': edge.parent_id,
                'child_id': edge.child_id,
                'is_primary': edge.is_primary,
                'display_order': edge.display_order,
            })
        except CircularReferenceError:
            # Surface the planned 'cycle' sentinel verbatim so the
            # frontend can branch on it without parsing prose.
            return serialize_response(False, error='cycle')
        except Exception as e:
            self._log_error(
                f'Error adding parent edge: {e}',
                {'child_id': child_id, 'parent_id': parent_id},
            )
            return serialize_response(False, error=f'Failed to add parent: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def removeParent(self, edge_id: int) -> str:
        """
        Remove a parent edge by ID.

        Args:
            edge_id: ID of the edge to remove.

        Returns:
            JSON response with ``{ok: true}``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            self.user_db.remove_edge(edge_id)
            return serialize_response(True, data={'ok': True})
        except Exception as e:
            self._log_error(
                f'Error removing parent edge: {e}',
                {'edge_id': edge_id},
            )
            return serialize_response(False, error=f'Failed to remove parent: {e}')

    @pyqtSlot(int, int, result=str)
    @instrumented_slot
    def setPrimaryParent(self, child_id: int, parent_id: int) -> str:
        """
        Atomically switch the primary parent for a subject node.

        Args:
            child_id: ID of the child node.
            parent_id: ID of the parent to mark primary. An edge between
                the two must already exist.

        Returns:
            JSON response with the updated edge.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            edge = self.user_db.set_primary_parent(child_id, parent_id)
            return serialize_response(True, data={
                'edge_id': edge.id,
                'parent_id': edge.parent_id,
                'child_id': edge.child_id,
                'is_primary': edge.is_primary,
                'display_order': edge.display_order,
            })
        except Exception as e:
            self._log_error(
                f'Error setting primary parent: {e}',
                {'child_id': child_id, 'parent_id': parent_id},
            )
            return serialize_response(False, error=f'Failed to set primary parent: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getParents(self, child_id: int) -> str:
        """
        List all parent edges for a subject node.

        Args:
            child_id: ID of the child node.

        Returns:
            JSON response with a list of parent-edge dicts (primary first).
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            parents = self.user_db.get_parents(child_id)
            return serialize_response(True, data=[p.to_dict() for p in parents])
        except Exception as e:
            self._log_error(
                f'Error getting parents: {e}',
                {'child_id': child_id},
            )
            return serialize_response(False, error=f'Failed to get parents: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def getPathsToRoot(self, child_id: int) -> str:
        """
        List every distinct root-to-child path for a subject node.

        Args:
            child_id: ID of the child node.

        Returns:
            JSON response with a list of paths (each a list of node IDs).
            The primary path appears first.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        try:
            paths = self.user_db.get_paths_to_root(child_id)
            return serialize_response(True, data=paths)
        except Exception as e:
            self._log_error(
                f'Error getting paths to root: {e}',
                {'child_id': child_id},
            )
            return serialize_response(False, error=f'Failed to get paths: {e}')
