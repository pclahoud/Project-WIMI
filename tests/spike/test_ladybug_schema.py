"""
S0.3: LadybugDB Schema Modeling Test
Miniature WIMI subject hierarchy in graph with Cypher queries.
"""
import pytest
import real_ladybug as lbug


@pytest.fixture
def wimi_graph(tmp_path):
    """Create a LadybugDB with WIMI's graph schema and test data."""
    db_path = str(tmp_path / "wimi_schema.lbdb")
    db = lbug.Database(db_path)
    conn = lbug.Connection(db)

    # --- Node tables ---
    conn.execute("CREATE NODE TABLE ExamContext(sqlite_id INT64, name STRING, PRIMARY KEY(sqlite_id))")
    conn.execute("CREATE NODE TABLE Dimension(sqlite_id INT64, name STRING, PRIMARY KEY(sqlite_id))")
    conn.execute("CREATE NODE TABLE Subject(sqlite_id INT64, name STRING, level_type STRING, full_path STRING, PRIMARY KEY(sqlite_id))")
    conn.execute("CREATE NODE TABLE Entry(sqlite_id INT64, PRIMARY KEY(sqlite_id))")
    conn.execute("CREATE NODE TABLE Note(sqlite_id INT64, PRIMARY KEY(sqlite_id))")

    # --- Relationship tables ---
    conn.execute("CREATE REL TABLE HAS_DIMENSION(FROM ExamContext TO Dimension)")
    conn.execute("CREATE REL TABLE HAS_CHILD(FROM Subject TO Subject)")
    conn.execute("CREATE REL TABLE BELONGS_TO(FROM Subject TO Dimension)")
    conn.execute("CREATE REL TABLE TAGGED_TO(FROM Entry TO Subject, mapping_type STRING)")
    conn.execute("CREATE REL TABLE NOTE_LINKED_TO(FROM Note TO Subject)")
    conn.execute("CREATE REL TABLE ROOT_OF(FROM ExamContext TO Subject)")

    # --- Exam Context ---
    conn.execute("CREATE (:ExamContext {sqlite_id: 5, name: 'USMLE Step 3'})")

    # --- Dimensions ---
    conn.execute("CREATE (:Dimension {sqlite_id: 1, name: 'Organ System'})")
    conn.execute("CREATE (:Dimension {sqlite_id: 2, name: 'Discipline'})")
    conn.execute("CREATE (:Dimension {sqlite_id: 3, name: 'Clinical Task'})")

    # Link dimensions to exam
    conn.execute("MATCH (e:ExamContext {sqlite_id: 5}), (d:Dimension {sqlite_id: 1}) CREATE (e)-[:HAS_DIMENSION]->(d)")
    conn.execute("MATCH (e:ExamContext {sqlite_id: 5}), (d:Dimension {sqlite_id: 2}) CREATE (e)-[:HAS_DIMENSION]->(d)")
    conn.execute("MATCH (e:ExamContext {sqlite_id: 5}), (d:Dimension {sqlite_id: 3}) CREATE (e)-[:HAS_DIMENSION]->(d)")

    # --- Organ System subjects (Level 1 -> 2 -> 3) ---
    # Level 1: Systems
    conn.execute("CREATE (:Subject {sqlite_id: 101, name: 'Cardiology', level_type: 'System', full_path: 'Cardiology'})")
    conn.execute("CREATE (:Subject {sqlite_id: 102, name: 'Pulmonology', level_type: 'System', full_path: 'Pulmonology'})")
    conn.execute("CREATE (:Subject {sqlite_id: 103, name: 'Neurology', level_type: 'System', full_path: 'Neurology'})")

    # Level 2: Subsystems under Cardiology
    conn.execute("CREATE (:Subject {sqlite_id: 111, name: 'Heart Failure', level_type: 'Subsystem', full_path: 'Cardiology > Heart Failure'})")
    conn.execute("CREATE (:Subject {sqlite_id: 112, name: 'Arrhythmias', level_type: 'Subsystem', full_path: 'Cardiology > Arrhythmias'})")
    conn.execute("CREATE (:Subject {sqlite_id: 113, name: 'Valvular Disease', level_type: 'Subsystem', full_path: 'Cardiology > Valvular Disease'})")

    # Level 2: Subsystems under Pulmonology
    conn.execute("CREATE (:Subject {sqlite_id: 121, name: 'Asthma', level_type: 'Subsystem', full_path: 'Pulmonology > Asthma'})")
    conn.execute("CREATE (:Subject {sqlite_id: 122, name: 'COPD', level_type: 'Subsystem', full_path: 'Pulmonology > COPD'})")

    # Level 3: Topics under Heart Failure
    conn.execute("CREATE (:Subject {sqlite_id: 211, name: 'Systolic HF', level_type: 'Topic', full_path: 'Cardiology > Heart Failure > Systolic HF'})")
    conn.execute("CREATE (:Subject {sqlite_id: 212, name: 'Diastolic HF', level_type: 'Topic', full_path: 'Cardiology > Heart Failure > Diastolic HF'})")

    # Level 3: Topics under Arrhythmias
    conn.execute("CREATE (:Subject {sqlite_id: 221, name: 'Atrial Fibrillation', level_type: 'Topic', full_path: 'Cardiology > Arrhythmias > Atrial Fibrillation'})")

    # --- Discipline subjects ---
    conn.execute("CREATE (:Subject {sqlite_id: 301, name: 'Pharmacology', level_type: 'System', full_path: 'Pharmacology'})")
    conn.execute("CREATE (:Subject {sqlite_id: 302, name: 'Pathology', level_type: 'System', full_path: 'Pathology'})")
    conn.execute("CREATE (:Subject {sqlite_id: 311, name: 'Antiarrhythmics', level_type: 'Subsystem', full_path: 'Pharmacology > Antiarrhythmics'})")
    conn.execute("CREATE (:Subject {sqlite_id: 312, name: 'ACE Inhibitors', level_type: 'Subsystem', full_path: 'Pharmacology > ACE Inhibitors'})")

    # --- Clinical Task subjects ---
    conn.execute("CREATE (:Subject {sqlite_id: 401, name: 'Diagnosis', level_type: 'System', full_path: 'Diagnosis'})")
    conn.execute("CREATE (:Subject {sqlite_id: 402, name: 'Management', level_type: 'System', full_path: 'Management'})")
    conn.execute("CREATE (:Subject {sqlite_id: 411, name: 'ECG Interpretation', level_type: 'Subsystem', full_path: 'Diagnosis > ECG Interpretation'})")
    conn.execute("CREATE (:Subject {sqlite_id: 412, name: 'Drug Selection', level_type: 'Subsystem', full_path: 'Management > Drug Selection'})")

    # --- HAS_CHILD edges (hierarchy) ---
    # Cardiology children
    conn.execute("MATCH (p:Subject {sqlite_id: 101}), (c:Subject {sqlite_id: 111}) CREATE (p)-[:HAS_CHILD]->(c)")
    conn.execute("MATCH (p:Subject {sqlite_id: 101}), (c:Subject {sqlite_id: 112}) CREATE (p)-[:HAS_CHILD]->(c)")
    conn.execute("MATCH (p:Subject {sqlite_id: 101}), (c:Subject {sqlite_id: 113}) CREATE (p)-[:HAS_CHILD]->(c)")
    # Heart Failure children
    conn.execute("MATCH (p:Subject {sqlite_id: 111}), (c:Subject {sqlite_id: 211}) CREATE (p)-[:HAS_CHILD]->(c)")
    conn.execute("MATCH (p:Subject {sqlite_id: 111}), (c:Subject {sqlite_id: 212}) CREATE (p)-[:HAS_CHILD]->(c)")
    # Arrhythmias children
    conn.execute("MATCH (p:Subject {sqlite_id: 112}), (c:Subject {sqlite_id: 221}) CREATE (p)-[:HAS_CHILD]->(c)")
    # Pulmonology children
    conn.execute("MATCH (p:Subject {sqlite_id: 102}), (c:Subject {sqlite_id: 121}) CREATE (p)-[:HAS_CHILD]->(c)")
    conn.execute("MATCH (p:Subject {sqlite_id: 102}), (c:Subject {sqlite_id: 122}) CREATE (p)-[:HAS_CHILD]->(c)")
    # Pharmacology children
    conn.execute("MATCH (p:Subject {sqlite_id: 301}), (c:Subject {sqlite_id: 311}) CREATE (p)-[:HAS_CHILD]->(c)")
    conn.execute("MATCH (p:Subject {sqlite_id: 301}), (c:Subject {sqlite_id: 312}) CREATE (p)-[:HAS_CHILD]->(c)")
    # Diagnosis children
    conn.execute("MATCH (p:Subject {sqlite_id: 401}), (c:Subject {sqlite_id: 411}) CREATE (p)-[:HAS_CHILD]->(c)")
    # Management children
    conn.execute("MATCH (p:Subject {sqlite_id: 402}), (c:Subject {sqlite_id: 412}) CREATE (p)-[:HAS_CHILD]->(c)")

    # --- BELONGS_TO edges (subject -> dimension) ---
    for sid in [101, 102, 103, 111, 112, 113, 121, 122, 211, 212, 221]:
        conn.execute(f"MATCH (s:Subject {{sqlite_id: {sid}}}), (d:Dimension {{sqlite_id: 1}}) CREATE (s)-[:BELONGS_TO]->(d)")
    for sid in [301, 302, 311, 312]:
        conn.execute(f"MATCH (s:Subject {{sqlite_id: {sid}}}), (d:Dimension {{sqlite_id: 2}}) CREATE (s)-[:BELONGS_TO]->(d)")
    for sid in [401, 402, 411, 412]:
        conn.execute(f"MATCH (s:Subject {{sqlite_id: {sid}}}), (d:Dimension {{sqlite_id: 3}}) CREATE (s)-[:BELONGS_TO]->(d)")

    # --- ROOT_OF edges (exam -> root subjects) ---
    for sid in [101, 102, 103]:
        conn.execute(f"MATCH (e:ExamContext {{sqlite_id: 5}}), (s:Subject {{sqlite_id: {sid}}}) CREATE (e)-[:ROOT_OF]->(s)")
    for sid in [301, 302]:
        conn.execute(f"MATCH (e:ExamContext {{sqlite_id: 5}}), (s:Subject {{sqlite_id: {sid}}}) CREATE (e)-[:ROOT_OF]->(s)")
    for sid in [401, 402]:
        conn.execute(f"MATCH (e:ExamContext {{sqlite_id: 5}}), (s:Subject {{sqlite_id: {sid}}}) CREATE (e)-[:ROOT_OF]->(s)")

    # --- Entry stubs ---
    for eid in [1, 2, 3, 4, 5]:
        conn.execute(f"CREATE (:Entry {{sqlite_id: {eid}}})")

    # --- TAGGED_TO edges ---
    # Entry 1: tagged to Systolic HF (under Cardiology) + Pharmacology
    conn.execute("MATCH (e:Entry {sqlite_id: 1}), (s:Subject {sqlite_id: 211}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")
    conn.execute("MATCH (e:Entry {sqlite_id: 1}), (s:Subject {sqlite_id: 301}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")
    # Entry 2: tagged to Atrial Fibrillation (under Cardiology) + Antiarrhythmics (under Pharmacology)
    conn.execute("MATCH (e:Entry {sqlite_id: 2}), (s:Subject {sqlite_id: 221}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")
    conn.execute("MATCH (e:Entry {sqlite_id: 2}), (s:Subject {sqlite_id: 311}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")
    # Entry 3: tagged to Asthma (under Pulmonology)
    conn.execute("MATCH (e:Entry {sqlite_id: 3}), (s:Subject {sqlite_id: 121}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")
    # Entry 4: tagged to Diastolic HF (under Cardiology) + ACE Inhibitors (under Pharmacology)
    conn.execute("MATCH (e:Entry {sqlite_id: 4}), (s:Subject {sqlite_id: 212}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")
    conn.execute("MATCH (e:Entry {sqlite_id: 4}), (s:Subject {sqlite_id: 312}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")
    # Entry 5: tagged to Valvular Disease (under Cardiology) + Diagnosis
    conn.execute("MATCH (e:Entry {sqlite_id: 5}), (s:Subject {sqlite_id: 113}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")
    conn.execute("MATCH (e:Entry {sqlite_id: 5}), (s:Subject {sqlite_id: 401}) CREATE (e)-[:TAGGED_TO {mapping_type: 'primary'}]->(s)")

    # --- Note stubs ---
    conn.execute("CREATE (:Note {sqlite_id: 1})")
    conn.execute("CREATE (:Note {sqlite_id: 2})")
    conn.execute("CREATE (:Note {sqlite_id: 3})")

    # --- NOTE_LINKED_TO edges ---
    conn.execute("MATCH (n:Note {sqlite_id: 1}), (s:Subject {sqlite_id: 211}) CREATE (n)-[:NOTE_LINKED_TO]->(s)")
    conn.execute("MATCH (n:Note {sqlite_id: 2}), (s:Subject {sqlite_id: 112}) CREATE (n)-[:NOTE_LINKED_TO]->(s)")
    conn.execute("MATCH (n:Note {sqlite_id: 3}), (s:Subject {sqlite_id: 301}) CREATE (n)-[:NOTE_LINKED_TO]->(s)")

    yield db, conn

    conn.close()
    db.close()


