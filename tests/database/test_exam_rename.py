"""#718: editing an exam can rename it and can clear its date.

Before #718, ``update_exam_context_settings`` had no name parameter, so no
layer could rename an exam: the wizard's Exam Name field was editable,
validated and then left out of the save. A cleared date never cleared either,
because the bridge turned ``''`` into ``None`` and the domain reads ``None``
as "not supplied".

A rename is more than one column. Seven tables name their exam by TEXT in an
``exam_context`` column, with no foreign key, so a rename that moved
``exam_contexts.exam_name`` alone would leave the subject tree, aliases and
tags under a name no exam holds. The exam would open empty, and the next exam
created with the old name would inherit them.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.domains.exam_contexts import EXAM_NAME_KEYED_TABLES
from database.exceptions import ValidationError


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="rename_user",
                                  display_name="Rename User",
                                  user_types=["student"])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username=user.username)
        yield db
        db.close()
        master.close()


def _fill_every_keyed_table(db, exam_name: str) -> dict[str, int]:
    """One row under ``exam_name`` in each name-keyed table; return counts."""
    node = db.create_subject_node(exam_context=exam_name, name="Cardiology",
                                  level_type="System")
    db.execute("INSERT INTO subject_aliases (subject_node_id, exam_context,"
               " alias_name) VALUES (?, ?, 'Cardio')", (node.id, exam_name))
    # A library error type (#888: tags are not filed under an exam), there
    # only so the legacy question_tags row has something to name.
    tag = db.execute("INSERT INTO tags (tag_name) VALUES ('hard')").lastrowid
    qa = db.execute(
        "INSERT INTO question_analyses (exam_context, question_source,"
        " question_source_id, answered_incorrectly_date)"
        " VALUES (?, 'bank', 'q1', '2026-11-01')", (exam_name,)).lastrowid
    db.execute("INSERT INTO question_tags (question_analysis_id, tag_id,"
               " exam_context) VALUES (?, ?, ?)", (qa, tag, exam_name))
    db.execute("INSERT INTO question_topic_assignments (question_analysis_id,"
               " subject_node_id, exam_context) VALUES (?, ?, ?)",
               (qa, node.id, exam_name))
    db.execute("INSERT INTO question_sources (user_id, source_name, exam_context)"
               " VALUES (?, 'bank', ?)", (db.user_id, exam_name))
    db.conn.commit()
    return _counts(db, exam_name)


def _counts(db, exam_name: str) -> dict[str, int]:
    return {t: db.fetchone(f"SELECT COUNT(*) AS n FROM {t} WHERE exam_context = ?",
                           (exam_name,))["n"]
            for t in EXAM_NAME_KEYED_TABLES}


# ---------------------------------------------------------------- the rename

def test_a_rename_moves_every_row_filed_under_the_old_name(user_db):
    exam = user_db.create_exam_context(exam_name="Step 1")
    before = _fill_every_keyed_table(user_db, "Step 1")
    assert all(n == 1 for n in before.values()), before

    updated = user_db.update_exam_context_settings(exam.id, exam_name="USMLE Step 1")

    assert updated.exam_name == "USMLE Step 1"
    assert _counts(user_db, "USMLE Step 1") == before, (
        "every name-keyed row must follow the exam to its new name")
    assert set(_counts(user_db, "Step 1").values()) == {0}, (
        "nothing may stay filed under the old name")
    assert [n.name for n in user_db.get_subject_hierarchy("USMLE Step 1")] \
        == ["Cardiology"], "the renamed exam must still open on its tree"


def test_every_exam_context_column_is_in_the_rename_list(user_db):
    """The list is hand-written, so this reads the schema it must cover.

    A table that gains an ``exam_context`` column without joining
    ``EXAM_NAME_KEYED_TABLES`` would be left behind by every rename, and
    nothing else would notice.
    """
    found = set()
    for (table,) in user_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"):
        cols = {r[1] for r in user_db.conn.execute(f"PRAGMA table_info('{table}')")}
        if "exam_context" in cols:
            found.add(table)
    assert found - set(NOT_NAME_KEYED) == set(EXAM_NAME_KEYED_TABLES)
    # An exemption that no longer names a real column has outlived its reason.
    assert set(NOT_NAME_KEYED) <= found, set(NOT_NAME_KEYED) - found


# Tables that carry an ``exam_context`` column which names no exam, each with
# the reason it is not in EXAM_NAME_KEYED_TABLES.
NOT_NAME_KEYED = {
    # Always NULL since m038 (#888): error types are one library per profile,
    # and an exam's types are its exam_error_types rows, keyed by
    # exam_contexts.id. Listing it would make a permanent delete take types
    # off other exams' entries again (#887).
    "tags": "tags.exam_context is always NULL since m038 (#888)",
}


def test_the_name_is_stripped_and_an_unchanged_name_writes_nothing(user_db):
    exam = user_db.create_exam_context(exam_name="MCAT")
    stamp = user_db.fetchone("SELECT updated_at FROM exam_contexts WHERE id = ?",
                             (exam.id,))["updated_at"]
    assert user_db.update_exam_context_settings(exam.id, exam_name="  MCAT ").exam_name == "MCAT"
    assert user_db.fetchone("SELECT updated_at FROM exam_contexts WHERE id = ?",
                            (exam.id,))["updated_at"] == stamp
    assert user_db.update_exam_context_settings(exam.id, exam_name=" GRE ").exam_name == "GRE"


def test_an_empty_name_is_refused(user_db):
    exam = user_db.create_exam_context(exam_name="MCAT")
    with pytest.raises(ValidationError, match="needs a name"):
        user_db.update_exam_context_settings(exam.id, exam_name="   ")
    assert user_db.get_exam_context_config(exam.id).exam_name == "MCAT"


@pytest.mark.parametrize("suspended", [False, True], ids=["active", "suspended"])
def test_a_name_another_exam_holds_is_refused_with_a_sentence(user_db, suspended):
    user_db.create_exam_context(exam_name="Step 2 CK")
    other = user_db.get_exam_context_by_name("Step 2 CK")
    if suspended:
        user_db.update_exam_context_settings(other.id, is_active=False)
    exam = user_db.create_exam_context(exam_name="Step 1")
    _fill_every_keyed_table(user_db, "Step 1")

    with pytest.raises(ValidationError, match='already called "Step 2 CK"') as err:
        user_db.update_exam_context_settings(
            exam.id, exam_name="Step 2 CK", exam_description="moved")
    assert ("suspended" in str(err.value)) == suspended

    # One transaction: the description in the same call is not saved either.
    kept = user_db.get_exam_context_config(exam.id)
    assert kept.exam_name == "Step 1"
    assert kept.exam_description != "moved"
    assert set(_counts(user_db, "Step 1").values()) == {1}


def test_a_name_a_deleted_exam_left_rows_under_is_refused(user_db):
    """Rows filed under a name no exam holds are refused, not adopted.

    Until #873 a hard delete left exactly this behind (no foreign key), so
    databases from before it can still carry such rows. The delete no longer
    makes them (``test_exam_hard_delete.py``), so this builds them directly:
    an exam row removed with its name-keyed rows left in place.
    """
    gone = user_db.create_exam_context(exam_name="Old Shelf")
    _fill_every_keyed_table(user_db, "Old Shelf")
    user_db.execute("DELETE FROM exam_contexts WHERE id = ?", (gone.id,))
    user_db.conn.commit()
    assert user_db.fetchone("SELECT COUNT(*) AS n FROM subject_nodes"
                            " WHERE exam_context = 'Old Shelf'")["n"] == 1, (
        "premise: rows are still filed under a name no exam holds")

    exam = user_db.create_exam_context(exam_name="Surgery")
    with pytest.raises(ValidationError, match="permanently deleted"):
        user_db.update_exam_context_settings(exam.id, exam_name="Old Shelf")
    assert user_db.get_exam_context_config(exam.id).exam_name == "Surgery"


# ---------------------------------------------------------------- the date

def test_a_date_can_be_cleared(user_db):
    exam = user_db.create_exam_context(exam_name="SAT")
    user_db.update_exam_context_settings(exam.id, exam_date=date(2026, 12, 15))
    assert user_db.get_exam_context_config(exam.id).exam_date is not None

    cleared = user_db.update_exam_context_settings(exam.id, clear_exam_date=True)
    assert cleared.exam_date is None


def test_an_omitted_date_is_still_left_alone(user_db):
    exam = user_db.create_exam_context(exam_name="SAT")
    user_db.update_exam_context_settings(exam.id, exam_date=date(2026, 12, 15))
    after = user_db.update_exam_context_settings(exam.id, exam_description="x")
    assert str(after.exam_date) == "2026-12-15"


def test_setting_and_clearing_a_date_at_once_is_refused(user_db):
    exam = user_db.create_exam_context(exam_name="SAT")
    with pytest.raises(ValidationError):
        user_db.update_exam_context_settings(
            exam.id, exam_date=date(2026, 12, 15), clear_exam_date=True)
