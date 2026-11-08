"""The difficulty and time card's data, one rule per test (#898 Wave 0).

``AdvancedAnalyticsMixin.get_difficulty_time_quadrants`` places every mistake
in scope by its rating and its time spent. The rules are the *Data rules* of
``docs/planning/DIFFICULTY_TIME_CARD_PLAN.md``, decided on #898:

* hard is rated 4-5, easy 1-2, 3 a middle band in no quadrant;
* *timed* is ``time_spent_seconds > 0``;
* the median is over every timed mistake of the exam, ignoring the picker
  and the subject; fast is ``t < m`` and slow ``t >= m``;
* under 10 timed mistakes there are no quadrants, only ``unsplit``;
* every mistake is in exactly one bucket, and the method checks the sum.

One test per rule rather than one per fixture, for the same reason
``test_draft_policy_by_surface.py`` gives: a consolidated assertion names
the fixture that broke, not the rule. Do not merge them.
"""
from __future__ import annotations

import random
from datetime import date

import pytest

from database.exceptions import ValidationError
from database.user_db import UserDatabase
import database.domains.analytics_advanced as aa

pytestmark = pytest.mark.database


class Exam:
    """One exam with a polyhierarchy, a session and an entry factory.

    ``Systems`` and ``Disciplines`` are roots. ``Shared`` sits under both
    (primary under Systems), and ``Leaf`` under Shared. ``Other`` is a
    second child of Systems.
    """

    def __init__(self, db: UserDatabase, name: str):
        self.db = db
        self.exam = db.create_exam_context(
            exam_name=name, exam_description="#898",
            hierarchy_levels=["System", "Topic", "Subtopic"])
        self.id = self.exam.id
        self.name = self.exam.exam_name
        mk = lambda n, lvl, parent=None: db.create_subject_node(
            exam_context=self.name, name=f"{name} {n}", level_type=lvl,
            parent_id=parent)
        self.systems = mk("Systems", "System")
        self.disciplines = mk("Disciplines", "System")
        self.shared = mk("Shared", "Topic", self.systems.id)
        db.add_edge(self.disciplines.id, self.shared.id)
        self.leaf = mk("Leaf", "Subtopic", self.shared.id)
        self.other = mk("Other", "Topic", self.systems.id)
        self.session = db.create_review_session(
            exam_context_id=self.id, total_questions=50, total_incorrect=50,
            session_name=f"{name} session", date_encountered=date.today())

    def add(self, d=None, t=None, *, subject=None, secondary=None,
            tags=None, draft=False, parent=None):
        subject = subject if subject is not None else self.other
        entry = self.db.create_question_entry(
            review_session_id=self.session.id,
            user_answer="A", correct_answer="B",
            perceived_difficulty=d, time_spent_seconds=t,
            reflection=None if draft else "I rushed.",
            explanation="Because.",
            primary_subject_ids=[subject.id] if subject else [],
            secondary_subject_ids=[s.id for s in (secondary or [])],
            tag_ids=list(tags or []))
        assert bool(entry.is_draft) == draft, "fixture made the wrong kind"
        if parent is not None:
            self.db.execute(
                "UPDATE entry_subject_mappings SET primary_parent_id = ? "
                "WHERE question_entry_id = ? AND mapping_type = 'primary'",
                (parent.id, entry.id))
            self.db.conn.commit()
        return entry.id

    def tag(self, name):
        return self.db.create_tag(self.name, f"{self.name} {name}").id

    def quadrants(self, **kw):
        return self.db.get_difficulty_time_quadrants(self.id, **kw)


@pytest.fixture
def db(tmp_path):
    database = UserDatabase(tmp_path / "dt.db", user_id=1, username="dt")
    yield database
    database.close()


@pytest.fixture
def exam(db):
    return Exam(db, "DT")


def bucket_of(payload, entry_id):
    return next(e["bucket"] for e in payload["entries"] if e["id"] == entry_id)


