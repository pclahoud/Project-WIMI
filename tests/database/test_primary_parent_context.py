"""Tests for ``entry_subject_mappings.primary_parent_id`` semantics.

Exercises §5.4 of ``docs/planning/POLYHIERARCHY_MIGRATION.md``: when
``primary_parent_id`` is set on a mapping, the entry rolls up *only*
through that parent's ancestors, not through every ancestor reachable
from the leaf. When ``primary_parent_id IS NULL`` (the default), the
entry uses OMOP-style rollup through all ancestors.

The DAG used by most tests:

::

           A
          / \\
         B   C
          \\ /
           D   (D has parents B and C, both rooted in A)
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase


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
        username="ppc_user",
        display_name="Primary Parent Context User",
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


def _make_node(user_db, name: str) -> int:
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, sort_order, status) "
        "VALUES (?, ?, ?, NULL, 0, 'active')",
        ("USMLE", name, "Topic"),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _make_session(user_db) -> int:
    """Provision an exam_context row + a review_sessions row."""
    ec_row = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = 'USMLE'"
    )
    if ec_row is None:
        cursor = user_db.execute(
            "INSERT INTO exam_contexts (user_id, exam_name, exam_description) "
            "VALUES (?, 'USMLE', 'Test')",
            (user_db.user_id,),
        )
        ec_id = cursor.lastrowid
    else:
        ec_id = ec_row['id']
    cursor = user_db.execute(
        "INSERT INTO review_sessions "
        "(user_id, session_name, date_encountered, exam_context_id, "
        " total_questions, total_incorrect) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_db.user_id, "Test session", date.today().isoformat(), ec_id, 1, 1),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _log_entry(user_db, session_id, subject_node_id, primary_parent_id=None, entry_order=1):
    cursor = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?)",
        (session_id, entry_order, "A", "B"),
    )
    entry_id = cursor.lastrowid
    user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
        "VALUES (?, ?, 'primary', ?)",
        (entry_id, subject_node_id, primary_parent_id),
    )
    user_db.conn.commit()
    return entry_id


def _build_diamond(user_db):
    """Build the ``A → {B, C} → D`` DAG and return the node ids."""
    a = _make_node(user_db, "A")
    b = _make_node(user_db, "B")
    c = _make_node(user_db, "C")
    d = _make_node(user_db, "D")
    user_db.add_edge(a, b, is_primary=True)
    user_db.add_edge(a, c, is_primary=True)
    user_db.add_edge(b, d, is_primary=True)
    user_db.add_edge(c, d, is_primary=False)
    return a, b, c, d


def _count_under(user_db, root_id):
    """Count entries that roll up to ``root_id`` honoring §5.4 semantics.

    Replicates the ``primary_parent_id``-aware predicate added to the
    descendant-CTE callers (``analytics_advanced.get_subject_deep_dive``,
    ``entries.get_entries_paginated``). Kept inline here so the tests
    fail loudly if the public callers regress and the predicate
    diverges from the canonical shape documented in the migration plan.
    """
    cte = user_db._build_descendant_cte(root_id)
    row = user_db.fetchone(
        f"""
        {cte}
        SELECT COUNT(DISTINCT esm.question_entry_id) AS c
        FROM entry_subject_mappings esm
        WHERE
            (esm.primary_parent_id IS NULL
             AND esm.subject_node_id IN (SELECT id FROM descendants))
            OR
            (esm.primary_parent_id IS NOT NULL
             AND esm.primary_parent_id IN (SELECT id FROM descendants))
        """
    )
    return row['c']


# ---------------------------------------------------------------- tests


def test_null_primary_parent_rolls_up_through_all_ancestors(user_db):
    """primary_parent_id=NULL → OMOP rollup. Entry on D counts under A,
    B, and C (all reachable ancestors).
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, d, primary_parent_id=None)

    assert _count_under(user_db, a) == 1
    assert _count_under(user_db, b) == 1
    assert _count_under(user_db, c) == 1
    assert _count_under(user_db, d) == 1


