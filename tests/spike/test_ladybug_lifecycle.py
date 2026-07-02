"""
S0.7: Connection Lifecycle Test — LadybugDB alongside SQLite

Tests that LadybugDB and SQLite can coexist in the same application lifecycle,
simulating the exact patterns WIMI would use for dual-database operation.

Connection Lifecycle API Documentation
=======================================

LadybugDB (real_ladybug / kuzu):
    1. Create a Database:
        db = lbug.Database("/path/to/file.lbdb")
        - Path must be a FILE path, not a directory.
        - The file (and supporting files) are created automatically.

    2. Create a Connection:
        conn = lbug.Connection(db)
        - A Connection is required for all queries.
        - Multiple connections can be created from one Database.

    3. Execute queries:
        result = conn.execute("MATCH (n) RETURN n.name")
        while result.has_next():
            row = result.get_next()  # returns a list

    4. Close properly:
        conn.close()  # Close connection(s) first
        db.close()    # Then close the database

    Gotchas:
        - Must close Connection before Database.
        - Must close Database before reopening the same file (file locking).
        - Close order between LadybugDB and SQLite does not matter — they are
          independent file handles with no cross-dependency.
        - The Database path must point to a file, not a directory.

SQLite (sqlite3):
    Standard Python sqlite3 module — conn = sqlite3.connect(path), cursor,
    commit, close. No special considerations when used alongside LadybugDB.
"""
import sqlite3
import pytest
import real_ladybug as lbug


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_graph_schema(conn):
    """Create a subject hierarchy schema in LadybugDB."""
    conn.execute(
        "CREATE NODE TABLE Subject("
        "  sid INT64,"
        "  name STRING,"
        "  PRIMARY KEY (sid)"
        ")"
    )
    conn.execute(
        "CREATE REL TABLE ChildOf(FROM Subject TO Subject)"
    )


def _setup_sqlite_schema(sql_conn):
    """Create a minimal WIMI-like entries table in SQLite."""
    sql_conn.execute(
        "CREATE TABLE IF NOT EXISTS question_entries ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  content TEXT NOT NULL,"
        "  subject_id INTEGER"
        ")"
    )
    sql_conn.commit()


def _collect_all(result):
    """Drain a LadybugDB result set into a list of rows."""
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    return rows


# ---------------------------------------------------------------------------
# Test 1: Simultaneous open — interleaved reads and writes
# ---------------------------------------------------------------------------

class TestSimultaneousOpen:
    """Open SQLite and LadybugDB at the same time and interleave operations."""

    def test_interleaved_writes_and_reads(self, tmp_path):
        # Open both databases
        sqlite_path = str(tmp_path / "user.db")
        graph_path = str(tmp_path / "graph.lbdb")

        sql_conn = sqlite3.connect(sqlite_path)
        graph_db = lbug.Database(graph_path)
        graph_conn = lbug.Connection(graph_db)

        # --- Setup schemas ---
        _setup_sqlite_schema(sql_conn)
        _setup_graph_schema(graph_conn)

        # --- Interleaved write 1: SQLite ---
        sql_conn.execute(
            "INSERT INTO question_entries (content, subject_id) VALUES (?, ?)",
            ("What is the heart?", 1),
        )
        sql_conn.commit()

        # --- Interleaved write 2: LadybugDB ---
        graph_conn.execute("CREATE (:Subject {sid: 1, name: 'Cardiology'})")

        # --- Interleaved write 3: SQLite ---
        sql_conn.execute(
            "INSERT INTO question_entries (content, subject_id) VALUES (?, ?)",
            ("What is the liver?", 2),
        )
        sql_conn.commit()

        # --- Interleaved write 4: LadybugDB ---
        graph_conn.execute("CREATE (:Subject {sid: 2, name: 'Hepatology'})")

        # --- Read from SQLite ---
        cursor = sql_conn.execute(
            "SELECT id, content FROM question_entries ORDER BY id"
        )
        sql_rows = cursor.fetchall()
        assert len(sql_rows) == 2
        assert sql_rows[0][1] == "What is the heart?"
        assert sql_rows[1][1] == "What is the liver?"

        # --- Read from LadybugDB ---
        result = graph_conn.execute(
            "MATCH (s:Subject) RETURN s.sid, s.name ORDER BY s.sid"
        )
        graph_rows = _collect_all(result)
        assert len(graph_rows) == 2
        assert graph_rows[0] == [1, "Cardiology"]
        assert graph_rows[1] == [2, "Hepatology"]

        # Cleanup
        graph_conn.close()
        graph_db.close()
        sql_conn.close()


# ---------------------------------------------------------------------------
# Test 2: WIMI lifecycle pattern — full open/write/close/reopen cycle
# ---------------------------------------------------------------------------

