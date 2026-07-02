# Addon System — Layer 2: Bridge Mixin Decomposition

## Goal
Split `DatabaseBridge` (5,600 lines, 122 `@pyqtSlot` methods) into domain-specific mixins, then add a generic plugin dispatch slot.

## Current State
- Single class `DatabaseBridge(QObject)` in `src/app/bridge.py`
- 122 `@pyqtSlot` methods grouped into 18 logical domains
- 11 private helper methods (serializers, error logging, etc.)
- 3 `pyqtSignal` definitions
- Common pattern: check `self.user_db` → parse JSON → call `user_db.method()` → `serialize_response()`
- Standalone helpers: `DateTimeEncoder`, `serialize_response()` (module-level)

## Target Structure

```
src/app/
  bridge.py                     # slim orchestrator (~150 lines)
  bridge_helpers.py             # DateTimeEncoder, serialize_response (module-level)
  bridge_domains/
    __init__.py                 # exports all bridge mixins
    _serializers.py             # shared serialization helpers (_serialize_question_entry, etc.)
    exam_contexts.py            # ExamContextBridgeMixin (9 slots)
    hierarchy.py                # HierarchyBridgeMixin (18 slots)
    aliases.py                  # AliasBridgeMixin (6 slots)
    sessions.py                 # SessionBridgeMixin (7 slots)
    timer.py                    # TimerBridgeMixin (10 slots)
    entries.py                  # EntryBridgeMixin (11 slots)
    notes.py                    # NoteBridgeMixin (6 slots)
    media.py                    # MediaBridgeMixin (10 slots)
    sources.py                  # SourceBridgeMixin (4 slots)
    tags.py                     # TagBridgeMixin (3 slots)
    analytics.py                # AnalyticsBridgeMixin (23 slots)
    dimensions.py               # DimensionBridgeMixin (13 slots)
    dimension_analytics.py      # DimensionAnalyticsBridgeMixin (5 slots)
    hierarchy_tags.py           # HierarchyTagBridgeMixin (4 slots)
    import_export.py            # ImportExportBridgeMixin (7 slots)
    settings.py                 # SettingsBridgeMixin (2 slots)
    filters.py                  # FilterBridgeMixin (3 slots)
    utility.py                  # UtilityBridgeMixin (7 slots — connection, app info, clipboard, docs)
    plugin_dispatch.py          # PluginDispatchMixin (1 slot — callPlugin)
```

## Bridge Mixin Domain Mapping

| Mixin | Slots | Lines (approx) |
|-------|-------|-----------------|
| ExamContextBridgeMixin | 9 | ~350 |
| HierarchyBridgeMixin | 18 | ~550 |
| AliasBridgeMixin | 6 | ~200 |
| SessionBridgeMixin | 7 | ~250 |
| TimerBridgeMixin | 10 | ~200 |
| EntryBridgeMixin | 11 | ~400 |
| NoteBridgeMixin | 6 | ~180 |
| MediaBridgeMixin | 10 | ~350 |
| SourceBridgeMixin | 4 | ~180 |
| TagBridgeMixin | 3 | ~120 |
| AnalyticsBridgeMixin | 23 | ~600 |
| DimensionBridgeMixin | 13 | ~400 |
| DimensionAnalyticsBridgeMixin | 5 | ~200 |
| HierarchyTagBridgeMixin | 4 | ~160 |
| ImportExportBridgeMixin | 7 | ~350 |
| SettingsBridgeMixin | 2 | ~80 |
| FilterBridgeMixin | 3 | ~100 |
| UtilityBridgeMixin | 7 | ~200 |
| PluginDispatchMixin | 1 | ~60 |

## PyQt6 Mixin Constraint

`@pyqtSlot` decorators are evaluated at class definition time. Mixins with `@pyqtSlot` methods work **as long as the final composed class inherits from QObject**. This is the same pattern used in large PyQt projects.

```python
# bridge_domains/timer.py
from PyQt6.QtCore import pyqtSlot
from ..bridge_helpers import serialize_response
import json

class TimerBridgeMixin:
    """Timer round bridge methods. Must be mixed into a QObject subclass."""

    @pyqtSlot(int, int, result=str)
    def createTimerRound(self, session_id: int, duration: int) -> str:
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            rnd = self.user_db.create_timer_round(session_id, duration)
            return serialize_response(True, data=rnd.to_dict() if rnd else None)
        except Exception as e:
            self._log_error(f'Error creating timer round: {e}')
            return serialize_response(False, error=str(e))
    # ... remaining timer slots
```

## Shared Serializers (`bridge_domains/_serializers.py`)

These helpers are used across multiple bridge domains:

| Method | Used By |
|--------|---------|
| `_serialize_question_entry()` | entries, sessions (getSessionEntries) |
| `_serialize_entry_note()` | notes, entries |
| `_serialize_entry_media()` | media, entries |
| `_subject_node_to_dict()` | hierarchy, dimensions |
| `_get_media_data_url()` | media, entries |
| `_get_subject_mistake_counts()` | analytics |

These become methods on a `SerializerMixin` or standalone functions that take `self` (the bridge instance) as a parameter.

## Composed DatabaseBridge

