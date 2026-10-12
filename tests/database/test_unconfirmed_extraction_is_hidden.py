"""An unconfirmed extracted relation is not shown (owner's decision, 2026-10-05).

#60 proposes relations by parsing the student's own explanation, and a proposal
becomes a `subject_relations` row the moment it is made -- m019 designed
``origin`` and ``confirmed_at`` for exactly that, and #14's own notes say so:
*"set at creation for origin='user' (writing the reason is the confirmation);
NULL for an unconfirmed extraction."*

The owner's decision is that such a row **does not appear on the subject deep
dive**. That follows #14's decision 10 (*a student who never touches this must
never notice it exists*) and decision 11 (*degrade to absent, not to an empty
card*): a panel listing machine guesses beside relations the student wrote
would breach both.

This file holds the behaviour and the sweep. The sweep is the valuable half,
for the reason `test_dimension_soft_delete.py` gives about its own status
column: **partial adoption is worse than none.** Miss one display read and an
unconfirmed proposal appears somewhere, silently, and the student cannot tell
it from something they endorsed.
"""
from __future__ import annotations

import ast
import re
import tempfile
from pathlib import Path

import pytest

from database.domains.relations import UNCONFIRMED_IS_HIDDEN
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

SRC = Path(__file__).resolve().parent.parent.parent / 'src'

#: Reads that deliberately see unconfirmed rows. Each needs a reason in the
#: source next to it, not only here -- the marker is what a reader finds.
#:
#: * the duplicate check and the candidate-picker exclusion, because m026's
#:   UNIQUE(from, to, relation_type_id) makes the row physically occupy the
#:   pair whether or not anybody can see it;
#: * the delete-batch journal, because archiving a subject must stamp its
#:   unconfirmed extractions too, and #37's restore replays that journal.
MARKER = 'includes-unconfirmed'

#: The same marker as a Python identifier. A name carrying it travels with
#: every interpolation of that fragment, however far from its definition the
#: query sits -- which a nearby comment does not: the picker builds three
#: queries from one `same_type_includes_unconfirmed` string and the third is
#: too far below the comment for any fixed window to reach.
MARKER_IDENT = MARKER.replace('-', '_')


def _is_marked(text: str) -> bool:
    return MARKER in text or MARKER_IDENT in text


def _render(node) -> str:
    """The SQL text of a literal, **f-strings included**.

    This is the fix for the first thing this sweep got wrong. An f-string is
    an ``ast.JoinedStr``, not a ``Constant``, so a literal scan does not see
    it at all -- and the two queries that actually adopted the predicate
    interpolate it, which means the first version of this test flagged exactly
    the code it was written to approve.

    A ``FormattedValue`` is rendered as its *expression source*, so a query
    interpolating ``UNCONFIRMED_IS_HIDDEN`` reads as carrying that name. That
    is the right signal: naming the one definition is better evidence than
    repeating its text, which is why the predicate is a constant.
    """
    if isinstance(node, ast.Constant):
        return node.value
    parts = []
    for piece in node.values:
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
            parts.append(piece.value)
        elif isinstance(piece, ast.FormattedValue):
            parts.append(ast.unparse(piece.value))
    return ''.join(parts)


