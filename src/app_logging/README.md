# Error Logging Manager

A robust, asynchronous error logging system for the PyQt6 WebEngine Student Question Analysis App.

## Features

### Core Capabilities
- **Dual-Environment Capture**: Logs errors from both Python backend and JavaScript frontend
- **Asynchronous Processing**: Non-blocking error logging with ThreadPoolExecutor
- **Automatic Recovery**: Built-in strategies for database locks and network failures
- **Aggressive Migration Logging**: Special handling for schema migration errors
- **In-App Developer Console**: Real-time error viewer for development mode
- **Privacy-Aware**: Configurable sharing settings for multi-user scenarios

### Error Levels
- `TRACE` - Detailed diagnostic information
- `DEBUG` - Debug-level messages
- `INFO` - Informational messages
- `WARNING` - Warning messages
- `ERROR` - Error messages
- `CRITICAL` - Critical failures
- `FATAL` - Fatal errors requiring immediate attention

### Error Categories
- `NETWORK` - Network-related errors
- `DATABASE` - Database operations and locks
- `VALIDATION` - Input validation errors
- `PERMISSION` - Access control issues
- `SYSTEM` - System-level errors
- `BRIDGE` - Python-JavaScript communication
- `MIGRATION` - Schema migration errors
- `ANKI` - AnkiConnect integration errors
- `UI` - User interface errors
- `CUSTOM` - Custom application errors

## Directory Structure

```
src/app_logging/
├── __init__.py           # Module exports
├── error_logger.py       # Main Python error logger
└── js_error_bridge.py    # JavaScript-Python bridge

src/web/
├── js/
│   └── error-logger.js   # JavaScript error logger
├── css/
│   └── error-viewer.css  # Error viewer styles
└── html/
    └── error-viewer.html # Standalone error viewer

logs/
├── StudentApp_*.log      # Rotating application logs
└── migrations_*.log      # Migration-specific logs
```

## Installation

The error logging system is already integrated into the project. No additional installation required.

## Usage

### Basic Python Usage

```python
from src.app_logging import ErrorLogger, ErrorLevel, ErrorCategory

# Initialize the logger
logger = ErrorLogger(
    app_name="StudentApp",
    mode='development',  # or 'production'
    max_file_size=50 * 1024 * 1024,  # 50MB
    buffer_size=1000
)

# Set user context
logger.set_user_context(user_id=1, username="student1", database="user_001")

# Log messages at different levels
logger.info("Application started")
logger.warning("Low memory warning", category=ErrorCategory.SYSTEM)
logger.error("Database query failed", category=ErrorCategory.DATABASE)

# Log with additional context
logger.error(
    "Failed to save question",
    category=ErrorCategory.DATABASE,
    context={
        'question_id': 123,
        'user_action': 'save_question',
        'error_code': 'DB_LOCK'
    }
)

# Log exceptions with stack trace
try:
    risky_operation()
except Exception as e:
    logger.error(
        "Operation failed",
        error=e,  # Automatically captures stack trace
        auto_recover=True  # Attempt automatic recovery
    )
```

### JavaScript Usage

```javascript
// Initialize with Python bridge
window.errorLogger = new ErrorLogger({
    pythonBridge: pyqt_bridge,
    enableConsoleCapture: true,
    enableWindowErrorCapture: true,
    enableBreadcrumbs: true
});

// Set user context
window.errorLogger.setUser(userId, username);

// Log messages
window.errorLogger.info('Page loaded successfully');
window.errorLogger.warning('Slow network detected');
window.errorLogger.error('Failed to load question', {
    category: 'network',
    questionId: 456
});

// Errors are automatically captured
throw new Error('This will be logged automatically');
```

### PyQt6 Integration

```python
from src.app_logging import ErrorLogger, JavaScriptErrorBridge
from PyQt6.QtWebChannel import QWebChannel

# In your main window
def setup_webengine(self):
    # Create web channel
    self.channel = QWebChannel()
    self.web_view.page().setWebChannel(self.channel)
    
    # Create and register error bridge
    self.js_error_bridge = JavaScriptErrorBridge(self.error_logger)
    self.channel.registerObject("pyqt_bridge", self.js_error_bridge)
```

## Configuration

### Logger Options

```python
ErrorLogger(
    app_name="StudentApp",           # Application name for logs
    log_dir=Path("custom/path"),     # Custom log directory
    mode='development',               # 'development' or 'production'
    max_file_size=50*1024*1024,     # Max size before rotation (50MB)
    max_files=10,                    # Number of log files to keep
    buffer_size=1000,                # In-memory buffer size
    flush_interval=5.0               # Seconds between auto-flush
)
```

