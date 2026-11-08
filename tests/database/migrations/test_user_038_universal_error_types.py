"""m038: one library of error types, and a list per exam (#888).

The profile is built as v37 code left it: the registry is cut at 37 while it is
created, exams, sessions and entries go through the real API, and the error
types are written per exam the way ``seed_default_tags`` wrote them before
#888. Raw SQL is used for those rows on purpose, so this fixture keeps
describing a v37 profile after Wave 1 changes ``tags.py``.
"""
from __future__ import annotations

import inspect
import logging
import sqlite3
import tempfile
from pathlib import Path

import pytest

import database.migrations.user as user_migrations
from database import MasterDatabase, UserDatabase
from database.domains.tags import _DEFAULT_TAG_DEFINITIONS
from database.migration_runner import MigrationFailedError, MigrationRunner
from database.migrations.user import MIGRATIONS, m038_universal_error_types
from database.schema_fingerprint import compare, fingerprint

GROUPS = {
    "Knowledge Issues": ("#EF4444", ["Knowledge Gap", "Memory Failure", "Misunderstanding"]),
    "Reading & Interpretation": ("#F59E0B", ["Misread Question"]),
    "Execution Errors": ("#10B981", ["Calculation Error", "Careless Mistake",
                                     "Incomplete Solution", "Wrong Approach"]),
    "Test Strategy": ("#3B82F6", ["Time Pressure", "Second-Guessing", "Elimination Error",
                                  "Poor Prioritization", "Wrong Guess Strategy"]),
    "Mental & Physical State": ("#8B5CF6", ["Anxiety Related", "Focus Problem",
                                            "Fatigue Related"]),
}
A, B, C = "Step 1", "Step 2 CK", "Shelf"


def _seed_v37(conn, exam_name: str) -> dict:
    """``seed_default_tags`` as it was before #888: a copy per exam."""
    ids = {}
    for order, (group, (colour, names)) in enumerate(GROUPS.items()):
        gid = conn.execute(
            "INSERT INTO tags (exam_context, tag_name, tag_category, color_hex,"
            " description, is_group, display_order) VALUES (?, ?, 'mistake_type', ?, ?, 1, ?)",
            (exam_name, group, colour, _DEFAULT_TAG_DEFINITIONS.get(group), order)).lastrowid
        ids[group] = gid
        for i, name in enumerate(names):
            ids[name] = conn.execute(
                "INSERT INTO tags (exam_context, tag_name, tag_category, color_hex,"
                " description, parent_id, display_order) VALUES (?, ?, 'mistake_type', ?, ?, ?, ?)",
                (exam_name, name, colour, _DEFAULT_TAG_DEFINITIONS.get(name), gid, i)).lastrowid
    return ids


def _custom(conn, exam_name, group_id, name) -> int:
    return conn.execute(
        "INSERT INTO tags (exam_context, tag_name, parent_id, description)"
        " VALUES (?, ?, ?, 'mine')", (exam_name, name, group_id)).lastrowid


def _tag(conn, entry_id, tag_id):
    conn.execute("INSERT INTO entry_tags (question_entry_id, tag_id) VALUES (?, ?)",
                 (entry_id, tag_id))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(user_migrations, "MIGRATIONS",
                        [m for m in MIGRATIONS if m.version < 38])
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="types_user", display_name="T",
                                  user_types=["student"])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username=user.username)
        monkeypatch.setattr(user_migrations, "MIGRATIONS", MIGRATIONS)
        yield master, user, db
        db.close()
        master.close()


