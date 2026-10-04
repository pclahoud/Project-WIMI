"""Child process for ``test_browser_pane_teardown_order.py`` (#153).

Builds a real ``BrowserPaneController`` with a real persistent
``QWebEngineProfile``, releases the profile, and reports how many times
QtWebEngine said *"Release of profile requested but WebEnginePage still not
deleted"*. ``argv[1]`` picks the order:

``no_teardown``
    release the profile with the pages still alive -- the NEGATIVE CONTROL.
    If this does not warn, the ``teardown`` run proves nothing.

``teardown``
    call ``BrowserPaneController.teardown()`` first (twice, so idempotence
    is on the same path), then release.

``inflight``
    start a navigation that cannot complete on every tab and tear down with
    the loads still pending, no event-loop turn in between.

Why a separate process rather than a test body:

- ``QtWebEngineWidgets`` must be imported before any ``QCoreApplication``
  exists, and a ``QApplication`` plus a Chromium render process is not
  something to leave standing in the middle of ``tests/app``.
- the warning arrives through Qt's message handler, which is process-global.
- the control deliberately provokes a state Qt calls "Expect troubles", and
  a crash here must cost a skip, not a corrupted pytest run.

The profile directory is always an explicit temporary directory. It must
never default: ``BrowserPaneController`` would otherwise create
``<app_data>/browser_pane/`` beside the student's real qbank session state.

Prints exactly one ``RESULT ...`` line on success. No ``RESULT`` line means
QtWebEngine could not start here, which the parent turns into a skip.
"""
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / 'src'))

# Before QApplication, deliberately: PyQt raises
# "QtWebEngineWidgets must be imported ... before a QCoreApplication
# instance is created" otherwise.
import PyQt6.QtWebEngineWidgets  # noqa: F401,E402
from PyQt6.QtCore import QObject, QTimer, QUrl, qInstallMessageHandler  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

WARNING_FRAGMENT = 'Release of profile requested'

_messages: list[str] = []


def _handler(_mode, _context, message):
    _messages.append(message)


def main() -> int:
    mode = sys.argv[1]
    qInstallMessageHandler(_handler)

    app = QApplication(sys.argv[:1])

    from app.browser_pane import BrowserPaneController  # noqa: PLC0415

    profile_dir = Path(tempfile.mkdtemp(prefix='wimi_pane_teardown_'))

    class _ParentWindow(QObject):
        """The controller only needs a QObject parent here; everything it
        would otherwise read off MainWindow is passed explicitly."""

    parent = _ParentWindow()
    controller = BrowserPaneController(
        parent,
        run_js_in_app=lambda _script: None,
        app_data_dir=profile_dir,
        profile_name='wimi_pane_teardown_probe',
    )
    controller.new_tab('about:blank')
    # Read the count before teardown: afterwards the views have no page.
    tab_count = controller.get_status()['tab_count']
    teardown_calls = 0

    def finish():
        nonlocal teardown_calls
        if mode == 'inflight':
            for index in range(controller._tabs.count()):
                view = controller._tabs.widget(index)
                # Discard-protocol port; the navigation stays pending.
                view.load(QUrl('http://127.0.0.1:9/never-answers'))
            # No processEvents() here: that is the point of this mode.
        if mode in ('teardown', 'inflight'):
            controller.teardown()
            teardown_calls += 1
            controller.teardown()  # must be a no-op, not a raise
            teardown_calls += 1
        app.processEvents()
        # The profile is parented to the controller, so deleting the
        # controller is what releases it.
        controller.deleteLater()
        parent.deleteLater()
        app.processEvents()
        app.quit()

    QTimer.singleShot(1500, finish)
    app.exec()
    app.processEvents()

    hits = sum(1 for m in _messages if WARNING_FRAGMENT in m)
    print(
        f"RESULT mode={mode} warnings={hits} tabs={tab_count} "
        f"teardown_calls={teardown_calls}",
        flush=True,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
