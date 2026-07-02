"""
S0.2: Basic LadybugDB Graph Operations
Standalone test script exercising core graph operations.
"""
import os
import tempfile
import pytest
import real_ladybug as lbug


@pytest.fixture
def graph_db(tmp_path):
    """Create a temporary LadybugDB database."""
    db_path = str(tmp_path / "test.lbdb")
    db = lbug.Database(db_path)
    conn = lbug.Connection(db)
    yield db, conn, db_path
    conn.close()
    db.close()


class TestNodeOperations:
    """Test basic node CRUD operations."""

    def test_create_node_table(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))")
        # Verify table exists by inserting
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
        result = conn.execute("MATCH (p:Person) RETURN p.name")
        assert result.has_next()
        assert result.get_next() == ['Alice']

    def test_create_nodes_with_properties(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))")
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn.execute("CREATE (:Person {name: 'Bob', age: 25})")
        conn.execute("CREATE (:Person {name: 'Charlie', age: 35})")

        result = conn.execute("MATCH (p:Person) RETURN p.name ORDER BY p.name")
        names = []
        while result.has_next():
            names.append(result.get_next()[0])
        assert names == ['Alice', 'Bob', 'Charlie']

    def test_query_by_property_exact(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))")
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn.execute("CREATE (:Person {name: 'Bob', age: 25})")

        result = conn.execute("MATCH (p:Person {name: 'Bob'}) RETURN p.age")
        assert result.get_next() == [25]

    def test_query_by_property_filter(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))")
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn.execute("CREATE (:Person {name: 'Bob', age: 25})")
        conn.execute("CREATE (:Person {name: 'Charlie', age: 35})")

        result = conn.execute("MATCH (p:Person) WHERE p.age > 28 RETURN p.name ORDER BY p.name")
        names = []
        while result.has_next():
            names.append(result.get_next()[0])
        assert names == ['Alice', 'Charlie']

    def test_delete_node(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))")
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn.execute("CREATE (:Person {name: 'Bob', age: 25})")

        conn.execute("MATCH (p:Person {name: 'Bob'}) DELETE p")
        result = conn.execute("MATCH (p:Person) RETURN count(p)")
        assert result.get_next() == [1]


class TestEdgeOperations:
    """Test edge/relationship operations."""

    def test_create_edges(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, PRIMARY KEY (name))")
        conn.execute("CREATE REL TABLE Knows(FROM Person TO Person, since INT64)")
        conn.execute("CREATE (:Person {name: 'Alice'})")
        conn.execute("CREATE (:Person {name: 'Bob'})")
        conn.execute(
            "MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) "
            "CREATE (a)-[:Knows {since: 2020}]->(b)"
        )

        result = conn.execute(
            "MATCH (a:Person)-[k:Knows]->(b:Person) RETURN a.name, k.since, b.name"
        )
        assert result.get_next() == ['Alice', 2020, 'Bob']

    def test_single_hop_traversal(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, PRIMARY KEY (name))")
        conn.execute("CREATE REL TABLE Knows(FROM Person TO Person)")
        conn.execute("CREATE (:Person {name: 'Alice'})")
        conn.execute("CREATE (:Person {name: 'Bob'})")
        conn.execute("CREATE (:Person {name: 'Charlie'})")
        conn.execute("MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) CREATE (a)-[:Knows]->(b)")
        conn.execute("MATCH (a:Person {name: 'Alice'}), (c:Person {name: 'Charlie'}) CREATE (a)-[:Knows]->(c)")

        result = conn.execute(
            "MATCH (a:Person {name: 'Alice'})-[:Knows]->(friend) RETURN friend.name ORDER BY friend.name"
        )
        friends = []
        while result.has_next():
            friends.append(result.get_next()[0])
        assert friends == ['Bob', 'Charlie']

    def test_variable_length_traversal(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, PRIMARY KEY (name))")
        conn.execute("CREATE REL TABLE Knows(FROM Person TO Person)")
        conn.execute("CREATE (:Person {name: 'Alice'})")
        conn.execute("CREATE (:Person {name: 'Bob'})")
        conn.execute("CREATE (:Person {name: 'Charlie'})")
        conn.execute("MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) CREATE (a)-[:Knows]->(b)")
        conn.execute("MATCH (b:Person {name: 'Bob'}), (c:Person {name: 'Charlie'}) CREATE (b)-[:Knows]->(c)")

        # Variable-length path: Alice knows Bob knows Charlie
        result = conn.execute(
            "MATCH (a:Person {name: 'Alice'})-[:Knows*1..2]->(reached) RETURN reached.name ORDER BY reached.name"
        )
        reached = []
        while result.has_next():
            reached.append(result.get_next()[0])
        assert 'Bob' in reached
        assert 'Charlie' in reached

    def test_delete_edge(self, graph_db):
        db, conn, _ = graph_db
        conn.execute("CREATE NODE TABLE Person(name STRING, PRIMARY KEY (name))")
        conn.execute("CREATE REL TABLE Knows(FROM Person TO Person)")
        conn.execute("CREATE (:Person {name: 'Alice'})")
        conn.execute("CREATE (:Person {name: 'Bob'})")
        conn.execute("MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) CREATE (a)-[:Knows]->(b)")

        conn.execute("MATCH (a:Person {name: 'Alice'})-[k:Knows]->(b:Person {name: 'Bob'}) DELETE k")
        result = conn.execute("MATCH ()-[k:Knows]->() RETURN count(k)")
        assert result.get_next() == [0]


class TestPersistence:
    """Test data persistence across close/reopen."""

    def test_data_persists_after_reopen(self, tmp_path):
        db_path = str(tmp_path / "persist.lbdb")

        # Write data
        db = lbug.Database(db_path)
        conn = lbug.Connection(db)
        conn.execute("CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY (name))")
        conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
        conn.execute("CREATE (:Person {name: 'Bob', age: 25})")
        conn.close()
        db.close()

        # Reopen and verify
        db2 = lbug.Database(db_path)
        conn2 = lbug.Connection(db2)
        result = conn2.execute("MATCH (p:Person) RETURN p.name ORDER BY p.name")
        names = []
        while result.has_next():
            names.append(result.get_next()[0])
        conn2.close()
        db2.close()

        assert names == ['Alice', 'Bob']

    def test_edges_persist_after_reopen(self, tmp_path):
        db_path = str(tmp_path / "persist_edges.lbdb")

        # Write data with edges
        db = lbug.Database(db_path)
        conn = lbug.Connection(db)
        conn.execute("CREATE NODE TABLE Person(name STRING, PRIMARY KEY (name))")
        conn.execute("CREATE REL TABLE Knows(FROM Person TO Person)")
        conn.execute("CREATE (:Person {name: 'Alice'})")
        conn.execute("CREATE (:Person {name: 'Bob'})")
        conn.execute("MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) CREATE (a)-[:Knows]->(b)")
        conn.close()
        db.close()

        # Reopen and verify
        db2 = lbug.Database(db_path)
        conn2 = lbug.Connection(db2)
        result = conn2.execute("MATCH (a)-[:Knows]->(b) RETURN a.name, b.name")
        assert result.get_next() == ['Alice', 'Bob']
        conn2.close()
        db2.close()
