"""
The sync manifest — the small JSON file that makes a generation authoritative.

This is NOT the manifest *inside* a ``.wimi`` archive (that one is
``profile_archive.MANIFEST_MEMBER``, and describes the archive's contents). This
one sits **beside** the archive in the sync folder and describes the archive's
*place in a chain of generations*.

Write order is blob first, manifest second, always. A push interrupted between
the two leaves a blob nobody points at, which the pull path ignores, so the
previous generation stays authoritative. The reverse order would make a
half-written blob authoritative — which is the failure this ordering exists to
prevent.

``parent_generation`` is what makes fork detection possible: two manifests
naming the same parent are two devices that both built on the same ancestor,
i.e. a fork. Detecting that is in scope; resolving it is #124.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

MANIFEST_FORMAT = "wimi-foldersync-manifest"
MANIFEST_FORMAT_VERSION = 1

#: A generation with no parent — the first push into an empty folder.
NO_PARENT = 0


class ManifestError(ValueError):
    """A manifest is absent, malformed, or from a format we do not understand."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class SyncManifest:
    """
    Everything a pulling device needs in order to decide whether to trust a blob.

    Every field here is checkable against the blob or against the local install.
    Nothing is taken on faith: ``sha256`` and ``bytes`` are re-derived from the
    file on pull, and a mismatch disqualifies the generation outright.
    """

    format: str
    format_version: int

    sync_id: str
    generation: int
    parent_generation: int

    device_id: str
    device_name: str

    blob_name: str
    sha256: str
    bytes: int

    schema_version: int
    row_counts: Dict[str, int]

    #: Everything else ``build_profile_archive`` measured from the snapshot --
    #: date ranges, subject count. Kept separate from ``row_counts`` because
    #: that one is counts, is typed ``int``, and coerces on parse; a date
    #: string in it raises. #124's fork report needs the dates *cheaply* --
    #: they are what separate "a month of work" from "a stale copy" -- so
    #: they ride in the manifest rather than being read out of the archive.
    #: Untyped and optional: a manifest written before this existed parses
    #: to an empty dict, which readers must treat as "not recorded".
    stats: Dict[str, Any] = field(default_factory=dict)

    #: The generation(s) this one's CONTENT descends from, by blob sha256
    #: (#148, #149). ``None`` means the field was absent -- a manifest written
    #: before lineage existed -- and readers fall back to ``parent_generation``.
    #: ``()`` means "descends from nothing in this folder": a first push, or a
    #: device whose content has no known relation to anything here.
    #:
    #: Why a digest and not ``parent_generation``: both sides of a fork
    #: normally SHARE a generation number (each device numbered its push
    #: against a folder where the other's file had not yet appeared), so a
    #: number cannot say which side something was built on. That made the
    #: recorded parent a function of which hostname sorted first.
    parents: Optional[Tuple[str, ...]] = None

    #: Generations this one explicitly REPLACES -- the rejected sides of a
    #: fork the student resolved. Separate from ``parents`` because the two
    #: mean different things and conflating them cannot express a real case:
    #: a first-connect "keep this computer's copy" whose content has no folder
    #: ancestor at all, yet must still retire the other head.
    #:
    #: Publishing a descendant of the chosen side does not by itself tell
    #: anyone the other side was rejected -- it would stay a leaf, a live
    #: head, forever. This field is what lets a fork clear.
    supersedes: Tuple[str, ...] = ()

    created_at: str = ""
    app_version: str = "unknown"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @property
    def is_root(self) -> bool:
        """True for a generation with no ancestor in this folder."""
        if self.parents is not None:
            return len(self.parents) == 0
        return self.parent_generation == NO_PARENT

    @property
    def has_lineage(self) -> bool:
        """True when this manifest names its parents by digest (#148).

        False for a manifest written before that existed; its ancestry can
        only be inferred from ``parent_generation``, which is ambiguous
        across a fork.
        """
        return self.parents is not None


def build_manifest(
    *,
    sync_id: str,
    generation: int,
    parent_generation: int,
    device_id: str,
    device_name: str,
    blob_name: str,
    sha256: str,
    size_bytes: int,
    schema_version: int,
    row_counts: Optional[Dict[str, int]] = None,
    stats: Optional[Dict[str, Any]] = None,
    parents: Optional[Sequence[str]] = None,
    supersedes: Optional[Sequence[str]] = None,
    app_version: str = "unknown",
    created_at: Optional[str] = None,
) -> SyncManifest:
    """Assemble a manifest. Callers pass values derived from the SNAPSHOT, not the live DB."""
    return SyncManifest(
        format=MANIFEST_FORMAT,
        format_version=MANIFEST_FORMAT_VERSION,
        sync_id=str(sync_id),
        generation=int(generation),
        parent_generation=int(parent_generation),
        device_id=str(device_id),
        device_name=str(device_name),
        blob_name=str(blob_name),
        sha256=str(sha256),
        bytes=int(size_bytes),
        schema_version=int(schema_version),
        row_counts=dict(row_counts or {}),
        stats=dict(stats or {}),
        parents=None if parents is None else tuple(str(x) for x in parents),
        supersedes=tuple(str(x) for x in (supersedes or ())),
        created_at=created_at or utc_now_iso(),
        app_version=str(app_version),
    )


