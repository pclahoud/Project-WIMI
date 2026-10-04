"""The dimensional §5.4 rollups must not carry one parameter per subject (#208).

Sibling of ``test_analytics_rollup_scopes_by_join_not_in_list.py`` (#199),
for the two bucket queries in ``dimensions.py`` that #199 deliberately did
not touch:

* ``get_dimension_performance`` — the dimensional Top Subjects list;
* ``get_subject_hierarchy_with_mistakes_by_dimension`` — the dimensional
  sunburst.

Both are on the analytics dashboard for a multi-dimensional exam, which
CLAUDE.md calls "the common case, not the edge case".

**#199's IN list was redundant and was deleted. This one is not.** The
ids come from a dimension-scoped query, so removing the predicate would
let the other dimension's subjects into the buckets — a wrong sunburst,
not a fast one. The predicate therefore moves into a join on the same
three columns the node query filters on::

    JOIN subject_nodes sn ON sn.id = esm.subject_node_id
                         AND sn.exam_context = (SELECT exam_name ...)
                         AND sn.dimension_id = ?
                         AND sn.status = 'active'

All three, restated rather than argued away. Two earlier passes at this
fix each dropped a different one: the first named only ``dimension_id``,
the second added ``status`` and forgot ``exam_context``. So there is one
test per predicate below, and each was mutation-checked by deleting that
predicate from the join and confirming its own test — and only its own —
went red.

What the measurement was, stated plainly because the issue's table
needed correcting twice. On this file's fixture, 3,118 entries, timing
the two spellings of the bucket query directly:

    nodes in dimension    IN list    JOIN      ratio
    200                   119.1 ms   3.6 ms    33x
    800                   454.4 ms   4.6 ms   100x
    2,000               1,110.7 ms   6.6 ms   169x

Two corrections to #208's body fall out of that. The ratio is **not**
flat at ~161x — it grows with the node count. And the whole effect is
conditional on SQLite having no ``sqlite_stat1``: with statistics
present the IN list plans sanely and both spellings run in single-digit
milliseconds. No statistics is the state of a freshly created profile
and a freshly imported ``.wimi``, because ``BaseDatabase.close()`` runs
``PRAGMA optimize`` and that is what writes them — so this is a
first-launch cost, reliably. The join is worth having anyway for the
reason the timing does not show: its plan does not depend on the
statistics, and the IN list's does.

None of that is assertable here. A timing assertion on a small fixture
is not reliable and on a large one is slow and flaky, and the row sets
are identical by design, so results cannot see it either. What *can* be
asserted deterministically is that the statement does not grow with the
node count — that is the first test — plus the four scoping facts the
join has to preserve and the §5.4 meaning it must not change.
"""
from __future__ import annotations

import pytest

from database.user_db import UserDatabase
from wimi_test.db.seeders import seed_multi_dimensional


# --------------------------------------------------------------- helpers


#: The two call sites, as (label, callable-builder). Every structural
#: test runs against both: they are the same defect in two places and a
#: fix to one is routinely not applied to the other.
SITES = ("performance", "sunburst")


def _invoke(db: UserDatabase, site: str, exam_id: int, dim_id: int):
    if site == "performance":
        return db.get_dimension_performance(exam_id, dim_id, include_children=True)
    return db.get_subject_hierarchy_with_mistakes_by_dimension(exam_id, dim_id)


def _build(tmp_path, name: str, *, filler: int = 0):
    """A multi-dimensional database, plus the handle onto its ids.

    The fixture lives in ``wimi_test/db/seeders.py`` rather than here
    because #66's four waves need the same thing, and because a fixture
    that only one test file can reach is how the last three performance
    issues came to be measured against a database that could not
    express their failure mode.
    """
    db = UserDatabase(tmp_path / f"{name}.db", user_id=1, username=name)
    fixture = seed_multi_dimensional(
        db, exam_name=f"Dim Exam {name}", filler_topics_per_dimension=filler,
    )
    return db, fixture


