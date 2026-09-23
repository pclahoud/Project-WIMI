"""Bridge tests for ``RelationsBridgeMixin`` — issue #14.

The semantics are covered in ``tests/database/test_subject_relations.py``;
these prove the JSON contract ({success, data, error}), the no-``user_db``
guards, and the two places where the bridge is not a pass-through:

- a refused relation comes back as ``success=false`` with the database
  layer's own sentence, because "you have not written a reason yet" is a
  normal user state and the modal has to show it (decision 2);
- ``primary_parent_id`` reaches the read slot and reorders without
  filtering (decision 5) — the slot is the seam the deep dive uses, so
  the property is asserted through it rather than only underneath.
"""
import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


# ==================== Fixtures ====================

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
    db = UserDatabase(db_path=temp_db_path, user_id=1, username="test_user")
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase) -> DatabaseBridge:
    return DatabaseBridge(master_db=None, user_db=user_db)


@pytest.fixture
def empty_bridge() -> DatabaseBridge:
    return DatabaseBridge(master_db=None, user_db=None)


# ==================== Helpers ====================

def _node(db, name: str, dimension_id=None) -> int:
    cursor = db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, status, dimension_id) "
        "VALUES ('USMLE', ?, 'Topic', 'active', ?)",
        (name, dimension_id),
    )
    db.conn.commit()
    return cursor.lastrowid


def _create(bridge, from_id, to_id, reason, **extra):
    payload = {'from_subject_id': from_id, 'to_subject_id': to_id,
               'reason': reason}
    payload.update(extra)
    return json.loads(bridge.createSubjectRelation(json.dumps(payload)))


def _read(bridge, subject_id, parent_id=None):
    return json.loads(bridge.getSubjectRelations(json.dumps({
        'subject_id': subject_id, 'primary_parent_id': parent_id,
    })))


# ==================== Guards ====================

@pytest.mark.parametrize("call", [
    lambda b: b.getSubjectRelations('{"subject_id": 1}'),
    lambda b: b.createSubjectRelation(
        '{"from_subject_id": 1, "to_subject_id": 2, "reason": "x"}'),
    lambda b: b.deleteSubjectRelation(1),
    lambda b: b.searchRelatableSubjects('{"subject_id": 1, "query": "a"}'),
])
def test_every_slot_guards_on_no_user_database(empty_bridge, call):
    response = json.loads(call(empty_bridge))
    assert response['success'] is False
    assert 'No user database connected' in response['error']


def test_required_ids_are_reported_not_raised(bridge):
    assert json.loads(bridge.getSubjectRelations('{}'))['success'] is False
    assert json.loads(
        bridge.createSubjectRelation('{"reason": "x"}'))['success'] is False
    assert json.loads(
        bridge.searchRelatableSubjects('{"query": "a"}'))['success'] is False


# ==================== Decision 2: the reason is mandatory ====================

def test_a_relation_without_a_reason_is_refused_with_a_readable_message(bridge):
    """The modal shows this string. A traceback-flavoured error here
    would make the one mandatory field in the feature look like a bug."""
    a, b = _node(bridge.user_db, "A"), _node(bridge.user_db, "B")

    response = _create(bridge, a, b, "   ")

    assert response['success'] is False
    assert 'reason' in response['error'].lower()
    assert 'Traceback' not in response['error']
    assert _read(bridge, a)['data']['relations'] == []


def test_a_relation_with_a_reason_is_created(bridge):
    a, b = _node(bridge.user_db, "A"), _node(bridge.user_db, "B")
    response = _create(bridge, a, b, "A leads to B.")
    assert response['success'] is True
    assert response['data']['reason'] == "A leads to B."
    assert response['data']['id'] > 0


def test_a_self_loop_and_a_duplicate_come_back_as_refusals(bridge):
    a, b = _node(bridge.user_db, "A"), _node(bridge.user_db, "B")
    assert _create(bridge, a, a, "Itself.")['success'] is False
    assert _create(bridge, a, b, "First.")['success'] is True
    assert _create(bridge, a, b, "Again.")['success'] is False


