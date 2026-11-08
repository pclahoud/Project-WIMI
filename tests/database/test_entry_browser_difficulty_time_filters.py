"""The entry browser's #898 filters, one rule per test, each with controls.

``get_entries_paginated`` gains ``difficulty_levels``, ``time_min_seconds``
(inclusive), ``time_max_seconds`` (exclusive), ``missing_any``,
``tag_mode``, ``untagged`` and ``counted_subject_id`` / ``counted_parent_id``
so the difficulty and time card can land on exactly the entries it counts
(``docs/planning/DIFFICULTY_TIME_CARD_PLAN.md``, Wave 1). *Rated* and
*timed* must read as the card's ``_dt_is_rated`` / ``_dt_is_timed`` do, so
several tests here plant the values those two treat specially: a stored 0,
a REAL 4.0 rating, a time stored as text.

Every positive assertion has a control that the same fixture would fail if
the condition were missing or inverted. The landing parity across buckets
is ``test_entry_browser_lands_on_the_card.py``.
"""
from __future__ import annotations

import pytest

from database.exceptions import ValidationError
from database.user_db import UserDatabase
from tests.database.test_difficulty_time_quadrants import Exam

pytestmark = pytest.mark.database


@pytest.fixture
def db(tmp_path):
    database = UserDatabase(tmp_path / "browse.db", user_id=1, username="b")
    yield database
    database.close()


@pytest.fixture
def exam(db):
    return Exam(db, "BR")


def found(exam, **kw):
    entries, total = exam.db.get_entries_paginated(
        exam_context_id=exam.id, per_page=500, **kw)
    ids = {e.id for e in entries}
    assert len(ids) == total, "the total and the page disagree"
    return ids


def raw(db, entry_id, column, value):
    db.execute(f"UPDATE question_entries SET {column} = ? WHERE id = ?",
               (value, entry_id))
    db.conn.commit()


def typeof(db, entry_id, column):
    return db.fetchone(
        f"SELECT typeof({column}) AS ty FROM question_entries WHERE id = ?",
        (entry_id,))["ty"]


# ============================================================ difficulty


def test_difficulty_levels_match_only_those_ratings(exam):
    by_d = {d: exam.add(d, 60) for d in (1, 2, 3, 4, 5)}
    unrated = exam.add(None, 60)
    assert found(exam, difficulty_levels=[4, 5]) == {by_d[4], by_d[5]}
    # Control: the unfiltered page has every one of them.
    assert found(exam) == set(by_d.values()) | {unrated}


def test_a_real_rating_is_not_rated_as_the_card_reads_it(exam):
    """``_dt_is_rated`` wants an int; a REAL 4.5 is no rating to the card.

    (A REAL 4.0 cannot be planted: the column's INTEGER affinity stores it
    as 4. 4.5 is the value affinity keeps as REAL.)"""
    real = exam.add(4, 60)
    raw(exam.db, real, "perceived_difficulty", 4.5)
    assert typeof(exam.db, real, "perceived_difficulty") == "real"
    int_four = exam.add(4, 60)
    assert found(exam, difficulty_levels=[4]) == {int_four}
    assert real in found(exam, missing_any=["difficulty"])
    assert exam.quadrants()["entries"][0]["bucket"] == "not_placed"


def test_a_difficulty_outside_one_to_five_is_refused(exam):
    for bad in (0, 6, "4", True, 4.0):
        with pytest.raises(ValidationError):
            found(exam, difficulty_levels=[bad])


# ================================================================== time


def test_time_min_is_inclusive_and_implies_timed(exam):
    t = {s: exam.add(3, s) for s in (99, 100, 101)}
    zero, untimed = exam.add(3, 0), exam.add(3, None)
    assert found(exam, time_min_seconds=100) == {t[100], t[101]}
    # time_min 0 is "timed, any time": the 0 and the NULL stay out.
    assert found(exam, time_min_seconds=0) == set(t.values())
    assert {zero, untimed} <= found(exam)


def test_time_max_is_exclusive_and_implies_timed(exam):
    t = {s: exam.add(3, s) for s in (99, 100, 101)}
    zero, untimed = exam.add(3, 0), exam.add(3, None)
    assert found(exam, time_max_seconds=100) == {t[99]}
    assert zero not in found(exam, time_max_seconds=1000)
    assert untimed not in found(exam, time_max_seconds=1000)
    assert {zero, untimed} <= found(exam)


def test_a_half_second_bound_splits_whole_seconds(exam):
    """The card's median can end in .5 and the link carries it unrounded."""
    t94, t95 = exam.add(4, 94), exam.add(4, 95)
    assert found(exam, time_max_seconds=94.5) == {t94}
    assert found(exam, time_min_seconds=94.5) == {t95}


def test_both_bounds_together_are_a_band(exam):
    t = {s: exam.add(2, s) for s in (10, 20, 30)}
    assert found(exam, time_min_seconds=20, time_max_seconds=30) == {t[20]}