### Development Mode Features
- Console output with color coding
- In-app error viewer at bottom-right
- Full stack traces captured
- All log levels recorded
- Real-time statistics panel

### Production Mode Features
- File-only logging (no console)
- Compact log format
- Only WARNING and above logged
- Minimal stack traces
- Optimized for performance

## Automatic Recovery

The system includes built-in recovery strategies:

### Database Lock Recovery
- Detects SQLite "database is locked" errors
- Implements exponential backoff (up to 3 retries)
- Waits 0.5s, 1s, 1.5s between retries

### Network Retry Recovery
- Handles timeout and connection refused errors
- Up to 5 retry attempts
- Exponential backoff up to 30 seconds

### Custom Recovery Strategies

```python
class CustomRecovery(RecoveryStrategy):
    def can_recover(self, error: ErrorLogEntry) -> bool:
        return "specific_error" in error.message
    
    def recover(self, error: ErrorLogEntry) -> bool:
        # Implement recovery logic
        return True

# Add to logger
logger.recovery_strategies.append(CustomRecovery())
```

## Privacy Settings

User-configurable privacy settings for error sharing:

```python
privacy_settings = {
    'share_errors_with_tutor': True,     # Enable tutor access
    'share_level': 'WARNING',            # Minimum level to share
    'share_categories': [                # Categories to share
        'database', 'sync', 'study'
    ],
    'exclude_categories': ['personal'],  # Never share these
    'auto_expire_shares': 7,             # Days until auto-removal
}
```

## Error Viewer (Development)

The in-app error viewer provides:
- Real-time error display
- Filtering by level and category
- Search functionality
- Export to JSON/CSV
- Statistics panel
- Expandable stack traces

Access via:
- Click the minimized console at bottom-right
- Use keyboard shortcut (Ctrl+Shift+E)
- Call `errorViewer.toggleViewer()` from console

## Log File Formats

### Development Mode (Pretty JSON)
```json
{
  "id": "a1b2c3d4",
  "timestamp": 1704556800.123,
  "datetime": "2024-01-06T12:00:00",
  "level": "ERROR",
  "category": "database",
  "message": "Database query failed",
  "stack_trace": "...",
  "context": {
    "user_id": 1,
    "database": "user_001",
    "query": "SELECT * FROM questions"
  },
  "recovered": false,
  "recovery_attempts": 2
}
```

### Production Mode (Compact JSON)
```json
{"id":"a1b2c3d4","ts":1704556800.123,"lvl":50,"cat":"database","msg":"Database query failed","ctx":{"user":1,"env":"python"}}
```

## Migration Error Logging

Migration errors receive special treatment:
- Separate log file: `migrations_YYYYMMDD.log`
- Full context preservation
- No truncation of SQL statements
- Formatted for readability
- Includes before/after states

## Testing

Run the demo application:
```bash
python examples/error_logger_demo.py
```

This provides:
- Interactive error generation
- Visual error viewer
- Python-JavaScript bridge testing
- Recovery strategy demonstration

## Performance Considerations

- **Async Processing**: Errors queued and processed in background
- **Memory Buffer**: Recent 1000 errors kept in memory
- **Deduplication**: Prevents log spam (5-second window)
- **File Rotation**: Automatic rotation at 50MB
- **Cleanup**: Old logs auto-deleted (keeps last 10)

## Troubleshooting

### Logs Directory Not Created
The logger automatically creates the logs directory. Ensure write permissions.

### JavaScript Errors Not Captured
Verify WebChannel is properly initialized:
```javascript
console.log(window.pyqt_bridge); // Should not be undefined
```

### Database Lock Errors Persist
Increase recovery attempts or wait time:
```python
DatabaseLockRecovery(max_retries=5, wait_time=1.0)
```

### High Memory Usage
Reduce buffer size:
```python
ErrorLogger(buffer_size=500)  # Default is 1000
```

## Best Practices

1. **Set User Context Early**: Call `set_user_context()` after login
2. **Use Appropriate Levels**: INFO for normal, ERROR for failures
3. **Include Context**: Add relevant metadata for debugging
4. **Category Consistency**: Use predefined categories
5. **Handle Exceptions**: Use try/except with error logging
6. **Test Recovery**: Verify automatic recovery works
7. **Monitor Stats**: Check statistics regularly in development
8. **Clean Logs**: Implement log retention policy

## License

Part of the Student Question Analysis App project.