def _sql_literals(path: Path):
    """Every SQL-bearing string in ``path`` that is not a docstring.

    Docstrings are prose and legitimately discuss `FROM subject_relations`
    while explaining these rules; scanning raw text flags them. Adjacent
    literals are concatenated by the parser, so a query split across source
    lines arrives whole.
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, (ast.Constant, ast.JoinedStr))):
                docstrings.add(id(first.value))

    # Constants nested INSIDE an f-string must not be yielded separately.
    # `ast.walk` returns both the JoinedStr and its pieces, so without this
    # every interpolated query was scanned twice: once whole, where the
    # predicate is visible and it passes, and once as the fragment holding
    # `FROM subject_relations`, where it is not and it fails. The second
    # reading reported the two queries that had correctly adopted the
    # predicate -- a sweep failing on the code it exists to approve.
    nested = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for piece in ast.walk(node):
                if piece is not node:
                    nested.add(id(piece))

    for node in ast.walk(tree):
        if id(node) in docstrings or id(node) in nested:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node, _render(node)
        elif isinstance(node, ast.JoinedStr):
            yield node, _render(node)


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------

def test_every_read_of_subject_relations_hides_unconfirmed_or_says_why():
    """A source check, in the spirit of ``check_css_empty_selector.py``.

    The guarantee is "nowhere", and a behavioural test can only cover the
    paths somebody thought to write. A read that wants unconfirmed rows is a
    decision; a read that forgot them is a defect, and the two are
    indistinguishable from the outside, which is why the marker is required
    rather than optional.
    """
    offenders = []
    scanned = 0

    for path in (SRC / 'database').rglob('*.py'):
        if path.name.startswith('m0'):
            continue  # migrations create the columns; they do not display them

        lines = path.read_text(encoding='utf-8').splitlines()

        for node, sql in _sql_literals(path):
            if not re.search(r'(?:FROM|JOIN)\s+subject_relations\b', sql):
                continue
            # A write is not a read. UPDATE/DELETE/INSERT act on rows the
            # caller already identified.
            if re.match(r'\s*(?:INSERT|UPDATE|DELETE)\b', sql, re.IGNORECASE):
                continue
            scanned += 1

            # A lookup by primary key cannot leak a row into a list: the
            # caller already named it.
            if re.search(r'WHERE\s+id\s*=\s*\?', sql):
                continue
            if 'UNCONFIRMED_IS_HIDDEN' in sql or 'confirmed_at IS NOT NULL' in sql:
                continue
            if _is_marked(sql):
                continue

            # The marker may be an SQL comment inside the query or a Python
            # comment above it. Both are what a reader actually sees, and
            # requiring it inside the string would mean writing `--` into
            # single-line concatenated SQL, which comments out the rest of
            # the statement. So look at the source around the literal.
            start = max(0, (node.lineno or 1) - 9)
            end = node.end_lineno or node.lineno or 1
            context = '\n'.join(lines[start:end])
            if _is_marked(context):
                continue

            offenders.append(f'{path.relative_to(SRC)}:{node.lineno}: '
                             f'{sql.strip()[:100]}')

    assert scanned >= 4, (
        f'the sweep found only {scanned} reads of subject_relations, which is '
        f'fewer than existed when it was written -- it has probably stopped '
        f'matching. Fix the pattern rather than trusting the pass.')
    assert not offenders, (
        'these reads of subject_relations neither hide unconfirmed '
        'extractions nor carry an ' + MARKER + ' marker saying why:\n  '
        + '\n  '.join(offenders))


def test_the_sweep_would_catch_a_read_that_forgot():
    """The control. Without it the sweep passes on a clean tree either way.

    `check_relations_runtime_imports.py` makes the same point about itself: on
    a tree with no violations, a neutered gate reports exactly what a working
    one reports.
    """
    forgot = (
        "SELECT r.id FROM subject_relations r "
        "WHERE r.from_subject_id = ?"
    )
    assert re.search(r'(?:FROM|JOIN)\s+subject_relations\b', forgot)
    assert 'confirmed_at IS NOT NULL' not in forgot
    assert not _is_marked(forgot)
    assert not re.search(r'WHERE\s+id\s*=\s*\?', forgot), (
        'the by-id exemption must not swallow a read filtered on a different '
        'column')


def test_the_predicate_never_hides_a_user_authored_relation():
    """The half that would be easy to get backwards.

    A user-authored relation is confirmed at creation, so a predicate written
    as `confirmed_at IS NOT NULL` alone would hide any legacy user row whose
    stamp is missing -- and #14's relations predate #60 entirely.
    """
    assert "origin <> 'extracted'" in UNCONFIRMED_IS_HIDDEN
    assert 'confirmed_at IS NOT NULL' in UNCONFIRMED_IS_HIDDEN
    assert ' OR ' in UNCONFIRMED_IS_HIDDEN, (
        'the two clauses must be alternatives: an extracted-and-confirmed row '
        'is shown, and a user row is shown whatever its stamp')


def test_the_two_spellings_are_one_predicate():
    """The aliased and unaliased forms must not drift apart.

    Two constants exist because the reads differ: the panel aliases
    ``subject_relations`` as ``r``, while the candidate picker's exclusion
    subqueries select from it alone, where ``r.`` would be a syntax error.
    Two hand-written predicates are two things to keep in step, so this says
    they are the same one.
    """
    from database.domains.relations import UNCONFIRMED_IS_HIDDEN_NO_ALIAS

    assert UNCONFIRMED_IS_HIDDEN_NO_ALIAS == UNCONFIRMED_IS_HIDDEN.replace('r.', '')
    assert 'UNCONFIRMED_IS_HIDDEN' in 'UNCONFIRMED_IS_HIDDEN_NO_ALIAS', (
        "the unaliased constant's NAME has to contain the aliased one's, "
        "because the sweep above renders an f-string interpolation as the "
        "name of what was interpolated -- that is how a query carrying this "
        "predicate is recognised as carrying it")


# --------------------------------------------------------------------------
# The behaviour
# --------------------------------------------------------------------------

@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=Path(tmpdir))
        user = master.create_user(
            username='unconfirmed_user', display_name='Unconfirmed',
            user_types=['student'])
        db = UserDatabase(
            db_path=master.ensure_user_database(user.id),
            user_id=user.id, username=user.username)
        try:
            yield db
        finally:
            db.close()
            master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context('USMLE').id


def _node(user_db, name: str) -> int:
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, "
        "sort_order, status) VALUES ('USMLE', ?, 'Topic', NULL, 0, 'active')",
        (name,))
    user_db.conn.commit()
    return cursor.lastrowid


@pytest.fixture
def two_subjects(user_db, exam):
    return (_node(user_db, 'Chronic hypertension'),
            _node(user_db, 'Hypertensive nephrosclerosis'))


def test_an_unconfirmed_extraction_is_absent_from_the_panel(
        user_db, two_subjects):
    a, b = two_subjects
    user_db.create_subject_relation(
        a, b, 'Chronic hypertension causes hypertensive nephrosclerosis.',
        origin='extracted')

    panel = user_db.get_subject_relations(a)

    assert panel['relations'] == [], (
        'an unconfirmed machine proposal appeared on the deep dive, which is '
        "the owner's decision of 2026-10-05 and #14's decisions 10 and 11")


def test_a_user_authored_relation_is_present(user_db, two_subjects):
    """The positive control. Without it the test above passes against a panel
    that renders nothing at all."""
    a, b = two_subjects
    user_db.create_subject_relation(
        a, b, 'Chronic hypertension causes hypertensive nephrosclerosis.')

    panel = user_db.get_subject_relations(a)

    assert len(panel['relations']) == 1
    assert panel['relations'][0]['origin'] == 'user'
