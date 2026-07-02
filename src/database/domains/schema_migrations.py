"""WIMI Schema migration methods."""

import json
from pathlib import Path

from ..base_db import DatabaseConnectionError, DatabaseIntegrityError
from ..exceptions import ValidationError, SubjectNodeError, QuestionAnalysisError, TagError, PreferenceError
from app_logging import ErrorLogger, ErrorLevel, ErrorCategory, ErrorContext


class SchemaMigrationMixin:
    """Mixin providing all schema migration and ensure methods for UserDatabase."""

    def _ensure_phase2_schema(self) -> None:
        """
        Ensure Phase 2 schema tables exist.
        This method is idempotent and safe to call multiple times.
        """
        # Check if Phase 2 tables exist
        tables = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {row['name'] for row in tables}

        phase2_tables = {'exam_contexts', 'hierarchy_level_definitions', 'subject_node_weights'}
        missing_tables = phase2_tables - table_names

        if missing_tables:
            # Run Phase 2 schema
            schema_path = Path(__file__).parent.parent / 'schema' / 'user_db_schema_v1_phase2.sql'

            if not schema_path.exists():
                if self.error_logger:
                    self.error_logger.warning(
                        f"Phase 2 schema file not found: {schema_path}",
                        category=ErrorCategory.DATABASE
                    )
                return

            with open(schema_path, 'r') as f:
                schema_sql = f.read()

            try:
                self.conn.executescript(schema_sql)
                self.conn.commit()

                if self.error_logger:
                    self.error_logger.info(
                        f"Phase 2 schema initialized for user {self.username}",
                        category=ErrorCategory.DATABASE
                    )
            except Exception as e:
                if self.error_logger:
                    self.error_logger.error(
                        f"Failed to initialize Phase 2 schema for user {self.username}",
                        category=ErrorCategory.DATABASE,
                        error=e
                    )
                raise

    def _ensure_phase4_schema(self) -> None:
        """
        Ensure Phase 4 schema tables exist.
        This method is idempotent and safe to call multiple times.
        """
        # Check if Phase 4 tables exist
        tables = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {row['name'] for row in tables}

        phase4_tables = {
            'question_sources', 'review_sessions', 'question_entries',
            'entry_subject_mappings', 'entry_tags', 'entry_media'
        }
        missing_tables = phase4_tables - table_names

        # Always run column migrations for existing databases
        if 'review_sessions' in table_names:
            self._ensure_session_duration_column()
            self._ensure_timer_break_columns()

        if 'exam_contexts' in table_names:
            self._ensure_analytics_config_column()

        if 'entry_media' in table_names:
            self._ensure_media_dimension_column()
            self._ensure_media_active_column()
            self._ensure_media_decoupling_schema(table_names)

        # Add rich text JSON columns for Phase 8 (if question_entries exists)
        if 'question_entries' in table_names:
            self._ensure_richtext_json_columns()

        # Phase 9: Entry notes table + migration from legacy notes field
        self._ensure_entry_notes_table(table_names)

        # Saved delimiters table for Export Question IDs dialog
        self._ensure_saved_delimiters_table(table_names)

        # Import mapping profiles table for session import wizard
        self._ensure_import_mappings_table(table_names)

        # Timer rounds table for multi-round session timer
        self._ensure_timer_rounds_table(table_names)

        if missing_tables:
            # Run Phase 4 schema
            schema_path = Path(__file__).parent.parent / 'schema' / 'user_db_schema_v1_phase4.sql'

            if not schema_path.exists():
                if self.error_logger:
                    self.error_logger.warning(
                        f"Phase 4 schema file not found: {schema_path}",
                        category=ErrorCategory.DATABASE
                    )
                return

            with open(schema_path, 'r') as f:
                schema_sql = f.read()

            try:
                self.conn.executescript(schema_sql)
                self.conn.commit()

                # Add hierarchy columns to tags table if not present
                self._ensure_tags_hierarchy_columns()

                # Add dimension_id column to entry_media if not present
                self._ensure_media_dimension_column()

                # Add is_active column to entry_media if not present
                self._ensure_media_active_column()

                # Create junction table for media decoupling
                tables_now = {r['name'] for r in self.fetchall(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                self._ensure_media_decoupling_schema(tables_now)

                # Add session_duration_minutes to review_sessions
                self._ensure_session_duration_column()

                # Add timer break columns to review_sessions
                self._ensure_timer_break_columns()

                # Add analytics_config to exam_contexts
                self._ensure_analytics_config_column()

                if self.error_logger:
                    self.error_logger.info(
                        f"Phase 4 schema initialized for user {self.username}",
                        category=ErrorCategory.DATABASE
                    )
            except Exception as e:
                if self.error_logger:
                    self.error_logger.error(
                        f"Failed to initialize Phase 4 schema for user {self.username}",
                        category=ErrorCategory.DATABASE,
                        error=e
                    )
                raise

    def _ensure_tags_hierarchy_columns(self) -> None:
        """Add hierarchy columns to tags table if they don't exist"""
        columns = self.fetchall("PRAGMA table_info(tags)")
        column_names = {col['name'] for col in columns}

        if 'parent_id' not in column_names:
            self.execute("ALTER TABLE tags ADD COLUMN parent_id INTEGER REFERENCES tags(id) NULL")
        if 'is_group' not in column_names:
            self.execute("ALTER TABLE tags ADD COLUMN is_group BOOLEAN DEFAULT FALSE")
        if 'display_order' not in column_names:
            self.execute("ALTER TABLE tags ADD COLUMN display_order INTEGER DEFAULT 0")

        self.conn.commit()

    def _ensure_media_dimension_column(self) -> None:
        """Add dimension_id column to entry_media table if it doesn't exist"""
        columns = self.fetchall("PRAGMA table_info(entry_media)")
        column_names = {col['name'] for col in columns}

        if 'dimension_id' not in column_names:
            self.execute("ALTER TABLE entry_media ADD COLUMN dimension_id INTEGER NULL")
            self.conn.commit()

    def _ensure_media_active_column(self) -> None:
        """Add is_active column to entry_media table if it doesn't exist"""
        columns = self.fetchall("PRAGMA table_info(entry_media)")
        column_names = {col['name'] for col in columns}

        if 'is_active' not in column_names:
            self.execute("ALTER TABLE entry_media ADD COLUMN is_active INTEGER DEFAULT 1")
            self.conn.commit()

    def _ensure_media_decoupling_schema(self, table_names: set) -> None:
        """
        Decouple media from entries: create junction table, backfill data,
        add user_id to entry_media, and update the summary view.
        Idempotent — checks for junction table existence before running.
        """
        if 'entry_media_mapping' in table_names:
            return

        # 1. Create junction table
        self.execute("""
            CREATE TABLE IF NOT EXISTS entry_media_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_entry_id INTEGER NOT NULL
                    REFERENCES question_entries(id) ON DELETE CASCADE,
                media_id INTEGER NOT NULL
                    REFERENCES entry_media(id) ON DELETE CASCADE,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.execute("""
            CREATE INDEX IF NOT EXISTS idx_emm_entry
            ON entry_media_mapping(question_entry_id, sort_order)
        """)
        self.execute("""
            CREATE INDEX IF NOT EXISTS idx_emm_media
            ON entry_media_mapping(media_id)
        """)
        self.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_emm_unique
            ON entry_media_mapping(question_entry_id, media_id)
        """)

        # 2. Populate junction table from existing entry_media rows
        self.execute("""
            INSERT OR IGNORE INTO entry_media_mapping
                (question_entry_id, media_id, sort_order, is_active)
            SELECT question_entry_id, id, sort_order, COALESCE(is_active, 1)
            FROM entry_media
            WHERE question_entry_id IS NOT NULL
        """)

        # 3. Add user_id column to entry_media if missing
        columns = self.fetchall("PRAGMA table_info(entry_media)")
        column_names = {col['name'] for col in columns}
        if 'user_id' not in column_names:
            self.execute(
                "ALTER TABLE entry_media ADD COLUMN user_id INTEGER"
            )
            # Backfill user_id from the join chain
            self.execute("""
                UPDATE entry_media SET user_id = (
                    SELECT rs.user_id
                    FROM question_entries qe
                    JOIN review_sessions rs ON qe.review_session_id = rs.id
                    WHERE qe.id = entry_media.question_entry_id
                )
                WHERE question_entry_id IS NOT NULL AND user_id IS NULL
            """)

        # 4. Recreate v_question_entry_summary view to use junction table
        self.execute("DROP VIEW IF EXISTS v_question_entry_summary")
        self.execute("""
            CREATE VIEW IF NOT EXISTS v_question_entry_summary AS
            SELECT
                qe.id,
                qe.review_session_id,
                qe.entry_order,
                qe.question_id,
                qe.user_answer,
                qe.correct_answer,
                qe.perceived_difficulty,
                qe.is_draft,
                qe.created_at,
                qe.updated_at,
                (SELECT COUNT(*) FROM entry_subject_mappings esm
                 WHERE esm.question_entry_id = qe.id
                 AND esm.mapping_type = 'primary') as primary_subject_count,
                (SELECT COUNT(*) FROM entry_subject_mappings esm
                 WHERE esm.question_entry_id = qe.id
                 AND esm.mapping_type = 'secondary') as secondary_subject_count,
                (SELECT COUNT(*) FROM entry_tags et
                 WHERE et.question_entry_id = qe.id) as tag_count,
                (SELECT COUNT(*) FROM entry_media_mapping emm
                 WHERE emm.question_entry_id = qe.id
                 AND emm.is_active = 1) as media_count
            FROM question_entries qe
        """)

        self.conn.commit()

    def _ensure_richtext_json_columns(self) -> None:
        """
        Add rich text JSON columns to question_entries table if they don't exist.
        Phase 8: These columns store Quill Delta JSON format for rich text editing.
        """
        columns = self.fetchall("PRAGMA table_info(question_entries)")
        column_names = {col['name'] for col in columns}

        columns_to_add = [
            ('explanation_json', 'TEXT'),
            ('reflection_json', 'TEXT'),
            ('notes_json', 'TEXT')
        ]

        for col_name, col_type in columns_to_add:
            if col_name not in column_names:
                self.execute(f"ALTER TABLE question_entries ADD COLUMN {col_name} {col_type}")

        self.conn.commit()

    def _ensure_entry_notes_table(self, table_names: set = None) -> None:
        """
        Create entry_notes table if missing and migrate legacy notes.

        Phase 9: Multiple discrete notes per entry with subject linking.
        Migrates existing question_entries.notes -> entry_notes rows one-time.
        """
        if table_names is None:
            tables = self.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            table_names = {row['name'] for row in tables}

        if 'entry_notes' not in table_names:
            schema_path = Path(__file__).parent.parent / 'schema' / 'user_db_schema_v1_phase9_notes.sql'
            if schema_path.exists():
                with open(schema_path, 'r') as f:
                    schema_sql = f.read()
                self.conn.executescript(schema_sql)
                self.conn.commit()

            # One-time migration: copy existing notes to entry_notes
            if 'question_entries' in table_names:
                self._migrate_legacy_notes()

    def _migrate_legacy_notes(self) -> None:
        """Migrate existing question_entries.notes into entry_notes table."""
        rows = self.fetchall("""
            SELECT id, notes, notes_json
            FROM question_entries
            WHERE notes IS NOT NULL AND notes != ''
        """)
        for row in rows:
            # Check if already migrated (safety for re-runs)
            existing = self.fetchone(
                "SELECT id FROM entry_notes WHERE question_entry_id = ? AND is_migrated = 1",
                (row['id'],)
            )
            if existing:
                continue
            self.execute("""
                INSERT INTO entry_notes (question_entry_id, content_html, content_json, sort_order, is_migrated)
                VALUES (?, ?, ?, 0, 1)
            """, (row['id'], row['notes'], row.get('notes_json')))
        self.conn.commit()

    def _ensure_saved_delimiters_table(self, table_names: set = None) -> None:
        """Create saved_delimiters table if missing."""
        if table_names is None:
            tables = self.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            table_names = {row['name'] for row in tables}

        if 'saved_delimiters' not in table_names:
            schema_path = Path(__file__).parent.parent / 'schema' / 'user_db_schema_v1_saved_delimiters.sql'
            if schema_path.exists():
                with open(schema_path, 'r') as f:
                    schema_sql = f.read()
                self.conn.executescript(schema_sql)
                self.conn.commit()

    def _ensure_import_mappings_table(self, table_names: set = None) -> None:
        """Create import_mapping_profiles table if missing."""
        if table_names is None:
            tables = self.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            table_names = {row['name'] for row in tables}

        if 'import_mapping_profiles' not in table_names:
            schema_path = Path(__file__).parent.parent / 'schema' / 'user_db_schema_v1_import_mappings.sql'
            if schema_path.exists():
                with open(schema_path, 'r') as f:
                    schema_sql = f.read()
                self.conn.executescript(schema_sql)
                self.conn.commit()

    def _ensure_timer_rounds_table(self, table_names: set = None) -> None:
        """Create session_timer_rounds table if missing and migrate existing sessions."""
        if table_names is None:
            tables = self.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            table_names = {row['name'] for row in tables}

        if 'session_timer_rounds' not in table_names:
            schema_path = Path(__file__).parent.parent / 'schema' / 'user_db_schema_v1_timer_rounds.sql'
            if schema_path.exists():
                with open(schema_path, 'r') as f:
                    schema_sql = f.read()
                self.conn.executescript(schema_sql)
                self.conn.commit()
            # Only migrate if review_sessions already exists (skip on fresh DB)
            if 'review_sessions' in table_names:
                self._migrate_existing_timed_sessions()

    def _migrate_existing_timed_sessions(self) -> None:
        """Create round 1 for existing timed sessions that don't have one yet."""
        rows = self.fetchall("""
            SELECT id, started_at, total_break_seconds, timer_paused_at,
                   session_duration_minutes
            FROM review_sessions
            WHERE session_duration_minutes IS NOT NULL
              AND id NOT IN (
                  SELECT review_session_id FROM session_timer_rounds
                  WHERE round_number = 1
              )
        """)
        for row in rows:
            self.execute("""
                INSERT INTO session_timer_rounds
                    (review_session_id, round_number, duration_minutes,
                     started_at, total_break_seconds, timer_paused_at)
                VALUES (?, 1, ?, ?, ?, ?)
            """, (
                row['id'],
                row['session_duration_minutes'],
                row['started_at'],
                row['total_break_seconds'] or 0,
                row['timer_paused_at'],
            ))
        if rows:
            self.conn.commit()

    def _ensure_session_duration_column(self) -> None:
        """Ensure session_duration_minutes column exists in review_sessions table."""
        columns = self.fetchall("PRAGMA table_info(review_sessions)")
        column_names = {col['name'] for col in columns}

        if 'session_duration_minutes' not in column_names:
            try:
                self.execute(
                    "ALTER TABLE review_sessions ADD COLUMN session_duration_minutes INTEGER DEFAULT NULL"
                )
                self.conn.commit()
                if self.error_logger:
                    self.error_logger.debug(
                        f"Added session_duration_minutes column for user {self.username}",
                        category=ErrorCategory.DATABASE
                    )
            except Exception as e:
                if self.error_logger:
                    self.error_logger.error(
                        f"Failed to add session_duration_minutes column for user {self.username}",
                        category=ErrorCategory.DATABASE,
                        error=e
                    )

    def _ensure_timer_break_columns(self) -> None:
        """Ensure total_break_seconds and timer_paused_at columns exist in review_sessions."""
        columns = self.fetchall("PRAGMA table_info(review_sessions)")
        column_names = {col['name'] for col in columns}

        for col_name, col_def in [
            ('total_break_seconds', 'INTEGER DEFAULT 0'),
            ('timer_paused_at', 'TEXT DEFAULT NULL'),
        ]:
            if col_name not in column_names:
                try:
                    self.execute(
                        f"ALTER TABLE review_sessions ADD COLUMN {col_name} {col_def}"
                    )
                    self.conn.commit()
                    if self.error_logger:
                        self.error_logger.debug(
                            f"Added {col_name} column for user {self.username}",
                            category=ErrorCategory.DATABASE
                        )
                except Exception as e:
                    if self.error_logger:
                        self.error_logger.error(
                            f"Failed to add {col_name} column for user {self.username}",
                            category=ErrorCategory.DATABASE,
                            error=e
                        )

    def _ensure_analytics_config_column(self) -> None:
        """Ensure analytics_config column exists in exam_contexts table."""
        columns = self.fetchall("PRAGMA table_info(exam_contexts)")
        column_names = {col['name'] for col in columns}

        if 'analytics_config' not in column_names:
            try:
                self.execute(
                    "ALTER TABLE exam_contexts ADD COLUMN analytics_config TEXT DEFAULT NULL"
                )
                self.conn.commit()
                if self.error_logger:
                    self.error_logger.debug(
                        f"Added analytics_config column for user {self.username}",
                        category=ErrorCategory.DATABASE
                    )
            except Exception as e:
                if self.error_logger:
                    self.error_logger.error(
                        f"Failed to add analytics_config column for user {self.username}",
                        category=ErrorCategory.DATABASE,
                        error=e
                    )

    def _ensure_phase6_schema(self) -> None:
        """
        Ensure Phase 6 schema tables exist.
        This method is idempotent and safe to call multiple times.
        """
        # Check if Phase 6 tables exist
        tables = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {row['name'] for row in tables}

        phase6_tables = {
            'user_goals', 'goal_periods', 'reflection_themes'
        }
        missing_tables = phase6_tables - table_names

        if missing_tables:
            # Run Phase 6 schema
            schema_path = Path(__file__).parent.parent / 'schema' / 'user_db_schema_v1_phase6.sql'

            if not schema_path.exists():
                if self.error_logger:
                    self.error_logger.warning(
                        f"Phase 6 schema file not found: {schema_path}",
                        category=ErrorCategory.DATABASE
                    )
                return

            with open(schema_path, 'r') as f:
                schema_sql = f.read()

            try:
                self.conn.executescript(schema_sql)
                self.conn.commit()

                if self.error_logger:
                    self.error_logger.info(
                        f"Phase 6 schema initialized for user {self.username}",
                        category=ErrorCategory.DATABASE
                    )
            except Exception as e:
                if self.error_logger:
                    self.error_logger.error(
                        f"Failed to initialize Phase 6 schema for user {self.username}",
                        category=ErrorCategory.DATABASE,
                        error=e
                    )
                raise

    def _ensure_phase7_schema(self) -> None:
        """
        Ensure Phase 7 schema tables exist.

        This method is idempotent and safe to call multiple times.
        It creates the exam_dimensions and question_hierarchy_tags tables
        if they don't exist, and adds dimension_id column to subject_nodes.
        """
        # Check if Phase 7 tables exist
        tables = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {row['name'] for row in tables}

        phase7_tables = {'exam_dimensions', 'question_hierarchy_tags'}
        missing_tables = phase7_tables - table_names

        if missing_tables:
            # Run Phase 7 schema
            schema_path = Path(__file__).parent.parent / 'schema' / 'user_db_schema_v1_phase7.sql'

            if not schema_path.exists():
                if hasattr(self, 'error_logger') and self.error_logger:
                    self.error_logger.warning(
                        f"Phase 7 schema file not found: {schema_path}",
                        category='DATABASE'
                    )
                # Create tables directly if schema file doesn't exist
                self._create_phase7_tables_directly()
                return

            with open(schema_path, 'r') as f:
                schema_sql = f.read()

            try:
                self.conn.executescript(schema_sql)
                self.conn.commit()

                if hasattr(self, 'error_logger') and self.error_logger:
                    self.error_logger.info(
                        f"Phase 7 schema initialized for user {getattr(self, 'username', 'unknown')}",
                        category='DATABASE'
                    )
            except Exception as e:
                if hasattr(self, 'error_logger') and self.error_logger:
                    self.error_logger.error(
                        f"Failed to initialize Phase 7 schema: {e}",
                        category='DATABASE',
                        error=e
                    )
                raise

        # Ensure dimension_id column exists in subject_nodes
        self._ensure_dimension_id_column()

    def _create_phase7_tables_directly(self) -> None:
        """Create Phase 7 tables directly without schema file"""
        cursor = self.conn.cursor()

        # Create exam_dimensions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_dimensions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                display_order INTEGER NOT NULL,
                is_required INTEGER DEFAULT 1,
                allow_multiple INTEGER DEFAULT 0,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exam_id) REFERENCES exam_contexts(id) ON DELETE CASCADE,
                UNIQUE(exam_id, name),
                UNIQUE(exam_id, display_order)
            )
        """)

        # Create indexes for exam_dimensions
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dimensions_exam
            ON exam_dimensions(exam_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dimensions_order
            ON exam_dimensions(exam_id, display_order)
        """)

        # Create question_hierarchy_tags table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS question_hierarchy_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                hierarchy_id INTEGER NOT NULL,
                dimension_id INTEGER NOT NULL,
                tagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (entry_id) REFERENCES question_entries(id) ON DELETE CASCADE,
                FOREIGN KEY (hierarchy_id) REFERENCES subject_nodes(id) ON DELETE CASCADE,
                FOREIGN KEY (dimension_id) REFERENCES exam_dimensions(id) ON DELETE CASCADE,
                UNIQUE(entry_id, dimension_id, hierarchy_id)
            )
        """)

        # Create indexes for question_hierarchy_tags
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_entry
            ON question_hierarchy_tags(entry_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_hierarchy
            ON question_hierarchy_tags(hierarchy_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_dimension
            ON question_hierarchy_tags(dimension_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_entry_dimension
            ON question_hierarchy_tags(entry_id, dimension_id)
        """)

        self.conn.commit()

    def _ensure_dimension_id_column(self) -> None:
        """Ensure dimension_id column exists in subject_nodes table"""
        columns = self.fetchall("PRAGMA table_info(subject_nodes)")
        column_names = {col['name'] for col in columns}

        if 'dimension_id' not in column_names:
            try:
                self.execute("""
                    ALTER TABLE subject_nodes ADD COLUMN dimension_id INTEGER
                """)
                self.conn.commit()

                # Create index
                self.execute("""
                    CREATE INDEX IF NOT EXISTS idx_subject_nodes_dimension
                    ON subject_nodes(dimension_id)
                """)
                self.conn.commit()

                if hasattr(self, 'error_logger') and self.error_logger:
                    self.error_logger.info(
                        "Added dimension_id column to subject_nodes",
                        category='DATABASE'
                    )
            except Exception as e:
                if hasattr(self, 'error_logger') and self.error_logger:
                    self.error_logger.error(
                        f"Failed to add dimension_id column: {e}",
                        category='DATABASE',
                        error=e
                    )
                # Don't raise - allow app to continue with limited functionality

