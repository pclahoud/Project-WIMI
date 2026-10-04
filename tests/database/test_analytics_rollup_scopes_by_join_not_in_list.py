"""The §5.4 rollup must not carry one bound parameter per subject (#199).

``get_subject_analytics`` splits each subject's mistakes by the parent the
student pinned them to, so a shared subject cannot inflate every branch it
appears under. That split is correct and is #13's decision; nothing here
argues with it.

What it used to cost: the bucket query scoped itself with
``AND esm.subject_node_id IN (?, ?, ? ...)`` -- **one placeholder per
subject**. On a real content outline that is 2,575 of them, and it measured

    IN list of 2,575 ids   1,613 ms
    JOIN subject_nodes         7.1 ms

for a byte-identical row set. 230x.

**A long IN list is not slow to parse; it changes the plan.** With it,
SQLite picks the composite ``idx_unique_entry_subject (question_entry_id,
subject_node_id)`` and probes it once per element of the list, per entry.
Without it, one probe on ``idx_entry_subjects_entry``. So the cost grew
with the size of the student's subject tree, and this single statement was
2.6 s of a 2.8 s dashboard open -- on the page the app lands on.

The regression is easy to reintroduce, because an ``IN`` list is the
obvious way to express "only these subjects" and it is *correct*. It is
only the plan that is catastrophic, and no test of the returned rows can
see that. Hence the first test below asserts on the **shape of the
statement**, not on its results or its time:

- results cannot see it (the row set is identical);
- timing cannot see it reliably on a small fixture, and a timing assertion
  on a big one would be slow and flaky.

What *can* see it, deterministically, is that the statement's size must not
grow with the number of subjects.

One thing this file deliberately does NOT do: generalise the assertion to
"no large IN list anywhere". ``_aggregate_hierarchy_counts`` legitimately
builds ``WHERE child_id IN (...)`` over the same node ids, and that one
measured 12-15 ms -- a plain index scan with no join or DISTINCT to
interact with. The defect is specific to this query, and so is the guard.

Nor does it touch ``dimensions.py``'s two sibling bucket queries: their IN
lists are scoped to **one dimension's** nodes, which is a genuine filter
rather than a redundant restatement, and removing them would change
results.
"""
from __future__ import annotations

from datetime import date

import pytest

from database.user_db import UserDatabase


# --------------------------------------------------------------- helpers


def _build(tmp_path, name: str, n_topics: int) -> tuple[UserDatabase, int, dict]:
    """One exam, one root, ``n_topics`` topics under it, one entry each."""
    db = UserDatabase(tmp_path / f"{name}.db", user_id=1, username=name)
    exam = db.create_exam_context(
        exam_name=f"Rollup Exam {name}",
        exam_description="#199 -- rollup scoping",
        hierarchy_levels=["System", "Topic"],
    )
    root = db.create_subject_node(
        exam_context=exam.exam_name, name="R Root", level_type="System",
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=n_topics,
        total_incorrect=n_topics, session_name="s",
        date_encountered=date.today(),
    )
    topics = {}
    for i in range(n_topics):
        t = db.create_subject_node(
            exam_context=exam.exam_name, name=f"R Topic {i}",
            level_type="Topic", parent_id=root.id,
        )
        topics[i] = t.id
        db.create_question_entry(
            review_session_id=session.id, user_answer="a", correct_answer="b",
            primary_subject_ids=[t.id],
        )
    return db, exam.id, {"root": root.id, "topics": topics, "session": session.id}


def _bucket_statement(db: UserDatabase, exam_id: int) -> str:
    """Run get_subject_analytics and return the §5.4 bucket statement.

    ``set_trace_callback`` hands back the EXPANDED sql -- parameters already
    substituted -- which is exactly what makes the per-subject growth
    visible as statement length.
    """
    seen: list[str] = []
    db.conn.set_trace_callback(seen.append)
    try:
        db.get_subject_analytics(exam_id, include_children=True)
    finally:
        db.conn.set_trace_callback(None)

    # The bucket query is the only one aliasing primary_parent_id to ppid.
    matches = [s for s in seen if "ppid" in s and "entry_subject_mappings" in s]
    assert matches, (
        "get_subject_analytics issued no §5.4 bucket query. Either the "
        "rollup stopped splitting by pinned parent (a #13 regression), or "
        "this test's fixture no longer reaches that branch -- it needs "
        "include_children=True and at least one subject carrying an entry."
    )
    return matches[0]


# ----------------------------------------------------------------- tests


