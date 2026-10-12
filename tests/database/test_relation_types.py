"""Relation types — owner's decision of 2026-10-03 (#14, #60).

Relations get a type from a fixed list the student owns, **per exam**,
seeded with causes / risk factor for / complication of / treats /
presents with / confused with. Each type has a forward and a reverse
label so decision 4's both-ends rendering survives; a type may be
symmetric; existing relations stay untyped until edited; a type in use is
renamed or retired, never deleted.

The reason stays mandatory (decision 2). This is type **and** sentence.
"""
from __future__ import annotations

import ast
import re
import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.exceptions import ValidationError


SRC = Path(__file__).resolve().parents[2] / 'src'
SEED_LABELS = [
    'causes', 'risk factor for', 'complication of',
    'treats', 'presents with', 'confused with',
]


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=Path(tmpdir))
        user = master.create_user(
            username="types_user", display_name="Types User", user_types=["student"])
        db = UserDatabase(
            db_path=master.ensure_user_database(user.id),
            user_id=user.id, username=user.username)
        try:
            yield db
        finally:
            db.close()
            master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context('USMLE').id


def _node(user_db, name: str, exam_name: str = 'USMLE') -> int:
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, "
        "sort_order, status) VALUES (?, ?, 'Topic', NULL, 0, 'active')",
        (exam_name, name))
    user_db.conn.commit()
    return cursor.lastrowid


def _type_id(user_db, exam_id: int, label: str) -> int:
    types = user_db.get_relation_types(exam_id, include_retired=True)
    return next(t['id'] for t in types if t['label'] == label)


def _only(payload, other_name):
    rows = [r for r in payload['relations'] if r['other_subject_name'] == other_name]
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------- seeding


def test_a_new_exam_is_seeded_with_the_owner_list(user_db, exam):
    types = user_db.get_relation_types(exam)
    assert [t['label'] for t in types] == SEED_LABELS
    by_label = {t['label']: t for t in types}
    assert by_label['causes']['reverse_label'] == 'caused by'
    assert by_label['confused with']['is_symmetric'] is True
    assert sum(t['is_symmetric'] for t in types) == 1


def test_types_are_per_exam(user_db, exam):
    other = user_db.create_exam_context('Surgery Shelf').id
    user_db.rename_relation_type(_type_id(user_db, exam, 'treats'),
                                 label='manages', reverse_label='managed by')
    assert 'treats' in [t['label'] for t in user_db.get_relation_types(other)]
    assert 'manages' not in [t['label'] for t in user_db.get_relation_types(other)]


def test_types_can_be_looked_up_from_a_subject(user_db, exam):
    a = _node(user_db, 'A')
    assert [t['label'] for t in user_db.get_relation_types(subject_id=a)] == SEED_LABELS


# ---------------------------------------------------------------- creating


def test_a_typed_relation_renders_with_its_labels_from_both_ends(user_db, exam):
    wilson, psychosis = _node(user_db, 'Wilson disease'), _node(user_db, 'Psychosis')
    user_db.create_subject_relation(
        wilson, psychosis, 'Copper deposits in the basal ganglia.',
        relation_type_id=_type_id(user_db, exam, 'causes'))

    out = _only(user_db.get_subject_relations(wilson), 'Psychosis')
    inc = _only(user_db.get_subject_relations(psychosis), 'Wilson disease')
    assert out['relation_label'] == 'causes'
    assert inc['relation_label'] == 'caused by'
    assert out['relation_type_label'] == inc['relation_type_label'] == 'causes'


def test_an_untyped_relation_still_renders_as_today(user_db, exam):
    """Decision 4 of the owner's ruling: nothing is guessed."""
    a, b = _node(user_db, 'A'), _node(user_db, 'B')
    user_db.create_subject_relation(a, b, 'Untyped, as before.')
    row = _only(user_db.get_subject_relations(a), 'B')
    assert row['relation_type_id'] is None
    assert row['relation_label'] is None
    assert row['direction'] == 'outgoing'


