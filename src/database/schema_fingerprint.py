"""
Structural comparison of a user database against the schema WIMI writes (#593).

A ``.wimi`` import, a restore and a folder-sync install all copy the
archive's ``user.db`` byte for byte, **its table definitions included**. So
every guarantee the app reads from its own DDL -- a CHECK constraint, a
column's declared type, ``INTEGER PRIMARY KEY`` -- holds on an installed
profile only if the file says so. ``preflight_schema`` compares
``schema_migrations`` checksums, which a crafted file copies from a real
export, so it never looked at the tables.

The owner's decision on #593 (option 2): migrate the incoming database, compare
its structure with a freshly migrated one, and refuse it on a mismatch.

WHY STRUCTURE AND NOT TEXT. A profile that predates the migration runner
gained its columns through ``ALTER TABLE ADD COLUMN``, so its stored
``CREATE TABLE`` text differs from a fresh database's even where the tables
are identical. Measured on a database built by the pre-runner tree
(``5109d33^``) and migrated forward: 7 objects differ as text and 0 differ
in structure. Comparing text would refuse real students' profiles. So what
is compared is what the text means: each column's declared type, NOT NULL,
default, primary-key position and hidden flag; every CHECK expression;
foreign keys; indexes; ``WITHOUT ROWID``; triggers and views.

WHAT IS ALLOWED, AND WHY EACH IS SAFE. Each rule was measured on real
history, not argued:

* **Anything WIMI declares must be present and declared the same way.**
  This is the whole point: a dropped CHECK (#593 variant A) or an ``id``
  redeclared ``TEXT`` (variant D) is refused.
* **Additions WIMI never reads are allowed:** an extra table, an extra
  column on one of WIMI's tables, an extra index, and an extra CHECK or
  foreign key. The AI-capture builds stamped m011-m014 into real databases
  (CLAUDE.md, *Parked Decisions*), and a database built from
  ``archive/ai-capture`` and migrated forward carries exactly these: two
  tables, four columns, two indexes and one CHECK, while changing nothing
  WIMI declares. Refusing them would lock those profiles out. None of these
  can widen what a value may be: an extra CHECK or index only narrows what
  can be written.
* **Triggers and views WIMI does not create are refused.** No version of
  WIMI has ever created one beyond its own, and a trigger runs on WIMI's
  own writes.
* **One measured legacy gap:** ``LEGACY_MISSING_CHECKS``, below.

A database at every commit that changed schema-creating code since
2025-12-26 (55 commits) was built with that commit's own code, migrated
forward with today's, and compared:
* 31 match exactly;
* 20 (2026-01-08 to 2026-03-12) differ only by ``LEGACY_MISSING_CHECKS``;
* 4 (2025-12-26 to 2026-01-01) cannot be opened by today's WIMI at all,
  failing m001. That is a separate, older defect, and this check is never
  reached for them.

This module is pure ``sqlite3``. It decides nothing about archives;
``app.profile_archive.preflight_schema`` is the caller.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

# Two CHECK clauses a fresh database declares and a profile created between
# 2026-01-08 and 2026-03-12 does not. Those columns arrived by
# ``ALTER TABLE ... ADD COLUMN`` with no CHECK, and a fresh database declares
# them inline. Both columns reach the page only as a comparison
# (``timer_display_size === 'large'``) and as arithmetic
# (``long_break_interval_rounds``), and ``PreferencesMixin`` validates both on
# write. So tolerating their absence widens nothing a page can render. Keyed
# by table, each value normalised as ``_normalise_sql`` returns it.
# ``tests/database/test_schema_fingerprint.py`` asserts each entry is still a
# CHECK that a fresh database declares, so an entry cannot go stale silently.
LEGACY_MISSING_CHECKS: Dict[str, FrozenSet[str]] = {
    'user_preferences': frozenset({
        "long_break_interval_rounds>=2 and long_break_interval_rounds<=10",
        "timer_display_size in('normal','large')",
    }),
}


# ---------------------------------------------------------------- normalising

def _normalise_sql(text: Optional[str]) -> str:
    """Lower-case and collapse whitespace outside string literals.

    Identifier quoting (``"x"``, ``[x]``, a backtick) is dropped, because
    SQLite accepts all three for the same name. String literals keep their
    case and spacing, because ``'Large'`` is not ``'large'``.
    """
    text = text or ''
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
            continue
        out.append(' ' if c.isspace() else c.lower())
        i += 1
    s = ''.join(out)
    s = re.sub(r' +', ' ', s).strip()
    s = re.sub(r' ?([(),=<>]) ?', r'\1', s)
    return re.sub(r'["`\[\]]', '', s)


def _check_clauses(table_sql: str) -> FrozenSet[str]:
    """Every ``CHECK (...)`` expression in a ``CREATE TABLE``, normalised."""
    s = _normalise_sql(table_sql)
    found = []
    for m in re.finditer(r'\bcheck\(', s):
        depth, j = 1, m.end()
        while j < len(s) and depth:
            if s[j] == "'":
                j = s.index("'", j + 1)
            elif s[j] == '(':
                depth += 1
            elif s[j] == ')':
                depth -= 1
            j += 1
        found.append(s[m.end():j - 1])
    return frozenset(found)


# ---------------------------------------------------------------- fingerprint

Column = Tuple[str, int, Optional[str], int, int]  # type, notnull, default, pk, hidden


@dataclass
class TableShape:
    columns: Dict[str, Column]
    checks: FrozenSet[str]
    foreign_keys: FrozenSet[tuple]
    # Explicit indexes by name -> normalised SQL. Constraint indexes (UNIQUE,
    # PRIMARY KEY) have generated names, so they are keyed by what they cover.
    indexes: Dict[str, str]
    without_rowid: bool


@dataclass
class SchemaShape:
    tables: Dict[str, TableShape] = field(default_factory=dict)
    triggers: Dict[str, str] = field(default_factory=dict)
    views: Dict[str, str] = field(default_factory=dict)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fingerprint(conn: sqlite3.Connection) -> SchemaShape:
    """Read a database's structure into a comparable shape."""
    shape = SchemaShape()
    objects = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%'").fetchall()
    for kind, name, sql in objects:
        if kind == 'trigger':
            shape.triggers[name] = _normalise_sql(sql)
        elif kind == 'view':
            shape.views[name] = _normalise_sql(sql)
        elif kind == 'table':
            columns = {
                row[1]: (str(row[2] or '').upper().strip(), row[3],
                         _normalise_sql(row[4]) if row[4] is not None else None,
                         row[5], row[6])
                for row in conn.execute(f'PRAGMA table_xinfo({_quote(name)})')
            }
            foreign_keys = frozenset(
                tuple(row[2:]) for row in
                conn.execute(f'PRAGMA foreign_key_list({_quote(name)})'))
            indexes = {}
            for _seq, index, unique, origin, _partial in conn.execute(
                    f'PRAGMA index_list({_quote(name)})'):
                covered = ','.join(
                    str(r[2]) for r in
                    conn.execute(f'PRAGMA index_info({_quote(index)})'))
                if origin == 'c':
                    row = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type = 'index' "
                        "AND name = ?", (index,)).fetchone()
                    indexes[index] = _normalise_sql(row[0] if row else '')
                else:
                    indexes[f'<{origin} {covered}>'] = f'unique={unique}'
            shape.tables[name] = TableShape(
                columns=columns, checks=_check_clauses(sql),
                foreign_keys=foreign_keys, indexes=indexes,
                without_rowid='without rowid' in _normalise_sql(sql))
    return shape


