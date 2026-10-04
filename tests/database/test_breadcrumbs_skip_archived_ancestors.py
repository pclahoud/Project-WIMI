"""A breadcrumb never names an archived subject (#262).

`EdgesMixin.get_paths_to_root` walked `subject_edges` upward with no status
predicate in either half -- not in the recursive term and not in the root
predicate -- so for an active `Child` whose only parent `Parent` is archived it
returned `Parent -> Child`, naming a subject the tree no longer shows. #260
exempted it on purpose, because fixing only the root predicate would leave
paths running *through* archived ancestors and merely stop them somewhere else:
incoherent rather than incomplete.

**Both halves are filtered here, and so is `_primary_path_to_root`.** That
third one walks `is_primary` edges in a Python loop and is the partial-adoption
site inside the same method -- but its effect was *measured* rather than
assumed, and the measurement says less than expected: filtering it changes what
the helper returns (`[X, D]` becomes `[D]`) and changes `get_paths_to_root`'s
output in none of the three shapes tried, because a path naming an archived
node and a truncated prefix both fail the membership test against `all_paths`
identically and both fall through to `sorted(all_paths)`. It is filtered for
consistency and because its own contract is "the canonical breadcrumb path";
see `test_the_primary_path_helper_never_names_an_archived_subject`, which
asserts the guarantee that exists instead of the one that sounded better.

**Why this direction, rather than #262's option 2 or 3.** It is what the rest
of the codebase already decided, which is a stronger argument than a
preference:

* `relations.py::_ancestor_sets` -- the other upward walk over `subject_edges`
  -- has filtered on `p.status = 'active'` since it was written, and says why
  in its docstring: *"an edge from an archived node is not a live context"*.
* `#57` filtered the single-step parent reads (`get_parents`,
  `get_edges_for_child`), for a closely related reason: an archived parent at
  the head of that list became a new entry's default parent context.
* `#260` filtered the root predicates, so a node under an archived parent is
  already a legitimate top-level root everywhere else.

So `get_paths_to_root` and `_primary_path_to_root` were the last two reads in
that chain still answering differently from the other three.

**The cost #262 anticipated does not arise, and that is measured below rather
than argued.** The issue expected that "a node whose *only* route to a root
runs through an archived parent then has no path at all", and asked for a
count first. There is no such node: filtering the walk and the root predicate
*together* makes that node a root, so it gets the one-element path `[itself]`.
`test_no_active_subject_is_left_without_a_path` is the assertion, and it is
structural rather than a census -- the base case always emits, and a DAG walk
that moves must terminate at a node with no active parent.
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
from database.domains import edges as edges_module  # noqa: E402


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='crumbs', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='crumbs')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context(exam_name='Issue 262')


def _node(user_db, exam, name, parent_id=None):
    n = user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, parent_id=parent_id,
        level_type='Topic')
    return n.id if hasattr(n, 'id') else n


def _orphan_under_archived_parent(user_db, exam):
    """`Parent` archived, `Child` active, the edge between them intact.

    Built the way #37's restore reaches it rather than by writing rows, so the
    fixture is a state the product can actually be in: delete the child (its
    edge survives, the parent is active), delete the parent (it survives
    again), restore the child.
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
        (parent, child)) is not None, 'the surviving edge is what makes this the bug'
    return parent, child, grandchild


def _status(user_db, node_id):
    return user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?', (node_id,))['status']


# ---------------------------------------------------------------- behaviour

def test_an_archived_parent_is_not_named_in_a_path(user_db, exam):
    """The deep dive must not offer a context the student cannot select."""
    parent, child, _grand = _orphan_under_archived_parent(user_db, exam)

    paths = user_db.get_paths_to_root(child)

    assert paths == [[child]], (
        f'expected the child to be its own root, got {paths}'
    )
    assert all(parent not in path for path in paths), (
        'an archived subject is named as an ancestor, so the breadcrumb points '
        'at something the tree does not show and the "Show as part of" '
        'selector offers a context that cannot be chosen (#262)'
    )


def test_a_path_does_not_run_through_an_archived_ancestor(user_db, exam):
    """The half a root-predicate-only fix cannot reach (#260's reasoning).

    `Grandchild` is two levels down. Filtering only where a path *terminates*
    would still emit `Parent -> Child -> Grandchild`; it is the walk that has
    to stop.
    """
    parent, child, grandchild = _orphan_under_archived_parent(user_db, exam)

    paths = user_db.get_paths_to_root(grandchild)

    assert paths == [[child, grandchild]], (
        f'expected the chain to start at the surviving parent, got {paths}'
    )
    assert all(parent not in path for path in paths)


def test_an_active_parent_is_still_named(user_db, exam):
    """The positive control. Without it, "return nothing" would pass above."""
    root = _node(user_db, exam, 'Root')
    mid = _node(user_db, exam, 'Mid', parent_id=root)
    leaf = _node(user_db, exam, 'Leaf', parent_id=mid)

    assert user_db.get_paths_to_root(leaf) == [[root, mid, leaf]]


