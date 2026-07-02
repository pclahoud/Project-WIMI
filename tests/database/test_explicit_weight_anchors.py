"""Tests for Stage 6 of the Hierarchical Weight Allocation Plan.

Covers the canonical user-typed-value endpoint exercised through the
``setExplicitWeight`` bridge slot (``WeightBridgeMixin``). The slot
collapses what was previously a two-call hot patch
(``updateRelativeWeight`` + ``setEdgeAnchor``) into a single atomic
operation that:

1. Writes the per-edge ``relative_weight`` (converting Q→% when
   ``unit='Q'``).
2. Sets ``subject_edges.is_anchor=TRUE`` and
   ``subject_edges.weight_source='user_explicit'``.
3. Mirrors the value onto ``subject_nodes.relative_weight`` so legacy
   read paths (chip render, analytics) reflect the new value.

Reference: ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``
Stage 6; ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``
§3.4 / §6.
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
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
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


# ---- Helpers -------------------------------------------------------------


def _make_node(
    db: UserDatabase,
    name: str,
    parent_id=None,
    level_type='Topic',
    exam_weight_low=None,
    exam_weight_high=None,
):
    """Build a subject node via the standard creator."""
    return db.create_subject_node_with_weight(
        exam_context='SetExplicitWeight Exam',
        name=name,
        level_type=level_type,
        parent_id=parent_id,
        exam_weight_low=exam_weight_low,
        exam_weight_high=exam_weight_high,
        weight_source='user_defined',
    )


def _seed_exam_with_length(db: UserDatabase, kind: str, typical: int | None):
    """Create an exam_context with the requested length triple."""
    exam = db.create_exam_context(
        exam_name='SetExplicitWeight Exam',
        exam_description='Stage 6 explicit weight tests',
    )
    if kind == 'unknown':
        db.update_exam_length(
            exam.id, kind='unknown', min=None, max=None, typical=None,
        )
    elif kind == 'fixed':
        db.update_exam_length(
            exam.id, kind='fixed', min=typical, max=typical, typical=typical,
        )
    else:  # range
        db.update_exam_length(
            exam.id, kind='range',
            min=max(1, typical - 20), max=typical + 20, typical=typical,
        )
    return exam


def _build_parent_with_child(db: UserDatabase):
    """One System parent at 100% with a single Topic child.

    Returns ``(parent_id, child_id, edge_id)``.
    """
    parent = _make_node(
        db, 'SetExplicit Sys',
        level_type='System', exam_weight_low=100, exam_weight_high=100,
    )
    child = _make_node(
        db, 'SetExplicit Child',
        parent_id=parent.id, level_type='Topic',
    )
    edge_row = db.fetchone(
        "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
        (parent.id, child.id),
    )
    assert edge_row is not None, (
        "Expected an edge row to be created for the new child"
    )
    return parent.id, child.id, edge_row['id']


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


# ==================== Tests ====================


class TestSetExplicitWeightPercent:
    """Unit-`%` cases — the value is interpreted directly as relative_weight."""

    def test_set_explicit_weight_percent_writes_anchor(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Writing with unit='%' anchors the edge and stamps user_explicit."""
        _seed_exam_with_length(user_db, kind='fixed', typical=280)
        _, child_id, edge_id = _build_parent_with_child(user_db)

        data = _ok(bridge.setExplicitWeight(edge_id, 25.0, '%', 'manual edit'))

        assert data['ok'] is True
        assert data['edge_id'] == edge_id
        assert data['applied_relative_weight'] == pytest.approx(25.0)
        assert data['unit'] == '%'

        row = user_db.fetchone(
            "SELECT relative_weight, is_anchor, weight_source "
            "FROM subject_edges WHERE id = ?",
            (edge_id,),
        )
        assert row['relative_weight'] == pytest.approx(25.0)
        assert bool(row['is_anchor']) is True
        assert row['weight_source'] == 'user_explicit'


