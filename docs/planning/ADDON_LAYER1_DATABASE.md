# Addon System — Layer 1: Database Mixin Decomposition

## Goal
Split `UserDatabase` (10,400 lines, 212 methods) into domain-specific mixins, then define a plugin schema registration interface.

## Current State
- Single class `UserDatabase(BaseDatabase)` in `src/database/user_db.py`
- 20+ `_ensure_*` migration methods scattered throughout
- 14 cross-domain method call patterns identified
- `BaseDatabase` in `src/database/base_db.py` provides: `execute()`, `fetchone()`, `fetchall()`, `transaction()`

## Target Structure

```
src/database/
  base_db.py                    # unchanged
  user_db.py                    # slim orchestrator (~100 lines)
  models.py                     # unchanged
  exceptions.py                 # unchanged
  schema_manager.py             # unchanged
  master_db.py                  # unchanged
  domains/
    __init__.py                 # exports all mixins
    _base.py                    # shared helpers (_subject_with_dimension, _entry_to_dict, etc.)
    preferences.py              # PreferencesMixin (3 methods)
    exam_contexts.py            # ExamContextMixin (9 methods)
    hierarchy.py                # HierarchyMixin (27 methods — subjects, weights, search)
    tags.py                     # TagsMixin (14 methods)
    sessions.py                 # SessionsMixin (8 methods — CRUD, no timer)
    timer.py                    # TimerMixin (10 methods — rounds, pause/unpause)
    sources.py                  # SourcesMixin (5 methods)
    entries.py                  # EntriesMixin (12 methods — CRUD, search, pagination)
    media.py                    # MediaMixin (13 methods)
    notes.py                    # NotesMixin (7 methods)
    analytics.py                # AnalyticsMixin (12 overview methods)
    analytics_advanced.py       # AdvancedAnalyticsMixin (14 methods — source, efficiency, weights)
    goals.py                    # GoalsMixin (5 methods)
    dimensions.py               # DimensionsMixin (28 methods)
    aliases.py                  # AliasesMixin (8 methods)
    import_export.py            # ImportExportMixin (7 methods — delimiters, mappings)
    schema_migrations.py        # SchemaMigrationMixin (20 _ensure_* + 2 _migrate_* methods)
  plugins/
    __init__.py                 # Plugin registry
    base.py                     # BasePlugin class with schema + mixin interface
```

## Mixin Domain Mapping

| Mixin | Methods | Lines (approx) | Key Tables |
|-------|---------|-----------------|------------|
| PreferencesMixin | 3 | ~80 | user_preferences |
| ExamContextMixin | 9 | ~300 | exam_contexts, hierarchy_levels |
| HierarchyMixin | 27 | ~1,800 | subject_nodes, hierarchy_level_definitions |
| TagsMixin | 14 | ~500 | tags, question_tags, hierarchy_tags |
| SessionsMixin | 8 | ~400 | review_sessions |
| TimerMixin | 10 | ~300 | session_timer_rounds |
| SourcesMixin | 5 | ~200 | question_sources |
| EntriesMixin | 12 | ~800 | question_entries, entry_subject_mappings |
| MediaMixin | 13 | ~400 | entry_media |
| NotesMixin | 7 | ~200 | entry_notes |
| AnalyticsMixin | 12 | ~800 | (reads entries, sessions, subjects) |
| AdvancedAnalyticsMixin | 14 | ~700 | (reads entries, sessions, sources) |
| GoalsMixin | 5 | ~500 | user_goals, goal_periods |
| DimensionsMixin | 28 | ~1,200 | exam_dimensions, dimension_tag_mappings |
| AliasesMixin | 8 | ~400 | subject_aliases |
| ImportExportMixin | 7 | ~200 | saved_delimiters, import_mapping_profiles |
| SchemaMigrationMixin | 22 | ~600 | (all tables — DDL only) |

## Cross-Domain Dependencies

These methods call across domains and need careful placement:

