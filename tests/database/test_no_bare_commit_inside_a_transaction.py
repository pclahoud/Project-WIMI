"""No bare ``conn.commit()`` may be reachable from inside a transaction (#232).

`BaseDatabase.transaction` is re-entrant and its docstring used to say that
nothing in `src/database` breaks it. That sentence was false **twice**:

* **#211** — `dimensions.py` had six bare commits and no `self.transaction()`;
  `reorderDimensions` called `update_dimension` from inside a transaction, so
  the first iteration committed it.
* **#232** — `create_tag_group` calls `_ensure_phase4_schema()`
  unconditionally, two of whose helpers committed on *every* call, so
  `seed_default_tags`' transaction was ended from inside it.

Each time the sentence was the reason nobody looked. So the invariant is
checked here instead of asserted in prose.

**This is a call-graph test, not a grep.** #232 was two levels deep
(`create_tag_group -> _ensure_phase4_schema -> _ensure_richtext_json_columns`)
and a direct-call scan reported the tree clean. There is also a behavioural
test below, because a static test cannot prove the runtime guard works.

One recorded false start, so nobody repeats it: the first version of this scan
counted `transaction()` itself as a bare-commit method — it is one, and that
commit is the legitimate one — so every `with self.transaction():` matched its
own context expression and buried the real signal under 110 false positives.
`_TRANSACTION_MACHINERY` is that exclusion.
"""
from __future__ import annotations

import ast
import pathlib
import sqlite3
import sys
import tempfile
from collections import defaultdict

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / 'src'))

from database import MasterDatabase, UserDatabase  # noqa: E402

SRC = pathlib.Path(__file__).resolve().parents[2] / 'src'

#: These own the commit/rollback. Excluding them is not a loophole -- the
#: commit inside `transaction()` is the one every other commit is measured
#: against.
_TRANSACTION_MACHINERY = {
    'transaction', '__enter__', '__exit__', 'close', '_connect',
    # Depth-aware by construction: it commits only at depth 0, which is the
    # sanctioned way for a method called at both depths to persist its work.
    # Excluded from the committer set rather than allow-listed per caller,
    # because calling it is the *fix*, not an exception to the rule.
    '_commit_if_top_level',
}

#: Traversal stops here. Each entry is a claim that the path cannot fire, and
#: pruning rather than skipping is deliberate: if a node is unreachable then so
#: is everything it calls, and continuing would report its callees as separate
#: violations of a path that does not execute.
_PRUNED = {
    # `_dual_write_graph` returns early unless `self._graph_available`, which
    # is False in every environment since `real_ladybug` was removed and is
    # never coming back (it is not in requirements and must not be added).
    # Pruned rather than deleted because the guard is a runtime flag, not a
    # deletion -- if the graph layer ever returns, remove this and fix what
    # the test then reports.
    '_mark_graph_stale',
}


def _analyse():
    """(bare-commit methods, call graph, calls made inside transaction blocks)."""
    committers: dict[str, set[str]] = {}
    calls_of: dict[str, set[str]] = defaultdict(set)
    in_txn: list[tuple[str, int, str]] = []

    for path in SRC.rglob('*.py'):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:
            continue

        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for sub in ast.walk(fn):
                if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)):
                    continue
                calls_of[fn.name].add(sub.func.attr)
                is_bare_commit = (
                    sub.func.attr == 'commit'
                    and isinstance(sub.func.value, ast.Attribute)
                    and sub.func.value.attr == 'conn'
                )
                if is_bare_commit and fn.name not in _TRANSACTION_MACHINERY:
                    committers.setdefault(fn.name, set()).add(
                        str(path.relative_to(SRC.parent)))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            opens_txn = any(
                isinstance(item.context_expr, ast.Call)
                and getattr(item.context_expr.func, 'attr', None) == 'transaction'
                for item in node.items
            )
            if not opens_txn:
                continue
            # The BODY only. The context expression is `self.transaction()`
            # itself, and counting it is the false start in the module docstring.
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        in_txn.append((str(path.relative_to(SRC.parent)),
                                       sub.lineno, sub.func.attr))

    return committers, calls_of, in_txn


def _path_to_committer(start, calls_of, committers, max_depth=6):
    """Shortest call chain from ``start`` to a bare committer, or None."""
    seen = set()
    frontier = [(start, [start])]
    while frontier:
        name, trail = frontier.pop(0)
        if name in seen or len(trail) > max_depth:
            continue
        seen.add(name)
        if name in _PRUNED:
            continue            # unreachable, and so is everything below it
        if name in committers:
            return trail
        for callee in calls_of.get(name, ()):
            frontier.append((callee, trail + [callee]))
    return None


@pytest.mark.database
def test_no_transaction_reaches_a_bare_commit():
    """The invariant, checked transitively.

    A violation means a rollback in that transaction will report success and
    undo nothing -- the shape of both #211 and #232.
    """
    committers, calls_of, in_txn = _analyse()

    violations = []
    for file, line, called in in_txn:
        trail = _path_to_committer(called, calls_of, committers)
        if trail:
            where = ', '.join(sorted(committers[trail[-1]]))
            violations.append(f'{file}:{line}  {" -> ".join(trail)}  [{where}]')

    assert not violations, (
        'these transaction blocks can reach a bare conn.commit(), so their '
        'rollback is a no-op:\n  ' + '\n  '.join(sorted(set(violations)))
        + '\n\nUse self.transaction(), or _commit_if_top_level() for a method '
          'called at both depths. See #211 and #232.'
    )


