"""
Base Database Class
Provides core database functionality for both Master and User databases
"""
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class BaseDatabaseError(Exception):
    """Base exception for database operations"""
    pass


class DatabaseConnectionError(BaseDatabaseError):
    """Raised when database connection fails"""
    pass


class DatabaseIntegrityError(BaseDatabaseError):
    """Raised when database integrity is violated"""
    pass


class BaseDatabase:
    """
    Base class for database operations.
    Provides connection management, transaction handling, and common utilities.
    """
    
    def __init__(self, db_path: str | Path):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to the SQLite database file
            
        Raises:
            DatabaseConnectionError: If connection fails
        """
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self._connect()
        
    def _connect(self) -> None:
        """Establish database connection with proper configuration"""
        try:
            self.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # Allow multi-threaded access
                timeout=10.0  # 10 second timeout
            )
            
            # Enable foreign keys
            self.conn.execute("PRAGMA foreign_keys = ON")
            
            # Use WAL mode for better concurrency
            self.conn.execute("PRAGMA journal_mode = WAL")
            
            # Row factory for dict-like access
            self.conn.row_factory = sqlite3.Row
            
            logger.info(f"Connected to database: {self.db_path}")
            
        except sqlite3.Error as e:
            raise DatabaseConnectionError(f"Failed to connect to {self.db_path}: {e}")
    
    def close(self) -> None:
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info(f"Closed database connection: {self.db_path}")
    
    @contextmanager
    def transaction(self):
        """
        Context manager for database transactions.
        
        Usage:
            with db.transaction():
                db.execute("INSERT ...")
                db.execute("UPDATE ...")
        """
        try:
            yield self.conn
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Transaction failed, rolled back: {e}")
            raise
    
    def execute(self, sql: str, params: Optional[Tuple | Dict] = None) -> sqlite3.Cursor:
        """
        Execute a single SQL statement.
        
        Args:
            sql: SQL statement to execute
            params: Optional parameters for the SQL statement
            
        Returns:
            Cursor object with query results
            
        Raises:
            DatabaseIntegrityError: If integrity constraint is violated
            BaseDatabaseError: For other database errors
        """
        try:
            if params:
                return self.conn.execute(sql, params)
            return self.conn.execute(sql)
        except sqlite3.IntegrityError as e:
            raise DatabaseIntegrityError(f"Integrity constraint violated: {e}")
        except sqlite3.Error as e:
            raise BaseDatabaseError(f"Database error: {e}")
    
    def execute_many(self, sql: str, params_list: List[Tuple | Dict]) -> None:
        """
        Execute the same SQL statement with multiple parameter sets.
        
        Args:
            sql: SQL statement to execute
            params_list: List of parameter tuples/dicts
        """
        try:
            self.conn.executemany(sql, params_list)
        except sqlite3.Error as e:
            raise BaseDatabaseError(f"Batch execution failed: {e}")
    
    def fetchone(self, sql: str, params: Optional[Tuple | Dict] = None) -> Optional[Dict]:
        """
        Execute query and fetch one result.
        
        Args:
            sql: SQL SELECT statement
            params: Optional parameters
            
        Returns:
            Dict-like Row object or None
        """
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def fetchall(self, sql: str, params: Optional[Tuple | Dict] = None) -> List[Dict]:
        """
        Execute query and fetch all results.
        
        Args:
            sql: SQL SELECT statement
            params: Optional parameters
            
        Returns:
            List of Dict-like Row objects
        """
        cursor = self.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_table_names(self) -> List[str]:
        """Get list of all tables in the database"""
        result = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row['name'] for row in result]
    
    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database"""
        result = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return result is not None
    
    def get_schema_version(self) -> str:
        """
        Get current schema version.
        Subclasses should override this if they track versions differently.
        """
        if not self.table_exists('schema_version'):
            return '0.0.0'
        
        result = self.fetchone(
            "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
        )
        return result['version'] if result else '0.0.0'
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection"""
        self.close()
    
    def __del__(self):
        """Ensure connection is closed on deletion"""
        self.close()
