"""Tests for ``get_subject_hierarchy``'s polyhierarchy-aware traversal.

Companion to ``test_polyhierarchy_traversal.py`` (which covers the
recursive CTEs the analytics layer uses). This file covers the
tree-building helper the bridge / tree-editor consume — its contract is
documented in ``docs/planning/POLYHIERARCHY_MIGRATION.md`` §7.1:

* A node with multiple parent edges appears once under each parent.
* The primary appearance carries the subtree.
* Non-primary appearances are flagged with ``is_alias_appearance=True``
  and DO NOT recurse (alias chip without subtree duplication).
* Roots are nodes with no incoming ``subject_edges`` row (the legacy
  ``subject_nodes.parent_id`` column is intentionally ignored — m004
  backfilled an edge for every existing parent_id).
"""

from __future__ import annotations

import pytest


def _build_dvt_diamond(db) -> dict:
    """Build a small DAG modelled on the canonical USMLE example.

    Cardiovascular > diseases-of-the-veins > DVT (primary)
    Pregnancy > systemic-disorders > DVT (non-primary, via add_edge)

    Returns a dict of node ids for the assertions to reference.
    """
    exam = db.create_exam_context(
        exam_name="Polyhierarchy Test Exam",
        exam_description="Diamond DAG for DVT",
    )

    cardio = db.create_subject_node(
        exam_context="Polyhierarchy Test Exam",
        name="Cardiovascular System",
        level_type="System",
        parent_id=None,
        sort_order=1,
    )
    veins = db.create_subject_node(
        exam_context="Polyhierarchy Test Exam",
        name="diseases of the veins",
        level_type="Subsystem",
        parent_id=cardio.id,
        sort_order=1,
    )
    dvt = db.create_subject_node(
        exam_context="Polyhierarchy Test Exam",
        name="Deep venous thrombosis",
        level_type="Topic",
        parent_id=veins.id,
        sort_order=1,
    )

    pregnancy = db.create_subject_node(
        exam_context="Polyhierarchy Test Exam",
        name="Pregnancy",
        level_type="System",
        parent_id=None,
        sort_order=2,
    )
    systemic = db.create_subject_node(
        exam_context="Polyhierarchy Test Exam",
        name="systemic disorders affecting pregnancy",
        level_type="Subsystem",
        parent_id=pregnancy.id,
        sort_order=1,
    )
    # The whole point of the migration: same DVT row, second parent.
    db.add_edge(parent_id=systemic.id, child_id=dvt.id, is_primary=False)

    return {
        "exam": exam,
        "cardio": cardio.id,
        "veins": veins.id,
        "dvt": dvt.id,
        "pregnancy": pregnancy.id,
        "systemic": systemic.id,
    }


def _find_in_subtree(node, target_id):
    """DFS for a node id; returns the node-list path or None."""
    if node.id == target_id:
        return [node]
    for c in node.children or []:
        p = _find_in_subtree(c, target_id)
        if p:
            return [node] + p
    return None


def test_multi_parent_leaf_appears_under_each_parent(test_user):
    """DVT must surface in both Cardiovascular and Pregnancy subtrees."""
    ids = _build_dvt_diamond(test_user.db)
    roots = test_user.db.get_subject_hierarchy("Polyhierarchy Test Exam")

    cardio_root = next(r for r in roots if r.id == ids["cardio"])
    preg_root = next(r for r in roots if r.id == ids["pregnancy"])

    cardio_path = _find_in_subtree(cardio_root, ids["dvt"])
    preg_path = _find_in_subtree(preg_root, ids["dvt"])

    assert cardio_path is not None, "DVT should appear under Cardiovascular"
    assert preg_path is not None, "DVT should appear under Pregnancy"
    assert [n.id for n in cardio_path] == [ids["cardio"], ids["veins"], ids["dvt"]]
    assert [n.id for n in preg_path] == [ids["pregnancy"], ids["systemic"], ids["dvt"]]


def test_primary_appearance_has_alias_false(test_user):
    """The Cardiovascular path is the primary edge; alias flag is False."""
    ids = _build_dvt_diamond(test_user.db)
    roots = test_user.db.get_subject_hierarchy("Polyhierarchy Test Exam")
    cardio_root = next(r for r in roots if r.id == ids["cardio"])
    cardio_path = _find_in_subtree(cardio_root, ids["dvt"])
    assert cardio_path[-1].is_alias_appearance is False


