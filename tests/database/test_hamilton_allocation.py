"""Tests for Stage 1 of the Hierarchical Weight Allocation plan.

Exercises the Hamilton (Largest Remainder) allocator and weakness-score
helper added to ``HierarchyMixin``, plus the ``get_sibling_edges``
read-side helper added to ``EdgesMixin``. See
``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md`` §"Stage 1"
and ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`` §3.1
for the canonical specification.

Fixtures follow the pattern in ``tests/database/test_subject_edges.py``:
a fully composed ``UserDatabase`` against a per-test temporary path,
all rows constructed via the public mixin API rather than direct SQL.
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from database import MasterDatabase, UserDatabase
from database.exceptions import AllocationFeasibilityError


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
        username="hamilton_user",
        display_name="Hamilton Test User",
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


def _make_node(user_db, name: str) -> int:
    """Insert a subject_nodes row directly. Bypasses ``create_subject_node``
    so each test can build the exact DAG shape it needs and then attach
    edges via the public ``add_edge`` API."""
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, status) "
        "VALUES (?, ?, 'Topic', 'active')",
        ("USMLE", name),
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
    """Stamp weight metadata on an existing edge. Done via direct SQL
    because the public per-edge weight writer lands in Stage 3 of the
    implementation plan; for Stage 1 tests we construct the world by
    hand."""
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
) -> tuple:
    """Build one parent with ``len(weights)`` children, returning
    ``(parent_id, [edge_id, ...])`` ordered by insertion.

    Each child gets the corresponding entry from ``weights`` as its
    edge ``relative_weight``. Indices in ``anchored_indices`` get
    ``is_anchor=TRUE``.
    """
    anchored = set(anchored_indices or [])
    parent_id = _make_node(user_db, "Parent")
    edge_ids: List[int] = []
    for idx, weight in enumerate(weights):
        child_id = _make_node(user_db, f"Child_{idx}")
        edge = user_db.add_edge(parent_id, child_id, is_primary=True)
        _set_edge_weight(
            user_db,
            edge.id,
            weight,
            is_anchor=(idx in anchored),
        )
        edge_ids.append(edge.id)
    return parent_id, edge_ids


# ---------------------------------------------------------------- get_sibling_edges


def test_get_sibling_edges_returns_all_outgoing_edges(user_db):
    parent_id, [e1, e2, e3] = _make_parent_with_children(
        user_db, [33.0, 33.0, 34.0]
    )
    siblings = user_db.get_sibling_edges(parent_id)
    assert [s['edge_id'] for s in siblings] == [e1, e2, e3]
    weights = [s['relative_weight'] for s in siblings]
    assert weights == [33.0, 33.0, 34.0]
    assert all(s['child_name'].startswith("Child_") for s in siblings)


def test_get_sibling_edges_respects_exclude(user_db):
    parent_id, edges = _make_parent_with_children(user_db, [50.0, 50.0])
    siblings = user_db.get_sibling_edges(parent_id, exclude_edge_id=edges[0])
    assert [s['edge_id'] for s in siblings] == [edges[1]]


def test_get_sibling_edges_orders_by_display_then_id(user_db):
    parent_id = _make_node(user_db, "Parent")
    c1 = _make_node(user_db, "C1")
    c2 = _make_node(user_db, "C2")
    c3 = _make_node(user_db, "C3")
    e1 = user_db.add_edge(parent_id, c1, is_primary=True)
    e2 = user_db.add_edge(parent_id, c2)
    e3 = user_db.add_edge(parent_id, c3)
    # Set explicit display_order on every edge so we can verify the
    # ORDER BY is by display_order first (e3 < e2 < e1) rather than
    # by insertion id.
    user_db.execute(
        "UPDATE subject_edges SET display_order = 5 WHERE id = ?", (e1.id,)
    )
    user_db.execute(
        "UPDATE subject_edges SET display_order = 3 WHERE id = ?", (e2.id,)
    )
    user_db.execute(
        "UPDATE subject_edges SET display_order = 1 WHERE id = ?", (e3.id,)
    )
    user_db.conn.commit()

    siblings = user_db.get_sibling_edges(parent_id)
    assert [s['edge_id'] for s in siblings] == [e3.id, e2.id, e1.id]


def test_get_sibling_edges_skips_inactive_children(user_db):
    parent_id, edges = _make_parent_with_children(user_db, [50.0, 50.0])
    # Soft-delete the second child.
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = "
        "(SELECT child_id FROM subject_edges WHERE id = ?)",
        (edges[1],),
    )
    user_db.conn.commit()
    siblings = user_db.get_sibling_edges(parent_id)
    assert [s['edge_id'] for s in siblings] == [edges[0]]


# ---------------------------------------------------------------- Hamilton: scenarios from the plan


def test_hamilton_three_children_33_33_34(user_db):
    """10 questions, weights 33/33/34 → leftover goes to the heaviest weight."""
    parent_id, [e1, e2, e3] = _make_parent_with_children(
        user_db, [33.0, 33.0, 34.0]
    )
    alloc = user_db.allocate_questions_hamilton(parent_id, 10)

    # Quota rule: each gets floor(share) or floor(share)+1.
    # Exact shares: 3.30, 3.30, 3.40 → floors 3,3,3 → 1 leftover.
    # Largest fractional remainder is e3 (0.40 vs 0.30, 0.30) → wins.
    assert alloc == {e1: 3, e2: 3, e3: 4}
    assert sum(alloc.values()) == 10


def test_hamilton_three_equal_children_tiebreak_by_edge_id(user_db):
    """10 questions, three equal weights → leftover to lowest edge_id
    when no weakness signal differentiates them.
    """
    parent_id, [e1, e2, e3] = _make_parent_with_children(
        user_db, [33.33, 33.33, 33.33]
    )
    alloc = user_db.allocate_questions_hamilton(parent_id, 10)
    # Exact shares all 3.333, floors 3,3,3, leftover 1. Equal
    # remainders, neutral weakness, so tie-break rule 3 (lower
    # edge_id) takes the leftover.
    assert alloc[e1] == 4
    assert alloc[e2] == 3
    assert alloc[e3] == 3
    assert sum(alloc.values()) == 10


def test_hamilton_anchored_child_fixed(user_db):
    """10 questions, anchored child fixed at 5 → remaining 5 to non-anchored."""
    parent_id, [e_anchor, e2, e3] = _make_parent_with_children(
        user_db,
        [50.0, 30.0, 20.0],
        anchored_indices=[0],
    )
    # Anchor demands 50% of 10 = 5 questions. Remaining 5 split among
    # the two non-anchored children at weights 30 vs 20.
    # Exact shares: 30/(30+20)·5 = 3.0, 20/50·5 = 2.0 → floors 3,2,
    # leftover 0.
    alloc = user_db.allocate_questions_hamilton(parent_id, 10)
    assert alloc[e_anchor] == 5
    assert alloc[e2] == 3
    assert alloc[e3] == 2
    assert sum(alloc.values()) == 10


def test_hamilton_zero_total_weight_returns_all_zeros(user_db):
    """Sum of weights = 0 → no division-by-zero, every edge gets 0."""
    parent_id, edges = _make_parent_with_children(user_db, [0.0, 0.0, 0.0])
    alloc = user_db.allocate_questions_hamilton(parent_id, 10)
    assert alloc == {e: 0 for e in edges}


def test_hamilton_single_child_gets_all(user_db):
    parent_id, [edge] = _make_parent_with_children(user_db, [80.0])
    alloc = user_db.allocate_questions_hamilton(parent_id, 7)
    assert alloc == {edge: 7}


def test_hamilton_quota_rule_floor_or_floor_plus_one(user_db):
    """Property: every allocation is floor(share) or floor(share)+1."""
    weights = [12.5, 27.5, 30.0, 30.0]
    parent_id, edges = _make_parent_with_children(user_db, weights)
    total = 17  # arbitrary, gives non-integer shares
    alloc = user_db.allocate_questions_hamilton(parent_id, total)

    sum_w = sum(weights)
    for edge_id, weight in zip(edges, weights):
        exact = total * weight / sum_w
        floor = int(exact)
        assert alloc[edge_id] in (floor, floor + 1), (
            f"edge {edge_id}: got {alloc[edge_id]}, "
            f"expected {floor} or {floor + 1} for share {exact}"
        )
    assert sum(alloc.values()) == total


def test_hamilton_determinism_across_many_runs(user_db):
    """Same inputs ⇒ same outputs across 100 runs (no randomness)."""
    parent_id, _edges = _make_parent_with_children(
        user_db, [33.33, 33.33, 33.34, 0.001]
    )
    first = user_db.allocate_questions_hamilton(parent_id, 13)
    for _ in range(99):
        assert user_db.allocate_questions_hamilton(parent_id, 13) == first


def test_hamilton_weakness_tiebreak_wins_over_edge_id(user_db):
    """Equal fractional remainders → higher weakness wins, beating the
    lower-edge_id last-resort rule."""
    parent_id, [e1, e2, e3] = _make_parent_with_children(
        user_db, [33.33, 33.33, 33.33]
    )
    # Without weakness, e1 (lowest id) wins the leftover. Now feed a
    # lookup that flags e3 as the weakest topic — the leftover should
    # follow it.
    weakness = {e1: 0.1, e2: 0.1, e3: 5.0}
    alloc = user_db.allocate_questions_hamilton(
        parent_id, 10, weakness_lookup=weakness.__getitem__
    )
    assert alloc[e3] == 4
    assert alloc[e1] == 3
    assert alloc[e2] == 3


def test_hamilton_zero_total_questions_returns_all_zeros(user_db):
    parent_id, edges = _make_parent_with_children(user_db, [50.0, 50.0])
    alloc = user_db.allocate_questions_hamilton(parent_id, 0)
    assert alloc == {e: 0 for e in edges}


def test_hamilton_no_siblings_returns_empty(user_db):
    parent_id = _make_node(user_db, "ChildlessParent")
    assert user_db.allocate_questions_hamilton(parent_id, 100) == {}


def test_hamilton_single_non_anchored_after_anchors(user_db):
    """Two anchors plus one non-anchored sibling → non-anchored gets
    the entire remaining budget."""
    parent_id, [a1, a2, e3] = _make_parent_with_children(
        user_db, [10.0, 20.0, 70.0], anchored_indices=[0, 1]
    )
    # Anchors take 1 + 2 = 3 of 10. Remaining 7 → all to e3 (only
    # non-anchored sibling).
    alloc = user_db.allocate_questions_hamilton(parent_id, 10)
    assert alloc[a1] == 1
    assert alloc[a2] == 2
    assert alloc[e3] == 7
    assert sum(alloc.values()) == 10


def test_hamilton_anchored_with_null_weight_gets_zero(user_db):
    """An anchored edge whose ``relative_weight`` is NULL is treated
    as 0 questions — defensive against half-configured rows."""
    parent_id, [e1, e2] = _make_parent_with_children(user_db, [100.0, 0.0])
    # Re-stamp e2 as anchored with NULL weight.
    user_db.execute(
        "UPDATE subject_edges SET is_anchor = TRUE, relative_weight = NULL "
        "WHERE id = ?",
        (e2,),
    )
    user_db.conn.commit()
    alloc = user_db.allocate_questions_hamilton(parent_id, 10)
    assert alloc[e2] == 0
    assert alloc[e1] == 10


# ---------------------------------------------------------------- structurally bad input


def test_hamilton_negative_total_questions_raises(user_db):
    parent_id, _edges = _make_parent_with_children(user_db, [50.0, 50.0])
    with pytest.raises(AllocationFeasibilityError):
        user_db.allocate_questions_hamilton(parent_id, -5)


def test_hamilton_negative_relative_weight_raises(user_db):
    parent_id, [e1, e2] = _make_parent_with_children(user_db, [50.0, 50.0])
    user_db.execute(
        "UPDATE subject_edges SET relative_weight = -10 WHERE id = ?", (e2,)
    )
    user_db.conn.commit()
    with pytest.raises(AllocationFeasibilityError):
        user_db.allocate_questions_hamilton(parent_id, 10)


# ---------------------------------------------------------------- _largest_remainder unit tests


def test_largest_remainder_pure_function():
    """Helper is a pure static method — no DB access required."""
    from database.domains.hierarchy import HierarchyMixin

    # Three shares with distinct remainders, total 10. Floors 3,3,3
    # leave 1 leftover; the share with the largest remainder (0.5)
    # gets it.
    out = HierarchyMixin._largest_remainder(
        [(1, 3.5), (2, 3.3), (3, 3.2)],
        10,
        weakness_lookup=lambda _e: 1.0,
    )
    assert out == {1: 4, 2: 3, 3: 3}


def test_largest_remainder_handles_exact_integer_shares():
    """When floors already sum to total, no extra units are distributed."""
    from database.domains.hierarchy import HierarchyMixin

    out = HierarchyMixin._largest_remainder(
        [(1, 3.0), (2, 4.0), (3, 3.0)],
        10,
        weakness_lookup=lambda _e: 1.0,
    )
    assert out == {1: 3, 2: 4, 3: 3}


def test_largest_remainder_empty_input_returns_empty():
    """Defensive branch — pure helper handles empty share list safely."""
    from database.domains.hierarchy import HierarchyMixin

    out = HierarchyMixin._largest_remainder(
        [], 0, weakness_lookup=lambda _e: 1.0
    )
    assert out == {}


def test_compute_weakness_scores_handles_unknown_edge_id(user_db):
    """Defensive — caller passes a stale edge id; we return neutral 1.0."""
    # 999_999 is unlikely to exist in this freshly-created DB.
    scores = user_db.compute_weakness_scores([999_999])
    assert scores == {999_999: 1.0}


# ---------------------------------------------------------------- compute_weakness_scores


def test_compute_weakness_scores_returns_neutral_for_no_history(user_db):
    parent_id, edges = _make_parent_with_children(user_db, [50.0, 50.0])
    scores = user_db.compute_weakness_scores(edges)
    assert scores == {edges[0]: 1.0, edges[1]: 1.0}


def test_compute_weakness_scores_recent_mistake_outweighs_old(user_db):
    """An edge with one recent mistake scores higher than an edge with
    one old mistake (recency decay in action)."""
    parent_id, [e1, e2] = _make_parent_with_children(user_db, [50.0, 50.0])

    # Bootstrap a session/exam_context.
    cursor = user_db.execute(
        "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
        "VALUES (?, 'USMLE', 'Test')",
        (user_db.user_id,),
    )
    ec_id = cursor.lastrowid
    user_db.conn.commit()

    def _log_mistake(child_id: int, days_ago: int) -> None:
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        cur = user_db.execute(
            "INSERT INTO review_sessions "
            "(user_id, session_name, date_encountered, exam_context_id, "
            " total_questions, total_incorrect) "
            "VALUES (?, 'S', ?, ?, 1, 1)",
            (user_db.user_id, d, ec_id),
        )
        sid = cur.lastrowid
        cur = user_db.execute(
            "INSERT INTO question_entries "
            "(review_session_id, entry_order, user_answer, correct_answer) "
            "VALUES (?, 1, 'A', 'B')",
            (sid,),
        )
        eid = cur.lastrowid
        user_db.execute(
            "INSERT INTO entry_subject_mappings "
            "(question_entry_id, subject_node_id, mapping_type) "
            "VALUES (?, ?, 'primary')",
            (eid, child_id),
        )
        user_db.conn.commit()

    # e1's child gets a 1-day-old mistake; e2's child gets a 365-day-
    # old mistake. With 90-day half life, the old one decays to ~0.06
    # and the recent one is ~0.99.
    e1_child = user_db.fetchone(
        "SELECT child_id FROM subject_edges WHERE id = ?", (e1,)
    )['child_id']
    e2_child = user_db.fetchone(
        "SELECT child_id FROM subject_edges WHERE id = ?", (e2,)
    )['child_id']
    _log_mistake(e1_child, days_ago=1)
    _log_mistake(e2_child, days_ago=365)

    scores = user_db.compute_weakness_scores([e1, e2], half_life_days=90)
    assert scores[e1] > scores[e2]
    # Sanity: recent-day weight is close to 1, year-old weight much smaller.
    assert 0.8 < scores[e1] <= 1.0
    assert scores[e2] < 0.2


def test_compute_weakness_scores_empty_list_returns_empty(user_db):
    assert user_db.compute_weakness_scores([]) == {}


def test_compute_weakness_scores_invalid_half_life_raises(user_db):
    parent_id, edges = _make_parent_with_children(user_db, [50.0, 50.0])
    from database.exceptions import ValidationError
    with pytest.raises(ValidationError):
        user_db.compute_weakness_scores(edges, half_life_days=0)
    with pytest.raises(ValidationError):
        user_db.compute_weakness_scores(edges, half_life_days=-1)