def test_set_primary_parent_scopes_rollup(user_db):
    """primary_parent_id=B → entry rolls up only through B's chain.

    A counts (B is in A's subtree); B counts (it IS the primary parent);
    C does NOT (the override blocks the C path even though C is a leaf
    parent of D).
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, d, primary_parent_id=b)

    assert _count_under(user_db, a) == 1   # B is in A's subtree
    assert _count_under(user_db, b) == 1   # primary parent itself
    assert _count_under(user_db, c) == 0   # blocked by override
    assert _count_under(user_db, d) == 0   # leaf is bypassed by override


def test_set_primary_parent_to_unrelated_subject(user_db):
    """primary_parent_id pointing at an unrelated subject — the DB allows
    it, even though it's logically wrong (D is not a descendant of an
    unrelated root).

    Documented behavior (per §5.4 plan): the entry counts under the
    primary_parent_id's subtree only — i.e., the user's explicit
    "context is X" claim wins over the leaf's actual graph position.
    The leaf and the leaf's actual ancestors do NOT count.
    """
    a, b, c, d = _build_diamond(user_db)
    # Build a completely separate root and leaf.
    e = _make_node(user_db, "E")
    f = _make_node(user_db, "F")
    user_db.add_edge(e, f, is_primary=True)

    session_id = _make_session(user_db)
    # Entry tagged on D, but the user asserts the *context* is F
    # (an unrelated subject).
    _log_entry(user_db, session_id, d, primary_parent_id=f)

    # The override: count under F's subtree only.
    assert _count_under(user_db, e) == 1   # F is in E's subtree
    assert _count_under(user_db, f) == 1   # primary parent itself
    # D's actual ancestors do NOT count.
    assert _count_under(user_db, a) == 0
    assert _count_under(user_db, b) == 0
    assert _count_under(user_db, c) == 0
    assert _count_under(user_db, d) == 0


def test_clearing_primary_parent_restores_default(user_db):
    """Set then clear primary_parent_id — entry counts under all
    ancestors again.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    entry_id = _log_entry(user_db, session_id, d, primary_parent_id=b)

    # Sanity: scoped to B's chain.
    assert _count_under(user_db, c) == 0

    # Clear it.
    user_db.execute(
        "UPDATE entry_subject_mappings SET primary_parent_id = NULL "
        "WHERE question_entry_id = ?",
        (entry_id,),
    )
    user_db.conn.commit()

    assert _count_under(user_db, a) == 1
    assert _count_under(user_db, b) == 1
    assert _count_under(user_db, c) == 1
    assert _count_under(user_db, d) == 1


# ---------------------- Stage 9 follow-up: deep-dive parent-context filter ----------------------
#
# Exercises the ``primary_parent_id`` parameter on
# ``get_subject_deep_dive``. Lenient semantic: entries with NULL
# ``esm.primary_parent_id`` pass through; entries with an explicit value
# must point at a node in the chosen parent's subtree.


def test_deep_dive_no_filter_matches_default(user_db):
    """Baseline — passing ``primary_parent_id=None`` produces the same
    payload as the legacy two-arg call."""
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=1)
    _log_entry(user_db, session_id, d, primary_parent_id=b, entry_order=2)

    default = user_db.get_subject_deep_dive(subject_id=a)
    explicit_none = user_db.get_subject_deep_dive(
        subject_id=a, primary_parent_id=None
    )

    assert default['total_mistakes'] == explicit_none['total_mistakes']
    assert default['direct_mistakes'] == explicit_none['direct_mistakes']


