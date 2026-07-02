"""
Database Models - Dataclasses for type-safe database operations
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import json


@dataclass
class User:
    """User account representation"""
    id: int
    username: str
    display_name: str
    email: Optional[str]
    user_type: List[str]  # ["student", "power_user", "admin"]
    database_filename: str
    profile_image_path: Optional[str]
    account_status: str  # 'active', 'suspended', 'disabled', 'soft_deleted'
    is_primary_admin: bool
    cloud_sync_enabled: bool
    cloud_user_id: Optional[str]
    last_active_at: datetime
    created_at: datetime
    soft_deleted_at: Optional[datetime]
    deletion_confirmed: bool
    registered_devices: List[str] = field(default_factory=list)
    notification_tokens: List[str] = field(default_factory=list)
    database_encryption_enabled: bool = False
    can_manage_users: bool = False
    can_view_all_statistics: bool = False
    can_export_all_data: bool = False
    can_manage_app_settings: bool = False
    current_schema_version: str = "1.0.0"
    last_schema_check: Optional[datetime] = None
    schema_migration_history: List[Dict[str, Any]] = field(default_factory=list)
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'User':
        """Create User from database row"""
        return cls(
            id=row['id'],
            username=row['username'],
            display_name=row['display_name'],
            email=row.get('email'),
            user_type=json.loads(row['user_type']) if row.get('user_type') else [],
            database_filename=row['database_filename'],
            profile_image_path=row.get('profile_image_path'),
            account_status=row['account_status'],
            is_primary_admin=bool(row['is_primary_admin']),
            cloud_sync_enabled=bool(row['cloud_sync_enabled']),
            cloud_user_id=row.get('cloud_user_id'),
            last_active_at=datetime.fromisoformat(row['last_active_at']) if row.get('last_active_at') else datetime.now(),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            soft_deleted_at=datetime.fromisoformat(row['soft_deleted_at']) if row.get('soft_deleted_at') else None,
            deletion_confirmed=bool(row.get('deletion_confirmed', False)),
            registered_devices=json.loads(row['registered_devices']) if row.get('registered_devices') else [],
            notification_tokens=json.loads(row['notification_tokens']) if row.get('notification_tokens') else [],
            database_encryption_enabled=bool(row.get('database_encryption_enabled', False)),
            can_manage_users=bool(row.get('can_manage_users', False)),
            can_view_all_statistics=bool(row.get('can_view_all_statistics', False)),
            can_export_all_data=bool(row.get('can_export_all_data', False)),
            can_manage_app_settings=bool(row.get('can_manage_app_settings', False)),
            current_schema_version=row.get('current_schema_version', '1.0.0'),
            last_schema_check=datetime.fromisoformat(row['last_schema_check']) if row.get('last_schema_check') else None,
            schema_migration_history=json.loads(row['schema_migration_history']) if row.get('schema_migration_history') else []
        )
    
    def is_admin(self) -> bool:
        """Check if user has admin privileges"""
        return 'admin' in self.user_type
    
    def is_power_user(self) -> bool:
        """Check if user has power user privileges"""
        return 'power_user' in self.user_type
    
    def is_active(self) -> bool:
        """Check if user account is active"""
        return self.account_status == 'active'


@dataclass
class UserDatabaseSchema:
    """User database schema tracking"""
    id: int
    user_id: int
    database_filename: str
    current_schema_version: str
    last_migration_applied: Optional[str]
    migration_history: List[Dict[str, Any]]
    needs_migration: bool
    migration_backup_created: bool
    last_migration_check: datetime
    created_at: datetime
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'UserDatabaseSchema':
        """Create UserDatabaseSchema from database row"""
        return cls(
            id=row['id'],
            user_id=row['user_id'],
            database_filename=row['database_filename'],
            current_schema_version=row['current_schema_version'],
            last_migration_applied=row.get('last_migration_applied'),
            migration_history=json.loads(row['migration_history']) if row.get('migration_history') else [],
            needs_migration=bool(row['needs_migration']),
            migration_backup_created=bool(row['migration_backup_created']),
            last_migration_check=datetime.fromisoformat(row['last_migration_check']),
            created_at=datetime.fromisoformat(row['created_at'])
        )


@dataclass
class AppSetting:
    """Application setting"""
    id: int
    setting_key: str
    setting_value: str
    setting_type: str  # 'string', 'integer', 'boolean', 'json'
    description: Optional[str]
    is_system_setting: bool
    requires_admin: bool
    updated_by_user_id: Optional[int]
    updated_at: datetime
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'AppSetting':
        """Create AppSetting from database row"""
        return cls(
            id=row['id'],
            setting_key=row['setting_key'],
            setting_value=row['setting_value'],
            setting_type=row['setting_type'],
            description=row.get('description'),
            is_system_setting=bool(row['is_system_setting']),
            requires_admin=bool(row['requires_admin']),
            updated_by_user_id=row.get('updated_by_user_id'),
            updated_at=datetime.fromisoformat(row['updated_at'])
        )
    
    def get_typed_value(self) -> Any:
        """Get setting value with proper type conversion"""
        if self.setting_type == 'integer':
            return int(self.setting_value)
        elif self.setting_type == 'boolean':
            return self.setting_value.lower() in ('true', '1', 'yes')
        elif self.setting_type == 'json':
            return json.loads(self.setting_value)
        return self.setting_value


# ==================== UserDatabase Models ====================

@dataclass
class UserPreferences:
    """User preferences and settings (Phase 1)"""
    id: int
    user_id: int
    # UI/Visual Preferences
    theme_name: str = 'default'
    primary_color_hex: str = '#2196F3'
    secondary_color_hex: str = '#FFC107'
    font_family: str = 'system'
    font_size_scale: float = 1.0
    ui_density: str = 'comfortable'
    show_animations: bool = True
    # Question Review Session Defaults
    default_session_duration_minutes: int = 60
    default_break_interval_minutes: int = 25
    default_long_break_minutes: int = 15
    manual_break_control: bool = True
    long_break_interval_rounds: int = 4
    timer_display_size: str = 'normal'
    # Timer Keyboard Shortcuts
    hotkey_timer_pause_resume: str = 'Alt+P'
    hotkey_timer_new_round: str = 'Alt+N'
    hotkey_timer_end_round: str = 'Alt+E'
    # Analytics & Reporting
    analytics_detail_level: str = 'detailed'
    dashboard_auto_refresh_seconds: int = 300
    show_performance_trends: bool = True
    show_mistake_patterns: bool = True
    show_subject_breakdown: bool = True
    show_time_analytics: bool = True
    # Calendar
    calendar_default_view: str = 'week'
    calendar_time_slot_minutes: int = 30
    show_weekend_in_calendar: bool = True
    # Entry Review Window
    entry_review_items_per_page: int = 25
    entry_review_default_sort_field: str = 'answered_incorrectly_date'
    entry_review_default_sort_direction: str = 'desc'
    # AnkiConnect Integration
    anki_integration_enabled: bool = False
    ankiconnect_port: int = 8765
    # Data Management
    auto_backup_enabled: bool = True
    backup_frequency_hours: int = 24
    backup_retention_days: int = 30
    cloud_sync_enabled: bool = False
    # Performance
    realtime_update_delay_ms: int = 1500
    # MCP Server
    mcp_server_enabled: bool = False
    mcp_server_port: int = 8000
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'UserPreferences':
        """Create UserPreferences from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            user_id=row['user_id'],
            theme_name=row.get('theme_name', 'default'),
            primary_color_hex=row.get('primary_color_hex', '#2196F3'),
            secondary_color_hex=row.get('secondary_color_hex', '#FFC107'),
            font_family=row.get('font_family', 'system'),
            font_size_scale=float(row.get('font_size_scale', 1.0)),
            ui_density=row.get('ui_density', 'comfortable'),
            show_animations=bool(row.get('show_animations', True)),
            default_session_duration_minutes=row.get('default_session_duration_minutes', 60),
            default_break_interval_minutes=row.get('default_break_interval_minutes', 25),
            default_long_break_minutes=row.get('default_long_break_minutes', 15),
            manual_break_control=bool(row.get('manual_break_control', True)),
            long_break_interval_rounds=row.get('long_break_interval_rounds', 4),
            timer_display_size=row.get('timer_display_size', 'normal'),
            hotkey_timer_pause_resume=row.get('hotkey_timer_pause_resume', 'Alt+P'),
            hotkey_timer_new_round=row.get('hotkey_timer_new_round', 'Alt+N'),
            hotkey_timer_end_round=row.get('hotkey_timer_end_round', 'Alt+E'),
            analytics_detail_level=row.get('analytics_detail_level', 'detailed'),
            dashboard_auto_refresh_seconds=row.get('dashboard_auto_refresh_seconds', 300),
            show_performance_trends=bool(row.get('show_performance_trends', True)),
            show_mistake_patterns=bool(row.get('show_mistake_patterns', True)),
            show_subject_breakdown=bool(row.get('show_subject_breakdown', True)),
            show_time_analytics=bool(row.get('show_time_analytics', True)),
            calendar_default_view=row.get('calendar_default_view', 'week'),
            calendar_time_slot_minutes=row.get('calendar_time_slot_minutes', 30),
            show_weekend_in_calendar=bool(row.get('show_weekend_in_calendar', True)),
            entry_review_items_per_page=row.get('entry_review_items_per_page', 25),
            entry_review_default_sort_field=row.get('entry_review_default_sort_field', 'answered_incorrectly_date'),
            entry_review_default_sort_direction=row.get('entry_review_default_sort_direction', 'desc'),
            anki_integration_enabled=bool(row.get('anki_integration_enabled', False)),
            ankiconnect_port=row.get('ankiconnect_port', 8765),
            auto_backup_enabled=bool(row.get('auto_backup_enabled', True)),
            backup_frequency_hours=row.get('backup_frequency_hours', 24),
            backup_retention_days=row.get('backup_retention_days', 30),
            cloud_sync_enabled=bool(row.get('cloud_sync_enabled', False)),
            realtime_update_delay_ms=row.get('realtime_update_delay_ms', 1500),
            mcp_server_enabled=bool(row.get('mcp_server_enabled', False)),
            mcp_server_port=row.get('mcp_server_port', 8000),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else None
        )