def test_two_types_between_one_pair_coexist(user_db, exam):
    a, b = _node(user_db, 'Obesity'), _node(user_db, 'Esophageal adenocarcinoma')
    user_db.create_subject_relation(
        a, b, 'Via GERD and Barrett.', relation_type_id=_type_id(user_db, exam, 'risk factor for'))
    user_db.create_subject_relation(
        a, b, 'I mixed them up once.', relation_type_id=_type_id(user_db, exam, 'confused with'))
    labels = sorted(r['relation_type_label']
                    for r in user_db.get_subject_relations(a)['relations'])
    assert labels == ['confused with', 'risk factor for']


def test_the_same_typed_statement_is_refused_with_a_sentence(user_db, exam):
    a, b = _node(user_db, 'A'), _node(user_db, 'B')
    causes = _type_id(user_db, exam, 'causes')
    user_db.create_subject_relation(a, b, 'First.', relation_type_id=causes)
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(a, b, 'Again.', relation_type_id=causes)


def test_a_symmetric_relation_cannot_be_stored_twice(user_db, exam):
    """Written from either page, ``A confused with B`` is one relation."""
    a, b = _node(user_db, 'Seborrheic keratosis'), _node(user_db, 'Melanoma')
    confused = _type_id(user_db, exam, 'confused with')
    created = user_db.create_subject_relation(b, a, 'Both pigmented, both "stuck on".',
                                              relation_type_id=confused)
    assert (created['from_subject_id'], created['to_subject_id']) == (min(a, b), max(a, b))
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(a, b, 'Again, from the other page.',
                                        relation_type_id=confused)


def test_a_symmetric_relation_reads_the_same_from_both_ends(user_db, exam):
    a, b = _node(user_db, 'Aortic dissection'), _node(user_db, 'Esophageal perforation')
    user_db.create_subject_relation(a, b, 'Both tear into the mediastinum.',
                                    relation_type_id=_type_id(user_db, exam, 'confused with'))
    from_a = _only(user_db.get_subject_relations(a), 'Esophageal perforation')
    from_b = _only(user_db.get_subject_relations(b), 'Aortic dissection')
    assert from_a['direction'] == from_b['direction'] == 'symmetric'
    assert from_a['relation_label'] == from_b['relation_label'] == 'confused with'


def test_a_type_from_another_exam_is_refused(user_db, exam):
    other = user_db.create_exam_context('Surgery Shelf').id
    a, b = _node(user_db, 'A'), _node(user_db, 'B')
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(
            a, b, 'Wrong exam.', relation_type_id=_type_id(user_db, other, 'causes'))


def test_an_unknown_type_is_refused(user_db, exam):
    a, b = _node(user_db, 'A'), _node(user_db, 'B')
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(a, b, 'No such type.', relation_type_id=999999)


def test_the_reason_is_still_mandatory_with_a_type(user_db, exam):
    """Decision 2 is untouched: a type does not replace the sentence."""
    a, b = _node(user_db, 'A'), _node(user_db, 'B')
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(
            a, b, '   ', relation_type_id=_type_id(user_db, exam, 'causes'))


# ---------------------------------------------------------------- rename / retire


def test_a_rename_reaches_every_relation_using_the_type(user_db, exam):
    a, b, c = _node(user_db, 'A'), _node(user_db, 'B'), _node(user_db, 'C')
    causes = _type_id(user_db, exam, 'causes')
    user_db.create_subject_relation(a, b, 'One.', relation_type_id=causes)
    user_db.create_subject_relation(c, b, 'Two.', relation_type_id=causes)

    user_db.rename_relation_type(causes, label='produces', reverse_label='produced by')

    incoming = user_db.get_subject_relations(b)['relations']
    assert {r['relation_label'] for r in incoming} == {'produced by'}
    assert _only(user_db.get_subject_relations(a), 'B')['relation_label'] == 'produces'


def test_a_rename_cannot_take_an_active_label(user_db, exam):
    with pytest.raises(ValidationError):
        user_db.rename_relation_type(_type_id(user_db, exam, 'treats'),
                                     label='Causes', reverse_label='x')


def test_a_symmetric_type_keeps_one_label(user_db, exam):
    confused = _type_id(user_db, exam, 'confused with')
    user_db.rename_relation_type(confused, label='mistaken for')
    t = next(t for t in user_db.get_relation_types(exam) if t['id'] == confused)
    assert t['label'] == t['reverse_label'] == 'mistaken for'