def test_deep_dive_filter_excludes_other_parent_context(user_db):
    """Filter=B excludes entries explicitly disambiguated to C.

    View A's deep-dive (root). Three entries on D: one NULL, one with
    primary_parent_id=B (Respiratory-style), one with
    primary_parent_id=C (Pregnancy-style). Default returns all three;
    filter=B returns NULL + B-tagged; filter=C returns NULL + C-tagged.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=1)
    _log_entry(user_db, session_id, d, primary_parent_id=b, entry_order=2)
    _log_entry(user_db, session_id, d, primary_parent_id=c, entry_order=3)

    default = user_db.get_subject_deep_dive(subject_id=a)
    filtered_b = user_db.get_subject_deep_dive(subject_id=a, primary_parent_id=b)
    filtered_c = user_db.get_subject_deep_dive(subject_id=a, primary_parent_id=c)

    assert default['total_mistakes'] == 3
    assert filtered_b['total_mistakes'] == 2  # NULL + B
    assert filtered_c['total_mistakes'] == 2  # NULL + C


def test_deep_dive_filter_lenient_null_passes_through(user_db):
    """NULL primary_parent_id entries are included under every filter
    choice — the selector is an implicit claim of context for ambiguous
    rows."""
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    # Two NULL-context entries on D; nothing else.
    _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=1)
    _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=2)

    filtered_b = user_db.get_subject_deep_dive(subject_id=a, primary_parent_id=b)
    filtered_c = user_db.get_subject_deep_dive(subject_id=a, primary_parent_id=c)

    assert filtered_b['total_mistakes'] == 2
    assert filtered_c['total_mistakes'] == 2


def test_deep_dive_filter_narrows_direct_mistakes(user_db):
    """The ``direct_mistakes`` stat (entries tagged ON the subject) is
    also narrowed by the filter — a context selection should affect the
    whole page, not just the aggregated rollup.

    Note: the legacy direct query (``WHERE esm.subject_node_id = ?``)
    does not enforce §5.4 polyhierarchy semantics, so the default
    direct count includes entries with any primary_parent_id. The
    Stage 9 follow-up filter is what introduces parent-context
    narrowing for direct counts.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    # Tag entries directly on B. One NULL, one to C
    # (cross-context — user said "this entry on B is in the C context").
    _log_entry(user_db, session_id, b, primary_parent_id=None, entry_order=1)
    _log_entry(user_db, session_id, b, primary_parent_id=c, entry_order=2)

    default = user_db.get_subject_deep_dive(subject_id=b)
    filtered_b = user_db.get_subject_deep_dive(subject_id=b, primary_parent_id=b)
    filtered_c = user_db.get_subject_deep_dive(subject_id=b, primary_parent_id=c)

    # Default: both entries count (direct query is legacy and doesn't
    # filter on primary_parent_id).
    assert default['direct_mistakes'] == 2
    # Filter=B: parent_context_descendants={B,D}. NULL passes;
    # C-tagged: C ∉ {B,D} → excluded. So 1.
    assert filtered_b['direct_mistakes'] == 1
    # Filter=C: parent_context_descendants={C,D}. NULL passes;
    # C-tagged: C ∈ {C,D} → passes. So 2.
    assert filtered_c['direct_mistakes'] == 2


# ---------------------- Stage 9 polish: orientation fields ----------------------
#
# Exercises ``path_via_parent`` and ``entries_scoped_elsewhere`` — the
# two payload fields that drive the dynamic breadcrumb and the
# explanatory banner on the subject deep-dive page.


def _name(user_db, node_id):
    row = user_db.fetchone(
        "SELECT name FROM subject_nodes WHERE id = ?", (node_id,)
    )
    return row['name'] if row else None


def test_deep_dive_path_via_parent_renders_for_chosen_route(user_db):
    """When a multi-parent leaf is viewed with primary_parent_id=B, the
    payload's path_via_parent should be the chain A > B > D (the path
    that routes through B), not the canonical primary path."""
    a, b, c, d = _build_diamond(user_db)

    via_b = user_db.get_subject_deep_dive(subject_id=d, primary_parent_id=b)
    via_c = user_db.get_subject_deep_dive(subject_id=d, primary_parent_id=c)

    expected_b = f"{_name(user_db, a)} > {_name(user_db, b)} > {_name(user_db, d)}"
    expected_c = f"{_name(user_db, a)} > {_name(user_db, c)} > {_name(user_db, d)}"
    assert via_b['path_via_parent'] == expected_b
    assert via_c['path_via_parent'] == expected_c


def test_deep_dive_path_via_parent_null_without_filter(user_db):
    """Without a parent filter, path_via_parent is null and the page
    falls back to full_path."""
    a, b, c, d = _build_diamond(user_db)
    payload = user_db.get_subject_deep_dive(subject_id=d)
    assert payload['path_via_parent'] is None
    assert payload['full_path']  # canonical path is still populated


