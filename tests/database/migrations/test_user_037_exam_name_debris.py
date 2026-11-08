"""m037 removes what pre-#880 permanent deletes left behind (#884, option A).

A "pre-#880 profile" is built the honest way: a real exam with a row in every
table that hangs off its subjects (``test_exam_hard_delete._build_exam``), then
the delete exactly as it was before #880 -- the ``exam_contexts`` row goes and
``ON DELETE CASCADE`` does the rest -- then v37 is unstamped so the runner
applies m037 as an import into this release would.

Every test that asserts something is gone has a control exam beside it that
must come through byte for byte, so a migration that emptied the tables would
not pass.
"""
from __future__ import annotations

import inspect
import sqlite3
import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.domains.exam_contexts import EXAM_NAME_KEYED_TABLES
from database.migration_runner import MigrationFailedError, MigrationRunner
from database.migrations.user import MIGRATIONS, m037_exam_name_debris
from database.schema_fingerprint import fingerprint
from tests.database.test_exam_hard_delete import (
    DOOMED, KEPT, _build_exam, _filed_under, _rows_naming)


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="debris_user",
                                  display_name="Debris User",
                                  user_types=["student"])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username=user.username)
        yield master, user, db
        db.close()
        master.close()


@pytest.fixture
def db(env):
    return env[2]


def _old_delete(db, exam_id: int) -> None:
    """``hard_delete_exam_context`` before #880: the row, and the cascade."""
    db.execute("DELETE FROM exam_contexts WHERE id = ?", (exam_id,))
    db.conn.commit()


def _unstamp_v37(db) -> None:
    db.execute("DELETE FROM schema_migrations WHERE version = 37")
    db.conn.commit()


def _migrate(db) -> None:
    MigrationRunner(db.conn, registry=MIGRATIONS, scope="user").apply_pending()


def _debris_profile(db):
    """A doomed exam deleted the old way, and a control exam beside it.

    m037 runs before m038, so on a real profile its tags are still filed under
    exam names. Since #888 ``create_tag`` files nothing (``exam_context`` is
    NULL), so the doomed exam's tag is filed by hand: that is the shape m037
    meets, and without it its tag rules would pass on nothing.
    """
    doomed = _build_exam(db, DOOMED)
    kept = _build_exam(db, KEPT)
    db.execute("UPDATE tags SET exam_context = ? WHERE id = ?",
               (DOOMED, doomed["tag"]))
    _old_delete(db, doomed["exam"].id)
    _unstamp_v37(db)
    return doomed, kept


def _snapshot(db, built) -> tuple:
    return (_filed_under(db, KEPT), _rows_naming(db, built["subjects"]),
            db.fetchone("SELECT COUNT(*) AS n FROM dimension_delete_batches"
                        " WHERE exam_id = ?", (built["exam"].id,))["n"],
            [tuple(r) for r in db.conn.execute(
                "SELECT * FROM subject_nodes WHERE exam_context = ? ORDER BY id",
                (KEPT,))])


def _everything(db) -> dict:
    out = {}
    for (t,) in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'"
                                " AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        out[t] = sorted(tuple(r) for r in db.conn.execute(f"SELECT * FROM {t}"))
    return out


# --------------------------------------------------------------- registry


# The registry snapshot moved to test_user_038_universal_error_types.py when
# m038 landed (#888), as its docstring instructed.


def test_the_tables_match_exam_name_keyed_tables():
    """m037 carries its own list rather than importing it (module docstring:
    the runner checksums ``upgrade`` alone). This is what keeps the two equal."""
    source = inspect.getsource(m037_exam_name_debris.upgrade)
    for table in EXAM_NAME_KEYED_TABLES:
        assert f'"{table}"' in source.split("keyed = (")[1].split(")")[0], table


def test_every_statement_lives_inside_upgrade():
    """Nothing the checksum cannot see: no module-level SQL, no imports from
    the app. A helper shared with the hard delete would change this migration's
    behaviour, unchecksummed, whenever the hard delete changed."""
    module = inspect.getsource(m037_exam_name_debris)
    head = module.split("def upgrade(")[0]
    assert "DELETE" not in head.split('"""', 2)[2]
    assert "from .." not in module and "from database" not in module


# --------------------------------------------------------------- the clean


