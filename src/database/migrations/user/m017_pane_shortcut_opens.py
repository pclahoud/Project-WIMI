"""User DB migration v17 — where a shortcut button lands.

One column on ``user_preferences``: ``pane_shortcut_opens``.

The browser pane now holds more than one page at a time, which turns a
question-bank shortcut button into an ambiguous instruction. Clicking one
used to mean "go here", because there was only one place to go. With tabs
it can also mean "open this alongside what I already have" — a student
who keeps a bank's question list and its explanation page open at once
does not want the shortcut row silently replacing either.

The two readings are both reasonable and neither is discoverable from the
button, so this is a choice rather than a default we guess at:
``'current'`` reuses the tab in front, ``'new'`` opens another one.

``'current'`` is the default because it is what the button did before
tabs existed. Defaulting to ``'new'`` would change the meaning of a
control every existing student already has a habit around, and the cost
of the wrong guess is asymmetric: reusing a tab you wanted kept is a lost
page, while opening one you did not want is a tab to close.

Idempotent add via ``add_column_if_missing``, so re-runs and databases
that already carry the column no-op.

Versions 11–14 are absent from this registry by design — see m015's
docstring for why — so this follows m016 without a gap of its own.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 17
NAME = "pane_shortcut_opens"


def upgrade(conn: sqlite3.Connection) -> None:
    add_column_if_missing(
        conn, "user_preferences", "pane_shortcut_opens",
        "VARCHAR(20) NOT NULL DEFAULT 'current'",
    )