def _bucket_statement(db: UserDatabase, site: str, exam_id: int, dim_id: int) -> str:
    """Run one site and return the §5.4 bucket statement it issued.

    ``set_trace_callback`` hands back the EXPANDED sql — parameters
    already substituted — which is what makes a per-subject id list
    visible as statement length, and what lets the scoping tests below
    re-execute the statement with no parameters of their own.
    """
    seen: list[str] = []
    db.conn.set_trace_callback(seen.append)
    try:
        _invoke(db, site, exam_id, dim_id)
    finally:
        db.conn.set_trace_callback(None)

    matches = [s for s in seen if "ppid" in s and "entry_subject_mappings" in s]
    assert matches, (
        f"{site} issued no §5.4 bucket query. Either the dimensional rollup "
        "stopped splitting mistakes by the pinned parent (a #13 regression), "
        "or this fixture no longer reaches that branch — it needs entries on "
        "subjects inside the dimension, and, for the performance site, "
        "include_children=True."
    )
    return matches[0]


#: The bucket query exactly as it stood before #208, for the row-identity
#: test. Kept as literal text rather than reconstructed from the module,
#: because the point is to compare against what shipped.
_PRE_208_SQL = """
    SELECT esm.subject_node_id AS sid,
           esm.primary_parent_id AS ppid,
           COUNT(DISTINCT qe.id) AS n
    FROM entry_subject_mappings esm
    JOIN question_entries qe ON qe.id = esm.question_entry_id
    JOIN review_sessions rs ON rs.id = qe.review_session_id
    WHERE esm.mapping_type = 'primary'
      AND rs.exam_context_id = ?
      AND rs.user_id = ?
      AND esm.subject_node_id IN ({placeholders})
    GROUP BY esm.subject_node_id, esm.primary_parent_id
"""


def _sortable(rows):
    """Sort rows that carry NULLs in the ppid column."""
    return sorted((tuple(r) for r in rows),
                  key=lambda t: tuple((x is None, x) for x in t))


def _pre_208_rows(db: UserDatabase, site: str, fixture):
    """Rows the old IN-list spelling returned, ids derived as it derived them."""
    exam_id, dim_id = fixture.exam_context_id, fixture.dimensions["System"]
    if site == "performance":
        # get_dimension_performance's node list, including its
        # (rs.id IS NOT NULL OR qe.id IS NULL) filter — the one place the
        # old and new node sets genuinely differ.
        node_ids = [r["hierarchy_id"] for r in db.fetchall("""
            SELECT sn.id AS hierarchy_id
            FROM subject_nodes sn
            LEFT JOIN entry_subject_mappings esm
                ON esm.subject_node_id = sn.id AND esm.mapping_type = 'primary'
            LEFT JOIN question_entries qe ON qe.id = esm.question_entry_id
            LEFT JOIN review_sessions rs
                ON rs.id = qe.review_session_id
                AND rs.exam_context_id = ? AND rs.user_id = ?
            WHERE sn.exam_context = (SELECT exam_name FROM exam_contexts WHERE id = ?)
              AND sn.dimension_id = ?
              AND sn.status = 'active'
              AND (rs.id IS NOT NULL OR qe.id IS NULL)
            GROUP BY sn.id, sn.name
        """, (exam_id, db.user_id, exam_id, dim_id))]
    else:
        node_ids = [r["id"] for r in db.fetchall("""
            SELECT sn.id FROM subject_nodes sn
            WHERE sn.exam_context = (SELECT exam_name FROM exam_contexts WHERE id = ?)
              AND sn.dimension_id = ?
              AND sn.status = 'active'
            ORDER BY sn.sort_order, sn.name
        """, (exam_id, dim_id))]

    sql = _PRE_208_SQL.format(placeholders=",".join(["?"] * len(node_ids)))
    return _sortable(db.conn.execute(
        sql, tuple([exam_id, db.user_id] + node_ids)).fetchall())


# ----------------------------------------------------- the #208 guard


