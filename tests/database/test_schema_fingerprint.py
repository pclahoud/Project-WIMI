"""The structural comparison behind #593's import check.

Each foreign database is a fresh WIMI database plus one named mutation from
``tests/_schema_mutations.py``, built at runtime. The rules each test pins,
and the history that measured them, are in ``database/schema_fingerprint.py``.
"""
from __future__ import annotations

import sqlite3

import pytest

from tests import _schema_mutations as mutate
from database.schema_fingerprint import (
    LEGACY_MISSING_CHECKS, _check_clauses, compare, fingerprint)
from database.user_db import UserDatabase


@pytest.fixture
def fresh_db(tmp_path):
    path = tmp_path / 'fresh.db'
    UserDatabase(db_path=path, user_id=1, username='fresh').close()
    return path


@pytest.fixture
def expected(fresh_db):
    conn = sqlite3.connect(fresh_db)
    try:
        return fingerprint(conn)
    finally:
        conn.close()


def _problems_after(fresh_db, expected, mutation):
    conn = sqlite3.connect(fresh_db)
    try:
        mutation(conn)
        return compare(expected, fingerprint(conn))
    finally:
        conn.close()


def test_a_fresh_database_matches_itself(fresh_db, expected):
    """Positive control. Without it, every refusal below could be a check
    that refuses everything."""
    assert _problems_after(fresh_db, expected, lambda conn: None) == []


def test_a_rebuilt_table_with_nothing_changed_still_matches(fresh_db, expected):
    """The mutation helper's own control. Rebuilding a table changes its
    stored text and its position in sqlite_master, and neither may count as
    a difference, or the refusals below would be the helper's doing."""
    assert _problems_after(
        fresh_db, expected,
        lambda conn: mutate.redeclare(conn, 'subject_aliases', 'is_primary', 'is_primary'),
    ) == []


@pytest.mark.parametrize('mutation, names', [
    (mutate.drop_alias_type_check, ['subject_aliases', 'alias_type in(']),
    (mutate.alias_id_as_text, ['subject_aliases', '"id"', 'TEXT PRIMARY KEY',
                               'INTEGER PRIMARY KEY']),
    (mutate.add_trigger, ['trigger', 'mutation_trigger']),
    (mutate.add_view, ['view', 'mutation_view']),
    (mutate.drop_font_scale_check, ['user_preferences', 'font_size_scale']),
], ids=['variant-A-check-dropped', 'variant-D-id-as-text', 'extra-trigger',
        'extra-view', 'a-check-no-profile-ever-lacked'])
def test_a_changed_structure_is_reported_by_name(fresh_db, expected, mutation, names):
    problems = _problems_after(fresh_db, expected, mutation)
    assert problems, f'{mutation.__name__} was not detected'
    text = ' '.join(problems)
    for name in names:
        assert name in text, (
            f'the report does not name {name!r}, so a student cannot tell '
            f'what was found: {problems!r}')


def test_additions_wimi_never_reads_are_allowed(fresh_db, expected):
    """The AI-capture builds left extra tables, columns and indexes in real
    profiles and changed nothing WIMI declares. Refusing them would lock
    those profiles out."""
    assert _problems_after(fresh_db, expected, mutate.add_unread_extras) == []


def test_the_measured_legacy_gap_is_allowed_and_nothing_wider(fresh_db, expected):
    assert _problems_after(fresh_db, expected, mutate.drop_legacy_checks) == []

    conn = sqlite3.connect(fresh_db)
    try:
        mutate.drop_font_scale_check(conn)
        problems = compare(expected, fingerprint(conn))
    finally:
        conn.close()
    assert len(problems) == 1 and 'font_size_scale' in problems[0], problems


def test_every_tolerated_check_is_one_a_fresh_database_declares(expected):
    """A tolerance entry nobody can match is dead. Worse, one that drifts
    from the real CHECK text tolerates nothing while reading as though it
    does. So every entry must name a CHECK the current schema declares."""
    for table, checks in LEGACY_MISSING_CHECKS.items():
        assert checks <= expected.tables[table].checks, (
            table, sorted(checks - expected.tables[table].checks))


def test_check_clauses_ignore_layout_and_keep_literal_case():
    a = _check_clauses("CREATE TABLE t (x TEXT CHECK (x IN ('A', 'b')))")
    b = _check_clauses('CREATE TABLE t (\n  x TEXT\n  check(x   in (\'A\',\'b\'))\n)')
    assert a == b == frozenset({"x in('A','b')"})
    assert _check_clauses("CREATE TABLE t (x TEXT CHECK (x IN ('a', 'b')))") != a
