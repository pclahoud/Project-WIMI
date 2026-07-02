"""
WIMI Application Package
PyQt6-based desktop application for exam preparation through metacognitive mistake analysis
"""

# Use lazy imports to avoid circular import issues
# Components are imported when accessed

__all__ = ['MainWindow', 'DatabaseBridge']

def __getattr__(name):
    """Lazy import of components"""
    if name == 'MainWindow':
        from app.main_window import MainWindow
        return MainWindow
    elif name == 'DatabaseBridge':
        from app.bridge import DatabaseBridge
        return DatabaseBridge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