@pytest.fixture
def profile(env):
    """Three exams: two seeded, one never seeded (its entries borrow types)."""
    _, _, db = env
    c = db.conn
    exams = {n: db.create_exam_context(exam_name=n) for n in (A, B, C)}
    a, b = _seed_v37(c, A), _seed_v37(c, B)
    # On B, the HIGHER id, so a lowest-id rule cannot pass the test by accident.
    c.execute("UPDATE tags SET description = 'my own reading' WHERE id = ?", (b["Knowledge Gap"],))
    c.execute("UPDATE tags SET description = 'tired, A' WHERE id = ?", (a["Fatigue Related"],))
    c.execute("UPDATE tags SET description = 'tired, B' WHERE id = ?", (b["Fatigue Related"],))
    a_only = _custom(c, A, a["Test Strategy"], "Rushed the stem")
    b_only = _custom(c, B, b["Test Strategy"], "Guessed on images")

    def entry(exam):
        s = db.create_review_session(exam_context_id=exams[exam].id,
                                     total_questions=1, total_incorrect=1)
        return db.create_question_entry(s.id, "a", "b").id

    e = {"a": entry(A), "b": entry(B), "c": entry(C), "x": entry(A), "f": entry(B)}
    _tag(c, e["a"], a["Knowledge Gap"])
    _tag(c, e["b"], b["Knowledge Gap"]); _tag(c, e["b"], b_only)
    _tag(c, e["c"], a["Misread Question"]); _tag(c, e["c"], b["Misread Question"])
    _tag(c, e["x"], b["Time Pressure"])
    _tag(c, e["f"], b["Fatigue Related"]); _tag(c, e["a"], b["Fatigue Related"])
    qa = c.execute("INSERT INTO question_analyses (exam_context, question_source,"
                   " question_source_id, answered_incorrectly_date)"
                   " VALUES (?, 'bank', 'q1', '2026-11-01')", (B,)).lastrowid
    c.execute("INSERT INTO question_tags (question_analysis_id, tag_id, exam_context)"
              " VALUES (?, ?, ?)", (qa, b["Memory Failure"], B))
    c.commit()
    return db, {k: v.id for k, v in exams.items()}, e, a, b, a_only, b_only


def _migrate(db):
    MigrationRunner(db.conn, registry=MIGRATIONS, scope="user").apply_pending()


def _names_on(db, entry_id) -> list:
    return sorted(r[0] for r in db.conn.execute(
        "SELECT t.tag_name FROM entry_tags et JOIN tags t ON t.id = et.tag_id"
        " WHERE et.question_entry_id = ?", (entry_id,)))


def _listed(db, exam_id) -> set:
    return {r[0] for r in db.conn.execute(
        "SELECT t.tag_name FROM exam_error_types l JOIN tags t ON t.id = l.tag_id"
        " WHERE l.exam_context_id = ?", (exam_id,))}


def _everything(db) -> dict:
    out = {}
    for (t,) in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'"
                                " AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        out[t] = sorted(tuple(r) for r in db.conn.execute(f"SELECT * FROM {t}"))
    return out


# --------------------------------------------------------------- registry


def test_registry_has_v38_and_keeps_the_gaps():
    """The registry snapshot, moved here from m037's test as it instructs.

    **A new migration will make this fail, and the fix is to MOVE these lines
    into its test, not to loosen them.** Carried m023 -> ... -> m037 -> here.
    m038 was reserved for #888 on that issue before it was written.
    """
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions)
    assert versions[versions.index(38) - 1] == 37
    for skipped in (8, 11, 12, 13, 14, 29):
        assert skipped not in versions
    assert {m.version: m.name for m in MIGRATIONS}[38] == "universal_error_types"
    assert max(versions) == 38


def test_the_defaults_match_tags_py():
    """m038 carries its own copy (the runner checksums ``upgrade`` alone)."""
    source = inspect.getsource(m038_universal_error_types.upgrade)
    block = source.split("defaults = {", 1)[1].split("\n    }", 1)[0]
    copied = eval("{" + block + "}")  # noqa: S307 - our own source
    assert copied == _DEFAULT_TAG_DEFINITIONS


def test_nothing_lives_outside_upgrade():
    module = inspect.getsource(m038_universal_error_types)
    assert "from database" not in module and "from .." not in module
    head = module.split("def upgrade(")[0].split('"""', 2)[2]
    assert "SELECT" not in head and "INSERT" not in head


# --------------------------------------------------------------- the merge


