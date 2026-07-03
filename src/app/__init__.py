"""
WIMI Application Package
PyQt6-based desktop application for exam preparation through metacognitive mistake analysis
"""

# Single source of truth for the user-facing application version.
# Consumed by getAppInfo (bridge), setApplicationVersion (Qt), the About
# dialog, and the .wimi profile-archive manifest. Distinct from
# database.__version__, which tracks the database package/schema phase.
APP_VERSION = '0.1.0-beta'

# Use lazy imports to avoid circular import issues
# Components are imported when accessed

__all__ = ['APP_VERSION', 'MainWindow', 'DatabaseBridge']

def __getattr__(name):
    """Lazy import of components"""
    if name == 'MainWindow':
        from app.main_window import MainWindow
        return MainWindow
    elif name == 'DatabaseBridge':
        from app.bridge import DatabaseBridge
        return DatabaseBridge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
