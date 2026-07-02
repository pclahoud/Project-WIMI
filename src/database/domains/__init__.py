"""WIMI Database domain mixins.

All mixins are composed into the UserDatabase class via multiple inheritance.
They share state through ``self.*`` and must NOT import each other.
"""

from ._base import SharedHelpersMixin
from .schema_migrations import SchemaMigrationMixin
from .preferences import PreferencesMixin
from .exam_contexts import ExamContextMixin
from .hierarchy import HierarchyMixin
from .edges import EdgesMixin
from .tags import TagsMixin
from .sessions import SessionsMixin
from .timer import TimerMixin
from .sources import SourcesMixin
from .entries import EntriesMixin
from .media import MediaMixin
from .notes import NotesMixin
from .analytics import AnalyticsMixin
from .analytics_advanced import AdvancedAnalyticsMixin
from .goals import GoalsMixin
from .dimensions import DimensionsMixin
from .aliases import AliasesMixin
from .import_export import ImportExportMixin
from .plugin_data import PluginDataMixin
from .graph import GraphMixin

__all__ = [
    'SharedHelpersMixin',
    'SchemaMigrationMixin',
    'PreferencesMixin',
    'ExamContextMixin',
    'HierarchyMixin',
    'EdgesMixin',
    'TagsMixin',
    'SessionsMixin',
    'TimerMixin',
    'SourcesMixin',
    'EntriesMixin',
    'MediaMixin',
    'NotesMixin',
    'AnalyticsMixin',
    'AdvancedAnalyticsMixin',
    'GoalsMixin',
    'DimensionsMixin',
    'AliasesMixin',
    'ImportExportMixin',
    'PluginDataMixin',
    'GraphMixin',
]
