"""Versioned migration runner for WIMI databases.

Design choices (see ``docs/planning/MIGRATION_RUNNER.md``):

- Forward-only. Migrations expose ``upgrade(conn)``; no ``downgrade``.
- Separate runners for user and master DBs, each with their own
  ``schema_migrations`` table.
- Hard-fail on checksum mismatch. The runner refuses to open a DB whose
  recorded checksum for an applied migration no longer matches the
  current source. Diagnostics are logged before raising.
- Per-migration transactions. A failed migration rolls back its own
  transaction; later migrations don't run until the failure is fixed.

Each migration is a Python module exposing:

    VERSION: int           # 1, 2, 3, ...  (gaps allowed but unusual)
    NAME: str              # short snake_case label
    def upgrade(conn): ... # applies the migration to ``conn``

Migration registries live in ``src.database.migrations.user`` and
``src.database.migrations.master`` as ordered ``MIGRATIONS`` lists.
"""
from __future__ import annotations

import hashlib
import inspect
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


class MigrationError(Exception):
    """Base for all migration-runner errors."""


class MigrationFailedError(MigrationError):
    """A migration's ``upgrade()`` raised. The transaction was rolled back."""

    def __init__(self, version: int, name: str, cause: BaseException):
        super().__init__(
            f"Migration {version:03d} ({name}) failed: {cause!r}. "
            f"Transaction rolled back; the DB is unchanged. Subsequent "
            f"migrations were not attempted."
        )
        self.version = version
        self.name = name
        self.cause = cause


class MigrationChecksumMismatchError(MigrationError):
    """An applied migration's source checksum no longer matches what was recorded.

    This usually means the migration file was edited after being applied —
    a category of mistake that can silently corrupt user data because the
    runner won't re-run it. Hard-failing forces the developer to either
    revert the file or write a new migration that fixes the divergence.
    """

    def __init__(
        self,
        version: int,
        name: str,
        recorded_checksum: str,
        current_checksum: str,
    ):
        super().__init__(
            f"Migration {version:03d} ({name}) has a checksum mismatch: "
            f"recorded={recorded_checksum[:12]}... "
            f"current={current_checksum[:12]}.... "
            f"The migration's source code changed after it was applied. "
            f"Either revert the file to its original content or write a new "
            f"migration that supersedes it."
        )
        self.version = version
        self.name = name
        self.recorded_checksum = recorded_checksum
        self.current_checksum = current_checksum


@dataclass(frozen=True)
class Migration:
    """A single migration ready to be applied or verified.

    The ``checksum`` field is computed from the source of ``upgrade_fn``.
    Two migrations whose ``upgrade_fn`` source is byte-identical will
    have the same checksum even if their module paths differ — that's
    the desired behavior (the source is what defines the migration).
    """

    version: int
    name: str
    upgrade_fn: Callable[[sqlite3.Connection], None]
    checksum: str = field(init=False)

    def __post_init__(self) -> None:
        # Frozen dataclass — use object.__setattr__ to set the derived field.
        object.__setattr__(self, "checksum", self._compute_checksum())

    def _compute_checksum(self) -> str:
        try:
            source = inspect.getsource(self.upgrade_fn)
        except (OSError, TypeError):
            # Fallback: hash the function's qualified name. Unusual path —
            # source-not-available shouldn't happen for normal migration
            # modules, but a frozen build that strips source could trigger
            # it. The qualified name is stable across runs.
            source = f"{self.upgrade_fn.__module__}:{self.upgrade_fn.__qualname__}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_migration(module) -> Migration:
    """Construct a :class:`Migration` from a migration module.

    The module must expose ``VERSION`` (int), ``NAME`` (str), and
    ``upgrade(conn)``. Raises ``AttributeError`` with a clear message
    if any are missing.
    """
    for attr in ("VERSION", "NAME", "upgrade"):
        if not hasattr(module, attr):
            raise AttributeError(
                f"Migration module {module.__name__!r} is missing required "
                f"attribute {attr!r}. Each migration must define VERSION, "
                f"NAME, and upgrade(conn)."
            )
    return Migration(
        version=int(module.VERSION),
        name=str(module.NAME),
        upgrade_fn=module.upgrade,
    )