def test_non_primary_appearance_has_alias_true(test_user):
    """The Pregnancy path was added via add_edge(is_primary=False)."""
    ids = _build_dvt_diamond(test_user.db)
    roots = test_user.db.get_subject_hierarchy("Polyhierarchy Test Exam")
    preg_root = next(r for r in roots if r.id == ids["pregnancy"])
    preg_path = _find_in_subtree(preg_root, ids["dvt"])
    assert preg_path[-1].is_alias_appearance is True


def test_alias_appearance_has_no_children(test_user):
    """Non-primary appearances must not recurse into the subtree.

    The plan §7.1 explicitly calls for this: showing the descendants
    under every alias parent multiplies the tree size and isn't what
    the SNOMED-style renderer wants — the canonical primary appearance
    carries the children, alias appearances are leaves with a chip.
    """
    ids = _build_dvt_diamond(test_user.db)
    # Add a child under DVT so the canonical appearance has a subtree
    # to compare against.
    test_user.db.create_subject_node(
        exam_context="Polyhierarchy Test Exam",
        name="DVT subtopic",
        level_type="Topic",
        parent_id=ids["dvt"],
        sort_order=1,
    )

    roots = test_user.db.get_subject_hierarchy("Polyhierarchy Test Exam")
    cardio_root = next(r for r in roots if r.id == ids["cardio"])
    preg_root = next(r for r in roots if r.id == ids["pregnancy"])

    cardio_dvt = _find_in_subtree(cardio_root, ids["dvt"])[-1]
    preg_dvt = _find_in_subtree(preg_root, ids["dvt"])[-1]

    assert len(cardio_dvt.children) == 1, "primary appearance carries children"
    assert preg_dvt.children == [], "alias appearance is a leaf"


def test_legacy_single_parent_unchanged(test_user):
    """A node with a single (auto-primary) edge behaves like the old tree.

    No alias flag, no duplication, normal recursion.
    """
    test_user.db.create_exam_context(
        exam_name="Single Parent Exam",
        exam_description="Simple linear hierarchy",
    )
    sys = test_user.db.create_subject_node(
        exam_context="Single Parent Exam",
        name="System",
        level_type="System",
        parent_id=None,
        sort_order=1,
    )
    sub = test_user.db.create_subject_node(
        exam_context="Single Parent Exam",
        name="Subsystem",
        level_type="Subsystem",
        parent_id=sys.id,
        sort_order=1,
    )
    leaf = test_user.db.create_subject_node(
        exam_context="Single Parent Exam",
        name="Leaf",
        level_type="Topic",
        parent_id=sub.id,
        sort_order=1,
    )

    roots = test_user.db.get_subject_hierarchy("Single Parent Exam")
    assert len(roots) == 1
    assert roots[0].id == sys.id
    assert roots[0].is_alias_appearance is False
    assert len(roots[0].children) == 1
    assert roots[0].children[0].id == sub.id
    assert roots[0].children[0].is_alias_appearance is False
    assert len(roots[0].children[0].children) == 1
    assert roots[0].children[0].children[0].id == leaf.id
    assert roots[0].children[0].children[0].is_alias_appearance is False


def test_root_detection_via_subject_edges_not_parent_id(test_user):
    """A node is a root iff it has no incoming subject_edges row.

    The legacy parent_id column is ignored. This guards against future
    schema drift where parent_id might still be set on a node that has
    been re-parented via edge-only operations.
    """
    test_user.db.create_exam_context(
        exam_name="Root Detection Exam",
        exam_description="",
    )
    a = test_user.db.create_subject_node(
        exam_context="Root Detection Exam",
        name="A", level_type="System", parent_id=None, sort_order=1,
    )
    b = test_user.db.create_subject_node(
        exam_context="Root Detection Exam",
        name="B", level_type="System", parent_id=None, sort_order=2,
    )
    # Both A and B start as roots (no parent_id, no incoming edges).
    roots = test_user.db.get_subject_hierarchy("Root Detection Exam")
    assert {r.id for r in roots} == {a.id, b.id}

    # Make B a child of A via add_edge — B should drop out of the root list.
    test_user.db.add_edge(parent_id=a.id, child_id=b.id, is_primary=True)
    roots = test_user.db.get_subject_hierarchy("Root Detection Exam")
    assert {r.id for r in roots} == {a.id}
    a_root = roots[0]
    assert {c.id for c in a_root.children} == {b.id}
