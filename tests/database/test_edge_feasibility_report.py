"""Tests for Stage 7 of the Hierarchical Weight Allocation plan.

Covers the read-side interval-rounding feasibility checker:

* :meth:`HierarchyMixin.validate_hierarchy_feasibility` — per-parent
  report describing whether the children's [low, high] ranges fit
  cleanly inside the parent's range, including the rounding-class
  infeasibility case (``Σ⌈child_lo·N/100⌉ > ⌊parent_hi·N/100⌋``).
* :meth:`HierarchyMixin.validate_hierarchy_feasibility_recursive` —
  walks the whole tree and returns a per-parent dict for the tree
  editor's warning-dot rendering.

Reference: ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``
§"Stage 7"; ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``
§3.5 (save-then-warn).

Fixture style mirrors ``tests/database/test_question_allocation_bridge.py``.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional, Tuple

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
        username="stage7_user",
        display_name="Stage 7 User",
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
    length_typical: Optional[int] = 100,
) -> int:
    """Create an exam context with a configured length triple. Returns the
    exam_context_id."""
    ctx = user_db.create_exam_context(
        exam_name=name,
        exam_description=f"Stage 7 fixture exam: {name}",
    )
    if length_kind == "unknown":
        return ctx.id
    if length_kind == "fixed":
        user_db.update_exam_length(
            ctx.id,
            kind="fixed",
            min=length_typical,
            max=length_typical,
            typical=length_typical,
        )
    else:
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
    """Create a top-level System node with explicit exam_weight_low/high."""
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


def _make_child_with_range(
    user_db,
    exam_name: str,
    name: str,
    parent_id: int,
    *,
    weight_low: float,
    weight_high: float,
    relative_weight: Optional[float] = None,
) -> Tuple[int, int]:
    """Create a child node with an absolute [low, high] range AND the edge
    to ``parent_id`` carrying the per-edge weight metadata.

    Returns ``(child_id, edge_id)``.
    """
    child = user_db.create_subject_node_with_weight(
        exam_context=exam_name,
        name=name,
        level_type="Topic",
        parent_id=parent_id,
        exam_weight_low=weight_low,
        exam_weight_high=weight_high,
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
    if relative_weight is not None:
        user_db.execute(
            "UPDATE subject_edges SET relative_weight = ? WHERE id = ?",
            (relative_weight, edge_id),
        )
        user_db.conn.commit()
    return child.id, edge_id


# ---------------------------------------------------------------- status='ok'


def test_status_ok_when_children_sum_within_range(user_db):
    """Three children summing to 95% under a parent with range 90-105%,
    length=100. Children's [low, high] fits inside parent's range → 'ok'."""
    exam_id = _make_exam_context(
        user_db, name="OK Exam", length_kind="fixed", length_typical=100
    )
    sys_id = _make_root_system(
        user_db, "OK Exam", "ParentSys", weight_low=90, weight_high=105
    )
    # Three children — explicit absolute ranges that sum to 95% (low) /
    # 95% (high). Sits inside parent's 90-105%.
    _make_child_with_range(
        user_db, "OK Exam", "ChildA", sys_id,
        weight_low=30, weight_high=30, relative_weight=30,
    )
    _make_child_with_range(
        user_db, "OK Exam", "ChildB", sys_id,
        weight_low=30, weight_high=30, relative_weight=30,
    )
    _make_child_with_range(
        user_db, "OK Exam", "ChildC", sys_id,
        weight_low=35, weight_high=35, relative_weight=35,
    )

    report = user_db.validate_hierarchy_feasibility(sys_id, 100)

    assert report['status'] == 'ok', f"Expected 'ok', got {report!r}"
    assert report['violators'] == []


# ---------------------------------------------------------------- status='under'


def test_status_under_when_children_sum_below_parent_low(user_db):
    """Children sum to 50% under a parent with range 90-100% → 'under'.

    children_high_sum_q < parent_low_q.
    """
    exam_id = _make_exam_context(
        user_db, name="Under Exam", length_kind="fixed", length_typical=100
    )
    sys_id = _make_root_system(
        user_db, "Under Exam", "UnderParent",
        weight_low=90, weight_high=100,
    )
    _make_child_with_range(
        user_db, "Under Exam", "ChildA", sys_id,
        weight_low=20, weight_high=20, relative_weight=20,
    )
    _make_child_with_range(
        user_db, "Under Exam", "ChildB", sys_id,
        weight_low=30, weight_high=30, relative_weight=30,
    )

    report = user_db.validate_hierarchy_feasibility(sys_id, 100)

    assert report['status'] == 'under', f"Expected 'under', got {report!r}"
    # Parent low = ⌊90·100/100⌋ = 90. Children high sum = 50% → ceil(50)=50.
    assert report['parent_low_q'] == 90
    assert report['children_high_sum_q'] == 50
    assert report['children_high_sum_q'] < report['parent_low_q']
    # Under-allocation per spec: no per-child violators.
    assert report['violators'] == []


# ---------------------------------------------------------------- status='over'


def test_status_over_when_children_sum_above_parent_high(user_db):
    """Children sum to 110% under a parent with range 80-90% → 'over'."""
    exam_id = _make_exam_context(
        user_db, name="Over Exam", length_kind="fixed", length_typical=100
    )
    sys_id = _make_root_system(
        user_db, "Over Exam", "OverParent",
        weight_low=80, weight_high=90,
    )
    _make_child_with_range(
        user_db, "Over Exam", "ChildA", sys_id,
        weight_low=40, weight_high=40, relative_weight=40,
    )
    _make_child_with_range(
        user_db, "Over Exam", "ChildB", sys_id,
        weight_low=40, weight_high=40, relative_weight=40,
    )
    _make_child_with_range(
        user_db, "Over Exam", "ChildC", sys_id,
        weight_low=30, weight_high=30, relative_weight=30,
    )

    report = user_db.validate_hierarchy_feasibility(sys_id, 100)

    assert report['status'] == 'over', f"Expected 'over', got {report!r}"
    assert report['children_low_sum_pct'] == pytest.approx(110.0)


# ---------------------------------------------------------------- status='infeasible'


def test_status_infeasible_rounding_class(user_db):
    """5 children each with low=18% under a parent at 90-99%, N=10.

    Design: percentages COULD fit (Σ child low = 90% ≤ parent high
    99%), but the rounded integer counts cannot:

    * ``parent_high_q = ⌊99·10/100⌋ = ⌊9.9⌋ = 9``
    * ``Σ ⌈18·10/100⌉ = Σ ⌈1.8⌉ = Σ 2 = 10``
    * 10 > 9 → status='infeasible' (rounding-class violation, not the
      simpler 'over' case).

    This is the canonical genuine-infeasibility case from design §3.5:
    the user's weights look reasonable in percent space but the integer
    item-count constraint is unsatisfiable. The fix is "round more
    aggressively" rather than "reduce a weight".
    """
    exam_id = _make_exam_context(
        user_db, name="Infeasible Exam", length_kind="fixed", length_typical=10
    )
    sys_id = _make_root_system(
        user_db, "Infeasible Exam", "InfParent",
        weight_low=90, weight_high=99,
    )
    # 5 children, each at 18% (no absolute range — helper uses rw for
    # both low and high).
    for i in range(5):
        _make_child_with_range(
            user_db, "Infeasible Exam", f"Child{i}", sys_id,
            weight_low=18, weight_high=18, relative_weight=18,
        )

    report = user_db.validate_hierarchy_feasibility(sys_id, 10)

    assert report['status'] == 'infeasible', (
        f"Expected 'infeasible', got {report!r}"
    )
    # parent_high_q = ⌊99·10/100⌋ = 9
    assert report['parent_high_q'] == 9
    # Σ ⌈18·10/100⌉ = Σ⌈1.8⌉ = Σ 2 = 10
    assert report['children_low_sum_q'] == 10
    assert report['children_low_sum_q'] > report['parent_high_q']
    # Percentages alone DON'T over-sum (90% ≤ 99%) — confirms this is
    # the rounding-class case, not the simple over case.
    assert report['children_low_sum_pct'] == pytest.approx(90.0)


# ---------------------------------------------------------------- violators


def test_violators_populated_for_over(user_db):
    """The 'over' case lists per-child violators with edge_id + child_id."""
    exam_id = _make_exam_context(
        user_db, name="Over-Vios Exam", length_kind="fixed", length_typical=100
    )
    sys_id = _make_root_system(
        user_db, "Over-Vios Exam", "OverVioParent",
        weight_low=80, weight_high=90,
    )
    c1, e1 = _make_child_with_range(
        user_db, "Over-Vios Exam", "ChildA", sys_id,
        weight_low=40, weight_high=40, relative_weight=40,
    )
    c2, e2 = _make_child_with_range(
        user_db, "Over-Vios Exam", "ChildB", sys_id,
        weight_low=40, weight_high=40, relative_weight=40,
    )
    c3, e3 = _make_child_with_range(
        user_db, "Over-Vios Exam", "ChildC", sys_id,
        weight_low=30, weight_high=30, relative_weight=30,
    )

    report = user_db.validate_hierarchy_feasibility(sys_id, 100)

    assert report['status'] == 'over'
    assert len(report['violators']) == 3, (
        f"Expected all 3 contributing edges in violators; got {report['violators']!r}"
    )
    edge_ids_in_violators = {v['edge_id'] for v in report['violators']}
    assert edge_ids_in_violators == {e1, e2, e3}
    child_ids_in_violators = {v['child_id'] for v in report['violators']}
    assert child_ids_in_violators == {c1, c2, c3}
    for v in report['violators']:
        assert 'child_name' in v
        assert 'reason' in v
        assert isinstance(v['reason'], str) and len(v['reason']) > 0


# ---------------------------------------------------------------- recursive


def test_feasibility_recursive_walks_whole_tree(user_db):
    """Small DAG with 3 parents → recursive variant returns 3 reports."""
    exam_id = _make_exam_context(
        user_db, name="Recursive Exam",
        length_kind="fixed", length_typical=100,
    )
    # Parent A: 100% with 3 children at 33/33/34 → 'ok'
    sys_a = _make_root_system(
        user_db, "Recursive Exam", "SysA",
        weight_low=100, weight_high=100,
    )
    _make_child_with_range(
        user_db, "Recursive Exam", "A-Child1", sys_a,
        weight_low=33, weight_high=33, relative_weight=33,
    )
    _make_child_with_range(
        user_db, "Recursive Exam", "A-Child2", sys_a,
        weight_low=33, weight_high=33, relative_weight=33,
    )
    _make_child_with_range(
        user_db, "Recursive Exam", "A-Child3", sys_a,
        weight_low=34, weight_high=34, relative_weight=34,
    )

    # Parent B: 50% with one child at 80% → 'over' (80 > 50)
    sys_b = _make_root_system(
        user_db, "Recursive Exam", "SysB",
        weight_low=40, weight_high=50,
    )
    _make_child_with_range(
        user_db, "Recursive Exam", "B-Child1", sys_b,
        weight_low=80, weight_high=80, relative_weight=80,
    )

    # Parent C: 50% with one child at 10% → 'under' (10 < 50)
    sys_c = _make_root_system(
        user_db, "Recursive Exam", "SysC",
        weight_low=40, weight_high=50,
    )
    _make_child_with_range(
        user_db, "Recursive Exam", "C-Child1", sys_c,
        weight_low=10, weight_high=10, relative_weight=10,
    )

    reports = user_db.validate_hierarchy_feasibility_recursive(exam_id)

    # All three parents should appear as keys.
    assert sys_a in reports
    assert sys_b in reports
    assert sys_c in reports
    assert reports[sys_a]['status'] == 'ok'
    assert reports[sys_b]['status'] == 'over'
    assert reports[sys_c]['status'] == 'under'


# ---------------------------------------------------------------- length_unknown


def test_feasibility_skipped_when_length_unknown(user_db):
    """exam length_kind='unknown' → integer feasibility check skipped.

    The recursive walker still reports — but the rounding-class
    infeasibility branch cannot fire (N=0 in the helper). Percent-only
    over/under checks still apply.

    For this test, configure parent + children such that the
    percent-only checks ALSO pass (sum within range). Expected status:
    'ok'.
    """
    exam_id = _make_exam_context(
        user_db, name="Unknown Exam", length_kind="unknown",
        length_typical=None,
    )
    sys_id = _make_root_system(
        user_db, "Unknown Exam", "UnknownSys",
        weight_low=90, weight_high=100,
    )
    _make_child_with_range(
        user_db, "Unknown Exam", "ChildA", sys_id,
        weight_low=30, weight_high=30, relative_weight=30,
    )
    _make_child_with_range(
        user_db, "Unknown Exam", "ChildB", sys_id,
        weight_low=30, weight_high=30, relative_weight=30,
    )
    _make_child_with_range(
        user_db, "Unknown Exam", "ChildC", sys_id,
        weight_low=35, weight_high=35, relative_weight=35,
    )

    # Direct call with length_typical=0 should also return ok (matches
    # the bridge's short-circuit path).
    report = user_db.validate_hierarchy_feasibility(sys_id, 0)
    assert report['status'] == 'ok', (
        f"length=0 should never trigger infeasibility; got {report!r}"
    )

    # Recursive walker with the unknown-length exam.
    reports = user_db.validate_hierarchy_feasibility_recursive(exam_id)
    assert sys_id in reports
    # Status should be 'ok' (no infeasibility check + percent sum 95% is
    # within parent's 90-100% range).
    assert reports[sys_id]['status'] == 'ok'


def test_validate_feasibility_no_siblings_returns_ok(user_db):
    """A parent with no outgoing edges returns 'ok' (nothing to check)."""
    exam_id = _make_exam_context(
        user_db, name="No-Children Exam",
        length_kind="fixed", length_typical=100,
    )
    sys_id = _make_root_system(
        user_db, "No-Children Exam", "LonelyParent",
        weight_low=10, weight_high=10,
    )

    report = user_db.validate_hierarchy_feasibility(sys_id, 100)

    assert report['status'] == 'ok'
    assert report['violators'] == []
    assert report['children_low_sum_q'] == 0
