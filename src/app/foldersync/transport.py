"""
The folder transport — write and read generations in a plain directory.

**This module does not know what a cloud is.** It reads and writes an ordinary
directory and never asks which client is watching it. That is a design
requirement, not a convenience: it is what makes the transport testable without
a Box account (there is no Box account, and none is obtainable), and it is what
makes Box, OneDrive, Drive, iCloud, Dropbox, Syncthing, a NAS and a USB stick
one code path instead of six.

Everything provider-specific arrives as a :class:`~.providers.Provider` value
object and is used only to *describe* and *warn* — never to branch the algorithm.

It also does not know what a database is. Wiring this to ``profile_archive`` is
``service.py``'s job.

Operations
----------

**Push** — snapshot (caller's job), then write the blob, *then* the manifest.
Blob first, so a half-finished write is detectable rather than authoritative.
The blob is written directly under its final name: nothing here relies on an
atomic rename, because rename is unreliable on these filesystems.

**Pull** — enumerate manifests, take the highest generation whose blob's SHA-256
validates. **Never trust a manifest whose blob does not verify.** A manifest
that fails verification does not poison the folder; the next-highest valid
generation is used instead.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import naming
from .hydration import (
    DEFAULT_TIMEOUT_S,
    HydrationTimeout,
    Residency,
    read_bytes_bounded,
    residency,
    sha256_bounded,
)
from .manifest import (
    NO_PARENT,
    ManifestError,
    SyncManifest,
    build_manifest,
    parse_manifest,
)
from .naming import ConflictCopy, ParsedName
from .providers import Provider, get_provider


class TransportError(Exception):
    """The folder could not be used as a transport."""


class FolderUnavailable(TransportError):
    """The folder is missing, unreadable, or the cloud client is not presenting it."""


# --------------------------------------------------------------------- scan results

@dataclass
class ManifestEntry:
    """One manifest file found in the folder — parsed, or with the reason it was not."""
    file_name: str
    parsed_name: ParsedName
    manifest: Optional[SyncManifest] = None
    error: Optional[str] = None

    @property
    def usable(self) -> bool:
        return self.manifest is not None


@dataclass
class FolderScan:
    """
    Everything one directory listing told us. Cheap, and honest about what it could not read.

    Enumeration alone does not materialise files on Box — Box documents download
    as triggered by *open* — so a scan is safe to run without hydrating the whole
    folder. It still crosses a network-backed filesystem, so it belongs off the
    Qt main thread.
    """
    sync_dir: str
    manifests: List[ManifestEntry] = field(default_factory=list)
    #: (device, generation) -> blob file name
    blobs: Dict[Tuple[str, int], str] = field(default_factory=dict)
    conflict_copies: List[ConflictCopy] = field(default_factory=list)
    #: Names present that a provider would silently refuse to sync.
    unsyncable: List[Tuple[str, str]] = field(default_factory=list)
    #: Names we did not recognise at all. Left strictly alone.
    unknown: List[str] = field(default_factory=list)

    @property
    def usable_manifests(self) -> List[ManifestEntry]:
        return [m for m in self.manifests if m.usable]

    @property
    def highest_generation(self) -> int:
        """
        Highest generation number seen ANYWHERE — manifests, orphan blobs, conflict copies.

        Used to allocate the next generation. Deliberately broader than
        "highest valid generation": a number that appeared on a file that later
        failed to verify must still never be reused, or two different payloads
        end up sharing a name.
        """
        seen = [0]
        seen.extend(m.parsed_name.generation for m in self.manifests)
        seen.extend(gen for (_device, gen) in self.blobs)
        seen.extend(c.parsed.generation for c in self.conflict_copies)
        return max(seen)


@dataclass
class Lineage:
    """The folder's generations as a graph (#148). See ``FolderTransport.lineage``."""
    by_sha: Dict[str, SyncManifest]
    parents_of: Dict[str, Set[str]]
    heads: List[SyncManifest]

    def ancestors(self, sha: str) -> Set[str]:
        """Every generation ``sha`` descends from, by content lineage. Excludes itself."""
        seen: Set[str] = set()
        stack = list(self.parents_of.get(sha, ()))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.parents_of.get(cur, ()))
        return seen

    def common_ancestors(self, shas: Sequence[str]) -> List[SyncManifest]:
        """Generations every one of ``shas`` descends from."""
        sets = [self.ancestors(s) for s in shas]
        if not sets:
            return []
        common = set.intersection(*sets)
        return [self.by_sha[s] for s in common if s in self.by_sha]

    def is_superseded(self, sha: str) -> Optional[SyncManifest]:
        """The manifest that explicitly superseded ``sha``, if any.

        This is how a device learns its copy was not the one kept: its base
        appears in another generation's ``supersedes``.
        """
        for m in self.by_sha.values():
            if sha in m.supersedes:
                return m
        return None

    def relation_of(self, base: Optional[str]) -> Tuple[str, Optional[SyncManifest]]:
        """Where a device's copy stands against the folder, given its base.

        Returns ``(relation, manifest)``:

        ``unknown``
            No base recorded: the device has neither published nor installed
            from this folder.
        ``missing``
            The base is not in the folder -- typically this device's own push
            that the cloud client has not listed yet.
        ``current``
            The base is a head. (There may be other heads; that is a fork,
            and ``detect_forks`` reports it.)
        ``behind``
            A head descends from the base: another device built on this
            device's copy and published. ``manifest`` is the newest such head.
            Ordinary; fetching catches up.
        ``superseded``
            No head descends from the base: a resolution on another device
            chose against it, or against something built on it. ``manifest``
            is the generation that did the superseding. This is how the losing
            side of a fork learns it lost -- the owner's decision on #148 needs
            that device told, not left to find out by accident.
        """
        if not base:
            return "unknown", None
        if base not in self.by_sha:
            return "missing", None
        if any(h.sha256 == base for h in self.heads):
            return "current", None
        containing = [h for h in self.heads if base in self.ancestors(h.sha256)]
        if containing:
            return "behind", containing[0]
        retired = {base} | {
            s for s in self.by_sha if base in self.ancestors(s)
        }
        for m in sorted(self.by_sha.values(), key=lambda m: (-m.generation, m.blob_name)):
            if retired & set(m.supersedes):
                return "superseded", m
        # Unreachable while every non-head is named by something, but a
        # reference into a digest that has since vanished can orphan a chain.
        return "superseded", self.heads[0] if self.heads else None


