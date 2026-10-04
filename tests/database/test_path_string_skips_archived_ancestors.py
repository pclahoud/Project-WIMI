"""The rendered path string agrees with `get_paths_to_root` (#301).

#262 filtered `EdgesMixin.get_paths_to_root` and `_primary_path_to_root`. It did
not touch `SharedHelpersMixin._build_subject_path`, whose affected-callers table
described as *"path helper fallback -- follows whatever the above decide"*. That
description matched the docstring and **not the code**: `_build_subject_path` has
its own independent upward walk with no status predicate in either of its two
steps, so on the #37-reachable state the two methods disagreed outright:

    Child       get_paths_to_root = [[Child]]          _build_subject_path = 'Parent > Child'
    Grandchild  get_paths_to_root = [[Child, Grand]]   _build_subject_path = 'Parent > Child > Grandchild'

One says the chain starts at `Child`; the other names the archived `Parent` as
its root -- and `_build_subject_path`'s answer is the string a student reads.

**Owner's decision, 2026-10-03, and it is neither option as the issue put
them:** filter archived ancestors so the path matches `get_paths_to_root`, AND
surface what was removed in a hover tooltip. Option 1's stated cost was that a
shortened path *"can look wrong without explaining why"*; the tooltip answers
that rather than accepting it. So: **one rule for the path, a second channel for
the caveat.**

Three things that fall out of it and are asserted here:

* The walk **returns what it removed**. `_build_subject_path_info` is the
  structured form; `_build_subject_path` is `['path']` off it. Re-walking
  unfiltered at each call site to recover the names would reintroduce exactly
  the disagreement this fixes.
* The omitted list is **empty unless something was actually dropped**, because a
  tooltip that always appears means nothing.
* The **legacy `subject_nodes.parent_id` fallback is filtered too.** The issue
  called it a second decision; it is the same decision reached through
  pre-m004 data, and leaving it would make the guarantee hold only for
  databases new enough to have `subject_edges`.

The source sweep at the bottom extends #262's guard to the **iterative** shape.
#262's sweep is scoped to recursive CTEs over `subject_edges` and therefore
could not see this walk at all -- it is a Python loop issuing one `fetchone` per
step, which is why #262's own sweep reported the tree clean while the bug was in
the file the sweep's helper lives beside.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys
import tempfile

import pytest

SRC = pathlib.Path(__file__).parent.parent.parent / 'src'
sys.path.insert(0, str(SRC))

from database import MasterDatabase, UserDatabase  # noqa: E402
from database.domains import _base as base_module  # noqa: E402


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='paths', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='paths')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context(exam_name='Issue 301')


def _node(user_db, exam, name, parent_id=None):
    n = user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, parent_id=parent_id,
        level_type='Topic')
    return n.id if hasattr(n, 'id') else n


def _status(user_db, node_id):
    return user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?', (node_id,))['status']


def _orphan_under_archived_parent(user_db, exam):
    """`Parent` archived, `Child` active, the edge between them intact.

    Built the way #37's restore reaches it rather than by writing rows, so the
    fixture is a state the product can actually be in: delete the child (its
    edge survives, the parent is active), delete the parent (it survives
    again), restore the child. Same helper shape as #262's and #260's files --
    deliberately duplicated rather than imported, because a shared fixture
    that changed would silently move three issues' contracts at once.
    """
    parent = _node(user_db, exam, 'Parent')
    child = _node(user_db, exam, 'Child', parent_id=parent)
    grandchild = _node(user_db, exam, 'Grandchild', parent_id=child)

    child_batch = user_db.delete_subject_subtree(child)['batch_id']
    user_db.delete_subject_subtree(parent)
    user_db.restore_subject_delete_batch(child_batch)

    assert _status(user_db, parent) == 'archived'
    assert _status(user_db, child) == 'active'
    assert _status(user_db, grandchild) == 'active'
    assert user_db.fetchone(
        'SELECT 1 FROM subject_edges WHERE parent_id = ? AND child_id = ?',
        (parent, child)) is not None, (
        'the surviving edge is what makes this the bug'
    )
    return parent, child, grandchild


# ---------------------------------------------------------------- behaviour

def test_the_path_string_does_not_name_an_archived_parent(user_db, exam):
    """The headline of #301: the string a student reads."""
    _parent, child, _grand = _orphan_under_archived_parent(user_db, exam)

    assert user_db._build_subject_path(child) == 'Child', (
        'the rendered path names a subject the tree no longer shows (#301)'
    )


