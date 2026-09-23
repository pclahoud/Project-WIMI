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


def _exam_context_id(user_db) -> int:
    """The exam context ``_make_session`` provisions, for analytics calls."""
    row = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = 'USMLE'"
    )
    return row['id']


def _log_entry(user_db, session_id, subject_node_id, primary_parent_id=None,
               entry_order=1, mapping_type='primary'):
    cursor = user_db.execute(
        "INSERT INTO question_entries "
        "(review_session_id, entry_order, user_answer, correct_answer) "
        "VALUES (?, ?, ?, ?)",
        (session_id, entry_order, "A", "B"),
    )
    entry_id = cursor.lastrowid
    _tag_entry(user_db, entry_id, subject_node_id,
               primary_parent_id=primary_parent_id, mapping_type=mapping_type)
    return entry_id


def _tag_entry(user_db, entry_id, subject_node_id, primary_parent_id=None,
               mapping_type='primary'):
    """Add one mapping row to an existing entry.

    Split out of :func:`_log_entry` so a test can give one entry a
    'primary' tag on one subject and a 'secondary' ("also tested") tag on
    another -- ``idx_unique_entry_subject`` is UNIQUE on
    ``(question_entry_id, subject_node_id)`` and mapping_type agnostic, so
    the two tags must sit on different subjects.
    """
    user_db.execute(
        "INSERT INTO entry_subject_mappings "
        "(question_entry_id, subject_node_id, mapping_type, primary_parent_id) "
        "VALUES (?, ?, ?, ?)",
        (entry_id, subject_node_id, mapping_type, primary_parent_id),
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


# ------------------------------------------- update preserves the context


def _context_of(user_db, entry_id, subject_id):
    row = user_db.fetchone(
        "SELECT primary_parent_id FROM entry_subject_mappings "
        "WHERE question_entry_id = ? AND subject_node_id = ?",
        (entry_id, subject_id),
    )
    return row['primary_parent_id'] if row else None


def test_update_preserves_primary_parent_id(user_db):
    """Saving an entry must not reset the parent context to NULL.

    Regression. ``update_question_entry`` replaces subject mappings
    wholesale (DELETE + INSERT), but ``primary_parent_id`` is written by
    a *separate* call (``set_primary_parent_for_entry``) and used to be
    dropped by that replacement. The mapping row survived, so nothing
    looked broken -- the context was simply NULL again.

    The damage was silent and compounding: the entry form's
    ``syncTagContextChoices`` memoises what it last wrote and skips the
    round-trip when it matches, so from the second save onward nothing
    rewrote the column. A deliberate "this DVT is the pregnancy one"
    choice survived exactly one save.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)

    # Tag D under C specifically (not its canonical first parent B).
    entry_id = _log_entry(user_db, session_id, d, primary_parent_id=c)
    assert _context_of(user_db, entry_id, d) == c

    # An ordinary save that re-sends the same subject list.
    user_db.update_question_entry(
        entry_id,
        primary_subject_ids=[d],
        user_answer="edited once",
    )
    assert _context_of(user_db, entry_id, d) == c, (
        "primary_parent_id was dropped by update_question_entry. The "
        "mapping replacement must carry the existing value forward."
    )

    # And again -- the second save is where the client-side memo stops
    # rewriting, so this is the one that used to lose the data for good.
    user_db.update_question_entry(
        entry_id,
        primary_subject_ids=[d],
        user_answer="edited twice",
    )
    assert _context_of(user_db, entry_id, d) == c


def test_update_leaves_new_subject_context_null(user_db):
    """A subject added by the update has no prior context to preserve."""
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    entry_id = _log_entry(user_db, session_id, d, primary_parent_id=c)

    user_db.update_question_entry(entry_id, primary_subject_ids=[d, b])

    assert _context_of(user_db, entry_id, d) == c
    assert _context_of(user_db, entry_id, b) is None


def test_update_forgets_context_of_removed_subject(user_db):
    """Dropping a subject and re-adding it starts its context fresh.

    Preservation is per surviving row, not a cache keyed by subject: if
    the student untags a subject, the parent they had chosen for it is
    gone, and re-tagging should not silently resurrect it.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    entry_id = _log_entry(user_db, session_id, d, primary_parent_id=c)

    user_db.update_question_entry(entry_id, primary_subject_ids=[b])
    user_db.update_question_entry(entry_id, primary_subject_ids=[d])

    assert _context_of(user_db, entry_id, d) is None


# ------------------------------- entry browser: filtering honours §5.4


def _paginated_ids(user_db, **kwargs):
    """Entry ids from get_entries_paginated, which returns (entries, total)."""
    entries, _total = user_db.get_entries_paginated(**kwargs)
    return {e.id for e in entries}


def test_entry_filter_excludes_entries_scoped_to_another_parent(user_db):
    """Filtering by a subject must respect the entry's chosen context.

    ``get_entries_paginated`` is what the entry browser filters with. Its
    subject filter implements §5.4 via ``_primary_parent_scope_sql``: an
    entry tagged on shared leaf D counts toward branch B only if it was
    left unscoped, or was explicitly scoped into B.

    Nothing covered this before. The refactor onto the shared helper was
    verified by sabotaging the helper to implement only the NULL branch --
    the whole database suite stayed green, which is how this gap was
    found.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)

    scoped_to_c = _log_entry(user_db, session_id, d,
                             primary_parent_id=c, entry_order=1)
    unscoped = _log_entry(user_db, session_id, d,
                          primary_parent_id=None, entry_order=2)

    # Filtering by C: the C-scoped entry plus the unscoped one.
    via_c = _paginated_ids(user_db, subject_ids=[c], include_child_subjects=True)
    assert via_c == {scoped_to_c, unscoped}, (
        f"Filtering by C returned {via_c}; expected both the C-scoped "
        f"entry ({scoped_to_c}) and the unscoped one ({unscoped})."
    )

    # Filtering by B: only the unscoped entry. The C-scoped one is
    # anchored away from B even though D sits under both.
    via_b = _paginated_ids(user_db, subject_ids=[b], include_child_subjects=True)
    assert via_b == {unscoped}, (
        f"Filtering by B returned {via_b}; expected only the unscoped "
        f"entry ({unscoped}). The entry scoped to C must not surface "
        "under B -- that is the whole point of the tag context."
    )


def test_entry_filter_on_the_leaf_finds_entries_scoped_to_another_parent(user_db):
    """Filtering by the leaf finds entries whatever context they carry.

    Was a characterisation test of the opposite behaviour
    (``test_entry_filter_on_the_leaf_hides_scoped_entries``): both entries
    are tagged on D, and filtering the entry browser by D returned only the
    unscoped one, because the predicate asked whether the *chosen parent*
    (C) was in the filter scope, which for ``subject_ids=[d]`` it is not.
    So a student tagged a question with D, said "the C one", and could no
    longer find it by filtering for D.

    Settled by the owner in Forgejo #13 (2026-09-14): filtering by S returns
    entries tagged S directly **regardless of their chosen parent context**.
    §5.4 governs rollup *through ancestors*; D is not an ancestor here, it
    is the subject the entry actually carries. A parent context says which
    chain an entry rolls up through -- it does not make the entry stop
    being about D. The deep dive already reads it this way.

    Inverted rather than deleted, per the issue: it still pins the same
    situation, now with the decided answer.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    scoped = _log_entry(user_db, session_id, d, primary_parent_id=c, entry_order=1)
    unscoped = _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=2)

    found = _paginated_ids(user_db, subject_ids=[d])
    assert found == {scoped, unscoped}, (
        f"Expected both entries tagged on D ({scoped}, {unscoped}); got "
        f"{found}. If the C-scoped entry ({scoped}) is missing, the direct-tag "
        "branch of the browser's subject filter regressed -- see Forgejo #13."
    )

    # The same holds with the descendants toggle on: turning it on may only
    # add entries, never drop the ones tagged on the subject itself.
    with_children = _paginated_ids(
        user_db, subject_ids=[d], include_child_subjects=True
    )
    assert with_children == {scoped, unscoped}, with_children