@pytest.mark.database
def test_the_scan_can_actually_find_something():
    """Negative control.

    The test above passes trivially if the analysis returns nothing -- an
    import error, a renamed attribute, a walk that visits no files. This
    asserts the machinery still sees the code it is supposed to police.
    """
    committers, calls_of, in_txn = _analyse()

    assert len(committers) > 10, f'only found {len(committers)} bare-commit methods'
    assert len(in_txn) > 50, f'only found {len(in_txn)} calls inside transactions'
    assert 'transaction' not in committers, (
        'transaction() is being counted as a bare committer again; that is the '
        'false start recorded in this module docstring'
    )


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=pathlib.Path(tmpdir))
        user = master.create_user(username='commit_probe', display_name='Probe',
                                  user_types=['student'])
        db = UserDatabase(db_path=master.ensure_user_database(user.id),
                          user_id=user.id, username='commit_probe')
        db._ensure_phase2_schema()
        db._ensure_phase4_schema()
        yield db
        db.close()
        master.close()


def _tag_name_column(db):
    columns = [c['name'] for c in db.fetchall('PRAGMA table_info(tags)')]
    return 'tag_name' if 'tag_name' in columns else columns[1]


@pytest.mark.database
def test_creating_a_tag_group_inside_a_transaction_rolls_back(user_db):
    """#232's reproduction, at four lines.

    Before the fix this logged `Transaction failed, rolled back` and left the
    row in place -- a rollback that reported success and did nothing.
    """
    exam = user_db.create_exam_context(exam_name='Probe')
    column = _tag_name_column(user_db)

    with pytest.raises(RuntimeError):
        with user_db.transaction():
            user_db.create_tag_group(exam_context=exam.exam_name,
                                     group_name='Probe Group')
            raise RuntimeError('roll it all back')

    rows = user_db.fetchall(
        f"SELECT {column} FROM tags WHERE {column} = ?", ('Probe Group',))
    assert rows == [], 'the tag group survived a rolled-back transaction (#232)'


@pytest.mark.database
def test_creating_a_tag_group_at_the_top_level_still_persists(user_db):
    """Negative control, and the one that matters most here.

    A "fix" that simply stopped committing would pass the test above and break
    every first-run write in this mixin. Persistence is checked after a close
    and reopen, because an uncommitted row is still visible on the connection
    that wrote it.
    """
    exam = user_db.create_exam_context(exam_name='Probe')
    column = _tag_name_column(user_db)

    user_db.create_tag_group(exam_context=exam.exam_name, group_name='Top Level')
    db_path, user_id = user_db.db_path, user_db.user_id
    user_db.close()

    reopened = UserDatabase(db_path=db_path, user_id=user_id, username='commit_probe')
    try:
        rows = reopened.fetchall(
            f"SELECT {column} FROM tags WHERE {column} = ?", ('Top Level',))
        assert rows, 'a top-level create was not committed -- first run is broken'
    finally:
        reopened.close()


@pytest.mark.database
def test_commit_if_top_level_defers_to_an_open_transaction(user_db):
    """The helper's own contract, both directions."""
    assert user_db._txn_depth == 0
    with user_db.transaction():
        assert user_db._txn_depth == 1
        user_db._commit_if_top_level()
        assert user_db.conn.in_transaction, (
            '_commit_if_top_level committed while nested, which is the whole '
            'defect it exists to prevent'
        )


@pytest.mark.database
def test_a_schema_script_refuses_to_run_inside_a_transaction(user_db):
    """`executescript` commits implicitly, so it must not run nested.

    This is the half `_commit_if_top_level` cannot fix: the implicit commit
    happens inside `executescript` itself, before any commit of ours, so
    deferring ours would hide the problem rather than repair it.
    """
    from database.base_db import DatabaseIntegrityError

    with pytest.raises(DatabaseIntegrityError) as caught:
        with user_db.transaction():
            user_db._executescript_at_top_level('CREATE TABLE probe_t(x);', 'probe')

    assert '232' in str(caught.value)


@pytest.mark.database
def test_executescript_really_does_commit_implicitly():
    """The premise, measured rather than cited.

    If a future Python or SQLite stops doing this, the refusal above becomes
    unnecessary caution and someone should know that from a failing test
    rather than by reading the standard library.
    """
    conn = sqlite3.connect(':memory:')
    try:
        conn.autocommit = sqlite3.LEGACY_TRANSACTION_CONTROL
    except AttributeError:
        pass
    conn.execute('CREATE TABLE t(x)')
    conn.commit()
    conn.execute('BEGIN')
    conn.execute('INSERT INTO t VALUES (1)')
    conn.executescript('CREATE TABLE u(y);')
    conn.rollback()

    surviving = conn.execute('SELECT count(*) FROM t').fetchone()[0]
    conn.close()
    assert surviving == 1, (
        'executescript no longer commits implicitly. If that is really true, '
        '_executescript_at_top_level can be relaxed -- verify first.'
    )


@pytest.mark.database
def test_schema_migrations_has_no_bare_commits_left():
    """Enforced by absence, like #211's guard on dimensions.py."""
    source = (SRC / 'database' / 'domains' / 'schema_migrations.py').read_text(
        encoding='utf-8')
    lines = [
        line.strip() for line in source.splitlines()
        if 'self.conn.commit()' in line and not line.strip().startswith('#')
    ]
    # Exactly one: the helper's own, guarded by the depth check.
    assert len(lines) == 1, (
        f'expected only _commit_if_top_level to commit, found {len(lines)}: {lines}'
    )
