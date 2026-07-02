"""Master-database migration registry."""
from __future__ import annotations

from ...migration_runner import Migration, build_migration

from . import m001_baseline

MIGRATIONS: list[Migration] = [
    build_migration(m001_baseline),
]
