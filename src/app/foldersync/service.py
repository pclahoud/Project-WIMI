"""
Wiring: the folder transport, the existing archive engine, and device-local state.

This is the only module here that knows what a database is. It deliberately
**reuses rather than reinvents** — every hard part is already built and measured:

*   ``build_profile_archive()`` snapshots via ``sqlite3.Connection.backup``, is
    WAL-safe, works while the profile is open, and computes its stats **from the
    snapshot**, so they describe exactly the bytes shipped. 54 ms -> 0.28 MB on a
    2,575-subject profile.
*   ``preflight_schema()`` already answers cross-device schema skew with
    ``ok`` / ``will_upgrade`` / ``newer_app_required`` and a user-facing reason.
    **That problem is solved; this module surfaces the verdict and does not
    redesign it.**
*   ``install_profile_as_new()`` forks on a name collision rather than
    overwriting, and ``replace_profile()`` exists for the other choice.

What this module adds is only: where the archive goes, which generation it is,
and what to believe when two of them disagree.

**Installation is deliberately left to the caller.** :meth:`ProfileFolderSync.fetch`
stages a verified archive and reports the schema verdict; choosing between
"install as new" and "replace" is the fork-resolution decision, which is #124.

Threading
---------
Every operation here comes in three phases, and **which thread runs which is
part of the contract**, not an implementation detail:

===============  ==========================  ==============================
phase            thread                      may touch
===============  ==========================  ==============================
``prepare_*``    caller's (Qt main)          ``master_db``, local disk
``perform_*``    worker                      the sync folder, and nothing else
``finish_*``     caller's (Qt main)          ``master_db``, ``state.json``
===============  ==========================  ==============================

The folder half has to leave the UI thread because a read of it can block for
as long as the hydration timeout allows -- on Box that is the normal case, not
an edge case, since our files are written once and never modified and Box
evicts on exactly that condition. The database half has to **stay** on it:
``base_db.py`` records that nothing in the application writes from a second
thread and tracks transaction re-entrancy with a per-connection counter, so
driving ``master_db`` from a worker would corrupt that depth silently.

``push()``, ``status()`` and ``fetch()`` compose all three and are correct for
tests and any single-threaded caller. A GUI caller goes through
``app.foldersync.jobs.SyncJobs``, which runs phase 2 on a worker and phases 1
and 3 on the calling thread. ``tests/app/test_foldersync_threading.py`` holds
the middle row by handing the worker a ``master_db`` that raises on any
attribute access -- verified to fail when violated, not merely to pass.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.profile_archive import (
    VERDICT_NEWER_APP_REQUIRED,
    _app_version,
    _profile_stats,
    _read_profile_uuid,
    build_profile_archive,
    preflight_schema,
    read_profile_archive,
)

from .hydration import DEFAULT_TIMEOUT_S, hydration_advice
from .manifest import NO_PARENT, SyncManifest, describe_for_user, utc_now_iso
from .forks import ForkReport, SideSummary, build_fork_report, figures_that_differ, summarise_side
from .naming import ROOT_DIR_NAME
from .providers import get_provider
from .state import DeviceIdentity, SyncLink, SyncState
from .transport import (
    HeadGeneration,
    FolderTransport,
    Fork,
    Lineage,
    PushResult,
    TransportError,
    VerificationFailure,
)

STAGING_DIR_NAME = "staging"


class FolderMovedSinceResolution(TransportError):
    """A send was refused: the folder changed after the student chose (#148).

    A resolution names the heads the student saw and chose against. A head
    that appeared afterwards is work nobody has looked at, and sending would
    either leave it standing (the fork comes straight back) or -- worse, if
    the resolution were recomputed at send time -- retire it unseen. Neither
    is acceptable, so nothing is sent and the student looks again.
    """

    def __init__(self, unseen: List[SyncManifest]):
        self.unseen = list(unseen)
        described = ", ".join(
            f"{m.device_name} generation {m.generation}" for m in self.unseen
        )
        super().__init__(
            "The sync folder has changed since you chose which copy to keep "
            f"({described} appeared). Nothing was sent. Look at the copies "
            "again and choose."
        )


@dataclass
class FetchResult:
    """A verified archive, staged outside the sync folder, with its verdict."""
    archive_path: str
    generation: int
    manifest: SyncManifest
    schema_verdict: str
    schema_reason: str
    blocked: bool
    summary: Dict[str, Any]
    skipped: List[VerificationFailure] = field(default_factory=list)


@dataclass
class SyncStatus:
    """
    What the panel is allowed to say.

    **You cannot force a sync or know when one finished.** "Nothing new" and "the
    other device has not uploaded yet" are indistinguishable from the filesystem,
    so every field here is an observation with a timestamp, and there is
    deliberately no ``synced: bool``.
    """
    linked: bool
    folder: Optional[str] = None
    provider_id: str = "generic"
    provider_name: str = "Local folder"
    sync_id: Optional[str] = None
    device_name: Optional[str] = None
    last_seen_generation: int = NO_PARENT
    last_seen_at: Optional[str] = None
    last_pushed_generation: int = NO_PARENT
    last_pushed_at: Optional[str] = None
    head_generation: Optional[int] = None
    head_device: Optional[str] = None
    head_created_at: Optional[str] = None
    #: False when the head's blob is present but its bytes are not stored on
    #: this device, so nobody has checked its digest. Looking is free;
    #: checking costs a download (#147). Not a warning -- the normal state
    #: for a generation another machine has just published.
    head_verified: bool = True
    #: Where this device's copy stands against the folder (#148). See
    #: ``Lineage.relation_of``: unknown / missing / current / behind /
    #: superseded. ``superseded`` is the losing side of a resolution made on
    #: another device, and the panel must say so.
    base_generation: int = NO_PARENT
    base_relation: str = "unknown"
    relation_detail: Optional[Dict[str, Any]] = None
    #: A choice made here and not yet sent. The owner's decision on #148:
    #: nothing reaches the folder until the student sends, so this must be
    #: shown as a standing state, not a toast that scrolls away.
    pending: Optional[Dict[str, Any]] = None
    #: ``ready`` -- nothing new in the folder since the choice; sending will
    #: settle it. ``folder_moved`` -- another device published since, and a
    #: send would be refused.
    pending_state: Optional[str] = None
    #: Has this computer changed since the copy it last sent or took (#151)?
    #: ``{checked, reason, differs: [{field, label, here, then}]}``. Only
    #: what was CHECKED: an edit to an existing entry moves none of these
    #: figures, so "no difference" is not "nothing unsent".
    local_changes: Dict[str, Any] = field(default_factory=dict)
    forks: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    conflict_copies: List[Dict[str, Any]] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    pin_hint: Optional[str] = None


@dataclass
class PushPlan:
    """
    Everything ``perform_push`` needs, gathered before the thread boundary.

    The archive is already built and sitting in staging: nothing here touches
    a database, so the push itself is pure folder I/O.
    """
    user_id: int
    link: SyncLink
    identity: DeviceIdentity
    staged_dir: Path
    archive_path: Path
    schema_version: int
    row_counts: Dict[str, Any]
    stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusInputs:
    """The database half of a status call, read before the thread boundary."""
    link: Optional[SyncLink]
    identity: Optional[DeviceIdentity] = None


class ProfileFolderSync:
    """
    Push and fetch whole-profile generations through a user-picked folder.

    Holds no live database connection: it goes through ``MasterDatabase`` the
    same way the export path already does, so it works regardless of which
    profile is currently open.
    """

    def __init__(self, master_db, app_data_dir: Optional[str | Path] = None, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.master_db = master_db
        # MasterDatabase.data_dir already carries the frozen-vs-dev answer from
        # main.get_application_paths(); resolving it a second time here would be
        # a second source of truth.
        self.app_data_dir = Path(app_data_dir or getattr(master_db, "data_dir", ".") )
        self.state = SyncState(self.app_data_dir)
        self.timeout_s = float(timeout_s)

    # ------------------------------------------------------------------ helpers

    @property
    def staging_dir(self) -> Path:
        """
        Where archives are built and staged — **never inside the sync folder**.

        Box documents that a file repeatedly written inside the synced folder
        produces conflict copies, and recommends working outside it. Building
        here and copying a finished file in is exactly that recommendation.
        """
        path = self.app_data_dir / "foldersync" / STAGING_DIR_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _device_identity(self) -> DeviceIdentity:
        """
        This machine, as the master database already knows it.

        Read, never minted. ``device_settings`` is keyed on
        ``MasterDatabase.get_device_id()``, so a second id minted here would
        mean one machine wearing two identities -- the exact failure
        ``device_local.py`` is a single definition to prevent. The name is
        cosmetic and only ever reaches a filename via ``DeviceIdentity.slug``.
        """
        return DeviceIdentity(
            device_id=self.master_db.get_device_id(),
            device_name=self.master_db.get_device_name(),
        )

    def _profile_uuid(self, user_id: int) -> str:
        """
        The profile's own identifier, which is what names its folder segment.

        Minting one here is the thing this must never do: the same profile
        would get a different identity on each machine and silently split
        into two histories, which is #129's failure in full.

        ``users.profile_uuid`` is a **mirror**, re-derived at every open,
        install and replace; the authority is ``profile_identity`` inside the
        user database. So read the mirror, and when it is empty fall back to
        the authority and heal the mirror rather than refusing -- a profile
        created but never yet opened through the app has a NULL mirror and a
        perfectly good uuid.
        """
        user = self.master_db.get_user(user_id=user_id)
        if user is None:
            raise TransportError(f"no such profile: {user_id}")
        if user.profile_uuid:
            return str(user.profile_uuid)

        db_path = self.master_db.ensure_user_database(user_id)
        found = _read_profile_uuid(Path(db_path))
        if not found:
            raise TransportError(
                "this profile has no stable identifier, so it cannot be "
                "linked to a sync folder. Open it once so one is recorded."
            )
        self.master_db.record_profile_uuid(user_id, found)
        return str(found)

    def _transport(self, link: SyncLink) -> FolderTransport:
        return FolderTransport(link.folder, link.sync_id, link.provider_id, timeout_s=self.timeout_s)

    @staticmethod
    def _base_of(link: SyncLink, device_id: Optional[str], graph: Lineage) -> Optional[str]:
        """What this device's copy descends from, as a digest (#149).

        The recorded base, and nothing else. ``last_seen_generation`` is
        never consulted: having looked at a generation is not having it, and
        treating the two as the same is #149.

        **No inference for a link that recorded none.** An earlier version
        guessed the base of a pre-#148 link from the generation this device
        last pushed. That assumes nothing replaced the local copy since, and
        a pre-#148 ``keep_remote`` did exactly that without recording it --
        found on hardware, where the guess named the device's own generation
        while it held the other device's rows. A push built on that guess
        claims a descent that is not true, which is #149's class of error.

        ``None`` means "descends from nothing this device can vouch for" and
        makes the next push a root. For a legacy link that can be a false "no
        shared history" -- wrong in the safe direction: the student is shown
        two copies and asked, rather than told something untrue.

        ``device_id`` and ``graph`` stay in the signature so a caller never
        has to know which facts the answer currently rests on.
        """
        return link.base_sha256 or None

    @staticmethod
    def _pending_state(link: SyncLink, graph: Lineage) -> Tuple[Optional[str], List[SyncManifest]]:
        """Has the folder moved since the student chose? ``(state, unseen heads)``."""
        if not link.pending:
            return None, []
        saw = set(link.pending.get("saw_heads") or [])
        unseen = [h for h in graph.heads if h.sha256 not in saw]
        return ("folder_moved" if unseen else "ready"), unseen

    @staticmethod
    def _divergences(
        transport: FolderTransport, scan, graph: Lineage, base: Optional[str]
    ) -> List[Fork]:
        """Every divergence this device should be shown.

        The folder's own forks, and -- when there are none -- this device's
        copy having been set aside by a resolution elsewhere. The second is
        not visible in the folder as a fork (it has one head), but from here
        it is exactly one: this device holds a copy nobody else is building on.
        """
        forks = transport.detect_forks(scan)
        if forks:
            return forks
        relation, by = graph.relation_of(base)
        if relation == "superseded" and base in graph.by_sha and graph.heads:
            mine = graph.by_sha[base]
            other = by if by is not None and by.sha256 in {h.sha256 for h in graph.heads} else graph.heads[0]
            common = graph.common_ancestors([mine.sha256, other.sha256])
            point = max(common, key=lambda m: (m.generation, m.blob_name)) if common else None
            return [Fork(
                parent_generation=point.generation if point else NO_PARENT,
                sides=[mine, other],
                first_connect=point is None,
                set_aside=True,
            )]
        return []

    @staticmethod
    def _local_side(sides: List[SyncManifest], base: Optional[str], device_id: Optional[str]) -> Optional[str]:
        """Which side this device HOLDS, as a blob name -- or ``None``.

        By base digest only. "Local" means the copy this computer has, and
        only the base says that. Who *published* a side is a different fact:
        a device that published generation 2 and then took the other side
        with ``keep_remote`` holds the other side's rows, and labelling its
        own generation "this computer's copy" would invite the student to
        keep something they no longer have. That was the device-id fallback
        here, and it was wrong every time it fired: with a known base it only
        fired when the base was not a side, i.e. when something had replaced
        the content since.

        ``None`` is a real answer -- neither side is known to be this
        computer's -- and the panel refuses to guess rather than pick one.
        """
        if base:
            for m in sides:
                if m.sha256 == base:
                    return m.blob_name
        return None

    # ------------------------------------------------------------------ discovery

    def discover(self, folder: str | Path, provider_id: str = "generic") -> List[Dict[str, Any]]:
        """
        What profiles already live in this folder, and which of them are ours.

        Single-threaded wrapper over ``scan_folder`` + ``annotate_discovery``;
        see *Threading* above.
        """
        return self.annotate_discovery(self.scan_folder(folder, provider_id))

    def scan_folder(
        self, folder: str | Path, provider_id: str = "generic"
    ) -> List[Dict[str, Any]]:
        """
        Phase 2, **worker thread**: enumerate the folder and resolve each head.

        Each directory under ``WIMI/`` is named by a profile uuid. Nothing here
        knows what profiles this machine holds -- that is the next phase,
        because answering it is a database read.
        """
        root = Path(folder) / ROOT_DIR_NAME
        if not root.is_dir():
            return []
        found: List[Dict[str, Any]] = []
        for child in sorted(p for p in root.iterdir() if p.is_dir()):
            transport = FolderTransport(folder, child.name, provider_id, timeout_s=self.timeout_s)
            try:
                # #147 applies here too, and this is the worse case: one
                # download PER PROFILE in the folder, just to answer "what is
                # already in here" while the student is still choosing it.
                # Everything shown comes from the manifest.
                head, failures = transport.resolve_head(allow_hydration=False)
            except TransportError:
                continue
            found.append({
                "sync_id": child.name,
                "head": describe_for_user(head.manifest) if head else None,
                "rejected": [{"generation": f.generation, "reason": f.reason} for f in failures],
            })
        return found

    def annotate_discovery(self, found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Phase 3, **caller's thread**: say which of those profiles this machine has.

        This answers a question the spike could not: **is this folder already
        holding a profile I have?** #129 recorded that no such check existed
        anywhere, and that linking was therefore "a manual act of faith".

        ``local_profiles`` is a list, not an id, because more than one match is
        legitimate rather than a corruption -- ``install_profile_as_new()``
        forks on a name collision by design, and "keep both" is one of the
        options at first connect. Choosing between copies is #124's job.
        """
        for entry in found:
            try:
                local = self.master_db.find_users_by_profile_uuid(entry["sync_id"])
            except Exception:
                # A folder segment that is not a uuid we know is simply not
                # ours. Discovery must survive whatever else is in there.
                local = []
            entry["local_profiles"] = [
                {"user_id": u.id, "username": u.username} for u in local
            ]
        return found

    # ------------------------------------------------------------------ linking

    def link(
        self,
        user_id: int,
        folder: str | Path,
        provider_id: str = "generic",
    ) -> SyncLink:
        """
        Point a profile at a folder.

        There is **no identity to negotiate**. The folder segment is
        ``WIMI/<profile-uuid>/``, derived from the profile itself (#129), so a
        second device linking the same profile computes the same path and
        lands in the same place without adopting anything from the folder --
        and two different profiles sharing one folder get separate segments
        rather than colliding.

        The spike this grew from had to negotiate, because a profile had no
        cross-machine identifier: it minted a sync id, wrote it into the
        manifest, and had the second device adopt whatever it found. That also
        meant a folder holding two profiles could not be linked
        unambiguously, and a mis-link was undetectable. Both are gone.

        Single-threaded wrapper; see *Threading* above.
        """
        plan = self.prepare_link(user_id, folder, provider_id)
        problems = self.check_folder(plan)
        return self.finish_link(plan, problems)

    def prepare_link(
        self, user_id: int, folder: str | Path, provider_id: str = "generic"
    ) -> Dict[str, Any]:
        """Phase 1, **caller's thread**: resolve which segment this profile owns."""
        return {
            "user_id": int(user_id),
            "folder": str(Path(folder)),
            "provider_id": str(provider_id),
            "sync_id": self._profile_uuid(user_id),
        }

    def check_folder(self, plan: Dict[str, Any]) -> List[str]:
        """
        Phase 2, **worker thread**: is this folder usable at all?

        A ``stat`` and a write probe, which on a cloud filesystem can block or
        fail while the client is offline or mid-reset -- so it belongs off the
        UI thread like every other touch of the folder.
        """
        return FolderTransport(
            plan["folder"], plan["sync_id"], plan["provider_id"], self.timeout_s
        ).preflight()

    def finish_link(self, plan: Dict[str, Any], problems: List[str]) -> SyncLink:
        """Phase 3, **caller's thread**: record the link, or refuse with the reason."""
        blocking = [
            p for p in problems
            if "does not exist" in p or "cannot write" in p or "is a file" in p
        ]
        if blocking:
            raise TransportError("; ".join(blocking))
        return self.state.link_or_create(
            plan["user_id"], plan["sync_id"], plan["folder"], plan["provider_id"]
        )

    def unlink(self, user_id: int) -> None:
        """Forget the link. Nothing in the folder is touched — the archives are the user's."""
        self.state.drop_link(user_id)

    # ------------------------------------------------------------------ push

    def push(self, user_id: int) -> PushResult:
        """
        Seal the current state of a profile and publish it as the next generation.

        Database only (``include_media=False``): media is content-addressed by
        construction and ships separately, which is #125.

        Single-threaded convenience wrapper. A GUI caller must not use this --
        see the *Threading* note at the top of this module and go through
        ``prepare_push`` / ``perform_push`` / ``finish_push`` instead.
        """
        plan = self.prepare_push(user_id)
        try:
            result = self.perform_push(plan)
        except BaseException:
            self.discard_push(plan)
            raise
        return self.finish_push(plan, result)

    def prepare_push(self, user_id: int) -> PushPlan:
        """
        Phase 1, **caller's thread**: read the database and seal the archive.

        Everything that touches ``master_db`` happens here.
        ``build_profile_archive`` is local disk and was measured at 54-66 ms on
        a 2,575-subject profile, so it is not what needs moving off the UI
        thread -- the cloud folder is.
        """
        link = self.state.get_link(user_id)
        if link is None:
            raise TransportError("this profile is not linked to a sync folder")

        identity = self._device_identity()
        staged = Path(tempfile.mkdtemp(prefix="push-", dir=str(self.staging_dir)))
        try:
            archive_path = staged / "profile.wimi"
            built = build_profile_archive(
                self.master_db, user_id, archive_path, include_media=False,
                # Every generation must have its own digest: lineage names
                # generations by SHA-256 (#148), and an unchanged profile
                # built twice inside one second is otherwise byte-identical.
                sync={"nonce": uuid.uuid4().hex},
            )
        except BaseException:
            shutil.rmtree(str(staged), ignore_errors=True)
            raise

        inner = built["manifest"]
        stats = dict(inner.get("stats") or {})
        # row_counts is counts, and is coerced to int on parse. The snapshot's
        # stats now also carry date ranges (#124), so split rather than widen:
        # a date string in row_counts raises at parse time.
        counts = {k: v for k, v in stats.items() if isinstance(v, int)}
        return PushPlan(
            user_id=user_id,
            link=link,
            identity=identity,
            staged_dir=staged,
            archive_path=archive_path,
            schema_version=int(inner.get("db", {}).get("schema_max_version") or 0),
            row_counts=counts,
            stats=stats,
        )

    def perform_push(self, plan: PushPlan) -> PushResult:
        """
        Phase 2, **worker thread**: the folder I/O, and nothing else.

        Touches no database connection. That is the property the thread split
        rests on, and ``test_foldersync_threading.py`` asserts it by handing
        this phase a ``master_db`` that raises on any attribute access.
        """
        transport = self._transport(plan.link)
        transport.ensure_dir()

        scan = transport.scan()
        graph = transport.lineage(scan)
        # The parent is what this device's copy DESCENDS FROM -- its base --
        # and never the folder head (#149). Reading the head meant a device
        # that had not fetched published its content as a child of work it
        # never had: no fork was reported, and the other device's newer
        # generation silently stopped being the head. Parenting to the base
        # makes that push a second child instead, which is a reported fork.
        #
        # Nothing here is verified or downloaded: generations are snapshots,
        # not deltas, so a parent records lineage and nothing is built out of
        # its bytes (#147).
        pending = plan.link.pending
        if pending:
            state, unseen = self._pending_state(plan.link, graph)
            if state == "folder_moved":
                raise FolderMovedSinceResolution(unseen)
            parents = list(pending["parents"])
            supersedes = list(pending["supersedes"])
        else:
            base = self._base_of(plan.link, plan.identity.device_id, graph)
            parents = [base] if base else []
            supersedes = []

        return transport.push(
            blob_source=plan.archive_path,
            device_id=plan.identity.device_id,
            device_name=plan.identity.device_name,
            schema_version=plan.schema_version,
            row_counts=plan.row_counts,
            stats=plan.stats,
            app_version=_app_version(),
            parents=parents,
            supersedes=supersedes,
            scan=scan,
            # Never reuse a number we have already published, even if the
            # cloud client has not brought our own earlier files back down.
            generation_floor=max(
                plan.link.last_pushed_generation, plan.link.last_seen_generation
            ),
        )

    def finish_push(self, plan: PushPlan, result: PushResult) -> PushResult:
        """Phase 3, **caller's thread**: record what was published, drop staging.

        What was published is now this device's base. A pending resolution
        the push carried is settled, so it is cleared -- and only then, never
        on the choosing (#148).
        """
        self.discard_push(plan)
        self.state.record_push(
            plan.user_id, result.generation, result.sha256,
            sent_pending=plan.link.pending,
        )
        return result

    def discard_push(self, plan: PushPlan) -> None:
        """Remove a plan's staging directory. Safe to call twice."""
        shutil.rmtree(str(plan.staged_dir), ignore_errors=True)

    # ------------------------------------------------------------------ fetch

    def fetch(self, user_id: int) -> FetchResult:
        """Fetch the highest verified generation for a linked profile."""
        link = self.state.get_link(user_id)
        if link is None:
            raise TransportError("this profile is not linked to a sync folder")
        result = self.fetch_from(link.folder, link.sync_id, link.provider_id)
        self.state.record_seen(user_id, result.generation)
        return result

    def fetch_from(
        self, folder: str | Path, sync_id: str, provider_id: str = "generic"
    ) -> FetchResult:
        """
        Fetch from a folder this machine has no link to yet — the second device's first pull.

        Staged, verified, schema-checked. Nothing is installed: that decision is
        the caller's, and where a fork is involved it is #124's.
        """
        transport = FolderTransport(folder, sync_id, provider_id, timeout_s=self.timeout_s)
        head, failures = transport.resolve_head()
        if head is None:
            provider = get_provider(provider_id)
            detail = f" ({failures[0].reason})" if failures else ""
            hint = ""
            if provider.streaming_by_default and failures:
                hint = "\n" + hydration_advice(provider.pin_setting_label, str(transport.sync_dir))
            raise TransportError(
                f"no usable generation in {transport.sync_dir}{detail}{hint}"
            )

        staged = self.staging_dir / f"fetch-gen-{head.manifest.generation:04d}.wimi"
        pull = transport.pull(staged, head=head)

        # The blob verified byte-for-byte; now confirm it is actually an archive
        # we understand, and get the schema verdict before anyone is offered a
        # button that installs it.
        inventory = read_profile_archive(pull.dest_path)
        verdict, reason = self._schema_verdict(pull.dest_path)

        summary = describe_for_user(pull.manifest)
        summary["archive_user"] = inventory["manifest"].get("user", {})
        summary["archive_stats"] = inventory["manifest"].get("stats", {})

        return FetchResult(
            archive_path=pull.dest_path,
            generation=pull.generation,
            manifest=pull.manifest,
            schema_verdict=verdict,
            schema_reason=reason,
            blocked=(verdict == VERDICT_NEWER_APP_REQUIRED),
            summary=summary,
            # The rejections come from OUR resolve_head above, not from pull():
            # pull() was handed an already-resolved head, so it did no rejecting
            # of its own and reports none. Dropping these on the floor would lose
            # exactly the thing the user is entitled to be told -- "generation 43
            # failed its checksum, so you are looking at 42".
            skipped=failures,
        )

    def _schema_verdict(self, archive_path: str) -> tuple[str, str]:
        """
        Run the EXISTING preflight against the staged archive's ``user.db``.

        A device on an older build pulling a newer profile must refuse with this
        message, not attempt anything clever.
        """
        import zipfile
        from app.profile_archive import DB_MEMBER

        work = Path(tempfile.mkdtemp(prefix="preflight-", dir=str(self.staging_dir)))
        try:
            with zipfile.ZipFile(archive_path) as zf:
                zf.extract(DB_MEMBER, str(work))
            report = preflight_schema(work / DB_MEMBER)
            return (str(report.get("verdict")), str(report.get("reason") or ""))
        finally:
            shutil.rmtree(str(work), ignore_errors=True)

    def install_from_folder(
        self, folder: str | Path, sync_id: str, provider_id: str = "generic"
    ) -> Dict[str, Any]:
        """A computer's first copy of a profile, from the folder (#151).

        Installed, its base recorded, and linked to the folder it came from.
        Single-threaded wrapper over the three phases below; a GUI caller
        goes through ``SyncJobs.submit_install``.
        """
        plan = self.prepare_install(folder, sync_id, provider_id)
        return self.finish_install(plan, self.perform_install(plan))

    def prepare_install(
        self, folder: str | Path, sync_id: str, provider_id: str = "generic"
    ) -> Dict[str, Any]:
        """Phase 1, **caller's thread**: refuse a profile this computer already has.

        A second copy sharing a profile uuid must never be linked -- the two
        would publish into one folder segment and fork against each other
        forever (#124's keep-both rule). So the picker does not install a
        profile that is already here; catching it up is the other path.
        """
        self._refuse_if_installed(sync_id)
        return {"folder": str(Path(folder)), "sync_id": str(sync_id),
                "provider_id": str(provider_id)}

    def perform_install(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 2, **worker thread**: fetch and verify, and probe the folder for the link."""
        fetched = self.fetch_from(plan["folder"], plan["sync_id"], plan["provider_id"])
        problems = FolderTransport(
            plan["folder"], plan["sync_id"], plan["provider_id"], self.timeout_s
        ).preflight()
        return {"fetched": fetched, "problems": problems}

    def finish_install(self, plan: Dict[str, Any], performed: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 3, **caller's thread**: install, record the base, link.

        The base is recorded **before** the link, and the link picks it up:
        installing and linking are one act here, but they are separate acts
        everywhere else, and the parked base is what keeps the second from
        forgetting the first (#149).

        A link that fails leaves the profile installed and says so, rather
        than undoing an install the student can use -- they can link it from
        Settings. An install that fails leaves nothing behind.
        """
        from app.profile_archive import install_profile_as_new

        fetched: FetchResult = performed["fetched"]
        try:
            if fetched.blocked:
                raise TransportError(
                    fetched.schema_reason or "this copy needs a newer version of WIMI")
            # Again, on this thread: another install may have landed while
            # the worker was fetching.
            self._refuse_if_installed(plan["sync_id"])
            installed = install_profile_as_new(self.master_db, fetched.archive_path)
        finally:
            try:
                Path(fetched.archive_path).unlink()
            except OSError:
                pass

        user_id = int(installed["user_id"])
        self.record_install(user_id, plan["sync_id"], fetched.manifest)

        link_error: Optional[str] = None
        if installed.get("profile_uuid") != plan["sync_id"]:
            # The folder segment is named by a profile uuid; an archive
            # holding a different one is not this segment's profile, and
            # linking it here would publish it into someone else's history.
            link_error = (
                "the copy in this folder carries a different profile id than "
                "the folder it sits in, so it was installed but not linked")
        else:
            try:
                self.finish_link(
                    {"user_id": user_id, "folder": plan["folder"],
                     "provider_id": plan["provider_id"], "sync_id": plan["sync_id"]},
                    performed.get("problems") or [])
            except TransportError as exc:
                link_error = str(exc)
        return {
            "installed": installed,
            "fetched": fetched,
            "linked": link_error is None,
            "link_error": link_error,
            "folder": plan["folder"],
        }

    def _refuse_if_installed(self, sync_id: str) -> None:
        existing = self.master_db.find_users_by_profile_uuid(sync_id)
        if existing:
            raise TransportError(
                f"This profile is already on this computer as "
                f"{existing[0].username!r}. Open it and take the newer copy from "
                f"Settings, rather than installing a second copy.")

    # ------------------------------------------------------------------ local changes

    def local_changes(
        self, user_id: int, base_manifest: Optional[SyncManifest], relation: str = "unknown"
    ) -> Dict[str, Any]:
        """Has this computer changed since the copy it last sent or took? (#151)

        Compares the live profile's figures with the base's manifest -- the
        same figures, and the same comparison, the fork report uses. Reads
        the database file directly with a plain connection, which is safe
        beside the app's own (WAL) and touches nothing it writes.

        **Only what was checked.** An edit to an existing entry changes none
        of these figures, so an empty ``differs`` means "no difference found",
        never "nothing unsent". The panel says so.
        """
        if base_manifest is None:
            reason = {
                "missing": "the copy this computer last synced is not in the folder",
            }.get(relation, "this computer has no copy recorded as last sent or taken")
            return {"checked": False, "reason": reason, "differs": []}
        try:
            db_path = Path(self.master_db.ensure_user_database(user_id))
            conn = sqlite3.connect(str(db_path))
            try:
                here = _profile_stats(conn)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - reported, never fatal to a status call
            return {"checked": False, "reason": f"could not read this profile: {exc}",
                    "differs": []}

        then = summarise_side(base_manifest)
        now = SideSummary(
            generation=0, parent_generation=0, device_id="", device_name="",
            created_at="", bytes=0,
            entries=here.get("entries"), sessions=here.get("sessions"),
            exam_contexts=here.get("exam_contexts"), subjects=here.get("subjects"),
            encountered_first=here.get("encountered_first"),
            encountered_last=here.get("encountered_last"),
            logged_first=here.get("logged_first"), logged_last=here.get("logged_last"),
        )
        return {
            "checked": True,
            "reason": None,
            "base_generation": base_manifest.generation,
            "differs": [
                {"field": d["field"], "label": d["label"], "here": d["a"], "then": d["b"]}
                for d in figures_that_differ(now, then)
            ],
        }

    def record_install(self, user_id: int, sync_id: str, manifest: SyncManifest) -> None:
        """A profile's contents now come from this folder generation.

        Call after installing a fetched archive as a profile. Without it the
        installed profile's first push would claim no ancestor, and both
        devices would be told their copies share no history.
        """
        self.state.record_install_base(
            user_id, sync_id, manifest.sha256, manifest.generation)

    # ------------------------------------------------------------------ status

    def status(self, user_id: int) -> SyncStatus:
        """
        An honest description of what we can actually observe. Never a green tick.

        Every claim carries a timestamp, because the only truthful statement
        available is "this is what was in the folder when we last looked".

        Single-threaded convenience wrapper -- see *Threading* at the top of
        this module. A GUI caller uses the three phases below.
        """
        inputs = self.prepare_status(user_id)
        if inputs.link is None:
            return SyncStatus(linked=False)
        observed = self.observe_folder(
            inputs.link, inputs.identity.device_id if inputs.identity else None)
        return self.finish_status(user_id, inputs, observed)

    def prepare_status(self, user_id: int) -> StatusInputs:
        """Phase 1, **caller's thread**: the link, and who this machine is."""
        link = self.state.get_link(user_id)
        if link is None:
            return StatusInputs(link=None)
        return StatusInputs(link=link, identity=self._device_identity())

    def observe_folder(self, link: SyncLink, device_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Phase 2, **worker thread**: look at the folder. No database, no state file.

        This is the call that can block for as long as the hydration timeout
        allows, because a manifest or a blob may have been evicted -- and on
        Box eviction is scheduled rather than exceptional, since our files are
        written once and never modified, which starts the 30-day clock
        immediately (#123 comment #1503).
        """
        transport = self._transport(link)
        try:
            scan = transport.scan()
        except TransportError as exc:
            return {"unavailable": str(exc)}

        # The display path must not download the archive to render a
        # generation number (#147). Measured on Box: 1,474 ms hydrating
        # against 49.7 ms local, and it pulls the whole blob. A head whose
        # bytes are not local comes back verified=False instead.
        head, failures = transport.resolve_head(scan, allow_hydration=False)
        # Lineage is manifest-only, so it is as free as the head (#147).
        graph = transport.lineage(scan)
        base = self._base_of(link, device_id, graph)
        relation, related = graph.relation_of(base)
        pending_state, unseen = self._pending_state(link, graph)
        forks = self._divergences(transport, scan, graph, base)
        return {
            "head": head,
            "failures": failures,
            "forks": forks,
            "local_sides": [self._local_side(f.sides, base, device_id) for f in forks],
            "base": base,
            "base_manifest": graph.by_sha.get(base) if base else None,
            "relation": relation,
            "related": related,
            "pending_state": pending_state,
            "unseen": unseen,
            "conflict_copies": transport.recoverable_conflict_copies(scan),
            "unsyncable": list(scan.unsyncable),
        }

    def finish_status(
        self, user_id: int, inputs: StatusInputs, observed: Dict[str, Any]
    ) -> SyncStatus:
        """Phase 3, **caller's thread**: assemble the report, record what was seen."""
        link = inputs.link
        if link is None:
            return SyncStatus(linked=False)

        provider = get_provider(link.provider_id)
        status = SyncStatus(
            linked=True,
            folder=link.folder,
            provider_id=link.provider_id,
            provider_name=provider.display_name,
            sync_id=link.sync_id,
            device_name=inputs.identity.device_name if inputs.identity else None,
            last_seen_generation=link.last_seen_generation,
            last_seen_at=link.last_seen_at,
            last_pushed_generation=link.last_pushed_generation,
            last_pushed_at=link.last_pushed_at,
            pin_hint=provider.pin_setting_label,
        )

        if observed.get("unavailable"):
            status.problems.append(str(observed["unavailable"]))
            return status

        head = observed.get("head")
        if head is not None:
            status.head_generation = head.manifest.generation
            status.head_device = head.manifest.device_name
            status.head_created_at = head.manifest.created_at
            status.head_verified = bool(getattr(head, "verified", True))
            self.state.record_seen(user_id, head.manifest.generation)
            status.last_seen_generation = max(
                status.last_seen_generation, head.manifest.generation
            )

        status.rejected = [
            {"generation": f.generation, "manifest": f.manifest_name, "reason": f.reason}
            for f in observed.get("failures", [])
        ]
        base_manifest = observed.get("base_manifest")
        status.base_generation = (
            base_manifest.generation if base_manifest is not None
            else link.base_generation)
        status.base_relation = str(observed.get("relation") or "unknown")
        related = observed.get("related")
        if related is not None:
            status.relation_detail = describe_for_user(related)

        status.local_changes = self.local_changes(
            user_id, base_manifest, status.base_relation)

        status.pending = dict(link.pending) if link.pending else None
        status.pending_state = observed.get("pending_state")
        if status.pending_state == "folder_moved":
            status.pending = dict(status.pending or {})
            status.pending["unseen"] = [
                describe_for_user(m) for m in observed.get("unseen", [])]

        local_sides = observed.get("local_sides") or []
        status.forks = []
        for i, fork in enumerate(observed.get("forks", [])):
            local = local_sides[i] if i < len(local_sides) else None
            sides = []
            for m in fork.sides:
                described = describe_for_user(m)
                described["is_local"] = bool(local) and m.blob_name == local
                sides.append(described)
            status.forks.append({
                "parent_generation": fork.parent_generation,
                "first_connect": fork.first_connect,
                "set_aside": fork.set_aside,
                # Chosen here, not yet sent, and nothing new has appeared
                # since. The folder still shows the fork -- it will until the
                # send -- but this device must not ask the question twice.
                "resolved_here": status.pending_state == "ready",
                "sides": sides,
            })
        status.conflict_copies = list(observed.get("conflict_copies", []))
        for name, reason in observed.get("unsyncable", []):
            status.problems.append(f"{name}: {reason}")
        return status

    # ------------------------------------------------------------------ fork report

    def prepare_fork_report(self, user_id: int) -> StatusInputs:
        """Phase 1, **caller's thread**: which folder, and who we are."""
        return self.prepare_status(user_id)

    def collect_fork_sides(
        self,
        link: SyncLink,
        parent_generation: Optional[int] = None,
        device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Phase 2, **worker thread**: find a fork and stage both of its sides.

        This downloads both blobs on a streaming provider, and that is the
        right cost here. #147 took the opposite decision for *status*
        because looking happens constantly; choosing between two copies is a
        deliberate act, and there is no honest answer without reading both.

        Each side is verified at the destination by ``pull``, so a blob that
        was fine in the folder and arrived damaged is caught before a
        student is asked to choose based on it.
        """
        transport = self._transport(link)
        try:
            scan = transport.scan()
        except TransportError as exc:
            return {"unavailable": str(exc)}

        graph = transport.lineage(scan)
        base = self._base_of(link, device_id, graph)
        forks = self._divergences(transport, scan, graph, base)
        if not forks:
            return {"fork": None}

        fork = forks[0]
        if parent_generation is not None:
            match = [f for f in forks if f.parent_generation == int(parent_generation)]
            if not match:
                return {"fork": None,
                        "note": f"no fork from generation {parent_generation}"}
            fork = match[0]

        staged: List[Tuple[Any, Optional[str]]] = []
        for manifest in fork.sides:
            # Named by BLOB NAME, not generation. The two sides of a fork
            # normally share a generation -- each device numbered its push
            # against a folder where the other's file had not yet appeared --
            # so a generation-named staging path has both sides overwrite
            # each other, and the report then compares one archive with
            # itself and truthfully finds no differences. Which is the worst
            # possible answer: a confident "these are the same".
            dest = self.staging_dir / f"fork-{Path(manifest.blob_name).stem}.wimi"
            try:
                ok, reason, blob_path = transport.verify(manifest)
                if not ok:
                    staged.append((manifest, None))
                    continue
                head = HeadGeneration(
                    manifest=manifest,
                    manifest_name=manifest.blob_name,
                    blob_path=str(blob_path),
                    blob_bytes=manifest.bytes,
                    verified=True,
                )
                pulled = transport.pull(dest, head=head)
                staged.append((manifest, pulled.dest_path))
            except TransportError:
                # One unreadable side must not lose the other: the report
                # says the comparison did not run rather than pretending
                # the two agree.
                staged.append((manifest, None))

        return {
            "fork": fork,
            "staged": staged,
            "local_side": self._local_side(fork.sides, base, device_id),
        }

    def finish_fork_report(self, observed: Dict[str, Any]) -> Optional[ForkReport]:
        """Phase 3, **caller's thread**: assemble the comparison.

        ``None`` means there is no fork, which is the ordinary case and not
        an error.
        """
        if observed.get("unavailable") or not observed.get("fork"):
            return None
        fork = observed["fork"]
        return build_fork_report(
            fork.parent_generation,
            observed["staged"],
            first_connect=fork.first_connect,
            set_aside=fork.set_aside,
            local_blob_name=observed.get("local_side"),
        )

    def fork_report(
        self, user_id: int, parent_generation: Optional[int] = None
    ) -> Optional[ForkReport]:
        """Single-threaded wrapper; see *Threading* above."""
        inputs = self.prepare_fork_report(user_id)
        if inputs.link is None:
            return None
        return self.finish_fork_report(self.collect_fork_sides(
            inputs.link, parent_generation,
            inputs.identity.device_id if inputs.identity else None))

    # ------------------------------------------------------------------ resolving

    def stage_other_side(self, link: SyncLink, blob_name: str) -> str:
        """
        Phase 2, **worker thread**: bring one specific side out of the folder.

        Addressed by **blob name, not generation number**. That is not
        fussiness: the two sides of a fork usually carry the *same*
        generation, because each device numbered its push against a folder
        in which the other's file had not yet appeared. Two devices at
        generation 2 is the normal shape of a fork, and asking for
        "generation 2" would be ambiguous — it would quietly stage
        whichever side was enumerated first, which is a coin flip between
        the copy the student chose and the one they rejected.

        The blob name is unique by construction, because it carries the
        device tag (see ``naming.DEVICE_TAG_CHARS``).
        """
        transport = self._transport(link)
        scan = transport.scan()
        for entry in scan.usable_manifests:
            if entry.manifest.blob_name != str(blob_name):
                continue
            ok, reason, blob_path = transport.verify(entry.manifest)
            if not ok:
                raise TransportError(
                    f"{blob_name} did not verify: {reason}")
            head = HeadGeneration(
                manifest=entry.manifest,
                manifest_name=entry.file_name,
                blob_path=str(blob_path),
                blob_bytes=entry.manifest.bytes,
                verified=True,
            )
            dest = self.staging_dir / f"resolve-{Path(blob_name).stem}.wimi"
            return transport.pull(dest, head=head).dest_path
        raise TransportError(f"{blob_name} is not in this folder")

    def stage_for_resolution(
        self, link: SyncLink, blob_name: str, device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Phase 2, **worker thread**: the chosen side, and what the student saw.

        A resolution records the heads present when the student chose, so a
        send can tell whether the folder moved in between (#148). Read here,
        from the same folder listing the side is staged from, so the two
        cannot describe different moments.
        """
        archive_path = self.stage_other_side(link, blob_name)
        transport = self._transport(link)
        graph = transport.lineage(transport.scan())
        chosen = next(
            (m for m in graph.by_sha.values() if m.blob_name == str(blob_name)), None)
        return {
            "archive_path": archive_path,
            "sync_id": link.sync_id,
            "chosen": chosen,
            "heads": list(graph.heads),
            "base": self._base_of(link, device_id, graph),
        }

    def finish_resolution(
        self, user_id: int, choice: str, staged: Dict[str, Any], resolution
    ) -> Dict[str, Any]:
        """Phase 3, **caller's thread**: remember the choice until it is sent.

        Computes what the send will publish. The content parent is the copy
        the profile now holds: the other side for ``keep_remote`` (which just
        replaced it), this device's base otherwise. Every other head the
        student saw is superseded -- publishing a descendant of one side is
        not enough on its own, because the rejected side would stay a head
        forever (see ``test_a_descendant_of_one_side_alone_does_not_clear_the_fork``).

        ``keep_remote`` onto the only head needs no send at all: the profile
        now holds exactly what the folder does, and there is nothing to
        retire. So no pending is recorded, and the panel says it is settled.
        """
        from .resolution import KEEP_REMOTE

        chosen: Optional[SyncManifest] = staged.get("chosen")
        heads: List[SyncManifest] = list(staged.get("heads") or [])
        base: Optional[str] = staged.get("base")

        if choice == KEEP_REMOTE and chosen is not None:
            content = chosen.sha256
        else:
            content = base

        supersedes = [h.sha256 for h in heads if h.sha256 != content]
        by_sha = {h.sha256: h for h in heads}
        kept = by_sha.get(content) if content else None
        pending = {
            "choice": choice,
            "parents": [content] if content else [],
            "supersedes": supersedes,
            "saw_heads": [h.sha256 for h in heads],
            "resolved_at": utc_now_iso(),
            "kept_device": kept.device_name if kept is not None else None,
            "set_aside_devices": [by_sha[s].device_name for s in supersedes],
        }

        new_base = chosen if choice == KEEP_REMOTE else None
        if not supersedes:
            # Nothing to retire, so nothing to send.
            if new_base is not None:
                self.state.record_install_base(
                    user_id, staged["sync_id"], new_base.sha256, new_base.generation)
            self.state.clear_pending(user_id)
            return {"send_needed": False, "pending": None}

        self.state.record_resolution(
            user_id, pending,
            base_sha256=new_base.sha256 if new_base is not None else None,
            base_generation=new_base.generation if new_base is not None else None,
        )
        return {"send_needed": True, "pending": pending}

    # ------------------------------------------------------------------ forks

    def forks(self, user_id: int) -> List[Fork]:
        """Detect forks. Resolving them is #124."""
        link = self.state.get_link(user_id)
        if link is None:
            return []
        return self._transport(link).detect_forks()
