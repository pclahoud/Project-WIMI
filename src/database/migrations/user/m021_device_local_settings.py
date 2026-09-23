"""User DB migration v21 — device-local settings, and a stable profile id.

Two problems, one migration, because they are the same problem twice:
WIMI had no stable notion of *which device* it is running on (#126) and
no stable notion of *which profile* it is looking at (#129). Both need a
table in this database, and running two migrations over real profiles is
two chances to get it wrong instead of one.

**The two identifiers travel in opposite directions, and swapping them
would be a quiet, serious bug:**

* The **device id** names a machine. It must NOT travel with a profile,
  so it is *not minted here* — it lives in the master database's
  ``app_settings`` (``MasterDatabase.get_device_id``), which is
  per-install and never packed into a ``.wimi``. This migration only
  creates tables *keyed by* it.
* The **profile id** (``profile_identity.profile_uuid``) names a
  profile. It must survive export, import, rename and re-install, so it
  is minted *here*, inside the thing it identifies, and rides along in
  the database snapshot for free.

----------------------------------------------------------------------
``profile_identity`` — one row, minted once (#129)
----------------------------------------------------------------------

A profile was identified only by ``users.id`` (an autoincrement
allocated per install) and ``users.username`` — *which import
deliberately changes*, because ``install_profile_as_new()`` renames on
collision (``alice`` -> ``alice_2``) by design. So after export on one
machine and install on another, the two databases held the same data and
nothing related them.

The authority lives in the user database rather than in master because
an identifier stored inside the thing it identifies cannot get out of
step with it, and it survives export without anyone remembering to carry
it. Master mirrors it (``users.profile_uuid``, master m002) as an index
so the registry can answer "do I already have this profile?" without
opening every profile in turn; a divergence is always resolved in this
table's favour.

``id INTEGER PRIMARY KEY CHECK (id = 1)`` makes the singleton a schema
fact rather than a convention, so a second row is an error at the point
of the mistake instead of an ambiguity later.

----------------------------------------------------------------------
``device_settings`` / ``device_source_settings`` — per machine (#126)
----------------------------------------------------------------------

``user_preferences`` was one row carrying two incompatible kinds of
setting. ``theme_name`` and the session defaults follow the student to
any machine; ``ankiconnect_host`` (default ``localhost``) **denotes a
different machine on each device**, so copying it is wrong even when the
two values are byte-identical. Today that is wrong on every ``.wimi``
install; under folder sync (#123) it would be wrong on every sync.

Rows for *other* devices travel along and are simply ignored: a profile
opened on a machine that has never seen it finds no row for its own
device id and takes defaults, which is exactly the desired behaviour and
needs no master involvement to be self-healing.

**The legacy columns on ``user_preferences`` and ``question_sources``
are deliberately left in place.** Dropping them means a table rebuild on
real user data — the highest-risk operation available — for a column
that, once nothing reads it, is inert. The guard that actually matters
is in code: the moved fields are gone from the ``UserPreferences``
dataclass and ``PreferencesMixin.update_preferences`` raises a
``ValidationError`` naming the right method if it is handed one, so a
future caller gets an error rather than a value nobody updates.

----------------------------------------------------------------------
The handover row
----------------------------------------------------------------------

A migration runs against a bare ``sqlite3.Connection`` and cannot know
this machine's device id (it lives in a different database). But the
values it is moving belong to exactly one machine — the one running the
migration. So they are parked under the reserved device id
``__pre_m021__`` and claimed by the first device that asks for its
settings, which on that machine is the same process microseconds later.
Once claimed the row is re-keyed, so a second machine can never inherit
it.

The handover row is written only when a ``user_preferences`` row already
exists. A brand-new profile runs this migration too, and seeding a
handover from defaults would hand the first device a row it should have
minted itself.

Versions 8 and 11-14 are absent from the registry by design — see m015's
docstring — so this follows m020 without a gap of its own.
"""
from __future__ import annotations

import sqlite3
import uuid

from .._helpers import get_column_names, get_table_names

VERSION = 21
NAME = "device_local_settings"

#: Reserved device id holding pre-migration values until the machine that
#: owns them claims the row. Deliberately a literal rather than an import
#: from ``database.device_local``: a migration is a historical record and
#: must keep meaning what it meant when it was applied, whatever the app
#: renames later. ``tests/database/migrations/test_user_021_device_local.py``
#: asserts the two still agree.
LEGACY_DEVICE_ID = "__pre_m021__"


