"""Landing parity: a click on the difficulty and time card opens the entry
browser on exactly the number the card showed (#898 Wave 1).

For every bucket and every picker state (none, one type, several types
matching any, several matching all, *No error type*), on the dashboard scope
and on the deep-dive scope with and without a parent context, the browser's
total for the link the card would send equals the card's count.

The chain is walked the way the page walks it:

1. ``dt_entry_browser_params`` -- the pure helper Wave 2's card will use
   through its JavaScript copy, ``difficulty_time_links.js`` -- turns the
   payload into URL parameters;
2. ``url_to_request`` mirrors ``EntryBrowser.parseUrlParams`` and
   ``filterParams`` in ``entry_browser.js``, turning those parameters into
   the request the page sends (numbers through JSON as JavaScript's
   ``parseFloat`` and ``JSON.stringify`` would leave them);
3. the request goes through the real ``getEntriesPaginated`` bridge slot.

The JavaScript halves of 1 and 2 are exercised in the real engine by
``tests/wimi_test/scenarios/test_entry_browser_filters_by_difficulty_and_time.py``.

The fixture is built to make every rule bite: an even number of timed
mistakes so the median ends in .5, entries at the median itself, stored 0s,
a REAL rating, drafts, a type removed from the exam's list, an entry with a
group row only, secondary-only and parent-context mappings, and a second
exam whose mistakes must count nowhere. Each parity assertion is guarded by
a check that the bucket is not trivially empty in at least one state, so a
fixture that drifted to all zeros cannot pass by agreeing on nothing.
"""
from __future__ import annotations

import json
import random

import pytest

from app.bridge import DatabaseBridge
from database.domains.analytics_advanced import (
    DT_LINK_BUCKETS, dt_entry_browser_params)
from database.user_db import UserDatabase
from tests.database.test_difficulty_time_quadrants import Exam

pytestmark = pytest.mark.database


def url_to_request(params: dict) -> dict:
    """``parseUrlParams`` then ``filterParams``, in Python.

    Kept deliberately literal: each key here is one line in
    ``entry_browser.js``. A number goes through ``float`` and back to
    ``int`` when whole, which is what ``parseFloat`` then ``JSON.stringify``
    then ``json.loads`` produces.
    """
    def number(text):
        value = float(text)
        return int(value) if value.is_integer() else value

    def ints(text):
        return [int(x) for x in text.split(",") if x]

    request = {"exam_context_id": int(params["exam"]), "per_page": 1}
    if "difficulty" in params:
        request["difficulty_levels"] = ints(params["difficulty"])
    if "time_min" in params:
        request["time_min_seconds"] = number(params["time_min"])
    if "time_max" in params:
        request["time_max_seconds"] = number(params["time_max"])
    if "missing" in params:
        request["missing_any"] = params["missing"].split(",")
    if "tags" in params:
        request["tag_ids"] = ints(params["tags"])
        if params.get("tag_mode") == "all":
            request["tag_mode"] = "all"
    if params.get("untagged") in ("1", "true"):
        request["untagged"] = True
    if "counted_subject" in params:
        request["counted_subject_id"] = int(params["counted_subject"])
        if "counted_parent" in params:
            request["counted_parent_id"] = int(params["counted_parent"])
    return request


def browser_total(bridge, params: dict) -> int:
    response = json.loads(bridge.getEntriesPaginated(
        json.dumps(url_to_request(params))))
    assert response["success"], response.get("error")
    return response["data"]["total"]


def card_count(payload: dict, bucket: str) -> int:
    selecting = bool(payload["selection"]["tag_ids"]
                     or payload["selection"]["untagged"])
    if bucket == "total":
        members = payload["entries"]
        if selecting:
            return sum(1 for e in members if e["matches"])
        return len(members)
    summary = (payload["unsplit"] if bucket == "unsplit"
               else payload["buckets"][bucket])
    return summary["match"]["count"] if selecting else summary["count"]


