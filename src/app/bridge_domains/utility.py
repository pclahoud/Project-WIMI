"""WIMI Utility bridge operations."""
import sys
from pathlib import Path

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import get_test_mode_bridge_calls, instrumented_slot

from ..bridge_helpers import serialize_response


class UtilityBridgeMixin:
    """Bridge mixin for utility operations. Composed into DatabaseBridge."""

    @pyqtSlot(float, result=str)
    def getTestModeBridgeCalls(self, since_ts: float = 0.0) -> str:
        """Return buffered bridge calls (test-mode only).

        Delegates to ``app.bridge_test_instrumentation.get_test_mode_bridge_calls``,
        which returns ``'[]'`` when test mode is off or no calls have been
        recorded. The wimi_test ``BridgeCapture`` polls this slot at low
        frequency and mirrors the buffer on the test driver side.

        Intentionally not wrapped with ``@instrumented_slot``: every
        call would otherwise self-record into the very buffer it returns,
        polluting the stream with poll-self-references. The CI check
        (``scripts/check_instrumented_slots.py``) recognises the literal
        phrase "Intentionally not wrapped" in this docstring as the
        opt-out sentinel and skips the pairing rule for this slot.
        """
        return get_test_mode_bridge_calls(self, since_ts)

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def loadTestUserDatabase(self, user_id: int) -> str:
        """Open the per-user DB for ``user_id`` and attach it to the bridge.

        Test-mode only. Production paths use
        ``MainWindow.set_user_database`` (driven by the user-login UI
        flow). The test harness can't go through that UI without already
        having a user loaded, so it goes through this slot instead.

        This sets ``self.user_db`` (which unblocks every analytics /
        entry / session / dimension bridge call) but does NOT wire the
        media manager or scheme handler — those live on ``MainWindow``
        and aren't reachable from the bridge. Scenarios touching media
        uploads will need a follow-up that emits a Qt signal the
        ``MainWindow`` can connect to.

        Refuses to run when test mode is off so a stray production
        invocation can't hand the bridge a foreign user's DB.
        """
        from app import test_mode

        if not test_mode.is_active():
            return serialize_response(
                False,
                error="loadTestUserDatabase is only available in test mode",
            )
        if self.master_db is None:
            return serialize_response(False, error="master DB not available")
        try:
            user = self.master_db.get_user(user_id=user_id)
            if user is None:
                return serialize_response(
                    False, error=f"user_id={user_id} not found"
                )
            # Make sure the per-user .db file exists and the schema is
            # initialised. Idempotent.
            self.master_db.ensure_user_database(user.id)

            from database import UserDatabase

            db_path = self.master_db.users_dir / user.database_filename
            new_db = UserDatabase(
                db_path=db_path,
                user_id=user.id,
                username=user.username,
            )
            self.user_db = new_db
            self.userDatabaseLoaded.emit(user.id)
            return serialize_response(
                True,
                data={
                    "user_id": user.id,
                    "username": user.username,
                    "db_path": str(db_path),
                },
            )
        except Exception as exc:
            self._log_error(
                f"loadTestUserDatabase failed: {exc}", {"user_id": user_id}
            )
            return serialize_response(
                False, error=f"loadTestUserDatabase failed: {exc}"
            )

    @pyqtSlot(result=str)
    @instrumented_slot
    def checkConnection(self) -> str:
        """
        Check if database connections are available.

        Returns:
            JSON response with connection status
        """
        return serialize_response(True, data={
            'master_db_connected': self.master_db is not None,
            'user_db_connected': self.user_db is not None
        })

    @pyqtSlot(result=str)
    @instrumented_slot
    def getAppInfo(self) -> str:
        """
        Get application information.

        Returns:
            JSON response with app info
        """
        return serialize_response(True, data={
            'name': 'WIMI',
            'version': '0.1.0-beta',
            'phase': 4,
            'description': 'Metacognitive exam preparation tool'
        })

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def readDocumentation(self, filename: str) -> str:
        """
        Read a documentation file from the docs/examples directory.

        Args:
            filename: Name of the documentation file

        Returns:
            JSON string with content or error
        """
        try:
            if getattr(sys, 'frozen', False):
                base_path = Path(sys._MEIPASS)
            else:
                base_path = Path(__file__).parent.parent.parent

            docs_path = base_path / 'docs' / 'examples' / filename

            if '..' in filename or filename.startswith('/'):
                return serialize_response(False, error='Invalid filename')

            if not docs_path.exists():
                alt_path = Path(__file__).parent.parent.parent / 'docs' / 'examples' / filename
                if alt_path.exists():
                    docs_path = alt_path
                else:
                    return serialize_response(False, error=f'Documentation file not found: {filename}')

            with open(docs_path, 'r', encoding='utf-8') as f:
                content = f.read()

            return serialize_response(True, data={
                'content': content,
                'filename': filename
            })

        except Exception as e:
            self._log_error(f'readDocumentation failed: {e}', {'filename': filename})
            return serialize_response(False, error=f'Failed to read documentation: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def copyToClipboard(self, text: str) -> str:
        """
        Copy text to the system clipboard via Qt.

        Args:
            text: The text to copy to clipboard

        Returns:
            JSON response with success status
        """
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            return serialize_response(True)
        except Exception as e:
            self._log_error(
                f'Error copying to clipboard: {e}',
                {
                    'text_len': len(text),
                    'text_preview': text[:200],
                },
            )
            return serialize_response(False, error=f'Failed to copy to clipboard: {e}')