# The three halves of what "filter by subject S" means, per the decision on
# Forgejo #13. Each is asserted on its own so a regression names itself.


def test_entry_filter_finds_entries_tagged_on_the_subject(user_db):
    """(a) Entries tagged S directly, with no parent context chosen.

    The uncontroversial half, and the one that always worked: a NULL
    context matches on the subject itself being in scope (§5.3, OMOP).
    Here so that (c) below is read as an *addition* to (a) rather than a
    replacement for it.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    on_d = _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=1)
    on_b = _log_entry(user_db, session_id, b, primary_parent_id=None, entry_order=2)

    assert _paginated_ids(user_db, subject_ids=[d]) == {on_d}
    assert _paginated_ids(user_db, subject_ids=[b]) == {on_b}


def test_entry_filter_rolls_descendants_up_through_the_chosen_parent(user_db):
    """(b) Entries on S's descendants, restricted to those routing through S.

    This is the §5.4 reading, and the part the decision explicitly did NOT
    relax: an entry on shared leaf D pinned to C rolls up through C's chain
    only, so filtering by B must not return it even though D sits under B
    too. The discriminator for the fix -- making the direct-tag branch
    match the whole descendant set instead of the named subjects would
    quietly break this.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    via_b = _log_entry(user_db, session_id, d, primary_parent_id=b, entry_order=1)
    via_c = _log_entry(user_db, session_id, d, primary_parent_id=c, entry_order=2)
    unscoped = _log_entry(user_db, session_id, d, primary_parent_id=None, entry_order=3)

    under_b = _paginated_ids(user_db, subject_ids=[b], include_child_subjects=True)
    assert under_b == {via_b, unscoped}, (
        f"Filtering by B returned {under_b}; the C-pinned entry ({via_c}) "
        "must not roll up through B."
    )

    under_c = _paginated_ids(user_db, subject_ids=[c], include_child_subjects=True)
    assert under_c == {via_c, unscoped}, under_c

    # ... and the root sees all three, since B and C are both in A's subtree.
    under_a = _paginated_ids(user_db, subject_ids=[a], include_child_subjects=True)
    assert under_a == {via_b, via_c, unscoped}, under_a


