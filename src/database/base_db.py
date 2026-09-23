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
    
    def close(self) -> None:
        """Close database connection.

        Runs ``PRAGMA optimize`` first. WIMI holds one connection per
        profile open for a whole session, which is the case SQLite's docs
        name for it, and the migration runner adds indexes over time --
        after which the planner is working from stale or absent
        ``sqlite_stat1`` rows until something runs ANALYZE. Nothing ever
        did.

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
        it. No code path does that today — every bare commit in
        ``src/database`` sits in a method that is only ever called at the
        top level — but do not add one.
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
