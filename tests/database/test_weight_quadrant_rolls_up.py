"""The weight quadrant counts a subject's whole branch, out of the whole exam (#468).

Owner's decisions, 2026-10-07:

1. **Include children.** A row counts the mistakes on that subject and
   everything beneath it, because #64 makes a weight a share of the whole exam
   at any depth -- a parent's 20-25% already includes its children. The
   quadrant counted direct tags only, so a weighted parent whose entries sat
   on its topics read 0% and was advised "well-balanced -- maintain current
   study level" about the branch with the most mistakes, while the sunburst on
   the same page drew it as the largest arc.
2. **Include 0%-weighted subjects**, which #64 says are real data. The filter
   ``COALESCE(exam_weight_low, 0) > 0`` excluded them along with the
   genuinely unweighted.

The percentage is out of every entry in the exam, not out of the sum over the
rows that survived the filter, so rows overlap and do not sum to 100% -- the
non-additivity #6 settled for the sunburst. The §5.4 parent-context half is in
``test_analytics_rollup_characterisation.py``.
"""
from __future__ import annotations

from datetime import date

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase

pytestmark = pytest.mark.database

EXAM = 'Quadrant Exam'


@pytest.fixture
def world(tmp_path):
    master = MasterDatabase(data_dir=tmp_path)
    user = master.create_user(
        username='quadrant', display_name='Q', user_types=['student'])
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    exam = db.create_exam_context(exam_name=EXAM, exam_description='#468')

    def node(name, low, high, parent=None, level='System'):
        return db.create_subject_node(
            exam_context=EXAM, name=name, level_type=level, parent_id=parent,
            exam_weight_low=low, exam_weight_high=high)

    cardio = node('Cardiovascular', 20, 25)
    htn = node('Hypertension', 6, 6, parent=cardio.id, level='Topic')
    renal = node('Renal', 8, 12)
    ethics = node('Ethics', 0, 0)
    unweighted = db.create_subject_node(
        exam_context=EXAM, name='Unweighted', level_type='System')

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=6, total_incorrect=6,
        session_name='q', date_encountered=date.today())
    # Three on the CHILD only, one each elsewhere, one on an unweighted
    # subject: six entries in the exam.
    for subject in (htn, htn, htn, renal, ethics, unweighted):
        db.create_question_entry(session.id, 'a', 'b',
                                 primary_subject_ids=[subject.id])
    db.conn.commit()
    try:
        yield db, exam.id
    finally:
        db.close()
        master.close()


def _rows(db, exam_id):
    return {s['subject_name']: s
            for s in db.get_subject_exam_weight_analysis(exam_id)['subjects']}


def test_a_parent_counts_its_childrens_mistakes(world):
    db, exam_id = world
    cardio = _rows(db, exam_id)['Cardiovascular']

    assert cardio['mistake_count'] == 3, (
        'the parent read its direct tags only -- the 0% #468 reported')
    assert cardio['direct_mistake_count'] == 0
    assert cardio['quadrant'] != 'well-maintained', (
        'the branch with the most mistakes must not be advised to maintain '
        'current effort')


def test_the_percentage_is_a_share_of_the_whole_exam(world):
    db, exam_id = world
    result = db.get_subject_exam_weight_analysis(exam_id)
    rows = {s['subject_name']: s for s in result['subjects']}

    assert result['total_mistakes'] == 6, (
        'the denominator is every entry in the exam, including the one on an '
        'unweighted subject -- not the sum over the rows that were kept')
    assert rows['Cardiovascular']['mistake_percentage'] == 50.0
    assert rows['Hypertension']['mistake_percentage'] == 50.0
    # Overlap is the point, not a bug: #6's non-additivity.
    assert sum(r['mistake_percentage'] for r in rows.values()) > 100


def test_a_subject_weighted_at_zero_is_in_the_quadrant(world):
    db, exam_id = world
    rows = _rows(db, exam_id)

    assert 'Ethics' in rows, '0% is a recorded weight (#64), not "unweighted"'
    assert rows['Ethics']['exam_weight'] == 0.0
    assert 'Unweighted' not in rows, 'NULL on both bounds is still left out'
