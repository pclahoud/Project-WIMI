"""Per-test user wrapper around :class:`MasterDatabase`.

Implements :class:`TestUser` per ``docs/planning/TEST_INFRASTRUCTURE.md``
Section 4 (``TestUser`` API contract). A :class:`TestUser` owns one
WIMI user account for the duration of a single test or interactive
session. It:

* Creates the user via :meth:`MasterDatabase.create_user` with a name
  shaped ``test_<scenario>_<run_id>`` so test users are easy to spot
  and reap.
* Lazily opens a :class:`UserDatabase` against the per-user database
  file recorded on the user row (``database_filename`` is resolved
  relative to ``master.users_dir``).
* Exposes :meth:`seed` to run a registered seeder by name (the seeder
  registry lands in T2.5; until then the call raises
  :class:`NotImplementedError`).
* Drops the user idempotently via :meth:`drop` — closes the cached
  :class:`UserDatabase`, deletes the user row from the master DB, and
  removes the per-user ``.db`` file. Each step is wrapped so a partial
  failure does not block the remaining cleanup.

The module is consumed by :mod:`wimi_test.session` (the per-session
hub) and the pytest fixture layer in :mod:`wimi_test.fixtures.core`.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Optional

# Concrete imports are required at runtime: ``TestUser`` actually
# constructs a ``UserDatabase`` and calls methods on a ``MasterDatabase``
# instance passed in by the caller. The TYPE_CHECKING block below is
# only used to satisfy static type-checkers without paying the import
# cost twice at runtime.
from database.master_db import MasterDatabase  # noqa: F401  (used in annotations + isinstance-style runtime references)
from database.user_db import UserDatabase

from wimi_test.config import TestConfig  # noqa: F401  (re-exported indirectly; kept per task contract)
from wimi_test.errors import WimiTestError

if TYPE_CHECKING:  # pragma: no cover - import-time only
    from database.master_db import MasterDatabase as _MasterDatabaseT
    from database.user_db import UserDatabase as _UserDatabaseT

__all__ = ["TestUser"]


_logger = logging.getLogger(__name__)

# Component validator. ``scenario`` and ``run_id`` are interpolated into
# both the WIMI username and (transitively) the per-user database
# filename, so we restrict them to the same character class
# ``MasterDatabase`` already accepts for usernames. Anything outside this
# pattern is rejected eagerly so the failure surfaces in our constructor
# rather than deep inside ``MasterDatabase._validate_username``.
_COMPONENT_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]+$")


class TestUser:
    """Per-test WIMI user account, scoped to one scenario / run-id pair.

    See ``docs/planning/TEST_INFRASTRUCTURE.md`` Section 4 for the full
    API contract. A :class:`TestUser` is created via the master
    database and dropped on teardown; its per-user :class:`UserDatabase`
    is opened lazily on first access to :attr:`db`.
    """

    def __init__(
        self,
        master: "_MasterDatabaseT",
        *,
        scenario: str,
        run_id: str,
    ) -> None:
        """Create the underlying WIMI user row.

        Parameters
        ----------
        master:
            Already-initialised :class:`MasterDatabase` rooted at the
            test ``app_data`` directory. The caller owns its lifetime.
        scenario:
            Short, filesystem-safe scenario name (matches
            ``[a-zA-Z0-9_-]+``). Used as the middle segment of the
            generated username.
        run_id:
            Per-process monotonic id (typically from
            :mod:`wimi_test._internal.runid`). Same character class as
            ``scenario``.

        Raises
        ------
        ValueError
            If ``scenario`` or ``run_id`` contain disallowed characters.
        WimiTestError
            If :meth:`MasterDatabase.create_user` raises (e.g. on
            username collision). The original exception is chained.
        """
        if not _COMPONENT_PATTERN.match(scenario):
            raise ValueError(
                f"scenario must match {_COMPONENT_PATTERN.pattern!r}; got {scenario!r}"
            )
        if not _COMPONENT_PATTERN.match(run_id):
            raise ValueError(
                f"run_id must match {_COMPONENT_PATTERN.pattern!r}; got {run_id!r}"
            )

        self.master: "_MasterDatabaseT" = master
        self.scenario: str = scenario
        self.run_id: str = run_id
        self._username: str = f"test_{scenario}_{run_id}"

        # Cached per-user DB handle, opened lazily by the ``db`` property.
        self._db: Optional["_UserDatabaseT"] = None
        # Idempotency latch for ``drop``.
        self._dropped: bool = False

        try:
            self._user: Any = master.create_user(
                username=self._username,
                display_name=f"Test User ({scenario}/{run_id})",
                user_types=["student"],
            )
        except Exception as exc:  # noqa: BLE001 — wrap-and-rechain
            raise WimiTestError(
                f"Failed to create test user {self._username!r}"
            ) from exc

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def username(self) -> str:
        """The computed WIMI username (``test_<scenario>_<run_id>``)."""
        return self._username

    @property
    def user_id(self) -> int:
        """The integer primary key of the underlying ``users`` row."""
        return int(self._user.id)

    @property
    def db(self) -> "_UserDatabaseT":
        """Lazy :class:`UserDatabase` handle.

        First access opens a connection to the per-user ``.db`` file
        recorded on the user row; subsequent accesses return the same
        cached instance. The handle is closed by :meth:`drop`.
        """
        if self._db is not None:
            return self._db

        # ``database_filename`` is the bare filename (e.g.
        # ``user_001_test_smoke_abc.db``) created by
        # ``MasterDatabase.create_user``. Resolve it relative to the
        # master's ``users_dir`` to get an absolute path.
        db_filename: str = self._user.database_filename
        db_path = self.master.users_dir / db_filename

        # ``ensure_user_database`` initialises the per-user schema if
        # the file does not yet exist. Safe to call repeatedly.
        try:
            self.master.ensure_user_database(self._user.id)
        except Exception as exc:  # noqa: BLE001 — wrap-and-rechain
            raise WimiTestError(
                f"Failed to ensure user database for {self._username!r}"
            ) from exc

        self._db = UserDatabase(
            db_path=db_path,
            user_id=self._user.id,
            username=self._username,
        )
        return self._db

    # ------------------------------------------------------------------
    # Mutating helpers
    # ------------------------------------------------------------------

    def seed(self, name: str, **kwargs: Any) -> None:
        """Run a registered seeder by name.

        The seeder registry lives in :mod:`wimi_test.db.seeders`, which
        lands in task T2.5. Until that module exists this method raises
        :class:`NotImplementedError` — once T2.5 ships, callers do not
        have to change.
        """
        try:
            from wimi_test.db import seeders  # type: ignore[import-not-found]
        except ImportError as exc:
            raise NotImplementedError(
                "Seeders module not yet available (T2.5)"
            ) from exc

        seeder = seeders.get_seeder(name)
        seeder(self.db, **kwargs)

    def drop(self) -> None:
        """Tear down the user: close DB, delete row, remove file.

        Idempotent — the second call is a no-op. Each substep is
        guarded so a failure in one (e.g. the file is already gone)
        does not prevent the next from running. Failures are logged at
        ``WARNING`` level rather than re-raised so the surrounding
        teardown path always completes.
        """
        if self._dropped:
            return

        # 1. Close the cached UserDatabase, if any.
        if self._db is not None:
            try:
                self._db.close()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                _logger.warning(
                    "TestUser %r: failed to close UserDatabase: %s",
                    self._username,
                    exc,
                )
            finally:
                self._db = None

        # 2. Delete the user row from the master DB.
        #
        # ``MasterDatabase`` exposes ``soft_delete_user`` and the
        # grace-period reaper but no direct hard-delete. For test
        # teardown we want the row gone immediately so the next test
        # can reuse the username; per the task spec, fall back to a
        # direct SQL DELETE on the ``users`` table.
        # TODO: replace with a dedicated MasterDatabase method if/when
        #       a hard-delete API lands upstream.
        try:
            with self.master.transaction():
                self.master.execute(
                    "DELETE FROM user_database_schemas WHERE user_id = ?",
                    (self._user.id,),
                )
                self.master.execute(
                    "DELETE FROM users WHERE id = ?",
                    (self._user.id,),
                )
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            _logger.warning(
                "TestUser %r: failed to delete user row id=%s: %s",
                self._username,
                getattr(self._user, "id", "<unknown>"),
                exc,
            )

        # 3. Remove the per-user .db file (and SQLite sidecar files).
        db_filename: Optional[str] = getattr(self._user, "database_filename", None)
        if db_filename:
            db_path = self.master.users_dir / db_filename
            for path in (
                db_path,
                db_path.with_suffix(db_path.suffix + "-wal"),
                db_path.with_suffix(db_path.suffix + "-shm"),
            ):
                try:
                    if path.exists():
                        path.unlink()
                except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                    _logger.warning(
                        "TestUser %r: failed to unlink %s: %s",
                        self._username,
                        path,
                        exc,
                    )

        self._dropped = True
