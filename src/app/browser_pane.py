"""Embedded browser pane: a second web view beside the app view.

A ``QWebEngineView`` living in the right half of ``MainWindow``'s
``QSplitter``, hidden until a page asks for it, with its own persistent
``QWebEngineProfile`` under ``<app_data>/browser_pane/`` so qbank logins
survive restarts, and a small toolbar (Back / URL bar / Go / "Chrome
mode" UA toggle / close).

WIMI never drives the site: the pane navigates only where the student
types or clicks. Nothing is read out of the page and nothing is
screenshotted — the pane is a browser, not an observer.

The bridge mixin delegates its pane slots to a controller attached to
the bridge instance. This module provides that controller; the protocol
the bridge expects is ``open_pane(url) -> dict``, ``close_pane() ->
dict``, ``get_status() -> dict``.

Teardown ordering: the pane's ``QWebEnginePage`` must be detached and
deleted *before* its profile is released, otherwise QtWebEngine warns
"Release of profile requested but WebEnginePage still not deleted.
Expect troubles!" on exit. ``MainWindow.closeEvent`` calls
:meth:`BrowserPaneController.teardown` to enforce this.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional, Union
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, Qt, QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QMenu,
    QTabWidget,
    QToolButton,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# Name of the pane's app_data subdirectory (cookie store + cache).
BROWSER_PROFILE_DIR_NAME = 'browser_pane'

# Event name the app page subscribes to on window.eventBus so its pane
# toggle button stays in sync. This is a contract with the frontend —
# do not rename without updating the subscriber.
PANE_STATE_EVENT = 'browser:pane_state'

DEFAULT_PANE_URL = 'about:blank'

# How many question-bank shortcuts sit on the toolbar before the rest
# overflow into a menu. Three keeps the address bar usable at the pane's
# minimum width; the row is ordered most-recently-opened first, so the
# one or two banks in daily rotation are the ones that stay visible.
MAX_SHORTCUT_BUTTONS = 3

# Zoom steps, as percentages. A question bank laid out for a full window
# sits in half of one, which is the constraint a side pane imposes and a
# full window does not. Stepped rather than free so the control is two
# buttons instead of a slider that needs a label to be readable.
ZOOM_STEPS = (50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200)
DEFAULT_ZOOM_PCT = 100

# Toolbar chrome stylesheet. One committed light-chrome look — browser
# chrome stays constant while page content varies, like any browser.
# Zoning is done by weight, not separators: ghost navigation, quiet
# meta controls. Every rule is scoped by objectName so nothing leaks
# into other Qt widgets.
_TOOLBAR_QSS = """
QWidget#paneToolbar {
    background-color: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
}
QPushButton#paneNavButton {
    background: transparent; border: none; border-radius: 5px;
    padding: 5px 9px; color: #334155; font-size: 12px;
}
QTabWidget#paneTabs::pane { border: none; }
QTabBar::tab {
    background: #0f172a; color: #94a3b8; border: none;
    padding: 4px 10px; font-size: 11px; max-width: 160px;
}
QTabBar::tab:selected { background: #1e293b; color: #e2e8f0; }
QTabBar::tab:hover { color: #e2e8f0; }

QPushButton#paneZoomLabel {
    background: transparent; color: #64748b; border: none;
    padding: 3px 4px; font-size: 11px; min-width: 34px;
}
QPushButton#paneZoomLabel:hover { color: #e2e8f0; }

QPushButton#paneShortcutButton {
    background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
    border-radius: 4px; padding: 3px 10px; font-size: 12px;
}
QPushButton#paneShortcutButton:hover { background: #334155; border-color: #475569; }
QToolButton#paneNavButton {
    background: transparent; color: #94a3b8; border: none;
    padding: 3px 6px; font-size: 13px;
}
QToolButton#paneNavButton:hover { color: #e2e8f0; }
QToolButton#paneNavButton::menu-indicator { image: none; }
QPushButton#paneNavButton:hover { background: #e2e8f0; }
QPushButton#paneNavButton:pressed { background: #cbd5e1; }
QLineEdit#paneAddress {
    background: white; color: #1e293b;
    border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 4px 10px; font-size: 12px;
    selection-background-color: #2563eb;
}
QLineEdit#paneAddress:focus { border: 1px solid #2563eb; }
QPushButton#paneCloseButton {
    background: transparent; border: none; border-radius: 5px;
    padding: 4px; color: #64748b;
}
QPushButton#paneCloseButton:hover { background: #e2e8f0; color: #1e293b; }
"""

# A current Chrome-on-Windows desktop UA (Chrome froze the minor/build
# segments years ago, so only the major version matters to sniffers).
# Offered because QtWebEngine's Chromium lags stable Chrome by roughly
# 6-18 months and some qbank auth providers block its default UA string.
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

# One-line note surfaced on first navigation to UWorld (risk table:
# "UWorld single-session bounce surprises students").
UWORLD_NOTE_TEXT = (
    'UWorld allows one active session — logging in here signs you out '
    'elsewhere.'
)

_SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*://')


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without Qt)
# ---------------------------------------------------------------------------


def normalize_url(raw: str) -> str:
    """Trim ``raw`` and auto-prefix ``https://`` when no scheme is given.

    Returns ``''`` for empty/whitespace input (callers decide the
    default; ``open_pane`` falls back to ``about:blank``).
    """
    raw = (raw or '').strip()
    if not raw:
        return ''
    if not _SCHEME_RE.match(raw):
        raw = 'https://' + raw
    return raw


def is_uworld_url(url: str) -> bool:
    """True when ``url``'s host is uworld.com or any subdomain of it."""
    try:
        host = urlparse(url or '').hostname or ''
    except ValueError:
        return False
    host = host.lower()
    return host == 'uworld.com' or host.endswith('.uworld.com')


