"""
Error Logging Manager for PyQt6 WebEngine Student App
Provides asynchronous, multi-environment error logging with automatic recovery
"""

import os
import json
import time
import queue
import logging
import hashlib
import sqlite3
import threading
import traceback
from enum import Enum, IntEnum
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

# For PyQt6 integration
from PyQt6.QtCore import QObject, pyqtSignal, QTimer


class ErrorLevel(IntEnum):
    """Error severity levels"""
    TRACE = 10
    DEBUG = 20
    INFO = 30
    WARNING = 40
    ERROR = 50
    CRITICAL = 60
    FATAL = 70


class ErrorCategory(Enum):
    """Error categorization for filtering and analysis"""
    NETWORK = "network"
    DATABASE = "database"
    VALIDATION = "validation"
    PERMISSION = "permission"
    SYSTEM = "system"
    BRIDGE = "python_js_bridge"
    MIGRATION = "schema_migration"
    ANKI = "anki_connect"
    UI = "user_interface"
    CUSTOM = "custom"


@dataclass
class ErrorContext:
    """Context information for error tracking"""
    user_id: Optional[int] = None
    username: Optional[str] = None
    session_id: Optional[str] = None
    database: Optional[str] = None  # 'master' or 'user_xxx'
    environment: str = 'python'  # 'python' or 'javascript'
    action: Optional[str] = None  # What user was doing
    question_id: Optional[int] = None
    subject_id: Optional[int] = None
    request_id: Optional[str] = None  # For tracking related errors
    metadata: Dict[str, Any] = None


@dataclass
class ErrorLogEntry:
    """Single error log entry"""
    id: str  # Unique ID
    timestamp: float
    level: ErrorLevel
    category: ErrorCategory
    message: str
    stack_trace: Optional[str] = None
    context: Optional[ErrorContext] = None
    error_hash: Optional[str] = None  # For deduplication
    count: int = 1  # For aggregating duplicate errors
    first_seen: Optional[float] = None
    last_seen: Optional[float] = None
    recovered: bool = False  # Was auto-recovery successful?
    recovery_attempts: int = 0


class RecoveryStrategy:
    """Base class for automatic error recovery strategies"""
    
    def can_recover(self, error: ErrorLogEntry) -> bool:
        """Check if this strategy can handle the error"""
        return False
    
    def recover(self, error: ErrorLogEntry) -> bool:
        """Attempt to recover from the error"""
        return False


class DatabaseLockRecovery(RecoveryStrategy):
    """Recovery strategy for SQLite database locks"""
    
    def __init__(self, max_retries: int = 3, wait_time: float = 0.5):
        self.max_retries = max_retries
        self.wait_time = wait_time
    
    def can_recover(self, error: ErrorLogEntry) -> bool:
        return (error.category == ErrorCategory.DATABASE and 
                "database is locked" in error.message.lower())
    
    def recover(self, error: ErrorLogEntry) -> bool:
        """Wait and retry the database operation"""
        if error.recovery_attempts >= self.max_retries:
            return False
        
        time.sleep(self.wait_time * (error.recovery_attempts + 1))
        # The actual retry would be handled by the calling code
        return True


class NetworkRetryRecovery(RecoveryStrategy):
    """Recovery strategy for network errors"""
    
    def can_recover(self, error: ErrorLogEntry) -> bool:
        return (error.category == ErrorCategory.NETWORK and
                any(x in error.message.lower() for x in ['timeout', 'connection refused', 'unreachable']))
    
    def recover(self, error: ErrorLogEntry) -> bool:
        """Exponential backoff for network retries"""
        if error.recovery_attempts >= 5:
            return False
        
        wait_time = min(30, 2 ** error.recovery_attempts)
        time.sleep(wait_time)
        return True


