"""
Shared test fixtures for MasterDatabase tests
"""
import pytest
import tempfile
from pathlib import Path
from database import MasterDatabase
from app_logging import ErrorLogger


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test databases"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    """Create a fresh MasterDatabase instance without error logger"""
    db = MasterDatabase(data_dir=temp_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def master_db_with_logger(temp_dir):
    """Create MasterDatabase with ErrorLogger for integration tests"""
    error_logger = ErrorLogger(
        app_name="TestApp",
        log_dir=temp_dir / "logs",
        mode='test'
    )
    db = MasterDatabase(data_dir=temp_dir, error_logger=error_logger)
    yield db, error_logger
    db.close()


@pytest.fixture
def admin_user(master_db):
    """Create and return a bootstrapped admin user"""
    return master_db.bootstrap_first_user(
        username="admin",
        display_name="Test Admin",
        email="admin@test.com"
    )


@pytest.fixture
def master_db_with_users(master_db):
    """Create MasterDatabase with pre-populated users"""
    admin = master_db.bootstrap_first_user(
        username="admin",
        display_name="Test Admin",
        email="admin@test.com"
    )
    
    student = master_db.create_user(
        username="student",
        display_name="Test Student",
        email="student@test.com",
        user_types=["student"]
    )
    
    tutor = master_db.create_user(
        username="tutor",
        display_name="Test Tutor",
        email="tutor@test.com",
        user_types=["power_user", "student"]
    )
    
    return master_db, admin, student, tutor
