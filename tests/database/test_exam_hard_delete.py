"""#873: "delete permanently" removes what is filed under the exam's name.

``hard_delete_exam_context`` deleted the ``exam_contexts`` row and relied on
``ON DELETE CASCADE`` for the rest. That reaches every table keyed by
``exam_contexts.id``. It never reached the seven tables that name their exam
by TEXT (``EXAM_NAME_KEYED_TABLES``, no foreign key), so the subject tree,
aliases and tags outlived the delete. Since the name was free again, the next
exam created with it opened on the deleted exam's tree. The dashboard's
confirmation says the delete "will remove all sessions, entries, and data".

The fixture builds one exam with something in every table that hangs off a
subject, and a second exam that must come through untouched. The second exam
is the control: without it, a delete that emptied every table would pass.

Error types are the exception, and the reverse of #873's rule (#887, #888).
Since m038 they are one library per profile and an exam only LISTS the ones
it offers (``exam_error_types``). #880's delete removed the types filed under
the exam's name, and ``entry_tags``' cascade took them off other exams'
entries too. Now the delete removes the exam's list by cascade and never a
type: the tests at the bottom are #887's reproduction, inverted.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.domains.exam_contexts import EXAM_NAME_KEYED_TABLES

DOOMED, KEPT = "Old Shelf", "Step 2 CK"


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="delete_user",
                                  display_name="Delete User",
                                  user_types=["student"])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username=user.username)
        yield db
        db.close()
        master.close()


def _build_exam(db, name: str) -> dict:
    """An exam with a row in every table that hangs off its subjects."""
    exam = db.create_exam_context(exam_name=name)
    root = db.create_subject_node(exam_context=name, name="Cardiology",
                                  level_type="System")
    leaf = db.create_subject_node(exam_context=name, name="Arrhythmia",
                                  level_type="Topic", parent_id=root.id)
    other = db.create_subject_node(exam_context=name, name="Pharmacology",
                                   level_type="System")
    db.add_edge(other.id, leaf.id)                      # a second parent
    gone = db.create_subject_node(exam_context=name, name="Archived topic",
                                  level_type="Topic", parent_id=root.id)
    db.delete_subject_subtree(gone.id)                  # m018 journal
    db.create_subject_relation(root.id, other.id, "drugs act on the heart")
    db.record_relation_rejection(leaf.id, other.id, kind="not_related")
    db.execute("INSERT INTO subject_aliases (subject_node_id, exam_context,"
               " alias_name) VALUES (?, ?, 'Cardio')", (root.id, name))
    tag = db.create_tag(exam_context=name, tag_name=f"hard-{name}")
    source = db.create_question_source(f"Bank for {name}", exam_context=name)
    session = db.create_review_session(exam_context_id=exam.id, total_questions=1,
                                       total_incorrect=1,
                                       question_source_id=source.id)
    entry = db.create_question_entry(session.id, "a", "b",
                                     primary_subject_ids=[leaf.id])
    dim = db.create_dimension(exam_id=exam.id, name="Discipline", display_order=1)
    db.archive_dimension(dim)                           # m024 journal
    free_note = db.add_free_note(content_html="<p>mine</p>",
                                 linked_subject_ids=[root.id])
    # The three legacy question_* tables are name-keyed too.
    qa = db.execute(
        "INSERT INTO question_analyses (exam_context, question_source,"
        " question_source_id, answered_incorrectly_date)"
        " VALUES (?, 'bank', 'q1', '2026-11-01')", (name,)).lastrowid
    db.execute("INSERT INTO question_tags (question_analysis_id, tag_id,"
               " exam_context) VALUES (?, ?, ?)", (qa, tag.id, name))
    db.execute("INSERT INTO question_topic_assignments (question_analysis_id,"
               " subject_node_id, exam_context) VALUES (?, ?, ?)",
               (qa, root.id, name))
    db.conn.commit()
    return {"exam": exam, "subjects": [root.id, leaf.id, other.id, gone.id],
            "tag": tag.id, "source": source.id, "entry": entry.id,
            "free_note": free_note.id}


def _filed_under(db, name: str) -> dict[str, int]:
    return {t: db.fetchone(f"SELECT COUNT(*) AS n FROM {t} WHERE exam_context = ?",
                           (name,))["n"] for t in EXAM_NAME_KEYED_TABLES}


def _rows_naming(db, subject_ids: list[int]) -> dict[str, int]:
    """Every row, in any table, that points at one of these subjects."""
    marks = ",".join("?" * len(subject_ids))
    found = {}
    for (table,) in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"):
        for fk in db.conn.execute(f"PRAGMA foreign_key_list('{table}')"):
            if fk[2] != "subject_nodes":
                continue
            n = db.fetchone(f"SELECT COUNT(*) AS n FROM {table}"
                            f" WHERE {fk[3]} IN ({marks})", tuple(subject_ids))["n"]
            if n:
                found[f"{table}.{fk[3]}"] = n
    for table, col in (("subject_delete_batches", "root_node_id"),
                       ("subject_delete_batch_items", "subject_node_id"),
                       ("dimension_delete_batch_subjects", "root_node_id")):
        n = db.fetchone(f"SELECT COUNT(*) AS n FROM {table} WHERE {col} IN ({marks})",
                        tuple(subject_ids))["n"]
        if n:
            found[f"{table}.{col}"] = n
    n = db.fetchone(f"SELECT COUNT(*) AS n FROM subject_nodes WHERE id IN ({marks})",
                    tuple(subject_ids))["n"]
    if n:
        found["subject_nodes.id"] = n
    return found


def _hard_delete(db, exam_id: int) -> None:
    db.update_exam_context_settings(exam_id, is_active=False)
    db.hard_delete_exam_context(exam_id)


def test_the_premise_every_dependent_table_is_populated(user_db):
    """Without this, the absence checks below could pass on an empty seed."""
    built = _build_exam(user_db, DOOMED)
    filed = _filed_under(user_db, DOOMED)
    assert all(n >= 1 for n in filed.values()), f"an empty name-keyed table: {filed}"
    seen = _rows_naming(user_db, built["subjects"])
    for key in ("subject_nodes.id", "subject_edges.child_id",
                "subject_relations.from_subject_id",
                "subject_relation_rejections.from_subject_id",
                "subject_aliases.subject_node_id",
                "entry_subject_mappings.subject_node_id",
                "subject_delete_batches.root_node_id"):
        assert seen.get(key), f"the seed put nothing in {key}: {seen}"
    assert user_db.fetchone("SELECT COUNT(*) AS n FROM dimension_delete_batches"
                            " WHERE exam_id = ?", (built["exam"].id,))["n"] == 1


def test_a_permanent_delete_leaves_nothing_filed_under_the_name(user_db):
    built = _build_exam(user_db, DOOMED)
    _hard_delete(user_db, built["exam"].id)

    assert set(_filed_under(user_db, DOOMED).values()) == {0}, (
        f"#873: rows outlived the delete: {_filed_under(user_db, DOOMED)}")
    assert _rows_naming(user_db, built["subjects"]) == {}, (
        "#873: something still points at a deleted subject")
    assert user_db.fetchone("SELECT COUNT(*) AS n FROM dimension_delete_batches"
                            " WHERE exam_id = ?", (built["exam"].id,))["n"] == 0


def test_the_next_exam_of_that_name_starts_empty(user_db):
    """The issue's reproduction, end to end."""
    built = _build_exam(user_db, DOOMED)
    _hard_delete(user_db, built["exam"].id)

    again = user_db.create_exam_context(exam_name=DOOMED)
    assert user_db.get_subject_hierarchy(DOOMED) == [], (
        "#873: the new exam inherited the deleted exam's subject tree")
    assert set(_filed_under(user_db, DOOMED).values()) == {0}, (
        "#873: the new exam inherited aliases or sources")
    assert user_db.get_tag_hierarchy(DOOMED) == [], (
        "#888: the new exam inherited the deleted exam's list of error types")
    assert again.id != built["exam"].id


