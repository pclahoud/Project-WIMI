"""Tests for user-DB migration v25 — ``exam_dimensions.import_id`` (#66 2.3).

The dimension-level mirror of m020. Three properties beyond "the column
exists", each of which m020 had to get right one level down:

* **The unique index is scoped per exam, not globally.** The id is the
  *file's* identifier, and two exams may legitimately both call a dimension
  ``"axis-1"``.
* **It is partial on `status = 'active'`.** A dimension #210 archived keeps
  its row and its id; re-importing a file that lists it again must be free to
  create it rather than collide with a row nothing can see.
* **The table may be absent.** `exam_dimensions` comes from the legacy
  `_ensure_phase7_schema`, so a database that never opened Phase 7 does not
  have it, and the migration must still stamp.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration_runner import MigrationRunner
from database.migrations._helpers import get_column_names
from database.migrations.user import MIGRATIONS


def _full_runner(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(conn, registry=MIGRATIONS, scope="user")


def _runner_through_v24(conn: sqlite3.Connection) -> MigrationRunner:
    return MigrationRunner(
        conn,
        registry=[m for m in MIGRATIONS if m.version <= 24],
        scope="user",
    )


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }


def _exams(conn: sqlite3.Connection, n: int = 2) -> list[int]:
    """Real `exam_contexts` rows.

    `exam_dimensions.exam_id` is a genuine FOREIGN KEY and `foreign_keys` is
    ON, so inserting a dimension against an invented exam id fails before the
    index under test is ever consulted.
    """
    ids = []
    for i in range(n):
        cur = conn.execute(
            "INSERT INTO exam_contexts (user_id, exam_name) VALUES (1, ?)",
            (f"Exam {i}",))
        ids.append(cur.lastrowid)
    return ids


def test_registry_has_v25_in_order():
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 25 in versions
    # The gaps stay gaps: v8 is the assessments branch, v11-v14 were stamped
    # into real databases by the paused AI-capture branch (#145).
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions
    # A snapshot claim, held by whichever migration is newest, and by exactly
    # one file at a time. m026 will make this fail, and the fix is to MOVE the
    # line into m026's test, not to loosen it -- it is the one assertion in
    # the suite that notices a migration arriving with nothing else updated.
    # It has now been carried m023 -> m024 -> here.
    assert max(versions) == 25


def test_it_adds_the_column(fresh_conn):
    _full_runner(fresh_conn).apply_pending()

    assert "import_id" in get_column_names(fresh_conn, "exam_dimensions")


def test_it_survives_the_table_being_absent(fresh_conn):
    """`fresh_conn` builds a Phase 7 database, so the absence has to be made."""
    _runner_through_v24(fresh_conn).apply_pending()
    fresh_conn.execute("DROP TABLE IF EXISTS exam_dimensions")

    _full_runner(fresh_conn).apply_pending()

    assert 'exam_dimensions' not in _tables(fresh_conn)
    stamped = {r[0] for r in fresh_conn.execute(
        "SELECT version FROM schema_migrations")}
    assert 25 in stamped


def test_two_exams_may_share_an_import_id(fresh_conn):
    """The id belongs to the file, not to WIMI.

    Two exams may legitimately both name a dimension `"axis-1"`. A globally
    unique index would make the second import fail for no reason.
    """
    _full_runner(fresh_conn).apply_pending()

    a, b = _exams(fresh_conn)
    fresh_conn.execute(
        "INSERT INTO exam_dimensions (exam_id, name, display_order, import_id) "
        "VALUES (?, 'System', 1, 'axis-1')", (a,))
    fresh_conn.execute(
        "INSERT INTO exam_dimensions (exam_id, name, display_order, import_id) "
        "VALUES (?, 'System', 1, 'axis-1')", (b,))

    rows = fresh_conn.execute(
        "SELECT COUNT(*) FROM exam_dimensions WHERE import_id = 'axis-1'"
    ).fetchone()[0]
    assert rows == 2


def test_one_exam_may_not_reuse_an_import_id(fresh_conn):
    """Negative control for the test above.

    Without it, dropping the index entirely would pass `two_exams_may_share`
    and leave nothing constraining anything.
    """
    _full_runner(fresh_conn).apply_pending()

    (a,) = _exams(fresh_conn, 1)
    fresh_conn.execute(
        "INSERT INTO exam_dimensions (exam_id, name, display_order, import_id) "
        "VALUES (?, 'System', 1, 'axis-1')", (a,))

    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO exam_dimensions (exam_id, name, display_order, import_id) "
            "VALUES (?, 'Task', 2, 'axis-1')", (a,))


def test_an_archived_dimension_frees_its_import_id(fresh_conn):
    """The `status = 'active'` half of the partial index (#210 made it possible).

    A dimension the import removed keeps its row and its id. Re-importing a
    file that lists it again must create a fresh one rather than collide with
    a row the student cannot see.
    """
    _full_runner(fresh_conn).apply_pending()

    (a,) = _exams(fresh_conn, 1)
    fresh_conn.execute(
        "INSERT INTO exam_dimensions (exam_id, name, display_order, import_id, status) "
        "VALUES (?, 'System', 1, 'axis-1', 'archived')", (a,))
    # Same exam, same import_id, but only one of them is active.
    fresh_conn.execute(
        "INSERT INTO exam_dimensions (exam_id, name, display_order, import_id) "
        "VALUES (?, 'System Again', 2, 'axis-1')", (a,))

    active = fresh_conn.execute(
        "SELECT COUNT(*) FROM exam_dimensions "
        "WHERE import_id = 'axis-1' AND status = 'active'").fetchone()[0]
    assert active == 1


def test_many_dimensions_may_have_no_import_id(fresh_conn):
    """Nothing populates this column yet, so every existing row is NULL.

    **This does not test the `import_id IS NOT NULL` predicate**, and an
    earlier version of this docstring wrongly claimed it did — *"an index that
    constrained NULLs would let an exam have exactly one dimension"*. That is
    false: **SQLite treats NULLs as distinct in a unique index**, so many NULL
    rows are permitted with or without the predicate. Removing it from the
    migration passes every test in this file, which is how the error surfaced.

    The predicate earns its place for a different reason — it makes the index
    *partial*, so rows with no id are not indexed at all. With nothing writing
    the column yet that is every row, and the index stays empty rather than
    carrying an entry per dimension. It also mirrors m020, which matters more
    than the bytes.

    What this test is: a behavioural guard that the common case works. Worth
    keeping, worth not mislabelling.
    """
    _full_runner(fresh_conn).apply_pending()

    (a,) = _exams(fresh_conn, 1)
    for order, name in enumerate(('System', 'Task', 'Site'), start=1):
        fresh_conn.execute(
            "INSERT INTO exam_dimensions (exam_id, name, display_order) "
            "VALUES (?, ?, ?)", (a, name, order))

    count = fresh_conn.execute(
        "SELECT COUNT(*) FROM exam_dimensions WHERE exam_id = ?", (a,)
    ).fetchone()[0]
    assert count == 3


def test_it_is_idempotent(fresh_conn):
    _full_runner(fresh_conn).apply_pending()
    _full_runner(fresh_conn).apply_pending()

    assert "import_id" in get_column_names(fresh_conn, "exam_dimensions")