@dataclass
class ExamContext:
    """Exam context definition"""
    id: int
    exam_name: str
    exam_code: Optional[str]
    exam_source: str
    is_active: bool
    is_primary: bool
    target_exam_date: Optional[date]
    created_at: datetime
    updated_at: datetime
    notes: Optional[str] = None
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'ExamContext':
        """Create ExamContext from database row"""
        return cls(
            id=row['id'],
            exam_name=row['exam_name'],
            exam_code=row.get('exam_code'),
            exam_source=row['exam_source'],
            is_active=bool(row['is_active']),
            is_primary=bool(row.get('is_primary', False)),
            target_exam_date=date.fromisoformat(row['target_exam_date']) if row.get('target_exam_date') else None,
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now(),
            notes=row.get('notes')
        )


@dataclass
class SubjectHierarchyVersion:
    """Subject hierarchy version tracking"""
    id: int
    exam_context_id: int
    version_number: int
    version_name: str
    is_active: bool
    created_at: datetime
    created_by: str  # 'manual', 'auto_launch', 'auto_close'
    notes: Optional[str] = None
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'SubjectHierarchyVersion':
        """Create SubjectHierarchyVersion from database row"""
        return cls(
            id=row['id'],
            exam_context_id=row['exam_context_id'],
            version_number=row['version_number'],
            version_name=row.get('version_name', ''),
            is_active=bool(row['is_active']),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            created_by=row.get('created_by', 'manual'),
            notes=row.get('notes')
        )


