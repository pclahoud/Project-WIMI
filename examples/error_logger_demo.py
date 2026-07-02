"""
PyQt6 WebEngine Integration Example with Error Logging
Shows how to integrate the error logging system with your Student App
"""

import sys
import json
from pathlib import Path
from PyQt6.QtCore import QUrl, pyqtSlot, QObject
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

# Import error logging components
from src.app_logging import (
    ErrorLogger, 
    ErrorLevel, 
    ErrorCategory,
    JavaScriptErrorBridge
)

# Import database components (adjust path as needed)
# from src.database import DatabaseManager


class StudentAppWindow(QMainWindow):
    """Main application window with error logging integration"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Student Question Analysis App")
        self.setGeometry(100, 100, 1200, 800)
        
        # Get project root directory
        self.project_root = Path(__file__).parent.parent
        
        # Initialize error logger
        self.error_logger = ErrorLogger(
            app_name="StudentApp",
            log_dir=self.project_root / "logs",
            mode='development',  # Change to 'production' for release
            max_file_size=50 * 1024 * 1024,  # 50MB
            buffer_size=1000
        )
        
        # Setup UI
        self.setup_ui()
        
        # Setup WebEngine with error logging
        self.setup_webengine()
        
        # Connect error signals to UI updates
        self.setup_error_handling()
        
        # Log application start
        self.error_logger.info("Application started", category=ErrorCategory.SYSTEM)
    
    def setup_ui(self):
        """Setup the main UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        # Create WebEngine view
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view)
    
    def setup_webengine(self):
        """Setup WebEngine with JavaScript error bridge"""
        # Create web channel for Python-JS communication
        self.channel = QWebChannel()
        self.web_view.page().setWebChannel(self.channel)
        
        # Create JavaScript error bridge
        self.js_error_bridge = JavaScriptErrorBridge(self.error_logger)
        self.channel.registerObject("pyqt_bridge", self.js_error_bridge)
        
        # Load the HTML with error logger
        html_content = self.get_html_with_error_logger()
        self.web_view.setHtml(html_content, QUrl("qrc:/"))
    
    def get_html_with_error_logger(self):
        """Get HTML content with integrated error logger"""
        # Read the error logger JavaScript
        error_logger_js_path = self.project_root / "src" / "web" / "js" / "error-logger.js"
        with open(error_logger_js_path, 'r') as f:
            error_logger_js = f.read()
        
        # Read the error viewer CSS
        error_viewer_css_path = self.project_root / "src" / "web" / "css" / "error-viewer.css"
        with open(error_viewer_css_path, 'r') as f:
            error_viewer_css = f.read()
        
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Student App</title>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{ color: #333; }}
        .button-group {{
            margin: 20px 0;
        }}
        button {{
            padding: 10px 20px;
            margin: 5px;
            border: none;
            border-radius: 4px;
            background: #4CAF50;
            color: white;
            cursor: pointer;
            font-size: 14px;
        }}
        button:hover {{ background: #45a049; }}
        .error-button {{ background: #f44336; }}
        .error-button:hover {{ background: #da190b; }}
        .warning-button {{ background: #ff9800; }}
        .warning-button:hover {{ background: #e68900; }}
        
        /* Include error viewer styles */
        {error_viewer_css}
    </style>
</head>
<body>
    <div class="container">
        <h1>Student Question Analysis App</h1>
        <p>Error logging is active and monitoring all JavaScript and Python errors.</p>
        
        <div class="button-group">
            <h2>Test Error Logging</h2>
            <button onclick="testInfo()">Log Info</button>
            <button class="warning-button" onclick="testWarning()">Log Warning</button>
            <button class="error-button" onclick="testError()">Trigger Error</button>
            <button onclick="testDatabaseOperation()">Test Database Operation</button>
            <button onclick="testNetworkRequest()">Test Network Request</button>
            <button class="error-button" onclick="testMigrationError()">Test Migration Error</button>
        </div>
        
        <div class="button-group">
            <h2>Error Viewer Controls</h2>
            <button onclick="errorViewer.toggleViewer()">Toggle Error Console</button>
            <button onclick="errorViewer.toggleStats()">Show Statistics</button>
            <button onclick="errorViewer.clearErrors()">Clear Errors</button>
        </div>
    </div>
    
    <!-- Error Viewer Component -->
    <div id="error-viewer" class="minimized">
        <div class="viewer-header">
            <div class="viewer-title">
                <span class="error-indicator" id="status-indicator"></span>
                <span>Error Console</span>
                <span class="error-badge" id="error-count">0</span>
            </div>
            <div class="viewer-controls">
                <button onclick="errorViewer.toggleStats()" title="Statistics">📊</button>
                <button onclick="errorViewer.clearErrors()" title="Clear">🗑️</button>
                <button onclick="errorViewer.exportErrors()" title="Export">💾</button>
                <button onclick="errorViewer.toggleViewer()" title="Minimize">_</button>
            </div>
        </div>
        
        <div class="viewer-filters">
            <select class="filter-select" id="level-filter" onchange="errorViewer.filterErrors()">
                <option value="">All Levels</option>
                <option value="TRACE">Trace</option>
                <option value="DEBUG">Debug</option>
                <option value="INFO">Info</option>
                <option value="WARNING">Warning</option>
                <option value="ERROR">Error</option>
                <option value="CRITICAL">Critical</option>
                <option value="FATAL">Fatal</option>
            </select>
            
            <select class="filter-select" id="category-filter" onchange="errorViewer.filterErrors()">
                <option value="">All Categories</option>
                <option value="javascript">JavaScript</option>
                <option value="network">Network</option>
                <option value="database">Database</option>
                <option value="migration">Migration</option>
                <option value="console">Console</option>
                <option value="promise">Promise</option>
                <option value="custom">Custom</option>
            </select>
            
            <input type="text" class="search-input" id="search-filter" 
                   placeholder="Search errors..." onkeyup="errorViewer.filterErrors()">
        </div>
        
        <div class="error-list" id="error-list">
            <div class="error-list-empty">
                <div class="error-list-empty-icon">✓</div>
                <div class="error-list-empty-text">No errors to display</div>
            </div>
        </div>
    </div>
    
    <!-- Statistics Panel -->
    <div class="stats-panel" id="stats-panel">
        <div class="stats-title">Error Statistics</div>
        <div id="stats-content"></div>
    </div>
    
    <script>
        // Include the error logger JavaScript
        {error_logger_js}
        
        // Error Viewer Class
        class ErrorViewer {{
            constructor() {{
                this.viewerMinimized = true;
                this.statsVisible = false;
                this.initialize();
            }}
            
            initialize() {{
                // Listen for new errors
                window.addEventListener('errorlogger:error', (event) => {{
                    this.updateErrorList();
                    this.updateErrorCount();
                    this.updateStatusIndicator();
                }});
                
                window.addEventListener('errorlogger:clear', (event) => {{
                    this.updateErrorList();
                    this.updateErrorCount();
                    this.updateStatusIndicator();
                }});
                
                // Initial update
                this.updateErrorList();
                this.updateErrorCount();
            }}
            
            toggleViewer() {{
                this.viewerMinimized = !this.viewerMinimized;
                document.getElementById('error-viewer').classList.toggle('minimized', this.viewerMinimized);
            }}
            
            toggleStats() {{
                this.statsVisible = !this.statsVisible;
                document.getElementById('stats-panel').classList.toggle('visible', this.statsVisible);
                if (this.statsVisible) {{
                    this.updateStats();
                }}
            }}
            
            clearErrors() {{
                if (confirm('Clear all errors?')) {{
                    window.errorLogger.clearErrors();
                }}
            }}
            
            exportErrors() {{
                const data = window.errorLogger.exportErrors('json');
                const blob = new Blob([data], {{ type: 'application/json' }});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `errors_${{Date.now()}}.json`;
                a.click();
                URL.revokeObjectURL(url);
            }}
            
            filterErrors() {{
                this.updateErrorList();
            }}
            
            updateErrorList() {{
                const levelFilter = document.getElementById('level-filter').value;
                const categoryFilter = document.getElementById('category-filter').value;
                const searchFilter = document.getElementById('search-filter').value;
                
                const errors = window.errorLogger.getErrors({{
                    level: levelFilter,
                    category: categoryFilter,
                    search: searchFilter
                }});
                
                const listEl = document.getElementById('error-list');
                
                if (errors.length === 0) {{
                    listEl.innerHTML = `
                        <div class="error-list-empty">
                            <div class="error-list-empty-icon">✓</div>
                            <div class="error-list-empty-text">No errors to display</div>
                        </div>
                    `;
                    return;
                }}
                
                listEl.innerHTML = errors.slice(0, 100).map(error => `
                    <div class="error-item level-${{error.level}}" onclick="errorViewer.toggleErrorDetails(this)">
                        <div class="error-header">
                            <span class="error-level level-${{error.level}}">${{error.level}}</span>
                            <span class="error-time">${{new Date(error.timestamp).toLocaleTimeString()}}</span>
                        </div>
                        <div class="error-message">${{this.escapeHtml(error.message)}}</div>
                        <div class="error-details">
                            ${{error.stack ? `<div class="error-stack">${{this.escapeHtml(error.stack)}}</div>` : ''}}
                            <div class="error-context">
                                <div class="context-item">
                                    <span class="context-label">Category:</span>
                                    <span class="context-value">${{error.category}}</span>
                                </div>
                                <div class="context-item">
                                    <span class="context-label">Session ID:</span>
                                    <span class="context-value">${{error.context.sessionId}}</span>
                                </div>
                                ${{error.context.url ? `
                                    <div class="context-item">
                                        <span class="context-label">URL:</span>
                                        <span class="context-value">${{this.escapeHtml(error.context.url)}}</span>
                                    </div>
                                ` : ''}}
                            </div>
                        </div>
                    </div>
                `).join('');
            }}
            
            toggleErrorDetails(element) {{
                element.classList.toggle('expanded');
            }}
            
            updateErrorCount() {{
                const count = window.errorLogger.errors.length;
                document.getElementById('error-count').textContent = count;
            }}
            
            updateStatusIndicator() {{
                const errors = window.errorLogger.errors;
                const indicator = document.getElementById('status-indicator');
                
                const hasErrors = errors.some(e => ['ERROR', 'CRITICAL', 'FATAL'].includes(e.level));
                const hasWarnings = errors.some(e => e.level === 'WARNING');
                
                indicator.classList.toggle('has-errors', hasErrors);
                indicator.classList.toggle('has-warnings', !hasErrors && hasWarnings);
            }}
            
            updateStats() {{
                const stats = window.errorLogger.getStatistics();
                const content = document.getElementById('stats-content');
                
                content.innerHTML = `
                    <div class="stat-row">
                        <span class="stat-label">Total Errors:</span>
                        <span class="stat-value">${{stats.total}}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Current Buffer:</span>
                        <span class="stat-value">${{stats.errors}}/${{stats.maxErrors}}</span>
                    </div>
                    ${{Object.entries(stats.byLevel).map(([level, count]) => `
                        <div class="stat-row">
                            <span class="stat-label">${{level}}:</span>
                            <span class="stat-value">${{count}}</span>
                        </div>
                    `).join('')}}
                `;
            }}
            
            escapeHtml(text) {{
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }}
        }}
        
        // Initialize Qt WebChannel
        let pyqt_bridge = null;
        
        new QWebChannel(qt.webChannelTransport, function(channel) {{
            pyqt_bridge = channel.objects.pyqt_bridge;
            
            // Initialize error logger with Python bridge
            window.errorLogger = new ErrorLogger({{
                pythonBridge: pyqt_bridge,
                enableConsoleCapture: true,
                enableWindowErrorCapture: true,
                enableUnhandledRejectionCapture: true,
                enableBreadcrumbs: true
            }});
            
            // Initialize error viewer
            window.errorViewer = new ErrorViewer();
            
            // Set user context
            window.errorLogger.setUser(1, 'demo_student');
            
            console.log('Error logger initialized with Python bridge');
        }});
        
        // Test functions
        function testInfo() {{
            window.errorLogger.info('This is an informational message', {{
                category: 'custom',
                action: 'test_button_click'
            }});
        }}
        
        function testWarning() {{
            window.errorLogger.warning('This is a warning message', {{
                category: 'custom',
                action: 'test_button_click'
            }});
        }}
        
        function testError() {{
            throw new Error('Test JavaScript error from UI');
        }}
        
        function testDatabaseOperation() {{
            // Simulate database operation
            window.errorLogger.error('Database query failed: database is locked', {{
                category: 'database',
                query: 'SELECT * FROM questions WHERE subject_id = 1',
                attempts: 3
            }});
        }}
        
        function testNetworkRequest() {{
            // Simulate network request failure
            fetch('https://nonexistent-api-endpoint-12345.com/data')
                .catch(error => {{
                    window.errorLogger.error('Network request failed', {{
                        category: 'network',
                        url: 'https://nonexistent-api-endpoint-12345.com/data',
                        error: error.message
                    }});
                }});
        }}
        
        function testMigrationError() {{
            window.errorLogger.error('Schema migration failed: Table already exists', {{
                category: 'migration',
                migration: '004_add_calendar_tables.sql',
                table: 'calendar_events',
                database: 'user_001.db'
            }});
        }}
    </script>
</body>
</html>
        """
    
    def setup_error_handling(self):
        """Setup error handling for the application"""
        # Connect error logger signals to UI updates
        self.error_logger.error_logged.connect(self.on_error_logged)
        self.error_logger.recovery_attempted.connect(self.on_recovery_attempted)
        
        # Handle Python exceptions
        sys.excepthook = self.handle_exception
    
    @pyqtSlot(dict)
    def on_error_logged(self, error_data):
        """Handle error logged signal"""
        if self.error_logger.mode == 'development':
            print(f"[{error_data['level']}] {error_data['message']}")
    
    @pyqtSlot(dict)
    def on_recovery_attempted(self, recovery_data):
        """Handle recovery attempt signal"""
        if recovery_data['success']:
            self.error_logger.info(
                f"Recovery successful: {recovery_data['strategy']}",
                category=ErrorCategory.SYSTEM
            )
        else:
            self.error_logger.warning(
                f"Recovery failed: {recovery_data['strategy']}",
                category=ErrorCategory.SYSTEM
            )
    
    def handle_exception(self, exc_type, exc_value, exc_traceback):
        """Global exception handler"""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        self.error_logger.critical(
            f"Uncaught exception: {exc_value}",
            category=ErrorCategory.SYSTEM,
            error=exc_value
        )
    
    def set_user_context(self, user_id: int, username: str, database: str):
        """Set the current user context for error logging"""
        self.error_logger.set_user_context(user_id, username, database)
        
        # Also update JavaScript side
        self.web_view.page().runJavaScript(
            f"if (window.errorLogger) {{ window.errorLogger.setUser({user_id}, '{username}'); }}"
        )
    
    def closeEvent(self, event):
        """Clean up when closing the application"""
        self.error_logger.info("Application shutting down", category=ErrorCategory.SYSTEM)
        
        # Get final statistics
        stats = self.error_logger.get_statistics(hours=24)
        self.error_logger.info(f"Session statistics: {json.dumps(stats)}", category=ErrorCategory.SYSTEM)
        
        # Cleanup
        self.error_logger.cleanup()
        event.accept()


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("StudentApp")
    
    # Create main window
    window = StudentAppWindow()
    
    # Set initial user context
    window.set_user_context(user_id=1, username="demo_student", database="user_001")
    
    # Test logging from Python
    window.error_logger.info("Application initialized successfully", category=ErrorCategory.SYSTEM)
    
    # Show window
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