def boundary_fixture(exam):
    """Median exactly 100: 11 unrated entries at 100 s, then d in {2,3,4}
    at 99, 100 and 101 s. 20 timed, the middle two both 100."""
    for _ in range(11):
        exam.add(None, 100)
    return {(d, t): exam.add(d, t) for d in (2, 3, 4) for t in (99, 100, 101)}


# ========================================================== the buckets


def test_rated_4_is_hard_and_rated_2_is_easy(exam):
    ids = boundary_fixture(exam)
    p = exam.quadrants()
    assert p["median"]["value_seconds"] == 100
    assert bucket_of(p, ids[(4, 101)]) == "hard_slow"
    assert bucket_of(p, ids[(2, 101)]) == "easy_slow"


def test_rated_3_is_the_middle_band_at_every_time(exam):
    ids = boundary_fixture(exam)
    p = exam.quadrants()
    assert [bucket_of(p, ids[(3, t)]) for t in (99, 100, 101)] == ["middle"] * 3
    assert p["buckets"]["middle"]["count"] == 3


def test_one_second_under_the_median_is_fast(exam):
    ids = boundary_fixture(exam)
    p = exam.quadrants()
    assert bucket_of(p, ids[(4, 99)]) == "hard_fast"
    assert bucket_of(p, ids[(2, 99)]) == "easy_fast"


def test_the_median_entry_goes_slow(exam):
    ids = boundary_fixture(exam)
    p = exam.quadrants()
    assert bucket_of(p, ids[(4, 100)]) == "hard_slow"
    assert bucket_of(p, ids[(2, 100)]) == "easy_slow"
    assert p["buckets"]["hard_fast"]["count"] == 1
    assert p["buckets"]["hard_slow"]["count"] == 2


def test_even_n_gives_a_half_second_median_and_the_label_entry_is_slow(exam):
    for _ in range(5):
        exam.add(None, 100)
    for _ in range(4):
        exam.add(None, 101)
    at_label = exam.add(4, 101)          # 10 timed: five 100s, five 101s
    p = exam.quadrants()
    assert p["median"]["value_seconds"] == 100.5
    assert p["median"]["label_seconds"] == 101
    assert bucket_of(p, at_label) == "hard_slow"


def test_all_times_equal_leaves_fast_empty(exam):
    for d in (1, 2, 4, 5, 4, 5, 1, 2, 4, 5):
        exam.add(d, 60)
    p = exam.quadrants()
    assert p["median"]["all_equal"] is True
    assert p["buckets"]["hard_fast"]["count"] == 0
    assert p["buckets"]["easy_fast"]["count"] == 0
    assert p["buckets"]["hard_slow"]["count"] == 6


def test_unequal_times_are_not_all_equal(exam):
    for i in range(10):
        exam.add(4, 60 + i)
    assert exam.quadrants()["median"]["all_equal"] is False


# ====================================================== too few to split


def test_nine_timed_mistakes_do_not_split(exam):
    for d in (1, 2, 4, 5, 4, 5, 1, 2, 3):
        exam.add(d, 90)
    p = exam.quadrants()
    assert p["median"]["available"] is False
    assert p["median"]["value_seconds"] is None
    assert all(p["buckets"][q] is None
               for q in ("hard_fast", "hard_slow", "easy_fast", "easy_slow"))
    assert p["unsplit"]["count"] == 8
    assert p["buckets"]["middle"]["count"] == 1


def test_ten_timed_mistakes_do_split(exam):
    for d in (1, 2, 4, 5, 4, 5, 1, 2, 3, 3):
        exam.add(d, 90)
    p = exam.quadrants()
    assert p["median"]["available"] is True
    assert p["unsplit"] is None
    assert p["buckets"]["hard_slow"]["count"] == 4


# ================================================================ timed


def test_zero_and_null_times_are_untimed(exam):
    zero = exam.add(4, 0)
    null = exam.add(4, None)
    p = exam.quadrants()
    assert p["median"]["timed_count"] == 0
    assert bucket_of(p, zero) == bucket_of(p, null) == "not_placed"
    assert p["not_placed_detail"]["no_time_only"] == 2