def test_a_time_stored_as_text_is_not_timed(exam):
    as_text = exam.add(4, 60)
    raw(exam.db, as_text, "time_spent_seconds", "sixty")
    assert typeof(exam.db, as_text, "time_spent_seconds") == "text"
    assert as_text not in found(exam, time_min_seconds=0)
    assert as_text in found(exam, missing_any=["time"])
    assert exam.quadrants()["entries"][0]["bucket"] == "not_placed"


def test_a_non_numeric_time_bound_is_refused(exam):
    for bad in ("60", True, float("nan")):
        with pytest.raises(ValidationError):
            found(exam, time_min_seconds=bad)
        with pytest.raises(ValidationError):
            found(exam, time_max_seconds=bad)


# =============================================================== missing


def test_missing_time_means_null_or_zero(exam):
    timed, zero, untimed = exam.add(4, 30), exam.add(4, 0), exam.add(4, None)
    assert found(exam, missing_any=["time"]) == {zero, untimed}
    assert timed in found(exam)


def test_missing_difficulty_counts_a_rating_off_the_integer_scale(exam):
    """The column's CHECK keeps 1-5, so the off-scale value a stored
    database can hold is a non-integer one, which the card treats as no
    rating."""
    rated, unrated, off = exam.add(2, 30), exam.add(None, 30), exam.add(2, 30)
    raw(exam.db, off, "perceived_difficulty", 2.5)
    assert found(exam, missing_any=["difficulty"]) == {unrated, off}
    assert rated in found(exam)


def test_missing_both_means_missing_either(exam):
    """The not-placed bucket: no rating OR no time."""
    full = exam.add(4, 30)
    no_d, no_t, neither = exam.add(None, 30), exam.add(4, None), exam.add()
    assert found(exam, missing_any=["difficulty", "time"]) == {
        no_d, no_t, neither}
    assert full in found(exam)


def test_an_unknown_missing_value_is_refused(exam):
    with pytest.raises(ValidationError):
        found(exam, missing_any=["subject"])


# ============================================================ error types


def test_tag_mode_all_needs_every_type(exam):
    a, b = exam.tag("A"), exam.tag("B")
    both, only_a, only_b = (exam.add(tags=[a, b]), exam.add(tags=[a]),
                            exam.add(tags=[b]))
    assert found(exam, tag_ids=[a, b], tag_mode="all") == {both}
    # Control: any, the default and the old behaviour, takes all three.
    assert found(exam, tag_ids=[a, b]) == {both, only_a, only_b}
    assert found(exam, tag_ids=[a, b], tag_mode="any") == {both, only_a, only_b}


def test_an_unknown_tag_mode_is_refused(exam):
    with pytest.raises(ValidationError):
        found(exam, tag_ids=[1], tag_mode="some")


def test_untagged_finds_entries_carrying_no_type(exam):
    a = exam.tag("A")
    tagged, bare = exam.add(tags=[a]), exam.add()
    assert found(exam, untagged=True) == {bare}
    assert tagged in found(exam)


def test_a_group_row_is_not_an_error_type(exam):
    """``tags_by_entry`` in the card skips groups, so an entry carrying only
    a group row is untagged to the card and must be here."""
    group = exam.db.create_tag_group(exam.name, "BR Group")
    only_group = exam.add()
    exam.db.execute("INSERT INTO entry_tags (question_entry_id, tag_id) "
                    "VALUES (?, ?)", (only_group, group.id))
    exam.db.conn.commit()
    with_type = exam.add(tags=[exam.tag("Real")])
    assert only_group in found(exam, untagged=True)
    assert with_type not in found(exam, untagged=True)
    assert exam.quadrants()["untagged_count"] == 1


def test_untagged_with_picked_types_is_refused(exam):
    with pytest.raises(ValidationError):
        found(exam, untagged=True, tag_ids=[exam.tag("A")])


# ======================================================= counted subject


def test_counted_subject_is_primary_only_and_takes_the_subtree(exam):
    in_leaf = exam.add(subject=exam.leaf)
    secondary_only = exam.add(subject=exam.other, secondary=[exam.shared])
    elsewhere = exam.add(subject=exam.other)
    assert found(exam, counted_subject_id=exam.shared.id) == {in_leaf}
    # Control: the finding-rule subject filter does take the secondary tag,
    # which is exactly why the card cannot link through it.
    assert secondary_only in found(
        exam, subject_ids=[exam.shared.id], include_child_subjects=True)
    assert elsewhere not in found(exam, counted_subject_id=exam.shared.id)


def test_counted_parent_narrows_to_that_parent_context(exam):
    via_disciplines = exam.add(subject=exam.shared, parent=exam.disciplines)
    via_systems = exam.add(subject=exam.shared, parent=exam.systems)
    no_context = exam.add(subject=exam.shared)
    assert found(exam, counted_subject_id=exam.shared.id,
                 counted_parent_id=exam.disciplines.id) == {
        via_disciplines, no_context}
    assert found(exam, counted_subject_id=exam.shared.id) == {
        via_disciplines, via_systems, no_context}