@pytest.fixture
def world(tmp_path):
    db = UserDatabase(tmp_path / "landing.db", user_id=1, username="land")
    exam = Exam(db, "LP")
    group = db.create_tag_group(exam.name, "LP Kinds")
    a = db.create_hierarchical_tag(exam.name, "LP A", group.id).id
    b = db.create_hierarchical_tag(exam.name, "LP B", group.id).id
    c = db.create_hierarchical_tag(exam.name, "LP C", group.id).id
    removed = db.create_hierarchical_tag(exam.name, "LP Removed",
                                         group.id).id

    rng = random.Random(898)
    subjects = [exam.leaf, exam.shared, exam.other, exam.systems,
                exam.disciplines]
    tag_sets = [[], [a], [b], [a, b], [a, b, c], [c], [removed], [a, removed]]
    ratings = [None, 1, 2, 3, 4, 5, 4, 2]
    times = [None, 0, 30, 60, 75, 75, 90, 120, 600, 45]
    for i in range(80):
        subject = rng.choice(subjects)
        parent = None
        if subject is exam.shared and rng.random() < 0.6:
            parent = rng.choice([exam.systems, exam.disciplines])
        secondary = [exam.shared] if rng.random() < 0.15 else []
        exam.add(rng.choice(ratings), rng.choice(times), subject=subject,
                 secondary=secondary, tags=rng.choice(tag_sets),
                 draft=(i % 9 == 0), parent=parent)
    # One with a group row only: untagged to the card.
    group_only = exam.add(4, 75, subject=exam.leaf)
    db.execute("INSERT INTO entry_tags (question_entry_id, tag_id) "
               "VALUES (?, ?)", (group_only, group.id))
    # A REAL rating: no rating to the card.
    real = exam.add(4, 75, subject=exam.leaf)
    db.execute("UPDATE question_entries SET perceived_difficulty = 4.5 "
               "WHERE id = ?", (real,))
    db.conn.commit()
    db.remove_tag_from_exam(exam.name, removed)

    # Another exam, sharing nothing but the profile: must count nowhere.
    elsewhere = Exam(db, "LP Elsewhere")
    for t in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110):
        elsewhere.add(4, t)

    yield {"db": db, "exam": exam, "bridge": DatabaseBridge(user_db=db),
           "a": a, "b": b, "c": c, "removed": removed}
    db.close()


PICKERS = {
    "none": lambda w: {},
    "one type": lambda w: {"tag_ids": [w["a"]]},
    "removed type": lambda w: {"tag_ids": [w["removed"]]},
    "any": lambda w: {"tag_ids": [w["a"], w["b"]], "match": "any"},
    "all": lambda w: {"tag_ids": [w["a"], w["b"]], "match": "all"},
    "untagged": lambda w: {"untagged": True},
}

SCOPES = {
    "dashboard": lambda e: {},
    "deep dive": lambda e: {"subject_id": e.shared.id},
    "deep dive, parent Disciplines": lambda e: {
        "subject_id": e.shared.id, "primary_parent_id": e.disciplines.id},
    "deep dive, parent Systems": lambda e: {
        "subject_id": e.shared.id, "primary_parent_id": e.systems.id},
    "deep dive, a root": lambda e: {"subject_id": e.systems.id},
}


def test_the_fixture_makes_the_rules_bite(world):
    p = world["exam"].quadrants()
    assert p["median"]["available"]
    assert isinstance(p["median"]["value_seconds"], (int, float))
    assert any(e["t"] == p["median"]["value_seconds"]
               for e in p["entries"]), "nobody sits on the median"
    assert any(e["is_draft"] for e in p["entries"])
    assert p["buckets"]["not_placed"]["count"] > 0
    assert p["buckets"]["middle"]["count"] > 0
    assert any(not t["listed_on_exam"] for t in p["types"])


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("picker", PICKERS)
def test_every_bucket_lands_on_the_cards_count(world, scope, picker):
    exam = world["exam"]
    payload = exam.quadrants(**SCOPES[scope](exam), **PICKERS[picker](world))
    assert payload["median"]["available"]
    for bucket in DT_LINK_BUCKETS:
        if bucket == "unsplit":
            continue
        params = dt_entry_browser_params(payload, bucket)
        assert browser_total(world["bridge"], params) == card_count(
            payload, bucket), (
            f"{scope} / {picker} / {bucket}: the link {params} lands on a "
            f"different number from the card's")