def test_the_premise_is_a_per_exam_profile(profile):
    db = profile[0]
    assert db.fetchone("SELECT COUNT(*) n FROM tags")["n"] == 2 * 21 + 2
    assert "exam_error_types" not in {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master")}


def test_copies_merge_into_one_library(profile):
    db = profile[0]
    _migrate(db)
    assert db.fetchone("SELECT COUNT(*) n FROM tags")["n"] == 21 + 2
    assert db.fetchone("SELECT COUNT(*) n FROM tags WHERE exam_context IS NOT NULL")["n"] == 0
    assert db.fetchone("SELECT COUNT(*) n FROM (SELECT tag_name FROM tags"
                       " GROUP BY IFNULL(parent_id,0), tag_name HAVING COUNT(*) > 1)")["n"] == 0
    assert list(db.conn.execute("PRAGMA foreign_key_check")) == []


def test_every_entry_keeps_every_type_it_had(profile):
    db, _, e, *_ = profile
    before = {k: sorted(set(_names_on(db, v))) for k, v in e.items()}
    _migrate(db)
    assert {k: _names_on(db, v) for k, v in e.items()} == before
    assert _names_on(db, e["c"]) == ["Misread Question"], "two copies collapse to one"


def test_an_edited_definition_beats_the_default(profile):
    db = profile[0]
    _migrate(db)
    assert db.fetchone("SELECT description FROM tags WHERE tag_name = 'Knowledge Gap'"
                       )["description"] == "my own reading"


def test_between_two_edits_the_more_used_wins_and_the_other_is_logged(profile, caplog):
    db = profile[0]
    with caplog.at_level(logging.WARNING, logger="database.migrations.user.m038"):
        _migrate(db)
    assert db.fetchone("SELECT description FROM tags WHERE tag_name = 'Fatigue Related'"
                       )["description"] == "tired, B"
    assert "tired, A" in caplog.text


def test_the_legacy_question_tags_follow(profile):
    db = profile[0]
    _migrate(db)
    row = db.fetchone("SELECT t.tag_name FROM question_tags qt JOIN tags t ON t.id = qt.tag_id")
    assert row["tag_name"] == "Memory Failure"


# --------------------------------------------------------------- the lists


def test_each_exam_lists_what_it_had(profile):
    db, exams, *_ = profile
    _migrate(db)
    defaults = set(GROUPS) | {n for _, names in GROUPS.values() for n in names}
    assert _listed(db, exams[A]) == defaults | {"Rushed the stem"}
    assert _listed(db, exams[B]) == defaults | {"Guessed on images"}


def test_a_custom_type_stays_on_its_own_exam(profile):
    """Decision 4: some exams have types others do not."""
    db, exams, *_ = profile
    _migrate(db)
    assert "Guessed on images" not in _listed(db, exams[A])
    assert "Rushed the stem" not in _listed(db, exams[B])


def test_an_exam_lists_the_types_its_entries_carry_with_their_group(profile):
    """Exam C was never seeded; its entry carries Misread Question."""
    db, exams, *_ = profile
    _migrate(db)
    assert _listed(db, exams[C]) == {"Misread Question", "Reading & Interpretation"}


def _seeded(db) -> set:
    return {r[0] for r in db.conn.execute(
        "SELECT exam_context_id FROM exam_error_types_seeded")}


def test_every_exam_given_a_list_is_marked_as_having_had_one(profile):
    """#895 review: seed_default_tags reads this, not whether the list is empty."""
    db, exams, *_ = profile
    _migrate(db)
    assert _seeded(db) == set(exams.values())


def test_an_exam_with_nothing_is_left_unmarked_and_offered_the_defaults(profile):
    db, exams, *_ = profile
    empty = db.create_exam_context(exam_name="Nothing filed").id
    db.conn.commit()
    _migrate(db)
    assert empty not in _seeded(db)
    db.seed_default_tags("Nothing filed")
    assert _listed(db, empty) == set(_DEFAULT_TAG_DEFINITIONS)
    assert empty in _seeded(db)


def test_a_permanent_delete_removes_the_list_and_never_a_type(profile):
    """#887 at the schema level: the list cascades, the library does not."""
    db, exams, e, *_ = profile
    _migrate(db)
    before = db.fetchone("SELECT COUNT(*) n FROM tags")["n"]
    db.execute("DELETE FROM exam_contexts WHERE id = ?", (exams[A],))
    db.conn.commit()
    assert db.fetchone("SELECT COUNT(*) n FROM tags")["n"] == before
    assert db.fetchone("SELECT COUNT(*) n FROM exam_error_types WHERE exam_context_id = ?",
                       (exams[A],))["n"] == 0
    assert exams[A] not in _seeded(db), "the mark goes with the exam"
    assert _names_on(db, e["b"]) == ["Guessed on images", "Knowledge Gap"]


# --------------------------------------------------------------- the table


def test_the_new_key_refuses_a_duplicate_in_one_group_only(profile):
    db = profile[0]
    _migrate(db)
    group = db.fetchone("SELECT id FROM tags WHERE tag_name = 'Test Strategy'")["id"]
    other = db.fetchone("SELECT id FROM tags WHERE tag_name = 'Knowledge Issues'")["id"]
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("INSERT INTO tags (tag_name, parent_id) VALUES ('Time Pressure', ?)", (group,))
    db.conn.execute("INSERT INTO tags (tag_name, parent_id) VALUES ('Time Pressure', ?)", (other,))


def test_ids_and_sequences_survive(profile):
    db, _, e, a, b, *_ = profile
    kept = b["Knowledge Gap"]   # B's edited copy is the survivor
    et_ids = {r[0] for r in db.conn.execute("SELECT id FROM entry_tags WHERE tag_id = ?", (kept,))}
    seq = dict(db.conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
    _migrate(db)
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (kept,))
    assert et_ids <= {r[0] for r in db.conn.execute("SELECT id FROM entry_tags")}
    after = dict(db.conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
    for name in ("tags", "entry_tags", "question_tags"):
        assert after[name] >= seq[name], name


def test_an_upgraded_profile_matches_a_fresh_one(profile, tmp_path):
    """What #593's preflight compares on import."""
    db = profile[0]
    _migrate(db)
    fresh = sqlite3.connect(tmp_path / "fresh.db")
    fresh.execute("PRAGMA foreign_keys = ON")
    MigrationRunner(fresh, registry=MIGRATIONS, scope="user").apply_pending()
    assert compare(fingerprint(fresh), fingerprint(db.conn)) == []
    fresh.close()


def test_a_second_run_changes_nothing(profile):
    db = profile[0]
    _migrate(db)
    once = _everything(db)
    m038_universal_error_types.upgrade(db.conn)
    db.conn.commit()
    assert _everything(db) == once


# --------------------------------------------------------------- atomicity


class _FailingOn:
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
    "RENAME TO tags",                  # children dropped, tags half rebuilt
    "INSERT INTO entry_tags SELECT",   # entry_tags recreated but empty
    "CREATE TABLE exam_error_types",   # everything but the lists
    "INSERT INTO exam_error_types_seeded",  # the very last write
])
def test_a_failed_upgrade_leaves_the_profile_as_it_was(profile, needle):
    db = profile[0]
    before = _everything(db)
    failing = _FailingOn(db.conn, needle)
    with pytest.raises(MigrationFailedError):
        MigrationRunner(failing, registry=MIGRATIONS, scope="user").apply_pending()
    assert failing.tripped
    assert not db.conn.in_transaction
    assert _everything(db) == before
    _migrate(db)
    assert db.fetchone("SELECT COUNT(*) n FROM tags")["n"] == 23


# --------------------------------------------------------------- the import


def test_an_imported_v37_profile_arrives_merged(env, profile, tmp_path):
    from app.profile_archive import build_profile_archive, install_profile_as_new

    master, user, db = env
    entries = profile[2]
    names = {k: sorted(set(_names_on(db, v))) for k, v in entries.items()}
    db.close()
    archive = tmp_path / "v37.wimi"
    build_profile_archive(master, user.id, archive, include_media=False)
    master.create_user(username="occupant", display_name="Here", user_types=["student"])
    result = install_profile_as_new(master, archive)
    new = master.get_user(result["user_id"])
    got = UserDatabase(db_path=master.users_dir / new.database_filename,
                       user_id=new.id, username=new.username)
    try:
        assert got.fetchone("SELECT COUNT(*) n FROM tags")["n"] == 23
        assert {k: _names_on(got, v) for k, v in entries.items()} == names
        assert 38 in {r[0] for r in got.conn.execute("SELECT version FROM schema_migrations")}
    finally:
        got.close()
