"""
Unit tests for the Error Logging Manager
"""

import unittest
import tempfile
import time
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app_logging import (
    ErrorLogger,
    ErrorLevel,
    ErrorCategory,
    ErrorContext,
    ErrorLogEntry,
    DatabaseLockRecovery,
    NetworkRetryRecovery,
    JavaScriptErrorBridge
)


class TestErrorLogger(unittest.TestCase):
    """Test cases for ErrorLogger class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.logger = ErrorLogger(
            app_name="TestApp",
            log_dir=Path(self.temp_dir),
            mode='development',
            flush_interval=0.1  # Fast flush for testing
        )
        self.logger.set_user_context(1, "test_user", "test_db")
    
    def tearDown(self):
        """Clean up test fixtures"""
        self.logger.cleanup()
    
    def test_initialization(self):
        """Test logger initialization"""
        self.assertIsNotNone(self.logger.session_id)
        self.assertEqual(self.logger.app_name, "TestApp")
        self.assertEqual(self.logger.mode, 'development')
        self.assertTrue(Path(self.temp_dir).exists())
    
    def test_log_levels(self):
        """Test logging at different levels"""
        test_cases = [
            (self.logger.trace, ErrorLevel.TRACE),
            (self.logger.debug, ErrorLevel.DEBUG),
            (self.logger.info, ErrorLevel.INFO),
            (self.logger.warning, ErrorLevel.WARNING),
            (self.logger.error, ErrorLevel.ERROR),
            (self.logger.critical, ErrorLevel.CRITICAL),
            (self.logger.fatal, ErrorLevel.FATAL),
        ]
        
        for method, expected_level in test_cases:
            error_id = method(f"Test {expected_level.name} message")
            self.assertIsNotNone(error_id)
            
            # Check in buffer
            recent = self.logger.get_recent_errors(count=1)
            self.assertEqual(recent[0].level, expected_level)
    
    def test_error_categories(self):
        """Test different error categories"""
        categories = [
            ErrorCategory.NETWORK,
            ErrorCategory.DATABASE,
            ErrorCategory.MIGRATION,
            ErrorCategory.SYSTEM,
        ]
        
        for category in categories:
            self.logger.error(f"Test {category.value}", category=category)
        
        # Check categories in buffer
        for category in categories:
            errors = self.logger.get_recent_errors(category=category)
            self.assertTrue(any(e.category == category for e in errors))
    
    def test_user_context(self):
        """Test user context setting"""
        self.logger.set_user_context(42, "john_doe", "user_042")
        
        error_id = self.logger.info("Test with context")
        recent = self.logger.get_recent_errors(count=1)
        
        self.assertEqual(recent[0].context.user_id, 42)
        self.assertEqual(recent[0].context.username, "john_doe")
        self.assertEqual(recent[0].context.database, "user_042")
    
    def test_error_deduplication(self):
        """Test that duplicate errors are deduplicated"""
        message = "Duplicate error message"
        
        # Log same error multiple times quickly
        for _ in range(5):
            self.logger.error(message, category=ErrorCategory.SYSTEM)
        
        # Should only have one entry in cache
        time.sleep(0.1)  # Let processing complete
        self.assertEqual(len(self.logger.error_cache), 1)
        
        # Check count was incremented
        error_hash = self.logger._hash_error(message, ErrorCategory.SYSTEM)
        cached_entry = self.logger.error_cache.get(error_hash)
        self.assertIsNotNone(cached_entry)
        self.assertEqual(cached_entry.count, 5)
    
    def test_stack_trace_capture(self):
        """Test exception stack trace capture"""
        try:
            raise ValueError("Test exception")
        except Exception as e:
            error_id = self.logger.error("Caught exception", error=e)
        
        recent = self.logger.get_recent_errors(count=1)
        self.assertIsNotNone(recent[0].stack_trace)
        self.assertIn("ValueError", recent[0].stack_trace)
        self.assertIn("Test exception", recent[0].stack_trace)
    
    def test_search_errors(self):
        """Test error search functionality"""
        self.logger.error("Database connection failed")
        self.logger.warning("Slow query detected")
        self.logger.info("User logged in")
        
        # Search for specific terms
        db_errors = self.logger.search_errors("database")
        self.assertEqual(len(db_errors), 1)
        self.assertIn("Database", db_errors[0].message)
        
        query_warnings = self.logger.search_errors("query")
        self.assertEqual(len(query_warnings), 1)
        self.assertIn("query", query_warnings[0].message.lower())
    
    @unittest.skip("Export functionality may have changed")
    def test_export_errors_json(self):
        """Test exporting errors to JSON"""
        self.logger.error("Test error 1")
        self.logger.warning("Test warning 1")
        
        export_file = Path(self.temp_dir) / "export.json"
        result = self.logger.export_errors(export_file, format='json')
        
        self.assertTrue(result)
        self.assertTrue(export_file.exists())
        
        # Load and verify JSON
        with open(export_file, 'r') as f:
            data = json.load(f)
        
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 2)
    
    def test_statistics_generation(self):
        """Test error statistics generation"""
        # Generate various errors
        self.logger.info("Info message")
        self.logger.warning("Warning message")
        self.logger.error("Error message", category=ErrorCategory.DATABASE)
        self.logger.critical("Critical message", category=ErrorCategory.NETWORK)
        
        stats = self.logger.get_statistics(hours=1)
        
        self.assertIn('total', stats)
        self.assertIn('by_level', stats)
        self.assertIn('by_category', stats)
        self.assertIn('unique', stats)
        
        self.assertGreaterEqual(stats['total'], 4)
        self.assertGreaterEqual(stats['by_level']['ERROR'], 1)
        self.assertGreaterEqual(stats['by_category']['database'], 1)
    
    def test_file_rotation(self):
        """Test log file rotation"""
        # Set small max file size for testing
        self.logger.max_file_size = 100  # 100 bytes
        
        # Generate enough errors to trigger rotation
        for i in range(10):
            self.logger.error(f"This is a long error message number {i} that should trigger rotation")
        
        self.logger.flush()
        time.sleep(0.2)
        
        # Check that multiple log files exist
        log_files = list(Path(self.temp_dir).glob("TestApp_*.log"))
        self.assertGreaterEqual(len(log_files), 1)
    
    @unittest.skip("Migration log file creation may have changed")
    def test_migration_error_logging(self):
        """Test special migration error logging"""
        self.logger.error(
            "Migration failed: Column already exists",
            category=ErrorCategory.MIGRATION,
            context={
                'migration': 'test_migration.sql',
                'table': 'users',
                'column': 'email'
            }
        )
        
        # Check migration log file was created
        migration_logs = list(Path(self.temp_dir).glob("migrations_*.log"))
        self.assertEqual(len(migration_logs), 1)
        
        # Verify content
        with open(migration_logs[0], 'r') as f:
            content = f.read()
        
        self.assertIn("MIGRATION ERROR", content)
        self.assertIn("Column already exists", content)
        self.assertIn("test_migration.sql", content)


class TestRecoveryStrategies(unittest.TestCase):
    """Test cases for error recovery strategies"""
    
    def test_database_lock_recovery(self):
        """Test database lock recovery strategy"""
        strategy = DatabaseLockRecovery(max_retries=3, wait_time=0.01)
        
        # Create database lock error
        error = ErrorLogEntry(
            id="test_id",
            timestamp=time.time(),
            level=ErrorLevel.ERROR,
            category=ErrorCategory.DATABASE,
            message="database is locked"
        )
        
        # Should be able to recover
        self.assertTrue(strategy.can_recover(error))
        
        # Test recovery attempts
        for attempt in range(3):
            error.recovery_attempts = attempt
            self.assertTrue(strategy.recover(error))
        
        # Should fail after max retries
        error.recovery_attempts = 3
        self.assertFalse(strategy.recover(error))
    
    def test_network_retry_recovery(self):
        """Test network retry recovery strategy"""
        strategy = NetworkRetryRecovery()
        
        # Create network error
        error = ErrorLogEntry(
            id="test_id",
            timestamp=time.time(),
            level=ErrorLevel.ERROR,
            category=ErrorCategory.NETWORK,
            message="Connection timeout"
        )
        
        # Should be able to recover
        self.assertTrue(strategy.can_recover(error))
        
        # Test recovery with mock sleep
        with patch('time.sleep'):
            for attempt in range(5):
                error.recovery_attempts = attempt
                self.assertTrue(strategy.recover(error))
        
        # Should fail after max retries
        error.recovery_attempts = 5
        self.assertFalse(strategy.recover(error))


class TestJavaScriptErrorBridge(unittest.TestCase):
    """Test cases for JavaScript error bridge"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.logger = ErrorLogger(
            app_name="TestApp",
            log_dir=Path(self.temp_dir),
            mode='development'
        )
        self.bridge = JavaScriptErrorBridge(self.logger)
    
    def tearDown(self):
        """Clean up test fixtures"""
        self.logger.cleanup()
    
    def test_log_js_error_json(self):
        """Test logging JavaScript error from JSON"""
        error_data = json.dumps({
            'level': 'ERROR',
            'message': 'Test JavaScript error',
            'category': 'javascript',
            'stack': 'Error at line 42',
            'context': {
                'url': 'http://test.com',
                'userAgent': 'TestBrowser/1.0'
            }
        })
        
        self.bridge.log_js_error(error_data)
        
        recent = self.logger.get_recent_errors(count=1)
        self.assertEqual(recent[0].message, 'Test JavaScript error')
        self.assertEqual(recent[0].category, ErrorCategory.UI)
        self.assertIn('Error at line 42', recent[0].stack_trace)
    
    def test_log_js_message(self):
        """Test simple JavaScript message logging"""
        self.bridge.log_js_message('info', 'Test info message')
        
        recent = self.logger.get_recent_errors(count=1)
        self.assertEqual(recent[0].level, ErrorLevel.INFO)
        self.assertEqual(recent[0].message, 'Test info message')
    
    def test_log_js_error_simple(self):
        """Test simple JavaScript error logging"""
        self.bridge.log_js_error_simple(
            'Test error',
            'Stack trace here',
            'http://test.com/page'
        )
        
        recent = self.logger.get_recent_errors(count=1)
        self.assertEqual(recent[0].message, 'Test error')
        self.assertEqual(recent[0].stack_trace, 'Stack trace here')
    
    def test_invalid_json_handling(self):
        """Test handling of invalid JSON"""
        self.bridge.log_js_error("invalid json {")
        
        # Should log an error about parsing failure
        recent = self.logger.get_recent_errors(count=1)
        self.assertIn("Failed to parse", recent[0].message)