def upgrade(conn: sqlite3.Connection) -> None:
    tables = get_table_names(conn)

    # ---------------------------------------------------------------- #129
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_identity (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            profile_uuid TEXT NOT NULL UNIQUE,
            minted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # INSERT OR IGNORE, not "check then insert": re-running must never
    # mint a second id, and the CHECK above makes a second row an error
    # rather than a silent duplicate identity.
    conn.execute(
        "INSERT OR IGNORE INTO profile_identity (id, profile_uuid) VALUES (1, ?)",
        (str(uuid.uuid4()),),
    )

    # ---------------------------------------------------------------- #126
    # No CHECK constraints on the value columns. Ranges are validated in
    # ``update_device_settings`` exactly as they were in
    # ``update_preferences``, and a CHECK here would turn an
    # out-of-range legacy value into a failed migration — i.e. an app
    # that will not open — rather than a value to clamp.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL UNIQUE,

            -- Browser pane geometry and session state. Zoom and split
            -- describe this machine's display and window; the last URL
            -- is where this machine was, not where the student is.
            pane_last_url TEXT,
            pane_split_app_pct INTEGER,
            pane_zoom_pct INTEGER NOT NULL DEFAULT 100,

            -- AnkiConnect names a process on THIS machine. 'localhost'
            -- is the whole argument for this table.
            ankiconnect_enabled BOOLEAN NOT NULL DEFAULT 0,
            anki_integration_enabled BOOLEAN NOT NULL DEFAULT 0,
            ankiconnect_host VARCHAR(255) NOT NULL DEFAULT 'localhost',
            ankiconnect_port INTEGER NOT NULL DEFAULT 8765,

            -- The MCP server binds a TCP port on THIS machine and is
            -- auto-started at launch. Whether it runs, and on which
            -- port, is a fact about one machine's processes.
            mcp_server_enabled BOOLEAN NOT NULL DEFAULT 0,
            mcp_server_port INTEGER NOT NULL DEFAULT 8000,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_source_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            source_id INTEGER NOT NULL
                REFERENCES question_sources(id) ON DELETE CASCADE,
            pane_desktop_site INTEGER NOT NULL DEFAULT 1,
            pane_last_opened_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (device_id, source_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_source_settings_device "
        "ON device_source_settings(device_id)"
    )

    # ------------------------------------------------------- handover row
    # Only for a profile that already has preferences. A fresh database
    # runs this migration too and must not be handed a row it should
    # mint itself.
    pref_cols = get_column_names(conn, "user_preferences")
    if "user_preferences" in tables and pref_cols:
        # Defaults applied HERE, not in a repair UPDATE afterwards.
        # ``user_preferences`` declares most of these nullable while
        # ``device_settings`` does not, and an ``INSERT OR IGNORE`` that
        # trips a NOT NULL constraint drops the WHOLE row silently — the
        # handover would vanish and the machine would quietly lose every
        # setting this migration exists to preserve.
        defaults = {
            "pane_last_url": None,
            "pane_split_app_pct": None,
            "pane_zoom_pct": 100,
            "ankiconnect_enabled": 0,
            "anki_integration_enabled": 0,
            "ankiconnect_host": "localhost",
            "ankiconnect_port": 8765,
            "mcp_server_enabled": 0,
            "mcp_server_port": 8000,
        }
        # Columns are read defensively: a database stamped v11-v14 by the
        # abandoned capture branch reached m015-m017 through
        # ``add_column_if_missing``, and a partially-built test database
        # may be missing any of them.
        present = [c for c in defaults if c in pref_cols]
        if present:
            row = conn.execute(
                f"SELECT {', '.join(present)} FROM user_preferences "
                f"ORDER BY id LIMIT 1"
            ).fetchone()
            if row is not None:
                values = []
                for i, col in enumerate(present):
                    value = row[i]
                    if value is None and defaults[col] is not None:
                        value = defaults[col]
                    values.append(value)
                cols = ["device_id"] + present
                conn.execute(
                    f"INSERT OR IGNORE INTO device_settings "
                    f"({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})",
                    tuple([LEGACY_DEVICE_ID] + values),
                )

    source_cols = get_column_names(conn, "question_sources")
    if {"pane_desktop_site", "pane_last_opened_at"} <= source_cols:
        # Only sources the pane has actually touched, or whose desktop
        # flag was turned off. Everything else is the default and would
        # make the handover carry noise.
        conn.execute(
            "INSERT OR IGNORE INTO device_source_settings "
            "(device_id, source_id, pane_desktop_site, pane_last_opened_at) "
            "SELECT ?, id, COALESCE(pane_desktop_site, 1), pane_last_opened_at "
            "FROM question_sources "
            "WHERE pane_last_opened_at IS NOT NULL "
            "   OR COALESCE(pane_desktop_site, 1) != 1",
            (LEGACY_DEVICE_ID,),
        )
