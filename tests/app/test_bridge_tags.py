"""Bridge tests for the tag-management slots.

Covers ``TagBridgeMixin``'s ``deleteTag``, ``updateTagDescription``,
and the 4-arg ``createTagInGroup`` (description pass-through). The
domain layer is covered in ``tests/database/test_tag_management.py``;
these tests prove the JSON contract ({success, data, error}), the
TagError → success=false mapping, and the no-user_db guards.
"""
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


EXAM = 'Bridge Tag Exam'


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except Exception:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for master database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    """Create a UserDatabase instance for testing."""
    db = UserDatabase(
        db_path=temp_db_path,
        user_id=1,
        username="test_user",
    )
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    """Create a MasterDatabase for testing."""
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase) -> DatabaseBridge:
    """Create a DatabaseBridge wired to test databases."""
    master_db.bootstrap_first_user(
        username="test_admin",
        display_name="Test Admin",
    )
    return DatabaseBridge(master_db=master_db, user_db=user_db)


@pytest.fixture
def bridge_no_user(master_db: MasterDatabase) -> DatabaseBridge:
    """Bridge with NO user database connected (guard-path testing)."""
    return DatabaseBridge(master_db=master_db, user_db=None)


# ---- Seed helpers ----------------------------------------------------------


def _make_group(db: UserDatabase, name: str = 'Knowledge Issues'):
    """Create a tag group directly via the domain mixin."""
    return db.create_tag_group(exam_context=EXAM, group_name=name)


def _make_tag(db: UserDatabase, group_id: int, name: str = 'Knowledge Gap',
              description=None):
    """Create a type inside a group directly via the domain mixin."""
    return db.create_hierarchical_tag(
        exam_context=EXAM,
        tag_name=name,
        group_id=group_id,
        description=description,
    )


def _tag_entries(db: UserDatabase, tag_id: int, count: int = 1) -> list[int]:
    """Create ``count`` question entries tagged with ``tag_id``.

    Goes through the real entries path (create_question_entry inserts
    the entry_tags junction rows), returning the new entry ids.
    """
    ctx = db.create_exam_context(exam_name=EXAM, exam_description='')
    session = db.create_review_session(
        exam_context_id=ctx.id,
        total_questions=10,
        total_incorrect=count,
        session_name='Bridge tag test session',
        date_encountered=date.today(),
    )
    entry_ids = []
    for _ in range(count):
        entry = db.create_question_entry(
            review_session_id=session.id,
            user_answer='A',
            correct_answer='B',
            tag_ids=[tag_id],
        )
        entry_ids.append(entry.id)
    return entry_ids


# ---- Response helpers ------------------------------------------------------


def _parse(response: str) -> dict:
    return json.loads(response)


def _ok(response: str) -> dict:
    payload = _parse(response)
    assert payload['success'] is True, (
        f"Expected success, got error: {payload.get('error')}"
    )
    return payload.get('data')


def _err(response: str) -> str:
    payload = _parse(response)
    assert payload['success'] is False, "Expected error, got success"
    return payload.get('error')


# ==================== deleteTag ====================