def test_rated_3_with_no_time_is_not_placed(exam):
    entry = exam.add(3, None)
    p = exam.quadrants()
    assert bucket_of(p, entry) == "not_placed"
    assert p["buckets"]["middle"]["count"] == 0


def test_no_rating_and_no_time_are_told_apart(exam):
    exam.add(None, None)
    exam.add(None, 30)
    exam.add(5, None)
    assert exam.quadrants()["not_placed_detail"] == {
        "no_rating_no_time": 1, "no_rating_only": 1, "no_time_only": 1}


def test_unrated_timed_mistakes_count_toward_the_median(exam):
    for _ in range(9):
        exam.add(4, 10)
    p_before = exam.quadrants()
    assert p_before["median"]["available"] is False
    exam.add(None, 10)                       # the tenth timed one
    p_after = exam.quadrants()
    assert p_after["median"]["timed_count"] == 10
    assert p_after["median"]["available"] is True


def test_placed_counts_the_quadrants_and_not_the_middle_band(exam):
    """The mockup's "92 of 133 placed" with 27 rated 3 and 14 not placed:
    placed is the quadrants alone, the denominator of each share."""
    ids = boundary_fixture(exam)
    exam.add(4, None)
    p = exam.quadrants()
    assert p["total"] == 21
    assert p["buckets"]["middle"]["count"] == 3
    assert p["placed"] == 6      # the six quadrant entries; not the three middle
    assert (p["placed"] + p["buckets"]["middle"]["count"]
            + p["buckets"]["not_placed"]["count"]) == p["total"]


def test_placed_is_the_unsplit_count_below_the_minimum(exam):
    for _ in range(5):
        exam.add(4, 100)
    exam.add(3, 100)
    p = exam.quadrants()
    assert p["median"]["available"] is False
    assert p["placed"] == p["unsplit"]["count"] == 5


# =============================================================== drafts


def test_a_draft_is_placed_in_a_bucket(exam):
    for _ in range(10):
        exam.add(None, 100)
    draft = exam.add(5, 300, draft=True)
    p = exam.quadrants()
    assert bucket_of(p, draft) == "hard_slow"
    assert next(e for e in p["entries"] if e["id"] == draft)["is_draft"] is True


def test_a_draft_moves_the_median(exam):
    for t in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        exam.add(None, t)
    before = exam.quadrants()["median"]["value_seconds"]
    exam.add(None, 1000, draft=True)
    after = exam.quadrants()["median"]["value_seconds"]
    assert (before, after) == (55, 60)


# ================================================= median is exam-wide


def test_the_median_ignores_the_picker(exam):
    tag = exam.tag("Rushed")
    for t in range(10, 110, 10):
        exam.add(4, t, tags=[tag] if t < 50 else [])
    whole = exam.quadrants()["median"]
    picked = exam.quadrants(tag_ids=[tag])["median"]
    assert picked == whole


def test_the_median_ignores_the_subject(exam):
    for t in range(10, 110, 10):
        exam.add(4, t, subject=exam.leaf if t < 30 else exam.other)
    whole = exam.quadrants()["median"]
    subject = exam.quadrants(subject_id=exam.leaf.id)
    assert subject["total"] == 2
    assert subject["median"] == whole


# =========================================================== accounting


def test_the_buckets_account_for_every_mistake_on_a_random_fixture(exam):
    rng = random.Random(898)
    tags = [exam.tag(f"T{i}") for i in range(3)]
    subjects = [exam.systems, exam.shared, exam.leaf, exam.other]
    for _ in range(120):
        exam.add(rng.choice([None, 1, 2, 3, 4, 5]),
                 rng.choice([None, 0, rng.randint(1, 600)]),
                 subject=rng.choice(subjects),
                 tags=rng.sample(tags, rng.randint(0, 2)),
                 draft=rng.random() < 0.2)
    for kw in ({}, {"subject_id": exam.systems.id},
               {"tag_ids": tags[:2], "match": "all"}):
        p = exam.quadrants(**kw)
        b = p["buckets"]
        split = sum(b[q]["count"] for q in
                    ("hard_fast", "hard_slow", "easy_fast", "easy_slow"))
        assert split + b["middle"]["count"] + b["not_placed"]["count"] == p["total"]
        assert len(p["entries"]) == p["total"]
    assert exam.quadrants()["total"] == 120