@pytest.mark.parametrize("site", SITES)
def test_the_bucket_query_does_not_grow_with_the_node_count(tmp_path, site):
    """Statement size must be independent of how many nodes the dimension holds."""
    small_db, small = _build(tmp_path, f"small_{site}", filler=3)
    large_db, large = _build(tmp_path, f"large_{site}", filler=120)

    small_stmt = _bucket_statement(
        small_db, site, small.exam_context_id, small.dimensions["System"])
    large_stmt = _bucket_statement(
        large_db, site, large.exam_context_id, large.dimensions["System"])

    assert len(small_stmt) == len(large_stmt), (
        f"{site}'s §5.4 bucket query grew with the node count: "
        f"{len(small_stmt)} chars at 13 subjects, {len(large_stmt)} at 130. "
        "That is an id list embedded in the statement. It returns the right "
        "rows and it changes the query plan — with no sqlite_stat1 SQLite "
        "switches to the composite idx_unique_entry_subject and probes it "
        "once per id, per entry, which measured 1,111 ms against 6.6 ms at "
        "2,000 nodes and 3,118 entries (#208). Scope it by JOINing "
        "subject_nodes on exam_context, dimension_id and status instead."
    )


@pytest.mark.parametrize("site", SITES)
def test_it_scopes_by_joining_subject_nodes(tmp_path, site):
    """Name the mechanism, so the fix is not reverted to a slower equivalent.

    The test above would also pass if somebody dropped the scoping
    altogether — and unlike #199, where that happened to be harmless,
    here it would be a correctness bug that no *output* assertion can
    see: both consumers read the buckets with ``.get(node_id)`` for
    nodes they already hold, so surplus keys are silently inert. The
    predicate has to be asserted on the statement.
    """
    db, fixture = _build(tmp_path, f"join_{site}", filler=4)
    stmt = _bucket_statement(
        db, site, fixture.exam_context_id, fixture.dimensions["System"])

    assert "subject_nodes" in stmt, (
        f"{site}'s §5.4 bucket query no longer joins subject_nodes. The "
        "dimension scoping is a genuine filter here, not a redundant "
        "restatement as in #199: without it the buckets carry every "
        "dimension's subjects, plus archived ones and ones belonging to "
        "other exams."
    )


@pytest.mark.parametrize("site", SITES)
def test_the_join_returns_exactly_the_rows_the_id_list_returned(tmp_path, site):
    """Row identity against the pre-#208 spelling. The thing #199 could not assert.

    #199's guard could only say the statement stopped growing and that it
    joined the right table. This one compares the actual rows, because the
    fix here changes a *filter* rather than removing a redundant one, and
    "equivalent by construction" is a claim that should be checked rather
    than asserted in a comment.
    """
    db, fixture = _build(tmp_path, f"identity_{site}", filler=6)
    stmt = _bucket_statement(
        db, site, fixture.exam_context_id, fixture.dimensions["System"])

    new_rows = _sortable(db.conn.execute(stmt).fetchall())
    old_rows = _pre_208_rows(db, site, fixture)

    assert new_rows, (
        "The bucket query returned nothing at all, so this test would pass "
        "against any join whatsoever. The fixture must put entries on "
        "subjects inside the measured dimension."
    )
    assert new_rows == old_rows, (
        f"{site}'s join does not return what the IN list returned.\n"
        f"  only in the join: {[r for r in new_rows if r not in old_rows]}\n"
        f"  only in the list: {[r for r in old_rows if r not in new_rows]}\n"
        "The join must filter subject_nodes on the same three predicates the "
        "node query above it uses — exam_context, dimension_id and status."
    )


# ------------------------------------- one test per predicate in the join


@pytest.mark.parametrize("site", SITES)
def test_another_dimensions_subjects_stay_out_of_the_buckets(tmp_path, site):
    """``sn.dimension_id = ?``. The predicate that makes this not-#199.

    The fixture's second dimension carries its own entries. If the join
    drops ``dimension_id``, a dimensional sunburst counts them.
    """
    db, fixture = _build(tmp_path, f"dim_{site}")
    stmt = _bucket_statement(
        db, site, fixture.exam_context_id, fixture.dimensions["System"])
    sids = {r[0] for r in db.conn.execute(stmt).fetchall()}

    other = {name: fixture.nodes[name] for name in
             ("Diagnosis", "Interpreting Laboratory Data", "Pharmacotherapy")}
    leaked = {name: nid for name, nid in other.items() if nid in sids}
    assert not leaked, (
        f"{site}'s buckets carry subjects from the Physician Task dimension "
        f"while scoped to System: {leaked}. Removing the IN list without "
        "replacing it with a dimension_id predicate is the correctness "
        "regression #208 exists to avoid — #199's list was redundant, this "
        "one is not."
    )
    # And the measured dimension is actually represented, or the assertion
    # above would hold vacuously.
    assert fixture.shared_node_id in sids


