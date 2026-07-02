#!/usr/bin/env python
"""
Quick start script for testing the Error Logger
Run this file to see the error logging system in action
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """Main entry point"""
    print("=" * 60)
    print("Student App - Error Logger Demo")
    print("=" * 60)
    print()
    
    # Check if PyQt6 is installed
    try:
        import PyQt6
        print("✓ PyQt6 is installed")
    except ImportError:
        print("✗ PyQt6 is not installed")
        print("  Please run: pip install -r requirements.txt")
        return 1
    
    # Check if logs directory exists
    logs_dir = project_root / "logs"
    if not logs_dir.exists():
        print(f"Creating logs directory: {logs_dir}")
        logs_dir.mkdir(parents=True, exist_ok=True)
    else:
        print(f"✓ Logs directory exists: {logs_dir}")
    
    print()
    print("Starting Error Logger Demo...")
    print("-" * 60)
    print()
    
    # Run the demo
    try:
        from examples.error_logger_demo import main as demo_main
        return demo_main()
    except Exception as e:
        print(f"Error running demo: {e}")
        print("\nTrying alternative: console-only demo...")
        return run_console_demo()

def run_console_demo():
    """Run a console-only demo if PyQt6 WebEngine is not available"""
    from src.app_logging import ErrorLogger, ErrorLevel, ErrorCategory
    
    print("\n" + "=" * 60)
    print("Console Error Logger Demo")
    print("=" * 60 + "\n")
    
    # Initialize logger
    logger = ErrorLogger(
        app_name="ConsoleDemo",
        mode='development'
    )
    
    # Set user context
    logger.set_user_context(1, "demo_user", "demo_db")
    
    # Demonstrate different log levels
    print("Testing different log levels:")
    print("-" * 40)
    
    logger.trace("This is a trace message")
    logger.debug("This is a debug message")
    logger.info("Application started successfully")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")
    
    print("\nTesting error categories:")
    print("-" * 40)
    
    # Test different categories
    logger.error("Database connection failed", category=ErrorCategory.DATABASE)
    logger.error("Network timeout", category=ErrorCategory.NETWORK)
    logger.error("Migration failed", category=ErrorCategory.MIGRATION)
    
    print("\nTesting exception handling:")
    print("-" * 40)
    
    # Test exception logging
    try:
        result = 1 / 0
    except ZeroDivisionError as e:
        logger.error("Division by zero caught", error=e, category=ErrorCategory.VALIDATION)
    
    print("\nTesting context metadata:")
    print("-" * 40)
    
    # Test with context
    logger.error(
        "Failed to save question",
        category=ErrorCategory.DATABASE,
        context={
            'question_id': 123,
            'user_action': 'save',
            'attempt': 3
        }
    )
    
    print("\nGenerating statistics:")
    print("-" * 40)
    
    # Get and display statistics
    stats = logger.get_statistics(hours=1)
    print(f"Total errors logged: {stats['total']}")
    print(f"Unique errors: {stats['unique']}")
    print("\nErrors by level:")
    for level, count in stats['by_level'].items():
        print(f"  {level}: {count}")
    print("\nErrors by category:")
    for category, count in stats['by_category'].items():
        print(f"  {category}: {count}")
    
    # Check log files
    print("\nLog files created:")
    print("-" * 40)
    
    logs_dir = Path(logger.log_dir)
    for log_file in logs_dir.glob("*.log"):
        size = log_file.stat().st_size
        print(f"  {log_file.name} ({size} bytes)")
    
    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print(f"Check the logs directory for output: {logs_dir}")
    print("=" * 60)
    
    # Cleanup
    logger.cleanup()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
