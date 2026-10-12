"""User DB migration v30 -- reset two never-read preferences to their new defaults.

No schema change. One ``UPDATE`` over ``user_preferences``, moving every row's
``analytics_detail_level`` to ``'advanced'`` and ``manual_break_control`` to
``0``.

The decision (#504, owner, 2026-10-07)
--------------------------------------
Nine Settings controls were stored and read by nothing. The owner chose to make
seven of them live rather than mark them *Coming Soon* or delete them, which
turns two columns that held inert values into columns that decide what a student
sees::

    analytics_detail_level  'detailed'  ->  drops the cross-dimension heatmap,
                                            Study Recommendations and
                                            Interaction Effects
    manual_break_control    1           ->  "Only take breaks when I ask", so a
                                            round's end offers no break

Both are what m001's column DEFAULTs put there (``VARCHAR(20) DEFAULT
'detailed'`` and ``BOOLEAN DEFAULT 1``), so **every profile that predates #504
holds them**. Without this migration, installing that build would silently take
three analytics views and the round-end break offer away from every existing
student, as a side effect of an upgrade. That is the whole reason this file
exists.

**The owner's answer was to reset every row**, not to try to honour what is
stored.

Why not "reset only the untouched rows"
---------------------------------------
Because it is not implementable as stated. ``user_preferences`` has **no
``updated_at`` and no per-field modification record**, so a row holding
``'detailed'`` is indistinguishable from one where a student deliberately chose
Detailed. Both controls have been real, enabled, savable controls on the
Settings page all along, so deliberate rows may exist and cannot be identified.

What the decision costs, stated rather than glossed: a student who deliberately
set Summary, or who deliberately ticked the break box, loses that choice. The
argument for discarding it is that **neither value has ever taken effect** --
nothing read either column -- so no student has seen the choice honoured and
none will notice it going.

The two fields were decided separately, and the reasoning differs
-----------------------------------------------------------------
Worth keeping, because a later sweep would otherwise read them as one rule.

* ``analytics_detail_level`` is safe either way. The stored value now *removes*
  views, so resetting it only ever adds them back. There is no direction in
  which resetting this field costs a student something.
* ``manual_break_control`` is **not** symmetric, because #504 changed the
  control's label to *"Only take breaks when I ask"*. A tick against the old
  wording is not consent to the new sentence, so the stored ``1`` is not a
  preference about the new control at all. This field would want resetting even
  if the other did not.

Unconditional, and that is deliberate
-------------------------------------
No ``WHERE``. A conditional reset would have to name the old values, which is
the "untouched rows" idea above wearing a different shape, and it would leave
the migration's effect depending on data nobody can characterise. Setting both
columns outright is the only version whose outcome is the same on every
database.

It is also **idempotent by construction** -- running it twice writes the same
values -- so a re-run is free and no guard is needed.

Ordering: this must be applied before #504's branch is merged, and it is a
**no-op in effect until then**, because nothing on master reads either column.
Safe to land on its own.

Why there is no m029
--------------------
m029 was reserved for a parallel batch that finished without needing a
migration, and **it must now stay permanently skipped** for the same reason
m008 and m011--m014 are. The runner treats a stamped version as applied: a
database that has taken 30 would later apply a 29 *after* it, out of order.
A gap costs nothing; a reused number is unrecoverable on databases in the wild.
"""
from __future__ import annotations

import sqlite3

VERSION = 30
NAME = "settings_defaults_reset"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE user_preferences
           SET analytics_detail_level = 'advanced',
               manual_break_control = 0
        """
    )
