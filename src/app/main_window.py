"""
Main Application Window for WIMI
PyQt6 window with embedded QWebEngineView for the UI
"""

import os
import sys
from pathlib import Path
from typing import Optional


def get_resource_path(relative_path: str) -> Path:
    """
    Get absolute path to a resource, works for dev and PyInstaller.
    
    In development: paths are relative to the src directory.
    In frozen mode: paths are relative to the executable directory.
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        base_path = Path(sys.executable).parent
    else:
        # Running in development
        base_path = Path(__file__).parent.parent
    
    return base_path / relative_path

from PyQt6.QtWidgets import (
    QMainWindow, QVBoxLayout, QWidget, QApplication,
    QMenuBar, QMenu, QStatusBar, QMessageBox, QFileDialog
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, Qt, QSize
from PyQt6.QtGui import QAction, QKeySequence, QShortcut, QIcon

from app.bridge import DatabaseBridge
from app.media_manager import MediaManager
from app.media_scheme_handler import MediaSchemeHandler, install_scheme_handler
from database import MasterDatabase, UserDatabase
from app_logging import ErrorLogger, JavaScriptErrorBridge


class WIMIWebPage(QWebEnginePage):
    """Custom web page to handle JavaScript console messages"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def javaScriptConsoleMessage(self, level, message, line, source):
        """Capture JavaScript console messages for debugging"""
        level_names = {0: 'INFO', 1: 'WARNING', 2: 'ERROR'}
        level_name = level_names.get(level, 'DEBUG')
        print(f"[JS {level_name}] {source}:{line} - {message}")


