"""Unit tests for the named-seeder registry in ``wimi_test.db.seeders``.

These tests build a :class:`UserDatabase` directly (via the standard
test fixtures) and run the registered seeders against it. They do not
spawn a real WIMI subprocess, so they're fast — unlike the scenario
tests under ``tests/wimi_test/scenarios/``, which are gated behind
``@pytest.mark.slow``.

The full-outline seeder takes ~30 seconds in dev mode (it materialises
~2,500 ``subject_nodes`` plus their multi-parent edges) so its test is
marked ``@pytest.mark.slow``. ``seed_minimal`` is fast and stays
unmarked.
"""

from __future__ import annotations

import pytest

from wimi_test.db.seeders import (
    get_seeder,
    seed_minimal,
    seed_usmle_step1_outline,
)


def test_get_seeder_lists_known_names() -> None:
    """Both shipped seeders are discoverable by name from the registry."""
    assert get_seeder("minimal") is seed_minimal
    assert get_seeder("usmle_step1_outline") is seed_usmle_step1_outline


def test_get_seeder_unknown_name_raises_with_valid_list() -> None:
    """Unknown name → KeyError mentioning the valid options for discoverability."""
    with pytest.raises(KeyError) as exc:
        get_seeder("not_a_real_seeder")
    assert "minimal" in str(exc.value)
    assert "usmle_step1_outline" in str(exc.value)


def test_seed_minimal_creates_one_exam_context(tmp_path) -> None:
    """``seed_minimal`` produces exactly one exam context and no subjects."""
    from database.user_db import UserDatabase

    db = UserDatabase(
        db_path=tmp_path / "user.db",
        user_id=1,
        username="minimal_test",
    )
    try:
        seed_minimal(db)
        contexts = db.fetchall("SELECT id FROM exam_contexts")
        assert len(contexts) == 1
        nodes = db.fetchall("SELECT id FROM subject_nodes")
        assert len(nodes) == 0
    finally:
        db.close()


@pytest.mark.slow
def test_seed_usmle_step1_outline_full_polyhierarchy(tmp_path) -> None:
    """Full-outline seeder loads ~2,500 nodes with multi-parent edges.

    Exercises the canonical polyhierarchy demo from
    ``docs/planning/POLYHIERARCHY_MIGRATION.md`` Section 1: hypertension
    and deep venous thrombosis must each end up with two or more parent
    edges. We don't assert on exact counts (the parser may legitimately
    grow new topic detections over time), only on lower bounds and the
    presence of the canonical multi-parent leaves.
    """
    from database.user_db import UserDatabase

    db = UserDatabase(
        db_path=tmp_path / "user.db",
        user_id=1,
        username="outline_test",
    )
    try:
        seed_usmle_step1_outline(db)

        # Exam context.
        contexts = db.fetchall("SELECT id, exam_name FROM exam_contexts")
        assert len(contexts) == 1
        assert "USMLE Step 1" in contexts[0]["exam_name"]

        # Lower bounds — the parser finds 2,544 topics today and 121
        # multi-parent names; assert generously below those so cosmetic
        # parser tweaks don't break this test.
        node_count = db.fetchone("SELECT COUNT(*) AS c FROM subject_nodes")["c"]
        edge_count = db.fetchone("SELECT COUNT(*) AS c FROM subject_edges")["c"]
        multi_parent_count = len(
            db.fetchall(
                "SELECT child_id FROM subject_edges "
                "GROUP BY child_id HAVING COUNT(*) >= 2"
            )
        )
        assert node_count >= 1000, f"Expected ≥1000 subject_nodes, got {node_count}"
        assert edge_count >= 1000, f"Expected ≥1000 subject_edges, got {edge_count}"
        assert (
            multi_parent_count >= 50
        ), f"Expected ≥50 multi-parent children, got {multi_parent_count}"

        # Canonical multi-parent leaves from the plan.
        for canonical in ("hypertension", "deep venous thrombosis"):
            row = db.fetchone(
                "SELECT id FROM subject_nodes WHERE LOWER(name) = ?",
                (canonical,),
            )
            assert row is not None, f"{canonical} should be a single canonical node"
            parents = db.get_parents(row["id"])
            assert (
                len(parents) >= 2
            ), f"{canonical} should have ≥2 parents, got {len(parents)}"
            primary_count = sum(1 for p in parents if p.is_primary)
            assert primary_count == 1, (
                f"{canonical} should have exactly one primary parent, "
                f"got {primary_count}"
            )
    finally:
        db.close()
