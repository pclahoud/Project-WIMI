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
from . import m009_entry_note_attachments
from . import m010_default_tag_definitions

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
]
