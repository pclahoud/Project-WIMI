"""The user/device split, defined once (#126).

``user_preferences`` used to be one row carrying two incompatible kinds
of setting. ``theme_name`` and the session defaults follow the student to
any machine. ``ankiconnect_host`` — whose default is ``localhost`` —
**denotes a different machine on each device**, so copying it is wrong
even when the two values are byte-identical.

This module is the single definition of which side each setting is on,
and it lives outside ``domains/`` deliberately: the mixins must not
import each other, but ``PreferencesMixin`` and ``DeviceSettingsMixin``
both have to agree about the boundary, and so do the bridge and
``MainWindow``. A column that is device-local in one place and
user-level in another is silent either way, which is exactly the failure
this split exists to prevent.

The **per-source half** of the same split lives in
``device_source_settings``: ``question_sources.name`` and ``url`` are
shared facts about a question bank, while ``pane_desktop_site`` and
``pane_last_opened_at`` are this machine's pane state for it. Those two
are read and written through ``SourcesMixin``, which kept its method
names, so there is no field list here to keep in step.

The **device id** itself is not defined here. It names a machine, so it
lives in the master database's ``app_settings``
(``MasterDatabase.get_device_id``) — per-install, and never packed into
a ``.wimi``.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

#: Device id used when no machine identity was supplied. Production code
#: always threads one through from ``MasterDatabase.get_device_id()``;
#: this is what a bare ``UserDatabase(...)`` in a test, or a short-lived
#: verify-open during import, gets — so such a connection still has
#: somewhere coherent to read and write.
UNKNOWN_DEVICE_ID = "unknown-device"

#: Reserved device id that m021 parks pre-migration values under until
#: the machine that owns them claims the row. A migration runs against a
#: bare connection and cannot know the device id, because it lives in a
#: different database.
LEGACY_DEVICE_ID = "__pre_m021__"

#: The columns m021 moved out of ``user_preferences``.
#:
#: What is **not** here is as deliberate as what is:
#:
#: * ``pane_open_mode``, ``pane_shortcut_opens`` — stated preferences
#:   with a control in Settings. Each means the same thing on any
#:   machine.
#: * ``pane_default_source_id`` — references a ``question_sources`` row,
#:   and that row travels inside the same snapshot, so the id denotes the
#:   same question bank on the other machine. Contrast
#:   ``ankiconnect_host``, whose identical string denotes a different
#:   machine. That is the test.
#: * ``realtime_update_delay_ms``, the backup policy numbers,
#:   ``anki_cache_refresh_interval_minutes`` — tuning and policy. A
#:   faster machine might want a different delay, but the value is
#:   meaningful everywhere; it does not *denote* a machine.
DEVICE_LOCAL_SETTING_FIELDS: Tuple[str, ...] = (
    # Browser pane geometry and session state: this machine's display,
    # this machine's window, where this machine was.
    "pane_last_url",
    "pane_split_app_pct",
    "pane_zoom_pct",
    # AnkiConnect names a process on THIS machine.
    "ankiconnect_enabled",
    "anki_integration_enabled",
    "ankiconnect_host",
    "ankiconnect_port",
    # The MCP server binds a TCP port on THIS machine and is auto-started
    # at launch, so whether it runs — and on which port — is a fact about
    # one machine's processes.
    "mcp_server_enabled",
    "mcp_server_port",
)


def partition_settings(
    fields: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Split a flat settings dict into ``(user_fields, device_fields)``.

    Callers that accept a mixed bag from the UI — the settings page saves
    every ``data-field`` through one call — use this so neither store
    ever sees a key belonging to the other.
    """
    user_fields: Dict[str, Any] = {}
    device_fields: Dict[str, Any] = {}
    for key, value in fields.items():
        if key in DEVICE_LOCAL_SETTING_FIELDS:
            device_fields[key] = value
        else:
            user_fields[key] = value
    return user_fields, device_fields
