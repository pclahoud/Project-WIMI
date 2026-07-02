"""Tests for Stage 8 of the Hierarchical Weight Allocation plan.

Covers CAT (variable-length adaptive exam) handling:

* :meth:`HierarchyMixin.allocate_questions_hamilton` honors the new
  ``is_adaptive`` kwarg and returns raw float shares (no integer
  rounding, no remainder distribution) when set.
* :meth:`HierarchyMixin.get_effective_question_counts` propagates
  ``is_adaptive`` from the exam context's ``length_kind`` and emits
  float ``q_typical`` values per row (plus an ``is_adaptive`` flag).
* :meth:`ExamContextsMixin.is_adaptive_exam` returns the right boolean
  for each of the three ``length_kind`` values.
* Anchored edges under an adaptive exam keep their explicit allocation
  as a float (no rounding lost).

Reference: ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``
§"Stage 8"; ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``
§3.2 (length triple rationale) and §7.4 (planning baseline copy).

Fixture style mirrors ``tests/database/test_hamilton_allocation.py``
and ``tests/database/test_question_allocation_bridge.py`` — a fully
composed ``UserDatabase`` against a per-test temporary path, world
built via the public mixin API.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from database import MasterDatabase, UserDatabase


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    return master_db.create_user(
        username="stage8_user",
        display_name="Stage 8 User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


# ---------------------------------------------------------------- helpers


def _make_exam_context(
    user_db,
    *,
    name: str,
    length_kind: str,
    length_typical: Optional[int] = None,
    length_min: Optional[int] = None,
    length_max: Optional[int] = None,
) -> int:
    """Create an exam context with the requested length triple.

    For ``length_kind='range'`` (CAT), defaults to NCLEX-like values
    (typical=100, min=85, max=150) when the caller doesn't override.
    For ``length_kind='fixed'``, min/max/typical all equal
    ``length_typical``.
    """
    ctx = user_db.create_exam_context(
        exam_name=name,
        exam_description=f"Stage 8 fixture exam: {name}",
    )
    if length_kind == "unknown":
        return ctx.id
    if length_kind == "fixed":
        typical = length_typical if length_typical is not None else 280
        user_db.update_exam_length(
            ctx.id, kind="fixed",
            min=typical, max=typical, typical=typical,
        )
    elif length_kind == "range":
        typical = length_typical if length_typical is not None else 100
        lo = length_min if length_min is not None else 85
        hi = length_max if length_max is not None else 150
        user_db.update_exam_length(
            ctx.id, kind="range", min=lo, max=hi, typical=typical,
        )
    return ctx.id


def _make_node(user_db, name: str, *, exam_context: str = "USMLE") -> int:
    """Insert a bare subject_nodes row for the allocator tests."""
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, status) "
        "VALUES (?, ?, 'Topic', 'active')",
        (exam_context, name),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _set_edge_weight(
    user_db,
    edge_id: int,
    relative_weight: Optional[float],
    *,
    is_anchor: bool = False,
    weight_source: str = "user_estimate",
) -> None:
    user_db.execute(
        "UPDATE subject_edges SET relative_weight = ?, is_anchor = ?, "
        "weight_source = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (relative_weight, bool(is_anchor), weight_source, edge_id),
    )
    user_db.conn.commit()


def _make_parent_with_children(
    user_db,
    weights: List[float],
    *,
    anchored_indices: Optional[List[int]] = None,
) -> Tuple[int, List[int]]:
    anchored = set(anchored_indices or [])
    parent_id = _make_node(user_db, "Parent")
    edge_ids: List[int] = []
    for idx, weight in enumerate(weights):
        child_id = _make_node(user_db, f"Child_{idx}")
        edge = user_db.add_edge(parent_id, child_id, is_primary=True)
        _set_edge_weight(
            user_db, edge.id, weight, is_anchor=(idx in anchored),
        )
        edge_ids.append(edge.id)
    return parent_id, edge_ids


def _make_root_system_for_exam(
    user_db,
    exam_name: str,
    name: str,
    *,
    weight_low: float = 100.0,
    weight_high: float = 100.0,
) -> int:
    node = user_db.create_subject_node_with_weight(
        exam_context=exam_name,
        name=name,
        level_type="System",
        parent_id=None,
        exam_weight_low=weight_low,
        exam_weight_high=weight_high,
        weight_source="user_defined",
    )
    return node.id


def _make_child_for_exam(
    user_db,
    exam_name: str,
    name: str,
    parent_id: int,
    *,
    relative_weight: Optional[float] = None,
    is_anchor: bool = False,
) -> Tuple[int, int]:
    child = user_db.create_subject_node_with_weight(
        exam_context=exam_name,
        name=name,
        level_type="Topic",
        parent_id=parent_id,
        relative_weight=relative_weight,
        weight_source="user_defined",
    )
    edge_row = user_db.fetchone(
        "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
        (parent_id, child.id),
    )
    if edge_row is None:
        edge = user_db.add_edge(parent_id, child.id, is_primary=True)
        edge_id = edge.id
    else:
        edge_id = edge_row['id']
    user_db.execute(
        "UPDATE subject_edges SET relative_weight = ?, is_anchor = ?, "
        "weight_source = 'user_explicit' WHERE id = ?",
        (relative_weight, bool(is_anchor), edge_id),
    )
    user_db.conn.commit()
    return child.id, edge_id


# ---------------------------------------------------------------- is_adaptive_exam


def test_is_adaptive_exam_returns_correct_boolean(user_db):
    """``is_adaptive_exam`` returns True only for length_kind='range'."""
    fixed_id = _make_exam_context(
        user_db, name="USMLE Step 1", length_kind="fixed",
        length_typical=280,
    )
    range_id = _make_exam_context(
        user_db, name="NCLEX-RN-Stage8", length_kind="range",
        length_typical=100, length_min=85, length_max=150,
    )
    unknown_id = _make_exam_context(
        user_db, name="Custom Exam", length_kind="unknown",
    )

    assert user_db.is_adaptive_exam(fixed_id) is False
    assert user_db.is_adaptive_exam(range_id) is True
    assert user_db.is_adaptive_exam(unknown_id) is False
    # Defensive — missing context returns False, not raises.
    assert user_db.is_adaptive_exam(999999) is False


# ---------------------------------------------------------------- allocator: CAT returns floats


def test_cat_returns_floats_not_integers(user_db):
    """``is_adaptive=True`` ⇒ allocator returns float exact shares.

    NCLEX-like exam: typical=100 questions, three children with
    weights 40/35/25 → allocations {40.0, 35.0, 25.0} as floats.
    The non-adaptive path would also return 40/35/25 (no remainder)
    but as ints — this test asserts the type is preserved as float
    so downstream UI formats the value with one decimal place + the
    "(planning estimate)" qualifier.
    """
    parent_id, [e1, e2, e3] = _make_parent_with_children(
        user_db, [40.0, 35.0, 25.0]
    )
    alloc = user_db.allocate_questions_hamilton(
        parent_id, 100, is_adaptive=True
    )

    # All values are floats — not ints — even when the underlying
    # math produces integer-valued shares.
    for edge_id, val in alloc.items():
        assert isinstance(val, float), (
            f"Edge {edge_id} returned {val!r} ({type(val).__name__}); "
            f"adaptive mode must preserve float precision."
        )

    assert alloc[e1] == pytest.approx(40.0)
    assert alloc[e2] == pytest.approx(35.0)
    assert alloc[e3] == pytest.approx(25.0)
    # Sum is exact within float epsilon.
    assert sum(alloc.values()) == pytest.approx(100.0)


def test_cat_returns_floats_with_fractional_shares(user_db):
    """An adaptive exam with weights that don't divide evenly still
    returns raw floats — no integer rounding, no remainder
    distribution.

    100 questions, three equal weights (33.33/33.33/33.33) → each
    edge gets ~33.33 (not 34/33/33 as Hamilton would produce in
    integer mode).
    """
    parent_id, [e1, e2, e3] = _make_parent_with_children(
        user_db, [33.33, 33.33, 33.33]
    )
    alloc = user_db.allocate_questions_hamilton(
        parent_id, 100, is_adaptive=True
    )
    for val in alloc.values():
        assert isinstance(val, float)
    # Every edge gets the same exact share.
    assert alloc[e1] == pytest.approx(alloc[e2])
    assert alloc[e2] == pytest.approx(alloc[e3])
    # And none of them is the rounded-up "34" Hamilton would produce.
    for val in alloc.values():
        assert not float(val).is_integer() or val == pytest.approx(100/3 * 3 / 3)
    assert sum(alloc.values()) == pytest.approx(100.0)


def test_fixed_length_still_integer(user_db):
    """``is_adaptive=False`` (the default) keeps the integer Hamilton
    contract: same children produce integer outputs that sum to the
    budget."""
    parent_id, [e1, e2, e3] = _make_parent_with_children(
        user_db, [40.0, 35.0, 25.0]
    )
    alloc = user_db.allocate_questions_hamilton(parent_id, 100)

    for val in alloc.values():
        assert isinstance(val, int), (
            f"Non-adaptive mode must return ints; got {val!r} "
            f"({type(val).__name__})"
        )
    assert sum(alloc.values()) == 100
    assert alloc[e1] == 40
    assert alloc[e2] == 35
    assert alloc[e3] == 25


def test_fixed_length_with_fractional_shares_rounds(user_db):
    """The pre-Stage-8 integer Hamilton path still produces the
    integer-rounded distribution. 100 questions, three equal weights
    → 34/33/33 (Hamilton leftover distribution).
    """
    parent_id, [e1, e2, e3] = _make_parent_with_children(
        user_db, [33.33, 33.33, 33.33]
    )
    alloc = user_db.allocate_questions_hamilton(parent_id, 100)

    for val in alloc.values():
        assert isinstance(val, int)
    assert sum(alloc.values()) == 100
    # Lowest edge_id gets the leftover by tie-break rule 3.
    assert alloc[e1] == 34
    assert alloc[e2] == 33
    assert alloc[e3] == 33


# ---------------------------------------------------------------- anchored edges under CAT


def test_anchored_edge_under_adaptive_keeps_float(user_db):
    """Anchored child's allocation in adaptive mode is float-precise
    — no integer rounding, even when the percentage produces a
    fractional question count.

    100 questions, anchored at 23% → exactly 23.0 (float), not 23
    (int) and not 23.0 due to integer round.
    """
    parent_id, [e_anchor, e2, e3] = _make_parent_with_children(
        user_db, [23.0, 50.0, 27.0], anchored_indices=[0],
    )
    alloc = user_db.allocate_questions_hamilton(
        parent_id, 100, is_adaptive=True,
    )

    assert isinstance(alloc[e_anchor], float)
    assert alloc[e_anchor] == pytest.approx(23.0)
    # Other two are floats too.
    assert isinstance(alloc[e2], float)
    assert isinstance(alloc[e3], float)
    # Non-anchored siblings share the remaining 77 in proportion to
    # their weights (50/77 and 27/77 of 77).
    assert alloc[e2] == pytest.approx(77.0 * 50.0 / 77.0)  # 50.0
    assert alloc[e3] == pytest.approx(77.0 * 27.0 / 77.0)  # 27.0


def test_anchored_edge_under_adaptive_with_fractional_percentage(user_db):
    """An anchored edge at a non-integer percentage under CAT keeps
    its float precision through the allocation.

    100 questions, anchored at 17.5% → exactly 17.5 (not 18 or 17).
    """
    parent_id, [e_anchor, e2] = _make_parent_with_children(
        user_db, [17.5, 82.5], anchored_indices=[0],
    )
    alloc = user_db.allocate_questions_hamilton(
        parent_id, 100, is_adaptive=True,
    )
    assert alloc[e_anchor] == pytest.approx(17.5)
    # The other gets the remaining budget (82.5 of 82.5 ratio = full
    # 82.5 remaining).
    assert alloc[e2] == pytest.approx(82.5)


# ---------------------------------------------------------------- get_effective_question_counts


def test_get_effective_question_counts_marks_adaptive_rows(user_db):
    """Every row of an adaptive exam carries ``is_adaptive=True``
    and a float ``q_typical``."""
    exam_id = _make_exam_context(
        user_db, name="NCLEX-RN-Stage8-marks", length_kind="range",
        length_typical=100, length_min=85, length_max=150,
    )
    sys_id = _make_root_system_for_exam(
        user_db, "NCLEX-RN-Stage8-marks", "Safe Care",
        weight_low=100, weight_high=100,
    )
    c1_id, e1 = _make_child_for_exam(
        user_db, "NCLEX-RN-Stage8-marks", "Topic1", sys_id,
        relative_weight=40,
    )
    c2_id, e2 = _make_child_for_exam(
        user_db, "NCLEX-RN-Stage8-marks", "Topic2", sys_id,
        relative_weight=30,
    )
    c3_id, e3 = _make_child_for_exam(
        user_db, "NCLEX-RN-Stage8-marks", "Topic3", sys_id,
        relative_weight=30,
    )

    rows = user_db.get_effective_question_counts(exam_id)
    assert rows, "Expected non-empty result for the NCLEX fixture"

    # Every row (edge rows AND the synthetic root row added by
    # bugfix 8890d8a) carries is_adaptive=True.
    for row in rows:
        assert row.get('is_adaptive') is True, (
            f"Row {row!r} missing is_adaptive=True under length_kind='range'"
        )

    # Edge rows under the System root have float q_typical values
    # that sum to ~100 (the planning typical).
    child_rows = [r for r in rows if r['parent_id'] == sys_id]
    assert len(child_rows) == 3
    for r in child_rows:
        assert r['q_typical'] is not None
        assert isinstance(r['q_typical'], float), (
            f"Adaptive row {r['edge_id']} q_typical {r['q_typical']!r} "
            f"is {type(r['q_typical']).__name__}, expected float"
        )
    total = sum(r['q_typical'] for r in child_rows)
    assert total == pytest.approx(100.0)

    # The float values are NOT integer-rounded — at typical=100 the
    # 40/30/30 split lands on exact integers (40.0, 30.0, 30.0) so
    # this fixture doesn't differentiate from the int path on numeric
    # value alone, but the TYPE assertion above proves the adaptive
    # branch is taken.


def test_get_effective_question_counts_fixed_marks_non_adaptive(user_db):
    """Sanity: ``length_kind='fixed'`` returns ``is_adaptive=False``
    on every row and integer q_typical."""
    exam_id = _make_exam_context(
        user_db, name="USMLE Step 1 Stage 8 Fixed",
        length_kind="fixed", length_typical=280,
    )
    sys_id = _make_root_system_for_exam(
        user_db, "USMLE Step 1 Stage 8 Fixed", "Cardio",
        weight_low=100, weight_high=100,
    )
    _make_child_for_exam(
        user_db, "USMLE Step 1 Stage 8 Fixed", "Topic1", sys_id,
        relative_weight=40,
    )
    _make_child_for_exam(
        user_db, "USMLE Step 1 Stage 8 Fixed", "Topic2", sys_id,
        relative_weight=60,
    )

    rows = user_db.get_effective_question_counts(exam_id)
    assert rows
    for row in rows:
        assert row.get('is_adaptive') is False, (
            f"Row {row!r} marked adaptive under length_kind='fixed'"
        )
    child_rows = [r for r in rows if r['parent_id'] == sys_id]
    for r in child_rows:
        assert isinstance(r['q_typical'], int), (
            f"Fixed row {r['edge_id']} q_typical "
            f"{r['q_typical']!r} is {type(r['q_typical']).__name__}, "
            f"expected int"
        )


def test_get_effective_question_counts_adaptive_with_fractional_split(user_db):
    """Adaptive exam with weights that produce fractional shares —
    the float precision is preserved through the allocator.

    typical=100, two children at 33.33/66.67 → 33.33 and 66.67 as
    floats (not 33/67 from integer Hamilton).
    """
    exam_id = _make_exam_context(
        user_db, name="NCLEX-RN-Stage8-frac", length_kind="range",
        length_typical=100, length_min=85, length_max=150,
    )
    sys_id = _make_root_system_for_exam(
        user_db, "NCLEX-RN-Stage8-frac", "Adult Health",
        weight_low=100, weight_high=100,
    )
    c1_id, e1 = _make_child_for_exam(
        user_db, "NCLEX-RN-Stage8-frac", "Chunk1", sys_id,
        relative_weight=33.33,
    )
    c2_id, e2 = _make_child_for_exam(
        user_db, "NCLEX-RN-Stage8-frac", "Chunk2", sys_id,
        relative_weight=66.67,
    )

    rows = user_db.get_effective_question_counts(exam_id)
    edge_rows = {r['edge_id']: r for r in rows if r['parent_id'] == sys_id}
    assert isinstance(edge_rows[e1]['q_typical'], float)
    assert isinstance(edge_rows[e2]['q_typical'], float)
    assert edge_rows[e1]['q_typical'] == pytest.approx(33.33)
    assert edge_rows[e2]['q_typical'] == pytest.approx(66.67)
    # Both rows still carry is_adaptive=True.
    assert edge_rows[e1]['is_adaptive'] is True
    assert edge_rows[e2]['is_adaptive'] is True


def test_get_effective_question_counts_unknown_length_not_adaptive(user_db):
    """``length_kind='unknown'`` is non-adaptive even though every
    q_typical is None (the CAT branch requires a planning baseline)."""
    exam_id = _make_exam_context(
        user_db, name="UnknownLen", length_kind="unknown",
    )
    sys_id = _make_root_system_for_exam(
        user_db, "UnknownLen", "SysA",
    )
    _make_child_for_exam(
        user_db, "UnknownLen", "Topic", sys_id, relative_weight=50,
    )
    rows = user_db.get_effective_question_counts(exam_id)
    assert rows
    for r in rows:
        assert r.get('is_adaptive') is False
        assert r['q_typical'] is None


def test_allocator_adaptive_zero_budget(user_db):
    """Edge case: total_questions=0 under adaptive mode returns
    every edge at 0.0 (float) — not 0 (int)."""
    parent_id, [e1, e2] = _make_parent_with_children(user_db, [50.0, 50.0])
    alloc = user_db.allocate_questions_hamilton(
        parent_id, 0, is_adaptive=True,
    )
    assert alloc[e1] == 0.0
    assert alloc[e2] == 0.0
    # Both stored as float so the downstream formatter doesn't go
    # through the int branch.
    assert isinstance(alloc[e1], float)
    assert isinstance(alloc[e2], float)


def test_allocator_adaptive_no_weights(user_db):
    """Edge case: every sibling has weight 0 → allocations all 0.0
    in adaptive mode."""
    parent_id, [e1, e2] = _make_parent_with_children(user_db, [0.0, 0.0])
    alloc = user_db.allocate_questions_hamilton(
        parent_id, 100, is_adaptive=True,
    )
    assert alloc[e1] == 0.0
    assert alloc[e2] == 0.0
    assert isinstance(alloc[e1], float)