def test_the_path_string_does_not_run_through_an_archived_ancestor(
    user_db, exam,
):
    """Two levels down -- the half a terminate-only filter cannot reach.

    This is #262's reasoning carried over: filtering only where the walk
    *stops* would still emit `Parent > Child > Grandchild`.
    """
    _parent, _child, grand = _orphan_under_archived_parent(user_db, exam)

    assert user_db._build_subject_path(grand) == 'Child > Grandchild'


def test_the_string_form_agrees_with_the_id_form(user_db, exam):
    """#301 is a *disagreement* bug, so assert the agreement, not a literal.

    A test pinning only the string would stay green if the id-returning
    helpers were later changed back, which is the state the issue is about.

    The exact counterpart is `_primary_path_to_root` (#262) -- both follow
    `is_primary` edges upward, so they must name the same chain. The looser
    comparison against `get_paths_to_root` is asserted alongside because that
    is the method #301's title names; it holds here because the fixture gives
    each node one parent, and `get_paths_to_root` puts the primary path first.
    """
    _parent, child, grand = _orphan_under_archived_parent(user_db, exam)

    def names_of(ids):
        return ' > '.join(
            user_db.fetchone(
                'SELECT name FROM subject_nodes WHERE id = ?', (nid,))['name']
            for nid in ids
        )

    for node in (child, grand):
        rendered = user_db._build_subject_path(node)
        assert rendered == names_of(user_db._primary_path_to_root(node)), (
            'the path string and the primary id path disagree about the '
            'chain, which is exactly what #301 is (the string is what a '
            'student reads)'
        )
        assert rendered == names_of(user_db.get_paths_to_root(node)[0])


def test_an_active_ancestor_is_still_named(user_db, exam):
    """The negative control. A filter that dropped everything would pass the
    three tests above and break every breadcrumb in the app."""
    root = _node(user_db, exam, 'Root')
    mid = _node(user_db, exam, 'Mid', parent_id=root)
    leaf = _node(user_db, exam, 'Leaf', parent_id=mid)

    assert user_db._build_subject_path(leaf) == 'Root > Mid > Leaf'


def test_the_named_subject_is_emitted_whatever_its_status(user_db, exam):
    """`get_paths_to_root` emits `child_id` regardless of status *because the
    caller named it*. The string form must agree, or the deep dive of an
    archived subject renders an empty breadcrumb."""
    root = _node(user_db, exam, 'Root')
    leaf = _node(user_db, exam, 'Leaf', parent_id=root)
    user_db.delete_subject_subtree(leaf)
    assert _status(user_db, leaf) == 'archived'

    assert user_db._build_subject_path(leaf) == 'Root > Leaf', (
        'the subject the caller asked about must still be named'
    )


# ---------------------------------------------- what was removed travels back

def test_the_walk_reports_the_ancestors_it_removed(user_db, exam):
    """The tooltip's data, and the reason this is one method rather than a
    second unfiltered walk at each call site."""
    _parent, child, _grand = _orphan_under_archived_parent(user_db, exam)

    info = user_db._build_subject_path_info(child)

    assert info['path'] == 'Child'
    assert info['omitted_ancestors'] == ['Parent'], (
        f"the archived ancestor's name has to reach the tooltip: {info}"
    )
    assert info['shortened'] is True


