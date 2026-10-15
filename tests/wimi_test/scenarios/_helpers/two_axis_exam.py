"""A two-axis exam for the analytics scenarios of #820 and #821.

Axis 1 (System) has ``systems`` roots, axis 2 (Task) ``tasks`` roots; every
root carries one child a level below. One entry per pair of children, tagged
on the children only, so a top-level figure exists only through roll-up.
The exam's level list names none of them, so each axis's levels are ordered
by tree depth (#818): the roots' level first.
"""
from __future__ import annotations

from datetime import date


def _w(lo, hi):
    return {'low': lo, 'high': hi}


def seed_two_axis_exam(db, systems, tasks, name='Axes', every_pair=True, per_pair=1):
    """``systems`` / ``tasks``: lists of root names; ``every_pair=False``
    logs one entry per position instead of the whole cross product;
    ``per_pair`` entries are logged for each pair. Returns
    ``(exam_id, {'System': dim_id, 'Task': dim_id}, {name: subject_id})``."""
    exam = db.create_exam_context(exam_name=name, exam_description='',
                                  hierarchy_levels=['Top', 'Beneath'])

    def roots(names, top, below, weight):
        return [{'id': f'{n}-id', 'name': n, 'level_type': top, 'weight': _w(*weight),
                 'children': [{'id': f'{n}-child-id', 'name': f'{n} child',
                               'level_type': below, 'weight': _w(2, 4)}]}
                for n in names]

    db.apply_whole_exam_import(exam.id, [
        {'id': 'sys', 'name': 'System', 'display_order': 1, 'is_required': True,
         'allow_multiple': False, 'root_nodes': roots(systems, 'System', 'Topic', (10, 20))},
        {'id': 'task', 'name': 'Task', 'display_order': 2, 'is_required': True,
         'allow_multiple': False, 'root_nodes': roots(tasks, 'Topic', 'Subtopic', (20, 30))},
    ])
    ids = {r['name']: r['id'] for r in db.fetchall(
        "SELECT id, name FROM subject_nodes WHERE status = 'active'")}
    dims = {r['name']: r['id'] for r in db.fetchall(
        "SELECT id, name FROM exam_dimensions WHERE exam_id = ? AND status = 'active'",
        (exam.id,))}
    session = db.create_review_session(exam_context_id=exam.id, total_questions=10,
                                       total_incorrect=2, session_name=name,
                                       date_encountered=date.today())
    pairs = ([(s, t) for s in systems for t in tasks] if every_pair
             else list(zip(systems, tasks)))
    for s, t in pairs * per_pair:
        db.create_question_entry(session.id, 'A', 'B', question_id=f'{s}/{t}',
                                 primary_subject_ids=[ids[f'{s} child'], ids[f'{t} child']])
    return exam.id, dims, ids
