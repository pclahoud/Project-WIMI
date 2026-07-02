"""CLI for the WIMI migration runner.

Usage::

    python -m database.migrations status <db_path> [--scope user|master]
    python -m database.migrations apply  <db_path> [--scope user|master]

Two thin subcommands aimed at support and debugging. The app applies
migrations on DB open at runtime; this CLI is for the offline cases
(verifying a backed-up DB's shape, pre-applying migrations to a copy,
inspecting checksum drift).

Output goes to stdout for the normal status/apply summary; errors go to
stderr. Exit codes:

- ``status`` exits 0 if every recorded migration is "ok" or "pending",
  1 if any is "CHECKSUM MISMATCH" or "MISSING FROM REGISTRY".
- ``apply`` exits 0 on success; non-zero if a migration raises.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

from database.migration_runner import (
    Migration,
    MigrationChecksumMismatchError,
    MigrationFailedError,
    MigrationRunner,
)


# ---------------------------------------------------------------------- helpers


def _load_registry(scope: str) -> list[Migration]:
    """Import and return the MIGRATIONS list for the requested scope."""
    if scope == "user":
        from database.migrations.user import MIGRATIONS

        return list(MIGRATIONS)
    if scope == "master":
        from database.migrations.master import MIGRATIONS

        return list(MIGRATIONS)
    raise ValueError(f"Unknown scope: {scope!r}")


def _detect_scope(conn: sqlite3.Connection) -> str:
    """Infer scope from schema. ``users`` table → master, otherwise user.

    The master DB owns the cross-user ``users`` registry table; a per-user
    DB never has it. This is a fast heuristic for the common case where
    ``--scope`` was omitted.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    return "master" if row is not None else "user"


def _open_conn(db_path: Path) -> sqlite3.Connection:
    """Open the DB read/write so the runner can create ``schema_migrations``
    if it isn't already there. We never write outside that case in
    ``status``.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------- status


def _print_status_row(
    version: int,
    name: str,
    state: str,
    *,
    applied_at: str | None = None,
    duration_ms: int | None = None,
    recorded_checksum: str | None = None,
    current_checksum: str | None = None,
) -> None:
    """Print a single status line in the documented format."""
    label = f"v{version:03d} {name}".ljust(28)
    if state == "pending":
        print(f"  {label}  pending")
        return
    duration = "" if duration_ms is None else f"duration_ms={duration_ms}"
    applied = applied_at or ""
    head = f"  {label}  applied {applied}".rstrip()
    tail = f"  {duration}  {state}".strip()
    print(f"{head}  {tail}".rstrip())
    if state == "CHECKSUM MISMATCH":
        if recorded_checksum is not None:
            print(f"                          recorded:  {recorded_checksum}")
        if current_checksum is not None:
            print(f"                          current:   {current_checksum}")


def cmd_status(db_path: Path, scope: str | None) -> int:
    """Print a summary of applied / pending migrations for ``db_path``.

    Returns the process exit code (0 healthy, 1 if drift was found).
    """
    if not db_path.exists():
        print(f"error: db_path does not exist: {db_path}", file=sys.stderr)
        return 2

    conn = _open_conn(db_path)
    try:
        if scope is None:
            scope = _detect_scope(conn)
            scope_label = f"{scope} (auto-detected)"
        else:
            scope_label = scope

        registry = _load_registry(scope)
        runner = MigrationRunner(conn, registry=registry, scope=scope)

        records = runner.applied_records()
        registry_by_version = {m.version: m for m in registry}

        print(f"WIMI migration status — {db_path} (scope: {scope_label})")
        print(
            f"schema_migrations table: present "
            f"({len(records)} row{'s' if len(records) != 1 else ''})"
        )
        print()

        problem_count = 0

        # Print rows for every applied record, in version order.
        for version in sorted(records.keys()):
            record = records[version]
            current = registry_by_version.get(version)
            if current is None:
                _print_status_row(
                    version,
                    record["name"],
                    "MISSING FROM REGISTRY",
                    applied_at=record["applied_at"],
                )
                problem_count += 1
                continue
            duration_ms = _fetch_duration_ms(conn, version)
            if record["checksum"] != current.checksum:
                _print_status_row(
                    version,
                    current.name,
                    "CHECKSUM MISMATCH",
                    applied_at=record["applied_at"],
                    duration_ms=duration_ms,
                    recorded_checksum=record["checksum"],
                    current_checksum=current.checksum,
                )
                problem_count += 1
            else:
                _print_status_row(
                    version,
                    current.name,
                    "ok",
                    applied_at=record["applied_at"],
                    duration_ms=duration_ms,
                )

        # Pending migrations come last, in version order.
        for migration in runner.pending():
            _print_status_row(migration.version, migration.name, "pending")

        return 1 if problem_count else 0
    finally:
        conn.close()


def _fetch_duration_ms(conn: sqlite3.Connection, version: int) -> int | None:
    """Look up the recorded ``duration_ms`` for an applied version.

    Kept separate from ``applied_records()`` so that helper stays focused
    on the fields the runner uses internally (the duration is a CLI-only
    display detail).
    """
    row = conn.execute(
        "SELECT duration_ms FROM schema_migrations WHERE version = ?",
        (version,),
    ).fetchone()
    if row is None:
        return None
    return row[0]


# ---------------------------------------------------------------------- apply


def cmd_apply(db_path: Path, scope: str | None) -> int:
    """Apply pending migrations to ``db_path``. Returns the exit code.

    Errors are printed to stderr with the migration version/name as the
    headline so support can see immediately which migration broke. The
    underlying exception is preserved for debugging via ``__cause__``.
    """
    if not db_path.exists():
        print(f"error: db_path does not exist: {db_path}", file=sys.stderr)
        return 2

    conn = _open_conn(db_path)
    try:
        if scope is None:
            scope = _detect_scope(conn)
            print(f"scope: {scope} (auto-detected)")
        else:
            print(f"scope: {scope}")

        registry = _load_registry(scope)
        runner = MigrationRunner(conn, registry=registry, scope=scope)

        try:
            applied = runner.apply_pending()
        except MigrationChecksumMismatchError as e:
            print(f"error: {e}", file=sys.stderr)
            return 3
        except MigrationFailedError as e:
            print(f"error: {e}", file=sys.stderr)
            return 4

        if not applied:
            print("No pending migrations. Database is up to date.")
        else:
            print(f"Applied {len(applied)} migration(s):")
            for version in applied:
                migration = next(m for m in registry if m.version == version)
                print(f"  v{version:03d} {migration.name}")
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------- entry point


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m database.migrations",
        description="Inspect or apply WIMI database migrations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser(
        "status",
        help="Show applied/pending migrations and checksum drift for a DB.",
    )
    p_status.add_argument("db_path", type=Path)
    p_status.add_argument(
        "--scope",
        choices=["user", "master"],
        default=None,
        help="Migration scope. Auto-detected from schema if omitted.",
    )

    p_apply = sub.add_parser(
        "apply",
        help="Apply any pending migrations to a DB.",
    )
    p_apply.add_argument("db_path", type=Path)
    p_apply.add_argument(
        "--scope",
        choices=["user", "master"],
        default=None,
        help="Migration scope. Auto-detected from schema if omitted.",
    )

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "status":
        return cmd_status(args.db_path, args.scope)
    if args.command == "apply":
        return cmd_apply(args.db_path, args.scope)
    # argparse with required=True prevents this branch in practice.
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
