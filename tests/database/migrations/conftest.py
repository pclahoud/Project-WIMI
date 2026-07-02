"""Shared fixtures for the migration runner tests.

Two flavors of fixture:

- ``fresh_conn`` — an in-memory ``sqlite3.Connection`` with foreign keys
  enabled and ``Row`` factory. Lets the runner tests work directly against
  a raw connection without spinning up the full ``UserDatabase`` stack.

- ``legacy_user_db_path`` — a file-backed per-user DB created via
  ``UserDatabase``, which (now that the runner is wired into ``__init__``)
  ends up fully migrated. Useful for tests that want to verify the
  "existing user opens the new app" adoption path.
"""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def fresh_conn():
    """Yield a brand-new in-memory sqlite3 connection.

    - ``row_factory = sqlite3.Row`` so tests can index by column name.
    - ``PRAGMA foreign_keys = ON`` to match production behavior.
    - Closed in teardown.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def legacy_user_db_path(tmp_path):
    """Build a per-user DB via UserDatabase and return its path.

    With the runner wired into ``UserDatabase.__init__``, every freshly
    constructed user DB ends up fully migrated. That's actually the
    correct simulation of an existing user opening the new app — by the
    time control returns the runner has already run.
    """
    from database.user_db import UserDatabase

    db_path = tmp_path / "user_001_legacy.db"
    db = UserDatabase(db_path=db_path, user_id=1, username="legacy")
    try:
        db.close()
    except Exception:
        pass
    return db_path
