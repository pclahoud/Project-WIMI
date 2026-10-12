"""m027 — the rejection table, and the scope rule it exists to encode (#60).

The tests that matter here are not "does the table exist". They are the ones
that would still pass against #14 decision 8's ``strength = -1`` sentinel if
this were built carelessly, and therefore have to be written so they do not:

* a ``misread`` rejection must be **scoped to its entry**, because 25 of #60's
  45 rejections meant "you misread my sentence" and suppressing those globally
  throws away true relations;
* a ``not_related`` rejection must be **global**, because re-asking a question
  the student has answered is the failure in the other direction;
* a symmetric type's rejection must canonicalise, or the student is asked again
  from the other end.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migrations.user import m019_subject_relations  # noqa: F401
from database.migrations.user import m026_relation_types, m027_relation_rejections


def _apply(conn: sqlite3.Connection) -> None:
    """Build just enough schema for m027, then apply it."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE exam_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, exam_name TEXT NOT NULL)
    """)
    conn.execute("""
        CREATE TABLE subject_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active')
    """)
    conn.execute("""
        CREATE TABLE question_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT)
    """)
    conn.execute("INSERT INTO exam_contexts (exam_name) VALUES ('Step 1')")
    for name in ("Hypertension", "Nephrosclerosis", "Diabetes"):
        conn.execute("INSERT INTO subject_nodes (name) VALUES (?)", (name,))
    conn.execute("INSERT INTO question_entries DEFAULT VALUES")
    conn.execute("INSERT INTO question_entries DEFAULT VALUES")
    m026_relation_types.upgrade(conn)
    m027_relation_rejections.upgrade(conn)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _apply(c)
    yield c
    c.close()


def _type_id(conn, label: str) -> int:
    return conn.execute(
        "SELECT id FROM relation_types WHERE label = ?", (label,)).fetchone()[0]


def _reject(conn, frm, to, type_id, kind, entry=None):
    conn.execute(
        "INSERT INTO subject_relation_rejections "
        "(from_subject_id, to_subject_id, relation_type_id, kind, source_entry_id) "
        "VALUES (?, ?, ?, ?, ?)", (frm, to, type_id, kind, entry))


def _is_suppressed(conn, frm, to, type_id, entry) -> bool:
    """The suppression rule, written once here so the tests agree on it."""
    row = conn.execute(
        "SELECT 1 FROM subject_relation_rejections "
        " WHERE from_subject_id = ? AND to_subject_id = ? "
        "   AND relation_type_id IS ? "
        "   AND (kind = 'not_related' OR source_entry_id = ?) LIMIT 1",
        (frm, to, type_id, entry)).fetchone()
    return row is not None


# --------------------------------------------------------------------------
# The scope rule. These two are the point of the table.
# --------------------------------------------------------------------------

def test_a_misread_is_scoped_to_the_entry_it_was_misread_from(conn):
    """25 of 45 rejections meant "you misread my sentence" (#60).

    Suppressing those globally is what `strength = -1` would have done, and it
    throws away a relation that a different explanation may state correctly.
    """
    causes = _type_id(conn, "causes")
    _reject(conn, 1, 2, causes, "misread", entry=1)

    assert _is_suppressed(conn, 1, 2, causes, entry=1), (
        "the entry it was misread from must not re-propose it")
    assert not _is_suppressed(conn, 1, 2, causes, entry=2), (
        "a DIFFERENT entry must still be able to propose this pair -- the "
        "student rejected a reading of one passage, not the relation")


def test_not_related_is_global(conn):
    """A claim about the subjects, not about one passage.

    The failure in this direction is re-asking a question the student has
    already answered, every time they write about either subject.
    """
    causes = _type_id(conn, "causes")
    _reject(conn, 1, 3, causes, "not_related", entry=1)

    assert _is_suppressed(conn, 1, 3, causes, entry=1)
    assert _is_suppressed(conn, 1, 3, causes, entry=2), (
        "a not_related rejection must suppress everywhere, or the student is "
        "asked the same question again from the next entry")


def test_a_rejection_of_one_type_does_not_suppress_another(conn):
    """m026 made several types per pair ordinary; rejections follow.

    "Hypertension causes diabetes -- no" says nothing about whether the student
    confuses the two, and that is exactly the pair #14's seed list expects.
    """
    causes = _type_id(conn, "causes")
    confused = _type_id(conn, "confused with")
    _reject(conn, 1, 3, causes, "not_related")

    assert _is_suppressed(conn, 1, 3, causes, entry=1)
    assert not _is_suppressed(conn, 1, 3, confused, entry=1)


# --------------------------------------------------------------------------
# The schema enforcing the scope rule
# --------------------------------------------------------------------------

def test_a_misread_without_its_entry_is_refused(conn):
    """A misread with no text could never match the suppression query.

    It would sit in the table suppressing nothing, silently -- so the CHECK
    refuses it rather than letting it look like a recorded decision.
    """
    causes = _type_id(conn, "causes")
    with pytest.raises(sqlite3.IntegrityError) as exc:
        _reject(conn, 1, 2, causes, "misread", entry=None)
    assert "CHECK" in str(exc.value) or "constraint" in str(exc.value).lower()


def test_not_related_needs_no_entry(conn):
    """The counterpart control: the CHECK must not over-reach.

    Without this, a CHECK written as `source_entry_id IS NOT NULL` for every
    kind would pass the test above and silently forbid the global case.
    """
    causes = _type_id(conn, "causes")
    _reject(conn, 1, 3, causes, "not_related", entry=None)
    assert conn.execute(
        "SELECT COUNT(*) FROM subject_relation_rejections").fetchone()[0] == 1


def test_an_unknown_kind_is_refused(conn):
    causes = _type_id(conn, "causes")
    with pytest.raises(sqlite3.IntegrityError):
        _reject(conn, 1, 2, causes, "wrong_type", entry=1)


def test_a_self_rejection_is_refused(conn):
    causes = _type_id(conn, "causes")
    with pytest.raises(sqlite3.IntegrityError):
        _reject(conn, 1, 1, causes, "not_related")


# --------------------------------------------------------------------------
# Symmetry, agreeing with m026
# --------------------------------------------------------------------------

def test_a_symmetric_rejection_must_be_canonical(conn):
    """Otherwise rejecting "A confused with B" leaves "B confused with A" live.

    m026 stores symmetric relations as (min id, max id) and enforces it with
    the same pair of triggers. A rejection table that did not would ask the
    student the same question again from the other end.
    """
    confused = _type_id(conn, "confused with")
    with pytest.raises(sqlite3.IntegrityError) as exc:
        _reject(conn, 3, 1, confused, "not_related")
    assert "canonical" in str(exc.value)


def test_an_asymmetric_rejection_may_be_either_way_round(conn):
    """The control. Direction is meaningful for an asymmetric type.

    A trigger that fired on every reversed pair would quietly forbid rejecting
    "B causes A" after rejecting "A causes B", which are different claims.
    """
    causes = _type_id(conn, "causes")
    _reject(conn, 1, 2, causes, "not_related")
    _reject(conn, 2, 1, causes, "not_related")
    assert conn.execute(
        "SELECT COUNT(*) FROM subject_relation_rejections").fetchone()[0] == 2


def test_an_untyped_rejection_is_allowed_and_not_canonicalised(conn):
    """m026 leaves existing relations untyped; a proposal may be untyped too.

    The trigger's predicate starts with `relation_type_id IS NOT NULL`, so an
    untyped rejection cannot consult `is_symmetric` for a type that is not
    there.
    """
    _reject(conn, 3, 1, None, "not_related")
    assert conn.execute(
        "SELECT COUNT(*) FROM subject_relation_rejections").fetchone()[0] == 1


# --------------------------------------------------------------------------
# Deletion behaviour
# --------------------------------------------------------------------------

def test_a_soft_deleted_subject_keeps_its_rejections(conn):
    """Subject deletion is soft (#15), so the FK never fires -- by design.

    The student's judgement about a subject did not stop being true while it
    was archived, and #37 can restore it.
    """
    causes = _type_id(conn, "causes")
    _reject(conn, 1, 2, causes, "not_related")
    conn.execute("UPDATE subject_nodes SET status = 'archived' WHERE id = 1")
    assert conn.execute(
        "SELECT COUNT(*) FROM subject_relation_rejections").fetchone()[0] == 1


def test_deleting_the_entry_takes_its_misread_rows(conn):
    causes = _type_id(conn, "causes")
    _reject(conn, 1, 2, causes, "misread", entry=1)
    _reject(conn, 1, 3, causes, "not_related", entry=None)
    conn.execute("DELETE FROM question_entries WHERE id = 1")
    rows = conn.execute(
        "SELECT kind FROM subject_relation_rejections").fetchall()
    assert [r["kind"] for r in rows] == ["not_related"]


def test_registry_has_v27_and_keeps_the_gaps():
    """The snapshot claim, inherited from m026's test exactly as it instructed.

    `max(versions)` is held by whichever migration is newest, by exactly one
    file at a time. It is the one assertion in the suite that notices a
    migration arriving with nothing else updated -- a new module registered but
    no test, or a test with no module.

    **Moved to m028's test** (``test_user_028_relation_confidence_threshold``)
    when m028 arrived, as this docstring instructed; this test keeps the rest.
    """
    from database.migrations.user import MIGRATIONS

    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert 27 in versions
    for skipped in (8, 11, 12, 13, 14):
        assert skipped not in versions, (
            "m008 is reserved for the assessments branch and m011-m014 were "
            "stamped into real databases by earlier AI-capture builds (#145)")
    assert {m.version: m.name for m in MIGRATIONS}[27] == "relation_rejections"


def test_upgrade_is_idempotent(conn):
    m027_relation_rejections.upgrade(conn)
    m027_relation_rejections.upgrade(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
        "AND name = 'subject_relation_rejections'").fetchone()[0] == 1
