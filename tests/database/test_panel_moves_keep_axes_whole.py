"""The "Subjects not in any axis" panel cannot split a shared subject across
axes (#903) or hit m020's import-id index raw (#904).

The panel moves one top-level subject at a time into an EXISTING axis
(``move_subjects_into_axis``). Before these fixes:

* #903 -- two top-level subjects sharing a child could go into different
  axes, one press each, leaving an edge from one axis into another.
  Cross-dimensional edges are a Non-Goal;
* #904 -- a subject whose ``import_id`` an active subject of the target axis
  already held reached the page as ``UNIQUE constraint failed: index
  'idx_subject_nodes_import_id'``.

The rules, one test each:

* a top-level subject that shares a subject with another top-level subject
  outside every axis **moves together with it** (the owner's rule for the
  first-axis prompt, #605 decision 6), and the listing names the link so the
  panel can say it before the press;
* a move that would leave a subject under, or over, a subject already in a
  **different** axis is refused with a sentence naming the axis that can
  take it -- no move into the chosen axis can avoid that edge;
* an import-id clash is refused with a sentence naming the subject and the
  axis, before any write.

Controls: an unlinked subject still moves alone, a move into the axis that
already holds the shared subject still works, and a move with no clash still
works.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase

EXAM = "Panel Move Exam"


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmp:
        master = MasterDatabase(data_dir=Path(tmp))
        user = master.create_user(username="panel_move", display_name="Panel",
                                  user_types=["student"])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username=user.username)
        db._ensure_phase2_schema()
        yield db
        db.close()
        master.close()


def _subject(db, name, import_id=None, dimension_id=None):
    cur = db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, dimension_id,"
        " import_id, sort_order, status) VALUES (?, ?, 'System', ?, ?, 0, 'active')",
        (EXAM, name, dimension_id, import_id))
    db.conn.commit()
    return cur.lastrowid


def _axis_of(db, subject_id):
    return db.fetchone("SELECT dimension_id FROM subject_nodes WHERE id = ?",
                       (subject_id,))["dimension_id"]


@pytest.fixture
def shared(user_db):
    """#903's repro: RootA and RootB share SharedC; Lone stands apart. Two axes."""
    exam = user_db.create_exam_context(exam_name=EXAM, exam_description="#903")
    x = user_db.create_dimension(exam_id=exam.id, name="AxisX", display_order=1)
    y = user_db.create_dimension(exam_id=exam.id, name="AxisY", display_order=2)
    ids = {n: _subject(user_db, n) for n in ("RootA", "RootB", "SharedC", "Lone")}
    user_db.add_edge(ids["RootA"], ids["SharedC"], is_primary=True)
    user_db.add_edge(ids["RootB"], ids["SharedC"], is_primary=False)
    user_db.conn.commit()
    return exam, x, y, ids


# ---------------------------------------------------------------- #903

def test_moving_one_root_takes_the_root_it_shares_a_subject_with(user_db, shared):
    exam, x, y, ids = shared

    result = user_db.move_subjects_into_axis([ids["RootA"]], x)

    assert result["success"] is True, result
    for name in ("RootA", "RootB", "SharedC"):
        assert _axis_of(user_db, ids[name]) == x, (
            f"{name} was left behind; a later press could then put RootB in "
            f"another axis from SharedC, which is #903")
    assert [s["name"] for s in result["linked_subjects"]] == ["RootB"], result
    assert result["moved"] == 3


def test_an_unlinked_root_still_moves_alone(user_db, shared):
    """Control: the link is shared subjects, not 'every stranded root'."""
    exam, x, y, ids = shared

    result = user_db.move_subjects_into_axis([ids["Lone"]], y)

    assert result["success"] is True, result
    assert result["moved"] == 1 and result["linked_subjects"] == []
    assert _axis_of(user_db, ids["Lone"]) == y
    for name in ("RootA", "RootB", "SharedC"):
        assert _axis_of(user_db, ids[name]) is None, f"{name} moved too"


def test_the_listing_names_the_link_before_the_press(user_db, shared):
    exam, x, y, ids = shared

    rows = {r["name"]: r for r in user_db.get_subjects_outside_any_axis(exam.id)}

    assert [m["name"] for m in rows["RootA"]["moves_with"]] == ["RootB"]
    assert [m["name"] for m in rows["RootB"]["moves_with"]] == ["RootA"]
    assert rows["Lone"]["moves_with"] == []
    assert rows["RootA"]["group"] == rows["RootB"]["group"] != rows["Lone"]["group"]


def _strand_root_b_after_root_a_moved(user_db, x, ids):
    """The state #903 reached by two presses: SharedC already in AxisX
    under RootA, RootB still outside every axis."""
    user_db.execute("UPDATE subject_nodes SET dimension_id = ? WHERE id IN (?, ?)",
                    (x, ids["RootA"], ids["SharedC"]))
    user_db.conn.commit()