def test_the_accounting_check_runs_and_fails_when_a_mistake_is_lost(
        exam, monkeypatch):
    """The mutation check. Make one entry fall into no bucket, and the
    method must refuse rather than return a smaller card."""
    for t in range(10, 110, 10):
        exam.add(4, t)
    real = aa._dt_bucket
    lost = {"n": 0}

    def leaky(d, t, m):
        lost["n"] += 1
        return "nowhere" if lost["n"] == 1 else real(d, t, m)

    monkeypatch.setattr(aa, "_dt_bucket", leaky)
    with pytest.raises(AssertionError, match="accounting broken"):
        exam.quadrants()
    monkeypatch.setattr(aa, "_dt_bucket", real)
    assert exam.quadrants()["total"] == 10       # the control


# ========================================================== error types


def test_a_mistake_with_two_types_counts_under_both(exam):
    a, b = exam.tag("A"), exam.tag("B")
    for _ in range(10):
        exam.add(None, 100)
    exam.add(4, 200, tags=[a, b])
    hard_slow = exam.quadrants()["buckets"]["hard_slow"]
    assert hard_slow["count"] == 1
    assert {t["tag_id"]: t["count"] for t in hard_slow["top_types"]} == {a: 1, b: 1}


def test_match_any_counts_an_entry_carrying_one_picked_type(exam):
    a, b, c = exam.tag("A"), exam.tag("B"), exam.tag("C")
    for _ in range(10):
        exam.add(None, 100)
    exam.add(4, 200, tags=[a])
    exam.add(4, 200, tags=[a, b])
    exam.add(4, 200, tags=[c])
    m = exam.quadrants(tag_ids=[a, b], match="any")["buckets"]["hard_slow"]["match"]
    assert m["count"] == 2
    assert m["per_type"] == [{"tag_id": a, "count": 2}, {"tag_id": b, "count": 1}]


def test_match_all_counts_an_entry_carrying_every_picked_type(exam):
    a, b = exam.tag("A"), exam.tag("B")
    for _ in range(10):
        exam.add(None, 100)
    exam.add(4, 200, tags=[a])
    both = exam.add(4, 200, tags=[a, b])
    p = exam.quadrants(tag_ids=[a, b], match="all")
    assert p["buckets"]["hard_slow"]["match"]["count"] == 1
    assert [e["id"] for e in p["entries"] if e["matches"]] == [both]


def test_untagged_matches_mistakes_with_no_type(exam):
    a = exam.tag("A")
    for _ in range(10):
        exam.add(None, 100, tags=[a])
    bare = exam.add(4, 200)
    exam.add(4, 200, tags=[a])
    p = exam.quadrants(untagged=True)
    assert p["buckets"]["hard_slow"]["match"] == {"count": 1, "per_type": []}
    assert p["buckets"]["hard_slow"]["untagged"] == 1
    assert p["untagged_count"] == 1
    assert [e["id"] for e in p["entries"] if e["matches"]] == [bare]


def test_with_nothing_picked_there_is_no_match_and_no_hits(exam):
    exam.add(4, 200, tags=[exam.tag("A")])
    p = exam.quadrants()
    assert all(e["matches"] is None and e["picked_hits"] == []
               for e in p["entries"])
    assert p["buckets"]["middle"]["match"] is None


def test_picked_hits_follow_the_pick_order(exam):
    a, b = exam.tag("A"), exam.tag("B")
    entry = exam.add(4, 200, tags=[a, b])
    p = exam.quadrants(tag_ids=[b, a])
    assert next(e for e in p["entries"] if e["id"] == entry)["picked_hits"] == [b, a]