@dataclass
class HeadGeneration:
    """The generation a pull would take: the highest whose blob is intact.

    ``verified`` is False when the blob is present but its bytes are **not
    local** and the caller asked not to hydrate. The generation is still the
    head -- the manifest says what it is, and the manifest is local -- but
    nobody has checked its digest yet, and a caller that displays it must say
    so rather than implying it has been validated (#147).
    """
    manifest: SyncManifest
    manifest_name: str
    blob_path: str
    blob_bytes: int
    verified: bool = True


@dataclass
class VerificationFailure:
    """A generation that claimed to be authoritative and was not."""
    generation: int
    manifest_name: str
    reason: str


@dataclass
class Fork:
    """
    More than one head, from more than one device (#148).

    ``sides`` are the heads. ``parent_generation`` is the newest generation
    every side descends from -- where the copies went their own way -- or
    ``NO_PARENT`` when they share no history at all.

    ``first_connect`` is that last case: two copies of one profile that were
    never synced, typically a second computer set up from a manual export and
    then linked. #124 treats it as the same three-way choice presented at a
    different moment, so it is the same object with a different framing,
    not a separate mechanism.
    """
    parent_generation: int
    sides: List[SyncManifest]
    first_connect: bool = False
    #: Not a divergence the folder shows, but one this device has: its copy
    #: was set aside by a resolution made elsewhere. ``sides`` is this
    #: device's base and the generation that superseded it. Offered through
    #: the same report and the same three choices rather than a second
    #: mechanism -- the student's question ("which copy do I want?") is the
    #: same one.
    set_aside: bool = False

    @property
    def device_names(self) -> List[str]:
        return [m.device_name for m in self.sides]