class TestDeleteTag:
    def test_delete_tag_returns_affected_entries(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Happy path: delete a used tag; affected_entries reflects the
        live entry_tags count and the junction rows cascade away."""
        group = _make_group(user_db)
        tag = _make_tag(user_db, group.id)
        _tag_entries(user_db, tag.id, count=2)

        data = _ok(bridge.deleteTag(tag.id))

        assert data == {
            'id': tag.id,
            'name': 'Knowledge Gap',
            'affected_entries': 2,
        }

        # Tag is gone and the entries were untagged (cascade).
        assert user_db.get_tag(tag.id) is None
        row = user_db.fetchone(
            "SELECT COUNT(*) as count FROM entry_tags WHERE tag_id = ?",
            (tag.id,),
        )
        assert row['count'] == 0

    def test_delete_unused_tag_reports_zero_affected(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        group = _make_group(user_db)
        tag = _make_tag(user_db, group.id, name='Second-Guessing')

        data = _ok(bridge.deleteTag(tag.id))
        assert data['affected_entries'] == 0
        assert data['name'] == 'Second-Guessing'

    def test_delete_non_empty_group_returns_clean_error(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """A group that still contains types is refused with the
        user-facing 'contains N types' message (TagError mapping)."""
        group = _make_group(user_db, name='Test Strategy')
        _make_tag(user_db, group.id, name='Time Pressure')
        _make_tag(user_db, group.id, name='Wrong Guess Strategy')

        error = _err(bridge.deleteTag(group.id))

        assert error == (
            "Group 'Test Strategy' contains 2 types; "
            "delete or move them first"
        )
        # Group survives the refused delete.
        assert user_db.get_tag(group.id) is not None

    def test_delete_empty_group_succeeds(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        group = _make_group(user_db, name='Empty Group')

        data = _ok(bridge.deleteTag(group.id))
        assert data['id'] == group.id
        assert data['affected_entries'] == 0
        assert user_db.get_tag(group.id) is None

    def test_delete_missing_tag_returns_error(
        self, bridge: DatabaseBridge
    ):
        error = _err(bridge.deleteTag(99999))
        assert error == 'Tag 99999 not found'

    def test_delete_tag_no_user_db_guard(self, bridge_no_user: DatabaseBridge):
        error = _err(bridge_no_user.deleteTag(1))
        assert error == 'No user database connected'

    def test_delete_tag_json_contract(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """Success payload carries {success, data}; failure carries
        {success, error} — the standard serialize_response contract."""
        group = _make_group(user_db)
        tag = _make_tag(user_db, group.id)

        ok_payload = _parse(bridge.deleteTag(tag.id))
        assert ok_payload['success'] is True
        assert set(ok_payload['data'].keys()) == {
            'id', 'name', 'affected_entries'
        }
        assert 'error' not in ok_payload

        err_payload = _parse(bridge.deleteTag(tag.id))  # already gone
        assert err_payload['success'] is False
        assert isinstance(err_payload['error'], str)
        assert 'data' not in err_payload


# ==================== updateTagDescription ====================


class TestUpdateTagDescription:
    def test_set_description(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        group = _make_group(user_db)
        tag = _make_tag(user_db, group.id)

        data = _ok(bridge.updateTagDescription(
            tag.id, 'You never learned or covered this material.'
        ))

        assert data == {
            'id': tag.id,
            'description': 'You never learned or covered this material.',
        }
        # Persisted.
        assert user_db.get_tag(tag.id).description == (
            'You never learned or covered this material.'
        )

    def test_clear_description_with_empty_string(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """'' normalizes to NULL — the definition is cleared."""
        group = _make_group(user_db)
        tag = _make_tag(user_db, group.id, description='Old definition.')

        data = _ok(bridge.updateTagDescription(tag.id, ''))

        assert data == {'id': tag.id, 'description': None}
        assert user_db.get_tag(tag.id).description is None

    def test_update_missing_tag_returns_error(self, bridge: DatabaseBridge):
        error = _err(bridge.updateTagDescription(99999, 'anything'))
        assert error == 'Tag 99999 not found'

    def test_update_description_no_user_db_guard(
        self, bridge_no_user: DatabaseBridge
    ):
        error = _err(bridge_no_user.updateTagDescription(1, 'x'))
        assert error == 'No user database connected'


# ==================== createTagInGroup ====================


class TestCreateTagInGroup:
    def test_create_with_description(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        group = _make_group(user_db)

        data = _ok(bridge.createTagInGroup(
            EXAM, 'Panic Spiral', group.id,
            'You spiraled after one hard question.',
        ))

        assert data['name'] == 'Panic Spiral'
        assert data['description'] == 'You spiraled after one hard question.'
        assert data['group_id'] == group.id
        assert data['is_group'] is False
        # Inherits the parent group's color.
        assert data['color'] == group.color_hex
        # Persisted on the row too.
        assert user_db.get_tag(data['id']).description == (
            'You spiraled after one hard question.'
        )

    def test_create_without_description(
        self, bridge: DatabaseBridge, user_db: UserDatabase
    ):
        """'' (the JS wrapper default) maps to NULL — no definition."""
        group = _make_group(user_db)

        data = _ok(bridge.createTagInGroup(EXAM, 'No Def Tag', group.id, ''))

        assert data['name'] == 'No Def Tag'
        assert data['description'] is None
        assert user_db.get_tag(data['id']).description is None

    def test_create_missing_group_returns_error(self, bridge: DatabaseBridge):
        error = _err(bridge.createTagInGroup(EXAM, 'Orphan', 99999, ''))
        assert error and 'Failed to create tag' in error

    def test_create_no_user_db_guard(self, bridge_no_user: DatabaseBridge):
        error = _err(bridge_no_user.createTagInGroup(EXAM, 'X', 1, ''))
        assert error == 'No user database connected'
