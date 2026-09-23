"""Device-local settings, and the profile's own identifier (#126, #129).

Two identifiers with **opposite travel rules** meet in this module, and
swapping them would be a quiet, serious bug:

======================  =========================================
identifier              must it travel with a profile?
======================  =========================================
device id               **No.** It names the machine. It lives in
                        the master database's ``app_settings``
                        (``MasterDatabase.get_device_id``), which
                        is per-install and never packed into a
                        ``.wimi``. This module only *consumes* it.
profile uuid            **Yes.** It names the profile. It lives in
                        ``profile_identity`` in this database, so
                        it survives export, import, rename and
                        re-install for free.
======================  =========================================

``ankiconnect_host = 'localhost'`` is the canonical argument for the
first row: it **denotes a different machine on each device**, so copying
it is wrong even when the two values are byte-identical.

**How a profile behaves on a machine it has never met.** It finds no
``device_settings`` row for that machine's device id, so it takes the
schema defaults. Rows belonging to other devices travel along inside the
snapshot and are simply ignored. That is self-healing, needs no master
involvement, and is precisely the behaviour the issue asks for.

**The legacy columns are still on ``user_preferences``.** m021 leaves
them rather than rebuilding two tables of real user data for columns
that, once nothing reads them, are inert. The guard that matters is
here and in ``PreferencesMixin``: the moved fields are gone from the
``UserPreferences`` dataclass, and ``update_preferences`` raises rather
than writing one.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..device_local import (
    DEVICE_LOCAL_SETTING_FIELDS,
    LEGACY_DEVICE_ID,
    UNKNOWN_DEVICE_ID,
    partition_settings,
)
from ..exceptions import ValidationError
from ..models import DeviceSettings


class DeviceSettingsMixin:
    """Mixin for device-local settings + profile identity. Composed into UserDatabase."""

    # Instance flag, declared on the class so a mixin needs no __init__.
    _legacy_device_rows_claimed = False

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def device_id(self) -> str:
        """This machine's device id, as handed to ``UserDatabase``.

        Resolved at call time, never captured: the id is supplied by the
        master database and a profile switch rebuilds the user database
        around it.
        """
        return getattr(self, "_device_id", None) or UNKNOWN_DEVICE_ID

    def get_profile_uuid(self) -> str:
        """This profile's stable identifier (#129).

        Minted by m021 and never re-minted. The defensive re-mint below
        covers a database that somehow reached here without the row —
        a mint is strictly better than returning ``None`` to a caller
        that is about to record an identity somewhere.
        """
        row = self.fetchone(
            "SELECT profile_uuid FROM profile_identity WHERE id = 1"
        )
        if row and row["profile_uuid"]:
            return str(row["profile_uuid"])

        import uuid as _uuid

        minted = str(_uuid.uuid4())
        with self.transaction():
            self.execute(
                "INSERT OR IGNORE INTO profile_identity (id, profile_uuid) "
                "VALUES (1, ?)",
                (minted,),
            )
        row = self.fetchone(
            "SELECT profile_uuid FROM profile_identity WHERE id = 1"
        )
        return str(row["profile_uuid"]) if row else minted

    # ------------------------------------------------------------------
    # The one-time handover from the pre-m021 world
    # ------------------------------------------------------------------

    def _claim_legacy_device_rows(self) -> None:
        """Re-key m021's handover rows onto this machine, exactly once.

        A migration cannot know the device id — it lives in a different
        database — so m021 parks the values it moved under
        ``LEGACY_DEVICE_ID``. They belong to the machine that ran the
        migration, and that machine is this process, microseconds later.
        Re-keying them here means a second machine opening the same
        profile can never inherit them.

        Idempotent and cheap; guarded by an instance flag so it costs two
        UPDATEs per opened database rather than two per read.
        """
        if self._legacy_device_rows_claimed:
            return
        self._legacy_device_rows_claimed = True

        device = self.device_id()
        if device == LEGACY_DEVICE_ID:
            return

        with self.transaction():
            # If this device already has a row, the handover is stale —
            # drop it rather than fail the UNIQUE index.
            mine = self.fetchone(
                "SELECT id FROM device_settings WHERE device_id = ?", (device,)
            )
            if mine:
                self.execute(
                    "DELETE FROM device_settings WHERE device_id = ?",
                    (LEGACY_DEVICE_ID,),
                )
            else:
                self.execute(
                    "UPDATE device_settings SET device_id = ? WHERE device_id = ?",
                    (device, LEGACY_DEVICE_ID),
                )

            self.execute(
                "DELETE FROM device_source_settings "
                "WHERE device_id = ? AND source_id IN ("
                "  SELECT source_id FROM device_source_settings WHERE device_id = ?"
                ")",
                (LEGACY_DEVICE_ID, device),
            )
            self.execute(
                "UPDATE device_source_settings SET device_id = ? WHERE device_id = ?",
                (device, LEGACY_DEVICE_ID),
            )

    # ------------------------------------------------------------------
    # device_settings
    # ------------------------------------------------------------------

    def get_device_settings(self) -> DeviceSettings:
        """Settings for this machine, creating the row on first use."""
        self._claim_legacy_device_rows()

        row = self.fetchone(
            "SELECT * FROM device_settings WHERE device_id = ?",
            (self.device_id(),),
        )
        if row:
            return DeviceSettings.from_db_row(row)
        return self.create_default_device_settings()

    def create_default_device_settings(self) -> DeviceSettings:
        """Insert this machine's row with the schema defaults."""
        with self.transaction():
            self.execute(
                "INSERT OR IGNORE INTO device_settings (device_id) VALUES (?)",
                (self.device_id(),),
            )
        row = self.fetchone(
            "SELECT * FROM device_settings WHERE device_id = ?",
            (self.device_id(),),
        )
        return DeviceSettings.from_db_row(row)

    def update_device_settings(self, **kwargs) -> DeviceSettings:
        """Update this machine's settings.

        Validation mirrors ``update_preferences`` — the ranges did not
        change when the columns moved, they just moved with them. m021
        deliberately puts no CHECK constraints on these columns: an
        out-of-range legacy value must be a value to clamp, not a failed
        migration and an app that will not open.
        """
        settings = self.get_device_settings()

        validated_fields = {
            "pane_zoom_pct": (25, 500),
            "pane_split_app_pct": (5, 95),
            "ankiconnect_port": (1000, 65535),
            "mcp_server_port": (1024, 65535),
        }

        updates: List[str] = []
        params: List[Any] = []
        for field, value in kwargs.items():
            if field not in DEVICE_LOCAL_SETTING_FIELDS:
                raise ValidationError(
                    f"'{field}' is not a device-local setting. User-level "
                    f"preferences go through update_preferences()."
                )
            constraint = validated_fields.get(field)
            if constraint is not None and value is not None:
                low, high = constraint
                if not (low <= value <= high):
                    raise ValidationError(
                        f"{field} must be between {low} and {high}"
                    )
            updates.append(f"{field} = ?")
            params.append(value)

        if not updates:
            return settings

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(self.device_id())

        with self.transaction():
            self.execute(
                f"UPDATE device_settings SET {', '.join(updates)} "
                f"WHERE device_id = ?",
                tuple(params),
            )

        return self.get_device_settings()

    # ------------------------------------------------------------------
    # The merged view the UI works in
    # ------------------------------------------------------------------

    def get_all_settings(self) -> Dict[str, Any]:
        """User preferences and this machine's device settings, merged.

        The split is a *storage and travel* property, not something the
        settings page has any reason to model, so the UI keeps seeing one
        flat object. Ordering matters: device values win, because any
        overlap would be a legacy column nothing should be reading.
        """
        from dataclasses import asdict

        prefs = self.get_preferences()
        device = self.get_device_settings()

        merged: Dict[str, Any] = {}
        if prefs is not None:
            merged.update(asdict(prefs))
        device_dict = asdict(device)
        device_dict.pop("id", None)
        device_dict.pop("device_id", None)
        device_dict.pop("created_at", None)
        device_dict.pop("updated_at", None)
        merged.update(device_dict)
        return merged

    def update_settings(self, **kwargs) -> Dict[str, Any]:
        """Write a mixed bag of settings to whichever store owns each one."""
        user_fields, device_fields = partition_settings(kwargs)
        # One transaction over both writes: #95 made ``transaction()``
        # re-entrant with real savepoints, so the inner blocks nest and
        # the whole composite is atomic.
        with self.transaction():
            if user_fields:
                self.update_preferences(**user_fields)
            if device_fields:
                self.update_device_settings(**device_fields)
        return self.get_all_settings()

    # ------------------------------------------------------------------
    # device_source_settings — the per-question-source half
    # ------------------------------------------------------------------

    def get_device_source_settings(self) -> Dict[int, Dict[str, Any]]:
        """This machine's pane state per question source, keyed by source id."""
        self._claim_legacy_device_rows()
        rows = self.fetchall(
            "SELECT source_id, pane_desktop_site, pane_last_opened_at "
            "FROM device_source_settings WHERE device_id = ?",
            (self.device_id(),),
        )
        return {
            int(r["source_id"]): {
                "desktop_site": bool(r["pane_desktop_site"]),
                "last_opened_at": r["pane_last_opened_at"],
            }
            for r in rows
        }

    def _upsert_device_source(self, source_id: int, column: str, value: Any) -> None:
        """Set one per-source, per-device column, creating the row if needed.

        ``column`` is never caller-supplied — the two callers below pass
        a literal — so the f-string carries no injection surface.
        """
        self._claim_legacy_device_rows()
        with self.transaction():
            self.execute(
                "INSERT OR IGNORE INTO device_source_settings "
                "(device_id, source_id) VALUES (?, ?)",
                (self.device_id(), source_id),
            )
            self.execute(
                f"UPDATE device_source_settings "
                f"SET {column} = ?, updated_at = CURRENT_TIMESTAMP "
                f"WHERE device_id = ? AND source_id = ?",
                (value, self.device_id(), source_id),
            )
