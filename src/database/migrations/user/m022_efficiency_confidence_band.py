"""User DB migration v22 — how the efficiency score shows its uncertainty.

One column on ``user_preferences``: ``efficiency_show_confidence_band``.

Background (#133)
-----------------
Stage 9 multiplied each subject's efficiency *penalty* by a confidence
factor keyed on ``subject_edges.weight_source``. Because it scaled a
penalty, a weight WIMI could not vouch for produced a **smaller** penalty
and therefore a **higher** score: "we do not know where this weight came
from" was the top-scoring state. The companion ``range_confidence`` term
had the same direction problem, and the ``min()`` of the two — written so
"the less certain signal dominates" — systematically selected whichever
factor inflated the score most.

Both factors describe the *measuring stick*; the score is a statement
about the *student*. #133 took them out of the arithmetic entirely rather
than inverting them, because inverting would lower a student's score for
a data problem that is not theirs — their blueprint simply carried no
provenance metadata.

What this column is for
-----------------------
The uncertainty did not disappear, it stopped being priced in. It is now
*shown*, and how it is shown is the student's call:

* ``0`` (default) — one number, alongside the "Weight Sources" breakdown
  card that was already in the ``get_weight_analysis`` payload. Not a
  degraded mode: the provenance information is on the page either way.
* ``1`` — the score renders as a band, widened by how much of the exam's
  weight mass came from somewhere other than a published blueprint.

Default ``0`` because ``_get_efficiency_rating``'s bands (``>= 85``
Excellent, and so on) assume a scalar, and defaulting to the band would
mean rethinking the rating vocabulary in the same change.

Why user-level and not device-local
-----------------------------------
m021 (#126) split ``user_preferences`` in two, and the test settled there
is whether a value **denotes a machine**. ``ankiconnect_host`` does —
``localhost`` names a different computer on each device, so copying it is
wrong even when the two strings are identical. This does not: it is a
stated display preference, the same class as ``pane_open_mode``, and it
should follow the student into a ``.wimi`` archive. It is deliberately
**absent** from ``DEVICE_LOCAL_SETTING_FIELDS``.

Idempotent add via ``add_column_if_missing``, so re-runs and databases
that already carry the column no-op.

Numbering: m021 is the floor. Versions 8 and 11-14 are absent from the
registry by design — see m015's docstring — so this follows m021 without
a gap of its own.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 22
NAME = "efficiency_confidence_band"


def upgrade(conn: sqlite3.Connection) -> None:
    add_column_if_missing(
        conn, "user_preferences", "efficiency_show_confidence_band",
        "BOOLEAN NOT NULL DEFAULT 0",
    )