def test_entry_filter_finds_direct_tags_pinned_outside_the_filter_chain(user_db):
    """(c) Entries tagged S directly, pinned to a parent outside S's chain.

    The case that disappeared. D gains a third parent E under an unrelated
    root Z, and the entry is pinned to E -- a parent that is in no sense
    reachable from the filter subject. Filtering by D must still find it:
    the filter names the subject the entry carries.

    The second assertion keeps (c) from swallowing (b): the E-pinned entry
    must still be absent when filtering by B, which is a rollup question.
    """
    a, b, c, d = _build_diamond(user_db)
    z = _make_node(user_db, "Z")
    e = _make_node(user_db, "E")
    user_db.add_edge(z, e, is_primary=True)
    user_db.add_edge(e, d, is_primary=False)

    session_id = _make_session(user_db)
    pinned_elsewhere = _log_entry(user_db, session_id, d, primary_parent_id=e)

    found = _paginated_ids(user_db, subject_ids=[d])
    assert found == {pinned_elsewhere}, (
        f"Filtering by D returned {found}; the entry is tagged D and must be "
        "found there whatever parent context it carries (Forgejo #13)."
    )

    under_b = _paginated_ids(user_db, subject_ids=[b], include_child_subjects=True)
    assert under_b == set(), (
        f"Filtering by B returned {under_b}; an entry pinned to E rolls up "
        "through E's chain only."
    )


def test_secondary_tag_is_findable_but_not_counted(user_db):
    """Counting is primary-only; finding is all tags (Forgejo #13).

    The entry below was tagged "also tested: D" -- a *secondary* mapping.
    A student looking for their D questions wants it, so the entry
    browser's subject filter returns it. Top Subjects must not: it totals
    mistakes, and a shared subject inflating its own total through "also
    tested" tags is exactly the double count the primary-only rule exists
    to prevent.

    One test rather than two because the pair is the point: whichever side
    someone changes, this names the principle they broke.
    """
    a, b, c, d = _build_diamond(user_db)
    session_id = _make_session(user_db)
    exam_id = _exam_context_id(user_db)

    also_tested_d = _log_entry(user_db, session_id, c, entry_order=1)
    _tag_entry(user_db, also_tested_d, d, mapping_type='secondary')

    # Finding: the browser's subject filter returns it.
    assert also_tested_d in _paginated_ids(user_db, subject_ids=[d]), (
        "an 'also tested' tag on D must be findable by filtering for D -- "
        "browsing is retrieval, not measurement"
    )

    # Counting: Top Subjects does not.
    counted = {
        row['subject_id']: row['mistake_count']
        for row in user_db.get_subject_analytics(
            exam_context_id=exam_id, include_children=False
        )
    }
    assert counted.get(c) == 1, (
        f"sanity: C carries the primary tag and must be counted; got {counted!r}"
    )
    assert d not in counted, (
        f"D was counted as a mistake ({counted.get(d)!r}) off a secondary "
        "'also tested' tag. get_subject_analytics filters mapping_type = "
        "'primary' precisely so it cannot be; if this went red, a counting "
        "surface picked up the browser filter's semantics."
    )
