"""Bridge tests for ``getExamContextStats``' subject count.

Forgejo issue #7: the dashboard exam card read "9 topics" where the tree
editor read "6 subjects" on the same data. ``getExamContextStats`` walked
the polyhierarchy-aware ``get_subject_hierarchy`` payload and added 1 per
visited node, so a subject with several parents was counted once per
parent — that is a count of tree *positions*, not of subjects.

Owner decision (2026-09-14): the dashboard shows the distinct subject
count. These tests pin that contract at the bridge layer; the UI half
(both surfaces agreeing on screen) is covered by
``tests/wimi_test/scenarios/test_dashboard_subject_count.py``.
"""
import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


EXAM_NAME = 'Issue 7 Stats Exam'


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(db_path=temp_db_path, user_id=1, username='test_user')
    yield db
    db.close()


@pytest.fixture
def master_db() -> Generator[MasterDatabase, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        db = MasterDatabase(data_dir=Path(tmpdir), error_logger=None)
        yield db
        db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(username='test_admin', display_name='Test Admin')
    return DatabaseBridge(master_db=master_db, user_db=user_db)


def _node(db: UserDatabase, name: str, parent_id=None):
    return db.create_subject_node(
        exam_context=EXAM_NAME,
        name=name,
        level_type='System' if parent_id is None else 'Topic',
        parent_id=parent_id,
    )


def _stats(bridge: DatabaseBridge, exam_context_id: int) -> dict:
    payload = json.loads(bridge.getExamContextStats(exam_context_id))
    assert payload['success'] is True, payload.get('error')
    return payload['data']


@pytest.mark.unit
def test_subject_count_is_distinct_subjects_not_tree_positions(
    bridge: DatabaseBridge, user_db: UserDatabase
) -> None:
    """Issue #7's reproducer: 6 subjects, 6 edges, 3 roots → 6, not 9."""
    exam = user_db.create_exam_context(
        exam_name=EXAM_NAME, exam_description='issue #7 reproducer'
    )

    cardio = _node(user_db, 'Cardiovascular')
    preg = _node(user_db, 'Pregnancy')
    resp = _node(user_db, 'Respiratory')

    hypertension = _node(user_db, 'hypertension', cardio.id)
    user_db.add_edge(preg.id, hypertension.id)

    vte = _node(user_db, 'VTE', cardio.id)
    user_db.add_edge(preg.id, vte.id)
    user_db.add_edge(resp.id, vte.id)

    _node(user_db, 'asthma', resp.id)

    # 6 parent->child edges + 3 parentless roots = 9 tree positions.
    edge_count = user_db.fetchone(
        'SELECT COUNT(*) AS n FROM subject_edges se '
        'JOIN subject_nodes sn ON sn.id = se.child_id '
        'WHERE sn.exam_context = ?',
        (EXAM_NAME,),
    )['n']
    assert edge_count == 6, 'seed drifted: no shared child means no repro'

    data = _stats(bridge, exam.id)
    assert data['subject_count'] == 6, (
        f"Expected the 6 distinct subjects; got {data['subject_count']}. "
        '9 means the bridge is counting tree positions again (issue #7).'
    )
    assert data['weight_configured'] is True


@pytest.mark.unit
def test_subject_count_matches_node_count_on_a_plain_tree(
    bridge: DatabaseBridge, user_db: UserDatabase
) -> None:
    """A single-parent tree is unchanged by the fix (the non-regression leg)."""
    exam = user_db.create_exam_context(
        exam_name=EXAM_NAME, exam_description='single-parent control'
    )
    root = _node(user_db, 'Root')
    _node(user_db, 'Child A', root.id)
    _node(user_db, 'Child B', root.id)

    assert _stats(bridge, exam.id)['subject_count'] == 3


@pytest.mark.unit
def test_subject_count_is_zero_for_an_empty_exam(
    bridge: DatabaseBridge, user_db: UserDatabase
) -> None:
    exam = user_db.create_exam_context(
        exam_name=EXAM_NAME, exam_description='no subjects yet'
    )
    data = _stats(bridge, exam.id)
    assert data['subject_count'] == 0
    assert data['weight_configured'] is False