def test_an_unshortened_path_reports_nothing_omitted(user_db, exam):
    """An affordance that always appears means nothing (owner, 2026-10-03)."""
    root = _node(user_db, exam, 'Root')
    leaf = _node(user_db, exam, 'Leaf', parent_id=root)

    info = user_db._build_subject_path_info(leaf)

    assert info['path'] == 'Root > Leaf'
    assert info['omitted_ancestors'] == []
    assert info['shortened'] is False


def test_the_string_helper_is_the_structured_one(user_db, exam):
    """One walk, not two. If `_build_subject_path` kept its own copy of the
    traversal the two could drift, which is #301's own shape."""
    _parent, child, grand = _orphan_under_archived_parent(user_db, exam)

    for node in (child, grand):
        assert (user_db._build_subject_path(node)
                == user_db._build_subject_path_info(node)['path'])


def test_only_the_archived_ancestors_actually_dropped_are_named(
    user_db, exam,
):
    """Not every archived node in the tree -- only the ones this path lost.

    A sibling branch being archived has nothing to do with this subject's
    breadcrumb, and naming it in the tooltip would be noise that reads as
    information.
    """
    parent = _node(user_db, exam, 'Parent')
    child = _node(user_db, exam, 'Child', parent_id=parent)
    _elsewhere = _node(user_db, exam, 'Elsewhere')

    child_batch = user_db.delete_subject_subtree(child)['batch_id']
    user_db.delete_subject_subtree(parent)
    user_db.restore_subject_delete_batch(child_batch)
    user_db.delete_subject_subtree(_elsewhere)

    info = user_db._build_subject_path_info(child)
    assert info['omitted_ancestors'] == ['Parent'], (
        f'an unrelated archived subject leaked into the tooltip: {info}'
    )


def test_the_legacy_parent_id_fallback_is_filtered_too(user_db, exam):
    """The second unfiltered step #301 names, reached through pre-m004 data.

    A node whose parent is recorded **only** in the legacy
    `subject_nodes.parent_id` column (no `subject_edges` row) takes the
    fallback branch. Filtering the edge step alone would leave the guarantee
    true only for databases new enough to have the junction table -- and
    `_build_subject_path` is the one helper that still reads that column.
    """
    root = _node(user_db, exam, 'LegacyRoot')
    leaf = _node(user_db, exam, 'LegacyLeaf', parent_id=root)
    # Drop the m004 edge so the walk has to use subject_nodes.parent_id.
    user_db.execute('DELETE FROM subject_edges WHERE child_id = ?', (leaf,))
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?", (root,))
    user_db.conn.commit()

    info = user_db._build_subject_path_info(leaf)
    assert info['path'] == 'LegacyLeaf', (
        'the legacy parent_id step walked onto an archived node (#301)'
    )
    assert info['omitted_ancestors'] == ['LegacyRoot']


def test_an_archived_edge_parent_does_not_fall_through_to_the_legacy_column(
    user_db, exam,
):
    """The precedence half, and it is the one a reviewer would get wrong.

    `subject_nodes.parent_id` is a mirror that is **allowed to diverge** --
    `add_parent` writes edges and not the column, and this method's own
    docstring describes a node "whose primary edge no longer matches its
    legacy `parent_id`". So "no *live* primary parent" must not be treated
    as "the junction table has nothing to say": a node whose primary edge
    points at an archived parent would then cross to the stale mirror and
    report a chain no edge supports, which is the defect class
    `_get_descendant_node_ids`' docstring is wholly about.

    `subject_edges` having an archived answer IS an answer.
    """
    edge_parent = _node(user_db, exam, 'EdgeParent')
    other = _node(user_db, exam, 'MirrorParent')
    child = _node(user_db, exam, 'Child', parent_id=edge_parent)
    # Diverge the mirror, then archive the real (edge) parent.
    user_db.execute(
        'UPDATE subject_nodes SET parent_id = ? WHERE id = ?',
        (other, child))
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?",
        (edge_parent,))
    user_db.conn.commit()

    info = user_db._build_subject_path_info(child)
    assert info['path'] == 'Child', (
        'the walk crossed from subject_edges to the legacy parent_id mirror '
        f"and reported a chain no edge supports: {info}"
    )
    assert info['omitted_ancestors'] == ['EdgeParent'], (
        'and the tooltip must name the edge parent, not the mirror'
    )


