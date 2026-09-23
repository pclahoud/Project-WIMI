"""Master-database migration registry."""
from __future__ import annotations

from ...migration_runner import Migration, build_migration

from . import m001_baseline
from . import m002_profile_uuid

MIGRATIONS: list[Migration] = [
    build_migration(m001_baseline),
    build_migration(m002_profile_uuid),
]
