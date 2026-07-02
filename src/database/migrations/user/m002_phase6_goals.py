"""User DB migration v2 — Phase 6 (goals + reflection themes).

Was previously created lazily by ``_ensure_phase6_schema()``, called at
the top of every goals operation. Now applied eagerly at DB init so the
tables exist regardless of whether the user has ever opened the goals
UI.

Tables created:

- ``user_goals``
- ``goal_periods``
- ``reflection_themes``

Idempotent — uses ``CREATE TABLE IF NOT EXISTS`` via the schema file.
"""
from __future__ import annotations

import sqlite3

from .._helpers import get_table_names, run_schema_script

VERSION = 2
NAME = "phase6_goals"


def upgrade(conn: sqlite3.Connection) -> None:
    phase6_tables = {"user_goals", "goal_periods", "reflection_themes"}
    if phase6_tables.issubset(get_table_names(conn)):
        return
    run_schema_script(conn, "user_db_schema_v1_phase6.sql")
