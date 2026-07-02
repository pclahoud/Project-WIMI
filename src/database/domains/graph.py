"""WIMI Graph Database — LadybugDB connection management and operations."""
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger('wimi.graph')
shadow_logger = logging.getLogger('wimi.graph.shadow')

GRAPH_SCHEMA_VERSION = "1.0.0"


class GraphMixin:
    """Mixin for LadybugDB graph database operations."""

    def _init_graph(self):
        """Initialize graph database connection. Called after SQLite init."""
        self._graph_db = None
        self._graph_conn = None
        self._graph_path = None

        try:
            import real_ladybug as lbug
            self._lbug = lbug
        except ImportError:
            logger.info("real_ladybug not installed, graph features disabled")
            return

        # Derive graph path from SQLite path
        self._graph_path = Path(str(self.db_path)).with_suffix('.lbdb')

        try:
            self._open_graph()
            self._ensure_graph_schema()
            if self._is_graph_stale():
                self._reconcile_graph()
        except Exception as e:
            logger.warning(f"Failed to open graph database: {e}")
            self._graph_db = None
            self._graph_conn = None

    def _open_graph(self):
        """Open or create the graph database file."""
        if not self._graph_path or not hasattr(self, '_lbug'):
            return

        self._graph_db = self._lbug.Database(str(self._graph_path))
        self._graph_conn = self._lbug.Connection(self._graph_db)
        logger.debug(f"Graph database opened: {self._graph_path}")

    def _close_graph(self):
        """Close graph database connection and database."""
        if self._graph_conn:
            try:
                self._graph_conn.close()
            except Exception as e:
                logger.warning(f"Error closing graph connection: {e}")
            self._graph_conn = None

        if self._graph_db:
            try:
                self._graph_db.close()
            except Exception as e:
                logger.warning(f"Error closing graph database: {e}")
            self._graph_db = None

    @property
    def _graph_available(self) -> bool:
        """Whether graph database is available for queries."""
        return self._graph_conn is not None

    @property
    def _graph_read_ready(self) -> bool:
        """Whether graph database is available AND populated with data.

        Used by P2.5 graph-primary read methods to avoid returning empty
        results from an unpopulated graph.  Caches the result for the
        lifetime of the connection to avoid repeated meta-node lookups.
        """
        if not self._graph_available:
            return False
        # Cache the check so we only query GraphMeta once per connection
        if not hasattr(self, '_graph_read_ready_cache'):
            version = self._get_graph_meta_version()
            self._graph_read_ready_cache = version == GRAPH_SCHEMA_VERSION
        return self._graph_read_ready_cache

    def _graph_execute(self, query: str, parameters: dict = None):
        """Execute a Cypher query on the graph database.

        Returns the query result, or None if graph is unavailable.
        """
        if not self._graph_available:
            return None
        try:
            if parameters:
                return self._graph_conn.execute(query, parameters)
            return self._graph_conn.execute(query)
        except Exception as e:
            logger.warning(f"Graph query failed: {e}\nQuery: {query}")
            return None

    def _graph_collect(self, result) -> list:
        """Collect all rows from a graph query result."""
        if result is None:
            return []
        rows = []
        while result.has_next():
            rows.append(result.get_next())
        return rows

    # ------------------------------------------------------------------
    # Shadow comparison infrastructure (P1.5)
    # ------------------------------------------------------------------

    @property
    def _shadow_reads_enabled(self) -> bool:
        """Whether shadow graph reads are enabled."""
        if not self._graph_available:
            return False
        # Check preference flag, default to True in dev mode
        try:
            prefs = self.get_preferences()
            if hasattr(prefs, 'graph_shadow_reads_enabled'):
                return bool(getattr(prefs, 'graph_shadow_reads_enabled', True))
            return True
        except Exception:
            return True

    @staticmethod
    def _normalize_for_comparison(result) -> set:
        """Normalize a query result into a set of comparable values.

        Handles lists of dicts (SQLite rows), lists of lists/tuples
        (graph rows), and scalar values.  For dicts the 'id' key is
        extracted when present; otherwise the full tuple of values is
        used.  For lists/tuples the first element is treated as the
        identifier.

        Returns:
            A frozenset of hashable values suitable for set comparison.
        """
        if result is None:
            return set()
        if not isinstance(result, (list, tuple)):
            return {result}

        normalized = set()
        for item in result:
            if isinstance(item, dict):
                # Prefer 'id', fall back to full value tuple
                if 'id' in item:
                    normalized.add(item['id'])
                else:
                    normalized.add(tuple(sorted(item.items())))
            elif isinstance(item, (list, tuple)):
                # Graph rows — use first element as identifier
                if len(item) == 1:
                    normalized.add(item[0])
                else:
                    normalized.add(tuple(item))
            else:
                normalized.add(item)
        return normalized

    def _shadow_compare(self, method_name: str, params: dict,
                        sqlite_result, graph_result) -> bool:
        """Compare SQLite and graph results, logging mismatches.

        Args:
            method_name: Name of the method being compared
            params: Parameters passed to the method (for logging)
            sqlite_result: Result from SQLite query
            graph_result: Result from graph query

        Returns:
            True if results match, False otherwise
        """
        sqlite_set = self._normalize_for_comparison(sqlite_result)
        graph_set = self._normalize_for_comparison(graph_result)

        if sqlite_set == graph_set:
            shadow_logger.debug(
                f"Shadow read MATCH: {method_name}({params}) "
                f"— {len(sqlite_set)} results"
            )
            return True

        sqlite_only = sqlite_set - graph_set
        graph_only = graph_set - sqlite_set
        shadow_logger.warning(
            f"Shadow read MISMATCH: {method_name}({params}) "
            f"— SQLite: {len(sqlite_set)}, Graph: {len(graph_set)}, "
            f"SQLite-only: {sqlite_only}, Graph-only: {graph_only}"
        )
        return False

    def _with_shadow_read(self, method_name: str, params: dict,
                          sqlite_fn: Callable, graph_fn: Callable):
        """Execute sqlite_fn, optionally compare with graph_fn result.

        Always returns the sqlite_fn result.  Graph failures are caught
        and logged — they never affect the return value.
        """
        sqlite_result = sqlite_fn()

        if not self._shadow_reads_enabled:
            return sqlite_result

        try:
            graph_result = graph_fn()
            self._shadow_compare(method_name, params,
                                 sqlite_result, graph_result)
        except Exception as e:
            shadow_logger.warning(
                f"Shadow read failed for {method_name}: {e}"
            )

        return sqlite_result

    # ------------------------------------------------------------------
    # Graph schema initialization (P1.2)
    # ------------------------------------------------------------------

    def _ensure_graph_schema(self):
        """Ensure graph schema exists with all node and relationship tables.

        Follows the _ensure_* pattern. Called from _init_graph() after
        connection opens. Idempotent — safe to call on every startup.
        """
        if not self._graph_available:
            return

        try:
            # Check if schema already exists by looking for GraphMeta node
            existing_version = self._get_graph_meta_version()

            if existing_version == GRAPH_SCHEMA_VERSION:
                # Schema is current, nothing to do
                logger.debug("Graph schema up to date (v%s)", GRAPH_SCHEMA_VERSION)
                return

            if existing_version is not None:
                # Future: handle incremental migrations here
                logger.info(
                    "Graph schema version %s found, current is %s",
                    existing_version, GRAPH_SCHEMA_VERSION,
                )

            # --- Create node tables ---
            self._create_graph_node_tables()

            # --- Create relationship tables ---
            self._create_graph_rel_tables()

            # --- Write GraphMeta node ---
            self._write_graph_meta()

            # --- Store version in SQLite preferences ---
            self._ensure_graph_preferences()
            self._set_graph_schema_version_pref(GRAPH_SCHEMA_VERSION)

            # --- Populate graph from SQLite on first run ---
            if existing_version is None:
                self._populate_graph_from_sqlite()

            logger.info("Graph schema v%s initialised", GRAPH_SCHEMA_VERSION)

        except Exception as e:
            logger.error("Graph schema initialisation failed: %s", e, exc_info=True)
            # Tear down: close connections, delete partial .lbdb, clear pref
            self._close_graph()
            if self._graph_path:
                lbdb = Path(self._graph_path)
                # LadybugDB stores data as a directory
                if lbdb.exists():
                    try:
                        if lbdb.is_dir():
                            shutil.rmtree(str(lbdb), ignore_errors=True)
                        else:
                            lbdb.unlink(missing_ok=True)
                    except Exception:
                        pass
            self._clear_graph_schema_version_pref()
            # App continues SQLite-only

    def _get_graph_meta_version(self) -> Optional[str]:
        """Return the schema_version from :GraphMeta, or None if missing."""
        try:
            result = self._graph_conn.execute(
                "MATCH (m:GraphMeta) RETURN m.schema_version LIMIT 1"
            )
            rows = self._graph_collect(result)
            if rows:
                return rows[0][0]
        except RuntimeError:
            # Table doesn't exist yet — that's fine
            pass
        return None

    def _create_graph_node_tables(self):
        """Create all node tables in the graph database."""
        node_defs = [
            "CREATE NODE TABLE IF NOT EXISTS ExamContext(sqlite_id INT64, name STRING, PRIMARY KEY(sqlite_id))",
            "CREATE NODE TABLE IF NOT EXISTS Dimension(sqlite_id INT64, name STRING, PRIMARY KEY(sqlite_id))",
            "CREATE NODE TABLE IF NOT EXISTS Subject(sqlite_id INT64, name STRING, level_type STRING, full_path STRING, PRIMARY KEY(sqlite_id))",
            "CREATE NODE TABLE IF NOT EXISTS Entry(sqlite_id INT64, PRIMARY KEY(sqlite_id))",
            "CREATE NODE TABLE IF NOT EXISTS Note(sqlite_id INT64, PRIMARY KEY(sqlite_id))",
            "CREATE NODE TABLE IF NOT EXISTS GraphMeta(schema_version STRING, migrated_at STRING, app_version STRING, PRIMARY KEY(schema_version))",
        ]
        for stmt in node_defs:
            try:
                self._graph_conn.execute(stmt)
            except RuntimeError as e:
                if "already exists" in str(e).lower():
                    logger.debug("Node table already exists: %s", e)
                else:
                    raise

    def _create_graph_rel_tables(self):
        """Create all relationship tables in the graph database."""
        rel_defs = [
            "CREATE REL TABLE IF NOT EXISTS HAS_DIMENSION(FROM ExamContext TO Dimension)",
            "CREATE REL TABLE IF NOT EXISTS HAS_CHILD(FROM Subject TO Subject)",
            "CREATE REL TABLE IF NOT EXISTS BELONGS_TO(FROM Subject TO Dimension)",
            "CREATE REL TABLE IF NOT EXISTS TAGGED_TO(FROM Entry TO Subject, mapping_type STRING)",
            "CREATE REL TABLE IF NOT EXISTS NOTE_LINKED_TO(FROM Note TO Subject)",
            "CREATE REL TABLE IF NOT EXISTS ROOT_OF(FROM ExamContext TO Subject)",
        ]
        for stmt in rel_defs:
            try:
                self._graph_conn.execute(stmt)
            except RuntimeError as e:
                if "already exists" in str(e).lower():
                    logger.debug("Rel table already exists: %s", e)
                else:
                    raise

    def _write_graph_meta(self):
        """Create or update the :GraphMeta node with the current version."""
        now = datetime.utcnow().isoformat() + "Z"
        # MERGE ensures idempotency
        self._graph_conn.execute(
            "MERGE (m:GraphMeta {schema_version: $ver}) "
            "SET m.migrated_at = $ts, m.app_version = $app",
            {
                "ver": GRAPH_SCHEMA_VERSION,
                "ts": now,
                "app": "WIMI",
            },
        )

    # ------------------------------------------------------------------
    # SQLite preference helpers for graph schema version
    # ------------------------------------------------------------------

    def _ensure_graph_preferences(self):
        """Add graph_schema_version and graph_stale columns to user_preferences if missing."""
        try:
            columns = self.fetchall("PRAGMA table_info(user_preferences)")
            column_names = {col['name'] for col in columns}
            if 'graph_schema_version' not in column_names:
                self.execute(
                    "ALTER TABLE user_preferences "
                    "ADD COLUMN graph_schema_version VARCHAR(20) DEFAULT NULL"
                )
                self.conn.commit()
                logger.debug("Added graph_schema_version column to user_preferences")
            if 'graph_stale' not in column_names:
                self.execute(
                    "ALTER TABLE user_preferences "
                    "ADD COLUMN graph_stale INTEGER DEFAULT 0"
                )
                self.conn.commit()
                logger.debug("Added graph_stale column to user_preferences")
        except Exception as e:
            logger.warning("Could not add graph preference columns: %s", e)

    def _set_graph_schema_version_pref(self, version: str):
        """Write graph_schema_version into the current user's preferences row."""
        try:
            self.execute(
                "UPDATE user_preferences SET graph_schema_version = ? WHERE user_id = ?",
                (version, self.user_id),
            )
            self.conn.commit()
        except Exception as e:
            logger.warning("Could not set graph_schema_version preference: %s", e)

    def _clear_graph_schema_version_pref(self):
        """Clear graph_schema_version preference (used on schema init failure)."""
        try:
            self.execute(
                "UPDATE user_preferences SET graph_schema_version = NULL WHERE user_id = ?",
                (self.user_id,),
            )
            self.conn.commit()
        except Exception:
            pass  # Best-effort cleanup

    # ------------------------------------------------------------------
    # ETL: Populate graph from SQLite (P1.3)
    # ------------------------------------------------------------------

    def _populate_graph_from_sqlite(self):
        """Populate the graph database from existing SQLite data.

        Called once on first run (when graph schema is freshly created).
        Reads all structural/relationship data from SQLite and creates
        corresponding nodes and edges in LadybugDB.

        Order matters due to dependencies:
        1. Dimensions  (no deps)
        2. ExamContexts + HAS_DIMENSION edges
        3. Subjects + HAS_CHILD, BELONGS_TO, ROOT_OF edges
        4. Entries (stubs)
        5. Entry-Subject mappings (TAGGED_TO edges)
        6. Notes + NOTE_LINKED_TO edges
        """
        logger.info("ETL: Starting graph population from SQLite")

        try:
            self._etl_dimensions()
            self._etl_exam_contexts()
            self._etl_subjects()
            self._etl_entries()
            self._etl_entry_subject_mappings()
            self._etl_notes()
            logger.info("ETL: Graph population complete")

        except Exception as e:
            logger.error("ETL: Graph population failed: %s", e, exc_info=True)
            # Tear down: close graph, delete .lbdb file, clear pref
            self._close_graph()
            if self._graph_path:
                lbdb = Path(self._graph_path)
                if lbdb.exists():
                    try:
                        if lbdb.is_dir():
                            shutil.rmtree(str(lbdb), ignore_errors=True)
                        else:
                            lbdb.unlink(missing_ok=True)
                    except Exception:
                        pass
            self._clear_graph_schema_version_pref()
            self._graph_db = None
            self._graph_conn = None

    def _etl_dimensions(self):
        """ETL Step 1: Create :Dimension nodes from exam_dimensions."""
        try:
            rows = self.fetchall("SELECT id, name FROM exam_dimensions")
        except Exception:
            # Table may not exist if Phase 7 schema was never applied
            logger.debug("ETL: exam_dimensions table not found, skipping")
            return

        count = 0
        for row in rows:
            self._graph_conn.execute(
                "MERGE (d:Dimension {sqlite_id: $id}) SET d.name = $name",
                {"id": row['id'], "name": row['name']},
            )
            count += 1
        logger.info("ETL: Created %d Dimension nodes", count)

    def _etl_exam_contexts(self):
        """ETL Step 2: Create :ExamContext nodes and :HAS_DIMENSION edges."""
        try:
            rows = self.fetchall(
                "SELECT id, exam_name FROM exam_contexts WHERE is_active = 1"
            )
        except Exception:
            logger.debug("ETL: exam_contexts table not found, skipping")
            return

        count = 0
        for row in rows:
            self._graph_conn.execute(
                "MERGE (e:ExamContext {sqlite_id: $id}) SET e.name = $name",
                {"id": row['id'], "name": row['exam_name']},
            )
            count += 1
        logger.info("ETL: Created %d ExamContext nodes", count)

        # Link dimensions to exam contexts via HAS_DIMENSION
        try:
            dim_rows = self.fetchall(
                "SELECT id AS dim_id, exam_id FROM exam_dimensions"
            )
        except Exception:
            return

        edge_count = 0
        for dr in dim_rows:
            result = self._graph_conn.execute(
                "MATCH (e:ExamContext {sqlite_id: $exam_id}), "
                "(d:Dimension {sqlite_id: $dim_id}) "
                "MERGE (e)-[:HAS_DIMENSION]->(d)",
                {"exam_id": dr['exam_id'], "dim_id": dr['dim_id']},
            )
            edge_count += 1
        logger.info("ETL: Created %d HAS_DIMENSION edges", edge_count)

    def _etl_subjects(self):
        """ETL Step 3: Create :Subject nodes with hierarchy edges.

        Creates :Subject nodes, then for each subject:
        - :HAS_CHILD edge from parent (if parent_id is set)
        - :BELONGS_TO edge to dimension (if dimension_id is set)
        - :ROOT_OF edge from ExamContext (if root node, i.e. parent_id is NULL)
        """
        # Build a lookup of exam_name -> exam_context id
        exam_name_to_id = {}
        try:
            exams = self.fetchall("SELECT id, exam_name FROM exam_contexts")
            for ex in exams:
                exam_name_to_id[ex['exam_name']] = ex['id']
        except Exception:
            pass

        # Check which columns exist on subject_nodes
        try:
            col_info = self.fetchall("PRAGMA table_info(subject_nodes)")
        except Exception:
            logger.debug("ETL: subject_nodes table not found, skipping")
            return
        col_names = {c['name'] for c in col_info}
        has_dimension_id = 'dimension_id' in col_names

        # Build the SELECT — full_path is computed, not stored
        select_cols = "id, name, level_type, parent_id, exam_context"
        if has_dimension_id:
            select_cols += ", dimension_id"

        rows = self.fetchall(
            f"SELECT {select_cols} FROM subject_nodes "
            "WHERE status = 'active' "
            "ORDER BY CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END, id"
        )

        # Pre-build full_path for all subjects using parent chain
        # First pass: index by id
        nodes_by_id = {}
        for row in rows:
            nodes_by_id[row['id']] = row

        def build_path(node_id):
            parts = []
            current = node_id
            seen = set()
            while current and current in nodes_by_id and current not in seen:
                seen.add(current)
                parts.insert(0, nodes_by_id[current]['name'])
                current = nodes_by_id[current]['parent_id']
            return ' > '.join(parts)

        # Create nodes
        node_count = 0
        for row in rows:
            full_path = build_path(row['id'])
            self._graph_conn.execute(
                "MERGE (s:Subject {sqlite_id: $id}) "
                "SET s.name = $name, s.level_type = $level_type, "
                "s.full_path = $full_path",
                {
                    "id": row['id'],
                    "name": row['name'],
                    "level_type": row['level_type'],
                    "full_path": full_path,
                },
            )
            node_count += 1
        logger.info("ETL: Created %d Subject nodes", node_count)

        # Create edges
        child_count = 0
        belongs_count = 0
        root_count = 0

        for row in rows:
            parent_id = row['parent_id']
            dim_id = row['dimension_id'] if has_dimension_id else None
            exam_ctx_name = row['exam_context']

            if parent_id is not None:
                # HAS_CHILD: parent -> this node
                self._graph_conn.execute(
                    "MATCH (p:Subject {sqlite_id: $parent_id}), "
                    "(c:Subject {sqlite_id: $child_id}) "
                    "MERGE (p)-[:HAS_CHILD]->(c)",
                    {"parent_id": parent_id, "child_id": row['id']},
                )
                child_count += 1
            else:
                # Root node — link from ExamContext via ROOT_OF
                exam_id = exam_name_to_id.get(exam_ctx_name)
                if exam_id is not None:
                    self._graph_conn.execute(
                        "MATCH (e:ExamContext {sqlite_id: $exam_id}), "
                        "(s:Subject {sqlite_id: $subj_id}) "
                        "MERGE (e)-[:ROOT_OF]->(s)",
                        {"exam_id": exam_id, "subj_id": row['id']},
                    )
                    root_count += 1

            if dim_id is not None:
                # BELONGS_TO: subject -> dimension
                self._graph_conn.execute(
                    "MATCH (s:Subject {sqlite_id: $subj_id}), "
                    "(d:Dimension {sqlite_id: $dim_id}) "
                    "MERGE (s)-[:BELONGS_TO]->(d)",
                    {"subj_id": row['id'], "dim_id": dim_id},
                )
                belongs_count += 1

        logger.info(
            "ETL: Created %d HAS_CHILD, %d BELONGS_TO, %d ROOT_OF edges",
            child_count, belongs_count, root_count,
        )

    def _etl_entries(self):
        """ETL Step 4: Create :Entry stub nodes from question_entries."""
        try:
            rows = self.fetchall("SELECT id FROM question_entries")
        except Exception:
            logger.debug("ETL: question_entries table not found, skipping")
            return

        count = 0
        for row in rows:
            self._graph_conn.execute(
                "MERGE (:Entry {sqlite_id: $id})",
                {"id": row['id']},
            )
            count += 1
        logger.info("ETL: Created %d Entry nodes", count)

    def _etl_entry_subject_mappings(self):
        """ETL Step 5: Create :TAGGED_TO edges from entry_subject_mappings."""
        try:
            rows = self.fetchall(
                "SELECT question_entry_id, subject_node_id, mapping_type "
                "FROM entry_subject_mappings"
            )
        except Exception:
            logger.debug("ETL: entry_subject_mappings table not found, skipping")
            return

        count = 0
        for row in rows:
            self._graph_conn.execute(
                "MATCH (e:Entry {sqlite_id: $entry_id}), "
                "(s:Subject {sqlite_id: $subject_id}) "
                "MERGE (e)-[:TAGGED_TO {mapping_type: $mtype}]->(s)",
                {
                    "entry_id": row['question_entry_id'],
                    "subject_id": row['subject_node_id'],
                    "mtype": row['mapping_type'] or 'primary',
                },
            )
            count += 1
        logger.info("ETL: Created %d TAGGED_TO edges", count)

    def _etl_notes(self):
        """ETL Step 6: Create :Note stubs and :NOTE_LINKED_TO edges."""
        try:
            rows = self.fetchall(
                "SELECT id, linked_subject_ids FROM entry_notes"
            )
        except Exception:
            logger.debug("ETL: entry_notes table not found, skipping")
            return

        node_count = 0
        edge_count = 0
        for row in rows:
            self._graph_conn.execute(
                "MERGE (:Note {sqlite_id: $id})",
                {"id": row['id']},
            )
            node_count += 1

            # Parse linked_subject_ids JSON array
            linked_ids_raw = row['linked_subject_ids']
            if linked_ids_raw:
                try:
                    linked_ids = json.loads(linked_ids_raw)
                    if isinstance(linked_ids, list):
                        for subj_id in linked_ids:
                            self._graph_conn.execute(
                                "MATCH (n:Note {sqlite_id: $note_id}), "
                                "(s:Subject {sqlite_id: $subj_id}) "
                                "MERGE (n)-[:NOTE_LINKED_TO]->(s)",
                                {"note_id": row['id'], "subj_id": int(subj_id)},
                            )
                            edge_count += 1
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.debug(
                        "ETL: Could not parse linked_subject_ids for note %d",
                        row['id'],
                    )

        logger.info(
            "ETL: Created %d Note nodes, %d NOTE_LINKED_TO edges",
            node_count, edge_count,
        )

    # ------------------------------------------------------------------
    # Shadow read graph query methods (P1.4)
    # ------------------------------------------------------------------

    def _graph_get_descendant_ids(self, parent_id: int) -> list:
        """Get all descendant IDs of a subject node from the graph.

        Equivalent to ``_get_descendant_node_ids()`` in SQLite.

        Returns:
            List of integer subject IDs (children, grandchildren, etc.)
        """
        result = self._graph_execute(
            "MATCH (s:Subject {sqlite_id: $id})-[:HAS_CHILD*1..20]->(child:Subject) "
            "RETURN child.sqlite_id",
            {"id": parent_id},
        )
        rows = self._graph_collect(result)
        return [row[0] for row in rows]

    def _graph_get_subject_node(self, node_id: int) -> dict:
        """Get subject node properties from the graph.

        Equivalent to ``get_subject_node()`` in SQLite.

        Returns:
            Dict with sqlite_id, name, level_type, full_path or empty dict.
        """
        result = self._graph_execute(
            "MATCH (s:Subject {sqlite_id: $id}) "
            "RETURN s.sqlite_id, s.name, s.level_type, s.full_path",
            {"id": node_id},
        )
        rows = self._graph_collect(result)
        if not rows:
            return {}
        row = rows[0]
        return {
            "id": row[0],
            "name": row[1],
            "level_type": row[2],
            "full_path": row[3],
        }

    def _graph_build_subject_path(self, node_id: int) -> str:
        """Build full path string for a subject node from the graph.

        Walks up the hierarchy from the target node to the root using
        the HAS_CHILD relationship.  Equivalent to ``_build_subject_path()``.

        Returns:
            Path string like "System > Subsystem > Topic".
        """
        # LadybugDB doesn't support list comprehension over nodes(path),
        # so we UNWIND to get one row per node in path order.
        result = self._graph_execute(
            "MATCH path = (root:Subject)-[:HAS_CHILD*0..20]->(target:Subject {sqlite_id: $id}) "
            "WHERE NOT ()-[:HAS_CHILD]->(root) "
            "UNWIND nodes(path) AS node "
            "RETURN node.name",
            {"id": node_id},
        )
        rows = self._graph_collect(result)
        if not rows:
            # Fallback: the node itself may be a root (no incoming HAS_CHILD)
            result2 = self._graph_execute(
                "MATCH (s:Subject {sqlite_id: $id}) RETURN s.name",
                {"id": node_id},
            )
            rows2 = self._graph_collect(result2)
            if rows2:
                return rows2[0][0] or ""
            return ""
        names = [row[0] for row in rows]
        return ' > '.join(str(n) for n in names)

    def _graph_get_entries_for_subject(self, subject_id: int,
                                       include_children: bool = True) -> list:
        """Get entry IDs tagged to a subject from the graph.

        Equivalent to ``get_entries_by_subject()`` in SQLite.

        Returns:
            List of integer entry IDs.
        """
        if include_children:
            result = self._graph_execute(
                "MATCH (s:Subject {sqlite_id: $id})-[:HAS_CHILD*0..20]->(child:Subject)"
                "<-[:TAGGED_TO]-(e:Entry) "
                "RETURN DISTINCT e.sqlite_id",
                {"id": subject_id},
            )
        else:
            result = self._graph_execute(
                "MATCH (e:Entry)-[:TAGGED_TO]->(s:Subject {sqlite_id: $id}) "
                "RETURN e.sqlite_id",
                {"id": subject_id},
            )
        rows = self._graph_collect(result)
        return [row[0] for row in rows]

    def _graph_get_intersection_entries(self, hierarchy_a_id: int,
                                        hierarchy_b_id: int,
                                        include_children: bool = True) -> list:
        """Get entry IDs at the intersection of two subject hierarchies.

        Equivalent to ``get_intersection_entries()`` in SQLite.

        Returns:
            List of integer entry IDs.
        """
        if include_children:
            result = self._graph_execute(
                "MATCH (s1:Subject {sqlite_id: $a})-[:HAS_CHILD*0..20]->(c1:Subject)"
                "<-[:TAGGED_TO]-(e:Entry)-[:TAGGED_TO]->"
                "(c2:Subject)<-[:HAS_CHILD*0..20]-(s2:Subject {sqlite_id: $b}) "
                "RETURN DISTINCT e.sqlite_id",
                {"a": hierarchy_a_id, "b": hierarchy_b_id},
            )
        else:
            result = self._graph_execute(
                "MATCH (e:Entry)-[:TAGGED_TO]->(s1:Subject {sqlite_id: $a}), "
                "(e)-[:TAGGED_TO]->(s2:Subject {sqlite_id: $b}) "
                "RETURN DISTINCT e.sqlite_id",
                {"a": hierarchy_a_id, "b": hierarchy_b_id},
            )
        rows = self._graph_collect(result)
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # Dual-write infrastructure (P2.1)
    # ------------------------------------------------------------------

    def _dual_write_graph(self, operation_name: str, graph_fn):
        """Execute a graph write operation with failure handling.

        If the graph write fails, the SQLite write has already succeeded.
        We mark the graph as stale and log the error.

        Args:
            operation_name: Human-readable name for logging
            graph_fn: Callable that performs the graph write
        """
        if not self._graph_available:
            return
        try:
            graph_fn()
        except Exception as e:
            logger.warning(f"Graph dual-write failed for {operation_name}: {e}")
            self._mark_graph_stale()

    def _mark_graph_stale(self):
        """Mark the graph as potentially stale after a failed write."""
        try:
            self._ensure_graph_preferences()
            self.conn.execute(
                "UPDATE user_preferences SET graph_stale = 1 WHERE user_id = ?",
                (self.user_id,)
            )
            self.conn.commit()
            logger.warning("Graph marked as stale — will reconcile on next load")
        except Exception as e:
            logger.error(f"Failed to mark graph as stale: {e}")

    def _is_graph_stale(self) -> bool:
        """Check if the graph is flagged as potentially stale."""
        try:
            row = self.fetchone(
                "SELECT graph_stale FROM user_preferences WHERE user_id = ?",
                (self.user_id,)
            )
            return bool(row and row.get('graph_stale'))
        except Exception:
            return False

    def _reconcile_graph(self):
        """Rebuild the graph from SQLite data.

        Called when the graph is flagged as stale.
        Deletes the graph file, re-runs full ETL.
        """
        logger.info("Reconciling graph from SQLite...")
        self._close_graph()

        # Delete graph file
        if self._graph_path:
            graph_path = Path(str(self._graph_path))
            if graph_path.exists():
                if graph_path.is_dir():
                    shutil.rmtree(str(graph_path))
                else:
                    graph_path.unlink()

        # Clear stale flag and version
        self._clear_graph_schema_version_pref()
        try:
            self.conn.execute(
                "UPDATE user_preferences SET graph_stale = 0 WHERE user_id = ?",
                (self.user_id,)
            )
            self.conn.commit()
        except Exception:
            pass

        # Reopen and re-run schema + ETL
        try:
            self._open_graph()
            self._ensure_graph_schema()
            logger.info("Graph reconciliation complete")
        except Exception as e:
            logger.error(f"Graph reconciliation failed: {e}")
            self._graph_db = None
            self._graph_conn = None