# ==================== Decision 4: both ends ====================

def test_the_relation_reads_back_from_both_ends(bridge):
    a, b = _node(bridge.user_db, "A"), _node(bridge.user_db, "B")
    _create(bridge, a, b, "A leads to B.")

    from_side = _read(bridge, a)['data']['relations']
    to_side = _read(bridge, b)['data']['relations']

    assert [r['direction'] for r in from_side] == ['outgoing']
    assert [r['direction'] for r in to_side] == ['incoming']
    assert from_side[0]['relation_id'] == to_side[0]['relation_id']


# ==================== Decision 5: ordering, not filtering ====================

def test_primary_parent_id_reorders_through_the_slot_and_hides_nothing(bridge):
    db = bridge.user_db
    cardio, preg, renal = (_node(db, "Cardiovascular"), _node(db, "Pregnancy"),
                           _node(db, "Renal"))
    htn, eclampsia, rpgn = (_node(db, "Hypertension"), _node(db, "Eclampsia"),
                            _node(db, "RPGN"))
    db.add_edge(cardio, htn, is_primary=True)
    db.add_edge(preg, htn, is_primary=False)
    db.add_edge(preg, eclampsia, is_primary=True)
    db.add_edge(renal, rpgn, is_primary=True)
    _create(bridge, htn, eclampsia, "Raises eclampsia risk.")
    _create(bridge, htn, rpgn, "Malignant phase mimics RPGN.")

    def names(parent_id):
        return [r['other_subject_name']
                for r in _read(bridge, htn, parent_id)['data']['relations']]

    assert names(preg)[0] == 'Eclampsia'
    assert names(cardio)[0] == 'RPGN'
    # Every view still contains both — a filtering implementation would
    # pass an assertion on the leading item alone.
    for parent_id in (None, preg, cardio):
        assert set(names(parent_id)) == {'Eclampsia', 'RPGN'}


# ==================== Decision 11: zero relations ====================

def test_zero_relations_is_a_success_with_an_empty_list(bridge):
    """Not an error and not a 404 — the page has to be able to tell
    "nothing yet" from "something went wrong", because it renders no
    container at all for the first and a message for the second."""
    a = _node(bridge.user_db, "Lonely")
    response = _read(bridge, a)
    assert response['success'] is True
    assert response['data']['relations'] == []
    assert response['data']['fanin_soft_cap'] > 0


def test_an_unknown_subject_is_reported_not_raised(bridge):
    response = _read(bridge, 999999)
    assert response['success'] is False
    assert 'not found' in response['error'].lower()


# ==================== Delete ====================

def test_deleting_a_relation_reports_whether_it_was_there(bridge):
    a, b = _node(bridge.user_db, "A"), _node(bridge.user_db, "B")
    relation_id = _create(bridge, a, b, "Mistyped.")['data']['id']

    first = json.loads(bridge.deleteSubjectRelation(relation_id))
    second = json.loads(bridge.deleteSubjectRelation(relation_id))

    assert first['success'] is True
    assert first['data'] == {'deleted': True}
    assert second['success'] is True
    assert second['data']['deleted'] is False


# ==================== The picker ====================

def test_the_picker_returns_candidates_with_fan_in_and_dimension(bridge):
    db = bridge.user_db
    a = _node(db, "Alpha")
    _node(db, "Alpha beta")
    response = json.loads(bridge.searchRelatableSubjects(json.dumps({
        'subject_id': a, 'query': 'Alpha', 'limit': 5,
    })))
    assert response['success'] is True
    assert [r['name'] for r in response['data']] == ['Alpha beta']
    row = response['data'][0]
    assert row['incoming_count'] == 0
    assert row['crosses_dimension'] is False
    assert 'path' in row
