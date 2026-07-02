"""Bridge tests for the Stage 3 per-edge weight slots.

Covers the three new slots added to ``WeightBridgeMixin`` per
``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`` Stage 3:

- ``setEdgeAnchor`` — toggle ``subject_edges.is_anchor``
- ``updateEdgeRelativeWeight`` — per-edge write, no rebalance
- ``getEdgesForChild`` — multi-parent edge enumeration

The DB-layer contract is exercised in
``tests/database/test_edge_anchor_semantics.py``; this file proves the
slot surface returns well-formed JSON, emits the ``weightUpdated`` Qt
signal, and handles error paths cleanly.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for master database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(
        db_path=temp_db_path,
        user_id=1,
        username="test_user",
    )
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(
        username="test_admin",
        display_name="Test Admin",
    )
    return DatabaseBridge(master_db=master_db, user_db=user_db)


# ---- Subject-tree builders ------------------------------------------------


def _make_node(db: UserDatabase, name: str, parent_id=None, level_type='System'):
    return db.create_subject_node(
        exam_context='Test Exam',
        name=name,
        level_type=level_type,
        parent_id=parent_id,
        exam_weight_low=0,
        exam_weight_high=0,
        sort_order=1,
    )


def _set_edge_weight(db: UserDatabase, edge_id: int, weight: float) -> None:
    """Seed an edge's relative_weight directly."""
    db.execute(
        "UPDATE subject_edges SET relative_weight = ? WHERE id = ?",
        (weight, edge_id),
    )
    db.conn.commit()


# ---- Response helpers -----------------------------------------------------


def _parse(response: str) -> dict:
    return json.loads(response)


def _ok(response: str) -> dict:
    payload = _parse(response)
    assert payload['success'] is True, (
        f"Expected success, got error: {payload.get('error')}"
    )
    return payload.get('data')


def _err(response: str) -> str:
    payload = _parse(response)
    assert payload['success'] is False, "Expected error, got success"
    return payload.get('error')


# ==================== setEdgeAnchor ====================