@pytest.mark.parametrize("site", SITES)
def test_an_archived_subject_that_still_carries_entries_stays_out(tmp_path, site):
    """``sn.status = 'active'``. The predicate that was nearly dropped.

    #15's delete is soft: archiving a subject leaves its
    ``entry_subject_mappings`` rows in place. So an archived subject is
    exactly the row that a ``dimension_id``-only join lets back in, and
    an archived subject with no entries would not notice. The fixture
    gives the archived subject an entry for that reason.
    """
    db, fixture = _build(tmp_path, f"archived_{site}")
    archived = fixture.archived_node_ids[0]

    # The premise: it is archived, in the measured dimension, and still
    # holds a primary mapping. Without all three this test is vacuous.
    row = db.fetchone(
        "SELECT status, dimension_id, "
        "(SELECT COUNT(*) FROM entry_subject_mappings esm "
        "  WHERE esm.subject_node_id = sn.id AND esm.mapping_type = 'primary') "
        "AS mappings FROM subject_nodes sn WHERE sn.id = ?", (archived,))
    assert row["status"] == "archived"
    assert row["dimension_id"] == fixture.dimensions["System"]
    assert row["mappings"] >= 1

    stmt = _bucket_statement(
        db, site, fixture.exam_context_id, fixture.dimensions["System"])
    sids = {r[0] for r in db.conn.execute(stmt).fetchall()}

    assert archived not in sids, (
        f"{site}'s buckets carry archived subject {archived}, which still "
        "holds entry mappings because #15's delete is soft. The node query "
        "above filters status = 'active'; the join must too, or the two "
        "queries see different subject sets and 'equivalent by "
        "construction' stops being true."
    )


@pytest.mark.parametrize("site", SITES)
def test_a_subject_with_no_dimension_at_all_stays_out(tmp_path, site):
    """``sn.dimension_id = ?`` again, from the NULL side.

    A part-converted exam really has these: subjects created before the
    dimensions were added. ``IS NULL`` never equals a dimension id, so
    the same predicate covers it — but from the other direction, and a
    join written as an ``OR`` or a ``LEFT JOIN`` would get this one
    wrong while passing the test above.
    """
    db, fixture = _build(tmp_path, f"nodim_{site}")
    stmt = _bucket_statement(
        db, site, fixture.exam_context_id, fixture.dimensions["System"])
    sids = {r[0] for r in db.conn.execute(stmt).fetchall()}

    assert fixture.undimensioned_node_id not in sids, (
        f"{site}'s buckets carry the subject with dimension_id IS NULL. A "
        "dimensional view is scoped to one dimension; the dimensionless "
        "leftovers of a part-converted exam are not in it."
    )


