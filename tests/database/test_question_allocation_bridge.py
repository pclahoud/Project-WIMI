"""Tests for Stage 5 of the Hierarchical Weight Allocation plan.

Covers the read-side question-allocation API on ``HierarchyMixin``:

* :meth:`HierarchyMixin.get_effective_question_counts` — whole-tree
  per-edge question count computation, including the
  ``length_kind='unknown'`` degradation contract and polyhierarchy
  multi-parent rows.
* Per-parent allocation via :meth:`HierarchyMixin.allocate_questions_hamilton`
  composed into the get_effective_question_counts walk.
* Anchored-edge behavior in allocations (delegated to the Stage 1
  allocator's contract).

Reference: ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``
§"Stage 5"; ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``
§7.5.

Fixture style mirrors ``tests/database/test_hamilton_allocation.py`` and
``tests/database/test_edge_anchor_semantics.py`` — a fully composed
``UserDatabase`` against a per-test temporary path, world built via the
public mixin API.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional

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
        username="stage5_user",
        display_name="Stage 5 User",
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
    name: str = "USMLE Step 1",
    length_kind: str = "fixed",
    length_typical: Optional[int] = 280,
) -> int:
    """Create an exam context with a configured length triple. Returns
    the exam_context_id."""
    ctx = user_db.create_exam_context(
        exam_name=name,
        exam_description=f"Stage 5 fixture exam: {name}",
    )
    if length_kind == "unknown":
        return ctx.id
    # Both fixed and range need a length_typical; in fixed mode the
    # min/max all equal the typical.
    if length_kind == "fixed":
        user_db.update_exam_length(
            ctx.id,
            kind="fixed",
            min=length_typical,
            max=length_typical,
            typical=length_typical,
        )
    else:  # range
        user_db.update_exam_length(
            ctx.id,
            kind="range",
            min=int(length_typical * 0.8),
            max=int(length_typical * 1.2),
            typical=length_typical,
        )
    return ctx.id


def _make_root_system(
    user_db,
    exam_name: str,
    name: str,
    *,
    weight_low: float = 100.0,
    weight_high: float = 100.0,
) -> int:
    """Create a top-level System node with explicit exam_weight_low/high.

    A System has no parent edge — it's a root in subject_edges.
    """
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


def _make_child(
    user_db,
    exam_name: str,
    name: str,
    parent_id: int,
    *,
    relative_weight: Optional[float] = None,
    is_anchor: bool = False,
) -> tuple[int, int]:
    """Create a child node + the edge to ``parent_id`` carrying the
    requested per-edge weight metadata.

    Returns ``(child_id, edge_id)``. The edge is set via direct SQL
    after creation because the per-edge writer is still landing across
    Stages 2/3 and the create-with-weight helper still writes the
    legacy node-level fields.
    """
    child = user_db.create_subject_node_with_weight(
        exam_context=exam_name,
        name=name,
        level_type="Topic",
        parent_id=parent_id,
        relative_weight=relative_weight,
        weight_source="user_defined",
    )
    # The parent-id pathway in create_subject_node_with_weight inserts
    # an edge via the m004 backfill or in-app code; locate it.
    edge_row = user_db.fetchone(
        "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
        (parent_id, child.id),
    )
    if edge_row is None:
        # The create path didn't auto-edge; add one explicitly.
        edge = user_db.add_edge(parent_id, child.id, is_primary=True)
        edge_id = edge.id
    else:
        edge_id = edge_row['id']

    # Stamp per-edge weight metadata so the read path returns what the
    # test expects.
    user_db.execute(
        "UPDATE subject_edges SET relative_weight = ?, is_anchor = ?, "
        "weight_source = 'user_explicit' WHERE id = ?",
        (relative_weight, bool(is_anchor), edge_id),
    )
    user_db.conn.commit()
    return child.id, edge_id


# ---------------------------------------------------------------- get_effective_question_counts


def test_get_effective_question_counts_returns_q_typical_for_fixed_length(user_db):
    """USMLE Step 1 (length=280), 3 children with weights 30/30/40 under a
    100% parent. Assert q_typical per child sums to 280."""
    exam_id = _make_exam_context(
        user_db, name="USMLE Step 1", length_kind="fixed", length_typical=280
    )
    sys_id = _make_root_system(
        user_db, "USMLE Step 1", "Cardiovascular", weight_low=100, weight_high=100
    )
    c1_id, _ = _make_child(user_db, "USMLE Step 1", "Topic1", sys_id, relative_weight=30)
    c2_id, _ = _make_child(user_db, "USMLE Step 1", "Topic2", sys_id, relative_weight=30)
    c3_id, _ = _make_child(user_db, "USMLE Step 1", "Topic3", sys_id, relative_weight=40)

    rows = user_db.get_effective_question_counts(exam_id)

    # Pick out the child rows for the System we just built.
    children_rows = [r for r in rows if r['parent_id'] == sys_id]
    assert len(children_rows) == 3

    total = sum(r['q_typical'] for r in children_rows)
    # The root System carries 100% range, so the children sum should
    # equal the exam length (280) modulo Hamilton rounding (sum is
    # exact by construction of the allocator's leftover distribution).
    assert total == 280, (
        f"Expected children q_typical to sum to 280, got {total}. "
        f"rows={children_rows}"
    )

    # Every child should have non-null q_typical (length_kind='fixed').
    for r in children_rows:
        assert r['q_typical'] is not None
        assert r['q_typical'] > 0


def test_get_effective_question_counts_handles_unknown_length(user_db):
    """length_kind='unknown' exam: q_typical/low/high are all NULL."""
    exam_id = _make_exam_context(
        user_db, name="Custom Exam", length_kind="unknown", length_typical=None
    )
    sys_id = _make_root_system(user_db, "Custom Exam", "SysA")
    _make_child(user_db, "Custom Exam", "ChildA", sys_id, relative_weight=50)
    _make_child(user_db, "Custom Exam", "ChildB", sys_id, relative_weight=50)

    rows = user_db.get_effective_question_counts(exam_id)
    assert len(rows) >= 2
    for r in rows:
        assert r['q_typical'] is None, (
            f"Expected NULL q_typical under length_kind='unknown', "
            f"got {r['q_typical']} for edge {r['edge_id']}"
        )
        assert r['q_low'] is None
        assert r['q_high'] is None


def test_get_effective_question_counts_walks_polyhierarchy(user_db):
    """Child node with 2 parent edges returns 2 rows (one per parent).

    Models the canonical multi-parent case from
    ``HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`` §1 (Hypertension lives
    under both Cardio and Pregnancy with different weights).
    """
    exam_id = _make_exam_context(
        user_db, name="USMLE Step 1", length_kind="fixed", length_typical=280
    )
    cardio_id = _make_root_system(
        user_db, "USMLE Step 1", "Cardiovascular", weight_low=10, weight_high=10
    )
    preg_id = _make_root_system(
        user_db, "USMLE Step 1", "Pregnancy", weight_low=5, weight_high=5
    )

    # Hypertension primary under Cardio at 25%, also under Pregnancy at 5%.
    htn_id, edge_cardio = _make_child(
        user_db, "USMLE Step 1", "Hypertension", cardio_id, relative_weight=25
    )
    # Add a second parent edge.
    edge_preg = user_db.add_edge(preg_id, htn_id, is_primary=False)
    user_db.execute(
        "UPDATE subject_edges SET relative_weight = ?, is_anchor = ?, "
        "weight_source = 'user_explicit' WHERE id = ?",
        (5.0, False, edge_preg.id),
    )
    user_db.conn.commit()

    rows = user_db.get_effective_question_counts(exam_id)

    htn_rows = [r for r in rows if r['child_id'] == htn_id]
    assert len(htn_rows) == 2, (
        f"Expected 2 polyhierarchy rows for Hypertension, got {len(htn_rows)}. "
        f"rows={htn_rows}"
    )

    parents = {r['parent_id'] for r in htn_rows}
    assert parents == {cardio_id, preg_id}, (
        f"Expected both Cardio and Pregnancy as parents, got {parents}"
    )

    # The Cardio edge: ~25% of 10% of 280 ≈ 7 questions (10*0.25*2.8).
    # The Pregnancy edge: ~5% of 5% of 280 ≈ 1 question.
    cardio_row = next(r for r in htn_rows if r['parent_id'] == cardio_id)
    preg_row = next(r for r in htn_rows if r['parent_id'] == preg_id)
    assert cardio_row['q_typical'] is not None
    assert preg_row['q_typical'] is not None
    # Cardio path should be greater than Pregnancy path under these
    # weights.
    assert cardio_row['q_typical'] > preg_row['q_typical']


def test_get_effective_question_counts_unknown_exam_context_raises(user_db):
    """A non-existent exam_context_id surfaces a ValueError."""
    with pytest.raises(ValueError, match="Exam context .* not found"):
        user_db.get_effective_question_counts(99999)


def test_get_effective_question_counts_empty_tree(user_db):
    """No subject edges yet → empty list (not an error)."""
    exam_id = _make_exam_context(
        user_db, name="Empty Exam", length_kind="fixed", length_typical=100
    )
    rows = user_db.get_effective_question_counts(exam_id)
    assert rows == []


# ---------------------------------------------------------------- Hamilton integration


def test_get_question_allocation_uses_hamilton(user_db):
    """Verify the integer allocation matches
    :meth:`HierarchyMixin.allocate_questions_hamilton` for the same
    inputs.

    The whole-tree endpoint walks the DAG and calls the allocator
    per-parent; this test asserts the per-edge counts agree with a
    direct allocator call on the same parent budget.
    """
    exam_id = _make_exam_context(
        user_db, name="USMLE Step 1", length_kind="fixed", length_typical=280
    )
    sys_id = _make_root_system(
        user_db, "USMLE Step 1", "Cardiovascular", weight_low=100, weight_high=100
    )
    c1_id, e1 = _make_child(
        user_db, "USMLE Step 1", "Arrhythmias", sys_id, relative_weight=30
    )
    c2_id, e2 = _make_child(
        user_db, "USMLE Step 1", "Ischemia", sys_id, relative_weight=30
    )
    c3_id, e3 = _make_child(
        user_db, "USMLE Step 1", "Hypertension", sys_id, relative_weight=40
    )

    # The System carries 100% range, so the parent budget is the full
    # exam length (280).
    direct = user_db.allocate_questions_hamilton(sys_id, 280)
    rows = user_db.get_effective_question_counts(exam_id)
    children_rows = {r['edge_id']: r['q_typical'] for r in rows if r['parent_id'] == sys_id}

    assert children_rows[e1] == direct[e1]
    assert children_rows[e2] == direct[e2]
    assert children_rows[e3] == direct[e3]


def test_get_question_allocation_anchored_child(user_db):
    """Anchored edge's allocation is fixed; the remainder is distributed
    across the non-anchored siblings per the Stage 1 contract."""
    exam_id = _make_exam_context(
        user_db, name="USMLE Step 1", length_kind="fixed", length_typical=100
    )
    sys_id = _make_root_system(
        user_db, "USMLE Step 1", "SysA", weight_low=100, weight_high=100
    )
    # 50% anchored, 30% and 20% non-anchored.
    c1_id, e_anchor = _make_child(
        user_db, "USMLE Step 1", "Anchored", sys_id,
        relative_weight=50, is_anchor=True,
    )
    c2_id, e2 = _make_child(
        user_db, "USMLE Step 1", "Auto1", sys_id, relative_weight=30
    )
    c3_id, e3 = _make_child(
        user_db, "USMLE Step 1", "Auto2", sys_id, relative_weight=20
    )

    rows = user_db.get_effective_question_counts(exam_id)
    by_edge = {r['edge_id']: r for r in rows if r['parent_id'] == sys_id}

    # Anchored at 50% of 100 → 50 questions.
    assert by_edge[e_anchor]['q_typical'] == 50
    # Remaining 50 split 30/20 → 30 and 20.
    assert by_edge[e2]['q_typical'] == 30
    assert by_edge[e3]['q_typical'] == 20

    # is_anchor flag carries through.
    assert by_edge[e_anchor]['is_anchor'] is True
    assert by_edge[e2]['is_anchor'] is False


# ---------------------------------------------------------------- get_subjects_with_effective_weights extension


def test_get_subjects_with_effective_weights_attaches_q_typical(user_db):
    """The legacy effective-weights endpoint now carries ``q_typical``."""
    exam_id = _make_exam_context(
        user_db, name="USMLE Step 1", length_kind="fixed", length_typical=280
    )
    sys_id = _make_root_system(
        user_db, "USMLE Step 1", "Cardiovascular", weight_low=10, weight_high=10
    )

    result = user_db.get_subjects_with_effective_weights(exam_id, include_children=True)

    # Find our root.
    root = next(r for r in result if r['id'] == sys_id)
    assert 'q_typical' in root['weight']
    # 10% of 280 = 28.
    assert root['weight']['q_typical'] == 28


def test_get_subjects_with_effective_weights_unknown_length_returns_null_q(user_db):
    """When the exam has length_kind='unknown', q_typical is None across
    the tree (the no-op degradation path)."""
    exam_id = _make_exam_context(
        user_db, name="Custom Exam", length_kind="unknown", length_typical=None
    )
    sys_id = _make_root_system(user_db, "Custom Exam", "SysA")

    result = user_db.get_subjects_with_effective_weights(exam_id, include_children=False)
    root = next(r for r in result if r['id'] == sys_id)
    assert root['weight']['q_typical'] is None
