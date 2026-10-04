"""User DB migration v23 — where speech-to-text keeps its four settings.

Two columns on ``user_preferences`` and two on ``device_settings``. No
column on ``question_entries``: the microphone goes on the two fields the
entry form already has, so the entry save path is untouched (#59, owner's
decision D1).

Is a migration needed at all?
-----------------------------
D1 removed the only column this feature was going to add to
``question_entries``, so the question is fair and the answer should not
be momentum. It is still yes, and the reason is **travel**, not storage.
Two generic stores already exist and neither can hold these four:

* ``plugin_data`` (user database, ``plugin_id``/``key``/``value``) is
  namespaced to plugins, and — decisively — it travels inside a
  ``.wimi`` like everything else in this file. Putting the microphone id
  there would copy one machine's hardware onto another, which is the
  exact defect #126 exists to prevent.
* ``app_settings`` in the **master** database never travels, which suits
  the device-local pair, but it is per-install and outside the settings
  routing path: ``get_all_settings()`` / ``update_settings()`` merge
  ``user_preferences`` with ``device_settings`` and nothing else, so the
  settings page could not read or write a value parked there without new
  plumbing in three layers.

So the four values need the two stores that already have the right
travel rules, and reaching them means columns.

**No column records whether the model is installed.** The file on disk
plus its sha256 is the truth, checked by ``stt/runtime.py`` and cached
per process. A flag would be a second source of truth that disagrees in
exactly the case that matters — a half-deleted or corrupted download.

Which side each column is on (#126 / #129)
------------------------------------------
m021 split ``user_preferences`` in two, and the test settled there is
whether a value **denotes a machine**. ``ankiconnect_host`` does:
``localhost`` names a different computer on each device, so copying it
is wrong even when the two strings are byte-identical.

``stt_input_device_id`` — **device-local.** A ``QAudioDevice`` id string
naming a specific piece of hardware attached to *this* computer. Copied
into a ``.wimi`` it points the other machine at a microphone that does
not exist there. This is the ``ankiconnect_host`` case with no argument
needed.

``stt_model_size`` — **device-local**, and this one earns the label on a
narrower argument than "a faster CPU wants a bigger model". That looser
form is the argument ``realtime_update_delay_ms`` was *rejected* on and
is recorded as rejected in ``device_local.py``: a machine-speed tuning
value is meaningful everywhere, so it does not denote a machine. What
settles this column is that the value **names a weights file in this
machine's** ``app_data/models/``, and ``app_data/`` does not travel. A
profile carrying ``small`` onto a machine that only ever downloaded
``base`` names something that is not there — wrong on the other machine
rather than merely suboptimal on it, which is the distinction the split
turns on.

``stt_priming_enabled`` — **user-level.** A stated preference about how
the student wants decoding to behave, the same class as
``pane_open_mode``. It means the same thing on any machine and should
follow the student into a ``.wimi``. Deliberately **absent** from
``DEVICE_LOCAL_SETTING_FIELDS``.

``stt_show_first_use_notice`` — **user-level**, and worth stating why,
because the notice's own wording ("your audio never leaves *this
computer*") invites the opposite reading. The column does not record a
fact about a computer; it records whether *the student* has been told
how the feature handles their audio. That is knowledge they keep when
they sit down at their laptop, and the claim is true of WIMI on every
machine, not of one of them. The failure modes are also asymmetric: the
worst a travelling value can do here is show a reassurance once too
often or once too seldom, whereas a travelling ``stt_input_device_id``
silently selects the wrong hardware.

Defaults
--------
``stt_priming_enabled`` defaults to **1**. §3.6 designs priming as the
behaviour the feature ships with and the preference as the escape hatch
R6 names ("exists so it can be turned off"), so on is the designed
default. Whether priming actually helps is a measured question (T3) and
the measurement may come back unfavourable; flipping the default then
costs the same either way, since existing rows keep whatever they store
whichever way it starts.

``stt_show_first_use_notice`` defaults to **1** — nobody has seen the
notice yet, so it is still to be shown. Dismissing it writes 0.

The two device columns are **nullable with no default**, and that is the
point: NULL means "this machine has not chosen one". Resolving NULL to
an actual model belongs to ``stt/model_spec.py``, which carries the
pinned revision and digest; a ``DEFAULT 'base'`` here would be a second
statement of what the default model is, able to disagree with the pinned
spec the moment that changes. For the microphone, NULL means "use the
system default input device", which is also what a stored id that no
longer resolves falls back to — an unplugged USB mic must not brick the
feature.

No CHECK constraint on ``stt_model_size``. m021 states the reason for
this table: a value the app cannot use must be something to clamp at
read time, not a failed migration and an app that will not open. A CHECK
naming today's model sizes would also need a migration every time the
pinned set changes.

Idempotent adds via ``add_column_if_missing``, so re-runs and databases
that already carry the columns no-op.

Numbering: m022 is the floor. Versions 8 and 11-14 are absent from the
registry by design — see m015's docstring — so this follows m022 without
a gap of its own.
"""
from __future__ import annotations

import sqlite3

from .._helpers import add_column_if_missing

VERSION = 23
NAME = "speech_to_text_settings"


def upgrade(conn: sqlite3.Connection) -> None:
    # User-level: these follow the student into a .wimi.
    add_column_if_missing(
        conn, "user_preferences", "stt_priming_enabled",
        "BOOLEAN NOT NULL DEFAULT 1",
    )
    add_column_if_missing(
        conn, "user_preferences", "stt_show_first_use_notice",
        "BOOLEAN NOT NULL DEFAULT 1",
    )

    # Device-local: these name this machine's hardware and this
    # machine's app_data/, and must never travel.
    add_column_if_missing(
        conn, "device_settings", "stt_model_size",
        "TEXT",
    )
    add_column_if_missing(
        conn, "device_settings", "stt_input_device_id",
        "TEXT",
    )