def should_show_uworld_note(url: str, already_shown: bool) -> bool:
    """Whether the single-session note should appear for this navigation.

    Shown at most once per app run (``already_shown`` is the
    per-controller latch).
    """
    return (not already_shown) and is_uworld_url(url)


def _build_emit_script(payload: dict, event: str = PANE_STATE_EVENT) -> str:
    """Return the JS that emits ``event`` with ``payload`` on the app page.

    The payload is embedded as a *double-encoded* JSON string literal
    and revived with ``JSON.parse`` on the JS side:

    * the inner ``json.dumps`` serializes the payload to JSON text;
    * the outer ``json.dumps`` turns that text into a quoted,
      fully-escaped string literal (a JSON string literal is a valid JS
      string literal), which handles every embedding hazard at once —
      quotes and backslashes, newlines, and (thanks to
      ``ensure_ascii=True``) the U+2028/U+2029 line separators that are
      legal raw inside JSON strings but illegal inside JS string
      literals.

    Embedding raw ``json.dumps`` output as a JS object literal would be
    *almost* correct, and that "almost" (U+2028/U+2029) is exactly why
    the double-encoding form is used instead.
    """
    literal = json.dumps(json.dumps(payload, ensure_ascii=True),
                         ensure_ascii=True)
    return (
        '(function () {\n'
        f'    var payload = JSON.parse({literal});\n'
        f"    window.eventBus && window.eventBus.emit('{event}',"
        ' payload);\n'
        '})();'
    )