def test_the_legacy_fallback_still_works_for_an_active_parent(user_db, exam):
    """Negative control for the test above: the fallback must still resolve."""
    root = _node(user_db, exam, 'LegacyRoot')
    leaf = _node(user_db, exam, 'LegacyLeaf', parent_id=root)
    user_db.execute('DELETE FROM subject_edges WHERE child_id = ?', (leaf,))
    user_db.conn.commit()

    assert user_db._build_subject_path(leaf) == 'LegacyRoot > LegacyLeaf'


# ------------------------------------------- the key the tooltip reads

def _entry_on(user_db, exam, subject_id):
    session = user_db.create_review_session(
        exam_context_id=exam.id, session_name='S1', total_questions=1,
        total_incorrect=1)
    entry = user_db.create_question_entry(
        review_session_id=session.id if hasattr(session, 'id') else session,
        user_answer='A', correct_answer='B',
        primary_subject_ids=[subject_id], reflection='why')
    return entry.id if hasattr(entry, 'id') else entry


def test_the_per_subject_dict_carries_the_names_when_shortened(
    user_db, exam,
):
    """`_subject_with_dimension` is the broadest payload carrying a path --
    every entry's subject list goes through it."""
    _parent, child, _grand = _orphan_under_archived_parent(user_db, exam)
    entry_id = _entry_on(user_db, exam, child)

    detail = user_db.get_entry_with_context(entry_id)
    subject = detail['entry']['primary_subjects'][0]

    assert subject['path'] == 'Child'
    assert subject['path_omitted_ancestors'] == ['Parent']


def test_the_per_subject_dict_omits_the_key_when_nothing_was_removed(
    user_db, exam,
):
    """The absence IS the "no tooltip" signal (owner: an affordance that
    always appears means nothing). Asserted as an absence rather than an
    empty list, because `[]` and `['Parent']` are both truthy keys to a
    reader who only checks `in`."""
    root = _node(user_db, exam, 'Root')
    leaf = _node(user_db, exam, 'Leaf', parent_id=root)
    entry_id = _entry_on(user_db, exam, leaf)

    subject = user_db.get_entry_with_context(
        entry_id)['entry']['primary_subjects'][0]

    assert subject['path'] == 'Root > Leaf'
    assert 'path_omitted_ancestors' not in subject


def test_the_deep_dive_payload_explains_its_shortened_path(user_db, exam):
    """#314 renders a parent path on three surfaces; this is the key it
    reads, and the reason #301 had to land first."""
    _parent, child, _grand = _orphan_under_archived_parent(user_db, exam)
    _entry_on(user_db, exam, child)

    payload = user_db.get_subject_deep_dive(child, exam.id)

    assert payload['full_path'] == 'Child'
    assert payload['path_omitted_ancestors'] == ['Parent']


def test_the_deep_dive_payload_says_nothing_when_the_path_is_whole(
    user_db, exam,
):
    """Negative control. Never an empty list -- `null`, one rule everywhere."""
    root = _node(user_db, exam, 'Root')
    leaf = _node(user_db, exam, 'Leaf', parent_id=root)
    _entry_on(user_db, exam, leaf)

    payload = user_db.get_subject_deep_dive(leaf, exam.id)

    assert payload['full_path'] == 'Root > Leaf'
    assert payload['path_omitted_ancestors'] is None