@dataclass
class SubjectNode:
    """
    Subject hierarchy node with hybrid weight support.
    
    Supports both official weight ranges (from authoritative sources) and
    relative weights for child subjects. The weight system follows these rules:
    
    1. Official ranges (exam_weight_low/high): Imported from authoritative sources,
       typically locked and cannot be edited by users.
    
    2. Relative weights: Used for child subjects within a parent that has official weights.
       Represents the proportion of the parent's weight.
    
    3. Weight source tracking: Distinguishes between official, derived, user_estimate,
       and user_defined weights.
    """
    id: int
    exam_context: str
    name: str
    parent_id: Optional[int]
    level_type: str
    sort_order: int
    
    # Absolute weight range (for official/top-level weights)
    exam_weight_low: Optional[float]
    exam_weight_high: Optional[float]
    exam_source: Optional[str]
    
    # Relative weight (for children within a parent with official weights)
    relative_weight: Optional[float] = None
    
    # Weight metadata
    weight_source: str = 'user_defined'  # 'official', 'derived', 'user_estimate', 'user_defined'
    weight_locked: bool = False
    
    # Other fields
    outline_type: str = 'content'
    status: str = 'active'
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    children: List['SubjectNode'] = field(default_factory=list)

    # Polyhierarchy: TRUE when this is a non-primary appearance of a node
    # that has multiple parent edges. The same canonical row appears once
    # under its primary parent (with alias=False) and once per non-primary
    # parent (with alias=True). Renderers use this to draw an "alias chip"
    # on duplicate appearances per docs/planning/POLYHIERARCHY_MIGRATION.md
    # §7.1. Set by get_subject_hierarchy; default False keeps legacy
    # consumers unaffected.
    is_alias_appearance: bool = False
    
    # Valid weight sources
    VALID_WEIGHT_SOURCES = {'official', 'derived', 'user_estimate', 'user_defined'}
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'SubjectNode':
        """Create SubjectNode from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            exam_context=row['exam_context'],
            name=row['name'],
            parent_id=row.get('parent_id'),
            level_type=row['level_type'],
            sort_order=row.get('sort_order', 1),
            exam_weight_low=float(row['exam_weight_low']) if row.get('exam_weight_low') is not None else None,
            exam_weight_high=float(row['exam_weight_high']) if row.get('exam_weight_high') is not None else None,
            exam_source=row.get('exam_source'),
            relative_weight=float(row['relative_weight']) if row.get('relative_weight') is not None else None,
            weight_source=row.get('weight_source', 'user_defined'),
            weight_locked=bool(row.get('weight_locked', False)),
            outline_type=row.get('outline_type', 'content'),
            status=row.get('status', 'active'),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now()
        )
    
    @property
    def has_absolute_weight(self) -> bool:
        """Check if node has absolute weight defined"""
        return self.exam_weight_low is not None
    
    @property
    def has_weight_range(self) -> bool:
        """Check if node has a weight range (low != high)"""
        return (
            self.exam_weight_low is not None and
            self.exam_weight_high is not None and
            self.exam_weight_low != self.exam_weight_high
        )
    
    @property
    def has_relative_weight(self) -> bool:
        """Check if node has relative weight defined"""
        return self.relative_weight is not None
    
    @property
    def weight_midpoint(self) -> Optional[float]:
        """Calculate midpoint of absolute weight range (for display only)"""
        if self.exam_weight_low is None:
            return None
        high = self.exam_weight_high if self.exam_weight_high is not None else self.exam_weight_low
        return (self.exam_weight_low + high) / 2.0
    
    @property
    def weight_range_width(self) -> float:
        """Get width of weight range (0 if single value)"""
        if self.has_weight_range:
            return self.exam_weight_high - self.exam_weight_low
        return 0.0
    
    @property
    def weight_display(self) -> str:
        """Get human-readable weight display string"""
        if self.has_absolute_weight:
            if self.has_weight_range:
                return f"{self.exam_weight_low}%–{self.exam_weight_high}%"
            return f"{self.exam_weight_low}%"
        if self.has_relative_weight:
            return f"{self.relative_weight}% (relative)"
        return "—"
    
    @property
    def is_official_weight(self) -> bool:
        """Check if this is an official weight from authoritative source"""
        return self.weight_source == 'official'
    
    @property
    def can_edit_weight(self) -> bool:
        """Check if weight can be edited (not locked)"""
        return not self.weight_locked
    
    def get_effective_weight(self, parent_midpoint: Optional[float] = None) -> Optional[float]:
        """
        Calculate effective absolute weight.
        
        For nodes with absolute weights, returns midpoint.
        For nodes with relative weights, calculates from parent's midpoint.
        
        Args:
            parent_midpoint: Parent's weight midpoint (required for relative weights)
            
        Returns:
            Effective weight as a percentage of the exam, or None if can't be calculated
        """
        if self.has_absolute_weight:
            return self.weight_midpoint
        
        if self.has_relative_weight and parent_midpoint is not None:
            return (self.relative_weight / 100.0) * parent_midpoint

        return None


@dataclass
class SubjectEdge:
    """
    A directed edge from a parent subject node to a child subject node.

    Foundation of the polyhierarchy migration described in
    ``docs/planning/POLYHIERARCHY_MIGRATION.md``. Replaces the strict
    ``subject_nodes.parent_id`` tree with a junction table that lets a
    single child have multiple parents within the same exam dimension.

    Per-edge attributes:

    - ``is_primary``: canonical parent for breadcrumbs/search. Each child
      has at most one primary edge.
    - ``display_order``: ordering of children under a parent (mirrors
      ``subject_nodes.sort_order`` semantically; backfilled from it).
    - ``is_anchor``, ``relative_weight``, ``weight_source``: per-edge
      weight metadata consumed by
      ``HIERARCHICAL_WEIGHT_ALLOCATION_REWORK.md`` once that plan
      lands. Defined here so the table shape is stable.
    """
    id: int
    parent_id: int
    child_id: int
    is_primary: bool = False
    display_order: int = 0
    is_anchor: bool = False
    relative_weight: Optional[float] = None
    weight_source: str = 'derived'
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Valid weight sources (matches the CHECK constraint on subject_edges.weight_source)
    VALID_WEIGHT_SOURCES = {
        'official', 'derived', 'user_estimate', 'user_defined', 'user_explicit'
    }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> Optional['SubjectEdge']:
        """Create SubjectEdge from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            parent_id=row['parent_id'],
            child_id=row['child_id'],
            is_primary=bool(row.get('is_primary', False)),
            display_order=row.get('display_order', 0),
            is_anchor=bool(row.get('is_anchor', False)),
            relative_weight=float(row['relative_weight']) if row.get('relative_weight') is not None else None,
            weight_source=row.get('weight_source', 'derived'),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'parent_id': self.parent_id,
            'child_id': self.child_id,
            'is_primary': self.is_primary,
            'display_order': self.display_order,
            'is_anchor': self.is_anchor,
            'relative_weight': self.relative_weight,
            'weight_source': self.weight_source,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class SubjectAlias:
    """
    Subject node alias for improved searchability.

    Supports multiple alias types:
    - eponym: Named after a person (e.g., "Parkinson's" for "Parkinsonism")
    - acronym: Abbreviations/acronyms (e.g., "MI" for "Myocardial Infarction")
    - alternate_name: Official alternate names
    - colloquial: Common/slang terms (e.g., "heart attack" for "Myocardial Infarction")

    Aliases are scoped per exam context and support case-insensitive matching.
    """
    id: int
    subject_node_id: int
    exam_context: str
    alias_name: str
    alias_type: str  # 'eponym', 'acronym', 'alternate_name', 'colloquial'
    is_primary: bool = False
    usage_count: int = 0
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Valid alias types
    VALID_ALIAS_TYPES = {'eponym', 'acronym', 'alternate_name', 'colloquial'}

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> Optional['SubjectAlias']:
        """Create SubjectAlias from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            subject_node_id=row['subject_node_id'],
            exam_context=row['exam_context'],
            alias_name=row['alias_name'],
            alias_type=row.get('alias_type', 'alternate_name'),
            is_primary=bool(row.get('is_primary', False)),
            usage_count=row.get('usage_count', 0),
            notes=row.get('notes'),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else None
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'subject_node_id': self.subject_node_id,
            'exam_context': self.exam_context,
            'alias_name': self.alias_name,
            'alias_type': self.alias_type,
            'is_primary': self.is_primary,
            'usage_count': self.usage_count,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @property
    def type_display(self) -> str:
        """Get human-readable type name"""
        type_names = {
            'eponym': 'Eponym',
            'acronym': 'Acronym/Abbreviation',
            'alternate_name': 'Alternate Name',
            'colloquial': 'Common/Slang'
        }
        return type_names.get(self.alias_type, self.alias_type)


# Legacy alias for backward compatibility
NodeAlias = SubjectAlias


# ==================== Phase 1 Question Analysis Models ====================

@dataclass
class QuestionAnalysis:
    """Question analysis entry (Phase 1)"""
    id: int
    exam_context: str
    question_source: str
    question_source_id: str
    answered_incorrectly_date: date
    user_selected_answer: Optional[str]
    correct_answer: Optional[str]
    perceived_difficulty: Optional[int]
    metacognitive_reflection: Optional[str]
    question_explanation: Optional[str]
    user_notes: Optional[str]
    time_spent_on_question: Optional[int]
    confidence_before_answer: Optional[int]
    mistake_category: Optional[str]
    review_status: str
    created_at: datetime
    updated_at: datetime
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'QuestionAnalysis':
        """Create QuestionAnalysis from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            exam_context=row['exam_context'],
            question_source=row['question_source'],
            question_source_id=row['question_source_id'],
            answered_incorrectly_date=date.fromisoformat(row['answered_incorrectly_date']) if row.get('answered_incorrectly_date') else None,
            user_selected_answer=row.get('user_selected_answer'),
            correct_answer=row.get('correct_answer'),
            perceived_difficulty=row.get('perceived_difficulty'),
            metacognitive_reflection=row.get('metacognitive_reflection'),
            question_explanation=row.get('question_explanation'),
            user_notes=row.get('user_notes'),
            time_spent_on_question=row.get('time_spent_on_question'),
            confidence_before_answer=row.get('confidence_before_answer'),
            mistake_category=row.get('mistake_category'),
            review_status=row.get('review_status', 'pending_review'),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now()
        )