def test_top_three_types_break_ties_by_name(exam):
    names = ["Delta", "Alpha", "Charlie", "Bravo"]
    ids = {n: exam.tag(n) for n in names}
    for _ in range(10):
        exam.add(None, 100)
    for n in names:
        exam.add(4, 200, tags=[ids[n]])
        exam.add(4, 200, tags=[ids[n]])
    hard_slow = exam.quadrants()["buckets"]["hard_slow"]
    assert [t["name"] for t in hard_slow["top_types"]] == [
        "DT Alpha", "DT Bravo", "DT Charlie"]
    assert hard_slow["more_types"] == 1


def test_top_three_ranks_by_count_before_name(exam):
    z, a = exam.tag("Zulu"), exam.tag("Alpha")
    exam.add(4, None, tags=[z])
    exam.add(4, None, tags=[z])
    exam.add(4, None, tags=[a])
    top = exam.quadrants()["buckets"]["not_placed"]["top_types"]
    assert [t["tag_id"] for t in top] == [z, a]


def test_a_type_removed_from_the_exam_is_still_listed_and_marked(exam):
    gone = exam.tag("Gone")
    exam.add(4, 200, tags=[gone])
    exam.db.remove_tag_from_exam(exam.name, gone)
    types = {t["tag_id"]: t for t in exam.quadrants()["types"]}
    assert gone in types
    assert types[gone]["listed_on_exam"] is False
    assert types[gone]["count"] == 1


def test_a_listed_type_no_mistake_carries_is_absent(exam):
    used, unused = exam.tag("Used"), exam.tag("Unused")
    exam.add(4, 200, tags=[used])
    types = {t["tag_id"]: t for t in exam.quadrants()["types"]}
    assert types[used]["listed_on_exam"] is True
    assert unused not in types


def test_the_type_list_carries_its_group(exam):
    group = exam.db.create_tag_group(exam.name, "DT Group")
    typed = exam.db.create_hierarchical_tag(exam.name, "DT In group", group.id).id
    exam.add(4, 200, tags=[typed])
    (row,) = exam.quadrants()["types"]
    assert (row["group_id"], row["group_name"]) == (group.id, "DT Group")


# ================================================================ scope


def test_another_exams_mistakes_are_excluded(db, exam):
    other = Exam(db, "Elsewhere")
    for _ in range(12):
        other.add(4, 50)
    exam.add(4, 50)
    p = exam.quadrants()
    assert p["total"] == 1
    assert p["median"]["timed_count"] == 1


def test_the_deep_dive_excludes_a_secondary_only_mistake(exam):
    exam.add(4, 50, subject=exam.other, secondary=[exam.leaf])
    p = exam.quadrants(subject_id=exam.leaf.id)
    assert p["total"] == 0
    assert exam.quadrants()["total"] == 1     # the control: it exists


def test_the_deep_dive_includes_a_primary_descendant(exam):
    entry = exam.add(4, 50, subject=exam.leaf)
    p = exam.quadrants(subject_id=exam.systems.id)
    assert [e["id"] for e in p["entries"]] == [entry]
    assert p["scope"]["counting"] == "primary_subject_subtree"


def polyhierarchy_fixture(exam):
    """Entries that each deep-dive reading treats differently."""
    exam.add(4, 50, subject=exam.shared)                           # NULL context
    exam.add(2, 70, subject=exam.shared, parent=exam.systems)
    exam.add(4, 80, subject=exam.shared, parent=exam.systems)
    exam.add(5, 90, subject=exam.shared, parent=exam.disciplines)
    exam.add(3, 20, subject=exam.leaf)
    exam.add(None, None, subject=exam.leaf, parent=exam.shared)
    exam.add(1, 40, subject=exam.systems)
    exam.add(4, 60, subject=exam.other, secondary=[exam.shared])   # secondary only
    exam.add(4, 30, subject=exam.other, draft=True)
    exam.add(2, 10, subject=None, draft=True)                      # no subject


@pytest.mark.parametrize("subject,parent", [
    ("shared", None), ("leaf", None), ("systems", None),
    ("disciplines", None), ("other", None),
])
def test_deep_dive_parity_without_a_parent_context(exam, subject, parent):
    polyhierarchy_fixture(exam)
    node = getattr(exam, subject)
    page = exam.db.get_subject_deep_dive(node.id, exam_context_id=exam.id)
    card = exam.quadrants(subject_id=node.id)
    assert card["total"] == page["total_mistakes"]


