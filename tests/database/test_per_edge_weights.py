"""Tests for Stage 9 of the Hierarchical Weight Allocation Plan.

Stage 9 makes the analytics layer ``weight_source``-aware:

* ``get_subject_exam_weight_analysis`` now reads ``weight_source`` from
  ``subject_edges`` (the polyhierarchy-canonical column) and picks the
  *dominant* edge for each node when the node has multiple parents.
* ``_calculate_efficiency_score`` blends a per-source confidence
  multiplier into the existing range-derived confidence.
* A new helper ``get_weight_source_breakdown`` returns per-source
  subject counts for the dashboard's "Confidence breakdown" card.

Reference: ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``
§"Stage 9"; ``docs/planning/HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md``
§3.4 / §7.5.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase


# ==================== Fixtures ====================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db: MasterDatabase):
    return master_db.create_user(
        username="test_student",
        display_name="Test Student",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db: MasterDatabase, test_user) -> Generator[UserDatabase, None, None]:
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    db._ensure_phase2_schema()
    yield db
    db.close()


# ==================== Helpers ====================


def _set_edge_source(
    db: UserDatabase, edge_id: int, source: str, relative_weight: float
):
    """Write ``weight_source`` and ``relative_weight`` directly on an edge.

    The user-facing ``setExplicitWeight`` always stamps
    ``'user_explicit'``, so for varying ``weight_source`` values across
    test fixtures we go through the raw SQL writer + the edges-mixin
    helper. This mirrors how Stage 2 / Stage 3 ingest legacy data.
    """
    db.execute(
        "UPDATE subject_edges SET relative_weight = ?, weight_source = ? "
        "WHERE id = ?",
        (relative_weight, source, edge_id),
    )
    db.conn.commit()


def _edge_id(db: UserDatabase, parent_id: int, child_id: int) -> int:
    row = db.fetchone(
        "SELECT id FROM subject_edges WHERE parent_id = ? AND child_id = ?",
        (parent_id, child_id),
    )
    assert row is not None, (
        f"Expected an edge for parent={parent_id} child={child_id}"
    )
    return row['id']


def _seed_minimal_exam(user_db: UserDatabase, name: str = 'Stage 9 Exam'):
    return user_db.create_exam_context(
        exam_name=name,
        exam_description='Stage 9 weight_source-aware analytics tests',
    )


def _make_subject(
    db: UserDatabase,
    exam_name: str,
    name: str,
    parent_id=None,
    level_type='Topic',
    exam_weight_low=10.0,
    exam_weight_high=20.0,
    weight_source='user_defined',
):
    """Create a subject node carrying a non-zero weight range.

    Default weights are non-zero because the analytics layer filters
    out nodes with ``exam_weight_low <= 0``; tests that want a node to
    appear in the analysis need a positive range.
    """
    return db.create_subject_node_with_weight(
        exam_context=exam_name,
        name=name,
        level_type=level_type,
        parent_id=parent_id,
        exam_weight_low=exam_weight_low,
        exam_weight_high=exam_weight_high,
        weight_source=weight_source,
    )


def _add_minimal_mistake(db: UserDatabase, exam, subject_id: int):
    """Log one non-draft question entry mapped to ``subject_id``.

    The analytics queries filter on ``qe.is_draft = FALSE`` (or via
    the ``OR qe.id IS NULL`` LEFT-JOIN escape hatch). For the entry
    to count toward analytics, ``is_draft`` must be ``FALSE`` —
    ``create_question_entry`` derives that from
    ``reflection AND explanation AND primary_subject_ids``, so we
    pass all three explicitly + force-update afterwards to be safe.
    """
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name='Stage 9 Session',
    )
    entry = db.create_question_entry(
        review_session_id=session.id,
        user_answer='wrong',
        correct_answer='right',
        perceived_difficulty=3,
        reflection='Stage 9 test reflection',
        explanation='Stage 9 test explanation',
        primary_subject_ids=[subject_id],
    )
    # Defensive: explicitly mark as non-draft. The creator already
    # does this when all three required fields are provided, but
    # forcing it makes the test resilient to default-changes.
    db.execute(
        "UPDATE question_entries SET is_draft = FALSE WHERE id = ?",
        (entry.id,),
    )
    db.conn.commit()
    # ``create_question_entry`` already inserts the primary mapping
    # when ``primary_subject_ids`` is non-empty, so do NOT insert a
    # duplicate here — the analytics query would deduplicate via
    # COUNT(DISTINCT) but a duplicate row violates the table's
    # unique constraint on (question_entry_id, subject_node_id).
    existing = db.fetchone(
        "SELECT 1 FROM entry_subject_mappings "
        "WHERE question_entry_id = ? AND subject_node_id = ?",
        (entry.id, subject_id),
    )
    if existing is None:
        db.conn.execute(
            "INSERT INTO entry_subject_mappings "
            "(question_entry_id, subject_node_id, mapping_type) "
            "VALUES (?, ?, 'primary')",
            (entry.id, subject_id),
        )
        db.conn.commit()
    return entry, session


# ==================== Tests ====================


class TestDominantEdgeSelection:
    """get_subject_exam_weight_analysis picks the dominant edge's source."""

    def test_dominant_edge_picked_for_multi_parent_node(
        self, user_db: UserDatabase
    ):
        """When a node has two parent edges, the heavier edge wins.

        Setup: subject ``Hypertension`` carries two parent edges:
            * Cardiovascular → Hypertension at rw=30, weight_source='official'
            * Pregnancy      → Hypertension at rw=10, weight_source='user_estimate'

        Expected: the analytics row for Hypertension reports
        ``weight_source='official'`` (the heavier edge), not
        ``'user_estimate'``.
        """
        exam = _seed_minimal_exam(user_db)

        # Two parent systems plus the shared child.
        cardio = _make_subject(
            user_db, exam.exam_name, 'Cardio',
            level_type='System', exam_weight_low=25, exam_weight_high=35,
        )
        pregnancy = _make_subject(
            user_db, exam.exam_name, 'Pregnancy',
            level_type='System', exam_weight_low=10, exam_weight_high=20,
        )
        # Initial parent is Cardio (we'll add Pregnancy as a 2nd edge).
        hypertension = _make_subject(
            user_db, exam.exam_name, 'Hypertension',
            parent_id=cardio.id, level_type='Topic',
            exam_weight_low=8, exam_weight_high=12,
        )

        # Add a 2nd parent edge for hypertension.
        user_db.add_edge(
            parent_id=pregnancy.id, child_id=hypertension.id, is_primary=False,
        )

        cardio_edge = _edge_id(user_db, cardio.id, hypertension.id)
        preg_edge = _edge_id(user_db, pregnancy.id, hypertension.id)

        _set_edge_source(user_db, cardio_edge, 'official', 30.0)
        _set_edge_source(user_db, preg_edge, 'user_estimate', 10.0)

        # Need a mistake so the node appears in the analysis (the
        # query LEFT JOINs through question_entries but the filter
        # ``COALESCE(sn.exam_weight_low, 0) > 0`` keeps it in even
        # without entries; we still add one for realism).
        _add_minimal_mistake(user_db, exam, hypertension.id)

        analysis = user_db.get_subject_exam_weight_analysis(exam.id)

        # Find hypertension's row.
        row = next(
            (s for s in analysis['subjects'] if s['subject_id'] == hypertension.id),
            None,
        )
        assert row is not None, (
            f"Hypertension missing from analysis subjects: "
            f"{[s['subject_id'] for s in analysis['subjects']]}"
        )
        assert row['weight_source'] == 'official', (
            f"Dominant edge under Cardio (rw=30, official) should win; "
            f"got {row['weight_source']!r}"
        )


