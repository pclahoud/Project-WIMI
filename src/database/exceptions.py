"""
Custom Database Exceptions
"""

from .base_db import BaseDatabaseError


class DatabaseError(Exception):
    """Base exception for all database errors"""
    pass


class UserAlreadyExistsError(DatabaseError):
    """Raised when attempting to create a user that already exists"""
    pass


class UserNotFoundError(DatabaseError):
    """Raised when user cannot be found"""
    pass


class DatabaseCreationError(DatabaseError):
    """Raised when user database file creation fails"""
    pass


class InvalidUsernameError(DatabaseError):
    """Raised when username doesn't meet requirements"""
    pass


class DeletionError(DatabaseError):
    """Raised when user deletion fails"""
    pass


class InvalidUserTypeError(DatabaseError):
    """Raised when invalid user type is specified"""
    pass


class PrimaryAdminError(DatabaseError):
    """Raised when attempting invalid operations on primary admin"""
    pass


# UserDatabase-specific exceptions

class PreferencesError(DatabaseError):
    """Raised when preferences operation fails"""
    pass


class ExamContextNotFoundError(DatabaseError):
    """Raised when exam context cannot be found"""
    pass


class PrimaryExamError(DatabaseError):
    """Raised when primary exam constraint is violated"""
    pass


class HierarchyVersionError(DatabaseError):
    """Raised when hierarchy version operation fails"""
    pass


class SubjectNodeNotFoundError(DatabaseError):
    """Raised when subject node cannot be found"""
    pass


class InvalidWeightError(DatabaseError):
    """Raised when weight values are invalid"""
    pass


class CircularReferenceError(DatabaseError):
    """Raised when operation would create circular reference in hierarchy"""
    pass


class InvalidHierarchyStructureError(DatabaseError):
    """Raised when hierarchy structure is invalid"""
    pass


# Phase 1 UserDatabase exceptions

class ValidationError(DatabaseError):
    """Raised when input validation fails"""
    pass


class SubjectNodeError(DatabaseError):
    """Raised when subject node operation fails"""
    pass


class QuestionAnalysisError(DatabaseError):
    """Raised when question analysis operation fails"""
    pass


class TagError(DatabaseError):
    """Raised when tag operation fails"""
    pass


class PreferenceError(DatabaseError):
    """Raised when preference operation fails"""
    pass


# ==================== Phase 2 Exceptions ====================

class ExamContextError(DatabaseError):
    """Raised when exam context operations fail"""
    pass


class ExamContextNotCreatedError(ExamContextError):
    """Raised when exam context creation fails"""
    pass


class ExamContextAlreadyExistsError(ExamContextError):
    """Raised when attempting to create a duplicate exam context"""
    pass


class WeightValidationError(ValidationError):
    """Raised when weight validation fails"""
    pass


class WeightBalancingError(WeightValidationError):
    """Raised when weight balancing calculation fails"""
    pass


class AllocationFeasibilityError(BaseDatabaseError):
    """Raised when Hamilton allocator inputs are structurally invalid.

    Reserved for *structural* bad input — negative weights, negative
    ``total_questions``, etc. Rounding-class infeasibility (the
    ``Σ⌈child_lo·N/100⌉ > ⌊parent_hi·N/100⌋`` case) is **not** an
    exception; it is surfaced as a return value by the Stage 7
    feasibility checker per
    ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.
    """
    pass


class HierarchyLevelError(DatabaseError):
    """Raised when hierarchy level operations fail"""
    pass


# ==================== Phase 4 Exceptions ====================

class ReviewSessionError(DatabaseError):
    """Raised when review session operations fail"""
    pass


class ReviewSessionNotFoundError(ReviewSessionError):
    """Raised when review session cannot be found"""
    pass


class QuestionEntryError(DatabaseError):
    """Raised when question entry operations fail"""
    pass


class QuestionEntryNotFoundError(QuestionEntryError):
    """Raised when question entry cannot be found"""
    pass


class QuestionSourceError(DatabaseError):
    """Raised when question source operations fail"""
    pass


class MediaError(DatabaseError):
    """Raised when media operations fail"""
    pass


# ==================== Phase 7 Exceptions ====================

class DimensionError(DatabaseError):
    """Raised when dimension operations fail"""
    pass


class DimensionNotFoundError(DimensionError):
    """Raised when dimension cannot be found"""
    pass


class DimensionAlreadyExistsError(DimensionError):
    """Raised when attempting to create a duplicate dimension"""
    pass


class HierarchyTagError(DatabaseError):
    """Raised when hierarchy tag operations fail"""
    pass


class HierarchyTagNotFoundError(HierarchyTagError):
    """Raised when hierarchy tag cannot be found"""
    pass


class DuplicateTagError(HierarchyTagError):
    """Raised when attempting to create a duplicate tag"""
    pass