class TestWIMILifecyclePattern:
    """Simulate the exact dual-DB lifecycle WIMI would use."""

    def test_full_lifecycle(self, tmp_path):
        sqlite_path = str(tmp_path / "user_001.db")
        graph_path = str(tmp_path / "user_001_graph.lbdb")

        # ---- Phase 1: Open both databases ----
        sql_conn = sqlite3.connect(sqlite_path)
        graph_db = lbug.Database(graph_path)
        graph_conn = lbug.Connection(graph_db)

        _setup_sqlite_schema(sql_conn)
        _setup_graph_schema(graph_conn)

        # ---- Phase 2: Write to SQLite, get auto-increment ID ----
        cursor = sql_conn.execute(
            "INSERT INTO question_entries (content, subject_id) VALUES (?, ?)",
            ("Missed the aortic valve question", 10),
        )
        sql_conn.commit()
        entry_id = cursor.lastrowid
        assert entry_id == 1  # first row

        # ---- Phase 3: Write to LadybugDB using that SQLite ID ----
        graph_conn.execute(
            "CREATE (:Subject {sid: 10, name: 'Cardiac Anatomy'})"
        )
        # In the real app, we might also store a reference node linking
        # the entry to the graph, but for this spike we just verify
        # the cross-reference pattern works.

        # ---- Phase 4: Query LadybugDB to verify ----
        result = graph_conn.execute(
            "MATCH (s:Subject {sid: 10}) RETURN s.name"
        )
        rows = _collect_all(result)
        assert rows == [["Cardiac Anatomy"]]

        # ---- Phase 5: Close LadybugDB first, then SQLite ----
        graph_conn.close()
        graph_db.close()
        sql_conn.close()

        # ---- Phase 6: Reopen both and verify persistence ----
        sql_conn2 = sqlite3.connect(sqlite_path)
        graph_db2 = lbug.Database(graph_path)
        graph_conn2 = lbug.Connection(graph_db2)

        # Verify SQLite data survived
        cursor2 = sql_conn2.execute(
            "SELECT id, content, subject_id FROM question_entries WHERE id = ?",
            (entry_id,),
        )
        row = cursor2.fetchone()
        assert row is not None
        assert row[0] == entry_id
        assert row[1] == "Missed the aortic valve question"
        assert row[2] == 10

        # Verify LadybugDB data survived
        result2 = graph_conn2.execute(
            "MATCH (s:Subject {sid: 10}) RETURN s.name"
        )
        rows2 = _collect_all(result2)
        assert rows2 == [["Cardiac Anatomy"]]

        # Cleanup
        graph_conn2.close()
        graph_db2.close()
        sql_conn2.close()


# ---------------------------------------------------------------------------
# Test 3: Two-step query pattern — graph traversal then SQL lookup
# ---------------------------------------------------------------------------

class TestTwoStepQueryPattern:
    """
    Query LadybugDB for descendant IDs via graph traversal, then use those
    IDs to fetch full entry content from SQLite.
    """

    def test_graph_traversal_then_sql_lookup(self, tmp_path):
        sqlite_path = str(tmp_path / "user.db")
        graph_path = str(tmp_path / "graph.lbdb")

        sql_conn = sqlite3.connect(sqlite_path)
        graph_db = lbug.Database(graph_path)
        graph_conn = lbug.Connection(graph_db)

        _setup_sqlite_schema(sql_conn)
        _setup_graph_schema(graph_conn)

        # ---- Build subject hierarchy in LadybugDB ----
        # Medicine -> Cardiology -> Heart Failure
        #                        -> Arrhythmia
        #          -> Nephrology
        graph_conn.execute("CREATE (:Subject {sid: 1, name: 'Medicine'})")
        graph_conn.execute("CREATE (:Subject {sid: 2, name: 'Cardiology'})")
        graph_conn.execute("CREATE (:Subject {sid: 3, name: 'Heart Failure'})")
        graph_conn.execute("CREATE (:Subject {sid: 4, name: 'Arrhythmia'})")
        graph_conn.execute("CREATE (:Subject {sid: 5, name: 'Nephrology'})")

        # ChildOf edges (child -> parent)
        graph_conn.execute(
            "MATCH (c:Subject {sid: 2}), (p:Subject {sid: 1}) "
            "CREATE (c)-[:ChildOf]->(p)"
        )
        graph_conn.execute(
            "MATCH (c:Subject {sid: 3}), (p:Subject {sid: 2}) "
            "CREATE (c)-[:ChildOf]->(p)"
        )
        graph_conn.execute(
            "MATCH (c:Subject {sid: 4}), (p:Subject {sid: 2}) "
            "CREATE (c)-[:ChildOf]->(p)"
        )
        graph_conn.execute(
            "MATCH (c:Subject {sid: 5}), (p:Subject {sid: 1}) "
            "CREATE (c)-[:ChildOf]->(p)"
        )

        # ---- Store entries in SQLite ----
        entries = [
            ("CHF management", 3),       # Heart Failure
            ("AFib diagnosis", 4),        # Arrhythmia
            ("Valve repair", 2),          # Cardiology (direct)
            ("CKD staging", 5),           # Nephrology
            ("General medicine Q", 1),    # Medicine (root)
        ]
        for content, sid in entries:
            sql_conn.execute(
                "INSERT INTO question_entries (content, subject_id) VALUES (?, ?)",
                (content, sid),
            )
        sql_conn.commit()

        # ---- Step 1: Graph traversal — find all descendants of Cardiology ----
        # Cardiology (sid=2) and its children via variable-length ChildOf path
        result = graph_conn.execute(
            "MATCH (d:Subject)-[:ChildOf*1..10]->(a:Subject {sid: 2}) "
            "RETURN d.sid"
        )
        descendant_ids = [row[0] for row in _collect_all(result)]
        # Include the ancestor itself
        all_cardiology_ids = [2] + descendant_ids
        all_cardiology_ids.sort()
        assert all_cardiology_ids == [2, 3, 4]

        # ---- Step 2: SQL lookup — fetch entries for those subject IDs ----
        placeholders = ",".join("?" * len(all_cardiology_ids))
        cursor = sql_conn.execute(
            f"SELECT id, content, subject_id FROM question_entries "
            f"WHERE subject_id IN ({placeholders}) ORDER BY id",
            all_cardiology_ids,
        )
        matched_entries = cursor.fetchall()

        assert len(matched_entries) == 3
        contents = [row[1] for row in matched_entries]
        assert "CHF management" in contents
        assert "AFib diagnosis" in contents
        assert "Valve repair" in contents
        # Nephrology and Medicine entries should NOT appear
        assert "CKD staging" not in contents
        assert "General medicine Q" not in contents

        # Cleanup
        graph_conn.close()
        graph_db.close()
        sql_conn.close()


