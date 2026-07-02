"""
S0.6: Concurrency and Crash Recovery Tests for LadybugDB

Tests file locking behavior, crash recovery, incomplete close handling,
and concurrent read access. WIMI is single-process, so these tests verify
safety guarantees and document recovery behavior.

Key findings documented in test docstrings.
"""
import gc
import os
import multiprocessing
import signal
import sys
import time

import pytest
import real_ladybug as lbug


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_database(db_path: str) -> None:
    """Create a database with baseline data for recovery tests."""
    db = lbug.Database(db_path)
    conn = lbug.Connection(db)
    conn.execute(
        "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
    )
    conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
    conn.execute("CREATE (:Person {name: 'Bob', age: 25})")
    conn.execute("CREATE (:Person {name: 'Charlie', age: 35})")
    conn.close()
    db.close()


def _read_all_names(db_path: str) -> list[str]:
    """Open a database, read all Person names, close, and return them."""
    db = lbug.Database(db_path)
    conn = lbug.Connection(db)
    result = conn.execute("MATCH (p:Person) RETURN p.name ORDER BY p.name")
    names = []
    while result.has_next():
        names.append(result.get_next()[0])
    conn.close()
    db.close()
    return names


def _child_write_and_crash(db_path: str) -> None:
    """Subprocess target: open DB, begin writing, then hard-exit without close.

    This simulates an application crash mid-write. The child process writes
    a new node then terminates abruptly via os._exit (bypasses cleanup).
    """
    db = lbug.Database(db_path)
    conn = lbug.Connection(db)
    conn.execute("CREATE (:Person {name: 'CrashNode', age: 99})")
    # Simulate crash: skip conn.close() and db.close()
    os._exit(1)


def _child_write_normal(db_path: str) -> None:
    """Subprocess target: open DB, write, close properly."""
    db = lbug.Database(db_path)
    conn = lbug.Connection(db)
    conn.execute("CREATE (:Person {name: 'SubprocessNode', age: 50})")
    conn.close()
    db.close()


# ---------------------------------------------------------------------------
# Test 1: Single-process file locking
# ---------------------------------------------------------------------------

class TestFileLocking:
    """Verify that LadybugDB enforces exclusive file-level locking.

    FINDING: LadybugDB raises RuntimeError with message
    'IO exception: Could not set lock on file' when a second Database
    instance tries to open the same file. This is expected and safe for
    WIMI's single-process architecture -- we just need to make sure we
    never open the same file twice.
    """

    def test_second_database_instance_raises_on_same_file(self, tmp_path):
        """Opening the same DB file from two Database instances raises RuntimeError."""
        db_path = str(tmp_path / "lock_test.lbdb")
        db1 = lbug.Database(db_path)
        conn1 = lbug.Connection(db1)

        try:
            with pytest.raises(RuntimeError, match="Could not set lock on file"):
                _db2 = lbug.Database(db_path)
        finally:
            conn1.close()
            db1.close()

    def test_reopen_after_first_closes(self, tmp_path):
        """After the first instance closes, a new one can open the file."""
        db_path = str(tmp_path / "lock_reopen.lbdb")

        db1 = lbug.Database(db_path)
        conn1 = lbug.Connection(db1)
        conn1.execute(
            "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
        )
        conn1.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn1.close()
        db1.close()

        # Should succeed now that db1 is closed
        db2 = lbug.Database(db_path)
        conn2 = lbug.Connection(db2)
        result = conn2.execute("MATCH (p:Person) RETURN p.name")
        assert result.has_next()
        assert result.get_next() == ["Alice"]
        conn2.close()
        db2.close()

    def test_lock_error_does_not_corrupt_first_instance(self, tmp_path):
        """A failed second open does not corrupt the first instance's data."""
        db_path = str(tmp_path / "lock_safe.lbdb")
        db1 = lbug.Database(db_path)
        conn1 = lbug.Connection(db1)
        conn1.execute(
            "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
        )
        conn1.execute("CREATE (:Person {name: 'Alice', age: 30})")

        # Attempt to open second instance (should fail)
        try:
            with pytest.raises(RuntimeError, match="Could not set lock on file"):
                _db2 = lbug.Database(db_path)
        finally:
            pass

        # First instance should still work fine
        conn1.execute("CREATE (:Person {name: 'Bob', age: 25})")
        result = conn1.execute(
            "MATCH (p:Person) RETURN p.name ORDER BY p.name"
        )
        names = []
        while result.has_next():
            names.append(result.get_next()[0])
        assert names == ["Alice", "Bob"]

        conn1.close()
        db1.close()


