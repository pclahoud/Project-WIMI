"""The heatmap payload carries the streak's own at-risk flag (#478).

``get_activity_heatmap`` already called ``_calculate_streak_info`` and
forwarded two of its keys, dropping ``streak_at_risk`` -- so the dashboard's
Current Streak card, which is drawn from this payload, could only hardcode
it. The assertion is agreement with ``get_streak_info`` (the same method),
not a second definition of "at risk", and it runs both ways so a payload
that always said ``True`` would fail too.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    database = UserDatabase(str(tmp_path / 'user.db'), user_id=1, username='t')
    yield database
    database.close()


def _seed(db, days_ago):
    exam = db.create_exam_context(exam_name='W478', exam_description='')
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name='Topic', level_type='Topic',
        exam_weight_low=10, exam_weight_high=10,
    )
    for n in days_ago:
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=5, total_incorrect=1,
            session_name=f'd-{n}', date_encountered=date.today() - timedelta(days=n),
        )
        db.create_question_entry(
            review_session_id=session.id, user_answer='A', correct_answer='B',
            perceived_difficulty=3, reflection='r', explanation='e',
            primary_subject_ids=[subject.id],
        )
    return exam.id


@pytest.mark.parametrize('days_ago, expected', [
    ([1, 2], True),     # active yesterday, nothing yet today
    ([0, 1], False),    # active today
    ([3, 4], False),    # streak already broken
])
def test_heatmap_forwards_streak_at_risk(db, days_ago, expected):
    exam_id = _seed(db, days_ago)

    payload = db.get_activity_heatmap(exam_id)

    assert db.get_streak_info(exam_id)['streak_at_risk'] is expected
    assert payload.get('streak_at_risk') is expected, payload.keys()
