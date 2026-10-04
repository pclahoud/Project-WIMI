"""Archiving a dimension takes its subject trees with it (#210).

`delete_dimension` was `DELETE FROM exam_dimensions`, and
`subject_nodes.dimension_id` was added by a bare `ALTER TABLE` with **no
FOREIGN KEY and no ON DELETE clause**. So every subject in the dimension was
left pointing at a row that no longer existed:

* absent from every dimension's view -- the dimension it names is not listed;
* absent from the no-dimension view -- `dimension_id` is not `NULL`, which is
  the predicate that path uses.

The rows survived, so no entry data was lost. **Reachability** was: the
subjects carried entries and could not be selected, renamed, re-weighted or
deleted through the tree editor. Irreversibly, with nothing said.

Two things these tests are shaped around.

**A status column alone does not fix it.** An archived dimension whose
subjects are still `'active'` leaves the same unreachable state, reached
differently -- so the cascade is asserted, not the flag. The last-dimension
case is its own test: archiving the last one flips `exam_uses_dimensions`
false, and the tree editor's plain path filters only on exam and status, so
an uncascaded archive would display the trees the student just archived.

**Partial adoption of a status column is worse than none.** There are read
sites in four files, two of them outside the dimensions domain. The sweep is
asserted by a source test, because a behavioural test can only cover the
paths someone thought to write.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / 'src'))

from database import MasterDatabase, UserDatabase  # noqa: E402

SRC = pathlib.Path(__file__).resolve().parents[2] / 'src'


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='dim_archive', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='dim_archive')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        db._ensure_phase7_schema()
        yield db
        db.close()
        master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context(exam_name='Issue 210')


def _dimension(user_db, exam, name, order):
    return user_db.create_dimension(exam_id=exam.id, name=name,
                                    display_order=order, is_required=True)


def _subject(user_db, exam, name, dimension_id, parent_id=None):
    return user_db.create_subject_node(
        exam_context=exam.exam_name, name=name, level_type='System',
        parent_id=parent_id, dimension_id=dimension_id)


def _status(user_db, node_id):
    return user_db.fetchone(
        'SELECT status FROM subject_nodes WHERE id = ?', (node_id,))['status']


# --------------------------------------------------------------------------
# The cascade
# --------------------------------------------------------------------------

@pytest.mark.database
def test_archiving_a_dimension_archives_its_subjects(user_db, exam):
    """The reported bug. The subject used to stay `active` and unreachable."""
    site = _dimension(user_db, exam, 'Site', 1)
    orphan = _subject(user_db, exam, 'Orphan Me', site)

    user_db.archive_dimension(site)

    assert _status(user_db, orphan.id) == 'archived'
    row = user_db.fetchone(
        'SELECT status FROM exam_dimensions WHERE id = ?', (site,))
    assert row['status'] == 'archived'


@pytest.mark.database
def test_a_whole_subtree_goes_not_just_the_root(user_db, exam):
    """The cascade runs `delete_subject_subtree`, so #15's fixpoint applies."""
    site = _dimension(user_db, exam, 'Site', 1)
    root = _subject(user_db, exam, 'Root', site)
    child = _subject(user_db, exam, 'Child', site, parent_id=root.id)
    grandchild = _subject(user_db, exam, 'Grandchild', site, parent_id=child.id)

    user_db.archive_dimension(site)

    for node in (root, child, grandchild):
        assert _status(user_db, node.id) == 'archived', f'{node.name} survived'