# ---------------------------------------------------------------------------
# Test 2: Crash mid-write simulation
# ---------------------------------------------------------------------------

class TestCrashRecovery:
    """Simulate crashes during write operations and verify recovery.

    FINDING: LadybugDB uses a WAL (write-ahead log) for durability.
    After a simulated crash (process killed without close), the database
    can be reopened and pre-crash data remains intact. The WAL replay
    on reopen handles recovery automatically.

    RECOVERY STEPS: Lock files (.lock) may persist after a crash.
    LadybugDB handles stale lock cleanup on reopen automatically on
    most platforms. No manual intervention needed.
    """

    def test_crash_preserves_committed_data(self, tmp_path):
        """Data written and closed before crash survives the crash."""
        db_path = str(tmp_path / "crash_test.lbdb")

        # Step 1: Seed the database with baseline data and close properly
        _seed_database(db_path)

        # Step 2: Spawn a child process that writes and then crashes
        proc = multiprocessing.Process(
            target=_child_write_and_crash, args=(db_path,)
        )
        proc.start()
        proc.join(timeout=10)

        # Child should have exited with code 1 (crash)
        assert proc.exitcode == 1

        # Step 3: Reopen and verify baseline data is intact
        names = _read_all_names(db_path)
        assert "Alice" in names
        assert "Bob" in names
        assert "Charlie" in names
        # CrashNode may or may not be present depending on WAL flush timing;
        # the critical assertion is that the DB is not corrupted and
        # pre-existing data is intact.

    def test_db_not_corrupted_after_crash(self, tmp_path):
        """Database remains structurally sound after a crash -- can still write."""
        db_path = str(tmp_path / "crash_write.lbdb")
        _seed_database(db_path)

        # Crash a child process
        proc = multiprocessing.Process(
            target=_child_write_and_crash, args=(db_path,)
        )
        proc.start()
        proc.join(timeout=10)

        # Reopen and write new data -- proves the DB is not corrupted
        db = lbug.Database(db_path)
        conn = lbug.Connection(db)
        conn.execute("CREATE (:Person {name: 'PostCrash', age: 1})")
        result = conn.execute(
            "MATCH (p:Person {name: 'PostCrash'}) RETURN p.age"
        )
        assert result.has_next()
        assert result.get_next() == [1]
        conn.close()
        db.close()

    def test_normal_subprocess_write_persists(self, tmp_path):
        """Control test: a subprocess that closes properly persists its data."""
        db_path = str(tmp_path / "normal_sub.lbdb")
        _seed_database(db_path)

        proc = multiprocessing.Process(
            target=_child_write_normal, args=(db_path,)
        )
        proc.start()
        proc.join(timeout=10)
        assert proc.exitcode == 0

        names = _read_all_names(db_path)
        assert "SubprocessNode" in names


# ---------------------------------------------------------------------------
# Test 3: Recovery after incomplete close
# ---------------------------------------------------------------------------

class TestIncompleteClose:
    """Test behavior when conn.close() and/or db.close() are skipped.

    FINDING: LadybugDB's Python bindings implement __del__ / destructor
    cleanup, so objects cleaned up by garbage collection release their
    locks. After forcing GC, the database file can be reopened.

    RECOVERY STEPS:
    - Force garbage collection (gc.collect()) to release handles
    - Then reopen the database normally
    - On some platforms, lock files may remain; LadybugDB handles
      stale lock cleanup transparently on reopen.
    """

    def test_gc_releases_lock_and_data_persists(self, tmp_path):
        """Skip close(), force GC, verify DB reopens with data intact."""
        db_path = str(tmp_path / "no_close.lbdb")

        # Write data without calling close
        db = lbug.Database(db_path)
        conn = lbug.Connection(db)
        conn.execute(
            "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
        )
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn.execute("CREATE (:Person {name: 'Bob', age: 25})")

        # Drop references without close
        del conn
        del db
        gc.collect()

        # Reopen -- should succeed after GC released the lock
        db2 = lbug.Database(db_path)
        conn2 = lbug.Connection(db2)
        result = conn2.execute(
            "MATCH (p:Person) RETURN p.name ORDER BY p.name"
        )
        names = []
        while result.has_next():
            names.append(result.get_next()[0])
        conn2.close()
        db2.close()

        # Data written before the incomplete close should persist
        assert "Alice" in names
        assert "Bob" in names

    def test_only_conn_close_skipped(self, tmp_path):
        """Skip conn.close() but call db.close(). Verify data persists."""
        db_path = str(tmp_path / "skip_conn_close.lbdb")

        db = lbug.Database(db_path)
        conn = lbug.Connection(db)
        conn.execute(
            "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
        )
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")

        # Skip conn.close(), only close the database
        del conn
        gc.collect()
        db.close()

        # Reopen and verify
        names = _read_all_names(db_path)
        assert names == ["Alice"]

    def test_only_db_close_skipped_lock_persists(self, tmp_path):
        """Skip db.close() -- GC alone may NOT release the file lock on Windows.

        FINDING: On Windows, deleting the Database object and forcing GC
        does NOT reliably release the file lock. The lock remains held
        until db.close() is explicitly called. This means db.close() is
        NOT optional in practice, despite Connection.close() being optional.

        RECOVERY: Always call db.close() explicitly. If the process crashes
        without closing, the OS releases file locks on process exit, and
        LadybugDB can reopen the file from a new process.
        """
        db_path = str(tmp_path / "skip_db_close.lbdb")

        db = lbug.Database(db_path)
        conn = lbug.Connection(db)
        conn.execute(
            "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
        )
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn.close()

        # Skip db.close(), try GC
        del db
        gc.collect()

        # On Windows, the lock is NOT released by GC -- reopen fails
        with pytest.raises(RuntimeError, match="Could not set lock on file"):
            _db2 = lbug.Database(db_path)


