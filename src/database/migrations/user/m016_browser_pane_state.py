"""User DB migration v16 — browser pane state and open behaviour.

Five columns on ``user_preferences``. One is a setting the student
chooses; the rest are state the pane remembers on their behalf, which is
why they live here rather than on the settings page:

* ``pane_open_mode`` — the only one with a control. ``'last'`` reopens
  the page you were on, ``'source'`` always opens one chosen question
  bank, ``'blank'`` opens empty. Defaults to ``'last'``, because the
  pane previously opened ``about:blank`` and then required a click to
  reach a bank you visit every day.

* ``pane_default_source_id`` — which bank ``'source'`` mode opens.
  Deliberately NOT a foreign key: a source can be deleted while it is
  still nominated, and a dangling id should degrade to "open blank"
  rather than block the delete or cascade into preferences.

* ``pane_last_url`` — what ``'last'`` mode reopens.

* ``pane_split_app_pct`` — the app's share of the splitter, as a
  percentage. Stored as the app's share rather than the pane's so the
  number still reads correctly if the pane's minimum width changes.
  Previously in-memory only, so a split set deliberately survived
  closing the pane but not restarting the app.

* ``pane_zoom_pct`` — page zoom, as a percentage. A question bank laid
  out for a full window sits in half of one, which is the constraint a
  side pane imposes and a full window does not.

All idempotent adds via ``add_column_if_missing``.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 16
NAME = "browser_pane_state"


def upgrade(conn: sqlite3.Connection) -> None:
    add_column_if_missing(
        conn, "user_preferences", "pane_open_mode",
        "VARCHAR(20) NOT NULL DEFAULT 'last'",
    )
    add_column_if_missing(
        conn, "user_preferences", "pane_default_source_id", "INTEGER",
    )
    add_column_if_missing(
        conn, "user_preferences", "pane_last_url", "TEXT",
    )
    add_column_if_missing(
        conn, "user_preferences", "pane_split_app_pct", "INTEGER",
    )
    add_column_if_missing(
        conn, "user_preferences", "pane_zoom_pct",
        "INTEGER NOT NULL DEFAULT 100",
    )
