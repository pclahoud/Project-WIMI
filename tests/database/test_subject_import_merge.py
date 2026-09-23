"""Subject-tree import is a merge behind a plan — issue #67.

The bug these pin down: ``import_node`` called ``create_subject_node``
unconditionally for every node in the file, so re-importing a corrected
outline either **duplicated** whatever had been renamed or **failed
outright** on the first node that had not. Both halves are asserted
below against the planner and the apply, because the acceptance criteria
are about what the tree looks like afterwards, not about which method
was called.

The structural claim of the issue — "share the planning code between
preview and execution so they cannot drift, as #15 does" — is asserted
directly in ``test_plan_counts_match_what_apply_did``: the apply returns
the plan it executed, so the two are the same object, not two agreeing
computations.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.exceptions import ValidationError


pytestmark = pytest.mark.database


# ==================== Fixtures & helpers ====================

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def test_user(master_db):
    return master_db.create_user(
        username="import_user",
        display_name="Import Merge User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    db_path = master_db.ensure_user_database(test_user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=test_user.id,
        username=test_user.username,
    )
    yield db
    db.close()


@pytest.fixture
def exam(user_db):
    """A bare exam context with no subjects."""
    user_db.create_exam_context(
        exam_name="Merge Exam",
        exam_description="issue #67",
    )
    return user_db.get_exam_context_by_name("Merge Exam")


def _file(*roots):
    return list(roots)


def _node(name, *, id=None, children=None, weight=None, level_type=None,
          sort_order=None, aliases=None):
    node = {'name': name}
    if id is not None:
        node['id'] = id
    if children:
        node['children'] = list(children)
    if weight is not None:
        node['weight'] = weight
    if level_type is not None:
        node['level_type'] = level_type
    if sort_order is not None:
        node['sort_order'] = sort_order
    if aliases is not None:
        node['aliases'] = aliases
    return node


def _active(user_db, exam_name):
    return {
        row['name']: row['id']
        for row in user_db.fetchall(
            "SELECT id, name FROM subject_nodes "
            "WHERE exam_context = ? AND status = 'active'",
            (exam_name,),
        )
    }


def _session(user_db, exam) -> int:
    cursor = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) VALUES (?, 'S', ?, ?, 1, 1)",
        (user_db.user_id, date.today().isoformat(), exam.id),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _tag_entry(user_db, exam, subject_id, order=1):
    """Create an entry and tag it to ``subject_id``.

    Raw inserts, like ``test_subject_delete_semantics.py``: the point is
    the mapping row, and going through the entry API would drag session
    and draft policy into a test about subject survival.
    """
    session_id = _session(user_db, exam)
    entry_id = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, 'A', 'B')",
        (session_id, order),
    ).lastrowid
    user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type) "
        "VALUES (?, ?, 'primary')",
        (entry_id, subject_id),
    )
    user_db.conn.commit()
    return entry_id


# ==================== The bug ====================

def test_reimporting_an_unchanged_file_is_a_no_op(user_db, exam):
    """Acceptance 1: no duplicates, no new rows.

    Before the fix this raised ``Subject node already exists: …/Root``
    from ``create_subject_node`` and left the caller with a failed
    import over a file that asked for nothing.
    """
    tree = _file(_node("Root", children=[_node("A"), _node("B")]))

    user_db.apply_subject_import(exam.id, tree)
    first = _active(user_db, exam.exam_name)
    assert set(first) == {"Root", "A", "B"}

    result = user_db.apply_subject_import(exam.id, tree)

    assert _active(user_db, exam.exam_name) == first, (
        "re-importing the same file changed the tree"
    )
    assert result['counts']['added'] == 0
    assert result['counts']['updated'] == 0
    assert result['counts']['removed'] == 0
    assert result['counts']['unchanged'] == 3


def test_rename_without_an_id_duplicated_the_tree(user_db, exam):
    """The other half of the old behaviour, now a remove-plus-add.

    With no ids in the file, "Root" renamed to "Root Renamed" is
    indistinguishable from a new subject, and the old one going away.
    That is the acceptance criterion — what must *not* happen is both
    trees existing at once, which is what the old importer produced.
    """
    user_db.apply_subject_import(
        exam.id, _file(_node("Root", children=[_node("A")]))
    )
    user_db.apply_subject_import(
        exam.id, _file(_node("Root Renamed", children=[_node("A")]))
    )

    names = _active(user_db, exam.exam_name)
    assert "Root" not in names, "the old root survived alongside the new one"
    assert set(names) == {"Root Renamed", "A"}


def test_preview_says_a_rename_without_ids_is_remove_plus_add(user_db, exam):
    """Acceptance 3: the preview has to say so, plainly."""
    user_db.apply_subject_import(
        exam.id, _file(_node("Root", children=[_node("A")]))
    )

    plan = user_db.plan_subject_import(
        exam.id, _file(_node("Root Renamed", children=[_node("A")]))
    )

    assert plan['rename_blind'] is True
    assert plan['file_uses_ids'] is False
    # The whole branch goes, not just the renamed node: "A" is matched by
    # name *under its parent*, and its parent is now a subject that does
    # not exist yet. That is the cost the banner is warning about, and
    # the preview states it rather than softening it.
    assert [item['name'] for item in plan['added']] == ["Root Renamed", "A"]
    assert {item['name'] for item in plan['removed']} == {"Root", "A"}


# ==================== Stable ids ====================

def test_rename_with_a_stable_id_is_a_rename(user_db, exam):
    """Acceptance 2: entries, weights and relations survive a rename."""
    user_db.apply_subject_import(
        exam.id,
        _file(_node("Cardio", id="c", weight=20, children=[
            _node("Arrhythmia", id="c.1"),
        ])),
    )
    ids = _active(user_db, exam.exam_name)
    node_id = ids["Arrhythmia"]
    entry_id = _tag_entry(user_db, exam, node_id)

    result = user_db.apply_subject_import(
        exam.id,
        _file(_node("Cardiovascular", id="c", weight=20, children=[
            _node("Arrhythmias and conduction", id="c.1"),
        ])),
    )

    after = _active(user_db, exam.exam_name)
    assert set(after) == {"Cardiovascular", "Arrhythmias and conduction"}
    assert after["Arrhythmias and conduction"] == node_id, (
        "the renamed subject is a different row — its history was orphaned"
    )
    assert result['counts']['renamed'] == 2
    assert result['counts']['added'] == 0
    assert result['counts']['removed'] == 0

    mapping = user_db.fetchone(
        "SELECT subject_node_id FROM entry_subject_mappings "
        "WHERE question_entry_id = ?",
        (entry_id,),
    )
    assert mapping['subject_node_id'] == node_id


def test_an_existing_subject_adopts_the_file_id_on_first_sight(user_db, exam):
    """The upgrade path for trees imported before ids existed.

    A 2,211-subject outline already in the database has no ids. The
    first file that carries them matches by name-and-path and the ids
    stick, so the *next* re-import can see renames.
    """
    user_db.apply_subject_import(exam.id, _file(_node("Renal")))
    user_db.apply_subject_import(exam.id, _file(_node("Renal", id="r")))

    row = user_db.fetchone(
        "SELECT import_id FROM subject_nodes WHERE name = 'Renal'"
    )
    assert row['import_id'] == "r"

    user_db.apply_subject_import(exam.id, _file(_node("Renal/Urinary", id="r")))
    assert set(_active(user_db, exam.exam_name)) == {"Renal/Urinary"}


def test_a_moved_subject_keeps_its_row_and_changes_parent(user_db, exam):
    """"Programming error" moved up a level, from the real import."""
    user_db.apply_subject_import(
        exam.id,
        _file(_node("Root", id="root", children=[
            _node("Branch", id="b", children=[_node("Leaf", id="leaf")]),
        ])),
    )
    leaf_id = _active(user_db, exam.exam_name)["Leaf"]

    result = user_db.apply_subject_import(
        exam.id,
        _file(_node("Root", id="root", children=[
            _node("Branch", id="b"),
            _node("Leaf", id="leaf"),
        ])),
    )

    assert _active(user_db, exam.exam_name)["Leaf"] == leaf_id
    assert result['counts']['moved'] == 1
    parents = [
        row['parent_id'] for row in user_db.fetchall(
            "SELECT parent_id FROM subject_edges WHERE child_id = ?", (leaf_id,)
        )
    ]
    assert parents == [_active(user_db, exam.exam_name)["Root"]]


def test_an_id_match_outranks_a_name_match_for_the_same_subject(user_db, exam):
    """Ids are matched in a first pass, before any name can claim a row.

    Without that ordering: "Alpha" (no id) claims the existing *renamed*
    row by name, so the file node carrying that row's id falls through to
    "add" — and the add writes an ``import_id`` the claimed row still
    holds, which trips the unique index and aborts an import over a file
    that is perfectly well-formed.
    """
    user_db.apply_subject_import(exam.id, _file(_node("Alpha", id="x")))
    alpha_id = _active(user_db, exam.exam_name)["Alpha"]

    # The file renames the id-carrying subject to "Beta" and introduces a
    # *new* subject that happens to be called "Alpha".
    result = user_db.apply_subject_import(
        exam.id, _file(_node("Alpha"), _node("Beta", id="x"))
    )

    after = _active(user_db, exam.exam_name)
    assert after["Beta"] == alpha_id, "the id did not win the match"
    assert after["Alpha"] != alpha_id, "the new subject reused the old row"
    assert result['counts']['added'] == 1
    assert result['counts']['renamed'] == 1
    assert result['counts']['removed'] == 0


def test_a_subject_can_move_under_a_parent_the_same_import_creates(user_db, exam):
    """Reorganising an outline in one pass.

    The new parent does not exist when the moved subject's row is
    updated, so the move has to run after the creates — which is why the
    apply is phased rather than one walk.
    """
    user_db.apply_subject_import(
        exam.id,
        _file(_node("Root", id="r", children=[_node("Leaf", id="leaf")])),
    )
    leaf_id = _active(user_db, exam.exam_name)["Leaf"]

    result = user_db.apply_subject_import(
        exam.id,
        _file(_node("Root", id="r", children=[
            _node("New Chapter", id="ch", children=[_node("Leaf", id="leaf")]),
        ])),
    )

    after = _active(user_db, exam.exam_name)
    assert after["Leaf"] == leaf_id, "the moved subject was recreated"
    assert result['counts']['added'] == 1
    assert result['counts']['moved'] == 1
    parents = [
        row['parent_id'] for row in user_db.fetchall(
            "SELECT parent_id FROM subject_edges WHERE child_id = ?", (leaf_id,)
        )
    ]
    assert parents == [after["New Chapter"]]
    assert not result['warnings'], result['warnings']


def test_two_subjects_claiming_one_id_is_an_error_not_a_guess(user_db, exam):
    plan = user_db.plan_subject_import(
        exam.id, _file(_node("One", id="x"), _node("Two", id="x"))
    )
    assert plan['errors']
    with pytest.raises(ValidationError):
        user_db.apply_subject_import(
            exam.id, _file(_node("One", id="x"), _node("Two", id="x"))
        )


# ==================== Decision 3 — entries outrank the blueprint ====

def test_a_subject_with_entries_is_kept_when_the_file_drops_it(user_db, exam):
    """Acceptance 4. The student's history outranks the blueprint."""
    user_db.apply_subject_import(
        exam.id, _file(_node("Root", children=[_node("Keeper"), _node("Goner")]))
    )
    ids = _active(user_db, exam.exam_name)
    _tag_entry(user_db, exam, ids["Keeper"])

    result = user_db.apply_subject_import(exam.id, _file(_node("Root")))

    after = _active(user_db, exam.exam_name)
    assert "Keeper" in after, "a subject carrying entries was removed"
    assert "Goner" not in after, "an empty subject the file dropped survived"
    kept = result['kept_in_use']
    assert [item['name'] for item in kept] == ["Keeper"]
    assert kept[0]['entry_count'] == 1
    assert kept[0]['id'] == ids["Keeper"]
    assert result['entries_affected'] == 1