def test_the_premise_a_pre_880_profile_carries_debris(db):
    doomed, _ = _debris_profile(db)
    filed = _filed_under(db, DOOMED)
    assert all(n >= 1 for n in filed.values()), filed
    assert _rows_naming(db, doomed["subjects"]).get("subject_nodes.id")
    assert db.fetchone("SELECT COUNT(*) AS n FROM dimension_delete_batches"
                       " WHERE exam_id = ?", (doomed["exam"].id,))["n"] == 1


def test_m037_removes_the_debris_and_nothing_else(db):
    doomed, kept = _debris_profile(db)
    control = _snapshot(db, kept)

    _migrate(db)

    assert set(_filed_under(db, DOOMED).values()) == {0}, _filed_under(db, DOOMED)
    assert _rows_naming(db, doomed["subjects"]) == {}
    assert db.fetchone("SELECT COUNT(*) AS n FROM dimension_delete_batches"
                       " WHERE exam_id = ?", (doomed["exam"].id,))["n"] == 0
    assert _snapshot(db, kept) == control
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (doomed["tag"],)) is None, (
        "a debris tag no live entry carries is removed (rule 1)")
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (kept["tag"],)), (
        "a library tag (exam_context NULL, #888) is never debris")
    assert db.get_entry_note(doomed["free_note"]) is not None, (
        "#848: a free note is the student's own writing")
    assert list(db.conn.execute("PRAGMA foreign_key_check")) == []
    assert 37 in {r[0] for r in db.conn.execute("SELECT version FROM schema_migrations")}


def test_the_next_exam_of_that_name_starts_empty(db):
    _debris_profile(db)
    _migrate(db)
    db.create_exam_context(exam_name=DOOMED)
    assert db.get_subject_hierarchy(DOOMED) == []


def test_an_adopted_tree_is_left_alone(db):
    """The one way this could delete something real: a student who already
    created a new exam under the old name is using that tree."""
    doomed, _ = _debris_profile(db)
    db.create_exam_context(exam_name=DOOMED)
    db.conn.commit()
    adopted = _filed_under(db, DOOMED)
    rows = _rows_naming(db, doomed["subjects"])

    _migrate(db)

    assert _filed_under(db, DOOMED) == adopted
    assert _rows_naming(db, doomed["subjects"]) == rows


def test_a_fresh_profile_is_unchanged(db):
    _build_exam(db, KEPT)
    _unstamp_v37(db)
    before = _everything(db)
    _migrate(db)
    after = _everything(db)
    before.pop("schema_migrations"), after.pop("schema_migrations")
    assert after == before


def test_a_second_run_changes_nothing(db):
    _debris_profile(db)
    _migrate(db)
    once = _everything(db)
    m037_exam_name_debris.upgrade(db.conn)
    db.conn.commit()
    assert _everything(db) == once


def test_the_schema_fingerprint_is_unchanged(db):
    _debris_profile(db)
    before = fingerprint(db.conn)
    _migrate(db)
    assert fingerprint(db.conn) == before
    assert not list(db.conn.execute(
        "SELECT name FROM sqlite_temp_master WHERE name LIKE 'm037_%'"))


# --------------------------------------------------------------- rule 1


def test_a_debris_subject_a_live_entry_uses_is_kept_with_its_ancestors(db):
    """Cannot happen through the app; a profile can carry anything. The
    mapping is ON DELETE CASCADE, so deleting the subject would untag it."""
    doomed, kept = _debris_profile(db)
    root, leaf = doomed["subjects"][0], doomed["subjects"][1]
    session = db.fetchone("SELECT id FROM review_sessions WHERE exam_context_id = ?",
                          (kept["exam"].id,))["id"]
    entry = db.create_question_entry(session, "a", "b", primary_subject_ids=[leaf])
    db.conn.commit()

    _migrate(db)

    present = {r["id"] for r in db.conn.execute("SELECT id FROM subject_nodes")}
    assert {root, leaf} <= present, "the entry's subject or its parent went"
    assert doomed["subjects"][3] not in present, "the unused debris stayed"
    assert db.fetchone("SELECT COUNT(*) AS n FROM entry_subject_mappings"
                       " WHERE question_entry_id = ? AND subject_node_id = ?",
                       (entry.id, leaf))["n"] == 1