@dataclass
class QuestionTopicAssignment:
    """Assignment of question to subject node (Phase 1)"""
    id: int
    question_analysis_id: int
    subject_node_id: int
    exam_context: str
    assignment_type: str  # 'primary', 'secondary'
    relevance_score: Optional[int]
    assigned_at: datetime
    assigned_by: str  # 'user', 'auto_suggested'
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'QuestionTopicAssignment':
        """Create QuestionTopicAssignment from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            question_analysis_id=row['question_analysis_id'],
            subject_node_id=row['subject_node_id'],
            exam_context=row['exam_context'],
            assignment_type=row.get('assignment_type', 'primary'),
            relevance_score=row.get('relevance_score'),
            assigned_at=datetime.fromisoformat(row['assigned_at']) if row.get('assigned_at') else datetime.now(),
            assigned_by=row.get('assigned_by', 'user')
        )


@dataclass
class Tag:
    """Tag for categorization (Phase 1)"""
    id: int
    exam_context: str
    tag_name: str
    tag_category: str  # 'mistake_type', 'study_method', 'content_type', 'difficulty', 'strategy', 'personal', 'other'
    color_hex: str
    description: Optional[str]
    usage_count: int
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime]
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'Tag':
        """Create Tag from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            exam_context=row['exam_context'],
            tag_name=row['tag_name'],
            tag_category=row.get('tag_category', 'other'),
            color_hex=row.get('color_hex', '#2196F3'),
            description=row.get('description'),
            usage_count=row.get('usage_count', 0),
            is_active=bool(row.get('is_active', True)),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            last_used_at=datetime.fromisoformat(row['last_used_at']) if row.get('last_used_at') else None
        )