# ---------------------------------------------------------------------------
# Test 4: Close order — graph first vs SQLite first
# ---------------------------------------------------------------------------

class TestCloseOrder:
    """Verify that close order between the two databases does not matter."""

    def _setup_both(self, tmp_path, suffix):
        """Helper to create and populate both databases."""
        sqlite_path = str(tmp_path / f"user_{suffix}.db")
        graph_path = str(tmp_path / f"graph_{suffix}.lbdb")

        sql_conn = sqlite3.connect(sqlite_path)
        graph_db = lbug.Database(graph_path)
        graph_conn = lbug.Connection(graph_db)

        _setup_sqlite_schema(sql_conn)
        _setup_graph_schema(graph_conn)

        sql_conn.execute(
            "INSERT INTO question_entries (content, subject_id) VALUES (?, ?)",
            ("Test entry", 1),
        )
        sql_conn.commit()
        graph_conn.execute("CREATE (:Subject {sid: 1, name: 'TestSubject'})")

        return sqlite_path, graph_path, sql_conn, graph_db, graph_conn

    def _verify_both(self, sqlite_path, graph_path):
        """Reopen both databases and verify data is intact."""
        sql_conn = sqlite3.connect(sqlite_path)
        cursor = sql_conn.execute("SELECT content FROM question_entries")
        assert cursor.fetchone()[0] == "Test entry"
        sql_conn.close()

        graph_db = lbug.Database(graph_path)
        graph_conn = lbug.Connection(graph_db)
        result = graph_conn.execute(
            "MATCH (s:Subject {sid: 1}) RETURN s.name"
        )
        assert result.get_next() == ["TestSubject"]
        graph_conn.close()
        graph_db.close()

    def test_close_graph_first_then_sqlite(self, tmp_path):
        """Close LadybugDB before SQLite — the expected default order."""
        sqlite_path, graph_path, sql_conn, graph_db, graph_conn = (
            self._setup_both(tmp_path, "graph_first")
        )

        # Close graph first
        graph_conn.close()
        graph_db.close()
        # Then SQLite
        sql_conn.close()

        # Verify both persisted
        self._verify_both(sqlite_path, graph_path)

    def test_close_sqlite_first_then_graph(self, tmp_path):
        """Close SQLite before LadybugDB — reversed order."""
        sqlite_path, graph_path, sql_conn, graph_db, graph_conn = (
            self._setup_both(tmp_path, "sql_first")
        )

        # Close SQLite first
        sql_conn.close()
        # Then graph
        graph_conn.close()
        graph_db.close()

        # Verify both persisted
        self._verify_both(sqlite_path, graph_path)

    def test_close_interleaved(self, tmp_path):
        """Close SQLite, then graph connection, then graph database."""
        sqlite_path, graph_path, sql_conn, graph_db, graph_conn = (
            self._setup_both(tmp_path, "interleaved")
        )

        # Interleaved: SQLite, graph conn, graph db
        sql_conn.close()
        graph_conn.close()
        graph_db.close()

        # Verify both persisted
        self._verify_both(sqlite_path, graph_path)
