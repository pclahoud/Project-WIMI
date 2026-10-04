"""
User Database Manager
Handles individual user data in isolated databases.

Composed from domain-specific mixins — see ``src/database/domains/`` for
the individual domain modules.
"""
from pathlib import Path
from typing import Optional

from .base_db import BaseDatabase
from .device_local import UNKNOWN_DEVICE_ID
from .migration_runner import MigrationRunner
from .domains import (
    SharedHelpersMixin,
    SchemaMigrationMixin,
    PreferencesMixin,
    DeviceSettingsMixin,
    ExamContextMixin,
    HierarchyMixin,
    EdgesMixin,
    RelationsMixin,
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
    SubjectImportMixin,
    SubjectRestoreMixin,
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
    UserPreferences, DeviceSettings, SubjectNode, QuestionAnalysis,
    QuestionTopicAssignment, Tag, QuestionTag, SubjectAlias
)
from app_logging import ErrorLogger, ErrorLevel, ErrorCategory, ErrorContext


class UserDatabase(
    GraphMixin,
    SchemaMigrationMixin,
    SharedHelpersMixin,
    PreferencesMixin,
    DeviceSettingsMixin,
    ExamContextMixin,
    HierarchyMixin,
    EdgesMixin,
    RelationsMixin,
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
    SubjectImportMixin,
    SubjectRestoreMixin,
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
        error_logger: Optional[ErrorLogger] = None,
        device_id: Optional[str] = None,
    ):
        """
        Initialize user database.

        Args:
            db_path: Path to user database file
            user_id: User ID from master database
            username: Username for logging
            error_logger: Error logger instance
            device_id: This machine's identity, from
                ``MasterDatabase.get_device_id()``. It keys
                ``device_settings`` (#126) and is deliberately NOT stored
                in this database: it names the machine, so it must not
                travel with a profile. Omitting it falls back to
                ``UNKNOWN_DEVICE_ID`` — fine for a test or a short-lived
                verify-open, wrong for a profile a student is actually
                using, so every production open passes one.
        """
        self.user_id = user_id
        self.username = username
        self.error_logger = error_logger
        self._device_id = device_id or UNKNOWN_DEVICE_ID

        # Initialize database connection
        super().__init__(db_path)

        # Everything from here on is post-connect work, and all of it can
        # raise: a failing migration, a checksum divergence that reached
        # the runner, a disk error. `closing_on_failed_init` releases the
        # connection opened above and re-raises the original failure, so a
        # constructor that does not return also does not leak a handle.
        #
        # This is load-bearing rather than tidy, and the reason is on the
        # OTHER side of the call: the exception escapes before the
        # caller's assignment completes, so the caller holds `None` and
        # its `if db is not None: db.close()` cannot fire. See
        # `BaseDatabase.closing_on_failed_init` for the measured Windows
        # consequence (#292) and for why `gc.collect()` is not an
        # alternative.
        with self.closing_on_failed_init():
            # Apply pending schema migrations via the versioned runner.
            # Imported locally to avoid a circular import (migrations ->
            # migration_runner -> user_db at module-load time).
            from .migrations.user import MIGRATIONS as USER_MIGRATIONS
            MigrationRunner(
                self.conn,
                USER_MIGRATIONS,
                scope="user",
                error_logger=error_logger,
            ).apply_pending()

            # Claim m021's handover row for this machine, immediately.
            #
            # A migration cannot know the device id (it lives in the
            # master database), so m021 parks the values it moved under a
            # reserved id for the machine that ran it to adopt. Doing that
            # here rather than lazily on first read closes the only window
            # in which an unclaimed row could reach an archive: the
            # migration runs a few lines above, and after this line no
            # opened database carries one. An export of a profile whose
            # handover was still pending would hand the RECEIVING machine
            # this machine's AnkiConnect host, which is exactly the bug
            # #126 exists to remove.
            try:
                self._claim_legacy_device_rows()
            except Exception as exc:  # pragma: no cover - defensive
                if error_logger:
                    error_logger.warning(
                        f"Could not claim device-local settings: {exc}",
                        category=ErrorCategory.DATABASE,
                    )

            # Initialize graph database (LadybugDB) — optional, never crashes
            self._init_graph()

            # Give the query planner something to work with, last (#218).
            #
            # Last on purpose: it has to follow the migration runner above,
            # so an index a migration just added is analysed in the same
            # session that created it rather than from the next open
            # onwards. It is deliberately NOT in `_connect`, for two
            # measured reasons — on a brand-new file the schema does not
            # exist yet there, so it would write nothing; and `_connect`
            # runs before the migrations, so a new index would be missed.
            #
            # See `BaseDatabase.write_planner_statistics` for why this is
            # ANALYZE rather than PRAGMA optimize, what it costs, and the
            # one query it makes slower.
            self.write_planner_statistics()

    def close(self) -> None:
        """Close all database connections (SQLite and graph)."""
        self._close_graph()
        super().close()
