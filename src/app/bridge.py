"""
Database Bridge for PyQt6 WebChannel
Provides Python-JavaScript communication for database operations.

This module composes domain-specific mixins from bridge_domains/ into
a single DatabaseBridge class exposed to the frontend via WebChannel.
"""

import sys
import traceback
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from database import MasterDatabase, UserDatabase
from app_logging import ErrorLogger

# Re-export helpers for backward compatibility (used by tests)
from app.bridge_helpers import DateTimeEncoder, serialize_response  # noqa: F401

from app.bridge_domains import (
    SerializerMixin,
    PreferencesBridgeMixin,
    UtilityBridgeMixin,
    TagBridgeMixin,
    TimerBridgeMixin,
    NoteBridgeMixin,
    GoalsBridgeMixin,
    AliasBridgeMixin,
    SourceBridgeMixin,
    SessionBridgeMixin,
    EntryBridgeMixin,
    MediaBridgeMixin,
    HierarchyBridgeMixin,
    EdgesBridgeMixin,
    HierarchyTagBridgeMixin,
    ExamContextBridgeMixin,
    WeightBridgeMixin,
    BrowsingBridgeMixin,
    AnalyticsBridgeMixin,
    DimensionBridgeMixin,
    DimensionAnalyticsBridgeMixin,
    ImportExportBridgeMixin,
    PluginDispatchMixin,
    PluginManagementMixin,
)
from app.bridge_domains.mcp_server import McpServerBridgeMixin


class DatabaseBridge(
    QObject,                      # MUST be first for PyQt6 MRO
    SerializerMixin,
    ExamContextBridgeMixin,
    HierarchyBridgeMixin,
    EdgesBridgeMixin,
    HierarchyTagBridgeMixin,
    WeightBridgeMixin,
    DimensionBridgeMixin,
    DimensionAnalyticsBridgeMixin,
    SessionBridgeMixin,
    TimerBridgeMixin,
    EntryBridgeMixin,
    MediaBridgeMixin,
    NoteBridgeMixin,
    SourceBridgeMixin,
    TagBridgeMixin,
    AliasBridgeMixin,
    BrowsingBridgeMixin,
    AnalyticsBridgeMixin,
    GoalsBridgeMixin,
    ImportExportBridgeMixin,
    PreferencesBridgeMixin,
    UtilityBridgeMixin,
    PluginDispatchMixin,
    PluginManagementMixin,
    McpServerBridgeMixin,
):
    """
    Bridge class for Python-JavaScript database operations.

    All methods return JSON strings for JavaScript consumption.
    Methods use pyqtSlot decorator for WebChannel exposure.

    Domain logic lives in mixin classes under bridge_domains/.
    This class provides the QObject base, signals, and shared state.
    """

    # Signals for UI updates (must be on the QObject-derived class)
    examContextCreated = pyqtSignal(str)  # Emits exam_context_id
    examContextUpdated = pyqtSignal(str)  # Emits exam_context_id
    weightUpdated = pyqtSignal(str)       # Emits node_id
    userDatabaseLoaded = pyqtSignal(int)  # Emits user_id (test-mode only)

    def __init__(
        self,
        master_db: Optional[MasterDatabase] = None,
        user_db: Optional[UserDatabase] = None,
        error_logger: Optional[ErrorLogger] = None
    ):
        super().__init__()
        self.master_db = master_db
        self.user_db = user_db
        self.error_logger = error_logger
        self._plugin_registry = {}

    def set_user_database(self, user_db: UserDatabase):
        """Update the user database reference"""
        self.user_db = user_db

    def _log_error(self, message: str, context: dict = None):
        """Log an error if error logger is available.

        When called from inside an ``except`` block (the common case for
        bridge slots), capture the current exception's traceback and
        forward it so the log entry actually contains a stack trace.
        Without this, ``_log_error('Error updating foo: <e>')`` writes
        only the rendered message — useless for debugging a real user
        failure where you need to know which line raised.
        """
        if not self.error_logger:
            return
        exc_type, exc_value, _ = sys.exc_info()
        if exc_type is not None:
            self.error_logger.error(
                message,
                context=context,
                stack_trace=traceback.format_exc(),
            )
        else:
            self.error_logger.error(message, context=context)