@pytest.mark.database
def test_another_dimensions_subjects_are_untouched(user_db, exam):
    """Negative control.

    Without it, a cascade that archived every subject in the exam would pass
    every other test here and quietly destroy the other axis.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    task = _dimension(user_db, exam, 'Task', 2)
    in_site = _subject(user_db, exam, 'Emergency', site)
    in_task = _subject(user_db, exam, 'Diagnosis', task)

    user_db.archive_dimension(site)

    assert _status(user_db, in_site.id) == 'archived'
    assert _status(user_db, in_task.id) == 'active', 'the other axis was archived'


@pytest.mark.database
def test_a_dimensionless_subject_is_untouched(user_db, exam):
    """`dimension_id IS NULL` belongs to no axis and must not travel."""
    site = _dimension(user_db, exam, 'Site', 1)
    legacy = user_db.create_subject_node(
        exam_context=exam.exam_name, name='Legacy', level_type='System')

    user_db.archive_dimension(site)

    assert _status(user_db, legacy.id) == 'active'


@pytest.mark.database
def test_archiving_the_last_dimension_still_cascades(user_db, exam):
    """The case that proves the cascade is not optional.

    Archiving the last dimension flips `exam_uses_dimensions` false, and the
    tree editor's plain path filters only on exam and status -- no dimension
    predicate. An uncascaded archive would display the trees the student just
    archived, flattened into one tree.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    subject = _subject(user_db, exam, 'Emergency', site)

    user_db.archive_dimension(site)

    assert user_db.exam_uses_dimensions(exam.id) is False
    assert _status(user_db, subject.id) == 'archived', (
        'the last dimension was archived without its tree, so the plain '
        'tree-editor path would now render it'
    )


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

@pytest.mark.database
def test_an_archived_dimension_disappears_from_the_reads(user_db, exam):
    site = _dimension(user_db, exam, 'Site', 1)
    task = _dimension(user_db, exam, 'Task', 2)

    user_db.archive_dimension(site)

    assert [d['id'] for d in user_db.get_exam_dimensions(exam.id)] == [task]
    assert user_db.get_dimension(site) is None
    assert user_db.get_dimension(task) is not None


@pytest.mark.database
def test_exam_uses_dimensions_ignores_archived_ones(user_db, exam):
    site = _dimension(user_db, exam, 'Site', 1)
    assert user_db.exam_uses_dimensions(exam.id) is True

    user_db.archive_dimension(site)

    assert user_db.exam_uses_dimensions(exam.id) is False


# --------------------------------------------------------------------------
# The journal
# --------------------------------------------------------------------------

@pytest.mark.database
def test_the_archive_is_journalled_and_names_its_subject_batches(user_db, exam):
    """One dimension event, N subject batches, related explicitly.

    #37 restores *a batch*, so restoring a dimension has to find exactly the
    subject batches this archive produced. "The batches created in the same
    second" is not a relation.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    _subject(user_db, exam, 'Root A', site)
    _subject(user_db, exam, 'Root B', site)

    result = user_db.archive_dimension(site)

    batch = user_db.fetchone(
        'SELECT * FROM dimension_delete_batches WHERE id = ?',
        (result['batch_id'],))
    assert batch is not None
    assert batch['dimension_id'] == site
    assert batch['dimension_name'] == 'Site'

    linked = user_db.fetchall(
        'SELECT subject_batch_id FROM dimension_delete_batch_subjects '
        'WHERE dimension_batch_id = ?', (result['batch_id'],))
    assert len(linked) == 2, 'one subject batch per root'
    assert {row['subject_batch_id'] for row in linked} == set(
        result['subject_batch_ids'])

    stamped = user_db.fetchone(
        'SELECT archived_batch_id FROM exam_dimensions WHERE id = ?', (site,))
    assert stamped['archived_batch_id'] == result['batch_id']


@pytest.mark.database
def test_archiving_an_archived_dimension_is_a_no_op(user_db, exam):
    """Mirrors #57 for subjects: no empty batch nobody owns."""
    site = _dimension(user_db, exam, 'Site', 1)
    user_db.archive_dimension(site)

    again = user_db.archive_dimension(site)

    assert again['batch_id'] is None
    assert user_db.fetchone(
        'SELECT COUNT(*) AS n FROM dimension_delete_batches')['n'] == 1


# --------------------------------------------------------------------------
# Atomicity and display_order
# --------------------------------------------------------------------------