class ErrorLogger(QObject):
    """
    Main Error Logging Manager
    Handles asynchronous logging with automatic recovery
    """
    
    # Qt signals for UI updates
    error_logged = pyqtSignal(dict)  # Emit when error is logged
    recovery_attempted = pyqtSignal(dict)  # Emit when recovery is attempted
    stats_updated = pyqtSignal(dict)  # Emit statistics updates
    
    def __init__(self, 
                 app_name: str = "StudentApp",
                 log_dir: Optional[Path] = None,
                 mode: str = 'development',
                 max_file_size: int = 50 * 1024 * 1024,  # 50MB
                 max_files: int = 10,
                 buffer_size: int = 1000,
                 flush_interval: float = 5.0):
        super().__init__()
        
        self.app_name = app_name
        self.mode = mode
        self.max_file_size = max_file_size
        self.max_files = max_files
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        
        # Setup logging directory
        if log_dir is None:
            # Use project's logs directory
            log_dir = Path(__file__).parent.parent.parent / 'logs'
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Current session
        self.session_id = self._generate_session_id()
        self.current_user: Optional[ErrorContext] = None
        
        # Error buffer for async logging
        self.error_queue = queue.Queue(maxsize=buffer_size)
        self.error_buffer: deque = deque(maxlen=buffer_size)  # In-memory cache
        
        # Deduplication
        self.error_cache: Dict[str, ErrorLogEntry] = {}
        self.dedup_window = 300  # 5 minutes
        
        # Recovery strategies
        self.recovery_strategies: List[RecoveryStrategy] = [
            DatabaseLockRecovery(),
            NetworkRetryRecovery(),
        ]
        
        # Statistics
        self.stats = defaultdict(lambda: defaultdict(int))
        
        # File handles
        self.current_log_file = None
        self.log_file_handle = None
        self.log_rotation_size = 0
        
        # Migration logging (aggressive mode)
        self.migration_log_file = self.log_dir / f"migrations_{datetime.now():%Y%m%d}.log"
        
        # Threading
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ErrorLogger')
        self.flush_timer = None
        self.running = True
        
        # Initialize
        self._initialize_logging()
        self._start_flush_timer()
    
    def _generate_session_id(self) -> str:
        """Generate unique session ID"""
        return f"{self.app_name}_{int(time.time())}_{os.getpid()}"
    
    def _initialize_logging(self):
        """Initialize the logging system"""
        # Setup Python's built-in logging to redirect here
        self.python_logger = logging.getLogger(self.app_name)
        handler = self.PythonLoggingHandler(self)
        handler.setLevel(logging.DEBUG if self.mode == 'development' else logging.WARNING)
        self.python_logger.addHandler(handler)
        
        # Open initial log file
        self._rotate_log_file()
    
    def _rotate_log_file(self):
        """Rotate log file when it gets too large"""
        if self.log_file_handle:
            self.log_file_handle.close()
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.current_log_file = self.log_dir / f"{self.app_name}_{timestamp}.log"
        self.log_file_handle = open(self.current_log_file, 'a', encoding='utf-8')
        self.log_rotation_size = 0
        
        # Clean up old files
        self._cleanup_old_logs()
    
    def _cleanup_old_logs(self):
        """Remove old log files beyond max_files limit"""
        log_files = sorted(self.log_dir.glob(f"{self.app_name}_*.log"))
        if len(log_files) > self.max_files:
            for old_file in log_files[:-self.max_files]:
                try:
                    old_file.unlink()
                except Exception:
                    pass
    
    def _start_flush_timer(self):
        """Start timer for periodic flushing"""
        if self.flush_timer:
            self.flush_timer.stop()
        
        self.flush_timer = QTimer()
        self.flush_timer.timeout.connect(self.flush)
        self.flush_timer.start(int(self.flush_interval * 1000))
    
    def set_user_context(self, user_id: int, username: str, database: str = 'master'):
        """Set the current user context for error tracking"""
        self.current_user = ErrorContext(
            user_id=user_id,
            username=username,
            database=database,
            session_id=self.session_id
        )
    
    def log(self,
            level: ErrorLevel,
            message: str,
            category: ErrorCategory = ErrorCategory.CUSTOM,
            error: Optional[Exception] = None,
            context: Optional[Dict[str, Any]] = None,
            stack_trace: Optional[str] = None,
            auto_recover: bool = True) -> str:
        """
        Log an error asynchronously
        
        Returns: Error ID for tracking
        """
        # Generate error ID
        error_id = self._generate_error_id(message, stack_trace)
        
        # Get stack trace if exception provided
        if error and not stack_trace:
            stack_trace = traceback.format_exc()
        
        # Build context
        error_context = self.current_user or ErrorContext()
        if context:
            error_context.metadata = context
        
        # Create log entry
        entry = ErrorLogEntry(
            id=error_id,
            timestamp=time.time(),
            level=level,
            category=category,
            message=message,
            stack_trace=stack_trace,
            context=error_context,
            error_hash=self._hash_error(message, category)
        )
        
        # Check for deduplication
        if self._should_deduplicate(entry):
            return error_id
        
        # Attempt auto-recovery if enabled
        if auto_recover and level >= ErrorLevel.ERROR:
            self.executor.submit(self._attempt_recovery, entry)
        
        # Queue for async processing
        try:
            self.error_queue.put_nowait(entry)
        except queue.Full:
            # If queue is full, process synchronously
            self._process_error(entry)

        # Add to memory buffer for quick access
        self.error_buffer.append(entry)

        # Update statistics
        self._update_stats(entry)

        # Emit signal for UI updates
        if self.mode == 'development':
            self.error_logged.emit(asdict(entry))

        # Flush ERROR+ events to disk immediately so that a subsequent
        # crash or app exit (which is often what surfaced the error in
        # the first place) doesn't lose the entry that's sitting in the
        # 5-second flush_timer window.
        if level >= ErrorLevel.ERROR:
            self.flush()

        return error_id
    
    def _generate_error_id(self, message: str, stack_trace: Optional[str]) -> str:
        """Generate unique error ID"""
        content = f"{message}{stack_trace or ''}{time.time()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _hash_error(self, message: str, category: ErrorCategory) -> str:
        """Hash error for deduplication"""
        content = f"{category.value}:{message}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _should_deduplicate(self, entry: ErrorLogEntry) -> bool:
        """Check if error should be deduplicated"""
        if entry.error_hash in self.error_cache:
            cached = self.error_cache[entry.error_hash]
            if time.time() - cached.last_seen < self.dedup_window:
                cached.count += 1
                cached.last_seen = time.time()
                return True
        
        self.error_cache[entry.error_hash] = entry
        entry.first_seen = entry.timestamp
        entry.last_seen = entry.timestamp
        return False
    
    def _attempt_recovery(self, entry: ErrorLogEntry):
        """Attempt automatic recovery for the error"""
        for strategy in self.recovery_strategies:
            if strategy.can_recover(entry):
                entry.recovery_attempts += 1
                
                try:
                    if strategy.recover(entry):
                        entry.recovered = True
                        self.recovery_attempted.emit({
                            'error_id': entry.id,
                            'strategy': strategy.__class__.__name__,
                            'success': True
                        })
                        break
                except Exception as e:
                    # Recovery failed
                    self.log(
                        ErrorLevel.WARNING,
                        f"Recovery strategy failed: {e}",
                        ErrorCategory.SYSTEM,
                        context={'original_error': entry.id}
                    )
    
    def _process_error(self, entry: ErrorLogEntry):
        """Process and write error to file"""
        try:
            # Format log entry
            log_line = self._format_log_entry(entry)
            
            # Write to file
            if self.log_file_handle:
                self.log_file_handle.write(log_line + '\n')
                self.log_rotation_size += len(log_line)
                
                # Check if rotation needed
                if self.log_rotation_size > self.max_file_size:
                    self._rotate_log_file()
            
            # Special handling for migration errors (aggressive logging)
            if entry.category == ErrorCategory.MIGRATION:
                self._log_migration_error(entry)
            
        except Exception as e:
            # Last resort - print to console
            print(f"Error logger failed: {e}")
            print(f"Original error: {entry.message}")
    
    def _format_log_entry(self, entry: ErrorLogEntry) -> str:
        """Format error entry for file output.

        Single verbose-but-single-line format across all modes. Log
        files are never user-facing — they exist exclusively to debug
        problems — so dropping ``stack_trace`` and ``context.metadata``
        in production (as the old compact format did) left real-user
        failures un-diagnosable. We keep single-line JSON so the file
        stays grep-friendly while exposing every load-bearing field.
        """
        return json.dumps({
            'id': entry.id,
            'ts': entry.timestamp,
            'datetime': datetime.fromtimestamp(entry.timestamp).isoformat(),
            'lvl': entry.level.value,
            'level': entry.level.name,
            'cat': entry.category.value,
            'msg': entry.message,
            'stack_trace': entry.stack_trace,
            'context': asdict(entry.context) if entry.context else None,
            'count': entry.count,
            'recovered': entry.recovered,
            'recovery_attempts': entry.recovery_attempts,
        })
    
    def _log_migration_error(self, entry: ErrorLogEntry):
        """Special aggressive logging for migration errors"""
        with open(self.migration_log_file, 'a') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"MIGRATION ERROR - {datetime.now()}\n")
            f.write(f"{'='*80}\n")
            f.write(f"Message: {entry.message}\n")
            if entry.stack_trace:
                f.write(f"\nStack Trace:\n{entry.stack_trace}\n")
            if entry.context and entry.context.metadata:
                f.write(f"\nContext:\n{json.dumps(entry.context.metadata, indent=2)}\n")
            f.write(f"{'='*80}\n\n")
    
    def _update_stats(self, entry: ErrorLogEntry):
        """Update error statistics"""
        hour_key = datetime.fromtimestamp(entry.timestamp).strftime('%Y%m%d_%H')
        self.stats[hour_key][entry.level.name] += 1
        self.stats[hour_key][entry.category.value] += 1
        
        if entry.recovered:
            self.stats[hour_key]['recovered'] += 1
        
        # Emit stats update for UI
        self.stats_updated.emit(dict(self.stats[hour_key]))
    
    def flush(self):
        """Flush queued errors to disk"""
        processed = 0
        while not self.error_queue.empty() and processed < 100:
            try:
                entry = self.error_queue.get_nowait()
                self._process_error(entry)
                processed += 1
            except queue.Empty:
                break
        
        if self.log_file_handle:
            self.log_file_handle.flush()
    
    def get_recent_errors(self, 
                         count: int = 100,
                         level: Optional[ErrorLevel] = None,
                         category: Optional[ErrorCategory] = None) -> List[ErrorLogEntry]:
        """Get recent errors from memory buffer"""
        errors = list(self.error_buffer)
        
        if level:
            errors = [e for e in errors if e.level == level]
        if category:
            errors = [e for e in errors if e.category == category]
        
        return errors[-count:]
    
    def search_errors(self,
                     query: str,
                     start_time: Optional[float] = None,
                     end_time: Optional[float] = None) -> List[ErrorLogEntry]:
        """Search errors in memory buffer"""
        results = []
        for entry in self.error_buffer:
            if start_time and entry.timestamp < start_time:
                continue
            if end_time and entry.timestamp > end_time:
                continue
            if query.lower() in entry.message.lower():
                results.append(entry)
        
        return results
    
    def export_errors(self, 
                     output_file: Path,
                     format: str = 'json',
                     start_time: Optional[float] = None) -> bool:
        """Export errors to file"""
        try:
            errors = [e for e in self.error_buffer 
                     if not start_time or e.timestamp >= start_time]
            
            if format == 'json':
                with open(output_file, 'w') as f:
                    json.dump([asdict(e) for e in errors], f, indent=2)
            elif format == 'csv':
                import csv
                with open(output_file, 'w', newline='') as f:
                    if errors:
                        writer = csv.DictWriter(f, fieldnames=asdict(errors[0]).keys())
                        writer.writeheader()
                        for error in errors:
                            writer.writerow(asdict(error))
            
            return True
        except Exception as e:
            self.log(ErrorLevel.ERROR, f"Failed to export errors: {e}", ErrorCategory.SYSTEM)
            return False
    
    def get_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """Get error statistics for the last N hours"""
        cutoff = time.time() - (hours * 3600)
        recent_errors = [e for e in self.error_buffer if e.timestamp >= cutoff]
        
        stats = {
            'total': len(recent_errors),
            'by_level': defaultdict(int),
            'by_category': defaultdict(int),
            'recovered': sum(1 for e in recent_errors if e.recovered),
            'unique': len(set(e.error_hash for e in recent_errors)),
            'top_errors': []
        }
        
        for error in recent_errors:
            stats['by_level'][error.level.name] += 1
            stats['by_category'][error.category.value] += 1
        
        # Get top errors by count
        error_counts = defaultdict(int)
        for error in recent_errors:
            if error.error_hash:
                error_counts[error.message[:100]] += 1
        
        stats['top_errors'] = sorted(
            error_counts.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:10]
        
        return stats
    
    def cleanup(self):
        """Cleanup resources on shutdown"""
        self.running = False
        
        if self.flush_timer:
            self.flush_timer.stop()
        
        self.flush()
        
        if self.log_file_handle:
            self.log_file_handle.close()
        
        self.executor.shutdown(wait=True)
    
    # Convenience methods for different error levels
    def trace(self, message: str, **kwargs):
        return self.log(ErrorLevel.TRACE, message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        return self.log(ErrorLevel.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        return self.log(ErrorLevel.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        return self.log(ErrorLevel.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        return self.log(ErrorLevel.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        return self.log(ErrorLevel.CRITICAL, message, **kwargs)
    
    def fatal(self, message: str, **kwargs):
        return self.log(ErrorLevel.FATAL, message, **kwargs)
    
    class PythonLoggingHandler(logging.Handler):
        """Handler to redirect Python's logging to our error logger"""
        
        def __init__(self, error_logger):
            super().__init__()
            self.error_logger = error_logger
        
        def emit(self, record):
            level_map = {
                logging.DEBUG: ErrorLevel.DEBUG,
                logging.INFO: ErrorLevel.INFO,
                logging.WARNING: ErrorLevel.WARNING,
                logging.ERROR: ErrorLevel.ERROR,
                logging.CRITICAL: ErrorLevel.CRITICAL
            }
            
            level = level_map.get(record.levelno, ErrorLevel.INFO)
            
            self.error_logger.log(
                level=level,
                message=record.getMessage(),
                category=ErrorCategory.SYSTEM,
                stack_trace=self.format(record) if record.exc_info else None
            )
