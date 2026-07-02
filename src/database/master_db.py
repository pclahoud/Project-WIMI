"""
Master Database Manager
Handles user accounts, app settings, and cross-user relationships
"""
import re
import json
import time
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from .base_db import BaseDatabase, DatabaseConnectionError, DatabaseIntegrityError
from .exceptions import (
    UserAlreadyExistsError, UserNotFoundError, DatabaseCreationError,
    InvalidUsernameError, DeletionError, InvalidUserTypeError, PrimaryAdminError
)
from .models import User, UserDatabaseSchema, AppSetting
from .migration_runner import MigrationRunner
from app_logging import ErrorLevel, ErrorCategory, ErrorContext


class MasterDatabase(BaseDatabase):
    """
    Master database manager for user accounts and app-level data.
    
    Database location: ~/.wimi/users.db
    User databases: ~/.wimi/users/user_XXX_username.db
    """
    
    VALID_USER_TYPES = {'student', 'power_user', 'admin'}
    VALID_ACCOUNT_STATUSES = {'active', 'suspended', 'disabled', 'soft_deleted'}
    DELETION_GRACE_PERIOD_DAYS = 10
    
    def __init__(
        self,
        data_dir: Optional[Path] = None,
        error_logger: Optional[Any] = None
    ):
        """
        Initialize master database.
        
        Args:
            data_dir: Base data directory (defaults to ~/.wimi)
            error_logger: Error logger instance for error tracking
        """
        # Set up directories
        if data_dir is None:
            data_dir = Path.home() / '.wimi'
        
        self.data_dir = Path(data_dir)
        self.users_dir = self.data_dir / 'users'
        self.archive_dir = self.data_dir / 'archive'
        
        # Create directories if they don't exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(exist_ok=True)
        self.archive_dir.mkdir(exist_ok=True)
        
        # Set up error logger
        self.error_logger = error_logger
        
        # Initialize database connection
        db_path = self.data_dir / 'users.db'
        super().__init__(db_path)
        
        # Initialize schema if needed
        self._initialize_schema()
    
    def _initialize_schema(self) -> None:
        """Apply pending master-DB schema migrations via the versioned runner."""
        from .migrations.master import MIGRATIONS as MASTER_MIGRATIONS
        MigrationRunner(
            self.conn,
            MASTER_MIGRATIONS,
            scope="master",
            error_logger=self.error_logger,
        ).apply_pending()
    
    # ==================== User Management ====================
    
    def create_user(
        self,
        username: str,
        display_name: str,
        email: Optional[str] = None,
        user_types: Optional[List[str]] = None,
        is_primary_admin: bool = False
    ) -> User:
        """
        Create a new user account.
        
        Args:
            username: Unique username
            display_name: Display name for the user
            email: Optional email address
            user_types: List of user types (default: ['student'])
            is_primary_admin: Whether this is the primary admin
            
        Returns:
            Created User object
            
        Raises:
            UserAlreadyExistsError: If username or email already exists
            InvalidUsernameError: If username is invalid
            InvalidUserTypeError: If user_types contains invalid types
        """
        # Default to student if no types specified
        if user_types is None:
            user_types = ['student']
        
        # Validate inputs
        self._validate_username(username)
        self._validate_user_types(user_types)
        
        try:
            with self.transaction():
                # Check if primary admin already exists
                if is_primary_admin:
                    existing_admin = self.fetchone(
                        "SELECT id FROM users WHERE is_primary_admin = TRUE"
                    )
                    if existing_admin:
                        raise PrimaryAdminError("Primary admin already exists")
                
                # Generate database filename
                user_count = self._get_user_count() + 1
                sanitized = self._sanitize_username(username)
                db_filename = f"user_{user_count:03d}_{sanitized}.db"
                
                # Insert user record
                cursor = self.execute("""
                    INSERT INTO users (
                        username, display_name, email, user_type,
                        database_filename, account_status, is_primary_admin,
                        cloud_sync_enabled, cloud_user_id,
                        deletion_confirmed, database_encryption_enabled,
                        can_manage_users, can_view_all_statistics,
                        can_export_all_data, can_manage_app_settings,
                        current_schema_version
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, FALSE, NULL, FALSE, FALSE, ?, ?, ?, ?, '1.0.0')
                """, (
                    username,
                    display_name,
                    email,
                    json.dumps(user_types),
                    db_filename,
                    is_primary_admin,
                    'admin' in user_types,  # Admins can manage users
                    'admin' in user_types,  # Admins can view all stats
                    'admin' in user_types,  # Admins can export data
                    'admin' in user_types   # Admins can manage settings
                ))
                
                user_id = cursor.lastrowid
                
                # Create schema tracking record
                self.execute("""
                    INSERT INTO user_database_schemas (
                        user_id, database_filename, current_schema_version,
                        needs_migration, migration_backup_created
                    ) VALUES (?, ?, '1.0.0', FALSE, FALSE)
                """, (user_id, db_filename))
                
                if self.error_logger:
                    self.error_logger.info(
                        f"Created user: {username} (ID: {user_id})",
                        category=ErrorCategory.DATABASE
                    )
                
                return self.get_user(user_id)
        
        except DatabaseIntegrityError as e:
            if self.error_logger:
                self.error_logger.error(
                    f"User already exists: {username}",
                    category=ErrorCategory.DATABASE,
                    error=e
                )
            raise UserAlreadyExistsError(f"User '{username}' already exists") from e
    
    def get_user(self, user_id: Optional[int] = None, username: Optional[str] = None) -> Optional[User]:
        """
        Get user by ID or username.
        
        Args:
            user_id: User ID to fetch
            username: Username to fetch
            
        Returns:
            User object or None if not found
        """
        if user_id is not None:
            row = self.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        elif username is not None:
            row = self.fetchone("SELECT * FROM users WHERE username = ?", (username,))
        else:
            raise ValueError("Must provide either user_id or username")
        
        return User.from_db_row(row) if row else None
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username (convenience method)"""
        return self.get_user(username=username)
    
    def get_all_users(
        self,
        include_deleted: bool = False,
        account_status: Optional[str] = None
    ) -> List[User]:
        """
        Get all users.
        
        Args:
            include_deleted: Include soft-deleted users
            account_status: Filter by specific account status
            
        Returns:
            List of User objects
        """
        query = "SELECT * FROM users WHERE 1=1"
        params = []
        
        if not include_deleted:
            query += " AND account_status != 'soft_deleted'"
        
        if account_status:
            query += " AND account_status = ?"
            params.append(account_status)
        
        query += " ORDER BY created_at DESC"
        
        rows = self.fetchall(query, tuple(params) if params else None)
        return [User.from_db_row(row) for row in rows]
    
    def update_user(
        self,
        user_id: int,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        user_types: Optional[List[str]] = None,
        account_status: Optional[str] = None
    ) -> User:
        """
        Update user information.
        
        Args:
            user_id: User ID to update
            display_name: New display name
            email: New email
            user_types: New user types
            account_status: New account status
            
        Returns:
            Updated User object
            
        Raises:
            UserNotFoundError: If user doesn't exist
        """
        user = self.get_user(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        
        updates = []
        params = []
        
        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
        
        if email is not None:
            updates.append("email = ?")
            params.append(email)
        
        if user_types is not None:
            self._validate_user_types(user_types)
            updates.append("user_type = ?")
            params.append(json.dumps(user_types))
        
        if account_status is not None:
            if account_status not in self.VALID_ACCOUNT_STATUSES:
                raise ValueError(f"Invalid account status: {account_status}")
            updates.append("account_status = ?")
            params.append(account_status)
        
        if not updates:
            return user
        
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        
        with self.transaction():
            self.execute(query, tuple(params))
        
        return self.get_user(user_id)
    
    def soft_delete_user(self, user_id: int) -> None:
        """
        Soft delete a user (10-day grace period before permanent deletion).
        
        Args:
            user_id: User ID to delete
            
        Raises:
            UserNotFoundError: If user doesn't exist
            PrimaryAdminError: If attempting to delete primary admin
        """
        user = self.get_user(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        
        if user.is_primary_admin:
            raise PrimaryAdminError("Cannot delete primary admin")
        
        try:
            with self.transaction():
                self.execute("""
                    UPDATE users 
                    SET account_status = 'soft_deleted',
                        soft_deleted_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (user_id,))
                
                # Move user database to archive
                user_db_path = self.users_dir / user.database_filename
                if user_db_path.exists():
                    archive_path = self.archive_dir / user.database_filename
                    shutil.move(str(user_db_path), str(archive_path))
            
            if self.error_logger:
                self.error_logger.info(
                    f"Soft deleted user: {user.username}",
                    category=ErrorCategory.DATABASE
                )
        
        except Exception as e:
            if self.error_logger:
                self.error_logger.error(
                    f"Failed to soft delete user: {user.username}",
                    category=ErrorCategory.DATABASE,
                    error=e
                )
            raise DeletionError(f"Failed to delete user {user_id}") from e
    
    def confirm_user_deletion(self, user_id: int) -> None:
        """
        Confirm deletion of a soft-deleted user.
        User will be permanently deleted after grace period.
        
        Args:
            user_id: User ID to confirm deletion
        """
        with self.transaction():
            self.execute(
                "UPDATE users SET deletion_confirmed = TRUE WHERE id = ?",
                (user_id,)
            )
    
    def restore_user(self, user_id: int) -> User:
        """
        Restore a soft-deleted user within grace period.
        
        Args:
            user_id: User ID to restore
            
        Returns:
            Restored User object
            
        Raises:
            UserNotFoundError: If user doesn't exist
            DeletionError: If grace period has expired
        """
        user = self.get_user(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        
        if user.account_status != 'soft_deleted':
            raise DeletionError(f"User {user_id} is not deleted")
        
        # Check grace period
        if user.soft_deleted_at:
            grace_end = user.soft_deleted_at + timedelta(days=self.DELETION_GRACE_PERIOD_DAYS)
            if datetime.now() > grace_end and user.deletion_confirmed:
                raise DeletionError(f"Grace period expired for user {user_id}")
        
        try:
            with self.transaction():
                self.execute("""
                    UPDATE users 
                    SET account_status = 'active',
                        soft_deleted_at = NULL,
                        deletion_confirmed = FALSE
                    WHERE id = ?
                """, (user_id,))
                
                # Restore user database from archive
                archive_path = self.archive_dir / user.database_filename
                if archive_path.exists():
                    user_db_path = self.users_dir / user.database_filename
                    shutil.move(str(archive_path), str(user_db_path))
            
            return self.get_user(user_id)
        
        except Exception as e:
            if self.error_logger:
                self.error_logger.error(
                    f"Failed to restore user: {user.username}",
                    category=ErrorCategory.DATABASE,
                    error=e
                )
            raise DeletionError(f"Failed to restore user {user_id}") from e
    
    def permanently_delete_expired_users(self) -> List[int]:
        """
        Permanently delete users past grace period.
        Should be run periodically (e.g., daily cron job).
        
        Returns:
            List of deleted user IDs
        """
        cutoff_date = datetime.now() - timedelta(days=self.DELETION_GRACE_PERIOD_DAYS)
        
        # Find expired users
        rows = self.fetchall("""
            SELECT id, username, database_filename 
            FROM users 
            WHERE account_status = 'soft_deleted'
              AND deletion_confirmed = TRUE
              AND soft_deleted_at <= ?
        """, (cutoff_date.isoformat(),))
        
        deleted_ids = []
        
        for row in rows:
            user_id = row['id']
            username = row['username']
            db_filename = row['database_filename']
            
            try:
                with self.transaction():
                    # Delete user record
                    self.execute("DELETE FROM users WHERE id = ?", (user_id,))
                    
                    # Delete archived database file
                    archive_path = self.archive_dir / db_filename
                    if archive_path.exists():
                        archive_path.unlink()
                
                deleted_ids.append(user_id)
                
                if self.error_logger:
                    self.error_logger.info(
                        f"Permanently deleted user: {username}",
                        category=ErrorCategory.DATABASE
                    )
            
            except Exception as e:
                if self.error_logger:
                    self.error_logger.error(
                        f"Failed to permanently delete user: {username}",
                        category=ErrorCategory.DATABASE,
                        error=e
                    )
        
        return deleted_ids
    
    # ==================== User Database Management ====================
    
    def ensure_user_database(self, user_id: int) -> Path:
        """
        Ensure user database exists, create if needed (lazy creation).
        Call this before opening a user's database.
        
        Args:
            user_id: User ID
            
        Returns:
            Path to user database file
            
        Raises:
            UserNotFoundError: If user doesn't exist
            DatabaseCreationError: If database creation fails
        """
        user = self.get_user(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        
        user_db_path = self.users_dir / user.database_filename
        
        if not user_db_path.exists():
            try:
                self._create_user_database(user_id, user.username, user_db_path)
                
                # Verify creation
                if not user_db_path.exists():
                    raise DatabaseCreationError(
                        f"Database file not created: {user_db_path}"
                    )
                
                if self.error_logger:
                    self.error_logger.info(
                        f"Created user database: {user.database_filename}",
                        category=ErrorCategory.DATABASE
                    )
            
            except Exception as e:
                if self.error_logger:
                    self.error_logger.critical(
                        f"Failed to create user database for {user.username}",
                        category=ErrorCategory.DATABASE,
                        error=e
                    )
                raise DatabaseCreationError(
                    f"Failed to create database for user {user_id}"
                ) from e
        
        return user_db_path
    
    def _create_user_database(self, user_id: int, username: str, db_path: Path) -> None:
        """
        Create a new user database file with Phase 1 schema.
        
        Args:
            user_id: User ID
            username: Username for logging
            db_path: Path where database should be created
        """
        import sqlite3
        
        # Read Phase 1 user schema
        schema_path = Path(__file__).parent / 'schema' / 'user_db_schema_v1_phase1.sql'
        
        if not schema_path.exists():
            raise FileNotFoundError(f"User schema file not found: {schema_path}")
        
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        # Create and initialize database
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(schema_sql)
            conn.commit()
        finally:
            conn.close()
    
    # ==================== Bootstrap & First User ====================
    
    def bootstrap_first_user(
        self,
        username: str,
        display_name: str,
        email: Optional[str] = None
    ) -> User:
        """
        Create the first user (primary admin) during initial setup.
        
        Args:
            username: Admin username
            display_name: Admin display name
            email: Admin email
            
        Returns:
            Created admin User object
            
        Raises:
            PrimaryAdminError: If primary admin already exists
        """
        # Check if any users exist
        user_count = self._get_user_count()
        if user_count > 0:
            raise PrimaryAdminError("Users already exist, cannot bootstrap")
        
        return self.create_user(
            username=username,
            display_name=display_name,
            email=email,
            user_types=['admin', 'student'],
            is_primary_admin=True
        )
    
    # ==================== App Settings ====================
    
    def get_setting(self, setting_key: str) -> Optional[AppSetting]:
        """Get an app setting by key"""
        row = self.fetchone(
            "SELECT * FROM app_settings WHERE setting_key = ?",
            (setting_key,)
        )
        return AppSetting.from_db_row(row) if row else None
    
    def set_setting(
        self,
        setting_key: str,
        setting_value: str,
        setting_type: str = 'string',
        description: Optional[str] = None,
        requires_admin: bool = False,
        updated_by_user_id: Optional[int] = None
    ) -> AppSetting:
        """Set or update an app setting"""
        valid_types = {'string', 'integer', 'boolean', 'json'}
        if setting_type not in valid_types:
            raise ValueError(f"Invalid setting type: {setting_type}")
        
        with self.transaction():
            # Try to update existing
            self.execute("""
                INSERT INTO app_settings (
                    setting_key, setting_value, setting_type, description,
                    requires_admin, updated_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    setting_type = excluded.setting_type,
                    description = excluded.description,
                    requires_admin = excluded.requires_admin,
                    updated_by_user_id = excluded.updated_by_user_id,
                    updated_at = CURRENT_TIMESTAMP
            """, (setting_key, setting_value, setting_type, description, requires_admin, updated_by_user_id))
        
        return self.get_setting(setting_key)
    
    # ==================== Validation & Utilities ====================
    
    def _validate_username(self, username: str) -> None:
        """Validate username meets requirements"""
        if not username or len(username) < 3:
            raise InvalidUsernameError("Username must be at least 3 characters")
        
        if not re.match(r'^[a-zA-Z0-9_-]+$', username):
            raise InvalidUsernameError(
                "Username can only contain letters, numbers, hyphens, and underscores"
            )
    
    def _validate_user_types(self, user_types: List[str]) -> None:
        """Validate user types are valid"""
        invalid = set(user_types) - self.VALID_USER_TYPES
        if invalid:
            raise InvalidUserTypeError(
                f"Invalid user types: {invalid}. Valid types: {self.VALID_USER_TYPES}"
            )
    
    def _sanitize_username(self, username: str) -> str:
        """Sanitize username for use in filenames"""
        # Replace spaces with underscores
        sanitized = username.replace(' ', '_')
        # Remove any characters that aren't alphanumeric, underscore, or hyphen
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', sanitized)
        # Limit length to 50 characters for filesystem compatibility
        sanitized = sanitized[:50]
        return sanitized.lower()
    
    def _get_user_count(self) -> int:
        """Get total number of users (including deleted)"""
        result = self.fetchone("SELECT COUNT(*) as count FROM users")
        return result['count'] if result else 0
