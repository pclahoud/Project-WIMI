"""
Database Module
Provides database management for the PyQt6 Student Question Analysis App
"""

from .base_db import BaseDatabase, DatabaseConnectionError, DatabaseIntegrityError, BaseDatabaseError
from .master_db import MasterDatabase
from .user_db import UserDatabase
from .models import (
    # Master database models
    User, UserDatabaseSchema, AppSetting,
    # Phase 1 user database models
    UserPreferences, SubjectNode, QuestionAnalysis,
    QuestionTopicAssignment, Tag, QuestionTag,
    # Phase 2 user database models
    ExamContextConfig, HierarchyLevelDefinition,
    SubjectNodeWeight, WeightUpdateResult
)
from .exceptions import (
    # General exceptions
    DatabaseError,
    # Master database exceptions
    UserAlreadyExistsError,
    UserNotFoundError,
    DatabaseCreationError,
    InvalidUsernameError,
    DeletionError,
    InvalidUserTypeError,
    PrimaryAdminError,
    # Phase 1 user database exceptions
    ValidationError,
    SubjectNodeError,
    QuestionAnalysisError,
    TagError,
    PreferenceError,
    # Phase 2 user database exceptions
    ExamContextError,
    ExamContextAlreadyExistsError,
    ExamContextNotCreatedError,
    WeightValidationError,
    WeightBalancingError,
    HierarchyLevelError
)

__all__ = [
    # Base classes
    'BaseDatabase',
    'DatabaseConnectionError',
    'DatabaseIntegrityError',
    'BaseDatabaseError',

    # Database managers
    'MasterDatabase',
    'UserDatabase',
    
    # Master database models
    'User',
    'UserDatabaseSchema',
    'AppSetting',
    
    # Phase 1 user database models
    'UserPreferences',
    'SubjectNode',
    'QuestionAnalysis',
    'QuestionTopicAssignment',
    'Tag',
    'QuestionTag',
    
    # Phase 2 user database models
    'ExamContextConfig',
    'HierarchyLevelDefinition',
    'SubjectNodeWeight',
    'WeightUpdateResult',
    
    # General exceptions
    'DatabaseError',
    
    # Master database exceptions
    'UserAlreadyExistsError',
    'UserNotFoundError',
    'DatabaseCreationError',
    'InvalidUsernameError',
    'DeletionError',
    'InvalidUserTypeError',
    'PrimaryAdminError',
    
    # Phase 1 user database exceptions
    'ValidationError',
    'SubjectNodeError',
    'QuestionAnalysisError',
    'TagError',
    'PreferenceError',
    
    # Phase 2 user database exceptions
    'ExamContextError',
    'ExamContextAlreadyExistsError',
    'ExamContextNotCreatedError',
    'WeightValidationError',
    'WeightBalancingError',
    'HierarchyLevelError'
]

__version__ = '1.1.0'  # Updated for Phase 2
