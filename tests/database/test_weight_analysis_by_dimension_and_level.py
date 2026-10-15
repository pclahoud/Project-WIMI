"""The weight analysis lists one dimension at one level when asked (#820).

Owner's request, 2026-10-14: the card should follow the dimension selection and
let the student move through a dimension's levels. Decision: at a level, a
subject's mistakes include the entries beneath it -- which is how the card has
counted since #468, so the filters choose which rows are listed and change no
figure on any row.

Two axes over one exam, each a system with a topic beneath it. Entries are
tagged on the topics only, in both axes, as a real multi-axis entry is.
"""
from __future__ import annotations

from datetime import date

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase

pytestmark = pytest.mark.database

EXAM = 'Axis Exam'


@pytest.fixture
def world(tmp_path):
    master = MasterDatabase(data_dir=tmp_path)
    user = master.create_user(
        username='axes', display_name='A', user_types=['student'])
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    exam = db.create_exam_context(exam_name=EXAM, exam_description='#820')
    system = db.create_dimension(exam.id, 'System', 1)
    task = db.create_dimension(exam.id, 'Task', 2)

    def node(name, low, high, dim, parent=None, level='System'):
        return db.create_subject_node(
            exam_context=EXAM, name=name, level_type=level, parent_id=parent,
            exam_weight_low=low, exam_weight_high=high, dimension_id=dim)

    cardio = node('Cardio', 20, 25, system)
    htn = node('HTN', 6, 8, system, parent=cardio.id, level='Topic')
    dx = node('Diagnosis', 40, 50, task)
    labs = node('Labs', 10, 15, task, parent=dx.id, level='Topic')

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=4, total_incorrect=4,
        session_name='axes', date_encountered=date.today())
    for _ in range(4):
        db.create_question_entry(session.id, 'a', 'b',
                                 primary_subject_ids=[htn.id, labs.id])
    db.conn.commit()
    try:
        yield db, exam.id, system, task
    finally:
        db.close()
        master.close()


def _names(result):
    return sorted(s['subject_name'] for s in result['subjects'])


def test_unfiltered_still_lists_every_weighted_subject(world):
    db, exam_id, _, _ = world
    assert _names(db.get_subject_exam_weight_analysis(exam_id)) == [
        'Cardio', 'Diagnosis', 'HTN', 'Labs']


def test_a_dimension_lists_only_its_own_subjects(world):
    db, exam_id, system, task = world
    assert _names(db.get_subject_exam_weight_analysis(exam_id, dimension_id=system)) == [
        'Cardio', 'HTN']
    assert _names(db.get_subject_exam_weight_analysis(exam_id, dimension_id=task)) == [
        'Diagnosis', 'Labs']


def test_a_level_lists_only_that_level(world):
    db, exam_id, system, _ = world
    top = db.get_subject_exam_weight_analysis(exam_id, dimension_id=system, level_type='System')
    below = db.get_subject_exam_weight_analysis(exam_id, dimension_id=system, level_type='Topic')
    assert _names(top) == ['Cardio']
    assert _names(below) == ['HTN']


def test_the_top_level_still_counts_what_is_tagged_beneath_it(world):
    """The owner's decision, and the reason a level filter is usable at all:
    every entry here is tagged on a topic, so a direct count would show
    Cardio at 0%."""
    db, exam_id, system, _ = world
    cardio = db.get_subject_exam_weight_analysis(
        exam_id, dimension_id=system, level_type='System')['subjects'][0]
    assert cardio['mistake_count'] == 4
    assert cardio['direct_mistake_count'] == 0
    assert cardio['mistake_percentage'] == 100.0


def test_filtering_changes_no_row_only_which_rows(world):
    db, exam_id, system, _ = world
    every = {s['subject_name']: s for s in db.get_subject_exam_weight_analysis(exam_id)['subjects']}
    one = db.get_subject_exam_weight_analysis(exam_id, dimension_id=system, level_type='System')
    assert one['total_mistakes'] == 4
    assert one['subjects'][0] == every['Cardio']