@dataclass
class QuestionTag:
    """Assignment of tag to question (Phase 1)"""
    id: int
    question_analysis_id: int
    tag_id: int
    exam_context: str
    assigned_by: str  # 'user', 'auto_suggestion', 'pattern_detection'
    confidence_score: Optional[float]
    assigned_at: datetime
    last_reviewed_at: Optional[datetime]
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'QuestionTag':
        """Create QuestionTag from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            question_analysis_id=row['question_analysis_id'],
            tag_id=row['tag_id'],
            exam_context=row['exam_context'],
            assigned_by=row.get('assigned_by', 'user'),
            confidence_score=float(row['confidence_score']) if row.get('confidence_score') is not None else None,
            assigned_at=datetime.fromisoformat(row['assigned_at']) if row.get('assigned_at') else datetime.now(),
            last_reviewed_at=datetime.fromisoformat(row['last_reviewed_at']) if row.get('last_reviewed_at') else None
        )


# ==================== Phase 2 Models: Exam Context & Weight Management ====================

@dataclass
class ExamContextConfig:
    """
    Exam context configuration with weight validation rules (Phase 2).
    
    This replaces the simple exam_context string with a full configuration object
    that stores exam setup, hierarchy definitions, and weight calculation rules.
    """
    id: int
    user_id: int
    exam_name: str
    exam_description: Optional[str]
    exam_date: Optional[date]
    created_date: date
    is_active: bool
    default_hierarchy_levels: List[str]
    weight_validation_rules: Dict[str, Any]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Stage 4 (Hierarchical Weight Allocation): exam-length triple.
    # Migration ``m007_exam_length_triple`` adds these five columns to
    # ``exam_contexts``. ``length_kind`` is the discriminant; the other
    # four are nullable. Cross-column validation is enforced in
    # ``ExamContextMixin.update_exam_length`` (SQLite cannot reference
    # multiple columns in a single CHECK without losing message clarity).
    length_kind: str = 'unknown'
    length_min: Optional[int] = None
    length_max: Optional[int] = None
    length_typical: Optional[int] = None
    length_note: Optional[str] = None

    # Default weight validation rules
    DEFAULT_WEIGHT_RULES: Dict[str, Any] = field(default_factory=lambda: {
        "autonomous_weight_balancing": True,
        "allow_absolute_weight_editing": False,
        "precision_decimal_places": 1,
        "require_exact_100": True,
        "balancing_algorithm": "proportional"
    })
    
    # Default hierarchy levels
    DEFAULT_HIERARCHY_LEVELS: List[str] = field(default_factory=lambda: ["System", "Subsystem", "Topic", "Subtopic", "Child"])
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'ExamContextConfig':
        """Create ExamContextConfig from database row"""
        if not row:
            return None
        
        default_rules = {
            "autonomous_weight_balancing": True,
            "allow_absolute_weight_editing": False,
            "precision_decimal_places": 1,
            "require_exact_100": True,
            "balancing_algorithm": "proportional"
        }
        default_levels = ["System", "Subsystem", "Topic", "Subtopic", "Child"]
        
        # Stage 4 length-triple columns may be absent on a row that was
        # produced by an old query/cache. ``BaseDatabase.fetchone`` /
        # ``fetchall`` always materialize rows as ``dict``, so ``.get``
        # is safe; defaulting to ``None`` (or ``'unknown'`` for the
        # discriminant) keeps consumers happy for unmigrated paths too.
        length_kind = row.get('length_kind') or 'unknown'

        return cls(
            id=row['id'],
            user_id=row['user_id'],
            exam_name=row['exam_name'],
            exam_description=row.get('exam_description'),
            exam_date=date.fromisoformat(row['exam_date']) if row.get('exam_date') else None,
            created_date=date.fromisoformat(row['created_date']) if row.get('created_date') else date.today(),
            is_active=bool(row.get('is_active', True)),
            default_hierarchy_levels=json.loads(row['default_hierarchy_levels']) if row.get('default_hierarchy_levels') else default_levels,
            weight_validation_rules=json.loads(row['weight_validation_rules']) if row.get('weight_validation_rules') else default_rules,
            notes=row.get('notes'),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now(),
            length_kind=length_kind,
            length_min=row.get('length_min'),
            length_max=row.get('length_max'),
            length_typical=row.get('length_typical'),
            length_note=row.get('length_note'),
        )
    
    @property
    def autonomous_balancing(self) -> bool:
        """Check if autonomous weight balancing is enabled"""
        return self.weight_validation_rules.get('autonomous_weight_balancing', True)
    
    @property
    def precision(self) -> int:
        """Get weight precision (decimal places)"""
        return self.weight_validation_rules.get('precision_decimal_places', 1)
    
    @property
    def balancing_algorithm(self) -> str:
        """Get weight balancing algorithm ('proportional' or 'even')"""
        return self.weight_validation_rules.get('balancing_algorithm', 'proportional')
    
    @property
    def requires_exact_100(self) -> bool:
        """Check if children must sum to exactly 100%"""
        return self.weight_validation_rules.get('require_exact_100', True)


@dataclass
class HierarchyLevelDefinition:
    """
    Hierarchy level definition for an exam context (Phase 2).
    
    Defines the naming and configuration of each hierarchy level,
    supporting custom levels beyond the default 5.
    """
    id: int
    exam_context_id: int
    level_name: str
    level_order: int
    is_required: bool
    display_name_template: Optional[str]
    is_custom_level: bool
    created_date: date
    created_at: datetime
    updated_at: datetime
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'HierarchyLevelDefinition':
        """Create HierarchyLevelDefinition from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            exam_context_id=row['exam_context_id'],
            level_name=row['level_name'],
            level_order=row['level_order'],
            is_required=bool(row.get('is_required', False)),
            display_name_template=row.get('display_name_template'),
            is_custom_level=bool(row.get('is_custom_level', False)),
            created_date=date.fromisoformat(row['created_date']) if row.get('created_date') else date.today(),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now()
        )
    
    def get_display_name(self, parent_name: Optional[str] = None) -> str:
        """
        Get display name, optionally with parent name substitution.
        
        For custom levels with template like "Daughter of {parent_name}",
        substitutes the actual parent name.
        """
        if self.display_name_template and parent_name:
            return self.display_name_template.format(parent_name=parent_name)
        return self.level_name


@dataclass
class SubjectNodeWeight:
    """
    Weight change history record for a subject node (Phase 2).
    
    Provides complete audit trail for weight changes, enabling
    undo functionality and analytics on weight adjustments.
    """
    id: int
    subject_node_id: int
    weight_value: float
    edited_date: date
    edited_by: str  # 'user', 'system', 'import', 'migration'
    edited_reason: Optional[str]
    previous_weight: Optional[float]
    change_type: str  # 'initial', 'manual_edit', 'auto_recalculate', 'parent_redistribution', 'import', 'bulk_update'
    affected_siblings: List[int]
    user_notes: Optional[str]
    created_at: datetime
    
    # Valid change types
    VALID_CHANGE_TYPES = {
        'initial',
        'manual_edit',
        'auto_recalculate',
        'parent_redistribution',
        'import',
        'bulk_update'
    }
    
    # Valid edited_by values
    VALID_EDITORS = {'user', 'system', 'import', 'migration'}
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'SubjectNodeWeight':
        """Create SubjectNodeWeight from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            subject_node_id=row['subject_node_id'],
            weight_value=float(row['weight_value']),
            edited_date=date.fromisoformat(row['edited_date']) if row.get('edited_date') else date.today(),
            edited_by=row.get('edited_by', 'user'),
            edited_reason=row.get('edited_reason'),
            previous_weight=float(row['previous_weight']) if row.get('previous_weight') is not None else None,
            change_type=row.get('change_type', 'initial'),
            affected_siblings=json.loads(row['affected_siblings']) if row.get('affected_siblings') else [],
            user_notes=row.get('user_notes'),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now()
        )
    
    @property
    def weight_delta(self) -> Optional[float]:
        """Calculate weight change from previous value"""
        if self.previous_weight is not None:
            return self.weight_value - self.previous_weight
        return None
    
    @property
    def is_user_edit(self) -> bool:
        """Check if this was a direct user edit"""
        return self.edited_by == 'user' and self.change_type == 'manual_edit'
    
    @property
    def is_auto_adjustment(self) -> bool:
        """Check if this was an automatic system adjustment"""
        return self.change_type in ('auto_recalculate', 'parent_redistribution')


@dataclass
class WeightUpdateResult:
    """
    Result of a weight update operation (Phase 2).
    
    Contains information about the updated node and any
    sibling nodes that were automatically adjusted.
    """
    updated_node: SubjectNode
    affected_siblings: List[SubjectNode]
    total_updates: int
    weight_history_ids: List[int]
    
    @property
    def had_side_effects(self) -> bool:
        """Check if the update affected sibling nodes"""
        return len(self.affected_siblings) > 0


# ==================== Phase 4 Models: Question Entry System ====================

@dataclass
class QuestionSource:
    """
    Question source (question bank, textbook, etc.) - Phase 4.
    
    Tracks the sources from which users encounter questions,
    allowing categorization and statistics per source.
    """
    id: int
    user_id: int
    source_name: str
    source_type: str  # 'official_prep', 'commercial_prep', 'textbook', etc.
    exam_context: Optional[str]
    description: Optional[str]
    url: Optional[str]
    total_questions: Optional[int]
    user_rating: Optional[int]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    # Valid source types
    VALID_SOURCE_TYPES = {
        'official_prep', 'commercial_prep', 'textbook', 'online_platform',
        'practice_tests', 'tutoring_materials', 'flashcard_system',
        'video_course', 'study_group', 'previous_exams', 'other'
    }
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'QuestionSource':
        """Create QuestionSource from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            user_id=row['user_id'],
            source_name=row['source_name'],
            source_type=row.get('source_type', 'other'),
            exam_context=row.get('exam_context'),
            description=row.get('description'),
            url=row.get('url'),
            total_questions=row.get('total_questions'),
            user_rating=row.get('user_rating'),
            is_active=bool(row.get('is_active', True)),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now()
        )


