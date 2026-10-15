"""A dimension's levels are ordered by the exam's own level list (#818).

The order was a CASE over five built-in names (System, Subsystem, Topic,
Subtopic, Child) with every other name tied, so a dimension whose top level is
called anything else could open its level pickers -- the cross-dimension
heatmap's and the weight card's -- on a lower level. Owner, 2026-10-14: order
by the level list set in the exam's setup; a name not in that list goes after
it, by how far down the tree its subjects sit.
"""
from __future__ import annotations

import pytest

from database.master_db import MasterDatabase
from database.user_db import UserDatabase

pytestmark = pytest.mark.database


@pytest.fixture
def db(tmp_path):
    master = MasterDatabase(data_dir=tmp_path)
    user = master.create_user(username='levels', display_name='L', user_types=['student'])
    d = UserDatabase(db_path=master.ensure_user_database(user.id),
                     user_id=user.id, username=user.username)
    try:
        yield d
    finally:
        d.close()
        master.close()


def _exam(db, name, levels):
    exam = db.create_exam_context(exam_name=name, exam_description='#818',
                                  hierarchy_levels=levels)
    dim = db.create_dimension(exam.id, 'Axis', 1)
    return exam, dim


def _chain(db, exam, dim, names):
    """One subject per level name, each the child of the one before."""
    parent = None
    for n in names:
        parent = db.create_subject_node(exam_context=exam.exam_name, name=f'{n} node',
                                        level_type=n, parent_id=parent and parent.id,
                                        dimension_id=dim)


def _order(db, exam, dim):
    return [l['level_type'] for l in db.get_hierarchy_levels_for_dimension(exam.id, dim)['levels']]


def test_the_exams_list_orders_names_the_old_list_never_knew(db):
    exam, dim = _exam(db, 'SAT', ['Section', 'Domain', 'Skill'])
    _chain(db, exam, dim, ['Section', 'Domain', 'Skill'])
    assert _order(db, exam, dim) == ['Section', 'Domain', 'Skill']


def test_the_exams_list_wins_over_the_old_built_in_order(db):
    exam, dim = _exam(db, 'Odd', ['Topic', 'System'])
    _chain(db, exam, dim, ['Topic', 'System'])
    assert _order(db, exam, dim) == ['Topic', 'System']


def test_a_name_missing_from_the_list_goes_after_it_by_tree_depth(db):
    exam, dim = _exam(db, 'Mixed', ['Domain'])
    _chain(db, exam, dim, ['Zeta', 'Alpha', 'Domain'])
    # Domain is listed, so it leads even though it is the deepest; the two
    # unlisted names follow by depth (Zeta is the root), not alphabetically.
    assert _order(db, exam, dim) == ['Domain', 'Zeta', 'Alpha']


def test_a_new_exams_default_list_keeps_the_order_it_always_had(db):
    exam, dim = _exam(db, 'Default', None)
    _chain(db, exam, dim, ['System', 'Subsystem', 'Topic', 'Subtopic', 'Child'])
    assert _order(db, exam, dim) == ['System', 'Subsystem', 'Topic', 'Subtopic', 'Child']
