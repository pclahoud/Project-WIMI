"""
Error Logging Manager for PyQt6 WebEngine Student App
Provides asynchronous, multi-environment error logging with automatic recovery
"""

import atexit
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
    
    # Top-level package loggers whose records are captured into the log
    # files. Modules log through logging.getLogger(__name__), so these
    # roots cover 'app.model_runtime', 'app.bridge',
    # 'database.base_db', 'wimi.graph', and anything added under them.
    # Add a new root here if a new top-level package starts logging.
    CAPTURED_LOGGER_ROOTS = ('app', 'database', 'wimi', 'wimi_test')

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
        # Guards the file handle: the flush ticker thread and the caller's
        # thread can both reach flush().
        self._flush_lock = threading.RLock()
        self._cleaned_up = False
        self._shutdown_hook_installed = False

        # Initialize
        self._initialize_logging()
        self._start_flush_timer()

        # Last-resort drain, and the ONLY one until #278. The Qt
        # aboutToQuit hook is meant to cover a normal app exit -- three
        # comments here, one test and CLAUDE.md all said it did -- and
        # nothing connected it; ``install_shutdown_hook`` now does, from
        # the two places that build a QApplication. This registration
        # still covers everything that hook cannot see: a headless run, a
        # test, the MCP server, and any exit that bypasses the event loop.
        # An undrained queue means a 0-byte log file, which is exactly how
        # this module's failures have always hidden.
        #
        # wait=False is load-bearing: joining the executor from an atexit
        # handler races concurrent.futures' own atexit hook and hangs the
        # interpreter. That stranded every WIMI subprocess the regression
        # harness spawned, so the whole scenario suite failed while each
        # scenario passed alone.
        atexit.register(self._atexit_drain)
    
    def _generate_session_id(self) -> str:
        """Generate unique session ID"""
        return f"{self.app_name}_{int(time.time())}_{os.getpid()}"
    
    def _initialize_logging(self):
        """Initialize the logging system"""
        # Redirect Python's built-in logging here.
        #
        # Attached to the app's PACKAGE roots, not logging.getLogger(app_name):
        # every module uses logging.getLogger(__name__) — 'app.model_runtime',
        # 'app.bridge', 'database.base_db', 'wimi.graph' — and none
        # of those are descendants of 'StudentApp', so a handler on that name
        # received nothing and all stdlib logging was invisible in the files.
        #
        # Package roots rather than the root logger: root would also capture
        # every third-party library at DEBUG and bury the app's own records.
        level = logging.DEBUG if self.mode == 'development' else logging.WARNING
        handler = self.PythonLoggingHandler(self)
        handler.setLevel(level)

        self.python_loggers = []
        for name in self.CAPTURED_LOGGER_ROOTS:
            captured = logging.getLogger(name)
            # A second ErrorLogger in the same process must not
            # double-attach and write every record twice.
            for existing in list(captured.handlers):
                if isinstance(existing, self.PythonLoggingHandler):
                    captured.removeHandler(existing)
            captured.addHandler(handler)
            # The default level for a fresh logger is NOTSET, which
            # inherits root's WARNING — that alone dropped every INFO
            # record before it reached the handler.
            captured.setLevel(level)
            self.python_loggers.append(captured)

        # Back-compat: code that reached for .python_logger still works.
        self.python_logger = self.python_loggers[0]

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
    
    class _FlushTicker:
        """Daemon-thread periodic flush.

        Replaces a ``QTimer``. ``main.py`` constructs the ErrorLogger
        *before* ``QApplication`` exists, and a QTimer created without an
        event loop never fires — verified: 8 s of event loop afterwards
        still produced a 0-byte log file. That is why every
        ``StudentApp_*.log`` was empty: records queued, nothing drained
        them, and only an explicit ``cleanup()`` ever wrote.

        A plain daemon thread has no such ordering requirement and works
        headlessly (tests, MCP server) where no QApplication exists at
        all.
        """

        def __init__(self, interval, flush):
            self._interval = max(0.05, float(interval))
            self._flush = flush
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._run, name='wimi-log-flush', daemon=True,
            )
            self._thread.start()

        def _run(self):
            while not self._stop.wait(self._interval):
                try:
                    self._flush()
                except Exception:  # noqa: BLE001 — a logging thread must
                    pass           # never take the app down

        def stop(self):
            self._stop.set()

    def _start_flush_timer(self):
        """Start periodic flushing (see :class:`_FlushTicker`)."""
        if self.flush_timer:
            self.flush_timer.stop()

        self.flush_timer = self._FlushTicker(self.flush_interval, self.flush)
    
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
        """Check if a record should be collapsed into an earlier identical one.

        Deduplication exists to stop a failing code path from filling the
        log with thousands of identical stack traces. It must NOT apply
        to routine events: an INFO record states that something
        happened, and a second occurrence is the information, not noise.

        Collapsing them destroyed the audit trail outright. Any path
        that logs one low-entropy line per occurrence -- "Connected to
        database: ...", a per-session commit line -- produced a single
        entry for N events, and the survivor still read ``count: 1``,
        because the increment below mutates the cached object in memory
        and never rewrites what is already on disk. The repeat left no
        trace at all, which is exactly the silent-logging failure this
        module has a history of.
        """
        if entry.level < ErrorLevel.WARNING:
            return False

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
    
    # Records one periodic pass will write before yielding the lock.
    FLUSH_BATCH = 100

    def flush(self, *, drain_all: bool = False):
        """Flush queued errors to disk.

        Serialized: the periodic ticker runs on a daemon thread while
        cleanup() and ERROR-level self-flushes run on the caller's, so
        without the lock two threads can interleave writes into the same
        file handle.

        ``drain_all`` empties the queue instead of stopping after
        ``FLUSH_BATCH``, and only the shutdown drain passes it.

        **The bound was silently losing records at shutdown** (#278).
        ``cleanup()`` called this once, so a queue holding more than
        ``FLUSH_BATCH`` entries had its tail discarded with no error
        anywhere -- measured at 250 records logged, 100 on disk, 150 gone,
        on every exit path including ``atexit``. 100-plus records inside
        one flush window is not exotic: a profile import alone emits 46
        (CLAUDE.md, Logging invariant 2), so a startup burst followed by a
        crash -- precisely when the log is worth having -- is the shape
        that loses the most.

        The bound stays for the periodic path on purpose. The ticker is a
        daemon thread firing every ``flush_interval`` seconds, and a
        producer logging faster than it writes must not be able to hold it
        inside one call for ever. At shutdown there is no next pass, so
        there is nothing for the bound to protect.

        The drain is still bounded, just generously: the queue cannot hold
        more than ``buffer_size`` entries, so that many iterations plus one
        batch of headroom is enough to empty whatever was present on entry
        without letting a live producer livelock a shutdown.
        """
        with self._flush_lock:
            processed = 0
            limit = (
                self.buffer_size + self.FLUSH_BATCH
                if drain_all else self.FLUSH_BATCH
            )
            while not self.error_queue.empty() and processed < limit:
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
    
    def install_shutdown_hook(self, app) -> bool:
        """Drain and close the log from Qt's ``aboutToQuit`` (#278).

        Called from the two places that construct a ``QApplication`` --
        ``app.main_window.run_application`` and ``app.main._run_test_mode``
        -- because this object is deliberately built *before* any
        QApplication exists (Logging invariant 4: a ``QTimer`` created
        without an event loop never fires, which is why the periodic flush
        is a daemon thread). So the hook cannot be installed in
        ``__init__``; it has to be offered to whoever owns the app.

        Takes the app as an argument rather than calling
        ``QApplication.instance()``: ``app_logging`` imports no GUI class
        and should not start, and a module that reaches for a global
        singleton is one that cannot be tested without one.

        Returns True when the connection was made. A ``False`` is not a
        failure to propagate -- ``atexit`` still drains -- and raising
        would make a logging detail able to stop a launch, which is the
        opposite of this module's job.

        **What the hook buys, since ``atexit`` already drains.** It drains
        and closes the file *inside the event loop*, while the process is
        healthy. ``atexit`` does not run on a fatal signal, on
        ``os._exit``, or when the interpreter dies in C -- and Qt teardown
        dying in C is measured in this repo, not hypothetical: #153's
        forced wrong profile-release order **dumped core**. A core dump in
        Qt teardown takes the whole log with it, including the records
        describing whatever caused it.

        **What it does not buy, so that nobody re-derives it wrongly.**
        ``cleanup``'s ``wait`` parameter joins the *executor*, which only
        runs recovery strategies; a record logged from one of those arrives
        after ``cleanup`` has already flushed and closed the handle, so
        ``wait=True`` protects nothing about the file. The synchronous part
        that matters is the queue drain, and that is synchronous on every
        path.

        **Why closing the file here does not truncate the log early.**
        ``cleanup`` closes the handle and detaches the package-root
        handler, so anything logged after ``aboutToQuit`` is dropped (the
        handler's ``_cleaned_up`` guard drops it quietly rather than
        raising). Checked rather than assumed: every quit path in this app
        reaches ``aboutToQuit`` *through* ``MainWindow.closeEvent`` -- the
        File > Exit action is wired to ``self.close``, and nothing anywhere
        calls ``QApplication.quit`` directly -- so the database closes and
        their log lines are queued before the drain. If a future menu item
        or signal ever calls ``quit()`` without closing the window, that
        stops being true.
        """
        if self._shutdown_hook_installed:
            return True

        connect = getattr(getattr(app, 'aboutToQuit', None), 'connect', None)
        if connect is None:
            return False

        try:
            connect(self.cleanup)
        except Exception:  # noqa: BLE001 - never block a launch
            return False

        self._shutdown_hook_installed = True
        return True

    def _atexit_drain(self):
        """Non-blocking drain for interpreter shutdown."""
        self.cleanup(wait=False)

    def cleanup(self, wait: bool = True):
        """Cleanup resources on shutdown.

        Idempotent, and that is what lets both drains coexist: reachable
        from the Qt ``aboutToQuit`` hook (``install_shutdown_hook``), from
        the ``atexit`` hook, and from tests. After a normal GUI exit the
        ``atexit`` pass is a no-op; after a SIGTERM -- which Qt does not
        handle, so no ``aboutToQuit`` is emitted and no ``closeEvent``
        runs -- ``atexit`` is the only pass there is. A second call must
        not raise on an already-closed handle, or a normal shutdown would
        print a spurious traceback.

        Connected to ``aboutToQuit`` as-is, so Qt calls it with no
        arguments and ``wait`` defaults to True. See
        ``install_shutdown_hook`` for what that does and does not buy.
        """
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self.running = False

        if self.flush_timer:
            try:
                self.flush_timer.stop()
            except Exception:  # noqa: BLE001 — never block shutdown
                pass

        try:
            # drain_all: this is the last pass, so the FLUSH_BATCH bound
            # has no next pass to protect and would simply discard the
            # queue's tail (#278).
            self.flush(drain_all=True)
        except Exception:  # noqa: BLE001
            pass

        if self.log_file_handle:
            try:
                self.log_file_handle.close()
            except Exception:  # noqa: BLE001
                pass

        # Detach from the package loggers BEFORE the executor dies.
        # The handler is installed on process-global logging state
        # (logging.getLogger('database') and friends) but its lifetime was
        # tied to nothing: cleanup() shut the executor down and left the
        # handler attached, so the next module to log an ERROR under any
        # captured root -- code with no ErrorLogger of its own, a
        # MasterDatabase built with error_logger=None -- routed into a
        # dead instance and raised "cannot schedule new futures after
        # shutdown" from inside an unrelated test.
        for captured in getattr(self, 'python_loggers', []):
            for existing in list(captured.handlers):
                if isinstance(existing, self.PythonLoggingHandler) and                         existing.error_logger is self:
                    try:
                        captured.removeHandler(existing)
                    except Exception:  # noqa: BLE001 - never block shutdown
                        pass
        self.python_loggers = []

        # cancel_futures so a recovery strategy that has been QUEUED but
        # not started is discarded rather than run while the app is
        # quitting. This matters because aboutToQuit calls us with the
        # default wait=True: NetworkRetryRecovery sleeps up to 16 s per
        # attempt and DatabaseLockRecovery up to ~2 s, so without this a
        # burst of ERROR records just before exit could stall the quit by
        # seconds -- and a backoff-and-retry begun during shutdown cannot
        # accomplish anything anyway. Anything already running is still
        # joined, bounding the wait to one in-flight strategy per worker.
        self.executor.shutdown(wait=wait, cancel_futures=True)
    
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

            # Belt and braces for the detach in cleanup(). A handler can
            # still outlive its logger by a route cleanup() never sees:
            # the ErrorLogger is a QObject, so Qt can destroy the C++ side
            # while this Python wrapper survives, and any call into it
            # then raises "wrapped C/C++ object ... has been deleted".
            # A logging handler must never take down the code that logged.
            if getattr(self.error_logger, '_cleaned_up', False):
                return
            try:
                self.error_logger.log(
                    level=level,
                    message=record.getMessage(),
                    category=ErrorCategory.SYSTEM,
                    stack_trace=self.format(record) if record.exc_info else None
                )
            except RuntimeError:
                # Dead executor or deleted QObject: drop the record.
                # Reporting it through logging would recurse into here.
                pass