_REQUIRED = (
    "format", "format_version", "sync_id", "generation", "parent_generation",
    "device_id", "device_name", "blob_name", "sha256", "bytes", "schema_version",
)


def parse_manifest(payload: bytes | str) -> SyncManifest:
    """
    Parse and validate a manifest.

    Raises :class:`ManifestError` rather than returning a half-trusted object.
    A manifest we cannot fully parse is a manifest we must not act on — the
    pull path treats every such failure as "skip this generation", never as
    "assume a default".
    """
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ManifestError(f"manifest is not valid UTF-8: {exc}") from exc
    try:
        raw = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError("manifest is not a JSON object")

    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        raise ManifestError(f"manifest is missing required field(s): {', '.join(sorted(missing))}")

    if raw.get("format") != MANIFEST_FORMAT:
        raise ManifestError(
            f"unrecognised manifest format {raw.get('format')!r} "
            f"(expected {MANIFEST_FORMAT!r})"
        )

    try:
        fmt_version = int(raw["format_version"])
    except (TypeError, ValueError) as exc:
        raise ManifestError("manifest format_version is not an integer") from exc
    if fmt_version > MANIFEST_FORMAT_VERSION:
        raise ManifestError(
            f"manifest was written by a newer version of WIMI "
            f"(manifest format {fmt_version}, this build understands "
            f"{MANIFEST_FORMAT_VERSION}). Update WIMI on this device."
        )

    try:
        generation = int(raw["generation"])
        parent = int(raw["parent_generation"])
        size_bytes = int(raw["bytes"])
        schema_version = int(raw["schema_version"])
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"manifest has a non-integer numeric field: {exc}") from exc

    if generation <= 0:
        raise ManifestError(f"manifest generation must be positive, got {generation}")
    if parent < 0:
        raise ManifestError(f"manifest parent_generation must not be negative, got {parent}")
    if parent >= generation:
        raise ManifestError(
            f"manifest generation {generation} claims parent {parent}, which is not "
            f"an ancestor"
        )

    sha = str(raw["sha256"]).strip().lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ManifestError("manifest sha256 is not a 64-character hex digest")

    row_counts = raw.get("row_counts") or {}
    if not isinstance(row_counts, dict):
        raise ManifestError("manifest row_counts is not an object")

    # Absent or null -> legacy (None); a list, even empty, -> lineage recorded.
    # The distinction is load-bearing: None falls back to parent_generation,
    # while () asserts "descends from nothing here".
    raw_parents = raw.get("parents")
    parents = None if raw_parents is None else _digest_list(raw_parents, "parents", sha)
    supersedes = _digest_list(raw.get("supersedes") or [], "supersedes", sha)

    return SyncManifest(
        format=MANIFEST_FORMAT,
        format_version=fmt_version,
        sync_id=str(raw["sync_id"]),
        generation=generation,
        parent_generation=parent,
        device_id=str(raw["device_id"]),
        device_name=str(raw["device_name"]),
        blob_name=str(raw["blob_name"]),
        sha256=sha,
        bytes=size_bytes,
        schema_version=schema_version,
        row_counts={str(k): int(v) for k, v in row_counts.items()},
        stats={str(k): v for k, v in (raw.get("stats") or {}).items()},
        parents=parents,
        supersedes=supersedes,
        created_at=str(raw.get("created_at") or ""),
        app_version=str(raw.get("app_version") or "unknown"),
    )


def _digest_list(value: Any, name: str, own_sha: str) -> Tuple[str, ...]:
    """Validate a list of blob digests. Strict, like every other field here.

    A manifest naming itself is refused: a generation cannot descend from or
    supersede its own blob, and allowing it would let one malformed file make
    itself permanently a head or permanently not one.
    """
    if not isinstance(value, (list, tuple)):
        raise ManifestError(f"manifest {name} is not a list")
    out = []
    for item in value:
        d = str(item).strip().lower()
        if len(d) != 64 or any(c not in "0123456789abcdef" for c in d):
            raise ManifestError(f"manifest {name} entry is not a 64-character hex digest")
        if d == own_sha:
            raise ManifestError(f"manifest {name} names its own blob")
        out.append(d)
    return tuple(out)


def describe_for_user(manifest: SyncManifest) -> Dict[str, Any]:
    """
    The real numbers a fork dialog needs in order to be answerable.

    A student choosing between two sides needs to tell "a month of work" from "a
    stale copy", and only counts and dates do that. Reassurance does not.
    """
    return {
        "generation": manifest.generation,
        "parent_generation": manifest.parent_generation,
        "device_name": manifest.device_name,
        "device_id": manifest.device_id,
        "created_at": manifest.created_at,
        "entries": manifest.row_counts.get("entries"),
        "sessions": manifest.row_counts.get("sessions"),
        "exam_contexts": manifest.row_counts.get("exam_contexts"),
        "schema_version": manifest.schema_version,
        "bytes": manifest.bytes,
        # How a side is ADDRESSED (unique by construction) and how lineage
        # names it (#148). A generation number is neither: both sides of a
        # fork usually share one.
        "blob_name": manifest.blob_name,
        "sha256": manifest.sha256,
    }