def test_an_archived_branch_is_dropped_and_the_live_one_kept(user_db, exam):
    """A second positive control, and it passes before the fix -- deliberately.

    `Leaf` has two parents and one is archived, which sounds like the bug but
    is not: #15 *removes* the edge from an archived parent to a surviving
    child, so there is nothing left for the walk to follow. It is here to pin
    that, because it is the reason the reachable form of #262 needs #37's
    restore to build it -- and because it would catch a fix that dropped the
    live branch along with the dead one.
    """
    live_parent = _node(user_db, exam, 'LiveParent')
    dead_parent = _node(user_db, exam, 'DeadParent')
    leaf = _node(user_db, exam, 'Leaf', parent_id=live_parent)
    user_db.add_edge(dead_parent, leaf)

    # Archive DeadParent alone. The cascade would archive `leaf` too if that
    # edge were its last, which is exactly why it has `live_parent`.
    user_db.delete_subject_subtree(dead_parent)
    assert _status(user_db, leaf) == 'active', 'the shared child must survive'

    paths = user_db.get_paths_to_root(leaf)
    assert paths == [[live_parent, leaf]], (
        f'expected only the surviving branch, got {paths}'
    )


def test_no_active_subject_is_left_without_a_path(user_db, exam):
    """#262's option 1 was blocked on this, and the answer is "none".

    The issue expected a node reachable only through an archived parent to end
    up with no path, and wanted the count measured before committing to this
    direction. Filtering the walk and the root predicate together makes that
    node a root instead, so it gets `[[itself]]`.

    Asserted over every active subject in the fixture rather than the one
    interesting node, because "every consumer needs a defined answer for the
    empty case" is only retired if the empty case cannot happen at all.
    """
    _orphan_under_archived_parent(user_db, exam)
    extra = _node(user_db, exam, 'Unrelated')
    user_db.add_edge(extra, _node(user_db, exam, 'UnrelatedChild'))

    active = [row['id'] for row in user_db.fetchall(
        "SELECT id FROM subject_nodes WHERE status = 'active'")]
    assert active, 'the fixture built nothing'

    for node_id in active:
        paths = user_db.get_paths_to_root(node_id)
        assert paths, f'subject {node_id} has no path to any root'
        assert all(path and path[-1] == node_id for path in paths), (
            f'every path must end at the subject asked about: {paths}'
        )


def _diamond_with_an_archived_extra_parent(user_db, exam):
    """Build:

        A (active)              X (archived)
        |      \\                   |
        C       B                  |
         \\     /                  |
          \\   /                   |
            D --------------------+

    `D`'s primary parent is `B`. `C` is created **before** `B`, so plain
    `sorted()` would put `[A, C, D]` first -- which is how the primary-first
    ordering can be lost without anything erroring.
    """
    a = _node(user_db, exam, 'A')
    x = _node(user_db, exam, 'X')
    c = _node(user_db, exam, 'C', parent_id=a)
    b = _node(user_db, exam, 'B', parent_id=a)
    assert c < b, 'the test needs C to sort before B'

    d = _node(user_db, exam, 'D', parent_id=b)       # primary edge B -> D
    user_db.add_edge(c, d)
    user_db.add_edge(x, d)                           # non-primary, archived
    user_db.conn.commit()
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?", (x,))
    user_db.conn.commit()
    return a, b, c, d, x


def test_the_primary_path_still_comes_first(user_db, exam):
    """The archived branch goes; the primary-first ordering stays.

    The ordering is the part a fix could plausibly break, because filtering
    the walk changes which tuples are in `all_paths` and the primary path has
    to still be one of them. `C` sorts before `B`, so a fix that dropped the
    primary-first step would hand back `[A, C, D]` and nothing would error --
    three consumers read the first path (the deep-dive breadcrumb, the
    analytics rollup label, `_build_path_via_parent`).
    """
    a, b, c, d, x = _diamond_with_an_archived_extra_parent(user_db, exam)

    paths = user_db.get_paths_to_root(d)

    assert all(x not in path for path in paths), (
        f'the archived parent is still in a path: {paths}'
    )
    assert paths[0] == [a, b, d], (
        f'the primary path must come first, got {paths}'
    )
    # Both live branches survive -- the fix drops the archived one only.
    assert sorted(paths) == sorted([[a, b, d], [a, c, d]])


