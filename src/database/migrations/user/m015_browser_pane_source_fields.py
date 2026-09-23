"""User DB migration v15 — per-source fields for the browser pane.

The browser pane shows a shortcut button per question source that has a
web address, so the button row is a consequence of data the student
already maintains rather than a second list to curate. Two facts about a
source are the pane's, not the source's, so they live here rather than
in source management:

1. ``pane_desktop_site`` — send a desktop user-agent when opening this
   source. Previously a global "Chrome mode" checkbox on the toolbar,
   which was wrong twice over: it named the implementation
   (user-agent spoofing) rather than what the student controls, and it
   was global when the need is per-site. One qbank may serve a cramped
   mobile layout to an embedded view while another is fine.

2. ``pane_last_opened_at`` — when the pane last opened this source.
   Orders the shortcut row most-recently-used first, so the two banks
   in daily rotation stay visible when the row is capped and the rest
   overflow into a menu.

Both are idempotent adds via ``add_column_if_missing``, so re-runs and
databases that already have them no-op.

**On the version number.** This branch registers m001–m007, m009 and
m010; 11 through 14 are deliberately skipped. Databases carried over
from the abandoned capture feature already have v11–v14 stamped in
``schema_migrations``, and the runner treats a stamped version as
applied — so reusing any of those numbers would mean this migration
silently never ran on exactly the databases that already exist. Starting
at 15 clears them. The gap is intentional, like the m008 one.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 15
NAME = "browser_pane_source_fields"


def upgrade(conn: sqlite3.Connection) -> None:
    # add_column_if_missing already no-ops on a missing table, so a
    # partially-built database can't trip this.
    add_column_if_missing(
        conn,
        "question_sources",
        "pane_desktop_site",
        # DEFAULT 1, not 0: the toolbar checkbox this replaces was
        # checked by default, so every existing pane already sends the
        # Chrome user-agent. Defaulting to 0 would silently stop doing
        # that for every source at once, and a qbank that was happy to
        # log in yesterday might not be today.
        "INTEGER NOT NULL DEFAULT 1",
    )
    add_column_if_missing(
        conn,
        "question_sources",
        "pane_last_opened_at",
        "TIMESTAMP",
    )
