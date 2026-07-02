"""Master DB baseline (v1).

Captures the master database schema (users, app settings, cross-user
relationships) as of the introduction of the migration runner. Ports
``MasterDatabase._initialize_schema`` — runs ``master_db_schema_v1.sql``
which uses ``CREATE TABLE IF NOT EXISTS`` so it's idempotent.
"""
from __future__ import annotations

import sqlite3

from .._helpers import get_table_names, run_schema_script

VERSION = 1
NAME = "baseline"


def upgrade(conn: sqlite3.Connection) -> None:
    if "users" in get_table_names(conn):
        # Existing master DB — schema already populated. The runner will
        # record v1 in schema_migrations so future migrations can layer on.
        return
    run_schema_script(conn, "master_db_schema_v1.sql")