@pytest.mark.database
def test_a_failure_leaves_neither_half_applied(user_db, exam):
    """One transaction.

    A dimension archived with its trees still active is the exact state the
    cascade exists to prevent, so a part-way failure must roll both back.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    subject = _subject(user_db, exam, 'Emergency', site)

    real_execute = user_db.execute

    def failing_execute(sql, params=()):
        if 'dimension_delete_batches' in sql:
            raise RuntimeError('injected failure after the subtree archive')
        return real_execute(sql, params)

    user_db.execute = failing_execute
    try:
        with pytest.raises(RuntimeError):
            user_db.archive_dimension(site)
    finally:
        user_db.execute = real_execute

    assert _status(user_db, subject.id) == 'active', (
        'the subject tree stayed archived after the dimension write failed')
    assert user_db.fetchone(
        'SELECT status FROM exam_dimensions WHERE id = ?', (site,)
    )['status'] == 'active'


@pytest.mark.database
def test_the_archived_dimension_frees_its_display_order(user_db, exam):
    """An archived row holding slot 1 would block a new dimension taking it.

    `UNIQUE(exam_id, display_order)` is checked against archived rows too --
    SQLite does not know about `status`.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    user_db.archive_dimension(site)

    replacement = _dimension(user_db, exam, 'Replacement', 1)

    assert replacement is not None
    parked = user_db.fetchone(
        'SELECT display_order FROM exam_dimensions WHERE id = ?', (site,))
    assert parked['display_order'] < 1, 'the archived row kept a positive slot'


@pytest.mark.database
def test_reorder_ignores_archived_dimensions(user_db, exam):
    """#211's reorder assigns 1..N over the **active** set.

    If it still demanded every row of the exam, an archived dimension would
    make every reorder fail its membership check.
    """
    site = _dimension(user_db, exam, 'Site', 1)
    task = _dimension(user_db, exam, 'Task', 2)
    system = _dimension(user_db, exam, 'System', 3)
    user_db.archive_dimension(site)

    user_db.reorder_dimensions(exam.id, [system, task])

    orders = {d['id']: d['display_order'] for d in user_db.get_exam_dimensions(exam.id)}
    assert orders == {system: 1, task: 2}


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------

@pytest.mark.database
def test_every_read_of_exam_dimensions_filters_on_status():
    """Partial adoption of a status column is worse than no status column.

    Miss one read site and an archived dimension still appears somewhere,
    silently. There are sites in four files and two are outside the dimensions
    domain -- `graph.py` and `relations.py` -- plus `_base.py`'s
    `_subject_with_dimension`, which is the easiest of the lot to miss.

    This is a source check in the spirit of `check_css_empty_selector.py`: the
    guarantee is "nowhere", and a behavioural test can only cover the paths
    someone thought to write.
    """
    offenders = []
    scanned = 0
    for path in (SRC / 'database').rglob('*.py'):
        if path.name.startswith('m0') or path.name == 'schema_migrations.py':
            continue  # DDL and migrations create the column, they do not read it

        tree = ast.parse(path.read_text(encoding='utf-8'))

        # Docstrings are prose and mention `DELETE FROM exam_dimensions` while
        # explaining that it is gone. Scanning raw text flagged three of them.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))

        # SQL reaches the driver as a string literal. Adjacent literals are
        # concatenated by the parser into one Constant, so a query split over
        # several source lines arrives here whole -- which is what makes
        # looking for `status` in the same literal sound.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings):
                continue
            if not re.search(r'(?:FROM|JOIN)\s+exam_dimensions\b', node.value):
                continue
            scanned += 1
            # One query has to see archived rows: the reorder's floor, which
            # exists precisely because archived dimensions are parked in the
            # negative range and an active row must not be shifted onto one.
            # The exemption is a marker in the SQL rather than a list in this
            # test, so the reader of the query sees it.
            if 'includes-archived' in node.value:
                continue
            if 'status' not in node.value:
                offenders.append(f'{path.relative_to(SRC)}:{node.lineno}')

    assert scanned > 5, (
        f'only {scanned} queries found -- the scan is not seeing the code it '
        'is supposed to police'
    )
    assert offenders == [], (
        'these read exam_dimensions without filtering on status, so an '
        f'archived dimension still appears there (#210): {offenders}'
    )