def test_the_bucket_query_does_not_grow_with_the_number_of_subjects(tmp_path):
    """The guard for #199. Statement size must be independent of tree size."""
    small_db, small_exam, _ = _build(tmp_path, "small", 3)
    large_db, large_exam, _ = _build(tmp_path, "large", 120)

    small = _bucket_statement(small_db, small_exam)
    large = _bucket_statement(large_db, large_exam)

    assert len(small) == len(large), (
        "The §5.4 bucket query grew with the subject count: "
        f"{len(small)} chars at 3 subjects, {len(large)} at 120. That is an "
        "id list embedded in the statement. It returns the right rows and it "
        "changes the query plan -- SQLite switches to the composite "
        "idx_unique_entry_subject and probes it once per id, per entry, which "
        "measured 1,613 ms against 7 ms at 2,575 subjects (#199). Scope the "
        "query by JOINing subject_nodes, as the subject query above it does."
    )


def test_it_scopes_by_joining_subject_nodes(tmp_path):
    """Name the mechanism, so the fix is not reverted to a slower equivalent.

    The previous test would also pass if somebody dropped the scoping
    altogether. That happens to be safe today -- ``_aggregate_hierarchy_counts``
    reads ``context_buckets`` with ``.get(node_id)`` for nodes it was handed,
    so extra keys are inert -- but it is safe by the *consumer's* current
    shape rather than by construction. The join keeps both queries seeing the
    same subject ids whatever the consumer later does.
    """
    db, exam_id, _ = _build(tmp_path, "join", 4)
    stmt = _bucket_statement(db, exam_id)

    assert "subject_nodes" in stmt, (
        "The §5.4 bucket query no longer joins subject_nodes. Scoping it that "
        "way is what makes it provably the same subject set as the query "
        "above (same three joins, same where_clause, same mapping_type, no "
        "LIMIT) rather than relying on how the buckets happen to be read."
    )


def test_a_pinned_entry_still_rolls_up_through_one_parent_only(tmp_path):
    """#13 / POLYHIERARCHY §5.4 -- unchanged by the #199 fix.

    The scoping change must not touch what the rollup *means*. A subject
    under two parents, with its entry pinned to one of them, must reach that
    parent's total and not the other's.
    """
    db = UserDatabase(tmp_path / "pinned.db", user_id=1, username="pinned")
    exam = db.create_exam_context(
        exam_name="Pinned Exam", exam_description="#199 keeps #13",
        hierarchy_levels=["System", "Topic"],
    )
    a = db.create_subject_node(
        exam_context=exam.exam_name, name="P Parent A", level_type="System")
    b = db.create_subject_node(
        exam_context=exam.exam_name, name="P Parent B", level_type="System")
    shared = db.create_subject_node(
        exam_context=exam.exam_name, name="P Shared", level_type="Topic",
        parent_id=a.id)
    db.add_edge(parent_id=b.id, child_id=shared.id)

    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=3, total_incorrect=3,
        session_name="s", date_encountered=date.today())
    # Both parents need an entry of their own, or they never appear at all:
    # get_subject_analytics selects FROM subject_nodes JOINed to
    # entry_subject_mappings, so a subject carrying no entry directly is
    # absent from the result even when descendants roll up into it.
    for node in (a, b):
        db.create_question_entry(
            review_session_id=session.id, user_answer="a", correct_answer="b",
            primary_subject_ids=[node.id])
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer="a", correct_answer="b",
        primary_subject_ids=[shared.id])
    # There is no database-layer setter for this column; the bridge's
    # setPrimaryParentForEntry writes it directly, so the test does the same
    # statement rather than inventing an API.
    with db.transaction():
        db.execute(
            "UPDATE entry_subject_mappings SET primary_parent_id = ? "
            "WHERE question_entry_id = ? AND subject_node_id = ?",
            (a.id, entry.id, shared.id),
        )

    rows = {r["subject_id"]: r for r in
            db.get_subject_analytics(exam.id, limit=50, include_children=True)}

    # A: its own entry + the shared child's, which was pinned to A.
    assert rows[a.id]["total_mistake_count"] == 2, (
        f"Parent A totalled {rows[a.id]['total_mistake_count']}, expected 2 "
        "(its own entry plus the shared child's, which was pinned to A). "
        "#199 changed only how the bucket query is scoped; it must not "
        "change the §5.4 split (#13)."
    )
    # B: its own entry only. The shared child is its child too, but that
    # entry belongs to A's branch.
    assert rows[b.id]["total_mistake_count"] == 1, (
        f"Parent B totalled {rows[b.id]['total_mistake_count']}, expected 1. "
        "The shared child's entry was pinned to Parent A and must not reach "
        "B as well -- that is the double-count #13 fixed and dbf6087 "
        "implemented; #199's scoping change must not undo it."
    )