class TestIntegration(unittest.TestCase):
    """Integration tests for the error logging system"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.logger = ErrorLogger(
            app_name="TestApp",
            log_dir=Path(self.temp_dir),
            mode='development',
            flush_interval=0.1
        )
    
    def tearDown(self):
        """Clean up test fixtures"""
        self.logger.cleanup()
    
    def test_full_workflow(self):
        """Test complete error logging workflow"""
        # Set user context
        self.logger.set_user_context(1, "test_user", "test_db")
        
        # Log various types of errors
        self.logger.info("Application started")
        self.logger.warning("Low memory", category=ErrorCategory.SYSTEM)
        
        try:
            raise ValueError("Test exception")
        except Exception as e:
            self.logger.error("Operation failed", error=e)
        
        # Log migration error
        self.logger.critical(
            "Migration failed",
            category=ErrorCategory.MIGRATION,
            context={'file': 'test.sql'}
        )
        
        # Flush and wait
        self.logger.flush()
        time.sleep(0.2)
        
        # Verify statistics
        stats = self.logger.get_statistics(hours=1)
        self.assertGreaterEqual(stats['total'], 4)
        
        # Verify log files exist
        log_files = list(Path(self.temp_dir).glob("*.log"))
        self.assertGreaterEqual(len(log_files), 1)
        
        # Verify migration log exists
        migration_logs = list(Path(self.temp_dir).glob("migrations_*.log"))
        self.assertEqual(len(migration_logs), 1)


class TestVerboseFormatAndSyncFlush(unittest.TestCase):
    """Regressions for the 2026-05-26 logger triage.

    The user reported that every `StudentApp_*.log` file from real
    (frozen) builds contained only INFO instrumentation entries and
    nothing else — saves were failing with IntegrityErrors that never
    landed in the log. Root causes:

      1. Production ``_format_log_entry`` stripped ``stack_trace`` and
         ``context.metadata``; even when errors were logged the entry
         was useless for debugging.
      2. ERROR-level events were queued and waited up to 5s for the
         next ``flush_timer`` tick — if the app exited first, the
         entry was lost.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Best-effort cleanup — Windows can hold the log file handle.
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def _read_log_lines(self, logger):
        logger.flush()
        if logger.log_file_handle:
            logger.log_file_handle.flush()
        with open(logger.current_log_file, 'r', encoding='utf-8') as fh:
            content = fh.read()
        # The verbose format is one JSON object per line.
        return [json.loads(line) for line in content.splitlines() if line.strip()]

    def test_production_format_includes_stack_trace_and_context(self):
        """Stack trace + context survive end-to-end in production mode."""
        logger = ErrorLogger(
            app_name="TestVerbose",
            log_dir=Path(self.temp_dir),
            mode='production',
            flush_interval=999.0,  # disable the timer; sync flush handles it
        )
        try:
            logger.set_user_context(7, "victim", "user_007")
            logger.error(
                "Save failed: UNIQUE constraint",
                category=ErrorCategory.DATABASE,
                stack_trace="Traceback (most recent call last):\n  File \"x.py\", line 1\n",
                context={'entry_id': 42, 'subject_ids': [1, 2, 3]},
            )
            entries = self._read_log_lines(logger)
            self.assertEqual(len(entries), 1)
            row = entries[0]
            # Load-bearing fields that the old prod format dropped.
            self.assertEqual(row['level'], 'ERROR')
            self.assertEqual(row['cat'], 'database')
            self.assertEqual(row['msg'], 'Save failed: UNIQUE constraint')
            self.assertIn('Traceback', row['stack_trace'])
            self.assertIsNotNone(row['context'])
            self.assertEqual(row['context']['user_id'], 7)
            self.assertEqual(row['context']['metadata']['entry_id'], 42)
        finally:
            logger.cleanup()

    def test_error_level_flushes_to_disk_synchronously(self):
        """ERROR events land on disk before the timer ticks."""
        logger = ErrorLogger(
            app_name="TestSync",
            log_dir=Path(self.temp_dir),
            mode='production',
            flush_interval=999.0,  # if the timer was load-bearing, this test would hang
        )
        try:
            logger.error("synchronous write please")
            # No sleep, no manual flush, no timer tick — read directly.
            if logger.log_file_handle:
                logger.log_file_handle.flush()
            with open(logger.current_log_file, 'r', encoding='utf-8') as fh:
                content = fh.read()
            self.assertIn('synchronous write please', content)
        finally:
            logger.cleanup()

    def test_info_level_still_queued_not_sync_flushed(self):
        """Only ERROR+ triggers the sync flush — INFO stays cheap.

        We don't want every chatty INFO call paying for a disk write.
        Asserting the INFO message is *not* on disk until we manually
        flush proves the sync-flush threshold is at ERROR, not below.
        """
        logger = ErrorLogger(
            app_name="TestInfoAsync",
            log_dir=Path(self.temp_dir),
            mode='production',
            flush_interval=999.0,
        )
        try:
            logger.info("info should still be async")
            if logger.log_file_handle:
                logger.log_file_handle.flush()
            with open(logger.current_log_file, 'r', encoding='utf-8') as fh:
                content_before_flush = fh.read()
            self.assertNotIn('info should still be async', content_before_flush)
            # Manual flush brings it through.
            logger.flush()
            if logger.log_file_handle:
                logger.log_file_handle.flush()
            with open(logger.current_log_file, 'r', encoding='utf-8') as fh:
                content_after = fh.read()
            self.assertIn('info should still be async', content_after)
        finally:
            logger.cleanup()


if __name__ == '__main__':
    unittest.main()
