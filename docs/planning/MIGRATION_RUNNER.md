# Versioned Migration Runner

Date: 2026-05-09
Status: Implemented

## Context

WIMI's per-user SQLite databases used to be migrated by chained
`_ensure_*_schema()` methods on `SchemaMigrationMixin`. Each method
inferred state by inspecting `sqlite_master` / `PRAGMA table_info` and
ran `CREATE TABLE IF NOT EXISTS` plus targeted `ALTER TABLE` statements.

That worked while every change was additive. It breaks down for:

- **Data migrations** (move rows from table A into junction table B with
  computed values). The `_ensure_*` pattern can add tables and columns
  but isn't shaped for cross-row data movement.
- **Partial-application recovery**. If a migration crashed mid-way the
  next open had no record of how far it got — re-running relied on
  `IF NOT EXISTS` no-ops, which doesn't catch a half-applied
  `ALTER TABLE`.
- **Source drift**. There was no way to detect that a previously-applied
  migration's source code had changed; the next open would silently use
  the new code path against an old DB shape.
- **Lazy init** of phases 6 and 7 (called from goals/dimensions code) meant
  fresh tests had to remember to invoke them, and operations on
  not-yet-touched features paid an extra `sqlite_master` query each call.

A parallel `SchemaManager` framework existed in `schema_manager.py` but
was never wired up.

## Decision

Replace the `_ensure_*` chain with a versioned migration runner.

### Shape

- Each migration is a Python module exposing `VERSION: int`,
  `NAME: str`, and `def upgrade(conn): ...`.
- A `schema_migrations` table inside each DB records `(version, name,
  applied_at, checksum, duration_ms)` for every applied migration.
- `MigrationRunner` (in `src/database/migration_runner.py`) reads the
  ledger, verifies recorded checksums against current source, and
  applies any pending migrations — each in its own transaction.

### Locked-in choices

1. **Forward-only.** Migrations expose `upgrade(conn)` only — no
   `downgrade`. Forward-only is industry standard; rollback is rarely
   correct in practice and adds significant maintenance burden.
2. **Separate runners for user and master DBs.** Each DB has its own
   `schema_migrations` table. Migration files live in
   `src/database/migrations/user/` and `src/database/migrations/master/`.
   No shared runner state.
3. **Hard fail on checksum mismatch.** If a previously-applied
   migration's `upgrade()` source no longer matches the recorded
   checksum, the runner raises `MigrationChecksumMismatchError` and
   refuses to open the DB. Diagnostics (recorded vs current checksum,
   recorded `applied_at`) are logged via `error_logger.error` before
   the raise, so support can see exactly what diverged.
4. **Tests required per migration.** Every PR adding a migration must
   add a matching `test_<scope>_NNN_*.py` that exercises the upgrade
   against (a) the previous version's expected state and (b) data
   movement assertions when the migration touches data. Helpers in
   `tests/database/migrations/conftest.py` keep this cheap.

### What the baseline contains

`migrations/user/m001_baseline.py` is the cumulative state of the
per-user DB as of the runner's introduction. It ports everything that
the chained `_ensure_phase{1,2,4}_schema()` and their helpers used to
do — ~25 tables, the hybrid-weight columns, dimension_id, the 23
preference columns added incrementally over time, the entry_media
junction-table decoupling, the legacy notes migration, and the timer
rounds back-fill. For users with a pre-runner DB, every step no-ops:
`CREATE TABLE IF NOT EXISTS`, `add_column_if_missing`, and the data
backfills check for already-migrated rows. The runner records v1 in
`schema_migrations` after the baseline runs, so subsequent migrations
can layer on top.

`migrations/user/m002_phase6_goals.py` and
`migrations/user/m003_phase7_dimensions.py` move the previously-lazy
phase 6 and 7 schema creation onto the eager-init path. The
corresponding `_ensure_phase{6,7}_schema()` calls in `goals.py` and
`dimensions.py` were removed in the same change.

`migrations/master/m001_baseline.py` ports the master-DB schema
initialization that previously lived in `MasterDatabase._initialize_schema`.

## Consequences

### Better

- Single point of truth for schema state per DB
  (`SELECT MAX(version) FROM schema_migrations`).
- Atomic per-migration. A failed migration rolls back its own
  transaction; subsequent migrations don't run until it's fixed.
- Source-drift protection via checksum.
- Tests can pin specific schema versions (`runner.apply_specific(N)`)
  to assert behavior at any historical version.
- Polyhierarchy and other future data migrations now have a place
  to live.

### Cost

- One more concept for contributors to learn (the ledger, the file
  convention, the tests-required rule).
