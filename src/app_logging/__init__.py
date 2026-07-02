"""
Error Logging Module for PyQt6 WebEngine Student App
"""

from .error_logger import (
    ErrorLogger,
    ErrorLevel,
    ErrorCategory,
    ErrorContext,
    ErrorLogEntry,
    RecoveryStrategy,
    DatabaseLockRecovery,
    NetworkRetryRecovery
)

from .js_error_bridge import JavaScriptErrorBridge

__all__ = [
    'ErrorLogger',
    'ErrorLevel',
    'ErrorCategory',
    'ErrorContext',
    'ErrorLogEntry',
    'RecoveryStrategy',
    'DatabaseLockRecovery',
    'NetworkRetryRecovery',
    'JavaScriptErrorBridge'
]

__version__ = '1.0.0'
