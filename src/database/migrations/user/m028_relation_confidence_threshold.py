"""User DB migration v28 -- the student's confidence cutoff for relation proposals.

One column on ``user_preferences``: ``relation_confidence_threshold``, a REAL,
default 0.8.

The decision (#380, owner, 2026-10-05)
--------------------------------------
Relation extraction (#60) proposes a relation only when the model's
confidence clears a cutoff. The owner decided that the cutoff is the
student's: **0.80 by default, configurable from 0.10 to 0.95 in steps of
0.05**. #4904's adjudication of real explanations measured 0.80 precision at
>= 0.8 against 0.69 with no cut, which is where the default comes from;
``app/relation_extraction/runtime.py`` carries the full reasoning, including
why the floor is low on purpose.

No CHECK constraint, on purpose
-------------------------------
The range is enforced in ``PreferencesMixin.update_preferences`` and again
where extraction takes the value (``runtime.validate_threshold``), not in the
schema. A CHECK on ``user_preferences`` could only be widened later by
rebuilding a table of real user data, and the range is a product decision
that has already moved once (a 0.50 floor was proposed and the owner chose
0.10). m026 left ``relation_types.status`` without a CHECK for the same
reason.

Why user-level and not device-local
-----------------------------------
#126/#129's test is whether a value **denotes a machine**. A judgement about
how confident a proposal must be does not, so the cutoff travels in a
``.wimi`` with the rest of the student's preferences and is deliberately
**absent** from ``DEVICE_LOCAL_SETTING_FIELDS``.

Idempotent add via ``add_column_if_missing``, so re-runs and databases that
already carry the column no-op. Follows m027 (#60's rejection table).
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 28
NAME = "relation_confidence_threshold"


def upgrade(conn: sqlite3.Connection) -> None:
    add_column_if_missing(
        conn, "user_preferences", "relation_confidence_threshold",
        "REAL NOT NULL DEFAULT 0.8",
    )