@dataclass
class ReviewSession:
    """
    Review session for analyzing practice test mistakes - Phase 4.
    
    Groups multiple question entries from a single study session,
    tracking completion progress and session metadata.
    """
    id: int
    user_id: int
    exam_context_id: int
    question_source_id: Optional[int]
    session_name: Optional[str]
    date_encountered: date
    total_questions: int
    total_incorrect: int
    entries_completed: int
    session_status: str  # 'in_progress', 'completed', 'abandoned'
    started_at: datetime
    completed_at: Optional[datetime]
    last_activity_at: datetime
    created_at: datetime
    updated_at: datetime
    
    # Additional fields from joins (optional)
    exam_name: Optional[str] = None
    source_name: Optional[str] = None
    session_duration_minutes: Optional[int] = None
    total_break_seconds: int = 0
    timer_paused_at: Optional[str] = None

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'ReviewSession':
        """Create ReviewSession from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            user_id=row['user_id'],
            exam_context_id=row['exam_context_id'],
            question_source_id=row.get('question_source_id'),
            session_name=row.get('session_name'),
            date_encountered=date.fromisoformat(row['date_encountered']) if row.get('date_encountered') else date.today(),
            total_questions=row['total_questions'],
            total_incorrect=row['total_incorrect'],
            entries_completed=row.get('entries_completed', 0),
            session_status=row.get('session_status', 'in_progress'),
            started_at=datetime.fromisoformat(row['started_at']) if row.get('started_at') else datetime.now(),
            completed_at=datetime.fromisoformat(row['completed_at']) if row.get('completed_at') else None,
            last_activity_at=datetime.fromisoformat(row['last_activity_at']) if row.get('last_activity_at') else datetime.now(),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now(),
            exam_name=row.get('exam_name'),
            source_name=row.get('source_name'),
            session_duration_minutes=row.get('session_duration_minutes'),
            total_break_seconds=row.get('total_break_seconds', 0) or 0,
            timer_paused_at=row.get('timer_paused_at')
        )
    
    @property
    def is_complete(self) -> bool:
        """Check if all entries are completed"""
        return self.entries_completed >= self.total_incorrect
    
    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage"""
        if self.total_incorrect == 0:
            return 100.0
        return round(self.entries_completed / self.total_incorrect * 100, 1)
    
    @property
    def remaining_entries(self) -> int:
        """Calculate remaining entries to complete"""
        return max(0, self.total_incorrect - self.entries_completed)