class TestWeightSourceBreakdown:
    """get_weight_source_breakdown counts the dominant source per node."""

    def test_weight_source_breakdown_counts_correctly(
        self, user_db: UserDatabase
    ):
        """Mix of subjects with different weight_sources → correct totals."""
        exam = _seed_minimal_exam(user_db)

        parent = _make_subject(
            user_db, exam.exam_name, 'Root',
            level_type='System', exam_weight_low=100, exam_weight_high=100,
        )

        # Five subjects, each with a distinct dominant source.
        children = []
        sources_in_order = [
            'official',
            'user_explicit',
            'user_defined',
            'derived',
            'user_estimate',
        ]
        for i, src in enumerate(sources_in_order, start=1):
            child = _make_subject(
                user_db, exam.exam_name, f'Child{i}',
                parent_id=parent.id, level_type='Topic',
                exam_weight_low=10, exam_weight_high=15,
            )
            children.append(child)
            edge_id = _edge_id(user_db, parent.id, child.id)
            _set_edge_source(user_db, edge_id, src, 20.0)

        breakdown = user_db.get_weight_source_breakdown(exam.id)

        # Each source bucket should have exactly one subject; the
        # parent itself is excluded from the count only if it has no
        # incoming edge (which it doesn't, by construction). But the
        # parent's weight_source defaults to whatever
        # create_subject_node_with_weight sets ('user_defined'), and
        # the parent has no incoming edge so the fallback to
        # ``subject_nodes.weight_source`` triggers.
        assert breakdown['official'] == 1, breakdown
        assert breakdown['user_explicit'] == 1, breakdown
        assert breakdown['user_defined'] >= 1, breakdown  # +1 from the root
        assert breakdown['derived'] == 1, breakdown
        assert breakdown['user_estimate'] == 1, breakdown
        # Total reconciles: 5 children + 1 root.
        assert breakdown['total'] == 6, breakdown
        # And total is the sum of the five buckets.
        assert breakdown['total'] == sum(
            v for k, v in breakdown.items() if k != 'total'
        )


