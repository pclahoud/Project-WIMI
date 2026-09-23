"""Master DB migration v2 — ``users.profile_uuid`` (issue #129).

A **mirror**, not the authority. The profile id is minted in the user
database (``profile_identity``, user m021) because an identifier living
inside the thing it identifies cannot get out of step with it and
survives ``.wimi`` export for free. This column exists so the registry
can answer "do I already have this profile?" without opening every
profile database in turn, and it is re-derived from the user database
whenever a profile is opened or installed. A divergence is always
resolved in the user database's favour.

**Deliberately not ``UNIQUE``.** Two installs of the same archive are a
supported outcome, not an error: ``install_profile_as_new()`` renames on
collision (``alice`` -> ``alice_2``) by design, and #22 comment #1454
decided that "keep both" is one of the two first-connect options a
student is offered. A unique index would turn that decision into an
``IntegrityError`` at the worst possible moment. The import path instead
*detects* a duplicate and reports it; choosing between the two copies is
fork resolution, which is #124's and not this column's.

The index is partial so the common pre-mirror ``NULL`` costs nothing.

**No backfill.** Minting ids here for existing rows would put the
authority in the wrong database: master would claim an id the user
database has never heard of, and the first open would have to decide
which one wins. The column stays ``NULL`` until a profile is opened and
the real id is read out of it.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing, get_column_names

VERSION = 2
NAME = "profile_uuid"


def upgrade(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "users", "profile_uuid", "TEXT")

    # Guarded for the same reason m020's index is: add_column_if_missing
    # is a silent no-op on a missing table, and an unguarded CREATE INDEX
    # would then raise on the missing column.
    if "profile_uuid" in get_column_names(conn, "users"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_profile_uuid "
            "ON users(profile_uuid) WHERE profile_uuid IS NOT NULL"
        )