def test_deep_dive_path_via_parent_null_for_unrelated_parent(user_db):
    """If the requested parent isn't actually on any path to the
    subject, return None — the page should fall back rather than
    render a misleading breadcrumb."""
    a, b, c, d = _build_diamond(user_db)
    unrelated = _make_node(user_db, "Unrelated Root")
    payload = user_db.get_subject_deep_dive(
        subject_id=d, primary_parent_id=unrelated
    )
    assert payload['path_via_parent'] is None


def test_deep_dive_entries_scoped_elsewhere_zero_without_filter(user_db):
    """Without a parent filter, the view shows every entry tagged on
    the subject (Show-everything-always semantic). Nothing is hidden,
    so scoped_elsewhere is 0 regardless of the entries' contexts."""
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=1)
    _log_entry(user_db, session_id, d, primary_parent_id=b, entry_order=2)
    _log_entry(user_db, session_id, d, primary_parent_id=c, entry_order=3)

    payload = user_db.get_subject_deep_dive(subject_id=d)
    assert payload['entries_scoped_elsewhere'] == 0


def test_deep_dive_entries_scoped_elsewhere_counts_under_filter(user_db):
    """When a parent context is active, scoped_elsewhere counts entries
    tagged on the subject whose explicit primary_parent_id routes
    through a different parent — those entries are visible on that
    parent's deep-dive but not on this view. The banner surfaces
    this count.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=1)
    _log_entry(user_db, session_id, d, primary_parent_id=b, entry_order=2)
    _log_entry(user_db, session_id, d, primary_parent_id=c, entry_order=3)

    # Filter=B: parent_context_descendants = {B, D}. The C-tagged
    # entry (primary=C) routes elsewhere → counted as scoped_elsewhere.
    via_b = user_db.get_subject_deep_dive(subject_id=d, primary_parent_id=b)
    assert via_b['entries_scoped_elsewhere'] == 1

    # Filter=C: parent_context_descendants = {C, D}. The B-tagged
    # entry routes elsewhere → counted.
    via_c = user_db.get_subject_deep_dive(subject_id=d, primary_parent_id=c)
    assert via_c['entries_scoped_elsewhere'] == 1


def test_deep_dive_show_everything_always_no_filter(user_db):
    """No-filter view shows every entry tagged on the subject —
    diverges from polyhierarchy §5.4 strict rollup by design (the
    deep-dive page is a *view*, not a rollup). Entries with explicit
    primary_parent are no longer scoped away from the leaf's own
    deep-dive.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    # 3 entries on D: NULL, primary=B, primary=C. Under old §5.4
    # strict, only the NULL entry would show on D's deep-dive. Under
    # the new "Show everything" semantic, all 3 show.
    _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=1)
    _log_entry(user_db, session_id, d, primary_parent_id=b, entry_order=2)
    _log_entry(user_db, session_id, d, primary_parent_id=c, entry_order=3)

    payload = user_db.get_subject_deep_dive(subject_id=d)
    assert payload['total_mistakes'] == 3
    assert payload['direct_mistakes'] == 3


def test_deep_dive_filter_includes_chosen_parent_entries(user_db):
    """When filter=P is active and an entry on the subject has
    primary_parent=P, that entry is INCLUDED in the view — this is
    the user-expected behavior that made the lenient-filter
    half-measure feel broken. The view shows NULL entries plus
    entries routing through P.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=1)
    _log_entry(user_db, session_id, d, primary_parent_id=b, entry_order=2)
    _log_entry(user_db, session_id, d, primary_parent_id=c, entry_order=3)

    via_b = user_db.get_subject_deep_dive(subject_id=d, primary_parent_id=b)
    via_c = user_db.get_subject_deep_dive(subject_id=d, primary_parent_id=c)

    # Filter=B: NULL entry + B-tagged entry = 2. C-tagged is hidden.
    assert via_b['total_mistakes'] == 2
    # Filter=C: NULL entry + C-tagged entry = 2. B-tagged is hidden.
    assert via_c['total_mistakes'] == 2
