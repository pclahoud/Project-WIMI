"""The draft-entry policy, pinned one surface at a time (issue #12).

The owner's decision, 2026-09-14:

    **Drafts count everywhere, except goals.** A draft exists because a
    question was answered wrong. The mistake happened; an unfinished
    reflection does not un-happen it. A student with fifteen unfinished
    drafts must not be shown an analytics screen implying they have no
    weaknesses.

    The goals exception: a goal of "log 20 entries this week" means 20
    *finished* entries. Goals continue to exclude drafts, and gain a
    qualifier showing the outstanding drafts alongside the progress.

Why one test per surface rather than one test for the policy: this
question has been re-litigated three times. ``ENTRY_COUNT_AUDIT.md``
deferred it, ``ANALYTICS_PRIMARY_PARENT_ROLLUP.md`` deferred it, and
commit ``d3690b0`` implemented a draft filter in
``get_dimension_performance`` before reverting it as a behaviour change
nobody had asked for. A single consolidated assertion would go green
again the moment one surface drifted; per-surface assertions name the
surface that broke.

The seed puts **two drafts on their own subject** (``DP Renal``) and one
completed entry on another (``DP Cardio``). Both drafts carry a primary
subject mapping, without which they could not reach a subject-scoped
surface at all and every assertion below would pass for the wrong
reason. The split also makes the draft the *leader* on the source's top
subject, which is what discriminates
``_get_top_subject_for_source``: with both entries on one subject the
name is the same either way.

(A draft may legitimately have *no* primary subject — it is a required
field, which is partly why the entry is still a draft. Those simply do
not appear on subject-scoped surfaces; that is expected, not a bug.)
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.user_db import UserDatabase


# ---------------------------------------------------------------- fixture


@pytest.fixture
def seed(tmp_path):
    """One exam, one source, one session, three entries.

    ``DP Cardio``  → 1 completed entry
    ``DP Renal``   → 2 draft entries

    Returns a dict of the ids each test needs.
    """
    db = UserDatabase(tmp_path / "draft_policy.db", user_id=1, username="dp_user")

    exam = db.create_exam_context(
        exam_name="Draft Policy Exam",
        exam_description="issue #12 — draft policy per surface",
        hierarchy_levels=["System", "Topic"],
    )
    dimension_id = db.create_dimension(
        exam_id=exam.id,
        name="Systems",
        description="Body system",
        display_order=1,
    )

    root = db.create_subject_node(
        exam_context=exam.exam_name,
        name="DP Body Systems",
        level_type="System",
        exam_weight_low=40,
        exam_weight_high=40,
        dimension_id=dimension_id,
    )
    cardio = db.create_subject_node(
        exam_context=exam.exam_name,
        name="DP Cardio",
        level_type="Topic",
        parent_id=root.id,
        exam_weight_low=20,
        exam_weight_high=20,
        dimension_id=dimension_id,
    )
    renal = db.create_subject_node(
        exam_context=exam.exam_name,
        name="DP Renal",
        level_type="Topic",
        parent_id=root.id,
        exam_weight_low=10,
        exam_weight_high=10,
        dimension_id=dimension_id,
    )

    source = db.create_question_source(
        source_name="DP Question Bank",
        source_type="online_platform",
        exam_context=exam.exam_name,
    )
    session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=3,
        total_incorrect=3,
        question_source_id=source.id,
        session_name="DP session",
        date_encountered=date.today(),
    )

    # A complete entry: reflection + explanation + a primary subject.
    completed = db.create_question_entry(
        review_session_id=session.id,
        user_answer="A",
        correct_answer="B",
        perceived_difficulty=3,
        reflection="I misread the vignette.",
        explanation="Preload vs afterload.",
        primary_subject_ids=[cardio.id],
    )
    # Two drafts: no reflection, so ``is_draft`` is set — but each still
    # carries its primary subject mapping.
    drafts = [
        db.create_question_entry(
            review_session_id=session.id,
            user_answer="A",
            correct_answer="C",
            perceived_difficulty=5,
            explanation="Something about the nephron.",
            primary_subject_ids=[renal.id],
        )
        for _ in range(2)
    ]

    # Guard the seed itself. If create_question_entry's draft rule ever
    # changes, every assertion below would pass vacuously.
    assert completed.is_draft is False or completed.is_draft == 0
    for draft in drafts:
        assert draft.is_draft, "seed produced a completed entry, not a draft"
    mapped = db.fetchone(
        "SELECT COUNT(*) AS n FROM entry_subject_mappings esm "
        "JOIN question_entries qe ON qe.id = esm.question_entry_id "
        "WHERE qe.is_draft = TRUE AND esm.mapping_type = 'primary'"
    )
    assert mapped["n"] == 2, "drafts must carry a primary subject mapping"

    yield {
        "db": db,
        "exam_id": exam.id,
        "exam_name": exam.exam_name,
        "dimension_id": dimension_id,
        "root_id": root.id,
        "cardio_id": cardio.id,
        "renal_id": renal.id,
        "source_id": source.id,
        "session_id": session.id,
    }
    db.close()


# ======================================================= aligned up (#12)
#
# These three surfaces carried ``AND qe.is_draft = FALSE`` and now do not.


@pytest.mark.database
def test_weight_quadrant_counts_drafts(seed):
    """Surface: weight quadrant (``get_subject_exam_weight_analysis``)."""
    payload = seed["db"].get_subject_exam_weight_analysis(seed["exam_id"])
    by_name = {s["subject_name"]: s for s in payload["subjects"]}

    assert by_name["DP Renal"]["mistake_count"] == 2, (
        "the weight quadrant dropped the two drafts on DP Renal; a subject "
        "whose only entries are drafts must not read as a solved topic"
    )
    assert payload["total_mistakes"] == 3


@pytest.mark.database
def test_source_comparison_counts_drafts(seed):
    """Surface: source comparison (``get_source_comparison``).

    Also pins ``_get_top_subject_for_source``, which carried the same
    filter: DP Renal (2 drafts) outranks DP Cardio (1 completed) only if
    drafts count.
    """
    payload = seed["db"].get_source_comparison(exam_context_id=seed["exam_id"])
    by_name = {s["source_name"]: s for s in payload["sources"]}

    assert payload["total_entries"] == 3, (
        "source comparison dropped the drafts from the entry totals"
    )
    assert by_name["DP Question Bank"]["entry_count"] == 3
    assert by_name["DP Question Bank"]["top_subject"] == "DP Renal", (
        "_get_top_subject_for_source still excludes drafts, so the source's "
        "top subject named the completed entry's subject instead"
    )


@pytest.mark.database
def test_performance_over_time_counts_drafts(seed):
    """Surface: performance over time (``get_performance_over_time``)."""
    periods = seed["db"].get_performance_over_time(
        exam_context_id=seed["exam_id"], period="weekly", weeks=4
    )

    assert sum(p["entry_count"] for p in periods) == 3, (
        "the activity trend dropped the drafts, so a week spent logging "
        "drafts reads as a week with no activity: "
        f"{periods!r}"
    )


# ==================================================== already correct (#12)
#
# These surfaces already counted drafts. The decision aligns the ones
# above *up* to match them, so these assertions are what stops a future
# change aligning everything down instead.


@pytest.mark.database
def test_top_subjects_counts_drafts(seed):
    """Surface: Top Subjects (``get_subject_analytics``)."""
    rows = seed["db"].get_subject_analytics(exam_context_id=seed["exam_id"])
    by_name = {r["subject_name"]: r for r in rows}

    assert by_name["DP Renal"]["mistake_count"] == 2


@pytest.mark.database
def test_subject_sunburst_counts_drafts(seed):
    """Surface: subject sunburst.

    Its per-position counts come from the bridge helper
    ``_get_subject_mistake_buckets`` (``src/app/bridge_domains/_serializers.py``),
    not from a database mixin, so the assertion has to go through a
    bridge. No ``QApplication`` is needed for that.
    """
    from app.bridge import DatabaseBridge

    bridge = DatabaseBridge(user_db=seed["db"])
    buckets = bridge._get_subject_mistake_buckets(seed["exam_id"])

    # Both drafts are undisambiguated (no primary_parent_id), so they sit
    # in the None bucket, which belongs at every position.
    assert buckets.get(seed["renal_id"], {}).get(None) == 2


@pytest.mark.database
def test_dimension_sunburst_counts_drafts(seed):
    """Surface: dimension sunburst
    (``get_subject_hierarchy_with_mistakes_by_dimension``)."""
    tree = seed["db"].get_subject_hierarchy_with_mistakes_by_dimension(
        exam_context_id=seed["exam_id"], dimension_id=seed["dimension_id"]
    )

    def find(node, node_id):
        if node.get("id") == node_id:
            return node
        for child in node.get("children", []):
            hit = find(child, node_id)
            if hit:
                return hit
        return None

    renal = find({"children": tree["children"]}, seed["renal_id"])
    assert renal is not None, f"DP Renal missing from the dimension tree: {tree!r}"
    assert renal["direct_mistakes"] == 2
    assert tree["value"] == 3


@pytest.mark.database
def test_dimension_performance_counts_drafts(seed):
    """Surface: ``dimensions.py`` (``get_dimension_performance``).

    This is the one commit ``d3690b0`` briefly filtered and then
    reverted. The decision makes the revert permanent.
    """
    payload = seed["db"].get_dimension_performance(
        exam_context_id=seed["exam_id"], dimension_id=seed["dimension_id"]
    )
    by_name = {n["name"]: n for n in payload["nodes"]}

    assert by_name["DP Renal"]["direct_entries"] == 2
    assert payload["total"] == 3


@pytest.mark.database
def test_subject_deep_dive_counts_drafts(seed):
    """Surface: subject deep dive (``get_subject_deep_dive``)."""
    payload = seed["db"].get_subject_deep_dive(
        subject_id=seed["renal_id"], exam_context_id=seed["exam_id"]
    )

    assert payload["total_mistakes"] == 2
    assert payload["direct_mistakes"] == 2


@pytest.mark.database
def test_related_subjects_counts_drafts(seed):
    """Surface: related subjects (``get_related_subjects``)."""
    related = seed["db"].get_related_subjects(
        subject_id=seed["cardio_id"], exam_context_id=seed["exam_id"]
    )
    by_name = {r["name"]: r for r in related}

    assert "DP Renal" in by_name, f"DP Renal not offered as related: {related!r}"
    assert by_name["DP Renal"]["entry_count"] == 2


# ============================================================ goals (#12)


@pytest.mark.database
def test_goal_entry_count_still_excludes_drafts(seed):
    """Surface: goals — the exception to the policy.

    ``_count_entries_in_period`` is the counter behind entry-shaped goal
    progress. "Log 20 entries this week" means 20 *finished* entries, so
    this one keeps its ``is_draft = FALSE``.
    """
    db = seed["db"]
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    assert db._count_entries_in_period(week_start, week_end, seed["exam_id"]) == 1, (
        "goals must keep excluding drafts — only the completed entry counts"
    )


@pytest.mark.database
def test_goals_report_outstanding_drafts(seed):
    """Surface: goals — the qualifier the decision requires.

    "A goal that silently ignores three drafts is the same information
    gap this issue is about, just moved." So the goal payload carries the
    outstanding draft count alongside the progress, and the widget
    renders it as "N drafts remaining".
    """
    db = seed["db"]
    db.set_weekly_goal(target_questions=20, exam_context_id=seed["exam_id"])

    goals = db.get_user_goals(exam_context_id=seed["exam_id"])
    assert len(goals) == 1, f"expected the one weekly goal, got {goals!r}"
    goal = goals[0]

    assert "drafts_remaining" in goal, (
        "goal payload has no drafts_remaining qualifier, so the student is "
        "shown progress that silently ignores their unfinished drafts"
    )
    assert goal["drafts_remaining"] == 2
    # And the progress itself is untouched by the drafts: one finished
    # entry counts, the two drafts do not.
    #
    # This read 3 (the session's question total) until issue #58 routed
    # ``weekly_entries`` goals to ``_count_entries_in_period``. Adding the
    # qualifier did not change what progress means -- #58 did, and the
    # draft exclusion only became reachable at all once it had.
    assert goal["current_value"] == 1, (
        "weekly goals count entries logged, and only the finished one "
        f"counts: {goal!r}"
    )
