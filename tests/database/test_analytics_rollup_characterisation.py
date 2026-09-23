"""Characterisation: how analytics rolls up multi-parent subjects today.

Stage 1 of ``docs/planning/ANALYTICS_PRIMARY_PARENT_ROLLUP.md``.

**Several assertions in this file encode behaviour that is WRONG.** That is
deliberate. Before changing five analytics surfaces that share a rollup
concept, we pin what each one currently returns so the fix's diff is
something we read rather than something we assume. Each such assertion is
marked ``CHARACTERISATION`` and states what it should become.

The rule these surfaces are supposed to follow is
``POLYHIERARCHY_MIGRATION.md`` §5.4, which is a conditional:

* ``primary_parent_id IS NULL`` -> the entry rolls up through **every**
  ancestor reachable from the leaf (OMOP "honest non-additivity", §5.3).
* ``primary_parent_id`` set -> the entry rolls up through **only** that
  parent's ancestors.

Today only the NULL branch exists outside ``get_subject_deep_dive``, so a
disambiguated entry is still counted under parents the student explicitly
excluded.

Fixture
-------

::

        Cardio            Pregnancy
            \\             /
             \\           /
              hypertension        (2 parents)
        Neuro
            |
          migraine                (1 parent, control)

Two entries:

* ``entry_ctx``  — tagged hypertension, ``primary_parent_id = Cardio``.
  Should count under Cardio only; today counts under both.
* ``entry_null`` — tagged hypertension, ``primary_parent_id = NULL``.
  Should count under both, today and after the fix. This is the control
  that proves a fix does not over-correct into strict-always rollup.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


EXAM = "Rollup Characterisation"


# ---------------------------------------------------------------- fixtures


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
        username="rollup_char",
        display_name="Rollup Characterisation User",
        user_types=["student"],
    )


@pytest.fixture
def user_db(master_db, test_user):
    db = UserDatabase(
        db_path=master_db.ensure_user_database(test_user.id),
        user_id=test_user.id,
        username=test_user.username,
    )
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()
    yield db
    db.close()


@pytest.fixture
def world(user_db):
    """Build the fixture above and return the ids that matter."""
    exam = user_db.create_exam_context(
        exam_name=EXAM, exam_description="Characterisation fixture"
    )

    def node(name, parent=None, level="Topic"):
        return user_db.create_subject_node(
            exam_context=EXAM, name=name, level_type=level,
            parent_id=parent, sort_order=1,
        )

    cardio = node("Cardio", level="System")
    pregnancy = node("Pregnancy", level="System")
    neuro = node("Neuro", level="System")
    # First-created parent edge is the canonical one.
    htn = node("hypertension", parent=cardio.id)
    user_db.add_edge(pregnancy.id, htn.id, is_primary=False)
    migraine = node("migraine", parent=neuro.id)
    # The weight quadrant only considers weighted subjects, so without
    # this the whole surface is silently excluded from characterisation.
    for nid in (cardio.id, pregnancy.id, neuro.id, htn.id, migraine.id):
        user_db.execute(
            "UPDATE subject_nodes SET exam_weight_low = 5, exam_weight_high = 5 "
            "WHERE id = ?",
            (nid,),
        )
    user_db.conn.commit()

    session = user_db.create_review_session(
        exam_context_id=exam.id, total_questions=2, total_incorrect=2,
        session_name="chars", date_encountered=date.today(),
    )

    def entry(order, subject_id, ppid):
        # is_draft must be explicit: the weight-quadrant query filters on
        # ``qe.is_draft = FALSE``, so entries left at the column default
        # vanish from that surface and it silently characterises nothing.
        cur = user_db.execute(
            "INSERT INTO question_entries "
            "(review_session_id, entry_order, user_answer, correct_answer, "
            " is_draft) "
            "VALUES (?, ?, 'a', 'b', 0)",
            (session.id, order),
        )
        eid = cur.lastrowid
        user_db.execute(
            "INSERT INTO entry_subject_mappings "
            "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
            "VALUES (?, ?, 'primary', ?)",
            (eid, subject_id, ppid),
        )
        user_db.conn.commit()
        return eid

    return {
        "exam_id": exam.id,
        "cardio": cardio.id,
        "pregnancy": pregnancy.id,
        "neuro": neuro.id,
        "htn": htn.id,
        "migraine": migraine.id,
        "entry_ctx": entry(1, htn.id, cardio.id),
        "entry_null": entry(2, htn.id, None),
        # get_subject_analytics only returns subjects that have their own
        # direct entries -- an ancestor with none never appears in the
        # rows at all. Give both systems one so the descendant rollup is
        # observable on this surface.
        "entry_cardio": entry(3, cardio.id, None),
        "entry_preg": entry(4, pregnancy.id, None),
    }


# ------------------------------------------------------------- the fixture


def test_fixture_shape(user_db, world):
    """Guard the fixture itself, so a later failure is never the setup."""
    parents = user_db.fetchall(
        "SELECT parent_id FROM subject_edges WHERE child_id = ?",
        (world["htn"],),
    )
    assert {p["parent_id"] for p in parents} == {world["cardio"], world["pregnancy"]}

    rows = user_db.fetchall(
        "SELECT question_entry_id, primary_parent_id FROM entry_subject_mappings "
        "WHERE subject_node_id = ? ORDER BY question_entry_id",
        (world["htn"],),
    )
    assert [r["primary_parent_id"] for r in rows] == [world["cardio"], None], (
        "Expected one context-scoped entry and one NULL control."
    )


# ------------------------------------------------ surface: subject sunburst


def _walk_counts(tree):
    """Flatten the sunburst payload to {(node_name, parent_name): direct}."""
    out = {}
    def walk(node, parent_name):
        direct = node.get("direct_mistakes", 0) or 0
        out[(node.get("name"), parent_name)] = direct
        for child in node.get("children") or []:
            walk(child, node.get("name"))
    walk(tree, None)
    return out


def test_subject_mistake_counts_are_keyed_by_subject_only(user_db, world):
    """CHARACTERISATION -- the count map discards the parent context.

    Should become: keyed by (subject_id, primary_parent_id), so the caller
    can attribute each bucket to the right tree position.
    """
    # _get_subject_mistake_counts lives on the bridge serializer mixin, so
    # assert its query shape here rather than importing the bridge.
    rows = user_db.fetchall(
        """
        SELECT esm.subject_node_id, COUNT(DISTINCT qe.id) as count
        FROM question_entries qe
        JOIN review_sessions rs ON qe.review_session_id = rs.id
        JOIN entry_subject_mappings esm ON qe.id = esm.question_entry_id
        WHERE rs.exam_context_id = ? AND rs.user_id = ?
          AND esm.mapping_type = 'primary'
        GROUP BY esm.subject_node_id
        """,
        (world["exam_id"], user_db.user_id),
    )
    counts = {r["subject_node_id"]: r["count"] for r in rows}

    assert counts[world["htn"]] == 2, (
        "Both entries counted against the subject with no regard for "
        "context. Correct once fixed: one bucket of 1 under Cardio "
        "(the disambiguated entry) and one bucket of 1 with NULL context "
        "(which still rolls up to both parents)."
    )


# --------------------------------------------------- surface: Top Subjects


def test_top_subjects_counts_ignore_context(user_db, world):
    """CHARACTERISATION -- both entries land on hypertension regardless.

    Should become: unchanged here (the leaf's own direct count is 2 either
    way), but the ancestor rollup must differ -- see the next test.
    """
    rows = user_db.get_subject_analytics(world["exam_id"], limit=50)
    by_name = {r["subject_name"]: r for r in rows}
    assert by_name["hypertension"]["mistake_count"] == 2


def test_top_subjects_rolls_up_per_chosen_parent(user_db, world):
    """Top Subjects honours the parent context (§5.4).

    Each system has one direct entry of its own, plus whatever rolls up
    from hypertension. Before the fix BOTH hypertension entries rolled
    into BOTH systems, so each totalled 1 + 2 = 3.

    Now:

    * Cardio    1 own + 2 (the Cardio-scoped entry AND the NULL one) = 3
    * Pregnancy 1 own + 1 (the NULL one only)                        = 2

    Pregnancy is the number that moved and Cardio is the one that did
    not -- that asymmetry is what distinguishes honouring §5.4 from
    simply counting each entry once.
    """
    rows = user_db.get_subject_analytics(world["exam_id"], limit=50,
                                         include_children=True)
    by_name = {r["subject_name"]: r for r in rows}

    cardio_total = by_name.get("Cardio", {}).get("total_mistake_count")
    preg_total = by_name.get("Pregnancy", {}).get("total_mistake_count")

    assert (cardio_total, preg_total) == (3, 2), (
        f"Cardio={cardio_total} Pregnancy={preg_total}, expected (3, 2). "
        "Cardio keeps both hypertension entries -- one pinned to it, one "
        "never disambiguated. Pregnancy keeps only the undisambiguated "
        "one. If BOTH moved, the fix over-corrected into counting each "
        "entry once globally, which is not what §5.4 says."
    )


def test_only_subjects_with_direct_entries_appear(user_db, world):
    """Ancestors without their own entries never appear in Top Subjects.

    Not a defect, but load-bearing for reading this file: the rollup
    totals exist only on rows that earned a place by having direct
    entries. migraine has none, so it is absent.
    """
    names = {r["subject_name"] for r in
             user_db.get_subject_analytics(world["exam_id"], limit=50)}
    assert "migraine" not in names
    assert {"hypertension", "Cardio", "Pregnancy"} <= names


# ------------------------------------------------- surface: weight quadrant


def _quadrant_counts(user_db, exam_id):
    result = user_db.get_subject_exam_weight_analysis(exam_id)
    return {s["subject_name"]: s["mistake_count"]
            for s in result.get("subjects", [])}


def test_weight_quadrant_is_not_affected_by_parent_context(user_db, world):
    """The quadrant has NO §5.4 defect -- it does not roll up at all.

    Its query joins ``sn.id = esm.subject_node_id`` and groups by
    subject: direct counts per weighted node, no ancestor walk, no
    reference to primary_parent_id. So the context cannot change its
    output, and there is nothing here for the §5.4 conditional to fix.

    The scoping doc originally listed this surface as broken. It is not.
    Proven rather than reasoned: flip the context to the other parent and
    assert the numbers are identical.
    """
    before = _quadrant_counts(user_db, world["exam_id"])
    user_db.execute(
        "UPDATE entry_subject_mappings SET primary_parent_id = ? "
        "WHERE question_entry_id = ? AND subject_node_id = ?",
        (world["pregnancy"], world["entry_ctx"], world["htn"]),
    )
    user_db.conn.commit()
    after = _quadrant_counts(user_db, world["exam_id"])

    assert before == after, (
        f"Flipping primary_parent_id changed the quadrant: {before} -> "
        f"{after}. If that is now intended, this surface has joined the "
        "§5.4 set and needs a real characterisation."
    )
    assert before["hypertension"] == 2, (
        "Both entries are hypertension mistakes and both should count "
        "against hypertension -- there is no double-counting here."
    )


def test_weight_quadrant_and_top_subjects_agree_on_secondary_tags(
    user_db, world,
):
    """Both surfaces count primary tags only.

    Regression. The quadrant's query used to have no ``mapping_type``
    filter, so it counted secondary "also tested" tags as full mistakes
    while Top Subjects and the sunburst filtered to ``primary``. The same
    question yielded different counts depending on the chart, and the
    inflated ``total_mistakes`` denominator drove ``mistake_pct`` and the
    efficiency score.

    Found while probing whether the quadrant had a §5.4 defect. It did
    not; it had this instead.
    """
    user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type) "
        "VALUES (?, ?, 'secondary')",
        (world["entry_null"], world["migraine"]),
    )
    user_db.conn.commit()

    quadrant = _quadrant_counts(user_db, world["exam_id"])
    top = {r["subject_name"]: r["mistake_count"]
           for r in user_db.get_subject_analytics(world["exam_id"], limit=50)}

    assert quadrant.get("migraine", 0) == 0, (
        f"The quadrant counted a secondary tag: {quadrant}. It now filters "
        "to mapping_type = 'primary' in its JOIN, matching Top Subjects "
        "and the sunburst."
    )
    assert "migraine" not in top, "Top Subjects has always filtered to primary."
    assert quadrant.get("hypertension") == top.get("hypertension"), (
        f"The two surfaces disagree on hypertension: quadrant="
        f"{quadrant.get('hypertension')} top={top.get('hypertension')}. "
        "They count the same thing and must agree."
    )


# ---------------------------------------------- surface: patterns & insights


def test_patterns_inherit_subject_ranking(user_db, world):
    """CHARACTERISATION -- insights are derived, so they inherit the skew.

    get_patterns_and_insights calls get_subject_analytics(limit=5). It has
    no rollup logic of its own; it changes only because its input does.
    """
    import inspect
    src = inspect.getsource(user_db.get_patterns_and_insights)
    assert "get_subject_analytics" in src, (
        "Patterns no longer derives from subject analytics -- this surface "
        "needs its own characterisation rather than inheriting one."
    )





def test_context_moves_top_subjects(user_db, world):
    """The §5.4 conditional, exercised in all three states.

    Was a characterisation asserting the opposite: flipping the context
    left every surface byte-identical, which is what proved Top Subjects
    was rolling up blind. The discriminator for "is context-blindness a
    defect here" was whether the surface aggregates at all -- it does
    (Cardio totals its own 1 plus hypertension's 2), unlike the weight
    quadrant, which is why that one needed no fix and this one did.
    """
    def snapshot():
        return {
            r["subject_name"]: r["total_mistake_count"]
            for r in user_db.get_subject_analytics(
                world["exam_id"], limit=50, include_children=True)
        }

    states = {}
    for label, ppid in [("cardio", world["cardio"]),
                        ("pregnancy", world["pregnancy"]),
                        ("null", None)]:
        user_db.execute(
            "UPDATE entry_subject_mappings SET primary_parent_id = ? "
            "WHERE question_entry_id = ? AND subject_node_id = ?",
            (ppid, world["entry_ctx"], world["htn"]))
        user_db.conn.commit()
        states[label] = snapshot()

    assert states["cardio"]["Cardio"] == 3 and states["cardio"]["Pregnancy"] == 2
    # Symmetric: pinning the other way moves the other number.
    assert states["pregnancy"]["Pregnancy"] == 3 and states["pregnancy"]["Cardio"] == 2
    # Undisambiguated keeps OMOP rollup -- both branches get everything.
    assert states["null"]["Cardio"] == 3 and states["null"]["Pregnancy"] == 3, (
        f"NULL context must still reach both parents (§5.3): {states['null']}"
    )
    # The leaf's own total never depends on context: every entry tagged
    # on it is its mistake, whichever branch it rolls into.
    assert {s["hypertension"] for s in states.values()} == {2}


# ------------------------- stage 4: the subject sunburst honours §5.4


class _BucketHost:
    """Minimal stand-in exposing the serializer mixin's two helpers.

    The helpers live on a bridge mixin that expects ``self.user_db``;
    instantiating the whole bridge here would drag in Qt. This binds just
    the two methods under test to a real database.
    """

    def __init__(self, user_db):
        self.user_db = user_db

    def buckets(self, exam_id):
        from app.bridge_domains._serializers import SerializerMixin
        return SerializerMixin._get_subject_mistake_buckets(self, exam_id)

    @staticmethod
    def at(buckets, subject_id, parent_id):
        from app.bridge_domains._serializers import SerializerMixin
        return SerializerMixin._position_mistake_count(
            buckets, subject_id, parent_id)


def test_sunburst_buckets_split_by_chosen_parent(user_db, world):
    """The count map keeps the context instead of discarding it."""
    host = _BucketHost(user_db)
    buckets = host.buckets(world["exam_id"])

    assert buckets[world["htn"]] == {world["cardio"]: 1, None: 1}, (
        f"Expected hypertension's two entries in separate buckets, got "
        f"{buckets.get(world['htn'])}. One was scoped to Cardio, one left "
        "unscoped."
    )


def test_sunburst_attributes_scoped_entry_to_one_position_only(user_db, world):
    """The §5.4 fix, stated as the numbers drawn at each position.

    hypertension is drawn twice -- once under Cardio, once under
    Pregnancy. Before the fix both positions showed 2. Now:

    * under Cardio    the Cardio-scoped entry + the unscoped one = 2
    * under Pregnancy the unscoped one only                      = 1

    The unscoped entry appearing in both is not a bug: §5.3 OMOP rollup
    is correct when the student never disambiguated. A fix that showed 1
    and 1 would have over-corrected.
    """
    host = _BucketHost(user_db)
    buckets = host.buckets(world["exam_id"])

    under_cardio = host.at(buckets, world["htn"], world["cardio"])
    under_preg = host.at(buckets, world["htn"], world["pregnancy"])

    assert (under_cardio, under_preg) == (2, 1), (
        f"Got Cardio={under_cardio} Pregnancy={under_preg}, expected (2, 1). "
        "Cardio takes both entries; Pregnancy takes only the unscoped one."
    )


def test_sunburst_unrelated_parent_gets_only_unscoped_entries(user_db, world):
    """A parent the subject does not sit under draws only NULL-context."""
    host = _BucketHost(user_db)
    buckets = host.buckets(world["exam_id"])
    assert host.at(buckets, world["htn"], world["neuro"]) == 1


def test_sunburst_subject_with_no_entries_is_zero_everywhere(user_db, world):
    host = _BucketHost(user_db)
    buckets = host.buckets(world["exam_id"])
    assert host.at(buckets, world["migraine"], world["neuro"]) == 0


def test_root_position_does_not_double_count_unscoped_entries(user_db, world):
    """Regression: None means two different things and they collided.

    In the bucket map ``None`` keys the "never disambiguated" entries,
    which belong at every position. It is also the ``parent_id`` of a
    root position. Summing ``get(None) + get(parent_id)`` therefore added
    that bucket to itself for any root subject, doubling it.

    Cardio is a root with one direct entry and no context. It must draw
    1, not 2. Found only when the dimension sunburst was rebuilt on the
    same helper shape -- the stage 4 tests all probed non-root positions
    and sailed past it.
    """
    host = _BucketHost(user_db)
    buckets = host.buckets(world["exam_id"])

    assert buckets[world["cardio"]] == {None: 1}, (
        f"fixture drifted: {buckets.get(world['cardio'])}"
    )
    assert host.at(buckets, world["cardio"], None) == 1, (
        "A root drew its unscoped entries twice."
    )