def _collect(result):
    """Collect all rows from a query result."""
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    return rows


class TestSchemaCreation:
    """Verify the schema and data were created correctly."""

    def test_node_counts(self, wimi_graph):
        _, conn = wimi_graph
        assert _collect(conn.execute("MATCH (e:ExamContext) RETURN count(e)"))[0] == [1]
        assert _collect(conn.execute("MATCH (d:Dimension) RETURN count(d)"))[0] == [3]
        assert _collect(conn.execute("MATCH (s:Subject) RETURN count(s)"))[0] == [19]
        assert _collect(conn.execute("MATCH (e:Entry) RETURN count(e)"))[0] == [5]
        assert _collect(conn.execute("MATCH (n:Note) RETURN count(n)"))[0] == [3]

    def test_hierarchy_depth(self, wimi_graph):
        """Cardiology has 3 levels: Cardiology -> Heart Failure -> Systolic HF."""
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s:Subject {name: 'Cardiology'})-[:HAS_CHILD]->(l2)-[:HAS_CHILD]->(l3) "
            "RETURN l3.name ORDER BY l3.name"
        )
        topics = [r[0] for r in _collect(result)]
        assert 'Systolic HF' in topics
        assert 'Diastolic HF' in topics


class TestDescendantQuery:
    """Query: Get all descendants of a subject."""

    def test_cardiology_descendants(self, wimi_graph):
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s:Subject {name: 'Cardiology'})-[:HAS_CHILD*0..20]->(child) "
            "RETURN child.name ORDER BY child.name"
        )
        names = [r[0] for r in _collect(result)]
        # Cardiology itself + 3 subsystems + 3 topics = 7
        assert len(names) == 7
        assert 'Cardiology' in names  # *0..20 includes self
        assert 'Heart Failure' in names
        assert 'Arrhythmias' in names
        assert 'Valvular Disease' in names
        assert 'Systolic HF' in names
        assert 'Diastolic HF' in names
        assert 'Atrial Fibrillation' in names

    def test_leaf_node_has_no_descendants(self, wimi_graph):
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s:Subject {name: 'Systolic HF'})-[:HAS_CHILD*0..20]->(child) "
            "RETURN child.name"
        )
        names = [r[0] for r in _collect(result)]
        assert names == ['Systolic HF']  # Only self


