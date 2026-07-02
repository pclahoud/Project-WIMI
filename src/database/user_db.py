"""
User Database Manager
Handles individual user data in isolated databases.

Composed from domain-specific mixins — see ``src/database/domains/`` for
the individual domain modules.
"""
from pathlib import Path
from typing import Optional

from .base_db import BaseDatabase
from .migration_runner import MigrationRunner
from .domains import (
    SharedHelpersMixin,
    SchemaMigrationMixin,
    PreferencesMixin,
    ExamContextMixin,
    HierarchyMixin,
    EdgesMixin,
    TagsMixin,
    SessionsMixin,
    TimerMixin,
    SourcesMixin,
    EntriesMixin,
    MediaMixin,
    NotesMixin,
    AnalyticsMixin,
    AdvancedAnalyticsMixin,
    GoalsMixin,
    DimensionsMixin,
    AliasesMixin,
    ImportExportMixin,
    PluginDataMixin,
    GraphMixin,
)

# Re-export exceptions and models so that existing ``from .user_db import …``
# statements in tests and bridge.py continue to work.
from .exceptions import (
    ValidationError, SubjectNodeError, QuestionAnalysisError,
    TagError, PreferenceError
)
from .models import (
    UserPreferences, SubjectNode, QuestionAnalysis,
    QuestionTopicAssignment, Tag, QuestionTag, SubjectAlias
)
from app_logging import ErrorLogger, ErrorLevel, ErrorCategory, ErrorContext


class UserDatabase(
    GraphMixin,
    SchemaMigrationMixin,
    SharedHelpersMixin,
    PreferencesMixin,
    ExamContextMixin,
    HierarchyMixin,
    EdgesMixin,
    TagsMixin,
    SessionsMixin,
    TimerMixin,
    SourcesMixin,
    EntriesMixin,
    MediaMixin,
    NotesMixin,
    AnalyticsMixin,
    AdvancedAnalyticsMixin,
    GoalsMixin,
    DimensionsMixin,
    AliasesMixin,
    ImportExportMixin,
    PluginDataMixin,
    BaseDatabase,
):
    """
    Individual user database manager.
    Each user has their own isolated database for privacy and performance.

    Composed from domain-specific mixins in ``src/database/domains/``.
    """

    def __init__(
        self,
        db_path: Path,
        user_id: int,
        username: str,
        error_logger: Optional[ErrorLogger] = None
    ):
        """
        Initialize user database.

        Args:
            db_path: Path to user database file
            user_id: User ID from master database
            username: Username for logging
            error_logger: Error logger instance
        """
        self.user_id = user_id
        self.username = username
        self.error_logger = error_logger

        # Initialize database connection
        super().__init__(db_path)

        # Apply pending schema migrations via the versioned runner. Imported
        # locally to avoid a circular import (migrations -> migration_runner
        # -> user_db at module-load time).
        from .migrations.user import MIGRATIONS as USER_MIGRATIONS
        MigrationRunner(
            self.conn,
            USER_MIGRATIONS,
            scope="user",
            error_logger=error_logger,
        ).apply_pending()

        # Initialize graph database (LadybugDB) — optional, never crashes
        self._init_graph()

    def close(self) -> None:
        """Close all database connections (SQLite and graph)."""
        self._close_graph()
        super().close()