@dataclass
class TimerRound:
    """A single timed round within a review session.

    Each review session can have multiple rounds, allowing users to restart
    the countdown timer after it expires.
    """
    id: int
    review_session_id: int
    round_number: int
    duration_minutes: int
    started_at: str
    ended_at: Optional[str] = None
    actual_studied_seconds: int = 0
    total_break_seconds: int = 0
    timer_paused_at: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'TimerRound':
        """Create TimerRound from database row."""
        if not row:
            return None
        return cls(
            id=row['id'],
            review_session_id=row['review_session_id'],
            round_number=row['round_number'],
            duration_minutes=row['duration_minutes'],
            started_at=row['started_at'],
            ended_at=row.get('ended_at'),
            actual_studied_seconds=row.get('actual_studied_seconds', 0) or 0,
            total_break_seconds=row.get('total_break_seconds', 0) or 0,
            timer_paused_at=row.get('timer_paused_at'),
            created_at=row.get('created_at'),
        )

    @property
    def is_active(self) -> bool:
        """Round is active if it hasn't ended yet."""
        return self.ended_at is None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON transport to the frontend."""
        return {
            'id': self.id,
            'review_session_id': self.review_session_id,
            'round_number': self.round_number,
            'duration_minutes': self.duration_minutes,
            'started_at': self.started_at,
            'ended_at': self.ended_at,
            'actual_studied_seconds': self.actual_studied_seconds,
            'total_break_seconds': self.total_break_seconds,
            'timer_paused_at': self.timer_paused_at,
            'created_at': self.created_at,
        }


@dataclass
class QuestionEntry:
    """
    Individual question entry within a review session - Phase 4.

    Captures the core metacognitive reflection data including
    answers, reflection, explanation, and draft status.

    Phase 8 additions: Rich text JSON fields for Quill Delta storage.
    The _json fields store Quill Delta format for editing, while the
    original fields store rendered HTML/plain text for display.
    """
    id: int
    review_session_id: int
    entry_order: int
    question_id: Optional[str]
    user_answer: str
    correct_answer: str
    perceived_difficulty: Optional[int]
    time_spent_seconds: Optional[int]
    reflection: Optional[str]
    explanation: Optional[str]
    notes: Optional[str]
    # Rich text JSON fields (Quill Delta format) - Phase 8
    reflection_json: Optional[str] = None
    explanation_json: Optional[str] = None
    notes_json: Optional[str] = None
    is_draft: bool = True
    draft_missing_fields: Optional[List[str]] = None
    created_at: datetime = None
    updated_at: datetime = None
    completed_at: Optional[datetime] = None

    # Related data (populated by joins)
    primary_subjects: List['SubjectNode'] = field(default_factory=list)
    secondary_subjects: List['SubjectNode'] = field(default_factory=list)
    tags: List['Tag'] = field(default_factory=list)
    media: List['EntryMedia'] = field(default_factory=list)
    notes_list: List['EntryNote'] = field(default_factory=list)

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'QuestionEntry':
        """Create QuestionEntry from database row"""
        if not row:
            return None
        
        missing_fields = None
        if row.get('draft_missing_fields'):
            try:
                missing_fields = json.loads(row['draft_missing_fields'])
            except (json.JSONDecodeError, TypeError):
                missing_fields = None
        
        return cls(
            id=row['id'],
            review_session_id=row['review_session_id'],
            entry_order=row['entry_order'],
            question_id=row.get('question_id'),
            user_answer=row['user_answer'],
            correct_answer=row['correct_answer'],
            perceived_difficulty=row.get('perceived_difficulty'),
            time_spent_seconds=row.get('time_spent_seconds'),
            reflection=row.get('reflection'),
            explanation=row.get('explanation'),
            notes=row.get('notes'),
            # Rich text JSON fields (Phase 8) - may be NULL in older databases
            reflection_json=row.get('reflection_json'),
            explanation_json=row.get('explanation_json'),
            notes_json=row.get('notes_json'),
            is_draft=bool(row.get('is_draft', True)),
            draft_missing_fields=missing_fields,
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now(),
            completed_at=datetime.fromisoformat(row['completed_at']) if row.get('completed_at') else None
        )
    
    def get_missing_required_fields(self) -> List[str]:
        """Get list of missing required fields"""
        missing = []
        if not self.user_answer:
            missing.append('user_answer')
        if not self.correct_answer:
            missing.append('correct_answer')
        if not self.reflection:
            missing.append('reflection')
        if not self.explanation:
            missing.append('explanation')
        # At least one primary subject required (checked separately)
        return missing
    
    @property
    def can_complete(self) -> bool:
        """Check if entry has all required fields to be marked complete"""
        return len(self.get_missing_required_fields()) == 0


@dataclass 
class EntrySubjectMapping:
    """
    Mapping between question entry and subject node - Phase 4.
    """
    id: int
    question_entry_id: int
    subject_node_id: int
    mapping_type: str  # 'primary', 'secondary'
    created_at: datetime
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'EntrySubjectMapping':
        """Create EntrySubjectMapping from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            question_entry_id=row['question_entry_id'],
            subject_node_id=row['subject_node_id'],
            mapping_type=row.get('mapping_type', 'primary'),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now()
        )


@dataclass
class EntryTag:
    """
    Mapping between question entry and tag - Phase 4.
    """
    id: int
    question_entry_id: int
    tag_id: int
    created_at: datetime
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'EntryTag':
        """Create EntryTag from database row"""
        if not row:
            return None
        return cls(
            id=row['id'],
            question_entry_id=row['question_entry_id'],
            tag_id=row['tag_id'],
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now()
        )


@dataclass
class EntryMedia:
    """
    Media attachment for question entry - Phase 4.

    Stores metadata about attached images/files, with actual
    files stored on disk using UUID naming.
    """
    id: int
    question_entry_id: Optional[int]  # Deprecated — use junction table
    file_uuid: str
    original_filename: Optional[str]
    user_filename: Optional[str]
    mime_type: Optional[str]
    file_size_bytes: Optional[int]
    sort_order: int
    linked_subject_ids: Optional[List[int]]
    dimension_id: Optional[int]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    user_id: Optional[int] = None

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'EntryMedia':
        """Create EntryMedia from database row"""
        if not row:
            return None

        linked_ids = None
        if row.get('linked_subject_ids'):
            try:
                linked_ids = json.loads(row['linked_subject_ids'])
            except (json.JSONDecodeError, TypeError):
                linked_ids = None

        return cls(
            id=row['id'],
            question_entry_id=row.get('question_entry_id'),
            file_uuid=row['file_uuid'],
            original_filename=row.get('original_filename'),
            user_filename=row.get('user_filename'),
            mime_type=row.get('mime_type'),
            file_size_bytes=row.get('file_size_bytes'),
            sort_order=row.get('sort_order', 0),
            linked_subject_ids=linked_ids,
            dimension_id=row.get('dimension_id'),
            is_active=bool(row.get('is_active', 1)),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now(),
            user_id=row.get('user_id')
        )
    
    @property
    def display_name(self) -> str:
        """Get display name (user filename or original)"""
        return self.user_filename or self.original_filename or self.file_uuid