def test_an_ancestor_of_a_kept_subject_is_kept_too(user_db, exam):
    """Removing the chapter would leave the kept topic rolling up nowhere.

    This is the #15 silent-rollup-loss class, reached through import
    instead of through the delete modal.
    """
    user_db.apply_subject_import(
        exam.id,
        _file(_node("Chapter", children=[
            _node("Section", children=[_node("Topic")]),
        ])),
    )
    ids = _active(user_db, exam.exam_name)
    _tag_entry(user_db, exam, ids["Topic"])

    result = user_db.apply_subject_import(exam.id, _file(_node("Other")))

    after = _active(user_db, exam.exam_name)
    assert {"Chapter", "Section", "Topic"} <= set(after)
    assert [item['name'] for item in result['kept_in_use']] == ["Topic"]
    assert {item['name'] for item in result['kept_as_ancestor']} == {
        "Chapter", "Section"
    }
    assert result['counts']['removed'] == 0


def test_no_entry_is_left_pointing_at_a_subject_that_no_longer_exists(
    user_db, exam
):
    """The acceptance criterion the issue asks for by name.

    Tagged subjects spread across the tree, then a file that lists none
    of them. Every mapping must still resolve to an ``active`` row.
    """
    user_db.apply_subject_import(
        exam.id,
        _file(
            _node("A", children=[_node("A1"), _node("A2")]),
            _node("B", children=[_node("B1", children=[_node("B1a")])]),
        ),
    )
    ids = _active(user_db, exam.exam_name)
    for name in ("A1", "B1a"):
        _tag_entry(user_db, exam, ids[name])

    user_db.apply_subject_import(exam.id, _file(_node("Replacement")))

    dangling = user_db.fetchall(
        """
        SELECT esm.id, esm.subject_node_id, sn.status
        FROM entry_subject_mappings esm
        LEFT JOIN subject_nodes sn ON sn.id = esm.subject_node_id
        WHERE sn.id IS NULL OR sn.status != 'active'
        """
    )
    assert dangling == [], (
        f"{len(dangling)} entry mappings point at a subject that is gone"
    )


