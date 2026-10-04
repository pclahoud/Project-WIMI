"""
Base Database Class
Provides core database functionality for both Master and User databases
"""
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class BaseDatabaseError(Exception):
    """Base exception for database operations"""
    pass


class DatabaseConnectionError(BaseDatabaseError):
    """Raised when database connection fails"""
    pass


class DatabaseIntegrityError(BaseDatabaseError):
    """Raised when database integrity is violated"""
    pass


class BaseDatabase:
    """
    Base class for database operations.
    Provides connection management, transaction handling, and common utilities.
    """

    # Nesting depth of :meth:`transaction`. A class-level default so the
    # attribute exists even for a subclass that never reaches ``__init__``
    # (``__del__`` runs on a half-built object too). Per *instance*, which
    # is per *connection* — see :meth:`transaction` on why that is the
    # right granularity and not a thread-local.
    _txn_depth: int = 0

    # The connection, for the same reason and in the same spirit — and the
    # omission beside that comment was reachable, measured (#281).
    # ``__init__`` assigns ``self.conn = None`` before connecting, so this
    # default fires only for an instance that never entered ``__init__``
    # at all: ``MasterDatabase.__init__`` runs three ``mkdir`` calls
    # *before* ``super().__init__``, and pointing ``--app-data-dir`` at a
    # path under a file raises ``NotADirectoryError`` there. ``__del__``
    # then reached ``close()`` on an object with no ``conn`` and printed
    # ``AttributeError: 'MasterDatabase' object has no attribute 'conn'``
    # on top of the real error — #281's complaint (an irrelevant
    # diagnostic at the worst moment) by another route.
    #
    # ``db_path`` deliberately gets no such default: ``close()`` reads it
    # only inside ``if self.conn:``, so it is unreachable on this path,
    # and ``None`` would be a *claim* about a path rather than the exact
    # truth that ``conn = None`` states about a connection.
    conn: Optional[sqlite3.Connection] = None

    def __init__(self, db_path: str | Path):
        """
        Initialize database connection.

        Args:
            db_path: Path to the SQLite database file

        Raises:
            DatabaseConnectionError: If connection fails
        """
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self._txn_depth = 0
        self._connect()

    def _connect(self) -> None:
        """Establish database connection with proper configuration"""
        try:
            # Transaction control is PINNED to the legacy mode this layer
            # was written against, rather than left to the default.
            #
            # `autocommit` arrived in Python 3.12 and the stdlib's default
            # is documented as changing to `False` in a future release. A
            # silent flip would land squarely on `transaction()` below, so
            # the mode is stated here instead of inherited.
            #
            # `False` (PEP 249 mode) was measured and REJECTED, twice over:
            #   * it keeps a transaction open at all times, and
            #     `PRAGMA journal_mode = WAL` cannot run inside one --
            #     "cannot change into wal mode from within a transaction",
            #     so this very method would fail;
            #   * a transaction always being open means any bare SELECT
            #     pins a read snapshot until the next commit. A pinned
            #     snapshot makes `PRAGMA wal_checkpoint(TRUNCATE)` return
            #     busy=1 (measured), which is exactly the condition that
            #     leaves a copied database missing its WAL tail (#155).
            #     In a GUI process holding one connection for hours, that
            #     would turn a rare race into the normal case.
            # What PEP 249 mode would have bought -- making #95's
            # savepoint-commits-the-parent shape structurally impossible --
            # is already bought by the explicit BEGIN in `transaction()`,
            # which is tested directly.
            connect_kwargs = {}
            legacy_mode = getattr(sqlite3, "LEGACY_TRANSACTION_CONTROL", None)
            if legacy_mode is not None:  # Python 3.12+; CI still runs 3.11
                connect_kwargs["autocommit"] = legacy_mode

            self.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # Allow multi-threaded access
                timeout=10.0,  # 10 second timeout
                **connect_kwargs,
            )

            # Enable foreign keys
            self.conn.execute("PRAGMA foreign_keys = ON")

            # Use WAL mode for better concurrency
            self.conn.execute("PRAGMA journal_mode = WAL")

            # NORMAL is the documented counterpart to WAL: writers stop
            # syncing the WAL on every single commit. WIMI commits
            # constantly (autosave writes a field at a time), and each one
            # was paying a full disk barrier for durability nobody asked
            # for. WAL + NORMAL cannot corrupt the database; what it gives
            # up is the last few committed transactions on a power cut or
            # kernel panic. An application crash is still safe.
            self.conn.execute("PRAGMA synchronous = NORMAL")

            # Bounds the work `PRAGMA optimize` does on close. SQLite
            # 3.46 limits it automatically; 3.45 (what Python 3.12 bundles)
            # does not, so an un-capped ANALYZE could stall a close.
            self.conn.execute("PRAGMA analysis_limit = 1000")

            # Row factory for dict-like access
            self.conn.row_factory = sqlite3.Row

            logger.info(f"Connected to database: {self.db_path}")
            
        except sqlite3.Error as e:
            raise DatabaseConnectionError(f"Failed to connect to {self.db_path}: {e}")

    @contextmanager
    def closing_on_failed_init(self):
        """Close this connection if the work inside fails, then re-raise.

        **A constructor that opens a connection owns closing it.** Every
        subclass here connects in ``__init__`` and then does more work —
        migrations, a device-row claim, the graph, ``ANALYZE`` — and a
        failure in any of it escapes ``__init__`` *before the caller's
        assignment completes*. So the caller holds ``None``, not a
        half-built object, and cannot close what it was never handed:

            verify_db = None
            try:
                verify_db = UserDatabase(...)   # raises inside __init__
            except Exception:
                if verify_db is not None:       # False. Never assigned.
                    verify_db.close()

        That is ``profile_archive.install_profile_as_new``'s rollback,
        written correctly against an object it cannot get. The guard is
        not defensive there; it misfires exactly when there is something
        to close (#292).

        On POSIX the consequence is invisible — a failed import's
        ``unlink`` succeeds on an open file — so this held for the whole
        life of the code and was found only on Windows, which refuses. It
        is the same class as #151 and as ``test_graph_phase1.py``'s
        teardown errors: *only Windows refuses to touch a file something
        still holds open*, and the fix belongs on this side of the call
        rather than in each caller.

        ``gc.collect()`` is **not** an alternative, and that was measured
        rather than assumed (#281 comment #4076): the half-built object
        stays reachable through ``exc.__traceback__`` -> the constructor's
        frame -> ``self``, so the handle outlives any collection the
        caller can force.

        ``BaseException`` and a bare ``raise``: an interrupt during a
        migration must release the file too, and the caller must see the
        original failure. A failure *from the close* is logged and
        dropped, never allowed to replace the diagnosis — #281's whole
        complaint is an irrelevant exception arriving on top of a real
        one.
        """
        try:
            yield
        except BaseException:
            try:
                self.close()
            except Exception as close_exc:
                logger.warning(
                    f"Could not close {self.db_path} after a failed "
                    f"initialization: {close_exc}"
                )
            raise

    def write_planner_statistics(self) -> None:
        """Run ``ANALYZE``, best-effort. Called when a profile is opened.

        **It must be ``ANALYZE`` and not ``PRAGMA optimize``, and that is
        measured rather than preferred (#218).** On SQLite 3.45 — what
        Python 3.12 bundles — ``PRAGMA optimize`` analyses a table only if
        a query in the *same connection* has already used an index on it.
        WIMI's open path never queries ``subject_nodes``,
        ``subject_edges``, ``question_entries`` or
        ``entry_subject_mappings``, so ``PRAGMA optimize`` here writes
        **zero rows at every database size** and changes no plan: a dry
        run (``PRAGMA optimize(0x03)``) after ``__init__`` names only
        ``device_source_settings``, which is empty. The ``0x10``
        "analyze all" bit that would fix it does not exist before 3.46.

        Why it runs at all, from #218: ``close()``'s ``PRAGMA optimize``
        was the only thing that ever wrote ``sqlite_stat1``, so a profile
        had **no planner statistics for the whole of its first session** —
        covering a new profile, one installed from a ``.wimi``, and one
        taken from a sync folder (#151). Measured on a real 13,967-node
        profile with six exams, statistics absent vs present:

        * ``get_subject_hierarchy`` on the active exam: **6,141 ms -> 60 ms**
        * the same on the largest tree (3,404 nodes): 4,918 ms -> 92 ms
        * a dimensional sunburst: 2,365 ms -> 32 ms
        * ``get_subject_deep_dive``: 2,480 ms -> 59 ms

        Payloads were byte-identical in every case. The cost here is
        **3.5 ms** on that profile, and it is flat in database size
        because ``analysis_limit = 1000`` is set in ``_connect`` — without
        that bound the same work is 60x worse at a million rows.

        **One known regression, disclosed rather than discovered later.**
        ``get_subject_analytics`` is *slower* with statistics on every
        exam of that profile — 5.1 -> 15.3 ms at worst, 1.4x to 3.8x. In
        absolute terms the worst case adds 10 ms while the best case saves
        6,081 ms, which is why this ships; but it is a real cost and the
        inversion is **#273**: statistics lose the selectivity of the exam
        filter in #199's rollup join, so `entry_subject_mappings` is scanned
        whole. Do not read this regression as an argument against ANALYZE --
        read #273.

        Best-effort for the same reason ``close()``'s pragma is: a
        read-only file, or a short-lived verify-open, must not fail
        because the planner would like better statistics.
        """
        if not self.conn:
            return
        try:
            self.conn.execute("ANALYZE")
        except sqlite3.Error as e:
            logger.warning(f"ANALYZE failed on open, continuing: {e}")

    def close(self) -> None:
        """Close database connection.

        Runs ``PRAGMA optimize`` first. WIMI holds one connection per
        profile open for a whole session, which is the case SQLite's docs
        name for it, and the migration runner adds indexes over time --
        after which the planner is working from stale or absent
        ``sqlite_stat1`` rows until something runs ANALYZE. Nothing ever
        did.

        **It is not sufficient on its own**, which is what #218 found:
        statistics written here only help the *next* session, so the first
        one ran unanalysed. ``write_planner_statistics()`` covers that,
        and note that ``PRAGMA optimize`` is correct *here* and wrong
        there — by the time a session closes it has issued the
        index-using queries that arm it.

        It is best-effort by design: a failure here (a read-only file, a
        connection already broken by the error that prompted the close)
        must never stop the close itself, because a leaked handle is a
        real problem on Windows and stale planner statistics are not.
        """
        if self.conn:
            try:
                self.conn.execute("PRAGMA optimize")
            except sqlite3.Error as e:
                logger.warning(f"PRAGMA optimize failed on close, continuing: {e}")
            self.conn.close()
            self.conn = None
            self._txn_depth = 0
            logger.info(f"Closed database connection: {self.db_path}")

    @property
    def transaction_depth(self) -> int:
        """How many :meth:`transaction` blocks are currently open.

        ``0`` outside any transaction. Read-only; tests assert on it and
        a domain method may use it to tell "I am the outermost" from "I
        am nested", but nothing should write it.
        """
        return self._txn_depth

    @contextmanager
    def transaction(self):
        """
        Context manager for database transactions. **Re-entrant** (#95).

        Usage::

            with db.transaction():
                db.execute("INSERT ...")
                db.execute("UPDATE ...")

        Nesting is real, so a composite operation can be written as a
        method that opens a transaction and calls other methods that open
        their own — which is the normal shape of this layer
        (``create_subject_node``, ``EdgesMixin.add_edge``,
        ``delete_subject_subtree`` are all both entry points and
        sub-steps). **Only the outermost block commits.** An inner block
        that fails discards its own work and leaves the enclosing
        transaction alive to decide; an outer block that fails discards
        everything, inner work included.

        Mechanics, and why each piece is there:

        * **Depth 1 issues an explicit** ``BEGIN`` (guarded on
          ``conn.in_transaction``, since re-issuing it inside an open
          transaction raises ``OperationalError``), and is the only level
          that calls ``commit()`` / ``rollback()``.
        * **Depth ≥ 2 issues** ``SAVEPOINT wimi_sp_<depth>`` and leaves
          through ``RELEASE`` on success or ``ROLLBACK TO`` + ``RELEASE``
          on failure. Depth makes the name unique within a stack.

        The explicit ``BEGIN`` is load-bearing, not tidiness. This
        connection runs on the sqlite3 module's legacy transaction
        control (``isolation_level=''``), which begins a transaction
        implicitly before DML and *not* before anything else — so an
        outer block that has not yet written anything is not in a
        transaction at all. A ``SAVEPOINT`` opened there starts the
        transaction itself, and SQLite **commits** when the outermost
        savepoint is released: the inner block's ``RELEASE`` would commit
        the outer block's work, which is the very bug #95 is about,
        wearing a savepoint. Verified against Python 3.12 / SQLite 3.45.

        Re-entrancy is tracked **per instance**, which is per connection —
        SQLite's transaction state is a property of the connection, so a
        thread-local counter would be wrong rather than merely different
        (two threads sharing one connection cannot hold two independent
        transactions in any case). ``check_same_thread=False`` is set, but
        nothing in the application writes from a second thread; the one
        background thread in the process is ``ErrorLogger``'s flush
        ticker, which touches files and never a database connection.

        One thing this cannot defend against: a bare ``self.conn.commit()``
        executed from inside a transaction block commits everything above
        it, so the enclosing ``__exit__`` has nothing left to roll back.

        **Do not restate that no code path does this.** That sentence stood
        here for a long time and was false twice — ``dimensions.py`` (#211)
        and ``schema_migrations.py`` (#232) — and each time it was the
        reason nobody checked. It is enforced now instead of asserted:
        ``tests/database/test_no_bare_commit_inside_a_transaction.py``
        walks the call graph from every ``with ... transaction():`` block
        and fails on anything that reaches a bare commit.

        ``sqlite3``'s ``executescript`` is the same hazard wearing different
        clothes: it issues an **implicit COMMIT before it runs**, so it ends
        an open transaction whatever the calling code does afterwards. A
        ``with self.transaction():`` around one is a false fix. See
        ``SchemaMigrationMixin._executescript_at_top_level``.
        """
        depth = self._txn_depth + 1
        savepoint: Optional[str] = None

        if depth == 1:
            # A transaction may already be open from DML issued outside
            # any transaction block; adopt it rather than fail on BEGIN.
            if not self.conn.in_transaction:
                self.conn.execute("BEGIN")
        else:
            savepoint = f"wimi_sp_{depth}"
            self.conn.execute(f"SAVEPOINT {savepoint}")

        self._txn_depth = depth
        try:
            yield self.conn
            if savepoint is None:
                self.conn.commit()
            else:
                self.conn.execute(f"RELEASE {savepoint}")
        except Exception as e:
            # The recovery statements get their own guard so a failure to
            # unwind (a dead connection, a savepoint SQLite already
            # discarded) is reported without masking the original cause.
            try:
                if savepoint is None:
                    self.conn.rollback()
                else:
                    self.conn.execute(f"ROLLBACK TO {savepoint}")
                    self.conn.execute(f"RELEASE {savepoint}")
            except sqlite3.Error as unwind_error:
                logger.error(
                    f"Transaction unwind failed at depth {depth}: {unwind_error}"
                )
            if savepoint is None:
                logger.error(f"Transaction failed, rolled back: {e}")
            else:
                logger.error(
                    f"Nested transaction failed at depth {depth}, "
                    f"rolled back to savepoint {savepoint}: {e}"
                )
            raise
        finally:
            self._txn_depth = depth - 1

    def execute(self, sql: str, params: Optional[Tuple | Dict] = None) -> sqlite3.Cursor:
        """
        Execute a single SQL statement.
        
        Args:
            sql: SQL statement to execute
            params: Optional parameters for the SQL statement
            
        Returns:
            Cursor object with query results
            
        Raises:
            DatabaseIntegrityError: If integrity constraint is violated
            BaseDatabaseError: For other database errors
        """
        try:
            if params:
                return self.conn.execute(sql, params)
            return self.conn.execute(sql)
        except sqlite3.IntegrityError as e:
            raise DatabaseIntegrityError(f"Integrity constraint violated: {e}")
        except sqlite3.Error as e:
            raise BaseDatabaseError(f"Database error: {e}")
    
    def execute_many(self, sql: str, params_list: List[Tuple | Dict]) -> None:
        """
        Execute the same SQL statement with multiple parameter sets.
        
        Args:
            sql: SQL statement to execute
            params_list: List of parameter tuples/dicts
        """
        try:
            self.conn.executemany(sql, params_list)
        except sqlite3.Error as e:
            raise BaseDatabaseError(f"Batch execution failed: {e}")
    
    def fetchone(self, sql: str, params: Optional[Tuple | Dict] = None) -> Optional[Dict]:
        """
        Execute query and fetch one result.
        
        Args:
            sql: SQL SELECT statement
            params: Optional parameters
            
        Returns:
            Dict-like Row object or None
        """
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def fetchall(self, sql: str, params: Optional[Tuple | Dict] = None) -> List[Dict]:
        """
        Execute query and fetch all results.
        
        Args:
            sql: SQL SELECT statement
            params: Optional parameters
            
        Returns:
            List of Dict-like Row objects
        """
        cursor = self.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_table_names(self) -> List[str]:
        """Get list of all tables in the database"""
        result = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row['name'] for row in result]
    
    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database"""
        result = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return result is not None
    
    def get_schema_version(self) -> str:
        """
        Get current schema version.
        Subclasses should override this if they track versions differently.
        """
        if not self.table_exists('schema_version'):
            return '0.0.0'
        
        result = self.fetchone(
            "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
        )
        return result['version'] if result else '0.0.0'
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection"""
        self.close()
    
    def __del__(self):
        """Ensure connection is closed on deletion"""
        self.close()