@dataclass
class EntryNote:
    """
    A discrete note attached to a question entry - Phase 9.

    Each entry can have multiple notes, each optionally linked to specific
    subjects via linked_subject_ids (JSON array like [12, 45]).
    NULL linked_subject_ids means "general" (not subject-specific).
    """
    id: int
    question_entry_id: int
    content_html: Optional[str]
    content_json: Optional[str]
    sort_order: int
    linked_subject_ids: Optional[List[int]]
    is_migrated: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> Optional['EntryNote']:
        """Create EntryNote from database row"""
        if not row:
            return None

        linked_ids = None
        if row.get('linked_subject_ids'):
            try:
                linked_ids = json.loads(row['linked_subject_ids'])
            except (json.JSONDecodeError, TypeError):
                linked_ids = None

        return cls(
            id=row['id'],
            question_entry_id=row['question_entry_id'],
            content_html=row.get('content_html'),
            content_json=row.get('content_json'),
            sort_order=row.get('sort_order', 0),
            linked_subject_ids=linked_ids,
            is_migrated=bool(row.get('is_migrated', False)),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.now(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.now()
        )

    @property
    def is_general(self) -> bool:
        """True if this note is not linked to any subjects"""
        return not self.linked_subject_ids

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'question_entry_id': self.question_entry_id,
            'content_html': self.content_html,
            'content_json': self.content_json,
            'sort_order': self.sort_order,
            'linked_subject_ids': self.linked_subject_ids or [],
            'is_general': self.is_general,
            'is_migrated': self.is_migrated,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ==================== Phase 7 Models: Multidimensional Hierarchical Database ====================

@dataclass
class ExamDimension:
    """
    A categorical dimension for multi-dimensional exams - Phase 7.
    
    Dimensions are independent categories for classifying questions.
    For example, NBME Shelf Exams have dimensions like:
    - Site of Care (Ambulatory, Emergency, Inpatient)
    - Physician Task (Diagnosis, Management, Prevention)
    - System (Cardiovascular, Pulmonary, GI, etc.)
    
    Simple exams do not use dimensions and continue to use single-path hierarchies.
    
    Attributes:
        id: Database ID
        exam_id: ID of the exam context this dimension belongs to
        name: Human-readable dimension name (e.g., "Site of Care")
        display_order: Order for UI display (1, 2, 3, ...)
        is_required: Whether users must tag questions in this dimension
        allow_multiple: Whether multiple selections are allowed in this dimension
        description: Help text for users
        created_at: When the dimension was created
    """
    id: int
    exam_id: int
    name: str
    display_order: int
    is_required: bool = True
    allow_multiple: bool = False
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> Optional['ExamDimension']:
        """
        Create ExamDimension from database row.
        
        Args:
            row: Dictionary containing database row data
            
        Returns:
            ExamDimension object or None if row is None
        """
        if not row:
            return None
        return cls(
            id=row['id'],
            exam_id=row['exam_id'],
            name=row['name'],
            display_order=row['display_order'],
            is_required=bool(row.get('is_required', True)),
            allow_multiple=bool(row.get('allow_multiple', False)),
            description=row.get('description'),
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else None
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the dimension
        """
        return {
            'id': self.id,
            'exam_id': self.exam_id,
            'name': self.name,
            'display_order': self.display_order,
            'is_required': self.is_required,
            'allow_multiple': self.allow_multiple,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

@dataclass
class QuestionHierarchyTag:
    """
    Links a question entry to a hierarchy node within a specific dimension - Phase 7.
    
    This enables multi-dimensional tagging where a question can be tagged with
    one node per dimension (or multiple if allow_multiple=1 for that dimension).
    
    For example, a single question might be tagged as:
    - Site of Care → "Emergency Department" (dimension 1)
    - Physician Task → "Diagnosis" (dimension 2)
    - System → "Cardiovascular → Arrhythmias" (dimension 3)
    
    Attributes:
        id: Database ID
        entry_id: ID of the question entry being tagged
        hierarchy_id: ID of the hierarchy node (subject_nodes.id)
        dimension_id: ID of the dimension this tag belongs to
        tagged_at: When the tag was created
        dimension_name: Name of the dimension (from join)
        hierarchy_name: Name of the hierarchy node (from join)
    """
    id: int
    entry_id: int
    hierarchy_id: int
    dimension_id: int
    tagged_at: Optional[datetime] = None
    
    # Additional fields populated from joins
    dimension_name: Optional[str] = None
    hierarchy_name: Optional[str] = None
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> Optional['QuestionHierarchyTag']:
        """
        Create QuestionHierarchyTag from database row.
        
        Args:
            row: Dictionary containing database row data
            
        Returns:
            QuestionHierarchyTag object or None if row is None
        """
        if not row:
            return None
        return cls(
            id=row['id'],
            entry_id=row['entry_id'],
            hierarchy_id=row['hierarchy_id'],
            dimension_id=row['dimension_id'],
            tagged_at=datetime.fromisoformat(row['tagged_at']) if row.get('tagged_at') else None,
            dimension_name=row.get('dimension_name'),
            hierarchy_name=row.get('hierarchy_name')
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the tag
        """
        return {
            'id': self.id,
            'entry_id': self.entry_id,
            'hierarchy_id': self.hierarchy_id,
            'dimension_id': self.dimension_id,
            'tagged_at': self.tagged_at.isoformat() if self.tagged_at else None,
            'dimension_name': self.dimension_name,
            'hierarchy_name': self.hierarchy_name
        }


@dataclass
class DimensionTagSummary:
    """
    Summary of tags for an entry across all dimensions - Phase 7.
    
    Used to display a complete picture of how an entry is tagged
    across all dimensions in the exam.
    
    Attributes:
        entry_id: ID of the question entry
        dimension_tags: Dict mapping dimension_id to list of tags
        missing_required: List of dimension IDs that require tags but have none
        is_complete: Whether all required dimensions are tagged
    """
    entry_id: int
    dimension_tags: Dict[int, List[QuestionHierarchyTag]] = field(default_factory=dict)
    missing_required: List[int] = field(default_factory=list)
    
    @property
    def is_complete(self) -> bool:
        """Check if all required dimensions are tagged"""
        return len(self.missing_required) == 0
    
    def get_tag_count(self) -> int:
        """Get total number of tags across all dimensions"""
        return sum(len(tags) for tags in self.dimension_tags.values())
    
    def get_dimensions_tagged(self) -> List[int]:
        """Get list of dimension IDs that have at least one tag"""
        return [dim_id for dim_id, tags in self.dimension_tags.items() if tags]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'entry_id': self.entry_id,
            'dimension_tags': {
                dim_id: [tag.to_dict() for tag in tags]
                for dim_id, tags in self.dimension_tags.items()
            },
            'missing_required': self.missing_required,
            'is_complete': self.is_complete,
            'tag_count': self.get_tag_count()
        }


@dataclass
class CrossDimensionAnalysis:
    """
    Cross-dimensional analysis results - Phase 7.
    
    Stores results of analyzing performance across dimension combinations,
    such as finding that a student struggles with "Diagnosis" questions
    specifically in "Emergency" settings.
    
    Attributes:
        dimension_combination: Dict of dimension_id -> hierarchy_id combinations
        entry_count: Number of entries matching this combination
        total_entries: Total entries in the exam for normalization
        percentage: What percentage of entries fall into this combination
        performance_metrics: Additional metrics like accuracy, time spent, etc.
    """
    dimension_combination: Dict[int, int]  # dimension_id -> hierarchy_id
    entry_count: int
    total_entries: int
    performance_metrics: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def percentage(self) -> float:
        """Calculate what percentage of entries have this combination"""
        if self.total_entries == 0:
            return 0.0
        return round(self.entry_count / self.total_entries * 100, 1)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'dimension_combination': self.dimension_combination,
            'entry_count': self.entry_count,
            'total_entries': self.total_entries,
            'percentage': self.percentage,
            'performance_metrics': self.performance_metrics
        }