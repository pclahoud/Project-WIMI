"""Every root-finding query agrees what a root is (#260).

Three places asked "which subjects are roots?" and two answered differently
from the third:

| | roots are | filtered parent status? |
|---|---|---|
| `hierarchy.py:242` (tree editor load) | no incoming edge **at all** | no |
| `hierarchy.py:2506` (Q-budget walk) | no incoming edge **at all** | no |
| `dimensions.py:405` (#210's cascade) | no edge from an **active** parent | yes |

A node holding an edge from an *archived* parent was therefore invisible to
the first two: not a root, because it has an incoming edge; and not anybody's
child either, because traversal starts at roots and an archived parent is
never one.

**That is why #15 deletes archived-parent-to-surviving-child edges.** CLAUDE.md
states the mechanism -- *"neither a root nor anybody's child, i.e. invisible"*
-- so the project was already relying on it being true, and was destroying
structure (deleting the edge, journalling a snapshot so #37 could rebuild it)
to avoid a state a one-JOIN-longer query cannot reach.

Found while building #37's restore, which reopened the state: delete a child
(its edge survives, the parent is active), delete the parent (it survives
again, the child is not *surviving*), restore the child. The owner chose to
align the predicates rather than keep guarding the symptom.

The source sweep at the bottom is the load-bearing test. The behavioural ones
can only cover the paths someone thought to write, and the whole lesson of
#210 is that **partial adoption of a status filter is worse than none** --
miss one site and the inconsistency is silent again.
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


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='roots', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='roots')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        db._ensure_phase7_schema()
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context(exam_name='Issue 260')


def _node(user_db, exam, name, parent_id=None, dimension_id=None):
    # ``exam_context`` holds the exam **name**, which is what every
    # production caller passes and what `get_effective_question_counts`
    # resolves before matching. A fixture storing the id passes the tree
    # editor's query (it compares whatever is there) and silently returns
    # nothing from the Q-budget walk -- an unrepresentative fixture that
    # looks like a code bug.
    n = user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, parent_id=parent_id,
        level_type='System', dimension_id=dimension_id)
    return n.id if hasattr(n, 'id') else n


def _orphan_under_archived_parent(user_db, exam):
    """Build the state: `child` active, its only parent archived, edge intact.

    Reached the way #37's restore reaches it, rather than by writing rows --
    the point of this issue is that the state is *reachable*, so the setup
    should be too.
    """
    parent = _node(user_db, exam, 'Parent')
    child = _node(user_db, exam, 'Child', parent_id=parent)
    grandchild = _node(user_db, exam, 'Grandchild', parent_id=child)

    child_batch = user_db.delete_subject_subtree(child)['batch_id']
    user_db.delete_subject_subtree(parent)
    user_db.restore_subject_delete_batch(child_batch)

    assert user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?', (parent,))['status'] \
        == 'archived'
    assert user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?', (child,))['status'] \
        == 'active'
    assert user_db.fetchone(
        'SELECT 1 FROM subject_edges WHERE parent_id = ? AND child_id = ?',
        (parent, child)) is not None, 'the edge is what makes this the bug'
    return parent, child, grandchild


# ---------------------------------------------------------------------------
# One test per read site
# ---------------------------------------------------------------------------


def test_the_tree_editor_shows_a_node_whose_only_parent_is_archived(
    user_db, exam,
):
    """`hierarchy.py:242` -- the load path a student actually looks at."""
    _parent, _child, _grand = _orphan_under_archived_parent(user_db, exam)

    roots = [n.name for n in user_db.get_subject_hierarchy(exam.exam_name)]
    assert 'Child' in roots, (
        'the node is active and reachable by nothing else, so it must render '
        'at the top level rather than vanish'
    )
    assert 'Parent' not in roots, 'the archived parent is still hidden'


def test_the_q_budget_walk_reaches_a_node_whose_only_parent_is_archived(
    user_db, exam,
):
    """`hierarchy.py:2506` -- and this is the half with a cost attached.

    The walk emits one row per edge, starting from roots. A node that is not
    a root is never descended into, so before #260 its **whole subtree** was
    absent from the Q budget: the student saw subjects in the tree editor
    whose questions were allocated to nobody.

    Visible and counted have to be the same predicate, which is why both
    `hierarchy.py` sites changed together rather than just the display one.
    """
    _parent, child, grandchild = _orphan_under_archived_parent(user_db, exam)

    rows = user_db.get_effective_question_counts(exam.id)
    edges = {(r['parent_id'], r['child_id']) for r in rows}
    assert (child, grandchild) in edges, (
        'the orphaned root must be descended into, or its subtree gets no '
        'question allocation at all'
    )


def test_the_cascade_root_finder_already_agreed(user_db, exam):
    """`dimensions.py:405` -- the control, unchanged by #260.

    It had the parent-status join from the start (#210 wrote it that way on
    purpose), which is what made the disagreement visible. Asserted here so a
    future change cannot quietly bring it down to the weaker form and make all
    three consistent in the wrong direction.
    """
    dimension = user_db.create_dimension(
        exam_id=exam.id, name='System', display_order=1, is_required=True)
    dim_id = dimension.id if hasattr(dimension, 'id') else dimension

    parent = _node(user_db, exam, 'DimParent', dimension_id=dim_id)
    child = _node(user_db, exam, 'DimChild', parent_id=parent,
                  dimension_id=dim_id)
    # Archive the parent alone, leaving the child active with a dead edge.
    user_db.execute(
        "UPDATE subject_nodes SET status = 'archived' WHERE id = ?", (parent,))
    user_db.conn.commit()

    preview = user_db.get_dimension_delete_preview(dim_id)
    assert child in preview['root_node_ids'], (
        'a subject whose only parent is archived is a root to the cascade'
    )


# ---------------------------------------------------------------------------
# The guard against partial adoption (#210's lesson)
# ---------------------------------------------------------------------------


def test_every_root_finding_query_filters_on_the_parents_status():
    """A source check, in the spirit of `check_css_empty_selector.py`.

    The guarantee is *nowhere*: no query may decide that a node is not a root
    on the strength of an incoming edge without checking that the edge comes
    from an **active** parent. Miss one and the invisible state is reachable
    again through that path alone, silently -- which is exactly how this
    survived three separate reads of the delete code.

    Scoped to the shape that decides roothood: a `NOT EXISTS` over
    `subject_edges` correlated on `child_id`. An ordinary
    `JOIN subject_edges ON child_id = ...` finds the parents *of* a node and
    is a different question, so it is deliberately not policed here.
    """
    offenders = []
    scanned = 0
    for path in (SRC / 'database').rglob('*.py'):
        if path.name.startswith('m0') or path.name == 'schema_migrations.py':
            continue  # DDL, not reads

        tree = ast.parse(path.read_text(encoding='utf-8'))

        # Prose describes this predicate while explaining it; scanning raw
        # text flagged the docstrings of the very modules that fixed it.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings):
                continue
            sql = node.value
            if not re.search(r'NOT\s+EXISTS', sql, re.IGNORECASE):
                continue
            if not re.search(r'subject_edges', sql):
                continue
            if not re.search(r'child_id\s*=', sql):
                continue
            scanned += 1
            # Same exemption convention as #210's status sweep: a marker in
            # the SQL, so the reader of the query sees why. One query is
            # exempt today -- `get_paths_to_root`, whose whole upward walk is
            # status-blind, making a root-predicate-only fix incoherent.
            if 'includes-archived' in sql:
                continue
            if not re.search(r'status\s*=\s*.active.', sql):
                offenders.append(f'{path.relative_to(SRC)}:{node.lineno}')

    assert scanned >= 3, (
        f'only {scanned} root-finding queries found -- the scan is not seeing '
        'the code it is supposed to police (there were three when #260 was '
        'fixed)'
    )
    assert offenders == [], (
        'these decide roothood from an incoming edge without checking the '
        f"parent is active, so a node under an archived parent is invisible "
        f'there (#260): {offenders}'
    )