class _PanePage(QWebEnginePage):
    """The pane's page, with popups redirected into the pane itself.

    A single-view page returns None from ``createWindow``, so anything a
    site opens in a tab or popup silently does nothing: no new window, no
    error, no indication the click was received. That matters here
    because institutional and SSO sign-in flows routinely open a popup —
    the student would see a "Sign in with…" button that appears broken,
    with nothing in the log to explain it.

    There is nowhere to put a second window (the pane is one view in a
    splitter), so the honest behaviour is to load the request in this
    view instead. The student can come back with the Back button, which
    is a normal browser gesture, rather than being stuck.

    Returning ``self`` is what tells QtWebEngine to do that: the returned
    page receives the navigation.
    """

    def __init__(self, profile, parent, controller=None):
        super().__init__(profile, parent)
        self._controller = controller

    def createWindow(self, _type):  # noqa: N802 (Qt casing)
        """Open a site's popup as a real tab in this pane.

        A single-view page returns None here, so anything a site opened
        in a tab or popup silently did nothing: no window, no error, no
        log line. Institutional and SSO sign-in flows routinely use a
        popup, so the student met a "Sign in with..." button that simply
        appeared broken.

        Returning a NEW TAB's page is what those flows expect — they
        write into the opened window and often close it themselves — and
        it leaves the original page untouched underneath. Before tabs
        this returned ``self``, which loaded the popup over the top of
        whatever the student was reading.
        """
        if self._controller is not None:
            view = self._controller.new_tab(focus=True)
            if view is not None:
                return view.page()
        return self


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class BrowserPaneController(QObject):
    """Owns the browser pane: profile, view, toolbar, open/close state.

    Satisfies the pane-controller protocol the bridge mixin documents
    (``open_pane`` / ``close_pane`` / ``get_status``); ``MainWindow``
    attaches an instance to the bridge.

    Args:
        parent_window: The owning ``MainWindow``. Used as the QObject
            parent, and as the fallback source of ``app_data_dir``,
            ``error_logger`` and the app web view when those are not
            passed explicitly.
        run_js_in_app: How pane events reach the app page. Either a
            callable ``(script: str) -> None`` or an object with a
            ``.page()`` returning something with ``runJavaScript``
            (i.e. the main ``QWebEngineView``). When omitted, resolves
            ``parent_window.web_view.page()`` at call time so test
            mode's page swap can't leave a stale reference.
        error_logger: WIMI's ``ErrorLogger``; defaults to the parent
            window's. Stored for callers — the surviving pane code has
            no background paths of its own to log.
        app_data_dir: WIMI's resolved app_data root (already
            ``app_data_test`` in test mode — MainWindow receives the
            resolved path from ``app.main``). Defaults to
            ``parent_window.app_data_dir``. The pane's persistent
            profile lives in ``<app_data_dir>/browser_pane/``.
        profile_name: Storage name for the ``QWebEngineProfile``.
            Overridable so tests can give each controller a distinct
            name within one process.
    """

    # First-open split when no saved sizes exist: app view | pane.
    DEFAULT_SPLIT_PERCENT = (60, 40)

    # Explicit minimum pane width. Without it QSplitter uses the
    # toolbar layout's natural minimum, which on modest windows grew
    # past 40% as the toolbar gained controls — the splitter would then
    # refuse the 60/40 default and squeeze the app view instead. A
    # cramped (clipping) toolbar on narrow panes is the lesser evil
    # versus a pane that cannot shrink.
    MIN_PANE_WIDTH = 280

    def __init__(
        self,
        parent_window,
        run_js_in_app: Optional[Union[Callable[[str], None], object]] = None,
        error_logger=None,
        app_data_dir: Optional[Union[str, Path]] = None,
        profile_name: str = 'wimi_browser_pane',
    ):
        super().__init__(parent_window)

        self._parent_window = parent_window
        self.error_logger = (
            error_logger if error_logger is not None
            else getattr(parent_window, 'error_logger', None)
        )

        # Resolve the app page lazily by default: test mode swaps the
        # view's page after construction, and a captured reference
        # would go stale.
        if run_js_in_app is None:
            def run_js_in_app(script):
                parent_window.web_view.page().runJavaScript(script)
        self._run_js_in_app_target = run_js_in_app

        if app_data_dir is None:
            app_data_dir = getattr(parent_window, 'app_data_dir', None)
        if app_data_dir is None:
            raise ValueError(
                'BrowserPaneController needs app_data_dir (explicitly, or '
                'as parent_window.app_data_dir)'
            )
        self._profile_dir = Path(app_data_dir) / BROWSER_PROFILE_DIR_NAME
        self._profile_dir.mkdir(parents=True, exist_ok=True)

        # Persistent named profile: explicit storage/cache paths plus
        # ForcePersistentCookies so qbank logins survive restarts.
        # Parented to the controller so it outlives the page — see
        # teardown() for the ordering fix.
        self._profile = QWebEngineProfile(profile_name, self)
        self._profile.setPersistentStoragePath(
            str(self._profile_dir / 'storage')
        )
        self._profile.setCachePath(str(self._profile_dir / 'cache'))
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        self._default_ua = self._profile.httpUserAgent()
        # The UA override defaults ON (spike finding: some qbank auth
        # providers block the default QtWebEngine UA). QtWebEngine
        # applies the profile UA to *subsequent* requests only, so it
        # must be set here, before anything loads; _on_ua_toggled()
        # reloads the page for later toggles.
        self._profile.setHttpUserAgent(CHROME_UA)

        # Mirrors the profile's user agent, which is set to CHROME_UA
        # just above. Per-source from here on: opening a shortcut applies
        # that source's setting.
        self._desktop_site = True

        # Injected by MainWindow. Resolved at call time, never cached:
        # the user database changes on profile switch, and a captured
        # reference would keep serving the previous student's banks.
        self._sources_provider = None
        self._on_source_opened = None

        # Pane state the student never sets directly: restored on open,
        # saved as it changes. Supplied by MainWindow, same call-time
        # resolution as the sources provider.
        self._state_provider = None
        self._state_saver = None
        self._zoom_pct = DEFAULT_ZOOM_PCT

        # Built by _build_widget below; declared here so refresh_shortcuts
        # is safe to call at any point in construction.
        self._shortcut_box = None
        self._shortcut_bar = None
        self._zoom_label = None
        self._tabs = None

        self._splitter: Optional[QSplitter] = None
        self._saved_splitter_sizes: Optional[list] = None
        self._uworld_note_shown = False
        self._torn_down = False

        self._build_widget()

    # ------------------------------------------------------------- widget

    def _build_widget(self) -> None:
        self._widget = QWidget()
        # See MIN_PANE_WIDTH: an explicit minimum overrides the toolbar
        # layout's natural minimum in QSplitter's size negotiation.
        self._widget.setMinimumWidth(self.MIN_PANE_WIDTH)
        outer = QVBoxLayout(self._widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Toolbar row --------------------------------------------------
        # Qt-side chrome, not themed web CSS (the web theme variables
        # only apply inside src/web). Styled by _TOOLBAR_QSS above.
        toolbar = QWidget(self._widget)
        toolbar.setObjectName('paneToolbar')
        toolbar.setStyleSheet(_TOOLBAR_QSS)
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(8, 6, 8, 6)
        bar.setSpacing(8)

        self._back_btn = QPushButton('←', toolbar)
        self._back_btn.setObjectName('paneNavButton')
        self._back_btn.setToolTip('Back')
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.clicked.connect(self._go_back)
        bar.addWidget(self._back_btn)

        # Reload was missing entirely. On a qbank you page through
        # questions, it is the button wanted most often.
        self._reload_btn = QPushButton('↻', toolbar)
        self._reload_btn.setObjectName('paneNavButton')
        self._reload_btn.setToolTip('Reload')
        self._reload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reload_btn.clicked.connect(lambda: self._view.reload())
        bar.addWidget(self._reload_btn)

        self._zoom_out_btn = QPushButton('−', toolbar)
        self._zoom_out_btn.setObjectName('paneNavButton')
        self._zoom_out_btn.setToolTip('Zoom out')
        self._zoom_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_out_btn.clicked.connect(lambda: self._step_zoom(-1))
        bar.addWidget(self._zoom_out_btn)

        # Shows the level AND resets it on click: at 100% there is
        # nothing to read, and at 125% the number is the only way to know
        # why the page looks different from the app beside it.
        self._zoom_label = QPushButton('100%', toolbar)
        self._zoom_label.setObjectName('paneZoomLabel')
        self._zoom_label.setToolTip('Reset zoom to 100%')
        self._zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_label.clicked.connect(lambda: self._set_zoom(DEFAULT_ZOOM_PCT))
        bar.addWidget(self._zoom_label)

        self._zoom_in_btn = QPushButton('+', toolbar)
        self._zoom_in_btn.setObjectName('paneNavButton')
        self._zoom_in_btn.setToolTip('Zoom in')
        self._zoom_in_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_in_btn.clicked.connect(lambda: self._step_zoom(1))
        bar.addWidget(self._zoom_in_btn)

        # --- Question bank shortcuts ---------------------------------
        # Populated from the student's sources on every open, so the row
        # reflects what they actually study without being a second list
        # to curate. Held in its own container so refresh_shortcuts()
        # can rebuild it without touching the rest of the toolbar.
        self._shortcut_box = QWidget(toolbar)
        self._shortcut_bar = QHBoxLayout(self._shortcut_box)
        self._shortcut_bar.setContentsMargins(0, 0, 0, 0)
        self._shortcut_bar.setSpacing(4)
        bar.addWidget(self._shortcut_box)

        self._url_bar = QLineEdit(toolbar)
        self._url_bar.setObjectName('paneAddress')
        self._url_bar.setPlaceholderText(
            "Your qbank's address — uworld.com, amboss.com…"
        )
        self._url_bar.returnPressed.connect(self._navigate)
        bar.addWidget(self._url_bar, 1)

        go_btn = QPushButton('Go', toolbar)
        go_btn.setObjectName('paneNavButton')
        go_btn.setToolTip('Open the address')
        go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        go_btn.clicked.connect(self._navigate)
        bar.addWidget(go_btn)

        # '+ Tab', not '+'. The zoom control a few widgets to the left is
        # also a '+' with the same styling, so a bare plus here was two
        # identical buttons doing unrelated things. The toolbar already
        # labels its actions in words ('Go'), so a word fits the row.
        self._new_tab_btn = QPushButton('+ Tab', toolbar)
        self._new_tab_btn.setObjectName('paneNavButton')
        self._new_tab_btn.setToolTip('Open a new tab in this pane')
        self._new_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_tab_btn.clicked.connect(lambda: self.new_tab())
        bar.addWidget(self._new_tab_btn)

        self._close_btn = QPushButton('✕', toolbar)
        self._close_btn.setObjectName('paneCloseButton')
        self._close_btn.setToolTip(
            'Close the browser pane (keeps your page and login)'
        )
        self._close_btn.setFixedWidth(28)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.close_pane)
        bar.addWidget(self._close_btn)

        outer.addWidget(toolbar)

        # --- First-use UWorld note bar (hidden until triggered) -----------
        self._note_bar = QWidget(self._widget)
        self._note_bar.setStyleSheet(
            'background-color: #fff3cd; color: #664d03;'
        )
        note_layout = QHBoxLayout(self._note_bar)
        note_layout.setContentsMargins(8, 4, 8, 4)
        self._note_label = QLabel(UWORLD_NOTE_TEXT, self._note_bar)
        self._note_label.setWordWrap(True)
        note_layout.addWidget(self._note_label, 1)
        dismiss_btn = QPushButton('Dismiss', self._note_bar)
        dismiss_btn.clicked.connect(self._note_bar.hide)
        note_layout.addWidget(dismiss_btn)
        self._note_bar.hide()
        outer.addWidget(self._note_bar)

        # --- Web view -----------------------------------------------------
        # The page is built explicitly against the pane's own persistent
        # profile; a default-constructed page would use the global
        # profile and lose the qbank cookie store.
        # A QTabWidget whose bar hides at one tab, so the ordinary
        # single-bank case looks exactly as it did before tabs and costs
        # no vertical space in an already narrow pane.
        self._tabs = QTabWidget(self._widget)
        self._tabs.setObjectName('paneTabs')
        self._tabs.setDocumentMode(True)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabBar().setVisible(False)
        outer.addWidget(self._tabs, 1)

        self.new_tab()

        # Hidden until open_pane(); explicit hide so isHidden() is the
        # authoritative "pane open?" flag even before the widget is
        # parented into the window's splitter.
        self._widget.hide()

    # ----------------------------------------------------------------- tabs

    @property
    def _view(self):
        """The active tab's view.

        A property rather than a field so every existing caller —
        navigation, zoom, reload, status — keeps working against
        "the page the student is looking at" without knowing about tabs.
        """
        return self._tabs.currentWidget() if self._tabs is not None else None

    def new_tab(self, url: str = '', focus: bool = True):
        """Add a tab and return its view.

        With no url the tab lands on the default question bank, not
        blank: a new tab is an intent to go somewhere, and the bank the
        student nominated is the only sensible guess. It deliberately
        does NOT honour 'where I left off' — that would duplicate the
        tab they are already on.
        """
        view = QWebEngineView(self._tabs)
        page = _PanePage(self._profile, view, controller=self)
        view.setPage(page)
        view.urlChanged.connect(
            lambda u, v=view: self._on_view_url_changed(v, u)
        )
        view.titleChanged.connect(
            lambda t, v=view: self._on_view_title_changed(v, t)
        )
        # Zoom is per-view, so a new tab inherits the pane's current
        # level rather than silently reverting to 100%.
        view.setZoomFactor(self._zoom_pct / 100.0)

        index = self._tabs.addTab(view, 'New tab')
        self._sync_tab_bar()
        if focus:
            self._tabs.setCurrentIndex(index)

        target = normalize_url(url) or self._new_tab_url()
        view.load(QUrl(target))
        return view

    def _new_tab_url(self) -> str:
        """Where a new tab lands: the nominated bank, else blank."""
        state = self._read_state()
        wanted = state.get('default_source_id')
        if wanted is not None and self._sources_provider is not None:
            try:
                for src in self._sources_provider() or []:
                    if src.get('id') == wanted:
                        return normalize_url(src.get('url') or '') or DEFAULT_PANE_URL
            except Exception:  # noqa: BLE001
                pass
        return DEFAULT_PANE_URL

    def _close_tab(self, index: int) -> None:
        """Close one tab; closing the last one closes the pane.

        An empty tabbed pane is a dead rectangle taking half the window,
        so there is no such state — the pane's own X and closing the
        final tab mean the same thing.
        """
        view = self._tabs.widget(index)
        if view is None:
            return
        if self._tabs.count() <= 1:
            self.close_pane()
            return
        self._tabs.removeTab(index)
        view.setPage(None)
        view.deleteLater()
        self._sync_tab_bar()

    def _sync_tab_bar(self) -> None:
        self._tabs.tabBar().setVisible(self._tabs.count() > 1)

    def _on_tab_changed(self, _index: int) -> None:
        """Point the address bar at whichever tab is now in front."""
        view = self._view
        if view is not None:
            self._url_bar.setText(view.url().toString())

    def _on_view_title_changed(self, view, title: str) -> None:
        index = self._tabs.indexOf(view)
        if index < 0:
            return
        text = (title or 'New tab').strip() or 'New tab'
        self._tabs.setTabText(index, text[:24])
        self._tabs.setTabToolTip(index, text)

    def _on_view_url_changed(self, view, url: QUrl) -> None:
        """Only the ACTIVE tab may drive the address bar.

        Without the guard a background tab finishing a redirect rewrites
        the address bar under the student while they are reading a
        different page.
        """
        if view is not self._view:
            return
        self._on_url_changed(url)

    def set_state_provider(self, provider, saver=None) -> None:
        """Supply the pane's remembered state and a way to save it.

        ``provider()`` returns a dict of ``open_mode``, ``default_source_id``,
        ``last_url``, ``split_app_pct`` and ``zoom_pct``. ``saver(**fields)``
        persists whichever of those changed.

        Callables, not data, for the same reason as the sources provider:
        the pane outlives a profile switch.
        """
        self._state_provider = provider
        self._state_saver = saver
        self._restore_zoom()

    def _opening_url(self) -> str:
        """Where a first open lands, per the student's open-mode setting.

        Every branch falls back to ``DEFAULT_PANE_URL`` rather than
        failing: 'source' can name a bank that has since been deleted or
        had its address cleared, and 'last' has nothing to reopen on a
        first run. A blank pane is a recoverable state — the shortcut
        row is right there — where an error dialog on open is not.
        """
        state = self._read_state()
        mode = state.get('open_mode') or 'last'

        if mode == 'blank':
            return DEFAULT_PANE_URL

        if mode == 'source':
            wanted = state.get('default_source_id')
            if wanted is not None and self._sources_provider is not None:
                try:
                    for src in self._sources_provider() or []:
                        if src.get('id') == wanted:
                            url = normalize_url(src.get('url') or '')
                            if url:
                                self._apply_desktop_site(
                                    bool(src.get('desktop_site')), reload=False
                                )
                                return url
                except Exception:  # noqa: BLE001
                    pass
            return DEFAULT_PANE_URL

        return normalize_url(state.get('last_url') or '') or DEFAULT_PANE_URL

    def _read_state(self) -> dict:
        if self._state_provider is None:
            return {}
        try:
            return dict(self._state_provider() or {})
        except Exception:  # noqa: BLE001 — chrome must not break on data
            return {}

    def _save_state(self, **fields) -> None:
        if self._state_saver is None:
            return
        try:
            self._state_saver(**fields)
        except Exception:  # noqa: BLE001 — remembering is not worth a crash
            pass

    def _restore_zoom(self) -> None:
        pct = self._read_state().get('zoom_pct') or DEFAULT_ZOOM_PCT
        self._set_zoom(int(pct), save=False)

    def _step_zoom(self, direction: int) -> None:
        """Move one step along ZOOM_STEPS, clamped at both ends.

        Finds the nearest step rather than assuming the current value is
        one of them: a level restored from a database written by a
        future version with different steps must still be adjustable.
        """
        nearest = min(
            range(len(ZOOM_STEPS)),
            key=lambda i: abs(ZOOM_STEPS[i] - self._zoom_pct),
        )
        idx = max(0, min(len(ZOOM_STEPS) - 1, nearest + direction))
        self._set_zoom(ZOOM_STEPS[idx])

    def _set_zoom(self, pct: int, save: bool = True) -> None:
        pct = max(ZOOM_STEPS[0], min(ZOOM_STEPS[-1], int(pct)))
        self._zoom_pct = pct
        self._view.setZoomFactor(pct / 100.0)
        if self._zoom_label is not None:
            self._zoom_label.setText(f'{pct}%')
        if save:
            self._save_state(pane_zoom_pct=pct)

    def set_sources_provider(self, provider, on_opened=None) -> None:
        """Supply the question banks the shortcut row offers.

        ``provider()`` returns the list ``get_pane_sources()`` produces:
        dicts of ``id``, ``source_name``, ``url`` and ``desktop_site``,
        most-recently-opened first. ``on_opened(source_id)`` records a
        click so that ordering keeps up.

        Both are callables rather than data because the pane outlives a
        profile switch.
        """
        self._sources_provider = provider
        self._on_source_opened = on_opened
        self.refresh_shortcuts()

    def refresh_shortcuts(self) -> None:
        """Rebuild the shortcut row from the current sources.

        Called on every open rather than once at construction: a source
        gains a button the moment its address is filled in, without
        restarting the app.
        """
        if self._shortcut_bar is None:
            return

        while self._shortcut_bar.count():
            item = self._shortcut_bar.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        sources = []
        if self._sources_provider is not None:
            try:
                sources = list(self._sources_provider() or [])
            except Exception:  # noqa: BLE001 — chrome must not break on data
                sources = []

        for src in sources[:MAX_SHORTCUT_BUTTONS]:
            self._shortcut_bar.addWidget(self._make_shortcut_button(src))

        overflow = sources[MAX_SHORTCUT_BUTTONS:]
        if overflow:
            more = QToolButton(self._shortcut_box)
            more.setObjectName('paneNavButton')
            more.setText('⋯')
            more.setToolTip('More question banks')
            more.setCursor(Qt.CursorShape.PointingHandCursor)
            more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(more)
            for src in overflow:
                action = menu.addAction(src.get('source_name') or 'Untitled')
                action.triggered.connect(
                    lambda _checked=False, s=src: self.open_source(s)
                )
            more.setMenu(menu)
            self._shortcut_bar.addWidget(more)

        self._shortcut_box.setVisible(bool(sources))

    def _make_shortcut_button(self, src: dict) -> QPushButton:
        name = src.get('source_name') or 'Untitled'
        btn = QPushButton(name, self._shortcut_box)
        btn.setObjectName('paneShortcutButton')
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(f"Open {name} — {src.get('url') or ''}".strip(' —'))
        btn.clicked.connect(lambda _checked=False, s=src: self.open_source(s))
        return btn

    def open_source(self, src: dict) -> None:
        """Open one question bank, honouring its own desktop-site setting.

        The user agent is applied WITHOUT a reload, because the load on
        the next line picks it up — reloading here would fetch the page
        twice and, on a site mid-login, can lose the redirect.
        """
        url = normalize_url(src.get('url') or '')
        if not url:
            return
        self._apply_desktop_site(bool(src.get('desktop_site')), reload=False)
        self._show_widget()
        # Reuse the current tab or open a new one, per the student's
        # setting. Reusing is the default: switching banks is the common
        # case, and accumulating a tab per click is not what "switch to
        # AMBOSS" means.
        if self._read_state().get('shortcut_opens') == 'new':
            self.new_tab(url)
        else:
            self._view.load(QUrl(url))
        source_id = src.get('id')
        if self._on_source_opened is not None and source_id is not None:
            try:
                self._on_source_opened(source_id)
            except Exception:  # noqa: BLE001 — ordering is not worth a crash
                pass
        self.refresh_shortcuts()

    def widget(self) -> QWidget:
        """The pane widget (toolbar + note bar + web view)."""
        return self._widget

    def attach_to_splitter(self, splitter: QSplitter) -> None:
        """Add the (hidden) pane widget to the window's splitter.

        The controller manages the splitter sizes itself: first open
        applies the 60/40 default, and sizes are saved on close /
        restored on reopen so the split survives toggling within a run.
        """
        self._splitter = splitter
        splitter.addWidget(self._widget)
        self._widget.hide()

    # ------------------------------------------------- controller protocol

    def open_pane(self, url: str = '') -> dict:
        """Show the pane and navigate it.

        With an empty ``url``: a fresh pane loads ``about:blank``, but a
        pane that already has a page keeps it — reopening mid-session
        must not throw away the student's place (or their login flow).
        Explicit URLs are normalized (https:// auto-prefix) and always
        loaded.
        """
        target = normalize_url(url)
        # A source whose address was filled in since the last open should
        # have a button now, without an app restart.
        self.refresh_shortcuts()
        self._restore_zoom()
        self._show_widget()
        if target:
            self._view.load(QUrl(target))
        elif not self._has_loaded_page():
            # Nothing loaded yet, so this is the first open of the run and
            # the student's open-mode preference decides where to land.
            # A pane that already has a page keeps it: reopening
            # mid-session must not throw away their place.
            self._view.load(QUrl(self._opening_url()))
        self._notify_pane_state()
        return self.get_status()

    def close_pane(self) -> dict:
        """Hide the pane.

        Saves the splitter sizes first so reopening restores the split.
        The web view keeps its page — closing the pane is a visibility
        toggle, not a session teardown.
        """
        if not self._widget.isHidden():
            if self._splitter is not None:
                sizes = self._splitter.sizes()
                if any(sizes):
                    self._saved_splitter_sizes = list(sizes)
                    # Also persist it, as the APP's share in percent.
                    # Percent rather than pixels because the window is a
                    # different size on the next run, and the app's share
                    # rather than the pane's so the number still reads
                    # correctly if MIN_PANE_WIDTH ever changes.
                    total = sum(sizes)
                    if total > 0:
                        self._save_state(
                            pane_split_app_pct=round(sizes[0] * 100 / total)
                        )
            self._widget.hide()
            self._notify_pane_state()
        return self.get_status()

    def _notify_pane_state(self) -> None:
        """Tell the app page the pane's open state changed.

        Emits ``browser:pane_state`` with ``{open: bool}`` so the app
        page's toggle button stays in sync no matter which side changed
        the state — the JS button or the pane's own close button.
        """
        script = _build_emit_script(
            {'open': not self._widget.isHidden()}, event=PANE_STATE_EVENT
        )
        self._run_js_in_app(script)

    def get_status(self) -> dict:
        """Pane state dict.

        Carries both the minimal keys the bridge docstring shows
        (``open``/``url``) and the richer aliases
        (``visible``/``current_url``) plus ``profile_dir`` and
        ``ua_override`` for diagnostics. Additive only — the bridge
        passes the dict through as-is.
        """
        visible = not self._widget.isHidden()
        url = self._view.url().toString()
        return {
            'open': visible,
            'visible': visible,
            'url': url,
            'current_url': url,
            'profile_dir': str(self._profile_dir),
            'desktop_site': self._desktop_site,
            'tab_count': self._tabs.count() if self._tabs else 0,
        }

    def _run_js_in_app(self, script: str) -> None:
        target = self._run_js_in_app_target
        if callable(target):
            target(script)
        else:
            target.page().runJavaScript(script)

    # ---------------------------------------------------------- navigation

    def _go_back(self) -> None:
        self._view.back()

    def _navigate(self) -> None:
        target = normalize_url(self._url_bar.text())
        if not target:
            return
        self._view.load(QUrl(target))

    def _apply_desktop_site(self, enabled: bool, reload: bool = True) -> None:
        """Send a desktop user agent, or don't, for what loads next.

        QtWebEngine applies the profile's HTTP user agent to
        *subsequent* requests only, so a change mid-page needs a reload
        to take effect — already-running JS keeps reporting the old
        navigator.userAgent until then. When this is called immediately
        before a load, pass ``reload=False``: the load itself picks up
        the new agent and a reload would fetch the page twice.
        """
        if enabled == self._desktop_site:
            return
        self._desktop_site = enabled
        self._profile.setHttpUserAgent(
            CHROME_UA if enabled else self._default_ua
        )
        if reload:
            self._view.reload()

    def _on_url_changed(self, url: QUrl) -> None:
        text = url.toString()
        self._url_bar.setText(text)
        self._maybe_show_uworld_note(text)
        # Remembered for 'last' mode. about:blank is skipped: reopening
        # onto a blank page is what the setting exists to avoid.
        if text and text != DEFAULT_PANE_URL:
            self._save_state(pane_last_url=text)

    def _maybe_show_uworld_note(self, url: str) -> None:
        if should_show_uworld_note(url, self._uworld_note_shown):
            # Latch immediately: once per app run, whether or not the
            # student dismisses it.
            self._uworld_note_shown = True
            self._note_bar.show()

    # -------------------------------------------------------------- layout

    def _has_loaded_page(self) -> bool:
        current = self._view.url().toString()
        return bool(current) and current != DEFAULT_PANE_URL

    def _show_widget(self) -> None:
        was_hidden = self._widget.isHidden()
        self._widget.show()
        if self._splitter is None or not was_hidden:
            return
        # In-run sizes win: they are what the student dragged a moment
        # ago, in this window's actual pixels.
        if self._saved_splitter_sizes:
            self._splitter.setSizes(self._saved_splitter_sizes)
            return
        total = sum(self._splitter.sizes()) or self._splitter.width()
        if total <= 0:
            return
        # Otherwise the split remembered from a previous run, falling
        # back to the default. Previously in-memory only, so a split set
        # deliberately survived closing the pane but not restarting.
        pct = self._read_state().get('split_app_pct')
        if not isinstance(pct, int) or not (10 <= pct <= 90):
            pct = self.DEFAULT_SPLIT_PERCENT[0]
        app_share = total * pct // 100
        self._splitter.setSizes([app_share, total - app_share])

    # ------------------------------------------------------------ teardown

    def teardown(self) -> None:
        """Release the page before the profile (call on app close).

        The ``QWebEnginePage`` must be detached from the view and
        deleted before its ``QWebEngineProfile`` is released, otherwise
        QtWebEngine warns "Release of profile requested but
        WebEnginePage still not deleted. Expect troubles!" on exit.
        Safe to call more than once.
        """
        if self._torn_down:
            return
        self._torn_down = True
        # Every tab's page, not just the visible one: the warning fires
        # for any page still alive when the profile goes, and with tabs
        # there can be several.
        for index in range(self._tabs.count() if self._tabs else 0):
            view = self._tabs.widget(index)
            if view is None:
                continue
            page = view.page()
            view.setPage(None)
            if page is not None:
                page.deleteLater()