def test_a_root_whose_shared_subject_is_in_another_axis_is_refused(user_db, shared):
    exam, x, y, ids = shared
    _strand_root_b_after_root_a_moved(user_db, x, ids)

    result = user_db.move_subjects_into_axis([ids["RootB"]], y)

    assert result["success"] is False, result
    error = result["error"]
    for word in ('"RootB"', '"AxisY"', '"SharedC"', '"AxisX"'):
        assert word in error, f"the refusal must name {word}: {error!r}"
    assert 'Move it into "AxisX" instead' in error, error
    assert _axis_of(user_db, ids["RootB"]) is None, "the refused move wrote"


def test_the_same_root_moves_into_the_axis_that_holds_its_shared_subject(
        user_db, shared):
    """Control for the refusal: the edge stays inside one axis, so it moves."""
    exam, x, y, ids = shared
    _strand_root_b_after_root_a_moved(user_db, x, ids)

    result = user_db.move_subjects_into_axis([ids["RootB"]], x)

    assert result["success"] is True, result
    assert _axis_of(user_db, ids["RootB"]) == x


def test_the_listing_names_the_axis_a_bound_root_can_go_into(user_db, shared):
    exam, x, y, ids = shared
    _strand_root_b_after_root_a_moved(user_db, x, ids)

    rows = {r["name"]: r for r in user_db.get_subjects_outside_any_axis(exam.id)}

    assert rows["RootB"]["linked_axes"] == [{"axis_id": x, "name": "AxisX"}]
    assert rows["Lone"]["linked_axes"] == []


def test_a_subject_whose_parent_is_in_another_axis_is_refused(user_db, shared):
    """The other direction of the same edge: a parent already in AxisX binds
    its stranded child to AxisX."""
    exam, x, y, ids = shared
    parent = _subject(user_db, "Filed parent", dimension_id=x)
    user_db.add_edge(parent, ids["Lone"], is_primary=True)
    user_db.conn.commit()

    result = user_db.move_subjects_into_axis([ids["Lone"]], y)

    assert result["success"] is False, result
    assert '"Filed parent"' in result["error"] and '"AxisX"' in result["error"]
    assert _axis_of(user_db, ids["Lone"]) is None


def test_a_root_linked_to_two_axes_has_no_axis_to_go_into(user_db, shared):
    exam, x, y, ids = shared
    in_y = _subject(user_db, "Held in Y", dimension_id=y)
    in_x = _subject(user_db, "Held in X", dimension_id=x)
    user_db.add_edge(ids["Lone"], in_y, is_primary=False)
    user_db.add_edge(ids["Lone"], in_x, is_primary=False)
    user_db.conn.commit()

    result = user_db.move_subjects_into_axis([ids["Lone"]], x)

    assert result["success"] is False, result
    assert "no axis can take it" in result["error"], result["error"]


# ---------------------------------------------------------------- #904

@pytest.fixture
def clash(user_db):
    """#904's repro: Held in X (AxisX) and Stranded share import_id dup-1."""
    exam = user_db.create_exam_context(exam_name=EXAM, exam_description="#904")
    x = user_db.create_dimension(exam_id=exam.id, name="AxisX", display_order=1)
    held = _subject(user_db, "Held in X", import_id="dup-1", dimension_id=x)
    stranded = _subject(user_db, "Stranded", import_id="dup-1")
    return exam, x, held, stranded


def test_an_import_id_clash_is_refused_with_a_sentence(user_db, clash):
    exam, x, held, stranded = clash

    result = user_db.move_subjects_into_axis([stranded], x)

    assert result["success"] is False, result
    assert result["error"] == (
        '"Stranded" cannot move into "AxisX": a subject there already '
        "carries the same import id."), result["error"]
    assert "UNIQUE" not in result["error"]
    assert _axis_of(user_db, stranded) is None, "the refused move wrote"


def test_a_clash_deep_in_the_subtree_moves_nothing(user_db, clash):
    """One transaction: the clean root above the clashing child stays too."""
    exam, x, held, stranded = clash
    top = _subject(user_db, "Clean parent")
    user_db.add_edge(top, stranded, is_primary=True)
    user_db.conn.commit()

    result = user_db.move_subjects_into_axis([top], x)

    assert result["success"] is False
    assert '"Stranded"' in result["error"] and '"AxisX"' in result["error"]
    assert _axis_of(user_db, top) is None and _axis_of(user_db, stranded) is None


def test_without_a_clash_the_same_move_works(user_db, clash):
    """Control: a different import id moves."""
    exam, x, held, stranded = clash
    user_db.execute("UPDATE subject_nodes SET import_id = 'dup-2' WHERE id = ?",
                    (stranded,))
    user_db.conn.commit()

    result = user_db.move_subjects_into_axis([stranded], x)

    assert result["success"] is True, result
    assert _axis_of(user_db, stranded) == x


def test_the_first_axis_helper_and_the_panel_share_the_clash_sentence(user_db):
    """One sentence, two callers: the helper's text is the panel's text."""
    assert user_db._import_id_clash_sentence("Stranded", "AxisX") == (
        '"Stranded" cannot move into "AxisX": a subject there already '
        "carries the same import id.")
