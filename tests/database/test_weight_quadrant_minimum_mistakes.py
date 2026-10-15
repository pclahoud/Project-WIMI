"""A subject needs a minimum number of mistakes before it is over-represented (#828).

Owner, 2026-10-14, after being shown that a 0%-weighted subject landed in
Reduce Focus on its first mistake (any share beats 1.3 x 0): *"I like the
minimum mistakes option. make it adjustible for users in the analytics page
settings"*. Per exam, in the exam's analytics config, 3 to start with; 1 is the
behaviour before.
"""
from __future__ import annotations

from datetime import date

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase

pytestmark = pytest.mark.database

EXAM = 'Minimum Exam'


@pytest.fixture
def world(tmp_path):
    master = MasterDatabase(data_dir=tmp_path)
    user = master.create_user(username='minimum', display_name='M', user_types=['student'])
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    exam = db.create_exam_context(exam_name=EXAM, exam_description='#828')
    zero = db.create_subject_node(exam_context=EXAM, name='Not tested', level_type='System',
                                  exam_weight_low=0, exam_weight_high=0)
    light = db.create_subject_node(exam_context=EXAM, name='Light', level_type='System',
                                   exam_weight_low=2, exam_weight_high=4)
    heavy = db.create_subject_node(exam_context=EXAM, name='Heavy', level_type='System',
                                   exam_weight_low=20, exam_weight_high=30)
    session = db.create_review_session(exam_context_id=exam.id, total_questions=10,
                                       total_incorrect=10, session_name='m',
                                       date_encountered=date.today())
    # Not tested: 1 mistake. Light: 2. Heavy: 7. Out of 10, each share is
    # far above 1.3 x the middle of its band.
    for subject, n in ((zero, 1), (light, 2), (heavy, 7)):
        for _ in range(n):
            db.create_question_entry(session.id, 'a', 'b', primary_subject_ids=[subject.id])
    db.conn.commit()
    try:
        yield db, exam.id
    finally:
        db.close()
        master.close()


def _quadrants(db, exam_id):
    return {s['subject_name']: s['quadrant']
            for s in db.get_subject_exam_weight_analysis(exam_id)['subjects']}


def test_the_default_is_three(world):
    db, exam_id = world
    assert db.get_exam_analytics_config(exam_id)['min_mistakes_to_flag'] == 3
    result = db.get_subject_exam_weight_analysis(exam_id)
    assert result['min_mistakes_to_flag'] == 3


def test_below_the_minimum_a_subject_is_not_over_represented(world):
    db, exam_id = world
    q = _quadrants(db, exam_id)
    assert q['Not tested'] == 'low-priority', 'a 0% subject was flagged on one mistake'
    assert q['Light'] == 'low-priority'
    assert q['Heavy'] == 'priority', 'seven mistakes are over the minimum'


def test_one_is_the_old_behaviour(world):
    db, exam_id = world
    db.update_exam_analytics_config(exam_id, {'min_mistakes_to_flag': 1})
    q = _quadrants(db, exam_id)
    assert q['Not tested'] == 'reduce-focus'
    assert q['Light'] == 'reduce-focus'


def test_the_setting_is_per_exam_and_survives_other_saves(world):
    db, exam_id = world
    db.update_exam_analytics_config(exam_id, {'min_mistakes_to_flag': 2})
    db.update_exam_analytics_config(exam_id, {'chart_sizes': {'tag_chart': 'L'}})
    assert db.get_exam_analytics_config(exam_id)['min_mistakes_to_flag'] == 2
    assert _quadrants(db, exam_id)['Light'] == 'reduce-focus'
    other = db.create_exam_context(exam_name='Other', exam_description='')
    assert db.get_exam_analytics_config(other.id)['min_mistakes_to_flag'] == 3


@pytest.mark.parametrize('bad', [0, 51, 2.5, '3', True])
def test_a_value_outside_one_to_fifty_is_refused_with_a_sentence(world, bad):
    db, exam_id = world
    with pytest.raises(ValueError, match='whole number from 1 to 50'):
        db.update_exam_analytics_config(exam_id, {'min_mistakes_to_flag': bad})
    assert db.get_exam_analytics_config(exam_id)['min_mistakes_to_flag'] == 3