| Method | Home Domain | Calls Into |
|--------|-------------|------------|
| `create_question_entry()` | entries | sessions (validate + increment) |
| `get_entry_with_context()` | entries | subjects, tags, media, notes, dimensions |
| `_entry_to_dict()` | entries (shared helper) | dimensions |
| `get_analytics_overview()` | analytics | entries, sessions (queries only) |
| `get_subject_deep_dive()` | analytics | dimensions |
| `create_review_session()` | sessions | exam_contexts, sources |
| `hard_delete_exam_context()` | exam_contexts | sessions (cascade) |
| `validate_entry_dimensions_complete()` | dimensions | entries |

**Resolution:** Cross-domain calls work naturally with mixins since all methods live on the same `self`. The key is that mixins must NOT import each other — they all access sibling methods via `self.*`.

## Shared Helpers (`domains/_base.py`)

Methods used across multiple domains go in a base helpers module:

- `_subject_with_dimension()` — used by entries + analytics
- `_entry_to_dict()` — used by entries + search
- `_build_subject_path()` — used by hierarchy + entries + analytics
- `_get_descendant_node_ids()` — used by hierarchy + dimensions
- `_build_descendant_cte()` — used by dimensions + analytics

These become a `SharedHelpersMixin` that other mixins can rely on.

## Composed UserDatabase

```python
# src/database/user_db.py (after refactor)
from .base_db import BaseDatabase
from .domains import (
    SharedHelpersMixin,
    SchemaMigrationMixin,
    PreferencesMixin,
    ExamContextMixin,
    HierarchyMixin,
    TagsMixin,
    SessionsMixin,
    TimerMixin,
    SourcesMixin,
    EntriesMixin,
    MediaMixin,
    NotesMixin,
    AnalyticsMixin,
    AdvancedAnalyticsMixin,
    GoalsMixin,
    DimensionsMixin,
    AliasesMixin,
    ImportExportMixin,
)

class UserDatabase(
    BaseDatabase,
    SharedHelpersMixin,
    SchemaMigrationMixin,
    PreferencesMixin,
    ExamContextMixin,
    HierarchyMixin,
    TagsMixin,
    SessionsMixin,
    TimerMixin,
    SourcesMixin,
    EntriesMixin,
    MediaMixin,
    NotesMixin,
    AnalyticsMixin,
    AdvancedAnalyticsMixin,
    GoalsMixin,
    DimensionsMixin,
    AliasesMixin,
    ImportExportMixin,
):
    """Per-user database — composed from domain mixins."""

    def __init__(self, db_path: str, user_id: int, username: str):
        super().__init__(db_path)
        self.user_id = user_id
        self.username = username
        self._run_migrations()
```

## Plugin Schema Interface

```python
# src/database/plugins/base.py
class DatabasePlugin:
    """Base class for database-layer plugins."""

    plugin_id: str  # e.g. "spaced-repetition"

    def ensure_schema(self, db: 'UserDatabase') -> None:
        """Create/migrate plugin tables. Called at startup."""
        raise NotImplementedError

    def get_mixin(self) -> type:
        """Return a mixin class with plugin's database methods."""
        raise NotImplementedError
```

## Execution Steps

1. **Create `src/database/domains/` directory and `__init__.py`**
2. **Extract `SchemaMigrationMixin`** — all `_ensure_*` and `_migrate_*` methods
3. **Extract `SharedHelpersMixin`** — cross-domain helpers
4. **Extract each domain mixin** — one at a time, smallest first (preferences → sources → notes → timer → etc.)
5. **Rewrite `user_db.py`** as composed class
6. **Run full test suite after each extraction** — `pytest --no-cov` to verify no regressions
7. **Create plugin base class and registry**

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Circular imports between mixins | Mixins never import each other; access via `self` |
| Method resolution order (MRO) conflicts | No diamond inheritance — each mixin is independent |
| IDE autocomplete breaks | Type stub or `TYPE_CHECKING` import for `self` methods |
| Test fixtures reference `UserDatabase` directly | No change needed — composed class has same interface |
| `_ensure_*` call order matters | `SchemaMigrationMixin._run_migrations()` preserves order |

## Validation Criteria

- All 588 tests pass with `--no-cov`
- No import changes needed in bridge.py (still imports `UserDatabase`)
- No changes to any frontend code
- Each mixin is independently readable (<800 lines)