@pytest.mark.parametrize("bucket", DT_LINK_BUCKETS)
def test_no_bucket_is_trivially_empty_everywhere(world, bucket):
    """The negative control for the parity test: agreement on 0 proves
    nothing, so every bucket must be non-zero in some scope and picker."""
    if bucket == "unsplit":
        pytest.skip("covered by the too-few test")
    exam = world["exam"]
    counts = [card_count(exam.quadrants(**SCOPES[s](exam),
                                        **PICKERS[p](world)), bucket)
              for s in SCOPES for p in PICKERS]
    assert max(counts) > 0, f"{bucket} is empty in every state"


def test_the_median_entry_lands_on_slow(world):
    """At the median itself the link must say slow, as the card does: the
    bound is the median, inclusive on the slow side, never its label."""
    exam = world["exam"]
    payload = exam.quadrants()
    m = payload["median"]["value_seconds"]
    on_median = [e for e in payload["entries"]
                 if e["t"] == m and e["d"] in (4, 5)]
    assert on_median, "fixture: no hard entry on the median"
    fast = dt_entry_browser_params(payload, "hard_fast")
    slow = dt_entry_browser_params(payload, "hard_slow")
    assert fast["time_max"] == slow["time_min"] == str(m).removesuffix(".0")


@pytest.mark.parametrize("picker", PICKERS)
def test_the_unsplit_bucket_lands_too(tmp_path, picker):
    """Under ten timed mistakes the card has one unsplit bucket instead of
    four quadrants. Its link must land as well, and a quadrant link must be
    refused rather than invented."""
    db = UserDatabase(tmp_path / "few.db", user_id=1, username="few")
    try:
        exam = Exam(db, "LP Few")
        group = db.create_tag_group(exam.name, "LP Kinds")
        a = db.create_hierarchical_tag(exam.name, "LP A", group.id).id
        b = db.create_hierarchical_tag(exam.name, "LP B", group.id).id
        removed = db.create_hierarchical_tag(exam.name, "LP R", group.id).id
        for d, t, tags in [(1, 10, [a]), (2, 20, [a, b]), (4, 30, []),
                           (5, 40, [b]), (3, 50, [a]), (None, 60, [removed]),
                           (4, 0, [a]), (4, None, [])]:
            exam.add(d, t, tags=tags)
        bridge = DatabaseBridge(user_db=db)
        world = {"a": a, "b": b, "removed": removed}
        payload = exam.quadrants(**PICKERS[picker](world))
        assert not payload["median"]["available"]
        for bucket in ("total", "unsplit", "middle", "not_placed"):
            params = dt_entry_browser_params(payload, bucket)
            assert browser_total(bridge, params) == card_count(
                payload, bucket), f"{picker} / {bucket}"
        assert card_count(exam.quadrants(), "unsplit") == 4
        with pytest.raises(ValueError):
            dt_entry_browser_params(payload, "hard_fast")
    finally:
        db.close()


def test_the_link_carries_the_picker_and_the_scope(world):
    """The helper's output itself, so a change of key names fails here with
    a readable diff rather than as a count mismatch."""
    exam = world["exam"]
    payload = exam.quadrants(subject_id=exam.shared.id,
                             primary_parent_id=exam.disciplines.id,
                             tag_ids=[world["a"], world["b"]], match="all")
    m = payload["median"]["value_seconds"]
    assert dt_entry_browser_params(payload, "easy_fast") == {
        "exam": str(exam.id),
        "counted_subject": str(exam.shared.id),
        "counted_parent": str(exam.disciplines.id),
        "difficulty": "1,2",
        "time_max": str(m).removesuffix(".0"),
        "tags": f"{world['a']},{world['b']}",
        "tag_mode": "all",
    }
    untagged = exam.quadrants(untagged=True)
    assert dt_entry_browser_params(untagged, "not_placed") == {
        "exam": str(exam.id), "missing": "difficulty,time", "untagged": "1"}
    assert dt_entry_browser_params(untagged, "middle") == {
        "exam": str(exam.id), "difficulty": "3", "time_min": "0",
        "untagged": "1"}
    one = exam.quadrants(tag_ids=[world["a"]], match="all")
    assert "tag_mode" not in dt_entry_browser_params(one, "total"), (
        "with one type, all and any are the same filter; send the default")
    with pytest.raises(ValueError):
        dt_entry_browser_params(payload, "everything")