def test_removals_go_through_the_delete_journal(user_db, exam):
    """An import's removals must be the *same* soft delete as #15's.

    Not a second set of rules: same archive, same batch, same journal,
    so #37's restore can undo an over-eager import.
    """
    user_db.apply_subject_import(
        exam.id, _file(_node("Root", children=[_node("Doomed")]))
    )
    result = user_db.apply_subject_import(exam.id, _file(_node("Root")))

    assert len(result['delete_batch_ids']) == 1
    batch_id = result['delete_batch_ids'][0]
    items = user_db.fetchall(
        "SELECT item_type, subject_node_id FROM subject_delete_batch_items "
        "WHERE batch_id = ?",
        (batch_id,),
    )
    assert any(item['item_type'] == 'node_archived' for item in items)
    archived = user_db.fetchone(
        "SELECT status, deleted_batch_id FROM subject_nodes WHERE name = 'Doomed'"
    )
    assert archived['status'] == 'archived'
    assert archived['deleted_batch_id'] == batch_id


def test_an_empty_file_removes_nothing(user_db, exam):
    """A file listing no subjects is a no-op, never "delete everything".

    "Every subject is absent from this file" and "this file lists no
    subjects" are the same sentence to the matcher and opposite
    intentions to the student. A misspelled ``root_nodes`` key or a
    truncated download arrives here as an empty list, and the old
    importer's answer to that — do nothing — was the right one.
    """
    user_db.apply_subject_import(
        exam.id, _file(_node("Root", children=[_node("Child")]))
    )
    before = _active(user_db, exam.exam_name)

    plan = user_db.plan_subject_import(exam.id, [])
    assert plan['empty_file'] is True
    assert plan['counts']['removed'] == 0

    result = user_db.apply_subject_import(exam.id, [])

    assert _active(user_db, exam.exam_name) == before
    assert result['counts']['removed'] == 0
    assert result['imported_count'] == 0


