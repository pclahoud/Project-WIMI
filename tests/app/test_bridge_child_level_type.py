"""Bridge tests for the child ``level_type`` derivation — issues #82, #106.

Every derivation test here runs against **both** "create a subject"
slots (the ``create_slot`` fixture), because #106 was the two of them
disagreeing: ``createSubjectNodeWithWeight`` never looked at the parent
and defaulted an omitted ``level_type`` to the literal ``'System'``, so
a child of a ``Topic`` was created as a ``System`` through one slot and
a ``Subtopic`` through the other. They now share one helper,
``HierarchyBridgeMixin._derive_child_level_type``.

``createSubjectNode`` derives the new node's ``level_type`` from the
*parent's stored* ``level_type`` whenever the caller omits the field: it
finds the parent's level name in ``get_hierarchy_levels`` and takes the
next one along. Two edges of that walk were wrong before #82:

* **Unknown vocabulary.** ``except ValueError: pass`` fell through to the
  literal ``'System'`` default at the ``create_subject_node`` call. A
  parent whose ``level_type`` is not in ``hierarchy_level_definitions`` —
  an imported outline carrying ``Section / Domain / Skill``, or a level
  renamed through ``update_hierarchy_level`` without back-filling
  ``subject_nodes.level_type`` — put a child of ``Domain`` at
  ``'System'``, silently substituting the app's vocabulary for the
  user's. Per the decision on #82 (comment #1065) the honest answer is to
  *repeat* the parent's level: there is no derivable "one below Domain".

* **Bottom of the list.** Already handled — a child of the deepest level
  repeats it — and asserted here so the two fall-through branches cannot
  drift apart.

The happy path is asserted too, because the tree editor used to bypass
this code entirely (it always sent an explicit ``level_type``, computed
from tree depth) which left the correct branch dead for every node
created through the UI.
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
def temp_master_db_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(db_path=temp_db_path, user_id=1, username="test_user")
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    master_db.bootstrap_first_user(username="test_admin", display_name="Test Admin")
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def exam(user_db: UserDatabase):
    """Exam with the default ``System/Subsystem/Topic/Subtopic/Child`` levels."""
    return user_db.create_exam_context(
        exam_name="Issue 82 Level Derivation",
        exam_description="Bridge tests for issue #82",
    )


# ==================== Helpers ====================

def _parent(user_db: UserDatabase, exam, level_type: str) -> int:
    return user_db.create_subject_node(
        exam_context=exam.exam_name,
        name=f"Parent stored as {level_type}",
        level_type=level_type,
    ).id


@pytest.fixture(params=['createSubjectNode', 'createSubjectNodeWithWeight'])
def create_slot(request) -> str:
    """Both "create a subject" slots, run through the same assertions.

    Issue #106: ``createSubjectNodeWithWeight`` creates the same row as
    ``createSubjectNode`` with a weight attached, and did not look at the
    parent at all — ``level_type=data.get('level_type', 'System')``, so a
    child of a ``Topic`` was created as a ``System`` through one slot and
    a ``Subtopic`` through the other. Both now call the one helper,
    ``_derive_child_level_type``, and parametrising the derivation tests
    over the pair is what stops them drifting apart again: a change to
    either that the other does not get fails here rather than in a
    plugin.
    """
    return request.param


def _add_child(
    bridge: DatabaseBridge,
    exam,
    parent_id: int,
    name: str,
    slot: str = 'createSubjectNode',
) -> dict:
    """Create a child the way the UI does when it omits ``level_type``."""
    payload = {
        'exam_context_id': exam.id,
        'name': name,
        'parent_id': parent_id,
    }
    if slot == 'createSubjectNodeWithWeight':
        payload['exam_weight_low'] = 10
        payload['exam_weight_high'] = 20
    response = json.loads(getattr(bridge, slot)(json.dumps(payload)))
    assert response['success'] is True, response
    return response['data']


def _stored_level(user_db: UserDatabase, node_id: int) -> str:
    return user_db.fetchone(
        "SELECT level_type FROM subject_nodes WHERE id = ?", (node_id,)
    )['level_type']


# ==================== The derivation ====================

def test_child_of_known_level_takes_the_next_one(
    bridge, user_db, exam, create_slot
):
    parent = _parent(user_db, exam, 'System')

    child = _add_child(bridge, exam, parent, "Child of System", create_slot)

    assert _stored_level(user_db, child['id']) == 'Subsystem'


def test_child_of_mid_list_level_takes_the_next_one(
    bridge, user_db, exam, create_slot
):
    parent = _parent(user_db, exam, 'Topic')

    child = _add_child(bridge, exam, parent, "Child of Topic", create_slot)

    assert _stored_level(user_db, child['id']) == 'Subtopic'


def test_child_of_the_deepest_level_repeats_it(
    bridge, user_db, exam, create_slot
):
    parent = _parent(user_db, exam, 'Child')

    child = _add_child(bridge, exam, parent, "Child of Child", create_slot)

    assert _stored_level(user_db, child['id']) == 'Child'


def test_child_of_unknown_vocabulary_repeats_the_parent(
    bridge, user_db, exam, create_slot
):
    """#82: a level name outside the configured list must survive.

    ``Domain`` is one of the in-app SAT example's levels (Section /
    Domain / Skill). Pre-fix the ``ValueError`` from ``.index()`` was
    swallowed and the child landed on the literal ``'System'``.
    """
    parent = _parent(user_db, exam, 'Domain')

    child = _add_child(bridge, exam, parent, "Child of Domain", create_slot)

    assert _stored_level(user_db, child['id']) == 'Domain', (
        "A child of a subject stored as 'Domain' must repeat 'Domain'. "
        "Falling back to 'System' discards the user's own vocabulary — "
        "the exact substitution issue #82's decision refused."
    )


def test_a_renamed_level_does_not_reset_children_to_system(
    bridge, user_db, exam, create_slot
):
    """The reachable route to unknown vocabulary, not just an import.

    ``update_hierarchy_level`` renames ``hierarchy_level_definitions``
    without back-filling ``subject_nodes.level_type``
    (``src/database/domains/hierarchy.py``), so every existing node is
    instantly carrying a name the list no longer has.
    """
    parent = _parent(user_db, exam, 'Subsystem')
    level = next(
        l for l in user_db.get_hierarchy_levels(exam.id)
        if l.level_name == 'Subsystem'
    )
    user_db.update_hierarchy_level(level.id, level_name='Organ System')

    child = _add_child(bridge, exam, parent, "Child of a renamed level", create_slot)

    assert _stored_level(user_db, child['id']) == 'Subsystem'


def test_explicit_level_type_still_wins(bridge, user_db, exam, create_slot):
    """The derivation only fires when the caller omits the field."""
    parent = _parent(user_db, exam, 'System')

    response = json.loads(getattr(bridge, create_slot)(json.dumps({
        'exam_context_id': exam.id,
        'name': "Explicitly a Topic",
        'parent_id': parent,
        'level_type': 'Topic',
        'exam_weight_low': 10,
    })))

    assert response['success'] is True, response
    assert _stored_level(user_db, response['data']['id']) == 'Topic'


def test_a_root_with_no_parent_keeps_the_System_default(
    bridge, user_db, exam, create_slot
):
    """#106: the fallback that stays.

    There is nothing to derive from without a parent, so the literal
    ``'System'`` is the honest answer rather than a substitution — and it
    is what both slots did before and still do. Asserted so the shared
    helper returning ``None`` cannot start meaning something else.
    """
    response = json.loads(getattr(bridge, create_slot)(json.dumps({
        'exam_context_id': exam.id,
        'name': "A root subject",
        'exam_weight_low': 10,
    })))

    assert response['success'] is True, response
    assert _stored_level(user_db, response['data']['id']) == 'System'


def test_both_slots_agree_on_every_configured_level(bridge, user_db, exam):
    """Issue #106 stated directly: same input, same column, either slot.

    The parametrised tests above would each pass if only one slot were
    ever run; this one compares them to each other, level by level, so a
    divergence is reported as a divergence rather than as five unrelated
    failures.
    """
    levels = [l.level_name for l in user_db.get_hierarchy_levels(exam.id)]
    assert levels, "the exam has no configured levels to walk"

    for level in levels + ['Domain']:  # + one the list does not contain
        parent = _parent(user_db, exam, level)
        plain = _add_child(
            bridge, exam, parent, f"plain child of {level}",
            'createSubjectNode',
        )
        weighted = _add_child(
            bridge, exam, parent, f"weighted child of {level}",
            'createSubjectNodeWithWeight',
        )
        assert _stored_level(user_db, plain['id']) == \
            _stored_level(user_db, weighted['id']), (
                f"a child of a {level!r} is stored as "
                f"{_stored_level(user_db, plain['id'])!r} through "
                f"createSubjectNode and "
                f"{_stored_level(user_db, weighted['id'])!r} through "
                f"createSubjectNodeWithWeight"
            )
