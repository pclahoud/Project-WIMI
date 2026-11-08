"""#888: error types are one library per profile, and each exam lists what it offers.

The owner's decisions, recorded on #888 under *Owner* headings (comments
12078 and 12081, accepting comment 12079's model):

1. A type is identified by (group name, type name); copies merge.
3. ``tags.exam_context`` is NULL: the library belongs to the profile.
4. A per-exam list, ``exam_error_types``, says what each exam's picker and
   Manage Error Types offer, so one exam can have types another does not.
   * 4a. A type made on an exam is listed on that exam only. Other exams add
     it on purpose ("Add from your other exams").
   * 4b. "Delete for good" is offered only once no other exam lists the
     type. It removes the type from every entry carrying it.

"Remove from this exam" deletes the list row only: entries keep the type.

Each test below names the rule it holds, and each was run against a mutant
of that rule (recorded in the PR for #888 Waves 1 and 2).
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.domains.tags import _DEFAULT_TAG_DEFINITIONS, _DEFAULT_TAG_GROUPS
from database.exceptions import TagError

pytestmark = pytest.mark.database

A, B, C = "Step 1", "Step 2 CK", "Surgery Shelf"


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="library_user",
                                  display_name="Library User",
                                  user_types=["student"])
        udb = UserDatabase(db_path=master.ensure_user_database(user.id),
                           user_id=user.id, username=user.username)
        yield udb
        udb.close()
        master.close()


def _exam(db, name):
    return db.create_exam_context(exam_name=name)


def _entry(db, exam, tag_ids):
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        date_encountered=date.today())
    subject = db.create_subject_node(exam_context=exam.exam_name,
                                     name=f"Subject {session.id}",
                                     level_type="System")
    return db.create_question_entry(session.id, "a", "b",
                                    primary_subject_ids=[subject.id],
                                    tag_ids=tag_ids)


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node["children"])


def _names(db, exam_name):
    return {n["name"] for n in _walk(db.get_tag_hierarchy(exam_name))}


def _node(db, exam_name, tag_id):
    return next((n for n in _walk(db.get_tag_hierarchy(exam_name))
                 if n["id"] == tag_id), None)


def _group_id(db, name):
    return db.fetchone("SELECT id FROM tags WHERE tag_name = ? AND is_group",
                       (name,))["id"]


def _entry_tag_ids(db, entry_id):
    return {r["tag_id"] for r in db.fetchall(
        "SELECT tag_id FROM entry_tags WHERE question_entry_id = ?", (entry_id,))}


DEFAULT_ROWS = len(_DEFAULT_TAG_GROUPS) + sum(len(t) for _, _, t in _DEFAULT_TAG_GROUPS)


# ------------------------------------------------------------- the seed

def test_the_premise_twenty_one_defaults():
    assert DEFAULT_ROWS == 21 == len(_DEFAULT_TAG_DEFINITIONS)


def test_seeding_two_exams_makes_one_library_listed_on_both(db):
    a, b = _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    db.seed_default_tags(B)

    rows = db.fetchall("SELECT id, exam_context FROM tags")
    assert len(rows) == DEFAULT_ROWS, "decision 1: one copy of each default"
    assert {r["exam_context"] for r in rows} == {None}, "decision 3"
    for exam in (a, b):
        listed = db.fetchall("SELECT tag_id FROM exam_error_types"
                             " WHERE exam_context_id = ?", (exam.id,))
        assert {r["tag_id"] for r in listed} == {r["id"] for r in rows}
    assert _names(db, A) == _names(db, B) == set(_DEFAULT_TAG_DEFINITIONS)


def test_seeding_again_changes_nothing(db):
    _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    db.seed_default_tags(B)
    before = (db.fetchall("SELECT * FROM tags ORDER BY id"),
              db.fetchall("SELECT exam_context_id, tag_id FROM exam_error_types"
                          " ORDER BY 1, 2"))
    db.seed_default_tags(A)
    db.seed_default_tags(B)
    db.seed_default_tags("No such exam")
    after = (db.fetchall("SELECT * FROM tags ORDER BY id"),
             db.fetchall("SELECT exam_context_id, tag_id FROM exam_error_types"
                         " ORDER BY 1, 2"))
    assert after == before


def test_seeding_leaves_an_exam_that_offers_something_alone(db):
    """An exam the student has shaped is not refilled with the defaults."""
    _exam(db, A)
    group = db.create_tag_group(A, "Mine")
    db.create_hierarchical_tag(A, "My type", group.id)
    db.seed_default_tags(A)
    assert _names(db, A) == {"Mine", "My type"}


# ------------------------------------------------------------- 4a

def test_a_type_created_on_one_exam_is_listed_on_that_exam_only(db):
    _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    db.seed_default_tags(B)
    group = _group_id(db, "Knowledge Issues")

    x = db.create_hierarchical_tag(A, "X", group)

    assert x.exam_context is None
    assert "X" in _names(db, A)
    assert "X" not in _names(db, B), "4a: B must add it on purpose"
    assert "X" in {c["name"] for g in db.get_tags_not_on_exam(B)
                   for c in g["children"]}


def test_creating_a_type_the_library_has_lists_it_and_makes_no_copy(db):
    _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    db.seed_default_tags(B)
    group = _group_id(db, "Knowledge Issues")
    x = db.create_hierarchical_tag(A, "X", group, description="first")
    count = db.fetchone("SELECT COUNT(*) AS n FROM tags")["n"]

    again = db.create_hierarchical_tag(B, "X", group, description="second")

    assert again.id == x.id
    assert again.description == "first", "a definition is shared"
    assert db.fetchone("SELECT COUNT(*) AS n FROM tags")["n"] == count
    assert "X" in _names(db, B)


def test_a_duplicate_name_in_the_same_group_is_refused_with_a_sentence(db):
    _exam(db, A)
    db.seed_default_tags(A)
    group = _group_id(db, "Knowledge Issues")
    with pytest.raises(TagError, match='"Knowledge Gap" is already an error type'
                                       ' in Knowledge Issues on this exam'):
        db.create_hierarchical_tag(A, "Knowledge Gap", group)
    with pytest.raises(TagError, match="already a group on this exam"):
        db.create_tag_group(A, "Knowledge Issues")


def test_the_same_name_in_another_group_is_a_different_type(db):
    _exam(db, A)
    db.seed_default_tags(A)
    other = _group_id(db, "Test Strategy")
    again = db.create_hierarchical_tag(A, "Knowledge Gap", other)
    assert again.id != db.fetchone(
        "SELECT id FROM tags WHERE tag_name = 'Knowledge Gap' AND parent_id = ?",
        (_group_id(db, "Knowledge Issues"),))["id"]


def test_add_tag_to_exam_lists_the_type_and_its_group(db):
    _exam(db, A), _exam(db, B)
    group = db.create_tag_group(A, "Habits")
    x = db.create_hierarchical_tag(A, "X", group.id)
    assert _names(db, B) == set()

    result = db.add_tag_to_exam(B, x.id)

    assert result["added"] == 2
    tree = db.get_tag_hierarchy(B)
    assert [g["name"] for g in tree] == ["Habits"]
    assert [c["name"] for c in tree[0]["children"]] == ["X"]
    assert db.get_tags_not_on_exam(B) == []


def test_adding_a_group_brings_its_types(db):
    _exam(db, A), _exam(db, B)
    group = db.create_tag_group(A, "Habits")
    db.create_hierarchical_tag(A, "X", group.id)
    db.create_hierarchical_tag(A, "Y", group.id)
    db.add_tag_to_exam(B, group.id)
    assert _names(db, B) == {"Habits", "X", "Y"}


def test_get_tags_not_on_exam(db):
    _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    db.seed_default_tags(B)
    ki = _group_id(db, "Knowledge Issues")
    x = db.create_hierarchical_tag(A, "X", ki)
    new_group = db.create_tag_group(A, "Habits")
    y = db.create_hierarchical_tag(A, "Y", new_group.id)
    _entry(db, db.get_exam_context_by_name(A), [x.id])

    tree = db.get_tags_not_on_exam(B)

    by_name = {n["name"]: n for n in tree}
    assert set(by_name) == {"Knowledge Issues", "Habits"}
    assert by_name["Knowledge Issues"]["listed"] is True, "B lists the group"
    assert [c["name"] for c in by_name["Knowledge Issues"]["children"]] == ["X"]
    assert by_name["Habits"]["listed"] is False
    assert [c["id"] for c in by_name["Habits"]["children"]] == [y.id]
    xnode = by_name["Knowledge Issues"]["children"][0]
    assert (xnode["exam_count"], xnode["entry_count_all"]) == (1, 1)
    assert db.get_tags_not_on_exam(A) == []
    with pytest.raises(TagError, match="no exam called"):
        db.get_tags_not_on_exam("No such exam")


# ------------------------------------------------------------- remove

def test_remove_from_this_exam_keeps_the_type_on_its_entries(db):
    a, b = _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    group = _group_id(db, "Knowledge Issues")
    x = db.create_hierarchical_tag(A, "X", group)
    db.add_tag_to_exam(B, x.id)
    entry_b = _entry(db, b, [x.id])
    entry_a = _entry(db, a, [x.id])
    analytics_before = db.get_tag_analytics(b.id)

    result = db.remove_tag_from_exam(B, x.id)

    assert result["removed"] == 1 and result["entries_keeping"] == 1
    assert x.id in _entry_tag_ids(db, entry_b.id), "B's entry keeps X"
    assert x.id in _entry_tag_ids(db, entry_a.id)
    assert "X" not in _names(db, B)
    assert "X" in _names(db, A)
    assert db.get_tag(x.id) is not None, "the library keeps it"
    assert db.get_tag_analytics(b.id) == analytics_before, (
        "analytics still count a type the exam no longer offers")
    assert [t.id for t in db.get_question_entry(entry_b.id).tags] == [x.id]


def test_removing_a_group_takes_its_listed_types_off_this_exam(db):
    _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    db.seed_default_tags(B)
    db.remove_tag_from_exam(B, _group_id(db, "Knowledge Issues"))
    assert {"Knowledge Issues", "Knowledge Gap", "Memory Failure",
            "Misunderstanding"} & _names(db, B) == set()
    assert "Knowledge Gap" in _names(db, A)


def _picker_load(db, exam_name):
    """What ``loadTagHierarchy`` does: an empty picker asks for the defaults."""
    tree = db.get_tag_hierarchy(exam_name)
    if not tree:
        db.seed_default_tags(exam_name)
        tree = db.get_tag_hierarchy(exam_name)
    return tree


def test_an_exam_emptied_by_remove_stays_empty_when_the_picker_reloads(db):
    """#895 review: emptying a list on purpose must not bring the defaults back.

    The entry form reloads the picker after every Remove, and an empty picker
    calls seedDefaultTags. Seeding on "the list is empty" re-listed all 21.
    """
    _exam(db, A), _exam(db, B)
    assert len(list(_walk(_picker_load(db, A)))) == DEFAULT_ROWS
    _picker_load(db, B)
    for group in db.get_tag_hierarchy(B):
        db.remove_tag_from_exam(B, group["id"])
    assert db.get_tag_hierarchy(B) == []

    assert _picker_load(db, B) == [], "the Remove was undone by a reseed"
    assert db.fetchone("SELECT COUNT(*) AS n FROM exam_error_types"
                       " WHERE exam_context_id = ?",
                       (db.get_exam_context_by_name(B).id,))["n"] == 0
    assert len(list(_walk(db.get_tags_not_on_exam(B)))) == DEFAULT_ROWS, (
        "everything removed is offered back under Add from your other exams")


def test_a_default_deleted_for_good_is_not_recreated_by_a_reload(db):
    _exam(db, A)
    _picker_load(db, A)
    gap = db.fetchone("SELECT id FROM tags WHERE tag_name = 'Knowledge Gap'")["id"]
    db.remove_tag_from_exam(A, gap)
    db.delete_tag(gap, A)
    for group in db.get_tag_hierarchy(A):
        db.remove_tag_from_exam(A, group["id"])

    _picker_load(db, A)

    assert db.fetchone("SELECT 1 FROM tags WHERE tag_name = 'Knowledge Gap'") is None


def test_a_new_exam_is_still_offered_the_defaults_once(db):
    _exam(db, A)
    _picker_load(db, A)
    for group in db.get_tag_hierarchy(A):
        db.remove_tag_from_exam(A, group["id"])
    _exam(db, C)
    assert _names(db, C) == set()
    assert {n["name"] for n in _walk(_picker_load(db, C))} == set(_DEFAULT_TAG_DEFINITIONS)


def test_removing_a_type_the_exam_does_not_offer_is_refused(db):
    _exam(db, A), _exam(db, B)
    x = db.create_tag(A, "X")
    with pytest.raises(TagError, match='"X" is not offered on this exam'):
        db.remove_tag_from_exam(B, x.id)


# ------------------------------------------------------------- 4b

def test_delete_for_good_is_refused_while_another_exam_lists_the_type(db):
    a, b = _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    group = _group_id(db, "Knowledge Issues")
    x = db.create_hierarchical_tag(A, "X", group)
    db.add_tag_to_exam(B, x.id)
    entry_a, entry_b = _entry(db, a, [x.id]), _entry(db, b, [x.id])

    with pytest.raises(TagError, match=f'still offered on "{B}"'):
        db.delete_tag(x.id, A)
    with pytest.raises(TagError, match="still offered on"):
        db.delete_tag(x.id)     # the one-argument form: two exams list it
    assert db.get_tag(x.id) is not None

    db.remove_tag_from_exam(B, x.id)
    result = db.delete_tag(x.id, A)

    assert result["affected_entries"] == 2, "the count spans every exam"
    assert db.fetchone("SELECT 1 FROM tags WHERE id = ?", (x.id,)) is None
    assert x.id not in _entry_tag_ids(db, entry_a.id)
    assert x.id not in _entry_tag_ids(db, entry_b.id), (
        "Delete for good takes it off every exam's entries")
    assert db.fetchone("SELECT 1 FROM exam_error_types WHERE tag_id = ?",
                       (x.id,)) is None


def test_delete_for_good_named_from_the_wrong_exam_is_refused(db):
    _exam(db, A), _exam(db, B)
    x = db.create_tag(A, "X")
    with pytest.raises(TagError, match=f'still offered on "{A}"'):
        db.delete_tag(x.id, B)


def test_a_type_no_exam_lists_can_be_deleted_by_either_form(db):
    _exam(db, A)
    x = db.create_tag(A, "X")
    db.remove_tag_from_exam(A, x.id)
    assert db.delete_tag(x.id)["name"] == "X"


def test_a_group_with_types_is_still_refused(db):
    _exam(db, A)
    db.seed_default_tags(A)
    with pytest.raises(TagError, match="contains 3 types"):
        db.delete_tag(_group_id(db, "Knowledge Issues"), A)


# ------------------------------------------------------------- the payload

def test_the_hierarchy_says_how_many_other_exams_and_entries(db):
    a, b, c = _exam(db, A), _exam(db, B), _exam(db, C)
    for name in (A, B, C):
        db.seed_default_tags(name)
    ki = _group_id(db, "Knowledge Issues")
    gap = db.fetchone("SELECT id FROM tags WHERE tag_name = 'Knowledge Gap'")["id"]
    x = db.create_hierarchical_tag(A, "X", ki)
    _entry(db, a, [gap, x.id])
    _entry(db, b, [gap])
    _entry(db, c, [gap])
    db.remove_tag_from_exam(C, gap)

    node = _node(db, A, gap)
    assert node["other_exam_count"] == 1, "B lists it; C removed it"
    assert node["entry_count_all"] == 3, "C's entry still carries it"
    assert node["usage_count"] == 1, "usage_count is this exam's entries"
    assert _node(db, A, x.id)["other_exam_count"] == 0
    assert _node(db, A, x.id)["entry_count_all"] == 1
    group = _node(db, A, ki)
    assert group["library_child_count"] == 4
    assert group["other_exam_count"] == 2
    assert _node(db, B, gap)["other_exam_count"] == 1


def test_a_definition_is_shared_by_every_exam_that_lists_it(db):
    _exam(db, A), _exam(db, B)
    db.seed_default_tags(A)
    db.seed_default_tags(B)
    gap = db.fetchone("SELECT id FROM tags WHERE tag_name = 'Knowledge Gap'")["id"]
    db.update_tag_description(gap, "rewritten on A")
    assert _node(db, B, gap)["description"] == "rewritten on A"


def test_get_tags_by_exam_reads_the_list(db):
    _exam(db, A), _exam(db, B)
    db.create_tag(A, "X")
    assert [t.tag_name for t in db.get_tags_by_exam(A)] == ["X"]
    assert db.get_tags_by_exam(B) == []
    assert db.get_tags_by_exam("No such exam") == []


# ------------------------------------------------------------- the logger

def test_every_new_write_path_survives_a_real_logger(tmp_path):
    """The fixtures above build their database with no logger, so no log call
    on these paths runs there (the #relation-confirmation class of bug)."""
    from app_logging import ErrorLogger

    logger = ErrorLogger(app_name="ErrorTypeWriteTest",
                         log_dir=tmp_path / "logs", flush_interval=60.0)
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=logger)
    user = master.create_user(username="logged", display_name="L",
                              user_types=["student"])
    udb = UserDatabase(db_path=master.ensure_user_database(user.id),
                       user_id=user.id, username=user.username,
                       error_logger=logger)
    try:
        assert udb.error_logger is not None, "the premise of this test"
        udb.create_exam_context(A)
        udb.create_exam_context(B)
        udb.seed_default_tags(A)
        group = udb.create_tag_group(A, "Habits")
        x = udb.create_hierarchical_tag(A, "X", group.id)
        udb.add_tag_to_exam(B, x.id)
        udb.remove_tag_from_exam(B, x.id)
        udb.delete_tag(x.id, A)
    finally:
        udb.close()
        master.close()
        logger.cleanup(wait=False)
