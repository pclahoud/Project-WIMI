"""User DB migration v31 -- which first-run tour steps a student has been shown.

Adds ``user_preferences.tour_seen_steps``: TEXT, a JSON list of step keys,
default ``'[]'``.

Why a list and not a yes/no flag (#430, owner, 2026-10-09)
---------------------------------------------------------
#430 originally planned a per-page seen flag. Measured on the dashboard, the
first page built, a true first run has something to point at for **1 of its 5
steps**. There are no exam cards yet, Quick Analytics renders its empty state
until there are entries, and Delete Permanently exists only on a suspended
exam. The owner's decision: **a step is shown once it can be.** Each visit
shows only the steps whose target is on screen and records them; the rest wait
for a later visit. A boolean cannot say "three of five", so the column holds
the shown steps themselves.

A step's key is ``page:anchor``, where ``anchor`` is the step's base anchor
even when it forks. If a chapter edit changes a step's anchor, it is a
different step and is shown again, which is the honest outcome.

User-level, and it travels
--------------------------
The #126/#129 test: does the value denote a machine? No. It records what *this
student* has been taught, and someone who learned WIMI on one computer should
not be taught it again on their second. Direct precedent:
``stt_show_first_use_notice`` (m023), user-level and travelling. So it is
deliberately absent from ``DEVICE_LOCAL_SETTING_FIELDS``.

Kept out of the Settings save path
----------------------------------
It is not a field of the ``UserPreferences`` dataclass. Settings saves the
preferences it shows, and a bulk save must never be able to rewrite what the
student has been shown. ``PreferencesMixin`` reads and writes it through its own
three methods, and Replay in Settings is one of them (it empties the list).

No backfill: every existing profile starts at ``'[]'``, which is the truth.
Nobody has been shown a tour step, because none has ever run.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 31
NAME = "tour_seen_steps"


def upgrade(conn: sqlite3.Connection) -> None:
    add_column_if_missing(
        conn, "user_preferences", "tour_seen_steps",
        "TEXT NOT NULL DEFAULT '[]'")
