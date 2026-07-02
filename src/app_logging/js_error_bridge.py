"""
JavaScript Error Bridge for PyQt6 WebEngine
Captures JavaScript errors and sends them to the Python error logger
"""

import json
from PyQt6.QtCore import QObject, pyqtSlot
from .error_logger import ErrorLogger, ErrorLevel, ErrorCategory, ErrorContext


class JavaScriptErrorBridge(QObject):
    """Bridge to capture JavaScript errors from WebEngine"""
    
    def __init__(self, error_logger: ErrorLogger):
        super().__init__()
        self.error_logger = error_logger
    
    @pyqtSlot(str)
    def log_js_error(self, error_data: str):
        """
        Receive error from JavaScript as JSON string
        
        Expected format:
        {
            "level": "ERROR",
            "message": "Error message",
            "category": "javascript",
            "stack": "Stack trace",
            "context": {
                "url": "http://...",
                "userAgent": "...",
                "breadcrumbs": [...]
            }
        }
        """
        try:
            data = json.loads(error_data)
            
            # Map JavaScript level to Python ErrorLevel
            level_map = {
                'TRACE': ErrorLevel.TRACE,
                'DEBUG': ErrorLevel.DEBUG,
                'INFO': ErrorLevel.INFO,
                'WARNING': ErrorLevel.WARNING,
                'ERROR': ErrorLevel.ERROR,
                'CRITICAL': ErrorLevel.CRITICAL,
                'FATAL': ErrorLevel.FATAL
            }
            
            level = level_map.get(data.get('level', 'ERROR'), ErrorLevel.ERROR)
            
            # Map JavaScript category to Python ErrorCategory
            category_map = {
                'javascript': ErrorCategory.UI,
                'network': ErrorCategory.NETWORK,
                'promise': ErrorCategory.UI,
                'console': ErrorCategory.UI,
                'custom': ErrorCategory.CUSTOM
            }
            
            category = category_map.get(data.get('category', 'javascript'), ErrorCategory.UI)
            
            # Extract context
            js_context = data.get('context', {})
            context = {
                'environment': 'javascript',
                'url': js_context.get('url'),
                'user_agent': js_context.get('userAgent'),
                'breadcrumbs': js_context.get('breadcrumbs', [])
            }
            
            # Add any additional metadata
            if 'sessionId' in js_context:
                context['js_session_id'] = js_context['sessionId']
            if 'userId' in js_context:
                context['js_user_id'] = js_context['userId']
            
            # Log the error
            self.error_logger.log(
                level=level,
                message=data.get('message', 'Unknown JavaScript error'),
                category=category,
                stack_trace=data.get('stack'),
                context=context
            )
            
        except json.JSONDecodeError as e:
            self.error_logger.error(
                f"Failed to parse JavaScript error data: {e}",
                category=ErrorCategory.BRIDGE,
                context={'raw_data': error_data}
            )
        except Exception as e:
            self.error_logger.error(
                f"Unexpected error in JavaScript bridge: {e}",
                category=ErrorCategory.BRIDGE
            )
    
    @pyqtSlot(str, str)
    def log_js_message(self, level: str, message: str):
        """Simple logging method for JavaScript"""
        level_map = {
            'trace': ErrorLevel.TRACE,
            'debug': ErrorLevel.DEBUG,
            'info': ErrorLevel.INFO,
            'warn': ErrorLevel.WARNING,
            'warning': ErrorLevel.WARNING,
            'error': ErrorLevel.ERROR,
            'critical': ErrorLevel.CRITICAL,
            'fatal': ErrorLevel.FATAL
        }
        
        error_level = level_map.get(level.lower(), ErrorLevel.INFO)
        
        self.error_logger.log(
            level=error_level,
            message=message,
            category=ErrorCategory.UI,
            context={'environment': 'javascript'}
        )
    
    @pyqtSlot(str, str, str)
    def log_js_error_simple(self, message: str, stack: str, url: str):
        """Simple error logging for JavaScript exceptions"""
        self.error_logger.log(
            level=ErrorLevel.ERROR,
            message=message,
            category=ErrorCategory.UI,
            stack_trace=stack,
            context={
                'environment': 'javascript',
                'url': url
            }
        )
    
    @pyqtSlot(result=str)
    def get_session_id(self):
        """Return the current session ID to JavaScript"""
        return self.error_logger.session_id
    
    @pyqtSlot(int, str)
    def set_js_user_context(self, user_id: int, username: str):
        """Set user context from JavaScript"""
        # Update the main error logger's user context
        self.error_logger.set_user_context(user_id, username)
    
    @pyqtSlot(result=str)
    def get_error_stats(self):
        """Get error statistics for JavaScript UI"""
        stats = self.error_logger.get_statistics(hours=1)
        return json.dumps(stats)
    
    @pyqtSlot()
    def clear_errors(self):
        """Clear error buffer (development only)"""
        if self.error_logger.mode == 'development':
            self.error_logger.error_buffer.clear()
            self.error_logger.error_cache.clear()