class MigrationRunner:
    """Applies a registry of migrations to a single SQLite connection.

    Usage:

        from src.database.migrations.user import MIGRATIONS
        runner = MigrationRunner(conn, MIGRATIONS, scope="user")
        runner.apply_pending()
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        registry: Iterable[Migration],
        scope: str = "user",
        error_logger=None,
    ):
        self.conn = conn
        self.scope = scope
        self.error_logger = error_logger
        # Sort by version, dedupe — defensive; registries should already be ordered.
        seen: set[int] = set()
        self.registry: list[Migration] = []
        for m in sorted(registry, key=lambda m: m.version):
            if m.version in seen:
                raise ValueError(
                    f"Duplicate migration version {m.version} in {scope} registry"
                )
            seen.add(m.version)
            self.registry.append(m)
        self._ensure_schema_migrations_table()

    # ------------------------------------------------------------------ schema_migrations table

    def _ensure_schema_migrations_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
                checksum    TEXT NOT NULL,
                duration_ms INTEGER
            )
            """
        )
        self.conn.commit()

    # ------------------------------------------------------------------ queries

    def applied_versions(self) -> set[int]:
        """Return the set of versions already recorded as applied."""
        cursor = self.conn.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cursor.fetchall()}

    def applied_records(self) -> dict[int, dict]:
        """Return a {version: {name, applied_at, checksum}} map."""
        cursor = self.conn.execute(
            "SELECT version, name, applied_at, checksum FROM schema_migrations"
        )
        return {
            row[0]: {"name": row[1], "applied_at": row[2], "checksum": row[3]}
            for row in cursor.fetchall()
        }

    def pending(self) -> list[Migration]:
        """Return migrations that haven't been applied yet, in version order."""
        applied = self.applied_versions()
        return [m for m in self.registry if m.version not in applied]

    # ------------------------------------------------------------------ checksum verification

    def verify_checksums(self) -> None:
        """Hard-fail if any applied migration's checksum doesn't match its current source.

        Call this BEFORE ``apply_pending``; the runner does so itself.
        """
        records = self.applied_records()
        registry_by_version = {m.version: m for m in self.registry}
        for version, record in records.items():
            if version not in registry_by_version:
                # An applied version that no longer exists in the registry —
                # the file was deleted/renamed. Don't fail (a removed
                # migration is still applied to the DB), but log it.
                self._log(
                    "warning",
                    f"schema_migrations records v{version:03d} ({record['name']}) "
                    f"but no matching migration is registered. The file may have "
                    f"been renamed or removed."
                )
                continue
            current = registry_by_version[version]
            if record["checksum"] != current.checksum:
                self._log(
                    "error",
                    f"Checksum mismatch on v{version:03d} ({current.name}): "
                    f"recorded={record['checksum']} current={current.checksum}. "
                    f"Recorded applied_at={record['applied_at']}."
                )
                raise MigrationChecksumMismatchError(
                    version=version,
                    name=current.name,
                    recorded_checksum=record["checksum"],
                    current_checksum=current.checksum,
                )

    # ------------------------------------------------------------------ apply

    def apply_pending(self) -> list[int]:
        """Verify checksums then apply each pending migration in its own transaction.

        Returns the list of versions that were applied (in order). On
        failure, raises :class:`MigrationFailedError` after rolling back
        the failing migration; later migrations aren't attempted.
        """
        self.verify_checksums()
        applied: list[int] = []
        for migration in self.pending():
            self._apply_one(migration)
            applied.append(migration.version)
        return applied

    def apply_specific(self, version: int) -> None:
        """Apply a single migration by version (test affordance).

        Raises ``KeyError`` if the version isn't registered, or
        ``ValueError`` if it's already applied.
        """
        match = next((m for m in self.registry if m.version == version), None)
        if match is None:
            raise KeyError(f"No migration registered with version {version}")
        if version in self.applied_versions():
            raise ValueError(f"Migration v{version:03d} is already applied")
        self._apply_one(match)

    def _apply_one(self, migration: Migration) -> None:
        # Each migration runs in its own transaction. We don't use the
        # BaseDatabase context manager here because the runner can be
        # invoked against a raw sqlite3.Connection in tests.
        self._log(
            "info",
            f"Applying {self.scope} migration v{migration.version:03d} "
            f"({migration.name})..."
        )
        start = time.monotonic()
        try:
            migration.upgrade_fn(self.conn)
            duration_ms = int((time.monotonic() - start) * 1000)
            self.conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum, duration_ms) "
                "VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, migration.checksum, duration_ms),
            )
            self.conn.commit()
            self._log(
                "info",
                f"Applied {self.scope} migration v{migration.version:03d} "
                f"({migration.name}) in {duration_ms}ms"
            )
        except Exception as e:
            try:
                self.conn.rollback()
            except sqlite3.Error:
                # Rollback can fail if the connection is in a weird state;
                # log it but raise the original cause.
                pass
            self._log(
                "error",
                f"Migration {self.scope}/v{migration.version:03d} "
                f"({migration.name}) failed: {e!r}. Rolled back."
            )
            raise MigrationFailedError(
                version=migration.version, name=migration.name, cause=e
            ) from e

    # ------------------------------------------------------------------ logging

    def _log(self, level: str, message: str) -> None:
        """Forward a log message to the error_logger if one is attached.

        ``ErrorLogger`` expects ``category`` to be an ``ErrorCategory``
        enum (it calls ``.value`` on it inside ``_hash_error``), not a
        string — passing "DATABASE" causes an AttributeError deep
        inside the logger that the previous try/except didn't catch
        because the kwarg is accepted at the call site, then crashes
        downstream. Import the enum lazily so the runner stays usable
        in tests that construct it against a raw sqlite3 connection
        without the full app_logging stack.

        Falls back silently if no logger is provided, the import
        fails, or the logger call raises — logging is non-critical to
        migration correctness.
        """
        if self.error_logger is None:
            return
        method = getattr(self.error_logger, level, None)
        if method is None:
            return
        category = None
        try:
            from app_logging import ErrorCategory
            category = ErrorCategory.DATABASE
        except (ImportError, AttributeError):
            pass
        try:
            if category is not None:
                method(message, category=category)
            else:
                method(message)
        except Exception:
            # Last-resort: try positional/no-kwarg form.
            try:
                method(message)
            except Exception:
                pass
