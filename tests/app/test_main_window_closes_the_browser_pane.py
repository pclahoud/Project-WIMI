"""``MainWindow.closeEvent`` tears the browser pane down (#153).

The pane's ``QWebEnginePage``s must be detached and deleted before its
persistent ``QWebEngineProfile`` is released. ``browser_pane.py``'s module
docstring and CLAUDE.md both said ``closeEvent`` called ``teardown()`` to
enforce that, and for the pane's whole life **nothing called it** --
``git log -S "browser_pane.teardown()"`` found no commit that ever added
the call. A documented invariant that two places assert and no code
implements is the thing this file exists to stop.

Why these tests and not a regression scenario:

- ``closeEvent`` is unreachable from ``tests/wimi_test``. The harness stops
  WIMI with ``WimiProcess.terminate()`` -> ``Popen.terminate()`` -> SIGTERM,
  which Qt does not handle, so the process dies without running a single
  widget's ``closeEvent``. A scenario could only assert that the *harness*
  can kill WIMI.
- ``closeEvent`` touches nothing Qt-specific: five attributes on ``self``
  and ``event.accept()``. So it is called here as an unbound function
  against recording stand-ins -- the same move the bridge tests make with
  ``DatabaseBridge`` and a fake controller, and it needs no
  ``QApplication``.

That ``teardown()`` in that order is what actually silences QtWebEngine is
a separate claim with separate evidence, in
``test_browser_pane_teardown_order.py``. This file only proves the call
happens, in the right order, on every path.
"""
import pytest

from app.main_window import MainWindow


class _RecordingPane:
    """Stands in for ``BrowserPaneController``.

    ``error`` makes ``teardown`` raise, which is the path that decides
    whether a failing pane can stop a window from closing.
    """

    def __init__(self, log: list, error: Exception | None = None):
        self._log = log
        self.error = error
        self.teardown_calls = 0

    def teardown(self):
        self.teardown_calls += 1
        self._log.append('teardown')
        if self.error:
            raise self.error


class _RecordingDb:
    def __init__(self, name: str, log: list):
        self.name = name
        self._log = log

    def close(self):
        self._log.append(f'close:{self.name}')


class _RecordingBridge:
    def __init__(self, log: list):
        self._log = log

    def teardownFolderSync(self):  # noqa: N802 (mirrors the bridge slot)
        self._log.append('foldersync')


class _RecordingEvent:
    def __init__(self, log: list):
        self._log = log
        self.accepted = False

    def accept(self):
        self.accepted = True
        self._log.append('accept')


class _RecordingLogger:
    def __init__(self):
        self.errors = []

    def error(self, message, context=None):
        self.errors.append((message, context))


_NO_PANE = object()


class _FakeWindow:
    """The attributes ``closeEvent`` reads, plus one ordered call log.

    ``pane=_NO_PANE`` leaves ``browser_pane`` undefined, which is what
    ``getattr`` in ``closeEvent`` has to survive.
    """

    def __init__(self, pane=_NO_PANE, logger=None):
        self.log: list[str] = []
        if pane is not _NO_PANE:
            self.browser_pane = pane
        self.db_bridge = _RecordingBridge(self.log)
        self.user_db = _RecordingDb('user', self.log)
        self.master_db = _RecordingDb('master', self.log)
        self.error_logger = logger


def _window_with_pane(error: Exception | None = None):
    log: list[str] = []
    pane = _RecordingPane(log, error=error)
    window = _FakeWindow(pane=pane)
    # One shared log so ordering is comparable across the parts.
    window.log = log
    window.db_bridge = _RecordingBridge(log)
    window.user_db = _RecordingDb('user', log)
    window.master_db = _RecordingDb('master', log)
    return window, pane


def _close(window) -> _RecordingEvent:
    event = _RecordingEvent(window.log)
    MainWindow.closeEvent(window, event)
    return event


# ==================== The call itself ====================


def test_close_tears_the_pane_down():
    window, pane = _window_with_pane()

    _close(window)

    assert pane.teardown_calls == 1, (
        'closeEvent must call BrowserPaneController.teardown() -- this is '
        'the call #153 found missing'
    )


def test_the_pane_is_torn_down_before_the_databases_close():
    """Ordering, not just presence.

    The pane's state saver writes through ``user_db.update_settings``, so
    anything the pane does on the way out has to happen while the database
    is still open. ``teardown()`` does not save state today; putting the
    call after the closes would make that an invisible constraint on
    whatever it does next.
    """
    window, _pane = _window_with_pane()

    _close(window)

    assert window.log.index('teardown') < window.log.index('close:user')
    assert window.log.index('teardown') < window.log.index('close:master')


# ==================== The pane is optional ====================


def test_a_window_with_no_pane_attribute_still_closes():
    """The pane is an optional feature and teardown must not assume it.

    ``BrowserPaneBridgeMixin`` reports ``browser pane not available`` when
    no controller is attached and pages hide their toggle on that string,
    so "no pane" is a supported state, not a broken one. A window whose
    construction failed before ``_setup_browser_pane`` is the other way to
    get here.
    """
    window = _FakeWindow()  # no browser_pane attribute at all

    event = _close(window)

    assert event.accepted is True
    assert window.log == ['foldersync', 'close:user', 'close:master', 'accept']


def test_a_none_pane_still_closes():
    window = _FakeWindow(pane=None)

    event = _close(window)

    assert event.accepted is True
    assert 'close:master' in window.log


# ==================== A failing teardown cannot wedge the close ============


def test_a_raising_teardown_does_not_stop_the_databases_closing():
    """A window that cannot close is worse than a mis-ordered release.

    Qt teardown is easy to turn into a crash on exit, and the cost of
    letting one propagate is concrete: the database closes below are what
    release the SQLite WAL handle, and a leaked handle keeps the profile
    file locked on Windows (#151).
    """
    logger = _RecordingLogger()
    window, pane = _window_with_pane(error=RuntimeError('boom'))
    window.error_logger = logger

    event = _close(window)

    assert pane.teardown_calls == 1
    assert event.accepted is True
    assert 'close:user' in window.log and 'close:master' in window.log
    assert len(logger.errors) == 1
    assert 'boom' in logger.errors[0][0]


def test_a_raising_teardown_with_no_error_logger_does_not_raise():
    """``error_logger`` is always set by ``__init__``, so this is cover for
    a half-constructed window rather than a reachable production state --
    but the handler is the one place that must not add a second failure to
    the first.
    """
    window, _pane = _window_with_pane(error=RuntimeError('boom'))
    window.error_logger = None

    event = _close(window)

    assert event.accepted is True


# ==================== Idempotence at this level ====================


def test_closing_twice_calls_teardown_twice_and_does_not_raise():
    """Qt can deliver a second close, and ``teardown()`` guards itself with
    ``_torn_down`` rather than relying on the caller. ``closeEvent`` must
    not add a guard of its own that would hide a genuine second pane.
    """
    window, pane = _window_with_pane()

    _close(window)
    _close(window)

    assert pane.teardown_calls == 2


if __name__ == '__main__':  # pragma: no cover
    pytest.main([__file__, '-v'])