@pytest.mark.parametrize("site", SITES)
def test_a_subject_in_another_exam_wearing_this_dimensions_id_stays_out(
        tmp_path, site):
    """``sn.exam_context = (SELECT exam_name ...)``. The third predicate.

    The honest note: this row is unlikely. ``subject_nodes.dimension_id``
    normally determines the exam context transitively, because a
    dimension belongs to one exam and dimension ids are globally unique.

    It is unlikely rather than impossible, which is the point.
    ``subject_nodes.dimension_id`` is a bare INTEGER — no foreign key —
    and no writer checks it against ``exam_context``: ``create_subject_node``
    takes both as independent arguments, so an importer or a bridge call
    carrying a stale dimension id produces exactly this row. That is why
    the predicate is copied from the query above rather than reasoned
    away. The ``status`` predicate was "obviously" safe on the same kind
    of argument, and was wrong.
    """
    db, fixture = _build(tmp_path, f"examctx_{site}")
    sys_dim = fixture.dimensions["System"]

    other_exam = db.create_exam_context(
        exam_name=f"Other Exam {site}",
        exam_description="A second exam context in the same profile",
        hierarchy_levels=["System", "Topic"],
    )
    intruder = db.create_subject_node(
        exam_context=other_exam.exam_name,
        name="Subject Of Another Exam",
        level_type="System",
        dimension_id=sys_dim,          # not validated against exam_context
    )
    # Give it an entry in the *measured* exam's session, so it can reach
    # the bucket query's rs.exam_context_id / rs.user_id filter and the
    # only thing left to exclude it is the subject's own exam_context.
    db.create_question_entry(
        review_session_id=fixture.review_session_id,
        user_answer="a", correct_answer="b",
        primary_subject_ids=[intruder.id],
    )

    stmt = _bucket_statement(db, site, fixture.exam_context_id, sys_dim)
    sids = {r[0] for r in db.conn.execute(stmt).fetchall()}

    assert intruder.id not in sids, (
        f"{site}'s buckets carry subject {intruder.id}, which belongs to "
        f"{other_exam.exam_name!r} and only wears this exam's dimension id. "
        "The node query above filters sn.exam_context; the join must too. "
        "Two earlier passes at #208 each dropped a different predicate, and "
        "this was the one the issue body itself left out."
    )


# --------------------------------------------- the meaning must not change


@pytest.mark.parametrize("site", SITES)
def test_a_pinned_entry_still_rolls_up_through_one_parent_only(tmp_path, site):
    """#13 / POLYHIERARCHY §5.4 — unchanged by the #208 scoping change.

    The fixture's Hypertension sits under both Cardiovascular and Renal
    inside the System dimension, with one entry pinned to each and one
    left unpinned. The unpinned one belongs at every position; the
    pinned ones belong at theirs alone. So each parent must see 2, not 3
    — and the shared subject's own direct count is all 3.
    """
    db, fixture = _build(tmp_path, f"pinned_{site}")
    exam_id, dim_id = fixture.exam_context_id, fixture.dimensions["System"]
    cardio = fixture.nodes["Cardiovascular System"]
    renal = fixture.nodes["Renal System"]

    if site == "performance":
        nodes = {n["hierarchy_id"]: n
                 for n in _invoke(db, site, exam_id, dim_id)["nodes"]}
        # Cardiovascular: Hypertension's unpinned + Cardiovascular-pinned
        # entries, plus Heart Failure's. The Renal-pinned one must not reach it.
        assert nodes[cardio]["total_entries"] == 3, (
            f"Cardiovascular totalled {nodes[cardio]['total_entries']}, "
            "expected 3 (Heart Failure's entry, Hypertension's unpinned "
            "entry and the one pinned to Cardiovascular). #208 changed only "
            "how the bucket query is scoped; it must not change the §5.4 "
            "split (#13)."
        )
        assert nodes[renal]["total_entries"] == 3, (
            f"Renal totalled {nodes[renal]['total_entries']}, expected 3 "
            "(Acute Kidney Injury's entry, Hypertension's unpinned entry and "
            "the one pinned to Renal)."
        )
        assert nodes[fixture.shared_node_id]["direct_entries"] == 3, (
            "The shared subject's own direct count must still be all three "
            "of its entries, whatever parent they were pinned to."
        )
    else:
        tree = _invoke(db, site, exam_id, dim_id)
        by_id = {c["id"]: c for c in tree["children"]}
        assert by_id[cardio]["value"] == 3, (
            f"Cardiovascular's arc totalled {by_id[cardio]['value']}, "
            "expected 3. The entry pinned to Renal must not be drawn under "
            "Cardiovascular as well — that is the double count #13 fixed."
        )
        assert by_id[renal]["value"] == 3, (
            f"Renal's arc totalled {by_id[renal]['value']}, expected 3."
        )
        # And the shared subject really is drawn under both parents, or the
        # two assertions above are not about a shared subject at all.
        drawn_under = {
            pid for pid, node in by_id.items()
            if any(k["id"] == fixture.shared_node_id
                   for k in node.get("children", []))
        }
        assert drawn_under == {cardio, renal}, (
            f"The shared subject is drawn under {drawn_under}, expected both "
            f"{cardio} and {renal}. Without two positions this test says "
            "nothing about the §5.4 split."
        )