def test_a_retired_type_leaves_the_picker_but_its_relations_still_render(user_db, exam):
    a, b = _node(user_db, 'A'), _node(user_db, 'B')
    treats = _type_id(user_db, exam, 'treats')
    user_db.create_subject_relation(a, b, 'First-line.', relation_type_id=treats)

    user_db.retire_relation_type(treats)

    assert 'treats' not in [t['label'] for t in user_db.get_relation_types(exam)]
    assert 'treats' in [t['label'] for t in
                        user_db.get_relation_types(exam, include_retired=True)]
    row = _only(user_db.get_subject_relations(a), 'B')
    assert row['relation_label'] == 'treats'
    assert row['relation_type_retired'] is True


def test_a_retired_type_cannot_start_a_new_relation(user_db, exam):
    a, b = _node(user_db, 'A'), _node(user_db, 'B')
    treats = _type_id(user_db, exam, 'treats')
    user_db.retire_relation_type(treats)
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(a, b, 'Too late.', relation_type_id=treats)


def test_a_retired_type_can_be_reinstated(user_db, exam):
    treats = _type_id(user_db, exam, 'treats')
    user_db.retire_relation_type(treats)
    user_db.reinstate_relation_type(treats)
    assert 'treats' in [t['label'] for t in user_db.get_relation_types(exam)]


def test_there_is_no_way_to_delete_a_type(user_db):
    """Owner's decision 5: renamed or retired, never deleted."""
    assert not hasattr(user_db, 'delete_relation_type')


# ---------------------------------------------------------------- picker candidates


def test_the_picker_offers_a_subject_already_related_by_another_type(user_db, exam):
    """Under m019 a subject already pointed at was hidden from the picker.
    With types, *A causes B* existing must not stop *A confused with B*."""
    a = _node(user_db, 'Crohn disease')
    b = _node(user_db, 'Nephrolithiasis')
    causes = _type_id(user_db, exam, 'causes')
    user_db.create_subject_relation(a, b, 'Oxalate absorption.', relation_type_id=causes)

    same = user_db.search_relatable_subjects(
        a, 'Nephro', direction='outgoing', relation_type_id=causes)
    other = user_db.search_relatable_subjects(
        a, 'Nephro', direction='outgoing',
        relation_type_id=_type_id(user_db, exam, 'complication of'))
    assert [r['id'] for r in same] == []
    assert [r['id'] for r in other] == [b]


def test_the_picker_hides_a_symmetric_partner_from_either_end(user_db, exam):
    a, b = _node(user_db, 'Sigmoid volvulus'), _node(user_db, 'Ogilvie syndrome')
    confused = _type_id(user_db, exam, 'confused with')
    user_db.create_subject_relation(a, b, 'Both dilated colon.', relation_type_id=confused)
    for here, query in ((a, 'Ogilvie'), (b, 'Sigmoid')):
        assert user_db.search_relatable_subjects(
            here, query, direction='symmetric', relation_type_id=confused) == []


# ---------------------------------------------------------------- the sweep


@pytest.mark.database
def test_every_read_of_relation_types_says_whether_it_sees_retired_rows():
    """Partial adoption is worse than none (#210's lesson, applied here).

    A retired type must not leak into a new-relation picker, and an existing
    relation must keep rendering with its retired type. Both are reads of
    ``relation_types``, in opposite directions -- so every query must either
    filter on ``status`` or carry an ``includes-retired`` marker saying it
    means to see retired rows. A query with neither is the bug.
    """
    offenders, scanned = [], 0
    for path in (SRC / 'database').rglob('*.py'):
        if path.name.startswith('m0'):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                continue
            if not re.search(r'(?:FROM|JOIN)\s+relation_types\b', node.value):
                continue
            scanned += 1
            if 'includes-retired' in node.value:
                continue
            if 'status' not in node.value:
                offenders.append(f'{path.relative_to(SRC)}:{node.lineno}')
    assert scanned >= 3, f'only {scanned} queries found -- the scan is blind'
    assert offenders == [], (
        'these read relation_types without saying whether retired types are '
        f'meant to appear: {offenders}')