def test_the_primary_path_helper_never_names_an_archived_subject(
    user_db, exam,
):
    """And this one is filtered for consistency, NOT for an observable bug.

    Measured, with the CTE already filtered: making `_primary_path_to_root`
    skip archived parents changes what the helper returns -- `[X, D]` becomes
    `[D]` -- and changes `get_paths_to_root`'s output in **none** of the three
    shapes tried (all-active; archived above `D`; archived above `B`). Both a
    path naming an archived node and a truncated prefix fail the membership
    test against `all_paths` identically, so both fall through to
    `sorted(all_paths)`.

    So the assertion is on the helper itself, which is the guarantee that
    actually exists: a method whose contract is "the canonical breadcrumb
    path" must not name a subject the tree does not show, and a second caller
    would otherwise inherit that. Writing this as an ordering test would be
    claiming a fix the measurement does not support.
    """
    _a, _b, _c, d, x = _diamond_with_an_archived_extra_parent(user_db, exam)

    # Make the archived edge the primary one, so the walk would step onto it.
    user_db.execute(
        'UPDATE subject_edges SET is_primary = 0 WHERE child_id = ?', (d,))
    user_db.execute(
        'UPDATE subject_edges SET is_primary = 1 '
        'WHERE child_id = ? AND parent_id = ?', (d, x))
    user_db.conn.commit()

    assert x not in user_db._primary_path_to_root(d), (
        'the is_primary walk steps onto an archived parent, so the "canonical '
        'breadcrumb path" names a subject the tree does not show (#262)'
    )
    assert user_db._primary_path_to_root(d) == [d], (
        'with its only primary parent archived the chain stops at the subject'
    )


# ---------------------------------------------------------------- guards

def test_the_primary_path_walk_filters_the_parents_status():
    """A targeted source check for the non-CTE half.

    The sweep below only sees recursive CTEs, and `_primary_path_to_root` is a
    Python loop issuing a one-step query. The behavioural test above can only
    catch it in the shape somebody thought to build, and this one is the whole
    method.
    """
    source = (SRC / 'database' / 'domains' / 'edges.py').read_text(
        encoding='utf-8')
    tree = ast.parse(source)
    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == '_primary_path_to_root'),
        None,
    )
    assert func is not None, '_primary_path_to_root is gone; re-point this guard'

    sql = ' '.join(
        n.value for n in ast.walk(func)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and 'subject_edges' in n.value
    )
    assert sql, 'no subject_edges query found in _primary_path_to_root'
    assert re.search(r"status\s*=\s*.active.", sql), (
        'the is_primary walk does not check that the parent is active, so '
        '"the canonical breadcrumb path" can name a subject the tree does '
        'not show (#262). Note this does NOT change get_paths_to_root\'s '
        'output -- measured -- so do not reach for an ordering test to '
        'cover it; see '
        'test_the_primary_path_helper_never_names_an_archived_subject.'
    )


def test_every_recursive_walk_over_subject_edges_filters_status():
    """The guard against partial adoption -- #210's lesson, #260's convention.

    Scoped to **recursive CTEs over `subject_edges`**, which is narrow enough
    to need no allowlist: a one-step edge read, an existence check and every
    write also mention `parent_id` and `child_id` and legitimately ignore
    status, so a broader rule would need a long list of exceptions and stop
    being a guard. A multi-hop walk is different in kind -- it decides which
    subjects are *related* to each other, and an archived node in the middle of
    one is a dead link in a live answer.

    Exemptions carry an `includes-archived` marker in the SQL itself, so the
    reader of the query sees the reason. There is exactly one, and it is a real
    decision rather than a leftover: `_would_create_cycle` must see archived
    nodes, because a cycle through an archived subject is still a cycle and
    #37's restore can bring that subject back.
    """
    offenders = []
    exempt = []
    seen = set()
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

        candidates = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings):
                candidates.append((node.lineno, node.value))
            elif isinstance(node, ast.JoinedStr):
                # An f-string's SQL arrives in pieces. `relations.py`'s
                # ancestor walk is built this way, and a scan that only read
                # `ast.Constant` would miss the one correctly-filtered upward
                # walk in the tree -- making this guard weaker than it claims
                # while its own count still looked healthy.
                literal = ' '.join(
                    v.value for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
                if literal:
                    candidates.append((node.lineno, literal))

        for lineno, sql in candidates:
            if not re.search(r'WITH\s+RECURSIVE', sql, re.IGNORECASE):
                continue
            if 'subject_edges' not in sql:
                continue
            where = f'{path.relative_to(SRC)}:{lineno}'
            # Deduplicate on (site, text). An f-string yields both its joined
            # literal and its individual `ast.Constant` parts, so a query whose
            # whole text sits in one part is otherwise counted twice and the
            # total below stops meaning anything.
            if (where, sql) in seen:
                continue
            seen.add((where, sql))
            scanned += 1
            if 'includes-archived' in sql:
                exempt.append(where)
            elif not re.search(r"status\s*=\s*.active.", sql):
                offenders.append(where)

    assert scanned >= 10, (
        f'only {scanned} recursive walks over subject_edges found -- the scan '
        'is not seeing the code it polices. There were exactly 10 when #262 '
        'was fixed: 2 in _base, 3 in analytics_advanced, 2 in dimensions, '
        '1 in relations and 2 in edges.'
    )
    assert offenders == [], (
        'these walk subject_edges recursively without filtering on the node '
        'status, so an archived subject can appear in the middle of a live '
        f'answer (#262): {offenders}'
    )
    assert len(exempt) == 1, (
        'the number of deliberate exemptions changed. One is expected '
        '(`_would_create_cycle`, which must see archived nodes). Adding '
        f'another needs a reason in the SQL: {exempt}'
    )