def test_another_exam_is_untouched(user_db):
    doomed = _build_exam(user_db, DOOMED)
    kept = _build_exam(user_db, KEPT)
    before = (_filed_under(user_db, KEPT), _rows_naming(user_db, kept["subjects"]))

    _hard_delete(user_db, doomed["exam"].id)

    assert (_filed_under(user_db, KEPT), _rows_naming(user_db, kept["subjects"])) \
        == before
    assert user_db.fetchone("SELECT COUNT(*) AS n FROM dimension_delete_batches"
                            " WHERE exam_id = ?", (kept["exam"].id,))["n"] == 1
    assert user_db.fetchone("SELECT 1 FROM question_sources WHERE id = ?",
                            (kept["source"],)) is not None


def test_a_free_note_tagged_with_a_deleted_subject_survives(user_db):
    """#848: a free note is the student's own writing and belongs to no exam."""
    built = _build_exam(user_db, DOOMED)
    _hard_delete(user_db, built["exam"].id)
    assert user_db.get_entry_note(built["free_note"]) is not None


def test_a_source_another_exam_still_uses_is_unfiled_not_deleted(user_db):
    """Deleting it would fail on review_sessions' NO ACTION, or lose data."""
    built = _build_exam(user_db, DOOMED)
    other = user_db.create_exam_context(exam_name=KEPT)
    user_db.create_review_session(exam_context_id=other.id, total_questions=1,
                                  total_incorrect=1,
                                  question_source_id=built["source"])
    user_db.conn.commit()

    _hard_delete(user_db, built["exam"].id)

    row = user_db.fetchone("SELECT exam_context FROM question_sources WHERE id = ?",
                           (built["source"],))
    assert row is not None, "a source still in use was deleted"
    assert row["exam_context"] is None, (
        "a source still in use stayed filed under the deleted name, so the "
        "next exam of that name would inherit it")


