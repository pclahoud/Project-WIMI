"""Study Recommendations ranks the heatmap's cells, not every level at once (#824).

The card asked ``get_cross_dimension_performance`` for the exam's first two
dimensions with no level, so every subject at every depth sat on both axes: a
system was ranked against its own topics, and one mistake reached the pair of
each. Owner, 2026-10-14: *"file it as an issue and fix it"*. The fix ranks the
cells the heatmap above it is showing, and a level nobody names is the top one.

Two axes, each a root with one child; four entries tagged on the children.
"""
from __future__ import annotations

from datetime import date

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase

pytestmark = pytest.mark.database

EXAM = 'Recs Exam'


@pytest.fixture
def world(tmp_path):
    master = MasterDatabase(data_dir=tmp_path)
    user = master.create_user(
        username='recs', display_name='R', user_types=['student'])
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    exam = db.create_exam_context(exam_name=EXAM, exam_description='#824')
    system = db.create_dimension(exam.id, 'System', 1)
    task = db.create_dimension(exam.id, 'Task', 2)

    def node(name, dim, parent=None, level='System'):
        return db.create_subject_node(
            exam_context=EXAM, name=name, level_type=level, parent_id=parent,
            exam_weight_low=10, exam_weight_high=20, dimension_id=dim)

    cardio = node('Cardio', system)
    htn = node('HTN', system, parent=cardio.id, level='Topic')
    dx = node('Diagnosis', task)
    labs = node('Labs', task, parent=dx.id, level='Topic')

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=4, total_incorrect=4,
        session_name='recs', date_encountered=date.today())
    for _ in range(4):
        db.create_question_entry(session.id, 'a', 'b',
                                 primary_subject_ids=[htn.id, labs.id])
    db.conn.commit()
    try:
        yield db, exam.id, system, task, cardio
    finally:
        db.close()
        master.close()


def _pairs(recs):
    return sorted((r['dim_a_value'], r['dim_b_value']) for r in recs)


def test_by_default_only_the_top_levels_are_ranked(world):
    db, exam_id, *_ = world
    assert _pairs(db.get_weighted_study_recommendations(exam_id, limit=50)) == [
        ('Cardio', 'Diagnosis')], (
        'a system was ranked against its own topics -- the unlevelled query')


def test_the_heatmaps_levels_choose_the_cells(world):
    db, exam_id, *_ = world
    recs = db.get_weighted_study_recommendations(
        exam_id, limit=50, level_type_a='Topic', level_type_b='Topic')
    assert _pairs(recs) == [('HTN', 'Labs')]


def test_the_heatmaps_dimensions_choose_the_axes(world):
    db, exam_id, system, task, _ = world
    recs = db.get_weighted_study_recommendations(
        exam_id, limit=50, dimension_a_id=task, dimension_b_id=system)
    assert _pairs(recs) == [('Diagnosis', 'Cardio')]


def test_a_drill_down_parent_scopes_by_itself(world):
    db, exam_id, _, _, cardio = world
    recs = db.get_weighted_study_recommendations(
        exam_id, limit=50, level_type_a='Topic', parent_node_a_id=cardio.id)
    assert _pairs(recs) == [('HTN', 'Diagnosis')]


def test_the_same_dimension_twice_ranks_nothing(world):
    db, exam_id, system, *_ = world
    assert db.get_weighted_study_recommendations(
        exam_id, dimension_a_id=system, dimension_b_id=system) == []