# ==================== Preview cannot drift from the apply ==========

def test_plan_counts_match_what_apply_did(user_db, exam):
    """Acceptance 6, asserted structurally *and* by outcome."""
    user_db.apply_subject_import(
        exam.id,
        _file(_node("Root", id="r", children=[
            _node("Stays", id="s"),
            _node("Renamed", id="rn"),
            _node("Dropped", id="d"),
            _node("InUse", id="u"),
        ])),
    )
    ids = _active(user_db, exam.exam_name)
    _tag_entry(user_db, exam, ids["InUse"])

    incoming = _file(_node("Root", id="r", children=[
        _node("Stays", id="s"),
        _node("Renamed Properly", id="rn"),
        _node("Brand New", id="new"),
    ]))

    plan = user_db.plan_subject_import(exam.id, incoming)
    result = user_db.apply_subject_import(exam.id, incoming)

    assert plan['counts'] == result['counts'], (
        "the preview promised different numbers than the import produced"
    )
    assert plan['counts']['added'] == 1
    assert plan['counts']['renamed'] == 1
    assert plan['counts']['removed'] == 1
    assert plan['counts']['kept_in_use'] == 1

    after = _active(user_db, exam.exam_name)
    assert len(result['created_ids']) == plan['counts']['added']
    assert len(result['removed_ids']) == plan['counts']['removed']
    assert "Dropped" not in after
    assert "InUse" in after
    assert "Brand New" in after