def test_an_unused_source_filed_under_the_name_is_deleted(user_db):
    built = _build_exam(user_db, DOOMED)
    _hard_delete(user_db, built["exam"].id)
    assert user_db.fetchone("SELECT 1 FROM question_sources WHERE id = ?",
                            (built["source"],)) is None


def test_a_rename_into_a_deleted_exams_name_is_now_allowed(user_db):
    """#718 refused this because rows were left behind. They are not now."""
    built = _build_exam(user_db, DOOMED)
    _hard_delete(user_db, built["exam"].id)
    exam = user_db.create_exam_context(exam_name="Surgery")
    assert user_db.update_exam_context_settings(
        exam.id, exam_name=DOOMED).exam_name == DOOMED


# ---------------------------------------------------------- #887, inverted

def _kept_entry_tags(db, exam_id: int) -> list:
    return [tuple(r) for r in db.conn.execute(
        "SELECT et.question_entry_id, et.tag_id FROM entry_tags et"
        " JOIN question_entries qe ON qe.id = et.question_entry_id"
        " JOIN review_sessions rs ON rs.id = qe.review_session_id"
        " WHERE rs.exam_context_id = ? ORDER BY 1, 2", (exam_id,))]


def _every_tag(db) -> list:
    return [tuple(r) for r in db.conn.execute("SELECT * FROM tags ORDER BY id")]


def _list_of(db, exam_id: int) -> list:
    return [r[0] for r in db.conn.execute(
        "SELECT tag_id FROM exam_error_types WHERE exam_context_id = ?"
        " ORDER BY tag_id", (exam_id,))]


def test_a_permanent_delete_takes_no_error_type_off_another_exams_entries(user_db):
    """#887: deleting exam A stripped error types from exam B's entries.

    B's entry carries two types A also offers: a default both exams list,
    and A's own custom type, which is #887's exact shape (an entry of B
    tagged with a type filed under A). Both must survive the delete, and so
    must every row of the library.
    """
    doomed = _build_exam(user_db, DOOMED)
    kept = _build_exam(user_db, KEPT)
    # Both exams already offer their own type, so seeding would not list the
    # defaults on them; the default is put in the library and added to both.
    user_db.seed_default_tags("")
    gap = user_db.fetchone("SELECT id FROM tags WHERE tag_name = 'Knowledge Gap'")["id"]
    user_db.add_tag_to_exam(DOOMED, gap)
    user_db.add_tag_to_exam(KEPT, gap)
    shared = next(c for g in user_db.get_tag_hierarchy(DOOMED)
                  for c in g["children"] if c["name"] == "Knowledge Gap")
    assert shared["other_exam_count"] == 1, "premise: both exams offer it"
    for tag_id in (shared["id"], doomed["tag"]):
        user_db.execute("INSERT INTO entry_tags (question_entry_id, tag_id)"
                        " VALUES (?, ?)", (kept["entry"], tag_id))
    user_db.execute("INSERT INTO entry_tags (question_entry_id, tag_id)"
                    " VALUES (?, ?)", (doomed["entry"], shared["id"]))
    # m038 leaves every tags.exam_context NULL, so a delete that reached tags
    # by name would find nothing and this test would pass on it anyway. Filing
    # A's own type under A's name by hand is what makes it fail if "tags" ever
    # returns to the delete's name-keyed loop (#887's exact mechanism).
    user_db.execute("UPDATE tags SET exam_context = ? WHERE id = ?",
                    (DOOMED, doomed["tag"]))
    user_db.conn.commit()

    tags_before = _every_tag(user_db)
    kept_before = _kept_entry_tags(user_db, kept["exam"].id)
    kept_list = _list_of(user_db, kept["exam"].id)
    assert (kept["entry"], doomed["tag"]) in kept_before, "premise"
    assert _list_of(user_db, doomed["exam"].id), "premise: A lists types"

    _hard_delete(user_db, doomed["exam"].id)

    assert _every_tag(user_db) == tags_before, (
        "#887: a permanent delete removed error types from the library")
    assert _kept_entry_tags(user_db, kept["exam"].id) == kept_before, (
        "#887: a permanent delete took error types off another exam's entries")
    assert _list_of(user_db, kept["exam"].id) == kept_list
    assert _list_of(user_db, doomed["exam"].id) == [], (
        "the deleted exam's list must go with it, by cascade")
    assert user_db.fetchone("SELECT COUNT(*) AS n FROM entry_tags"
                            " WHERE question_entry_id = ?",
                            (doomed["entry"],))["n"] == 0, (
        "the deleted exam's own entries go, and their entry_tags with them")