- A small ledger lookup on every DB open.

### Caveats

- **SQLite auto-commits DDL.** The runner wraps each migration in
  its own transaction, but stdlib `sqlite3` implicitly commits before
  any DDL statement (`CREATE TABLE`, `ALTER TABLE`). If a migration
  does DDL and then a DML statement fails, the DDL is **not** rolled
  back. This is a real property of `sqlite3`'s default isolation
  level, not a runner bug. Migrations that mix DDL and data movement
  should structure themselves so the data-movement step happens
  before any DDL that depends on it succeeding (or use explicit
  `BEGIN`/`COMMIT` semantics).
- **Discoverable failures only.** Checksum mismatches are caught at
  open time, but a *new* migration that's logically wrong can still
  break a user's DB on first open. Per-migration tests (decision 4)
  are the safety net — they're required, not optional.

## How to add a new migration

1. Pick the next version number for the target scope:
   ```python
   from database.migrations.user import MIGRATIONS
   next_version = max(m.version for m in MIGRATIONS) + 1
   ```
2. Create `src/database/migrations/user/m<NNN>_<short_name>.py`:
   ```python
   from .._helpers import get_table_names, run_schema_script
   VERSION = N
   NAME = "short_name"
   def upgrade(conn):
       ...
   ```
3. Add `from . import m<NNN>_<short_name>` and append
   `build_migration(...)` to `MIGRATIONS` in
   `src/database/migrations/user/__init__.py`.
4. Add `tests/database/migrations/test_user_<NNN>_<short_name>.py`
   with at least: a fresh-DB upgrade test, an idempotency test, and
   if the migration moves data, an assertion on the moved rows.
5. Run `python -m pytest tests/database/ --no-cov` and confirm
   no regressions.

## CLI

A small CLI ships in `src/database/migrations/__main__.py` for support
and debugging cases — verifying a backed-up DB's shape before launching
the app, pre-applying migrations to a copy, or inspecting checksum
drift. The app itself still applies migrations on every DB open at
runtime; the CLI is for the offline cases.

Two subcommands:

### `python -m database.migrations status <db_path> [--scope user|master]`

Prints a per-version summary of the DB's `schema_migrations` ledger
and any pending migrations from the current registry. Auto-detects
scope from the schema (presence of a `users` table → master) when
`--scope` is omitted.

Each row carries one of four states:

- `ok` — applied; recorded checksum matches the current registry source.
- `CHECKSUM MISMATCH` — applied, but the migration's source has
  changed since it was recorded. Both the recorded and current
  checksums are printed underneath the row.
- `MISSING FROM REGISTRY` — applied, but no matching migration is
  registered in the current code (the file may have been renamed or
  deleted).
- `pending` — registered but not yet applied.

Exit code is `0` if everything is `ok` or `pending`, `1` if any
`CHECKSUM MISMATCH` or `MISSING FROM REGISTRY` is found, `2` if the
DB path doesn't exist.

Example:

```text
WIMI migration status — /path/to/user_001_alice.db (scope: user)
schema_migrations table: present (3 rows)

  v001 baseline           applied 2026-04-12T08:14:01  duration_ms=42  ok
  v002 phase6_goals       applied 2026-04-12T08:14:01  duration_ms=3   ok
  v003 phase7_dimensions  applied 2026-04-12T08:14:01  duration_ms=2   ok
```

### `python -m database.migrations apply <db_path> [--scope user|master]`

Runs `MigrationRunner(...).apply_pending()` against the DB and prints
the versions that were applied. Returns `0` on success, `2` if the DB
path doesn't exist, `3` on `MigrationChecksumMismatchError`, `4` on
`MigrationFailedError` — the underlying error message is preserved as
the top-of-stack message (no `try`/`except` reformatting that buries
the cause).

Both subcommands open the DB read/write because the runner needs to
create the `schema_migrations` ledger if it isn't already present
(the read-only path would be possible but would mean a different
flow for fresh DBs vs migrated ones — not worth the complexity for
a support tool).

## Out of scope (not done by this change)

- Conversion of the legacy `_ensure_*` mixin methods on
  `SchemaMigrationMixin`. The methods are now unused in init paths but
  still present on the mixin; some test fixtures defensively call
  `db._ensure_phase2_schema()` etc. as a safety net. Removing the
  methods is a follow-up cleanup PR.
- The polyhierarchy migration (`docs/planning/POLYHIERARCHY_MIGRATION.md`).
  Will land as `migrations/user/m004_polyhierarchy.py` once the rest of
  that plan is ready.