def test_a_second_import_after_a_merge_is_still_a_no_op(user_db, exam):
    """The property that makes the whole feature usable: idempotence.

    A student correcting an outline re-imports repeatedly. The third
    import of the corrected file must do nothing at all, or every save
    quietly churns the tree.
    """
    first = _file(_node("Root", id="r", children=[_node("Child", id="c")]))
    corrected = _file(_node("Root", id="r", children=[
        _node("Child Renamed", id="c"), _node("Extra", id="e"),
    ]))

    user_db.apply_subject_import(exam.id, first)
    user_db.apply_subject_import(exam.id, corrected)
    snapshot = _active(user_db, exam.exam_name)

    third = user_db.apply_subject_import(exam.id, corrected)

    assert _active(user_db, exam.exam_name) == snapshot
    assert third['counts'] == {
        'added': 0, 'updated': 0, 'unchanged': 3, 'renamed': 0, 'moved': 0,
        'removed': 0, 'kept_in_use': 0, 'kept_as_ancestor': 0,
        'entries_affected': 0,
    }


def test_weights_and_levels_are_updated_in_place(user_db, exam):
    user_db.apply_subject_import(
        exam.id, _file(_node("Root", id="r", weight=10))
    )
    node_id = _active(user_db, exam.exam_name)["Root"]

    plan = user_db.plan_subject_import(
        exam.id, _file(_node("Root", id="r", weight={"low": 15, "high": 20}))
    )
    assert plan['counts']['updated'] == 1
    assert plan['updated'][0]['changes']['exam_weight_low'] == [10.0, 15]

    user_db.apply_subject_import(
        exam.id, _file(_node("Root", id="r", weight={"low": 15, "high": 20}))
    )
    row = user_db.fetchone(
        "SELECT exam_weight_low, exam_weight_high FROM subject_nodes WHERE id = ?",
        (node_id,),
    )
    assert (row['exam_weight_low'], row['exam_weight_high']) == (15, 20)


def test_a_hand_added_second_parent_survives_a_re_import(user_db, exam):
    """Polyhierarchy edges the file does not mention are not its business."""
    user_db.apply_subject_import(
        exam.id,
        _file(
            _node("Cardio", id="c", children=[_node("DVT", id="dvt")]),
            _node("Pulm", id="p"),
        ),
    )
    ids = _active(user_db, exam.exam_name)
    user_db.add_edge(ids["Pulm"], ids["DVT"], is_primary=False)

    user_db.apply_subject_import(
        exam.id,
        _file(
            _node("Cardio", id="c", children=[_node("DVT", id="dvt")]),
            _node("Pulm", id="p"),
        ),
    )

    parents = {
        row['parent_id'] for row in user_db.fetchall(
            "SELECT parent_id FROM subject_edges WHERE child_id = ?",
            (ids["DVT"],),
        )
    }
    assert parents == {ids["Cardio"], ids["Pulm"]}