```python
# src/app/bridge.py (after refactor)
from PyQt6.QtCore import QObject, pyqtSignal
from .bridge_domains import (
    SerializerMixin,
    ExamContextBridgeMixin,
    HierarchyBridgeMixin,
    AliasBridgeMixin,
    SessionBridgeMixin,
    TimerBridgeMixin,
    EntryBridgeMixin,
    NoteBridgeMixin,
    MediaBridgeMixin,
    SourceBridgeMixin,
    TagBridgeMixin,
    AnalyticsBridgeMixin,
    DimensionBridgeMixin,
    DimensionAnalyticsBridgeMixin,
    HierarchyTagBridgeMixin,
    ImportExportBridgeMixin,
    SettingsBridgeMixin,
    FilterBridgeMixin,
    UtilityBridgeMixin,
    PluginDispatchMixin,
)

class DatabaseBridge(
    QObject,
    SerializerMixin,
    ExamContextBridgeMixin,
    HierarchyBridgeMixin,
    AliasBridgeMixin,
    SessionBridgeMixin,
    TimerBridgeMixin,
    EntryBridgeMixin,
    NoteBridgeMixin,
    MediaBridgeMixin,
    SourceBridgeMixin,
    TagBridgeMixin,
    AnalyticsBridgeMixin,
    DimensionBridgeMixin,
    DimensionAnalyticsBridgeMixin,
    HierarchyTagBridgeMixin,
    ImportExportBridgeMixin,
    SettingsBridgeMixin,
    FilterBridgeMixin,
    UtilityBridgeMixin,
    PluginDispatchMixin,
):
    """Python-JS bridge — composed from domain mixins."""

    examContextCreated = pyqtSignal(str)
    examContextUpdated = pyqtSignal(str)
    weightUpdated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.master_db = None
        self.user_db = None
        self.error_logger = None
        self._plugin_registry = {}

    def set_user_database(self, user_db):
        self.user_db = user_db

    def _log_error(self, message, extra=None):
        if self.error_logger:
            self.error_logger.log_error(message, extra)
```

## Plugin Dispatch Slot

```python
# src/app/bridge_domains/plugin_dispatch.py
from PyQt6.QtCore import pyqtSlot
from ..bridge_helpers import serialize_response
import json

class PluginDispatchMixin:
    """Generic dispatch for plugin bridge calls."""

    @pyqtSlot(str, str, result=str)
    def callPlugin(self, plugin_id: str, payload_json: str) -> str:
        """Route a call to a registered plugin.

        Args:
            plugin_id: The plugin identifier
            payload_json: JSON with 'method' and optional 'args' keys
        """
        try:
            plugin = self._plugin_registry.get(plugin_id)
            if not plugin:
                return serialize_response(False, error=f'Unknown plugin: {plugin_id}')

            payload = json.loads(payload_json)
            method_name = payload.get('method')
            args = payload.get('args', {})

            method = getattr(plugin, method_name, None)
            if not method or method_name.startswith('_'):
                return serialize_response(False, error=f'Unknown method: {method_name}')

            result = method(**args)
            return serialize_response(True, data=result)
        except Exception as e:
            self._log_error(f'Plugin {plugin_id} error: {e}')
            return serialize_response(False, error=str(e))
```

## Execution Steps

1. **Extract `bridge_helpers.py`** — move `DateTimeEncoder` and `serialize_response()` out of bridge.py
2. **Create `src/app/bridge_domains/` directory**
3. **Extract `SerializerMixin`** — shared serialization helpers
4. **Extract each domain mixin** — smallest first, matching DB layer domains
5. **Rewrite `bridge.py`** as composed class
6. **Add `PluginDispatchMixin`** with `callPlugin` slot
7. **Run app manually** to verify WebChannel still works (no automated bridge tests exist)

## Alignment with Layer 1

| DB Domain Mixin | Bridge Domain Mixin | Slots |
|-----------------|---------------------|-------|
| PreferencesMixin | SettingsBridgeMixin | 2 |
| ExamContextMixin | ExamContextBridgeMixin | 9 |
| HierarchyMixin | HierarchyBridgeMixin | 18 |
| TagsMixin | TagBridgeMixin | 3 |
| SessionsMixin | SessionBridgeMixin | 7 |
| TimerMixin | TimerBridgeMixin | 10 |
| SourcesMixin | SourceBridgeMixin | 4 |
| EntriesMixin | EntryBridgeMixin | 11 |
| MediaMixin | MediaBridgeMixin | 10 |
| NotesMixin | NoteBridgeMixin | 6 |
| AnalyticsMixin + AdvancedAnalyticsMixin | AnalyticsBridgeMixin | 23 |
| DimensionsMixin | DimensionBridgeMixin + DimensionAnalyticsBridgeMixin | 18 |
| AliasesMixin | AliasBridgeMixin | 6 |
| ImportExportMixin | ImportExportBridgeMixin | 7 |
| GoalsMixin | (included in AnalyticsBridgeMixin) | — |
| — | UtilityBridgeMixin | 7 |
| — | FilterBridgeMixin | 3 |
| — | PluginDispatchMixin (new) | 1 |

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| PyQt6 MRO with QObject | QObject must be first in MRO — put it first in class definition |
| `@pyqtSlot` on mixin not recognized | Verified: PyQt6 resolves slots at class creation via metaclass; mixins work |
| Signals must be on class with QObject | Keep signals on `DatabaseBridge` directly, not in mixins |
| WebChannel JS side breaks | `bridge.methodName()` still resolves — class name doesn't matter |
| No automated bridge tests | Manual verification required; consider adding integration tests |

## Validation Criteria

- App launches and all pages load correctly
- All bridge calls from JS work (test each page manually)
- `serialize_response` format unchanged
- No changes needed in `api.js` or any frontend code
- Plugin dispatch slot responds to test calls