def test_a_debris_tag_a_live_entry_carries_is_kept(db):
    doomed, kept = _debris_profile(db)
    entry = kept["entry"]
    db.execute("INSERT INTO entry_tags (question_entry_id, tag_id) VALUES (?, ?)",
               (entry, doomed["tag"]))
    db.conn.commit()
    _migrate(db)
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (doomed["tag"],))
    assert db.fetchone("SELECT 1 FROM entry_tags WHERE question_entry_id = ? AND tag_id = ?",
                       (entry, doomed["tag"]))


def test_a_debris_tag_group_with_a_living_child_does_not_refuse_the_import(db):
    """tags.parent_id is NO ACTION: deleting the parent would fail the
    migration and with it the import."""
    doomed, _ = _debris_profile(db)
    child = db.create_tag(exam_context=KEPT, tag_name="child of debris")
    db.execute("UPDATE tags SET parent_id = ? WHERE id = ?", (doomed["tag"], child.id))
    db.conn.commit()
    _migrate(db)
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (doomed["tag"],))
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (child.id,))


def test_a_living_subject_under_a_debris_parent_survives(db):
    """subject_nodes.parent_id is CASCADE: deleting the parent would take it."""
    doomed, _ = _debris_profile(db)
    child = db.create_subject_node(exam_context=KEPT, name="Orphan",
                                   level_type="Topic")
    db.execute("UPDATE subject_nodes SET parent_id = ? WHERE id = ?",
               (doomed["subjects"][0], child.id))
    db.conn.commit()
    _migrate(db)
    assert db.fetchone("SELECT 1 FROM subject_nodes WHERE id = ?", (child.id,))


# --------------------------------------------------------------- rule 2


def test_a_debris_source_still_in_use_is_unfiled_and_an_unused_one_deleted(db):
    doomed, kept = _debris_profile(db)
    unused = db.create_question_source("Unused bank", exam_context=DOOMED)
    db.create_review_session(exam_context_id=kept["exam"].id, total_questions=1,
                             total_incorrect=1, question_source_id=doomed["source"])
    db.conn.commit()

    _migrate(db)

    row = db.fetchone("SELECT exam_context FROM question_sources WHERE id = ?",
                      (doomed["source"],))
    assert row is not None and row["exam_context"] is None
    assert db.fetchone("SELECT 1 FROM question_sources WHERE id = ?",
                       (unused.id,)) is None


# --------------------------------------------------------------- atomicity


class _FailingOn:
    """A connection that raises on the first statement containing ``needle``."""

    def __init__(self, conn, needle):
        self._conn, self._needle, self.tripped = conn, needle, False

    def execute(self, sql, *args):
        if self._needle in sql:
            self.tripped = True
            raise sqlite3.OperationalError(f"injected failure at {self._needle!r}")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.mark.parametrize("needle", [
    "DELETE FROM tags",           # after the journals and question_* rows
    "UPDATE question_sources",    # after the subjects are gone
])
def test_a_failed_upgrade_leaves_the_profile_as_it_was(db, needle):
    _debris_profile(db)
    before = _everything(db)
    failing = _FailingOn(db.conn, needle)
    with pytest.raises(MigrationFailedError):
        MigrationRunner(failing, registry=MIGRATIONS, scope="user").apply_pending()
    assert failing.tripped, "the injected failure never fired"
    assert not db.conn.in_transaction
    assert _everything(db) == before
    _migrate(db)
    assert set(_filed_under(db, DOOMED).values()) == {0}


# --------------------------------------------------------------- the import


def test_an_imported_pre_880_profile_arrives_clean(env, tmp_path):
    """How a student meets this migration: export, then import."""
    from app.profile_archive import build_profile_archive, install_profile_as_new

    master, user, db = env
    _debris_profile(db)
    assert _filed_under(db, DOOMED)["subject_nodes"] > 0
    db.close()

    archive = tmp_path / "pre880.wimi"
    build_profile_archive(master, user.id, archive, include_media=False)
    master.create_user(username="occupant", display_name="Already Here")
    result = install_profile_as_new(master, archive)
    new = master.get_user(result["user_id"])
    got = UserDatabase(db_path=master.users_dir / new.database_filename,
                       user_id=new.id, username=new.username)
    try:
        assert set(_filed_under(got, DOOMED).values()) == {0}
        assert _filed_under(got, KEPT)["subject_nodes"] > 0
        assert 37 in {r[0] for r in got.conn.execute(
            "SELECT version FROM schema_migrations")}
    finally:
        got.close()