def test_the_deep_dive_key_follows_the_path_the_page_will_show(
    user_db, exam,
):
    """`subject_deep_dive.js` prefers `path_via_parent` over `full_path`, so
    the key has to be computed for whichever one is rendered -- otherwise
    choosing a parent context silently drops the explanation.

    `path_via_parent` comes from the #262-filtered `get_paths_to_root`, so it
    can be cut short by an archived ancestor of the *chosen parent*. Here
    `Mid` is the chosen context and `Top` above it is archived.
    """
    top = _node(user_db, exam, 'Top')
    mid = _node(user_db, exam, 'Mid', parent_id=top)
    leaf = _node(user_db, exam, 'Leaf', parent_id=mid)
    _entry_on(user_db, exam, leaf)
    # Archive `Top` alone, leaving `Mid` active under a dead edge -- the
    # #260/#262 state, reached directly because deleting `Top` would cascade.
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?", (top,))
    user_db.conn.commit()

    payload = user_db.get_subject_deep_dive(
        leaf, exam.id, primary_parent_id=mid)

    assert payload['path_via_parent'] == 'Mid > Leaf', (
        'the chosen-context path should already be filtered by #262'
    )
    assert payload['path_omitted_ancestors'] == ['Top'], (
        'choosing a parent context dropped the explanation, so the page '
        'shows a shortened path with nothing saying why (#301)'
    )


def test_top_subjects_carries_the_key_for_314(user_db, exam):
    """`get_subject_analytics` feeds the dashboard's Top Subject card, which
    #314 will render the parent path on.

    Nothing reads the key today (`analytics_preview.js` uses `full_path`
    only as a fallback for a missing name), so this test is the only thing
    stopping it being removed as unused before #314 arrives -- at which
    point the cheap alternative is a second unfiltered walk at the call
    site, i.e. #301 again.
    """
    _parent, child, _grand = _orphan_under_archived_parent(user_db, exam)
    _entry_on(user_db, exam, child)

    rows = user_db.get_subject_analytics(exam_context_id=exam.id)
    row = next(r for r in rows if r['subject_id'] == child)

    assert row['full_path'] == 'Child'
    assert row['path_omitted_ancestors'] == ['Parent']


def test_the_relations_panel_carries_the_other_subjects_names(
    user_db, exam,
):
    """The panel already labels the other subject's dimension when it
    differs; this is the same shape of caveat on its path."""
    _parent, child, _grand = _orphan_under_archived_parent(user_db, exam)
    here = _node(user_db, exam, 'Here')
    user_db.create_subject_relation(
        from_subject_id=here, to_subject_id=child,
        reason='they are related in the student view')

    panel = user_db.get_subject_relations(here)
    relation = panel['relations'][0]

    assert relation['other_subject_path'] == 'Child'
    assert relation['other_subject_path_omitted_ancestors'] == ['Parent']


def test_the_relations_panel_says_nothing_when_the_path_is_whole(
    user_db, exam,
):
    root = _node(user_db, exam, 'Root')
    leaf = _node(user_db, exam, 'Leaf', parent_id=root)
    here = _node(user_db, exam, 'Here')
    user_db.create_subject_relation(
        from_subject_id=here, to_subject_id=leaf,
        reason='they are related in the student view')

    relation = user_db.get_subject_relations(here)['relations'][0]

    assert relation['other_subject_path'] == 'Root > Leaf'
    assert relation['other_subject_path_omitted_ancestors'] is None


# ---------------------------------------------------------------- guards

def test_the_iterative_upward_walk_filters_the_parents_status():
    """A source check on `_build_subject_path`'s own two steps.

    Both of #301's unfiltered reads are in one function, and neither is a
    recursive CTE, so #262's sweep is structurally blind to them. Pinned by
    name as well as swept below, because this is the function the issue is
    about.
    """
    tree = ast.parse(
        pathlib.Path(base_module.__file__).read_text(encoding='utf-8'))
    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef)
         and n.name in ('_build_subject_path', '_build_subject_path_info')
         and any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                 and 'subject_edges' in c.value
                 for c in ast.walk(n))),
        None,
    )
    assert func is not None, (
        'no subject_edges query found in the path-building helpers; '
        're-point this guard'
    )

    sql = ' '.join(
        n.value for n in ast.walk(func)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and ('subject_edges' in n.value or 'subject_nodes' in n.value)
    )
    assert re.search(r"status\s*=\s*.active.", sql), (
        'the upward walk does not check that the parent is active, so the '
        'rendered path can name a subject the tree does not show, and it '
        'disagrees with get_paths_to_root (#301)'
    )


