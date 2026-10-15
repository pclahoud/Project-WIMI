"""User-database migration registry.

Add new migrations to the ``MIGRATIONS`` list at the bottom of this file.
Order matters — the runner sorts by ``VERSION`` defensively, but the
file order is what readers see first, so keep it consistent.

Each migration module must expose:

    VERSION: int        # 1, 2, 3, ...
    NAME: str           # short snake_case label
    def upgrade(conn): ... # applies the migration

See ``docs/planning/MIGRATION_RUNNER.md`` for the design rationale.
"""
from __future__ import annotations

from ...migration_runner import Migration, build_migration

# Import each migration module. Order = version order.
from . import m001_baseline
from . import m002_phase6_goals
from . import m003_phase7_dimensions
from . import m004_subject_edges
from . import m005_primary_parent_id
from . import m006_subject_edge_weight_history
from . import m007_exam_length_triple
# v8 is reserved for `m008_assessments` from the
# `feat/psychometric-assessment` branch (commit ca63e69). Dev DBs that
# checked out that branch already have v8 applied; the registry skips
# straight to v9 here so master doesn't collide.
# That feature's migration now lands as m032 (#766, 2026-10-12); v8 stays
# reserved forever, because monotonicity, not stamping, is the bar.
from . import m009_entry_note_attachments
from . import m010_default_tag_definitions

# v11-v14 are skipped: they belong to the AI capture feature (a paused
# feature branch, feature/ai-capture -- #145). Databases that ran its
# builds already have those versions stamped, and the runner treats a
# stamped version as applied. See m015's docstring.
from . import m015_browser_pane_source_fields
from . import m016_browser_pane_state
from . import m017_pane_shortcut_opens
from . import m018_subject_delete_batches
from . import m019_subject_relations
from . import m020_subject_import_id
from . import m021_device_local_settings
from . import m022_efficiency_confidence_band
from . import m023_speech_to_text_settings
from . import m024_dimension_soft_delete
from . import m025_dimension_import_id
from . import m026_relation_types
from . import m027_relation_rejections
from . import m028_relation_confidence_threshold
from . import m030_settings_defaults_reset
from . import m031_tour_seen_steps
from . import m032_assessments
from . import m033_planned_sessions
from . import m034_anki
from . import m035_anki_relevance

MIGRATIONS: list[Migration] = [
    build_migration(m001_baseline),
    build_migration(m002_phase6_goals),
    build_migration(m003_phase7_dimensions),
    build_migration(m004_subject_edges),
    build_migration(m005_primary_parent_id),
    build_migration(m006_subject_edge_weight_history),
    build_migration(m007_exam_length_triple),
    build_migration(m009_entry_note_attachments),
    build_migration(m010_default_tag_definitions),
    build_migration(m015_browser_pane_source_fields),
    build_migration(m016_browser_pane_state),
    build_migration(m017_pane_shortcut_opens),
    build_migration(m018_subject_delete_batches),
    build_migration(m019_subject_relations),
    build_migration(m020_subject_import_id),
    build_migration(m021_device_local_settings),
    build_migration(m022_efficiency_confidence_band),
    build_migration(m023_speech_to_text_settings),
    build_migration(m024_dimension_soft_delete),
    build_migration(m025_dimension_import_id),
    build_migration(m026_relation_types),
    build_migration(m027_relation_rejections),
    build_migration(m028_relation_confidence_threshold),
    build_migration(m030_settings_defaults_reset),
    build_migration(m031_tour_seen_steps),
    build_migration(m032_assessments),
    build_migration(m033_planned_sessions),
    build_migration(m034_anki),
    build_migration(m035_anki_relevance),
]