class TestSetExplicitWeightQuestions:
    """Unit-`Q` cases — value converts to % via parent_q_typical."""

    def test_set_explicit_weight_questions_converts_to_percent(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """unit='Q', value=28, total=280 → relative_weight = 10.0."""
        _seed_exam_with_length(user_db, kind='fixed', typical=280)
        _, _, edge_id = _build_parent_with_child(user_db)

        data = _ok(bridge.setExplicitWeight(edge_id, 28.0, 'Q', ''))

        assert data['ok'] is True
        assert data['unit'] == 'Q'
        assert data['applied_relative_weight'] == pytest.approx(10.0)
        # 10.0% of 280 questions = 28 questions.
        assert data['applied_question_count'] == 28

        row = user_db.fetchone(
            "SELECT relative_weight, weight_source FROM subject_edges WHERE id = ?",
            (edge_id,),
        )
        assert row['relative_weight'] == pytest.approx(10.0)
        assert row['weight_source'] == 'user_explicit'

    def test_set_explicit_weight_questions_with_unknown_length_returns_error(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """When the exam has length_kind='unknown', Q-mode is unsupported."""
        _seed_exam_with_length(user_db, kind='unknown', typical=None)
        _, _, edge_id = _build_parent_with_child(user_db)

        error = _err(bridge.setExplicitWeight(edge_id, 28.0, 'Q', ''))
        assert 'length_typical' in error or "'unknown'" in error or 'budget' in error, (
            f"Expected an error mentioning length/budget; got: {error!r}"
        )

        # And the edge value must not have been mutated.
        row = user_db.fetchone(
            "SELECT relative_weight FROM subject_edges WHERE id = ?",
            (edge_id,),
        )
        # Either NULL (untouched) or the seeded value, but definitely
        # not the user's typed Q value masquerading as a percent.
        assert row['relative_weight'] is None or row['relative_weight'] != 28.0


class TestMirrorAndSource:
    """Side effects on the legacy node columns + audit-log columns."""

    def test_set_explicit_weight_mirrors_to_subject_nodes(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """The value lands on subject_nodes.relative_weight too (legacy mirror)."""
        _seed_exam_with_length(user_db, kind='fixed', typical=280)
        _, child_id, edge_id = _build_parent_with_child(user_db)

        _ok(bridge.setExplicitWeight(edge_id, 42.5, '%', 'mirror test'))

        row = user_db.fetchone(
            "SELECT relative_weight, weight_source "
            "FROM subject_nodes WHERE id = ?",
            (child_id,),
        )
        assert row['relative_weight'] == pytest.approx(42.5)
        # The legacy ``subject_nodes.weight_source`` CHECK constraint
        # only accepts the original four-value enum, so the mirror
        # writes 'user_defined' (the closest legacy match for "user
        # explicitly typed this"). The canonical edge-level source is
        # 'user_explicit' (covered by the dedicated test below).
        assert row['weight_source'] in ('user_defined', 'user_explicit'), (
            f"Mirrored weight_source on subject_nodes was {row['weight_source']!r}; "
            f"expected the legacy-compatible 'user_defined' or 'user_explicit'."
        )

    def test_set_explicit_weight_records_user_explicit_source(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """weight_source on subject_edges is always 'user_explicit'.

        Even when the prior source was something else (derived,
        user_estimate, etc.), Stage 6 Apply forces 'user_explicit'.
        """
        _seed_exam_with_length(user_db, kind='fixed', typical=280)
        _, _, edge_id = _build_parent_with_child(user_db)

        # Seed a non-explicit prior state.
        user_db.execute(
            "UPDATE subject_edges SET relative_weight = 12.5, "
            "weight_source = 'derived' WHERE id = ?",
            (edge_id,),
        )
        user_db.conn.commit()

        _ok(bridge.setExplicitWeight(edge_id, 33.0, '%', ''))

        row = user_db.fetchone(
            "SELECT weight_source FROM subject_edges WHERE id = ?",
            (edge_id,),
        )
        assert row['weight_source'] == 'user_explicit', (
            "Stage 6 must force weight_source='user_explicit' on every "
            "user-typed write, regardless of prior source."
        )


class TestSlotErrorPaths:
    """Bridge-level error path coverage."""

    def test_setExplicitWeight_slot_invalid_unit_returns_error(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """unit='X' (not '%' or 'Q') returns ok=False."""
        _seed_exam_with_length(user_db, kind='fixed', typical=280)
        _, _, edge_id = _build_parent_with_child(user_db)

        error = _err(bridge.setExplicitWeight(edge_id, 25.0, 'X', ''))
        assert 'unit' in error.lower(), (
            f"Expected an error mentioning unit; got: {error!r}"
        )

    def test_setExplicitWeight_slot_invalid_edge_returns_error(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Unknown edge_id returns ok=False with a clear message."""
        _seed_exam_with_length(user_db, kind='fixed', typical=280)
        _build_parent_with_child(user_db)  # sets up exam context

        error = _err(bridge.setExplicitWeight(999_999, 25.0, '%', ''))
        assert 'not found' in error.lower() or 'edge' in error.lower(), (
            f"Expected an edge-not-found error; got: {error!r}"
        )

    def test_setExplicitWeight_slot_returns_serialized_payload(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Happy path returns a well-formed JSON payload."""
        _seed_exam_with_length(user_db, kind='fixed', typical=280)
        _, _, edge_id = _build_parent_with_child(user_db)

        response = bridge.setExplicitWeight(edge_id, 15.0, '%', 'shape check')
        # Must be parseable JSON.
        payload = json.loads(response)
        assert payload['success'] is True
        data = payload['data']
        # Required fields per the slot's docstring.
        for key in (
            'ok', 'edge_id', 'applied_relative_weight',
            'applied_question_count', 'unit',
        ):
            assert key in data, (
                f"setExplicitWeight payload missing required field {key!r}: {data}"
            )