class TestEfficiencyScoreSourceFactor:
    """_calculate_efficiency_score honors the source confidence factor."""

    def test_efficiency_score_uses_source_multiplier(
        self, user_db: UserDatabase
    ):
        """``official`` source → different efficiency than ``user_estimate``.

        Both subjects have the same range and the same mistake
        percentage, so the *range*-derived confidence is identical.
        Only the ``weight_source`` differs. The penalty term uses
        ``min(range_conf, source_conf)``, so ``user_estimate`` (0.4)
        should produce a *lower* penalty than ``official`` (1.0) for
        the same deviation — meaning the ``user_estimate`` score is
        actually *higher* numerically.
        """
        # Sanity: build two synthetic subject rows and feed them
        # straight to the score helper to avoid the DB query path.
        # The helper is a pure function over the list shape.
        subjects_official = [{
            'subject_id': 1,
            'subject_name': 'Cardio',
            'mistake_percentage': 50.0,
            'exam_weight': 20.0,
            'exam_weight_low': 15.0,
            'exam_weight_high': 25.0,
            'weight_source': 'official',
        }]
        subjects_user_estimate = [{
            'subject_id': 1,
            'subject_name': 'Cardio',
            'mistake_percentage': 50.0,
            'exam_weight': 20.0,
            'exam_weight_low': 15.0,
            'exam_weight_high': 25.0,
            'weight_source': 'user_estimate',
        }]

        score_official = user_db._calculate_efficiency_score(subjects_official)
        score_estimate = user_db._calculate_efficiency_score(subjects_user_estimate)

        # The official source has 1.0 confidence (capped against the
        # 0.5 range-confidence), so the penalty is bigger and the
        # score is lower. user_estimate has 0.4 confidence, so its
        # penalty is smaller and the score is higher. The two must
        # NOT be equal — that would mean the source factor was ignored.
        assert score_official != score_estimate, (
            f"Efficiency scores must differ when only weight_source "
            f"differs. official={score_official}, "
            f"user_estimate={score_estimate}"
        )
        assert score_estimate > score_official, (
            f"user_estimate's lower confidence should produce a smaller "
            f"penalty (higher score) than official. "
            f"official={score_official}, user_estimate={score_estimate}"
        )

    def test_efficiency_score_unknown_source_uses_default(
        self, user_db: UserDatabase
    ):
        """Subjects missing a weight_source fall back to the default."""
        subjects_no_source = [{
            'subject_id': 1,
            'subject_name': 'Cardio',
            'mistake_percentage': 50.0,
            'exam_weight': 20.0,
            'exam_weight_low': 15.0,
            'exam_weight_high': 25.0,
            # No 'weight_source' key — should fall back to the default.
        }]

        # Should not raise — defaulting is the contract.
        score = user_db._calculate_efficiency_score(subjects_no_source)
        assert 0 <= score <= 100, (
            f"Efficiency score must be in [0, 100]; got {score}"
        )


class TestAnalysisIncludesDistribution:
    """get_subject_exam_weight_analysis bundles the breakdown."""

    def test_analysis_response_includes_weight_source_distribution(
        self, user_db: UserDatabase
    ):
        """The full analysis response carries ``weight_source_distribution``."""
        exam = _seed_minimal_exam(user_db)
        parent = _make_subject(
            user_db, exam.exam_name, 'Root',
            level_type='System', exam_weight_low=100, exam_weight_high=100,
        )
        child = _make_subject(
            user_db, exam.exam_name, 'Child',
            parent_id=parent.id, level_type='Topic',
            exam_weight_low=20, exam_weight_high=30,
        )
        edge_id = _edge_id(user_db, parent.id, child.id)
        _set_edge_source(user_db, edge_id, 'official', 100.0)

        _add_minimal_mistake(user_db, exam, child.id)

        analysis = user_db.get_subject_exam_weight_analysis(exam.id)
        assert 'weight_source_distribution' in analysis
        dist = analysis['weight_source_distribution']
        for key in (
            'official', 'user_explicit', 'user_defined',
            'derived', 'user_estimate', 'total',
        ):
            assert key in dist, (
                f"Missing key {key!r} in weight_source_distribution: {dist}"
            )
        assert dist['total'] == sum(
            v for k, v in dist.items() if k != 'total'
        )

    def test_empty_exam_returns_zeroed_distribution(
        self, user_db: UserDatabase
    ):
        """Exam with no weighted subjects → zeroed distribution shape."""
        exam = _seed_minimal_exam(user_db, name='Stage 9 Empty Exam')
        analysis = user_db.get_subject_exam_weight_analysis(exam.id)
        assert 'weight_source_distribution' in analysis
        dist = analysis['weight_source_distribution']
        assert dist['total'] == 0
        assert dist['official'] == 0
        assert dist['user_explicit'] == 0