class TestEntriesBySubjectTree:
    """Query: Get entries tagged to a subject or any descendant."""

    def test_entries_under_cardiology(self, wimi_graph):
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s:Subject {name: 'Cardiology'})-[:HAS_CHILD*0..20]->(child)"
            "<-[:TAGGED_TO]-(e:Entry) "
            "RETURN DISTINCT e.sqlite_id ORDER BY e.sqlite_id"
        )
        entry_ids = [r[0] for r in _collect(result)]
        # Entry 1 (Systolic HF), 2 (AFib), 4 (Diastolic HF), 5 (Valvular Disease)
        assert entry_ids == [1, 2, 4, 5]

    def test_entries_under_pulmonology(self, wimi_graph):
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s:Subject {name: 'Pulmonology'})-[:HAS_CHILD*0..20]->(child)"
            "<-[:TAGGED_TO]-(e:Entry) "
            "RETURN DISTINCT e.sqlite_id"
        )
        entry_ids = [r[0] for r in _collect(result)]
        assert entry_ids == [3]  # Only Entry 3 (Asthma)

    def test_entries_under_heart_failure(self, wimi_graph):
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s:Subject {name: 'Heart Failure'})-[:HAS_CHILD*0..20]->(child)"
            "<-[:TAGGED_TO]-(e:Entry) "
            "RETURN DISTINCT e.sqlite_id ORDER BY e.sqlite_id"
        )
        entry_ids = [r[0] for r in _collect(result)]
        assert entry_ids == [1, 4]  # Entry 1 (Systolic HF), Entry 4 (Diastolic HF)