def test_counted_subject_matches_the_card_population(exam):
    """Same helper as the card, so the same set, with and without a parent."""
    exam.add(subject=exam.leaf)
    exam.add(subject=exam.shared, parent=exam.systems)
    exam.add(subject=exam.shared, parent=exam.disciplines)
    exam.add(subject=exam.other, secondary=[exam.leaf])
    for parent in (None, exam.systems.id, exam.disciplines.id):
        card = {e["id"] for e in exam.quadrants(
            subject_id=exam.shared.id, primary_parent_id=parent)["entries"]}
        assert card, "the control needs a non-empty card"
        assert found(exam, counted_subject_id=exam.shared.id,
                     counted_parent_id=parent) == card


def test_a_parent_without_a_counted_subject_is_refused(exam):
    with pytest.raises(ValidationError):
        found(exam, counted_parent_id=exam.systems.id)


# ============================================================= contracts


def test_drafts_are_found_by_the_new_filters(exam):
    """#12: drafts count everywhere but goals; these filters do not change
    what is_draft means."""
    draft = exam.add(4, 30, draft=True)
    finished = exam.add(4, 30)
    assert found(exam, difficulty_levels=[4]) == {draft, finished}
    assert found(exam, difficulty_levels=[4], is_draft=True) == {draft}


def test_no_new_filter_by_default_changes_nothing(exam):
    ids = {exam.add(), exam.add(4, 30, tags=[exam.tag("A")]),
           exam.add(3, 0)}
    assert found(exam, difficulty_levels=[], missing_any=[],
                 tag_mode="any", untagged=False) == ids


@pytest.mark.parametrize("key", ["time_desc", "time_asc"])
def test_time_sorts_put_no_time_last(exam, key):
    t10, t50, zero, none = (exam.add(3, 10), exam.add(3, 50), exam.add(3, 0),
                            exam.add(3, None))
    entries, _ = exam.db.get_entries_paginated(
        exam_context_id=exam.id, sort_by=key, per_page=10)
    order = [e.id for e in entries]
    timed = [t50, t10] if key == "time_desc" else [t10, t50]
    assert order[:2] == timed
    assert set(order[2:]) == {zero, none}


# ===================================================== error-type listing


def test_error_types_for_filter_lists_a_removed_type_an_entry_carries(exam):
    group = exam.db.create_tag_group(exam.name, "BR Kinds")
    kept = exam.db.create_hierarchical_tag(exam.name, "BR Kept", group.id).id
    removed = exam.db.create_hierarchical_tag(
        exam.name, "BR Removed", group.id).id
    unused_removed = exam.db.create_hierarchical_tag(
        exam.name, "BR Unused", group.id).id
    exam.add(tags=[kept, removed])
    exam.add(tags=[removed])
    exam.db.remove_tag_from_exam(exam.name, removed)
    exam.db.remove_tag_from_exam(exam.name, unused_removed)

    nodes = exam.db.get_error_types_for_filter(exam.id)
    listed_group = next(n for n in nodes if n["id"] == group.id)
    assert listed_group["listed_on_exam"] is True
    assert [c["id"] for c in listed_group["children"]] == [kept]

    extra = [n for n in nodes if n.get("not_listed_group")]
    assert len(extra) == 1 and extra[0]["id"] is None
    assert extra[0]["name"] == "No longer on this exam"
    (carried,) = extra[0]["children"]
    assert carried["id"] == removed
    assert carried["listed_on_exam"] is False
    assert carried["usage_count"] == 2
    assert carried["group_name"] == "BR Kinds"
    # Control: a removed type nobody carries is not offered back.
    every_id = {c["id"] for n in nodes for c in n["children"]}
    assert unused_removed not in every_id
    # And the card counts the removed type, which is why the filter must.
    assert {t["tag_id"] for t in exam.quadrants()["types"]} == {kept, removed}


def test_error_types_for_filter_has_no_extra_group_when_none_is_needed(exam):
    group = exam.db.create_tag_group(exam.name, "BR Kinds")
    t = exam.db.create_hierarchical_tag(exam.name, "BR T", group.id).id
    exam.add(tags=[t])
    nodes = exam.db.get_error_types_for_filter(exam.id)
    assert not [n for n in nodes if n.get("not_listed_group")]
    assert nodes == [
        {**n, "listed_on_exam": True,
         "children": [{**c, "listed_on_exam": True} for c in n["children"]]}
        for n in exam.db.get_tag_hierarchy(exam.name)]


def test_error_types_for_filter_ignores_another_exams_entries(db):
    one, two = Exam(db, "BR1"), Exam(db, "BR2")
    group = db.create_tag_group(one.name, "BR Kinds")
    t = db.create_hierarchical_tag(one.name, "BR Shared", group.id).id
    two.add(tags=[t])          # carried on exam two, listed on exam one only
    assert not [n for n in db.get_error_types_for_filter(one.id)
                if n.get("not_listed_group")]
    extra = [n for n in db.get_error_types_for_filter(two.id)
             if n.get("not_listed_group")]
    assert [c["id"] for c in extra[0]["children"]] == [t]


def test_error_types_for_filter_of_no_such_exam_is_empty(db):
    assert db.get_error_types_for_filter(999) == []