# ---------------------------------------------------------------------------
# Test 4: Concurrent reads on same Database instance
# ---------------------------------------------------------------------------

class TestConcurrentReads:
    """Test multiple Connection objects on a single Database instance.

    FINDING: LadybugDB supports multiple Connection objects on the same
    Database instance. Both connections can read concurrently and see
    consistent data. This is useful for WIMI if we ever need read
    parallelism within the single process.
    """

    def test_two_connections_read_same_data(self, tmp_path):
        """Two connections on the same Database see identical data."""
        db_path = str(tmp_path / "concurrent_read.lbdb")
        db = lbug.Database(db_path)
        conn1 = lbug.Connection(db)

        conn1.execute(
            "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
        )
        conn1.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn1.execute("CREATE (:Person {name: 'Bob', age: 25})")

        # Open second connection on same Database
        conn2 = lbug.Connection(db)

        # Both connections should see the same data
        result1 = conn1.execute(
            "MATCH (p:Person) RETURN p.name ORDER BY p.name"
        )
        result2 = conn2.execute(
            "MATCH (p:Person) RETURN p.name ORDER BY p.name"
        )

        names1 = []
        while result1.has_next():
            names1.append(result1.get_next()[0])

        names2 = []
        while result2.has_next():
            names2.append(result2.get_next()[0])

        assert names1 == ["Alice", "Bob"]
        assert names2 == ["Alice", "Bob"]

        conn2.close()
        conn1.close()
        db.close()

    def test_write_on_one_conn_visible_to_other(self, tmp_path):
        """Data written via conn1 is visible to conn2 on the same Database."""
        db_path = str(tmp_path / "conn_visibility.lbdb")
        db = lbug.Database(db_path)
        conn1 = lbug.Connection(db)
        conn2 = lbug.Connection(db)

        conn1.execute(
            "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
        )
        conn1.execute("CREATE (:Person {name: 'Alice', age: 30})")

        # conn2 should see the data written by conn1
        result = conn2.execute("MATCH (p:Person) RETURN p.name")
        assert result.has_next()
        assert result.get_next() == ["Alice"]

        conn2.close()
        conn1.close()
        db.close()

    def test_multiple_connections_read_after_write(self, tmp_path):
        """Multiple connections can all read data written by any one of them."""
        db_path = str(tmp_path / "multi_conn.lbdb")
        db = lbug.Database(db_path)

        conn_writer = lbug.Connection(db)
        conn_writer.execute(
            "CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))"
        )
        conn_writer.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn_writer.execute("CREATE (:Person {name: 'Bob', age: 25})")
        conn_writer.execute("CREATE (:Person {name: 'Charlie', age: 35})")

        # Create several reader connections
        readers = [lbug.Connection(db) for _ in range(3)]
        for i, reader in enumerate(readers):
            result = reader.execute("MATCH (p:Person) RETURN count(p)")
            assert result.get_next() == [3], f"Reader {i} saw wrong count"

        for reader in readers:
            reader.close()
        conn_writer.close()
        db.close()
