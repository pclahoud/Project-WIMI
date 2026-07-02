"""
S0.5: Minimal LadybugDB script for PyInstaller bundling test.
"""
import os
import sys
import tempfile
import real_ladybug as lbug


def main():
    tmp = os.path.join(tempfile.mkdtemp(prefix='lbug_pyinst_'), 'test.lbdb')
    print(f"Database path: {tmp}")

    db = lbug.Database(tmp)
    conn = lbug.Connection(db)

    conn.execute("CREATE NODE TABLE Person(name STRING, age INT64, PRIMARY KEY(name))")
    conn.execute("CREATE (:Person {name: 'Alice', age: 30})")
    conn.execute("CREATE (:Person {name: 'Bob', age: 25})")

    result = conn.execute("MATCH (p:Person) RETURN p.name, p.age ORDER BY p.name")
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert rows == [['Alice', 30], ['Bob', 25]], f"Unexpected: {rows}"

    conn.close()
    db.close()

    # Verify persistence
    db2 = lbug.Database(tmp)
    conn2 = lbug.Connection(db2)
    result2 = conn2.execute("MATCH (p:Person) RETURN count(p)")
    count = result2.get_next()[0]
    assert count == 2, f"Expected 2, got {count}"
    conn2.close()
    db2.close()

    print("PYINSTALLER BUNDLING TEST PASSED")


if __name__ == '__main__':
    main()