@dataclass
class PushResult:
    generation: int
    parent_generation: int
    blob_name: str
    manifest_name: str
    sha256: str
    bytes: int
    blob_path: str
    manifest_path: str


@dataclass
class PullResult:
    generation: int
    manifest: SyncManifest
    dest_path: str
    bytes: int
    sha256: str
    #: Generations that were higher but failed verification, newest first.
    skipped: List[VerificationFailure] = field(default_factory=list)


# --------------------------------------------------------------------- the transport

class FolderTransport:
    """
    Reads and writes generations in ``<folder>/WIMI/<sync_id>/``.

    Stateless between calls apart from its configuration, so a caller may hold
    one per linked profile or build one per operation.
    """

    def __init__(
        self,
        folder: str | Path,
        sync_id: str,
        provider_id: str = "generic",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ):
        self.folder = Path(folder)
        self.sync_id = str(sync_id)
        self.provider: Provider = get_provider(provider_id)
        self.timeout_s = float(timeout_s)

    # ------------------------------------------------------------------ layout

    @property
    def root_dir(self) -> Path:
        return self.folder / naming.ROOT_DIR_NAME

    @property
    def sync_dir(self) -> Path:
        return self.root_dir / self.sync_id

    def ensure_dir(self) -> Path:
        try:
            self.sync_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FolderUnavailable(
                f"could not create the sync folder {self.sync_dir}: {exc}"
            ) from exc
        return self.sync_dir

    # ------------------------------------------------------------------ preflight

    def preflight(self) -> List[str]:
        """
        Problems with the folder itself, in the user's words. Empty means usable.

        Run when the folder is PICKED, not when a write fails — the path-length
        ceiling in particular is a property of the choice, and telling someone
        about it after they have used the folder for a month is useless.
        """
        problems: List[str] = []

        if not self.folder.exists():
            problems.append(f"the folder does not exist: {self.folder}")
            return problems
        if not self.folder.is_dir():
            problems.append(f"that is a file, not a folder: {self.folder}")
            return problems
        if not os.access(str(self.folder), os.W_OK):
            problems.append(f"WIMI cannot write to that folder: {self.folder}")

        # Budget the LONGEST name we will ever write, not the directory itself.
        longest = self.sync_dir / naming.blob_name(
            "x" * naming.DEVICE_MAX_CHARS, 999999, "f" * 32)
        budget = naming.path_budget_error(str(longest), self.provider)
        if budget:
            problems.append(budget)

        for part in (naming.ROOT_DIR_NAME, self.sync_id):
            reason = naming.ignored_reason(part, self.provider)
            if reason:
                problems.append(f"folder component {part!r} would not sync: {reason}")

        return problems

    # ------------------------------------------------------------------ scan

    def scan(self) -> FolderScan:
        """
        One directory listing, taken apart. Never raises on a single bad file.

        A manifest that fails to parse becomes a :class:`ManifestEntry` carrying
        its error, not an exception — one corrupt file must not make the folder
        unreadable.
        """
        scan = FolderScan(sync_dir=str(self.sync_dir))
        if not self.sync_dir.exists():
            return scan

        try:
            names = sorted(p.name for p in self.sync_dir.iterdir() if p.is_file())
        except OSError as exc:
            raise FolderUnavailable(
                f"could not read the sync folder {self.sync_dir}: {exc}"
            ) from exc

        for name in names:
            blob = naming.parse_blob_name(name)
            if blob is not None:
                scan.blobs[(blob.device, blob.generation)] = name
                continue

            man = naming.parse_manifest_name(name)
            if man is not None:
                scan.manifests.append(self._read_manifest(name, man))
                continue

            conflict = naming.recover_conflict_copy(name, self.provider)
            if conflict is not None:
                scan.conflict_copies.append(conflict)
                continue

            reason = naming.ignored_reason(name, self.provider)
            if reason:
                scan.unsyncable.append((name, reason))
            else:
                scan.unknown.append(name)

        scan.manifests.sort(key=lambda e: (-e.parsed_name.generation, e.file_name))
        scan.conflict_copies.sort(key=lambda c: (-c.parsed.generation, c.name))
        return scan

    def _read_manifest(self, file_name: str, parsed_name: ParsedName) -> ManifestEntry:
        path = self.sync_dir / file_name
        try:
            payload = read_bytes_bounded(path, self.timeout_s)
        except HydrationTimeout as exc:
            return ManifestEntry(file_name, parsed_name, error=str(exc))
        except OSError as exc:
            return ManifestEntry(file_name, parsed_name, error=f"could not read: {exc}")

        try:
            manifest = parse_manifest(payload)
        except ManifestError as exc:
            return ManifestEntry(file_name, parsed_name, error=str(exc))

        # The file name and the contents must agree. They are written together,
        # so a disagreement means someone edited or renamed one of them.
        if manifest.generation != parsed_name.generation:
            return ManifestEntry(
                file_name, parsed_name,
                error=(
                    f"manifest says generation {manifest.generation} but its file name "
                    f"says {parsed_name.generation}"
                ),
            )
        if manifest.sync_id != self.sync_id:
            return ManifestEntry(
                file_name, parsed_name,
                error=(
                    f"manifest belongs to a different profile "
                    f"(sync id {manifest.sync_id}, expected {self.sync_id})"
                ),
            )
        return ManifestEntry(file_name, parsed_name, manifest=manifest)

    # ------------------------------------------------------------------ verification

    def _blob_path_for(self, manifest: SyncManifest) -> Path:
        """
        Resolve a manifest's blob name to a path inside the sync folder — safely.

        A manifest is data from another machine, so its ``blob_name`` is untrusted
        input. Anything with a path separator, a parent reference, or a name we
        would not ourselves have written is refused outright.
        """
        blob_name = manifest.blob_name
        if not blob_name or blob_name != Path(blob_name).name or os.sep in blob_name:
            raise TransportError(f"manifest names an unsafe blob path: {blob_name!r}")
        if ".." in blob_name.split("/") or "\\" in blob_name:
            raise TransportError(f"manifest names an unsafe blob path: {blob_name!r}")
        parsed = naming.parse_blob_name(blob_name)
        if parsed is None:
            raise TransportError(f"manifest names a blob we would not have written: {blob_name!r}")
        if parsed.generation != manifest.generation:
            raise TransportError(
                f"manifest generation {manifest.generation} points at blob "
                f"{blob_name!r}, which is generation {parsed.generation}"
            )
        return self.sync_dir / blob_name

    def verify(
        self, manifest: SyncManifest, *, allow_hydration: bool = True
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        Does this manifest's blob actually exist, have the right size, and hash right?

        Returns ``(ok, reason, blob_path)``. Size is checked before the hash purely
        to fail fast and cheaply — but note that on a streaming provider ``st_size``
        is reported correctly even for an evicted file, so a size match is NOT
        evidence the bytes are local. Only the hash is evidence, and getting it
        is what forces hydration.

        ``allow_hydration=False`` stops before that (#147). Measured on Box:
        hashing a cloud-only 26 KB blob cost **1,474 ms against 49.7 ms** for the
        same call on a local one, and it downloads the whole file — so a *status*
        check was silently pulling the entire archive down just to render a
        generation number, which is exactly what Files On-Demand exists to avoid.
        Reading a residency flag costs nothing and is measured not to hydrate
        (``0x100080``, ``FILE_READ_ATTRIBUTES``, no ``onReadFile``, no download).

        The refusal is reported as ``(False, "not checked …", path)`` and callers
        must distinguish it from a *failed* check. ``resolve_head`` does, and
        marks the head unverified rather than rejecting it.
        """
        try:
            blob_path = self._blob_path_for(manifest)
        except TransportError as exc:
            return (False, str(exc), None)

        res: Residency = residency(blob_path)
        if not res.exists:
            return (False, f"blob {manifest.blob_name} is missing from the folder", blob_path)
        if res.size_bytes != manifest.bytes:
            return (
                False,
                f"blob {manifest.blob_name} is {res.size_bytes} bytes, manifest says "
                f"{manifest.bytes} — the write was interrupted or the file was replaced",
                blob_path,
            )

        if not allow_hydration and res.needs_hydration:
            return (
                False,
                f"blob {manifest.blob_name} is not stored on this device yet, so "
                f"its checksum has not been verified",
                blob_path,
            )

        try:
            digest = sha256_bounded(blob_path, self.timeout_s)
        except HydrationTimeout as exc:
            return (False, str(exc), blob_path)
        except OSError as exc:
            return (False, f"could not read blob {manifest.blob_name}: {exc}", blob_path)

        if digest != manifest.sha256:
            return (
                False,
                f"blob {manifest.blob_name} failed its checksum (expected "
                f"{manifest.sha256[:12]}…, got {digest[:12]}…)",
                blob_path,
            )
        return (True, "", blob_path)

    def resolve_head(
        self, scan: Optional[FolderScan] = None, *, allow_hydration: bool = True
    ) -> Tuple[Optional[HeadGeneration], List[VerificationFailure]]:
        """
        The highest generation whose blob verifies, plus every higher one that did not.

        The failures are returned rather than swallowed: "we ignored generation 43
        because its checksum did not match and used 42 instead" is something the
        user is entitled to be told.

        ``allow_hydration=False`` is the display path (#147). A blob whose bytes
        are not local is **not** treated as a failure — failing it would walk
        past a perfectly good generation and name an older one as head, which
        is worse than admitting the check has not run. Instead the head comes
        back with ``verified=False`` and the caller says so.
        """
        scan = scan if scan is not None else self.scan()
        failures: List[VerificationFailure] = []

        for entry in scan.manifests:  # already sorted highest generation first
            if not entry.usable:
                failures.append(
                    VerificationFailure(entry.parsed_name.generation, entry.file_name, entry.error or "unreadable")
                )
                continue
            manifest = entry.manifest

            # Cheap, and measured not to hydrate. Deciding here rather than
            # reading it out of verify()'s reason string keeps "we did not
            # check" and "we checked and it is wrong" from ever being the
            # same value.
            if not allow_hydration:
                try:
                    blob_path = self._blob_path_for(manifest)
                except TransportError as exc:
                    failures.append(
                        VerificationFailure(manifest.generation, entry.file_name, str(exc)))
                    continue
                res = residency(blob_path)
                if res.needs_hydration:
                    return (
                        HeadGeneration(
                            manifest=manifest,
                            manifest_name=entry.file_name,
                            blob_path=str(blob_path),
                            blob_bytes=manifest.bytes,
                            verified=False,
                        ),
                        failures,
                    )

            ok, reason, blob_path = self.verify(manifest, allow_hydration=allow_hydration)
            if not ok:
                failures.append(VerificationFailure(manifest.generation, entry.file_name, reason))
                continue
            return (
                HeadGeneration(
                    manifest=manifest,
                    manifest_name=entry.file_name,
                    blob_path=str(blob_path),
                    blob_bytes=manifest.bytes,
                    verified=True,
                ),
                failures,
            )
        return (None, failures)

    # ------------------------------------------------------------------ forks

    def lineage(self, scan: Optional[FolderScan] = None) -> "Lineage":
        """The folder's generations as a graph, and which of them are heads.

        A generation is a **head** when no other generation names it -- as a
        content parent, or as something it supersedes. More than one head is a
        divergence. That single rule covers every case (#148, #149):

        * two devices pushing before either sees the other: two children of
          one parent, two heads;
        * a device that had not fetched: it now parents to its *base*, so its
          push is a second child rather than a false descendant -- two heads,
          reported instead of silently dropping the other device's work;
        * a resolution: both old sides are named by the new generation, so
          **one head**, and the fork clears;
        * a device with no known base publishing into a non-empty folder: a
          second head with no shared history -- first connect.

        Manifests written before lineage existed name no digests, so their
        ancestry falls back to ``parent_generation``. Across a legacy fork
        that number is ambiguous, so every manifest carrying it is treated
        as a parent -- which reproduces the old behaviour rather than
        inventing a precision the file never had.

        A reference to a digest that is not in the folder is ignored rather
        than fatal: an append-only folder should not lose files, but one that
        has must still enumerate.
        """
        scan = scan if scan is not None else self.scan()
        manifests = [e.manifest for e in scan.usable_manifests]
        by_sha = {m.sha256: m for m in manifests}
        by_gen: Dict[int, List[SyncManifest]] = {}
        for m in manifests:
            by_gen.setdefault(m.generation, []).append(m)

        parents_of: Dict[str, Set[str]] = {}
        referenced: Set[str] = set()
        for m in manifests:
            if m.parents is not None:
                ps = {p for p in m.parents if p in by_sha}
            elif m.parent_generation != NO_PARENT:
                ps = {x.sha256 for x in by_gen.get(m.parent_generation, []) if x.sha256 != m.sha256}
            else:
                ps = set()
            parents_of[m.sha256] = ps
            referenced |= ps
            referenced |= {s for s in m.supersedes if s in by_sha}

        heads = sorted(
            (m for m in manifests if m.sha256 not in referenced),
            key=lambda m: (-m.generation, m.blob_name),
        )
        return Lineage(by_sha=by_sha, parents_of=parents_of, heads=heads)

    def detect_forks(self, scan: Optional[FolderScan] = None) -> List[Fork]:
        """More than one head, from more than one device. At most one ``Fork``.

        **Heads from a single device are not a divergence.** One device can
        leave two children of one parent -- a retry after a crash between
        writing a manifest and recording it locally -- and that is its own
        work twice, not two students' work in conflict. This is the same rule
        the old sibling-based detector applied.

        Returned as a list for compatibility; it holds zero or one fork,
        because "more than one head" is one condition however many heads
        there are.
        """
        scan = scan if scan is not None else self.scan()
        graph = self.lineage(scan)
        if len(graph.heads) < 2 or len({m.device_id for m in graph.heads}) < 2:
            return []

        common = graph.common_ancestors([m.sha256 for m in graph.heads])
        if common:
            point = max(common, key=lambda m: (m.generation, m.blob_name))
            return [Fork(parent_generation=point.generation, sides=list(graph.heads))]
        return [Fork(parent_generation=NO_PARENT, sides=list(graph.heads), first_connect=True)]

    # ------------------------------------------------------------------ push

    def next_generation(self, scan: Optional[FolderScan] = None, floor: int = 0) -> int:
        """
        The generation number a push should claim.

        ``floor`` lets a caller include a locally-remembered generation, so a
        device does not reuse a number after a folder is emptied or a sync client
        has not yet brought the other device's files down.
        """
        scan = scan if scan is not None else self.scan()
        return max(scan.highest_generation, int(floor)) + 1

    def push(
        self,
        *,
        blob_source: str | Path,
        device_id: str,
        device_name: str,
        schema_version: int,
        row_counts: Optional[Dict[str, int]] = None,
        stats: Optional[Dict[str, Any]] = None,
        app_version: str = "unknown",
        generation: Optional[int] = None,
        parent_generation: Optional[int] = None,
        parents: Optional[Sequence[str]] = None,
        supersedes: Optional[Sequence[str]] = None,
        scan: Optional[FolderScan] = None,
        generation_floor: int = 0,
    ) -> PushResult:
        """
        Publish ``blob_source`` as the next generation.

        ``blob_source`` must ALREADY be a sealed archive built **outside** the sync
        folder. That ordering is not fussiness: Box documents that a database file
        modified in place inside the folder produces conflict copies even with a
        single user, and recommends copying the file out of the folder to work on
        it. We only ever place a finished file.

        Write order is blob, then manifest. If this call dies between the two, the
        folder holds an orphan blob that nothing points at, :meth:`resolve_head`
        ignores it, and the previous generation stays authoritative.

        ``parents`` / ``supersedes`` are blob digests (#148). **Production
        callers must pass ``parents``**, derived from what the device's
        content actually descends from. Omitting it keeps the pre-lineage
        behaviour -- parent taken from the folder head, no digests written --
        which is #149: a device that has not fetched publishes its content as
        if it had built on work it never had, and the other device's newer
        generation silently drops out of the head. It survives here only so
        the transport stays usable on its own; ``ProfileFolderSync`` always
        passes an explicit list.
        """
        source = Path(blob_source)
        if not source.is_file():
            raise TransportError(f"there is no archive to push at {source}")

        self.ensure_dir()
        scan = scan if scan is not None else self.scan()

        if generation is None:
            generation = self.next_generation(scan, floor=generation_floor)

        device_slug = naming.sanitize_device_name(device_name or device_id)
        # device_id, not just the slug: two machines can share a hostname,
        # and then a shared filename, and then one silently overwrites the
        # other's generation. See naming.DEVICE_TAG_CHARS.
        blob_file = naming.blob_name(device_slug, generation, device_id)
        manifest_file = naming.manifest_name(device_slug, generation, device_id)
        blob_path = self.sync_dir / blob_file
        manifest_path = self.sync_dir / manifest_file

        # Immutability is checked FIRST, before anything expensive and before any
        # other complaint. It is the most fundamental invariant here, so when it
        # is the thing that is wrong it should be the thing the caller is told.
        if blob_path.exists() or manifest_path.exists():
            raise TransportError(
                f"generation {generation} already exists in this folder — refusing to "
                f"overwrite it. Generation files are immutable."
            )

        for candidate in (blob_file, manifest_file):
            reason = naming.ignored_reason(candidate, self.provider)
            if reason:
                raise TransportError(f"{self.provider.display_name} would not sync {candidate!r}: {reason}")
            budget = naming.path_budget_error(str(self.sync_dir / candidate), self.provider)
            if budget:
                raise TransportError(budget)

        if parent_generation is None:
            if parents is not None:
                # Number the parent from the content parent itself, so the
                # display generation cannot disagree with the digest.
                known = {e.manifest.sha256: e.manifest for e in scan.usable_manifests}
                first = known.get(parents[0]) if parents else None
                parent_generation = first.generation if first else NO_PARENT
            else:
                head, _failures = self.resolve_head(scan, allow_hydration=False)
                parent_generation = head.manifest.generation if head else NO_PARENT
        if parent_generation >= generation:
            raise TransportError(
                f"refusing to push generation {generation} with parent "
                f"{parent_generation}: a generation must be newer than its parent"
            )

        # --- blob first -------------------------------------------------
        # Written directly under its final name. Nothing here relies on an
        # atomic rename; a partial file is simply a blob nobody points at.
        shutil.copyfile(str(source), str(blob_path))
        self._fsync(blob_path)

        size_bytes = blob_path.stat().st_size
        digest = sha256_bounded(blob_path, self.timeout_s)

        # --- manifest second, the commit point --------------------------
        manifest = build_manifest(
            sync_id=self.sync_id,
            generation=generation,
            parent_generation=parent_generation,
            device_id=device_id,
            device_name=device_slug,
            blob_name=blob_file,
            sha256=digest,
            size_bytes=size_bytes,
            schema_version=schema_version,
            row_counts=row_counts,
            stats=stats,
            parents=parents,
            supersedes=supersedes,
            app_version=app_version,
        )
        manifest_path.write_text(manifest.to_json(), encoding="utf-8")
        self._fsync(manifest_path)

        return PushResult(
            generation=generation,
            parent_generation=parent_generation,
            blob_name=blob_file,
            manifest_name=manifest_file,
            sha256=digest,
            bytes=size_bytes,
            blob_path=str(blob_path),
            manifest_path=str(manifest_path),
        )

    @staticmethod
    def _fsync(path: Path) -> None:
        """
        Flush a written file to the filesystem before we claim it exists.

        Best-effort: a cloud-backed filesystem may refuse ``fsync``, and that is
        not a reason to fail a push that otherwise succeeded.
        """
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    # ------------------------------------------------------------------ pull

    def pull(self, dest_path: str | Path, head: Optional[HeadGeneration] = None) -> PullResult:
        """
        Copy the highest verified generation out of the folder to ``dest_path``.

        The copy is re-verified at the destination. A blob can verify in the sync
        folder and still arrive damaged if the copy itself is truncated, and this
        is the last point at which that is cheap to catch.
        """
        failures: List[VerificationFailure] = []
        if head is None:
            head, failures = self.resolve_head()
        if head is None:
            raise TransportError(
                "no usable generation in this folder"
                + (f" ({len(failures)} rejected: {failures[0].reason})" if failures else "")
            )

        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(head.blob_path, str(dest))

        digest = sha256_bounded(dest, self.timeout_s)
        if digest != head.manifest.sha256:
            try:
                dest.unlink()
            except OSError:
                pass
            raise TransportError(
                f"generation {head.manifest.generation} was damaged in transit — the "
                f"copy did not match its checksum. Nothing was installed."
            )

        return PullResult(
            generation=head.manifest.generation,
            manifest=head.manifest,
            dest_path=str(dest),
            bytes=head.manifest.bytes,
            sha256=digest,
            skipped=failures,
        )

    # ------------------------------------------------------------------ recovery

    def recoverable_conflict_copies(self, scan: Optional[FolderScan] = None) -> List[Dict[str, object]]:
        """
        Provider conflict copies in this folder that are actually readable.

        Reported, never acted on. A conflict copy that verifies against a manifest
        we hold is offered to the user as recoverable; one that does not is still
        listed, because "there is a file here we cannot explain" is information.
        """
        scan = scan if scan is not None else self.scan()
        known: Dict[int, SyncManifest] = {
            e.manifest.generation: e.manifest for e in scan.usable_manifests
        }

        out: List[Dict[str, object]] = []
        for copy in scan.conflict_copies:
            path = self.sync_dir / copy.name
            res = residency(path)
            record: Dict[str, object] = {
                "name": copy.name,
                "copy_of": copy.original_name,
                "marker": copy.marker,
                "generation": copy.parsed.generation,
                "device": copy.parsed.device,
                "kind": copy.parsed.kind,
                "detected_as": copy.description,
                "size_bytes": res.size_bytes,
                "verifies_against_manifest": False,
                "note": "",
            }
            manifest = known.get(copy.parsed.generation)
            if copy.parsed.kind == "blob" and manifest is not None:
                try:
                    digest = sha256_bounded(path, self.timeout_s)
                except (HydrationTimeout, OSError) as exc:
                    record["note"] = f"could not read it to check: {exc}"
                else:
                    if digest == manifest.sha256:
                        record["verifies_against_manifest"] = True
                        record["note"] = (
                            f"identical to generation {manifest.generation} — a duplicate "
                            f"your cloud client made, safe to delete"
                        )
                    else:
                        record["note"] = (
                            f"differs from generation {manifest.generation} — this may hold "
                            f"work that never reached the folder under its own name"
                        )
            elif copy.parsed.kind == "blob":
                record["note"] = (
                    f"no manifest for generation {copy.parsed.generation} — this may be the "
                    f"only copy of that generation"
                )
            out.append(record)
        return out