@pytest.mark.parametrize("subject,parent", [
    ("shared", "systems"), ("shared", "disciplines"), ("leaf", "shared"),
    ("leaf", "systems"), ("leaf", "disciplines"),
])
def test_deep_dive_parity_with_a_parent_context(exam, subject, parent):
    polyhierarchy_fixture(exam)
    node, ctx = getattr(exam, subject), getattr(exam, parent)
    page = exam.db.get_subject_deep_dive(
        node.id, exam_context_id=exam.id, primary_parent_id=ctx.id)
    card = exam.quadrants(subject_id=node.id, primary_parent_id=ctx.id)
    assert card["total"] == page["total_mistakes"]


def test_the_parity_fixture_discriminates_the_parent_context(exam):
    """The control for the two parity tests: the contexts must actually give
    different totals, or parity would hold for a helper ignoring them."""
    polyhierarchy_fixture(exam)
    totals = {
        ctx: exam.quadrants(subject_id=exam.shared.id,
                            primary_parent_id=getattr(exam, ctx).id
                            if ctx else None)["total"]
        for ctx in (None, "systems", "disciplines")}
    assert len(set(totals.values())) == 3, totals


# =========================================================== the payload


def test_the_payload_has_the_planned_shape(exam):
    exam.add(4, 50, tags=[exam.tag("A")])
    p = exam.quadrants()
    assert set(p) == {"scope", "total", "placed", "unsplit", "median",
                      "buckets", "not_placed_detail", "selection", "types",
                      "untagged_count", "entries", "axis"}
    assert set(p["median"]) == {"population", "timed_count", "value_seconds",
                                "label_seconds", "available", "min_timed",
                                "all_equal"}
    assert set(p["buckets"]["not_placed"]) == {
        "count", "untagged", "top_types", "more_types", "match"}
    assert set(p["entries"][0]) == {
        "id", "d", "t", "bucket", "is_draft", "session_name", "question_id",
        "subjects", "tag_ids", "matches", "picked_hits"}
    assert set(p["types"][0]) == {"tag_id", "name", "description", "group_id",
                                  "group_name", "count", "listed_on_exam"}
    assert p["scope"]["counting"] == "every_mistake"
    assert p["median"]["min_timed"] == aa.DT_MIN_TIMED == 10


def test_the_axis_stops_at_the_95th_percentile_rounded_up_to_a_minute(exam):
    for t in list(range(10, 200, 10)) + [3600]:      # 20 drawn, one outlier
        exam.add(4, t)
    axis = exam.quadrants()["axis"]
    assert axis == {"x_max_seconds": 240, "clipped_count": 1}


def test_the_constants_are_the_decided_ones():
    assert (aa.DT_HARD, aa.DT_EASY, aa.DT_MIDDLE) == ((4, 5), (1, 2), 3)
    assert (aa.DT_MIN_TIMED, aa.DT_TOP_TYPES) == (10, 3)


# =========================================================== refusals


def test_no_exam_is_refused(db):
    with pytest.raises(ValidationError):
        db.get_difficulty_time_quadrants(None)
    with pytest.raises(ValidationError):
        db.get_difficulty_time_quadrants(99999)


def test_untagged_with_picked_types_is_refused(exam):
    with pytest.raises(ValidationError):
        exam.quadrants(tag_ids=[exam.tag("A")], untagged=True)


def test_an_unknown_match_mode_is_refused(exam):
    with pytest.raises(ValidationError):
        exam.quadrants(match="some")


def test_a_parent_context_without_a_subject_is_refused(exam):
    with pytest.raises(ValidationError):
        exam.quadrants(primary_parent_id=exam.systems.id)


def test_a_non_integer_tag_id_is_refused(exam):
    with pytest.raises(ValidationError):
        exam.quadrants(tag_ids=["1"])


def test_the_method_writes_nothing(exam):
    exam.add(4, 50)
    before = exam.db.conn.total_changes
    exam.quadrants()
    assert exam.db.conn.total_changes == before
