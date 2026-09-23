"""WIMI browser pane bridge operations.

The embedded browser pane is a second ``QWebEngineView`` in the right
half of the main splitter, so a question bank can sit beside the entry
form without alt-tabbing. Two groups of slots:

*Shortcuts* — ``getPaneSources``, ``recordPaneSourceOpened`` and
``setPaneDesktopSite`` read and write the per-source facts the pane
needs. A source earns a shortcut button by having a web address, which
is why the same call serves both the pane's button row and the settings
panel that fills those addresses in.

*Pane control* — ``openBrowserPane``, ``closeBrowserPane`` and
``getBrowserPaneStatus`` delegate to the controller attached by
``MainWindow._setup_browser_pane`` after the web channel exists. Each
degrades to ``success=false, error='browser pane not available'`` when
no controller is attached, because the pane is optional: a page must be
able to ask without knowing whether the feature is present, and a
missing pane is a normal state rather than an error to surface.
"""
from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response


class BrowserPaneBridgeMixin:
    """Bridge mixin for the embedded browser pane. Composed into DatabaseBridge."""

    # ------------------------------------------------------------------
    # Question bank shortcuts
    # ------------------------------------------------------------------

    @pyqtSlot(result=str)
    @instrumented_slot
    def getPaneSources(self) -> str:
        """Question sources the pane offers as shortcut buttons.

        A source earns a button by having a web address, so this is also
        what the settings panel renders: sources with an address get a
        control, sources without get an invitation to add one.

        Returns:
            JSON response with a list of
            ``{id, source_name, url, desktop_site, last_opened_at}``,
            most-recently-opened first.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database loaded')
        try:
            return serialize_response(True, data=self.user_db.get_pane_sources())
        except Exception as e:
            self._log_error(f'getPaneSources failed: {e}')
            return serialize_response(False, error=f'Failed to read sources: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def recordPaneSourceOpened(self, source_id: int) -> str:
        """Record that the pane opened this source, for MRU ordering."""
        if not self.user_db:
            return serialize_response(False, error='No user database loaded')
        try:
            self.user_db.touch_pane_source(source_id)
            return serialize_response(True, data={'source_id': source_id})
        except Exception as e:
            self._log_error(
                f'recordPaneSourceOpened failed: {e}', {'source_id': source_id}
            )
            return serialize_response(False, error=f'Failed to record open: {e}')

    @pyqtSlot(int, bool, result=str)
    @instrumented_slot
    def setPaneDesktopSite(self, source_id: int, enabled: bool) -> str:
        """Whether the pane sends a desktop user-agent for this source.

        Per-source rather than global: one qbank may serve a cramped
        mobile layout to an embedded view while another is fine.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database loaded')
        try:
            self.user_db.set_pane_desktop_site(source_id, enabled)
            return serialize_response(
                True, data={'source_id': source_id, 'desktop_site': bool(enabled)}
            )
        except Exception as e:
            self._log_error(
                f'setPaneDesktopSite failed: {e}', {'source_id': source_id}
            )
            return serialize_response(False, error=f'Failed to save setting: {e}')

    def _get_browser_pane_controller(self):
        return getattr(self, '_browser_pane_controller', None)

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def openBrowserPane(self, url: str) -> str:
        """Show the browser pane and navigate it to ``url``.

        Returns:
            JSON response with the controller's status dict, falling back
            to ``{'open': True, 'url': url}`` if the controller returns
            something that is not a dict.
        """
        controller = self._get_browser_pane_controller()
        if controller is None:
            return serialize_response(False, error='browser pane not available')

        try:
            open_pane = getattr(controller, 'open_pane', None)
            if open_pane is None:
                return serialize_response(
                    False,
                    error='browser pane controller does not support open_pane',
                )
            result = open_pane(url)
            if not isinstance(result, dict):
                result = {'open': True, 'url': url}
            return serialize_response(True, data=result)
        except Exception as e:
            self._log_error(f'openBrowserPane failed: {e}', {'url': url})
            return serialize_response(
                False, error=f'Failed to open browser pane: {e}'
            )

    @pyqtSlot(result=str)
    @instrumented_slot
    def closeBrowserPane(self) -> str:
        """Hide the browser pane.

        Returns:
            JSON response with the controller's status dict, falling back
            to ``{'open': False}``.
        """
        controller = self._get_browser_pane_controller()
        if controller is None:
            return serialize_response(False, error='browser pane not available')

        try:
            close_pane = getattr(controller, 'close_pane', None)
            if close_pane is None:
                return serialize_response(
                    False,
                    error='browser pane controller does not support close_pane',
                )
            result = close_pane()
            if not isinstance(result, dict):
                result = {'open': False}
            return serialize_response(True, data=result)
        except Exception as e:
            self._log_error(f'closeBrowserPane failed: {e}')
            return serialize_response(
                False, error=f'Failed to close browser pane: {e}'
            )

    @pyqtSlot(result=str)
    @instrumented_slot
    def getBrowserPaneStatus(self) -> str:
        """Get the browser pane's current state.

        UI code should treat ``success=false`` as "pane not present" and
        simply not render its toggle, rather than reporting an error.

        Returns:
            JSON response with the controller's status dict, e.g.
            ``{'open': bool, 'url': str|null}``.
        """
        controller = self._get_browser_pane_controller()
        if controller is None:
            return serialize_response(False, error='browser pane not available')

        try:
            get_status = getattr(controller, 'get_status', None)
            if get_status is None:
                return serialize_response(
                    False,
                    error='browser pane controller does not support get_status',
                )
            result = get_status()
            if not isinstance(result, dict):
                result = {'open': bool(result)}
            return serialize_response(True, data=result)
        except Exception as e:
            self._log_error(f'getBrowserPaneStatus failed: {e}')
            return serialize_response(
                False, error=f'Failed to get browser pane status: {e}'
            )
