"""Regression tests for the deep-dive "Mistakes Over Time" buckets (issue #5).

``get_subject_deep_dive`` returns two views of the same entries: the
``this_week`` / ``last_week`` cards and an eight-bucket ``timeline`` whose
newest bucket is labelled ``'This'``. Before the fix, the timeline loop
computed each bucket as ``[week_start - (i+1)*7, week_start - i*7)`` — so
the ``'This'`` bucket (``i == 0``) actually covered *last* week and the
current week appeared nowhere. On a database whose entries were all
created today, every bucket read 0 while the cards read the true count.

These tests seed entries at known offsets from the current week's Monday
(the anchor both the cards and the timeline use) and assert the two views
agree. A non-zero baseline is asserted first so an empty result set fails
loudly rather than passing vacuously.
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


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
        username="tl_user",
        display_name="Timeline User",
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
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES (?, ?, ?, NULL, 0, 'active')",
        ("USMLE", name, "Topic"),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _exam_context_id(user_db) -> int:
    row = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = 'USMLE'"
    )
    if row is not None:
        return row['id']
    cursor = user_db.execute(
        "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
        "VALUES (?, 'USMLE', 'Test')",
        (user_db.user_id,),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _make_session(user_db, exam_context_id: int, when: date) -> int:
    cursor = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_db.user_id, "Test session", when.isoformat(), exam_context_id, 1, 1),
    )
    user_db.conn.commit()
    return cursor.lastrowid


_ENTRY_ORDER = {'n': 0}


def _log_entries(user_db, session_id: int, subject_node_id: int, n: int) -> None:
    for _ in range(n):
        _ENTRY_ORDER['n'] += 1
        cursor = user_db.execute(
            "INSERT INTO question_entries "
            "(review_session_id, entry_order, user_answer, correct_answer) "
            "VALUES (?, ?, ?, ?)",
            (session_id, _ENTRY_ORDER['n'], "A", "B"),
        )
        user_db.execute(
            "INSERT INTO entry_subject_mappings "
            "(question_entry_id, subject_node_id, mapping_type) "
            "VALUES (?, ?, 'primary')",
            (cursor.lastrowid, subject_node_id),
        )
    user_db.conn.commit()


def _week_start(today: date) -> date:
    """Monday of the week containing ``today`` — the anchor the cards use."""
    return today - timedelta(days=today.weekday())


@pytest.fixture
def seeded(user_db):
    """``Cardiovascular → Hypertension`` with entries in three known weeks.

    Returns a dict with the node ids, the exam context and the expected
    per-week counts. Dates are chosen relative to this week's Monday so the
    assertions hold on any weekday:

    * today                → this week      (3 on the leaf, 2 on the root)
    * Monday - 1 day       → last week      (2 on the leaf)
    * Monday - 8 days      → two weeks ago  (1 on the leaf)
    """
    today = date.today()
    monday = _week_start(today)

    root = _make_node(user_db, "Cardiovascular")
    leaf = _make_node(user_db, "Hypertension")
    user_db.add_edge(root, leaf, is_primary=True)

    ec = _exam_context_id(user_db)

    s_today = _make_session(user_db, ec, today)
    _log_entries(user_db, s_today, leaf, 3)
    _log_entries(user_db, s_today, root, 2)

    s_last = _make_session(user_db, ec, monday - timedelta(days=1))
    _log_entries(user_db, s_last, leaf, 2)

    s_prev = _make_session(user_db, ec, monday - timedelta(days=8))
    _log_entries(user_db, s_prev, leaf, 1)

    return {
        'root': root,
        'leaf': leaf,
        'exam_context_id': ec,
        'leaf_this_week': 3,
        'leaf_last_week': 2,
        'leaf_two_weeks_ago': 1,
        'root_this_week': 5,
        'root_last_week': 2,
        'root_two_weeks_ago': 1,
    }


# ------------------------------------------------------------------ tests


@pytest.mark.database
class TestDeepDiveTimelineBuckets:

    def _dive(self, user_db, seeded, node_key):
        return user_db.get_subject_deep_dive(
            seeded[node_key], exam_context_id=seeded['exam_context_id']
        )

    @pytest.mark.parametrize("node_key", ["leaf", "root"])
    def test_cards_have_non_zero_baseline(self, user_db, seeded, node_key):
        """Guard against a vacuous pass: the cards must see the seed data."""
        dive = self._dive(user_db, seeded, node_key)
        assert dive['total_mistakes'] == (
            seeded[f'{node_key}_this_week']
            + seeded[f'{node_key}_last_week']
            + seeded[f'{node_key}_two_weeks_ago']
        )
        assert dive['this_week'] == seeded[f'{node_key}_this_week'] > 0
        assert dive['last_week'] == seeded[f'{node_key}_last_week'] > 0

    @pytest.mark.parametrize("node_key", ["leaf", "root"])
    def test_newest_bucket_matches_this_week_card(self, user_db, seeded, node_key):
        """The bucket labelled 'This' must agree with the THIS WEEK card."""
        dive = self._dive(user_db, seeded, node_key)
        timeline = dive['timeline']
        assert len(timeline) == 8
        assert timeline[-1]['label'] == 'This'
        assert timeline[-1]['count'] == dive['this_week'] > 0

    @pytest.mark.parametrize("node_key", ["leaf", "root"])
    def test_second_newest_bucket_matches_last_week_card(self, user_db, seeded, node_key):
        dive = self._dive(user_db, seeded, node_key)
        timeline = dive['timeline']
        assert timeline[-2]['count'] == dive['last_week'] > 0

    @pytest.mark.parametrize("node_key", ["leaf", "root"])
    def test_buckets_are_consecutive_weeks_ending_now(self, user_db, seeded, node_key):
        """Each bucket is one week older than the next; nothing is skipped."""
        dive = self._dive(user_db, seeded, node_key)
        counts = [b['count'] for b in dive['timeline']]
        expected_tail = [
            seeded[f'{node_key}_two_weeks_ago'],
            seeded[f'{node_key}_last_week'],
            seeded[f'{node_key}_this_week'],
        ]
        assert counts[-3:] == expected_tail
        assert counts[:-3] == [0] * 5

    @pytest.mark.parametrize("node_key", ["leaf", "root"])
    def test_timeline_accounts_for_every_recent_entry(self, user_db, seeded, node_key):
        """Every seeded entry lies within the last 8 weeks, so the buckets
        must sum to the TOTAL MISTAKES card. A shifted window drops this
        week's entries off the newest edge and breaks this."""
        dive = self._dive(user_db, seeded, node_key)
        assert sum(b['count'] for b in dive['timeline']) == dive['total_mistakes'] > 0