class TestSubjectsInDimension:
    """Query: Get subjects in a dimension."""

    def test_organ_system_subjects(self, wimi_graph):
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (d:Dimension {name: 'Organ System'})<-[:BELONGS_TO]-(s:Subject) "
            "RETURN s.name ORDER BY s.name"
        )
        names = [r[0] for r in _collect(result)]
        assert len(names) == 11  # All organ system subjects
        assert 'Cardiology' in names
        assert 'Pulmonology' in names
        assert 'Systolic HF' in names

    def test_discipline_subjects(self, wimi_graph):
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (d:Dimension {name: 'Discipline'})<-[:BELONGS_TO]-(s:Subject) "
            "RETURN s.name ORDER BY s.name"
        )
        names = [r[0] for r in _collect(result)]
        assert len(names) == 4
        assert 'Pharmacology' in names
        assert 'Antiarrhythmics' in names


class TestCrossDimensionIntersection:
    """Query: Entries tagged to subjects in BOTH dimensions."""

    def test_cardiology_and_pharmacology(self, wimi_graph):
        """Entries tagged to Cardiology (or child) AND Pharmacology (or child)."""
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s1:Subject {name: 'Cardiology'})-[:HAS_CHILD*0..20]->(c1)"
            "<-[:TAGGED_TO]-(e:Entry)-[:TAGGED_TO]->(c2)"
            "<-[:HAS_CHILD*0..20]-(s2:Subject {name: 'Pharmacology'}) "
            "RETURN DISTINCT e.sqlite_id ORDER BY e.sqlite_id"
        )
        entry_ids = [r[0] for r in _collect(result)]
        # Entry 1: Systolic HF (Cardiology child) + Pharmacology
        # Entry 2: AFib (Cardiology child) + Antiarrhythmics (Pharmacology child)
        # Entry 4: Diastolic HF (Cardiology child) + ACE Inhibitors (Pharmacology child)
        assert entry_ids == [1, 2, 4]

    def test_cardiology_and_diagnosis(self, wimi_graph):
        """Entries tagged to Cardiology (or child) AND Diagnosis (or child)."""
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s1:Subject {name: 'Cardiology'})-[:HAS_CHILD*0..20]->(c1)"
            "<-[:TAGGED_TO]-(e:Entry)-[:TAGGED_TO]->(c2)"
            "<-[:HAS_CHILD*0..20]-(s2:Subject {name: 'Diagnosis'}) "
            "RETURN DISTINCT e.sqlite_id ORDER BY e.sqlite_id"
        )
        entry_ids = [r[0] for r in _collect(result)]
        # Entry 5: Valvular Disease (Cardiology child) + Diagnosis
        assert entry_ids == [5]

    def test_no_intersection(self, wimi_graph):
        """Pulmonology AND Diagnosis should have no entries."""
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s1:Subject {name: 'Pulmonology'})-[:HAS_CHILD*0..20]->(c1)"
            "<-[:TAGGED_TO]-(e:Entry)-[:TAGGED_TO]->(c2)"
            "<-[:HAS_CHILD*0..20]-(s2:Subject {name: 'Diagnosis'}) "
            "RETURN DISTINCT e.sqlite_id"
        )
        entry_ids = [r[0] for r in _collect(result)]
        assert entry_ids == []


class TestNoteLinks:
    """Verify note-to-subject links work."""

    def test_notes_linked_to_subject_tree(self, wimi_graph):
        """Notes linked to Cardiology descendants."""
        _, conn = wimi_graph
        result = conn.execute(
            "MATCH (s:Subject {name: 'Cardiology'})-[:HAS_CHILD*0..20]->(child)"
            "<-[:NOTE_LINKED_TO]-(n:Note) "
            "RETURN DISTINCT n.sqlite_id ORDER BY n.sqlite_id"
        )
        note_ids = [r[0] for r in _collect(result)]
        # Note 1 -> Systolic HF, Note 2 -> Arrhythmias
        assert note_ids == [1, 2]