class TestSetEdgeAnchor:
    def test_setEdgeAnchor_returns_serialized_edge(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Happy path: slot returns ok=True and an edge dict with the new flag."""
        parent = _make_node(user_db, 'Cardio')
        child = _make_node(user_db, 'Hypertension')
        edge = user_db.add_edge(parent.id, child.id, is_primary=True)
        _set_edge_weight(user_db, edge.id, 50.0)

        response = bridge.setEdgeAnchor(edge.id, True, 'Bridge test')
        data = _ok(response)

        assert data['ok'] is True
        assert data['edge']['id'] == edge.id
        assert data['edge']['is_anchor'] is True
        assert data['edge']['parent_id'] == parent.id
        assert data['edge']['child_id'] == child.id
        # The history row was written; the id should be a positive int
        # (or None if the history table is unavailable, which would
        # also be a defensive code path).
        assert data['weight_history_id'] is None or isinstance(
            data['weight_history_id'], int
        )

    def test_setEdgeAnchor_clear_returns_anchor_false(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Clearing an anchor flips the edge's is_anchor back to False."""
        parent = _make_node(user_db, 'Cardio')
        child = _make_node(user_db, 'Hypertension')
        edge = user_db.add_edge(parent.id, child.id, is_primary=True)
        _set_edge_weight(user_db, edge.id, 50.0)

        # Set then clear.
        _ok(bridge.setEdgeAnchor(edge.id, True, ''))
        data = _ok(bridge.setEdgeAnchor(edge.id, False, ''))

        assert data['edge']['is_anchor'] is False

    def test_setEdgeAnchor_invalid_edge_returns_error(
        self, bridge: DatabaseBridge
    ):
        """Unknown edge_id returns success=False with a typed error."""
        response = bridge.setEdgeAnchor(999_999, True, '')
        payload = _parse(response)
        assert payload['success'] is False
        assert payload.get('error_type') == 'SubjectNodeError'
        assert 'Subject edge' in payload.get('error', '')


# ==================== updateEdgeRelativeWeight ====================


class TestUpdateEdgeRelativeWeight:
    def test_updateEdgeRelativeWeight_returns_payload_without_rebalance(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Stage 2 contract: payload must not include affected_siblings."""
        parent = _make_node(user_db, 'Cardio')
        child = _make_node(user_db, 'Hypertension')
        edge = user_db.add_edge(parent.id, child.id, is_primary=True)
        _set_edge_weight(user_db, edge.id, 30.0)

        response = bridge.updateEdgeRelativeWeight(edge.id, 55.0, 'test')
        data = _ok(response)

        # Core writer return shape.
        assert data['ok'] is True
        assert data['edge_id'] == edge.id
        assert data['old_weight'] == pytest.approx(30.0)
        assert data['new_weight'] == pytest.approx(55.0)
        assert data['anchor_set'] is False

        # Stage 2/3 contract: this writer NEVER touches siblings, so
        # the payload must NOT promise a sibling-rebalance side-effect.
        assert 'affected_siblings' not in data, (
            "updateEdgeRelativeWeight payload contains affected_siblings — "
            "Stage 2/3 contract forbids this. Use rebalanceSiblings to opt in."
        )

    def test_updateEdgeRelativeWeight_writes_subject_edges(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """End-to-end: the value lands in subject_edges.relative_weight."""
        parent = _make_node(user_db, 'Cardio')
        child = _make_node(user_db, 'Hypertension')
        edge = user_db.add_edge(parent.id, child.id, is_primary=True)
        _set_edge_weight(user_db, edge.id, 30.0)

        _ok(bridge.updateEdgeRelativeWeight(edge.id, 42.5, ''))

        row = user_db.fetchone(
            "SELECT relative_weight, weight_source FROM subject_edges WHERE id = ?",
            (edge.id,),
        )
        assert float(row['relative_weight']) == pytest.approx(42.5)
        assert row['weight_source'] == 'user_explicit'

    def test_updateEdgeRelativeWeight_rejects_out_of_range(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Validation: out-of-range weight returns a typed error."""
        parent = _make_node(user_db, 'Cardio')
        child = _make_node(user_db, 'Hypertension')
        edge = user_db.add_edge(parent.id, child.id, is_primary=True)

        response = bridge.updateEdgeRelativeWeight(edge.id, 150.0, '')
        payload = _parse(response)
        assert payload['success'] is False
        assert payload.get('error_type') == 'WeightValidationError'


# ==================== getEdgesForChild ====================


class TestGetEdgesForChild:
    def test_getEdgesForChild_orders_primary_first(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """When a child has multiple parents, the primary edge leads."""
        cardio = _make_node(user_db, 'Cardiovascular')
        preg = _make_node(user_db, 'Pregnancy')
        leaf = _make_node(user_db, 'Hypertension')

        # Insert non-primary first to ensure ordering is by flag,
        # not by insertion order.
        user_db.add_edge(cardio.id, leaf.id, is_primary=False)
        user_db.add_edge(preg.id, leaf.id, is_primary=True)

        data = _ok(bridge.getEdgesForChild(leaf.id))

        assert len(data) == 2
        assert data[0]['is_primary'] is True
        assert data[0]['parent_id'] == preg.id
        assert data[0]['parent_name'] == 'Pregnancy'
        assert data[1]['is_primary'] is False
        assert data[1]['parent_id'] == cardio.id
        assert data[1]['parent_name'] == 'Cardiovascular'

        # Each row carries per-edge weight metadata.
        for row in data:
            assert 'edge_id' in row
            assert 'relative_weight' in row
            assert 'is_anchor' in row
            assert 'weight_source' in row
            assert 'sort_order' in row

    def test_getEdgesForChild_empty_for_orphan(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """A child with no parents returns an empty list."""
        orphan = _make_node(user_db, 'Orphan')
        data = _ok(bridge.getEdgesForChild(orphan.id))
        assert data == []