def test_every_iterative_primary_chain_walk_filters_the_parents_status():
    """The partial-adoption guard for the shape #262's sweep cannot see.

    Scoped to **a query inside a loop that climbs the primary edge chain**:
    `subject_edges`, `parent_id` selected, a `child_id =` predicate, and
    `is_primary`, lexically inside a `for`/`while`. That is the canonical
    breadcrumb walk whether or not SQLite's `WITH RECURSIVE` does the
    recursing, and it decides which subjects are named as another's
    ancestors -- the thing an archived node must not appear in.

    **Why `is_primary` is in the predicate rather than left out to catch
    more.** Dropping it widens the scan from 2 sites to 5, and the extra
    three are all in `subject_restore.py` and are all correct as they stand:
    `:354` is a `SELECT 1` existence check for `UNIQUE(parent_id, child_id)`,
    where status is not the question; `:372` and `:728` deliberately select
    `p.status` and reason about it in Python, because #37's planner has to
    know whether a restored node's parent is *still* archived (that is what
    makes it come back at the top level) and the Archived panel has to say
    so. Marking those three `includes-archived` would put a misleading
    comment about breadcrumbs in journal-replay code, so the predicate is
    narrowed instead and the three are named here. A non-primary multi-parent
    upward walk is a recursive CTE in practice and #262's sweep owns it.

    A one-step parent read outside a loop (`get_parents`,
    `get_edges_for_child` -- both already filtered by #57) is a different
    question and is deliberately not policed here. The `includes-archived`
    marker convention still applies if a real exception ever arrives, which
    is #260's and #210's convention and not a third one.
    """
    offenders = []
    exempt = []
    scanned = 0

    for path in sorted((SRC / 'database').rglob('*.py')):
        if path.name.startswith('m0') or path.name == 'schema_migrations.py':
            continue  # DDL, not reads

        tree = ast.parse(path.read_text(encoding='utf-8'))

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))

        for loop in ast.walk(tree):
            if not isinstance(loop, (ast.For, ast.While)):
                continue
            for node in ast.walk(loop):
                if not (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and id(node) not in docstrings):
                    continue
                sql = node.value
                if 'subject_edges' not in sql:
                    continue
                if not re.search(r'parent_id', sql):
                    continue
                if not re.search(r'child_id\s*=', sql):
                    continue
                if not re.search(r'is_primary', sql):
                    continue  # see the docstring; not an allowlist, a scope
                if re.search(r'WITH\s+RECURSIVE', sql, re.IGNORECASE):
                    continue  # #262's sweep owns that shape
                where = f'{path.relative_to(SRC)}:{node.lineno}'
                scanned += 1
                if 'includes-archived' in sql:
                    exempt.append(where)
                elif not re.search(r"status\s*=\s*.active.", sql):
                    offenders.append(where)

    assert scanned >= 2, (
        f'only {scanned} iterative upward walks found -- the scan is not '
        'seeing the code it polices. There were 2 when #301 was fixed: '
        '_base.py\'s _build_subject_path_info and edges.py\'s '
        '_primary_path_to_root.'
    )
    assert offenders == [], (
        'these ask subject_edges for a parent inside a loop without checking '
        'the parent is active, so the walk steps onto an archived subject and '
        f'names it as an ancestor (#301): {offenders}'
    )
    assert exempt == [], (
        'a deliberate exemption appeared. None is expected: an upward walk '
        f'that must see archived nodes needs a reason in the SQL. {exempt}'
    )
