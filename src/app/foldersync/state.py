"""
The device-local link between a profile and a sync folder.

**Why the link is a file and not a database column.** The mapping *this
machine's user row -> that folder* is inherently device-local: two machines
holding the same profile legitimately point it at two different paths
(``C:\\Users\\sam\\Box\\...`` and ``~/Library/CloudStorage/Box-Box/...``), and a
synced column would carry the wrong machine's answer. So this stays a JSON
file in the app-data directory, and that is the correct shape rather than a
workaround.

**What is no longer here, and why that matters.** The spike this grew from
minted its own device id into this file and minted its own per-profile "sync
id", because when it was written neither existed in the schema (#129). Both
landed in m021/m002 while the spike sat on a branch:

* the **device id** is ``MasterDatabase.get_device_id()`` — master's
  ``app_settings``, per-install, never packed into a ``.wimi``;
* the **profile id** is ``profile_identity.profile_uuid`` inside the user
  database, mirrored to ``users.profile_uuid``, and already carried in every
  archive manifest.

Minting a second device id here would have put two ids on one machine, which
is precisely the "one definition" failure ``device_local.py`` exists to
prevent. So this module reads identity and never mints it, and ``SyncLink``
carries the profile uuid rather than an id of its own invention.

That collapses a whole negotiation. The folder segment for a profile is
``WIMI/<profile-uuid>/``, which is **derived, not agreed**: a second device
linking the same profile computes the same path without adopting anything, and
two different profiles cannot collide. The spike's "the folder is the authority
on its own identity, device A mints and device B adopts" rule is gone with it.

No Qt imports, and the app-data directory is passed in rather than resolved
here -- ``MasterDatabase.data_dir`` already carries the frozen-vs-dev answer
from ``main.get_application_paths()``, so there is exactly one place that
resolves it.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

from .manifest import NO_PARENT, utc_now_iso
from .naming import sanitize_device_name

STATE_DIR_NAME = "foldersync"
STATE_FILE_NAME = "state.json"

STATE_FORMAT_VERSION = 1


@dataclass
class DeviceIdentity:
    """
    This installation's identity, as read from the master database.

    Never minted here. ``ProfileFolderSync._device_identity()`` builds it from
    ``MasterDatabase.get_device_id()`` / ``get_device_name()``, so the id that
    names this machine for sync is the same id ``device_settings`` is keyed on.
    """
    device_id: str
    device_name: str

    @property
    def slug(self) -> str:
        """The ``<device>`` segment of a generation file name."""
        return sanitize_device_name(self.device_name)

@dataclass
class SyncLink:
    """
    One profile on this machine, linked to one folder.

    ``sync_id`` is the profile's own ``profile_uuid`` (#129), not an
    identifier this layer invents. It is what names the folder segment, so
    two devices holding the same profile compute the same path with nothing
    to negotiate, and two different profiles can share a folder without
    colliding.

    ``last_seen_generation`` / ``last_seen_at`` are what the UI is allowed to
    show. They are the only honest claim available: you cannot force a sync or
    know when one finished, so "nothing new" and "the other device has not
    uploaded yet" are indistinguishable from the filesystem. The panel shows
    *last seen generation and when*, never a tick implying more.

    ``base_sha256`` is **what this device's local copy descends from** (#148,
    #149): the digest of the generation it last published, or last installed
    from the folder. It is the parent of this device's next push. Before it
    existed the parent was read off the folder head at push time, so a device
    that had never fetched published its content as if it had built on work it
    never had, and the other device's newer generation silently dropped out of
    the head. ``last_seen_generation`` must never stand in for it: *seen* is
    not *have*, and that substitution is #149 exactly.

    ``pending`` is a fork resolution the student has chosen but not yet sent.
    The owner decided (#148) that choosing stays local until the student
    sends, so it lives here -- device-local, like the link -- and the next push
    carries it: ``parents`` as the content parent, ``supersedes`` as the heads
    the student saw and chose against. ``saw_heads`` is every head at the
    moment of choosing, so a send can tell that the folder has moved since.
    """
    user_id: int
    sync_id: str
    folder: str
    provider_id: str = "generic"
    last_seen_generation: int = NO_PARENT
    last_seen_at: Optional[str] = None
    last_pushed_generation: int = NO_PARENT
    last_pushed_at: Optional[str] = None
    base_sha256: Optional[str] = None
    base_generation: int = NO_PARENT
    pending: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "SyncLink":
        return cls(
            user_id=int(raw["user_id"]),
            sync_id=str(raw["sync_id"]),
            folder=str(raw["folder"]),
            provider_id=str(raw.get("provider_id") or "generic"),
            last_seen_generation=int(raw.get("last_seen_generation") or NO_PARENT),
            last_seen_at=raw.get("last_seen_at"),
            last_pushed_generation=int(raw.get("last_pushed_generation") or NO_PARENT),
            last_pushed_at=raw.get("last_pushed_at"),
            base_sha256=raw.get("base_sha256") or None,
            base_generation=int(raw.get("base_generation") or NO_PARENT),
            pending=_pending_or_none(raw.get("pending")),
        )


def _pending_or_none(raw: Any) -> Optional[Dict[str, Any]]:
    """A stored pending resolution, or ``None`` if it is not one.

    Read defensively: a malformed entry must not take the whole link down
    with it (``get_link`` would return ``None`` and the profile would look
    unlinked). Dropping a bad pending is safe -- nothing has been sent, and
    the fork it described is still in the folder to be chosen again.
    """
    if not isinstance(raw, dict):
        return None
    parents = raw.get("parents")
    supersedes = raw.get("supersedes")
    if not isinstance(parents, list) or not isinstance(supersedes, list):
        return None
    return {
        "choice": str(raw.get("choice") or ""),
        "parents": [str(x) for x in parents],
        "supersedes": [str(x) for x in supersedes],
        "saw_heads": [str(x) for x in (raw.get("saw_heads") or [])],
        "resolved_at": raw.get("resolved_at"),
        "kept_device": raw.get("kept_device"),
        "set_aside_devices": list(raw.get("set_aside_devices") or []),
    }


class SyncState:
    """
    Device-local sync state, persisted as one small JSON file.

    Written atomically (temp file in the same directory, then ``os.replace``).
    This file lives in the app-data directory, **never in the sync folder**, so
    the atomic-rename caveat that applies to cloud filesystems does not apply
    here — this is ordinary local disk.
    """

    def __init__(self, app_data_dir: str | Path):
        self.app_data_dir = Path(app_data_dir)
        self.state_dir = self.app_data_dir / STATE_DIR_NAME
        self.state_path = self.state_dir / STATE_FILE_NAME
        self._data: Dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------ persistence

    def _load(self) -> None:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        raw.setdefault("format_version", STATE_FORMAT_VERSION)
        raw.setdefault("links", {})
        self._data = raw

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(self.state_dir), prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, str(self.state_path))
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ links

    def get_link(self, user_id: int) -> Optional[SyncLink]:
        raw = self._data.get("links", {}).get(str(int(user_id)))
        if not isinstance(raw, dict):
            return None
        try:
            return SyncLink.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return None

    def put_link(self, link: SyncLink) -> None:
        self._data.setdefault("links", {})[str(int(link.user_id))] = link.to_dict()
        self._save()

    def drop_link(self, user_id: int) -> None:
        self._data.setdefault("links", {}).pop(str(int(user_id)), None)
        self._save()

    def link_or_create(
        self,
        user_id: int,
        sync_id: str,
        folder: str,
        provider_id: str = "generic",
    ) -> SyncLink:
        """
        Get this profile's link, creating one if it has never been linked.

        ``sync_id`` is required and is the profile's ``profile_uuid``. Nothing
        is minted here: a profile that reached this point without a uuid is a
        bug upstream, not something to paper over with a fresh id that would
        make the same profile look like two.
        """
        if not sync_id:
            raise ValueError("sync_id (the profile uuid) is required")
        existing = self.get_link(user_id)
        if existing is not None and existing.sync_id == sync_id:
            if existing.folder != folder or existing.provider_id != provider_id:
                existing.folder = folder
                existing.provider_id = provider_id
                self.put_link(existing)
            return existing
        link = SyncLink(
            user_id=int(user_id),
            sync_id=str(sync_id),
            folder=str(folder),
            provider_id=str(provider_id),
        )
        # A profile installed from this folder before it was linked already
        # knows what it descends from. Without this, its first push would
        # claim no ancestor and every other device would be told the two
        # copies share no history -- true of neither.
        installed = self._data.get("install_bases", {}).pop(str(int(user_id)), None)
        if isinstance(installed, dict) and installed.get("sync_id") == sync_id:
            link.base_sha256 = installed.get("sha256") or None
            link.base_generation = int(installed.get("generation") or NO_PARENT)
        self.put_link(link)
        return link

    def record_push(
        self,
        user_id: int,
        generation: int,
        sha256: Optional[str] = None,
        *,
        sent_pending: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a published generation. It is now this device's base.

        ``sent_pending`` is the resolution the push carried, if any. It is
        cleared only when it is still the one stored: a student who chose
        again while the push was in flight has a newer choice, and a push
        carrying the old one must not erase it.
        """
        link = self.get_link(user_id)
        if link is None:
            return
        link.last_pushed_generation = int(generation)
        link.last_pushed_at = utc_now_iso()
        # A generation we wrote is a generation we have seen.
        if generation > link.last_seen_generation:
            link.last_seen_generation = int(generation)
            link.last_seen_at = link.last_pushed_at
        if sha256:
            link.base_sha256 = str(sha256)
            link.base_generation = int(generation)
        if sent_pending is not None and link.pending == sent_pending:
            link.pending = None
        self.put_link(link)

    def record_install_base(
        self, user_id: int, sync_id: str, sha256: str, generation: int
    ) -> None:
        """This profile's contents were installed from a folder generation.

        If the profile is already linked to that folder segment its base is
        set now (``keep_remote`` replaces a linked profile in place).
        Otherwise it is parked until :meth:`link_or_create` picks it up --
        installing from a folder and linking to it are separate acts, and the
        second may come days later.
        """
        link = self.get_link(user_id)
        if link is not None and link.sync_id == sync_id:
            link.base_sha256 = str(sha256)
            link.base_generation = int(generation)
            self.put_link(link)
            return
        self._data.setdefault("install_bases", {})[str(int(user_id))] = {
            "sync_id": str(sync_id),
            "sha256": str(sha256),
            "generation": int(generation),
        }
        self._save()

    def record_resolution(
        self,
        user_id: int,
        pending: Dict[str, Any],
        *,
        base_sha256: Optional[str] = None,
        base_generation: Optional[int] = None,
    ) -> None:
        """Remember a choice that has not been sent yet (#148).

        ``base_*`` is given only when the choice changed what the local copy
        descends from -- ``keep_remote``, which replaced it with the other
        side.
        """
        link = self.get_link(user_id)
        if link is None:
            return
        link.pending = _pending_or_none(pending)
        if base_sha256:
            link.base_sha256 = str(base_sha256)
            link.base_generation = int(base_generation or NO_PARENT)
        self.put_link(link)

    def clear_pending(self, user_id: int) -> None:
        link = self.get_link(user_id)
        if link is None or link.pending is None:
            return
        link.pending = None
        self.put_link(link)

    def record_seen(self, user_id: int, generation: int) -> None:
        """
        Record the highest generation observed in the folder, and when.

        Called even when nothing was pulled — "we looked, and this is what was
        there" is exactly the claim the UI is allowed to make.
        """
        link = self.get_link(user_id)
        if link is None:
            return
        link.last_seen_generation = max(int(generation), link.last_seen_generation)
        link.last_seen_at = utc_now_iso()
        self.put_link(link)
