"""
WIMI Bridge Domain Mixins.
Each mixin encapsulates a domain of bridge operations.
Composed into DatabaseBridge via multiple inheritance.
"""

from ._serializers import SerializerMixin
from .preferences import PreferencesBridgeMixin
from .profiles import ProfileBridgeMixin
from .profile_transfer import ProfileTransferBridgeMixin
from .utility import UtilityBridgeMixin
from .tags import TagBridgeMixin
from .timer import TimerBridgeMixin
from .notes import NoteBridgeMixin
from .goals import GoalsBridgeMixin
from .aliases import AliasBridgeMixin
from .sources import SourceBridgeMixin
from .sessions import SessionBridgeMixin
from .entries import EntryBridgeMixin
from .media import MediaBridgeMixin
from .hierarchy import HierarchyBridgeMixin
from .edges import EdgesBridgeMixin
from .hierarchy_tags import HierarchyTagBridgeMixin
from .exam_contexts import ExamContextBridgeMixin
from .weights import WeightBridgeMixin
from .browsing import BrowsingBridgeMixin
from .analytics import AnalyticsBridgeMixin
from .dimensions import DimensionBridgeMixin
from .dimension_analytics import DimensionAnalyticsBridgeMixin
from .import_export import ImportExportBridgeMixin
from .plugin_dispatch import PluginDispatchMixin
from .plugin_management import PluginManagementMixin

__all__ = [
    'SerializerMixin',
    'PreferencesBridgeMixin',
    'ProfileBridgeMixin',
    'ProfileTransferBridgeMixin',
    'UtilityBridgeMixin',
    'TagBridgeMixin',
    'TimerBridgeMixin',
    'NoteBridgeMixin',
    'GoalsBridgeMixin',
    'AliasBridgeMixin',
    'SourceBridgeMixin',
    'SessionBridgeMixin',
    'EntryBridgeMixin',
    'MediaBridgeMixin',
    'HierarchyBridgeMixin',
    'EdgesBridgeMixin',
    'HierarchyTagBridgeMixin',
    'ExamContextBridgeMixin',
    'WeightBridgeMixin',
    'BrowsingBridgeMixin',
    'AnalyticsBridgeMixin',
    'DimensionBridgeMixin',
    'DimensionAnalyticsBridgeMixin',
    'ImportExportBridgeMixin',
    'PluginDispatchMixin',
    'PluginManagementMixin',
]
