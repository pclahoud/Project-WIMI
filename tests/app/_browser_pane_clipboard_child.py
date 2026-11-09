"""Child process for test_browser_pane_clipboard.py. Not a test module.

Builds the real ``BrowserPaneController`` in a bare window, serves one local
page with a Copy button that calls ``navigator.clipboard.writeText``, clicks
it with real mouse events (the clipboard API needs a user gesture), and
prints one ``RESULT`` line as JSON.

``mode`` is ``handler`` (the shipped page) or ``no_handler`` (the page's
permission handler disconnected: the negative control, which must reproduce
the pre-fix hang), or ``link_menu``: select a paragraph, right-click the
link inside it, and report the stock menu and the pane's menu.
"""
import functools
import http.server
import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

import PyQt6.QtWebEngineWidgets  # noqa: F401  (must precede QApplication)
from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QSplitter, QWidget

PAGE = b"""<!doctype html><html><body style="margin:0">
<button id="b" style="position:absolute;left:0;top:0;width:120px;height:40px">Copy</button>
<script>
window.r = 'not clicked';
b.onclick = () => { window.r = 'pending';
  navigator.clipboard.writeText('COPIED_BY_THE_SITE').then(
    () => { window.r = 'ok'; }, e => { window.r = 'rejected: ' + e.name; }); };
</script></body></html>"""

LINK_PAGE = b"""<!doctype html><html><body style="margin:0;font-size:20px">
<p id="p" style="position:absolute;left:0;top:0;width:600px">Mitochondria are
<a id="a" href="/elsewhere">organelles</a> found in most cells.</p>
</body></html>"""


def main(mode: str) -> None:
    app = QApplication(sys.argv[:1])
    from app.browser_pane import BrowserPaneController

    site = Path(tempfile.mkdtemp())
    (site / 'copy.html').write_bytes(PAGE)
    (site / 'link.html').write_bytes(LINK_PAGE)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    name = 'link.html' if mode == 'link_menu' else 'copy.html'
    url = f'http://127.0.0.1:{server.server_port}/{name}'

    window = QMainWindow()
    window.resize(1200, 800)
    splitter = QSplitter(window)
    splitter.addWidget(QWidget())
    window.setCentralWidget(splitter)
    window.show()
    controller = BrowserPaneController(
        window, run_js_in_app=lambda s: None, app_data_dir=tempfile.mkdtemp())
    controller.attach_to_splitter(splitter)
    controller.open_pane(url)

    def view():
        return controller._view

    def finish(state):
        print('RESULT ' + json.dumps({
            'mode': mode, 'page': state, 'clipboard': QApplication.clipboard().text(),
        }), flush=True)
        controller.teardown()
        QTimer.singleShot(300, app.quit)

    def click():
        page = view().page()
        if mode == 'no_handler':
            page.permissionRequested.disconnect(page._on_permission_requested)
        QApplication.clipboard().setText('SENTINEL')
        target = view().focusProxy() or view()
        point = QPointF(60, 20)
        for kind, buttons in (
            (QMouseEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(target, QMouseEvent(
                kind, point, point, Qt.MouseButton.LeftButton, buttons,
                Qt.KeyboardModifier.NoModifier))
        QTimer.singleShot(2000, lambda: view().page().runJavaScript('window.r', finish))

    def link_menu():
        page = view().page()
        page.runJavaScript(
            "(()=>{const r=document.createRange();r.selectNodeContents(document.getElementById('p'));"
            "const s=getSelection();s.removeAllRanges();s.addRange(r);"
            "const b=document.getElementById('a').getBoundingClientRect();return [b.x+5,b.y+5]})()",
            right_click)

    def right_click(xy):
        target = view().focusProxy() or view()
        point = QPointF(xy[0], xy[1])
        for kind, buttons in (
            (QMouseEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton),
            (QMouseEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(target, QMouseEvent(
                kind, point, point, Qt.MouseButton.RightButton, buttons,
                Qt.KeyboardModifier.NoModifier))
        QTimer.singleShot(600, report_menu)

    def report_menu():
        import gc
        from PyQt6.QtWebEngineCore import QWebEnginePage
        gc.collect()   # a menu nothing references must not survive this
        popup = QApplication.activePopupWidget()
        shown = popup is not None and popup.isVisible()
        shown_actions = [a.text() for a in popup.actions()] if shown else []
        if popup is not None:
            popup.close()
        request = view().lastContextMenuRequest()
        copy = view().pageAction(QWebEnginePage.WebAction.Copy)
        stock = view().createStandardContextMenu()
        ours = view().build_context_menu()
        print('RESULT ' + json.dumps({
            'mode': mode,
            'on_link': bool(request and request.linkUrl().toString()),
            'has_selection': view().hasSelection(),
            'stock_has_copy': copy in stock.actions(),
            'pane_has_copy': copy in ours.actions(),
            'pane_first_is_copy': bool(ours.actions()) and ours.actions()[0] is copy,
            'menu_shown': shown,
            'shown_first': shown_actions[0] if shown_actions else None,
        }), flush=True)
        controller.teardown()
        QTimer.singleShot(300, app.quit)

    def wait_for_load(tries=[0]):
        tries[0] += 1
        if view() is not None and view().page().url().toString() == url:
            QTimer.singleShot(1200, link_menu if mode == 'link_menu' else click)
        elif tries[0] < 100:
            QTimer.singleShot(200, wait_for_load)

    QTimer.singleShot(500, wait_for_load)
    QTimer.singleShot(60_000, app.quit)
    app.exec()


if __name__ == '__main__':
    main(sys.argv[1])
