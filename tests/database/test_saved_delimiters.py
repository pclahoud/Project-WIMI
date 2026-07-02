"""Tests for saved delimiters CRUD operations."""

import pytest
from database.user_db import UserDatabase


@pytest.fixture
def db(tmp_path):
    """Create a temporary UserDatabase with schema initialized."""
    db_path = tmp_path / "test_user.db"
    db = UserDatabase(str(db_path), user_id=1, username="testuser")
    db._ensure_phase4_schema()
    return db


class TestSavedDelimitersTable:
    """Test that the saved_delimiters table is created during schema migration."""

    def test_table_exists(self, db):
        tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {row['name'] for row in tables}
        assert 'saved_delimiters' in table_names

    def test_table_columns(self, db):
        columns = db.fetchall("PRAGMA table_info(saved_delimiters)")
        col_names = {col['name'] for col in columns}
        assert col_names == {'id', 'name', 'value', 'hotkey', 'sort_order', 'created_at'}


class TestCreateSavedDelimiter:
    def test_create_basic(self, db):
        result = db.create_saved_delimiter(name='Semicolon', value='; ')
        assert result['name'] == 'Semicolon'
        assert result['value'] == '; '
        assert result['hotkey'] is None
        assert result['sort_order'] == 0
        assert result['id'] is not None

    def test_create_with_hotkey(self, db):
        result = db.create_saved_delimiter(name='Pipe', value=' | ', hotkey='/p')
        assert result['name'] == 'Pipe'
        assert result['value'] == ' | '
        assert result['hotkey'] == '/p'

    def test_sort_order_increments(self, db):
        d1 = db.create_saved_delimiter(name='First', value=', ')
        d2 = db.create_saved_delimiter(name='Second', value='; ')
        d3 = db.create_saved_delimiter(name='Third', value=' | ')
        assert d1['sort_order'] == 0
        assert d2['sort_order'] == 1
        assert d3['sort_order'] == 2


class TestGetSavedDelimiters:
    def test_get_empty(self, db):
        result = db.get_saved_delimiters()
        assert result == []

    def test_get_all(self, db):
        db.create_saved_delimiter(name='A', value=', ')
        db.create_saved_delimiter(name='B', value='; ')
        result = db.get_saved_delimiters()
        assert len(result) == 2
        assert result[0]['name'] == 'A'
        assert result[1]['name'] == 'B'

    def test_ordered_by_sort_order(self, db):
        db.create_saved_delimiter(name='First', value='a')
        db.create_saved_delimiter(name='Second', value='b')
        db.create_saved_delimiter(name='Third', value='c')
        result = db.get_saved_delimiters()
        names = [r['name'] for r in result]
        assert names == ['First', 'Second', 'Third']


class TestDeleteSavedDelimiter:
    def test_delete(self, db):
        d = db.create_saved_delimiter(name='ToDelete', value='; ')
        assert db.delete_saved_delimiter(d['id']) is True
        assert db.get_saved_delimiters() == []

    def test_delete_one_of_many(self, db):
        d1 = db.create_saved_delimiter(name='Keep', value=', ')
        d2 = db.create_saved_delimiter(name='Delete', value='; ')
        d3 = db.create_saved_delimiter(name='AlsoKeep', value=' | ')
        db.delete_saved_delimiter(d2['id'])
        result = db.get_saved_delimiters()
        assert len(result) == 2
        names = [r['name'] for r in result]
        assert 'Keep' in names
        assert 'AlsoKeep' in names
        assert 'Delete' not in names