class MainWindow(QMainWindow):
    """
    Main application window with embedded web view.
    
    Features:
    - QWebEngineView for rendering HTML/CSS/JS UI
    - WebChannel bridge for Python-JavaScript communication
    - Hot reload capability (F5)
    - Menu bar with common actions
    - Status bar for feedback
    - Error logging integration
    """
    
    def __init__(
        self,
        master_db: Optional[MasterDatabase] = None,
        user_db: Optional[UserDatabase] = None,
        error_logger: Optional[ErrorLogger] = None,
        dev_mode: bool = True,
        app_data_dir: Optional[Path] = None,
        plugin_manager=None
    ):
        super().__init__()

        self.master_db = master_db
        self.user_db = user_db
        self.error_logger = error_logger or ErrorLogger(mode='development' if dev_mode else 'production')
        self.dev_mode = dev_mode
        self.app_data_dir = app_data_dir or Path(__file__).parent.parent.parent / 'app_data'
        self.plugin_manager = plugin_manager
        
        # Media manager (will be initialized when user_db is set)
        self.media_manager: Optional[MediaManager] = None
        self.media_scheme_handler: Optional[MediaSchemeHandler] = None
        
        # Path configuration - handles both dev and frozen modes
        self.is_frozen = getattr(sys, 'frozen', False)
        if self.is_frozen:
            # PyInstaller sets sys._MEIPASS to the temp/data directory
            # This works on both Windows (_internal/) and macOS (.app bundle)
            self.src_dir = Path(sys.executable).parent
            self.web_dir = Path(sys._MEIPASS) / 'web'
            print(f"[FROZEN] Executable: {sys.executable}")
            print(f"[FROZEN] _MEIPASS: {sys._MEIPASS}")
            print(f"[FROZEN] Web dir: {self.web_dir}")
            print(f"[FROZEN] Web dir exists: {self.web_dir.exists()}")
        else:
            self.src_dir = Path(__file__).parent.parent
            self.web_dir = self.src_dir / 'web'
        self.static_dir = self.web_dir
        
        # Initialize UI components
        self._setup_window()
        self._setup_web_view()
        self._setup_web_channel()
        self._setup_media_handler()
        self._setup_menu_bar()
        self._setup_status_bar()
        self._setup_shortcuts()
        
        # Load initial page
        self.load_page('index.html')
    
    def _setup_window(self):
        """Configure the main window properties"""
        self.setWindowTitle("WIMI - What I Missed It")
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(QSize(800, 600))
        
        # Set window icon if available
        icon_path = self.src_dir / 'assets' / 'icon.png'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.central_layout = layout
    
    def _setup_web_view(self):
        """Initialize and configure the web view"""
        self.web_view = QWebEngineView()
        
        # Use custom page for console message capture
        self.web_page = WIMIWebPage(self.web_view)
        self.web_view.setPage(self.web_page)
        
        # Configure web settings
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        
        if self.dev_mode and not self.is_frozen:
            # Enable developer tools in dev mode (not in production builds)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
        
        # Handle file downloads (e.g. export JSON from subject tree)
        self.web_page.profile().downloadRequested.connect(self._handle_download)

        # Add to layout
        self.central_layout.addWidget(self.web_view)
    
    def _handle_download(self, download):
        """Handle file download requests from the web view (e.g. JSON export)"""
        suggested_name = download.downloadFileName()
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save File', suggested_name
        )
        if path:
            file_path = Path(path)
            download.setDownloadDirectory(str(file_path.parent))
            download.setDownloadFileName(file_path.name)
            download.accept()
        else:
            download.cancel()

    def _setup_web_channel(self):
        """Set up the WebChannel for Python-JavaScript communication"""
        self.channel = QWebChannel()
        
        # Create database bridge
        self.db_bridge = DatabaseBridge(
            master_db=self.master_db,
            user_db=self.user_db,
            error_logger=self.error_logger
        )
        
        # Wire up plugin manager
        if self.plugin_manager:
            self.db_bridge.plugin_manager = self.plugin_manager
            self.db_bridge._plugin_registry = self.plugin_manager.get_plugin_registry()

        # Test-mode hook: when the bridge's loadTestUserDatabase slot
        # swaps in a new user_db, route through set_user_database() so
        # the media manager / scheme handler / plugin manager get
        # rewired the same way as the production login flow.
        self.db_bridge.userDatabaseLoaded.connect(self._on_test_user_database_loaded)

        # Create JavaScript error bridge
        self.js_error_bridge = JavaScriptErrorBridge(self.error_logger)
        
        # Register objects with the channel
        self.channel.registerObject('bridge', self.db_bridge)
        self.channel.registerObject('errorBridge', self.js_error_bridge)
        
        # Attach channel to the page
        self.web_page.setWebChannel(self.channel)
    
    def _setup_media_handler(self):
        """Set up the media URL scheme handler"""
        # Initialize MediaManager if we have a user database
        if self.user_db:
            self.media_manager = MediaManager(
                base_path=self.app_data_dir,
                user_id=self.user_db.user_id,
                username=self.user_db.username
            )
        else:
            # Create a placeholder manager (will be updated when user_db is set)
            self.media_manager = MediaManager(
                base_path=self.app_data_dir,
                user_id=0,
                username='temp'
            )
        
        # Install the scheme handler on the default profile
        profile = self.web_page.profile()
        self.media_scheme_handler = install_scheme_handler(profile, self.media_manager)
        
        # Store reference in bridge for access from JavaScript
        self.db_bridge.media_manager = self.media_manager

        # Give plugins access to the media manager
        if self.plugin_manager:
            self.plugin_manager.set_media_manager(self.media_manager)

        if self.dev_mode:
            print(f"📷 Media handler installed for: {self.media_manager.user_media_path}")
    
    def _setup_menu_bar(self):
        """Create the application menu bar"""
        menu_bar = self.menuBar()
        
        # File Menu
        file_menu = menu_bar.addMenu('&File')
        
        new_exam_action = QAction('&New Exam Setup...', self)
        new_exam_action.setShortcut(QKeySequence.StandardKey.New)
        new_exam_action.triggered.connect(lambda: self.load_page('wizards/exam_wizard.html'))
        file_menu.addAction(new_exam_action)
        
        settings_action = QAction('&Settings...', self)
        settings_action.setShortcut(QKeySequence('Ctrl+,'))
        settings_action.triggered.connect(lambda: self.load_page('settings.html'))
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        exit_action = QAction('E&xit', self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View Menu
        view_menu = menu_bar.addMenu('&View')
        
        reload_action = QAction('&Reload', self)
        reload_action.setShortcut(QKeySequence.StandardKey.Refresh)
        reload_action.triggered.connect(self.reload_page)
        view_menu.addAction(reload_action)
        
        if self.dev_mode:
            view_menu.addSeparator()
            
            dev_tools_action = QAction('&Developer Tools', self)
            dev_tools_action.setShortcut(QKeySequence('F12'))
            dev_tools_action.triggered.connect(self._open_dev_tools)
            view_menu.addAction(dev_tools_action)
        
        # Help Menu
        help_menu = menu_bar.addMenu('&Help')
        
        about_action = QAction('&About WIMI', self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _setup_status_bar(self):
        """Create the status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage('Ready')
    
    def _setup_shortcuts(self):
        """Set up keyboard shortcuts"""
        # F5 for hot reload
        reload_shortcut = QShortcut(QKeySequence('F5'), self)
        reload_shortcut.activated.connect(self.reload_page)
        
        # Ctrl+Shift+I for dev tools (if in dev mode)
        if self.dev_mode:
            dev_shortcut = QShortcut(QKeySequence('Ctrl+Shift+I'), self)
            dev_shortcut.activated.connect(self._open_dev_tools)
    
    def load_page(self, page_name: str):
        """
        Load an HTML page from the web directory.
        
        Args:
            page_name: Relative path to the HTML file from web/html/
        """
        # Construct the full path
        page_path = self.web_dir / 'html' / page_name
        
        if not page_path.exists():
            self.error_logger.error(
                f"Page not found: {page_path}",
                context={'page_name': page_name}
            )
            self.status_bar.showMessage(f'Error: Page not found - {page_name}')
            return
        
        # Load the page
        url = QUrl.fromLocalFile(str(page_path))
        self.web_view.setUrl(url)
        
        self.status_bar.showMessage(f'Loaded: {page_name}')
        
        if self.dev_mode:
            print(f"📄 Loaded page: {page_path}")
    
    def reload_page(self):
        """Reload the current page (hot reload)"""
        self.web_view.reload()
        self.status_bar.showMessage('Page reloaded')
        
        if self.dev_mode:
            print("🔄 Page reloaded")
    
    def _open_dev_tools(self):
        """Open browser developer tools (dev mode only)"""
        if self.dev_mode:
            # Create a new window for dev tools
            self.dev_tools = QWebEngineView()
            self.web_page.setDevToolsPage(self.dev_tools.page())
            self.dev_tools.setWindowTitle('WIMI Developer Tools')
            self.dev_tools.resize(1200, 800)
            self.dev_tools.show()
    
    def _show_about(self):
        """Show the About dialog"""
        QMessageBox.about(
            self,
            'About WIMI',
            '<h2>WIMI - What I Missed It</h2>'
            '<p>Version 0.1.0-beta</p>'
            '<p>A metacognitive exam preparation tool for analyzing '
            'mistakes and improving learning outcomes.</p>'
            '<p>© 2025 Project WIMI</p>'
        )
    
    def set_user_database(self, user_db: UserDatabase):
        """Update the user database reference"""
        self.user_db = user_db
        self.db_bridge.set_user_database(user_db)
        
        # Update media manager for new user
        self.media_manager = MediaManager(
            base_path=self.app_data_dir,
            user_id=user_db.user_id,
            username=user_db.username
        )
        self.db_bridge.media_manager = self.media_manager

        # Give plugins access to the updated media manager
        if self.plugin_manager:
            self.plugin_manager.set_media_manager(self.media_manager)

        # Update scheme handler's reference
        if self.media_scheme_handler:
            self.media_scheme_handler.set_media_manager(self.media_manager)

        self.status_bar.showMessage(f'User database loaded')

    def _on_test_user_database_loaded(self, user_id: int) -> None:
        """Test-mode hook: complete the user-DB wiring after the bridge
        slot loadTestUserDatabase has set bridge.user_db. The bridge can't
        reach the media manager / scheme handler / plugin manager
        directly, so we route through the existing set_user_database()
        which knows how to wire all four.
        """
        user_db = self.db_bridge.user_db
        if user_db is None:
            # Slot fired the signal but cleared user_db before we got
            # here — race that shouldn't happen, but bail safely.
            return
        self.set_user_database(user_db)

    def closeEvent(self, event):
        """Handle window close event"""
        # Clean up resources
        if hasattr(self, 'dev_tools'):
            self.dev_tools.close()
        
        # Close database connections
        if self.user_db:
            self.user_db.close()
        if self.master_db:
            self.master_db.close()
        
        event.accept()


def run_application(
    master_db: Optional[MasterDatabase] = None,
    user_db: Optional[UserDatabase] = None,
    dev_mode: bool = True,
    app_data_dir: Optional[Path] = None,
    plugin_manager=None
) -> int:
    """
    Run the WIMI application.

    Args:
        master_db: Optional master database instance
        user_db: Optional user database instance
        dev_mode: Whether to run in development mode
        app_data_dir: Path to application data directory
        plugin_manager: Optional PluginManager instance

    Returns:
        Application exit code
    """
    app = QApplication(sys.argv)
    app.setApplicationName('WIMI')
    app.setApplicationVersion('0.1.0-beta')
    app.setOrganizationName('Project WIMI')

    # Create and show main window
    window = MainWindow(
        master_db=master_db,
        user_db=user_db,
        dev_mode=dev_mode,
        app_data_dir=app_data_dir,
        plugin_manager=plugin_manager
    )
    window.show()

    # Auto-start MCP SSE server if enabled in preferences
    _auto_start_mcp_server(window)

    return app.exec()


def _auto_start_mcp_server(window):
    """Start the MCP SSE server on launch if the user has it enabled."""
    try:
        bridge = window.db_bridge
        if not bridge or not bridge.user_db:
            return

        prefs = bridge.user_db.get_preferences()
        if prefs and prefs.mcp_server_enabled:
            import json
            result_json = bridge.startMcpServer(
                json.dumps({'port': prefs.mcp_server_port})
            )
            result = json.loads(result_json)
            if result.get('success'):
                port = result.get('data', {}).get('port', prefs.mcp_server_port)
                print(f'MCP server auto-started on port {port}')
            else:
                print(f'MCP server auto-start failed: {result.get("error", "unknown")}')
    except Exception as e:
        print(f'MCP server auto-start error: {e}')


if __name__ == '__main__':
    sys.exit(run_application())