# ---------------------------------------------------------------- comparing

def _describe_column(col: Column) -> str:
    ctype, notnull, default, pk, _hidden = col
    parts = [ctype or 'no declared type']
    if pk:
        parts.append('PRIMARY KEY')
    if notnull:
        parts.append('NOT NULL')
    if default is not None:
        parts.append(f'DEFAULT {default}')
    return ' '.join(parts)


def compare(expected: SchemaShape, incoming: SchemaShape) -> List[str]:
    """Every way ``incoming`` fails to match ``expected``, as sentences.

    An empty list means the incoming database may be installed. Each entry
    names the table (or trigger, or view) and says what differs, because a
    refusal that does not say what it found is a dead end (#174).
    """
    problems: List[str] = []

    for name, want in sorted(expected.tables.items()):
        got = incoming.tables.get(name)
        if got is None:
            problems.append(f'the table "{name}" is missing')
            continue
        for col, spec in sorted(want.columns.items()):
            if col not in got.columns:
                problems.append(f'the table "{name}" has no column "{col}"')
            elif got.columns[col] != spec:
                problems.append(
                    f'in the table "{name}", the column "{col}" is declared '
                    f'{_describe_column(got.columns[col])}, where WIMI '
                    f'declares {_describe_column(spec)}')
        missing_checks = (want.checks - got.checks
                          - LEGACY_MISSING_CHECKS.get(name, frozenset()))
        for check in sorted(missing_checks):
            problems.append(
                f'the table "{name}" is missing the rule CHECK({check})')
        if want.foreign_keys - got.foreign_keys:
            problems.append(
                f'the table "{name}" is missing a foreign key WIMI declares')
        for index, spec in sorted(want.indexes.items()):
            if index not in got.indexes:
                problems.append(
                    f'the table "{name}" is missing the index "{index}"')
            elif got.indexes[index] != spec:
                problems.append(
                    f'the table "{name}" declares the index "{index}" '
                    f'differently')
        if want.without_rowid != got.without_rowid:
            problems.append(f'the table "{name}" is stored differently '
                            f'(WITHOUT ROWID)')

    for kind, want_map, got_map in (('trigger', expected.triggers, incoming.triggers),
                                    ('view', expected.views, incoming.views)):
        for name in sorted(set(want_map) | set(got_map)):
            if name not in got_map:
                problems.append(f'the {kind} "{name}" is missing')
            elif name not in want_map:
                problems.append(
                    f'it has a {kind} "{name}" that WIMI never creates')
            elif got_map[name] != want_map[name]:
                problems.append(f'the {kind} "{name}" is defined differently')

    return problems
