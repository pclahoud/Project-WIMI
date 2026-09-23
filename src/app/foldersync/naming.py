"""
The file naming scheme, and the name rules the providers impose on it.

Layout written into the user-picked folder::

    <folder>/WIMI/<sync-id>/
        profile-<device>-gen-0042.wimi      database only (include_media=False)
        manifest-<device>-gen-0042.json     generation, PARENT generation, ...

Two properties carry the whole design and both are enforced here:

*   **Immutable.** A generation file, once written, is never rewritten. Nothing
    needs an atomic rename, which matters because rename is unreliable on these
    filesystems.
*   **Disjoint writers.** ``<device>`` is in the name, so two devices never
    write the same path. Every provider misbehaviour worth fearing -- Box's
    conflict copies, iCloud's invisible resolution, a 1-version free tier -- is
    downstream of two writers sharing a path, and this removes the precondition.

``<device>`` is user-influenced (a student may name their laptop), so it is
**sanitised to an allowlist rather than checked against a denylist**. Box
documents that it silently ignores "file names containing special characters"
without ever saying which characters those are (#123 comment #1503 §4), and an
unspecified rule cannot be satisfied by enumeration. Box also silently
*sanitises* names at the service level -- "Names containing non-printable ASCII
characters, forward and backward slashes (/, \\), and protected names like .
and .. are automatically sanitized by removing the non-allowed characters" --
so a name we do not control is a name we cannot later parse back.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Optional

from .providers import Provider, all_conflict_patterns

# --------------------------------------------------------------------- constants

#: Root folder created inside whatever folder the user picks.
ROOT_DIR_NAME = "WIMI"

BLOB_PREFIX = "profile-"
BLOB_SUFFIX = ".wimi"
MANIFEST_PREFIX = "manifest-"
MANIFEST_SUFFIX = ".json"

#: Minimum zero-padding for the generation. Generations above 9999 simply grow;
#: everything sorts numerically, never lexicographically.
GEN_PAD = 4

#: ``<device>`` allowlist. Deliberately narrower than any provider requires.
DEVICE_ALLOWED = re.compile(r"[^A-Za-z0-9_-]+")
DEVICE_MAX_CHARS = 32
DEVICE_FALLBACK = "device"

#: Greedy ``.+`` so the split happens at the LAST "-gen-", which keeps a device
#: legitimately named "my-gen-box" parseable.
# The device tag is optional in the pattern so a folder written before it
# existed still enumerates instead of going silently unreadable. Such a name
# parses with an empty tag, which is honest: that file genuinely does not say
# which installation wrote it.
_TAG = r"(?:-(?P<tag>[0-9a-z]{" + str(8) + r"}))?"
_BLOB_RE = re.compile(
    r"^" + re.escape(BLOB_PREFIX) + r"(?P<device>.+?)" + _TAG
    + r"-gen-(?P<gen>\d{" + str(GEN_PAD) + r",})"
    + re.escape(BLOB_SUFFIX) + r"$"
)
_MANIFEST_RE = re.compile(
    r"^" + re.escape(MANIFEST_PREFIX) + r"(?P<device>.+?)" + _TAG
    + r"-gen-(?P<gen>\d{" + str(GEN_PAD) + r",})"
    + re.escape(MANIFEST_SUFFIX) + r"$"
)

#: Box ignores names that are exactly 8 uppercase hex digits with no extension.
#: Our names always carry an extension so this cannot fire, but asserting it
#: costs nothing and documents the landmine for whoever changes the scheme.
_EIGHT_HEX_RE = re.compile(r"^[0-9A-F]{8}$")


# --------------------------------------------------------------------- device names

def sanitize_device_name(raw: Optional[str]) -> str:
    """
    Reduce a user-influenced machine name to something every provider will carry.

    Allowlist ``[A-Za-z0-9_-]``, collapse runs of rejected characters to a single
    ``-``, trim leading/trailing separators, cap the length, and never return an
    empty string. A leading ``.`` or ``~`` cannot survive this, which matters:
    Box treats both as "do not sync", silently.
    """
    text = (raw or "").strip()
    text = DEVICE_ALLOWED.sub("-", text)
    text = text.strip("-_")
    if len(text) > DEVICE_MAX_CHARS:
        text = text[:DEVICE_MAX_CHARS].rstrip("-_")
    return text or DEVICE_FALLBACK


# --------------------------------------------------------------------- build / parse

#: Hex characters of the device id folded into every file name.
#: The whole design rests on two devices never writing the same path, and the
#: human-readable device NAME cannot carry that: it is the hostname, and
#: hostnames are not unique. Two machines from one corporate image, two VMs
#: from one template, a cloned laptop, or simply two `DESKTOP-PC`s sharing a
#: Box account all produce the same slug -- and then the same filename, and
#: then one device's generation silently replaces another's. That is the
#: exact silent overwrite this scheme exists to prevent.
#:
#: Caught on 2026-09-21 by an end-to-end fork test: two app-data directories
#: on one machine are two devices by every measure the code uses, and they
#: wrote one file. The device ID is a UUID and genuinely unique, so eight of
#: its hex characters are folded in beside the name. The name stays, because
#: a folder a student can read is worth more than eight characters.
DEVICE_TAG_CHARS = 8


def device_tag(device_id: Optional[str]) -> str:
    """A short, stable, collision-resistant tag for one installation.

    Derived from the device id rather than hashed: the id is already a UUID,
    so its own hex is as distinct as a digest of it and stays greppable
    against ``MasterDatabase.get_device_id()``.
    """
    cleaned = "".join(c for c in str(device_id or "") if c.isalnum()).lower()
    if not cleaned:
        # A device with no id is a bug upstream, but a name that collides is
        # worse than an ugly one -- and "unknown" at least never pretends to
        # be a different machine than the other "unknown".
        return "nodevid0"[:DEVICE_TAG_CHARS]
    return cleaned[:DEVICE_TAG_CHARS]


def blob_name(device: str, generation: int, device_id: Optional[str] = None) -> str:
    """Name of the sealed archive for ``generation`` written by this device."""
    return (f"{BLOB_PREFIX}{sanitize_device_name(device)}-{device_tag(device_id)}"
            f"-gen-{generation:0{GEN_PAD}d}{BLOB_SUFFIX}")


def manifest_name(device: str, generation: int, device_id: Optional[str] = None) -> str:
    """Name of the manifest that makes ``generation`` authoritative."""
    return (f"{MANIFEST_PREFIX}{sanitize_device_name(device)}-{device_tag(device_id)}"
            f"-gen-{generation:0{GEN_PAD}d}{MANIFEST_SUFFIX}")


@dataclass(frozen=True)
class ParsedName:
    """A generation file name, taken apart.

    ``device`` is the human label and may repeat across machines;
    ``device_tag`` is what actually distinguishes them. Compare tags, never
    names.
    """
    device: str
    generation: int
    kind: str  # "blob" | "manifest"
    device_tag: str = ""


def parse_blob_name(name: str) -> Optional[ParsedName]:
    """Parse ``profile-<device>-gen-NNNN.wimi``, or None if it is not one."""
    m = _BLOB_RE.match(name)
    if not m:
        return None
    return ParsedName(device=m.group("device"), generation=int(m.group("gen")),
                      kind="blob", device_tag=(m.group("tag") or ""))


def parse_manifest_name(name: str) -> Optional[ParsedName]:
    """Parse ``manifest-<device>-gen-NNNN.json``, or None if it is not one."""
    m = _MANIFEST_RE.match(name)
    if not m:
        return None
    return ParsedName(device=m.group("device"), generation=int(m.group("gen")),
                      kind="manifest", device_tag=(m.group("tag") or ""))


def sync_root(folder: str) -> PurePosixPath:
    """The ``WIMI/`` root inside a user-picked folder, as a relative path."""
    return PurePosixPath(folder) / ROOT_DIR_NAME


# --------------------------------------------------------------------- provider rules

def ignored_reason(name: str, provider: Provider) -> Optional[str]:
    """
    Why ``provider`` would silently refuse to sync a file called ``name``.

    Returns None when the name is safe. These rules all fail *without an error*
    on the providers that implement them, which is the entire reason this
    function exists rather than a try/except somewhere.
    """
    if not name:
        return "empty file name"
    if name.startswith("."):
        return "names starting with '.' are treated as hidden and are not synced"
    if name.startswith("~"):
        return "names starting with '~' are treated as temporary and are not synced"
    if name.endswith("."):
        return "names ending with '.' sync but cannot be opened on Windows"
    lowered = name.lower()
    for ext in (".tmp", ".bak"):
        if lowered.endswith(ext):
            return f"'{ext}' files are treated as temporary/backup and are not synced"
    if "." not in name and _EIGHT_HEX_RE.match(name):
        return "names that are exactly 8 uppercase hex digits with no extension are ignored"
    for blocked in provider.blocked_extensions:
        if lowered.endswith(blocked):
            return f"'{blocked}' is on {provider.display_name}'s blocked list and will not sync"
    return None


def path_budget_error(path: str, provider: Provider) -> Optional[str]:
    """
    Why ``path`` is too long for ``provider``, or None.

    Box's ceiling is on the **path**, not the name -- 255 characters total. A
    36-character sync id plus a device name plus a user-chosen folder nested
    inside ``C:\\Users\\<USERNAME>\\Box\\...`` is a realistic way to breach it,
    so this is checked when the folder is picked, not when a write fails.
    """
    limit = provider.max_path_chars
    if limit is None:
        return None
    if len(path) <= limit:
        return None
    return (
        f"path is {len(path)} characters, over {provider.display_name}'s "
        f"{limit}-character limit -- choose a folder closer to the top of the drive"
    )


# --------------------------------------------------------------------- conflict copies

@dataclass(frozen=True)
class ConflictCopy:
    """A provider-made duplicate that still looks like one of our files."""
    name: str            # the conflict copy's own file name, as found on disk
    original_name: str   # the name it is a copy OF
    marker: str          # what the provider appended (a number, an email, ...)
    parsed: ParsedName   # the generation file the original name describes
    description: str     # which provider pattern recognised it


def recover_conflict_copy(name: str, provider: Optional[Provider] = None) -> Optional[ConflictCopy]:
    """
    Recognise ``name`` as a provider conflict copy of one of our generation files.

    Scanned with **every** provider's patterns, not just the configured one: a
    student may have moved the folder between clients, and a conflict copy found
    by the "wrong" pattern is still a recoverable file. ``provider`` is accepted
    so a caller can bias the order, and its patterns are tried first.

    Returns None unless the recovered original is a name we would have written --
    so an unrelated ``Budget (1).xlsx`` sitting in the folder is left alone.
    """
    patterns = list(provider.conflict_patterns) if provider else []
    for pattern in all_conflict_patterns():
        if pattern not in patterns:
            patterns.append(pattern)

    for pattern in patterns:
        hit = pattern.match(name)
        if not hit:
            continue
        original, marker = hit
        parsed = parse_blob_name(original) or parse_manifest_name(original)
        if parsed is None:
            continue
        return ConflictCopy(
            name=name,
            original_name=original,
            marker=marker,
            parsed=parsed,
            description=pattern.description,
        )
    return None


def find_conflict_copies(names: List[str], provider: Optional[Provider] = None) -> List[ConflictCopy]:
    """Every conflict copy in a directory listing, newest generation first."""
    found = [c for c in (recover_conflict_copy(n, provider) for n in names) if c]
    found.sort(key=lambda c: (-c.parsed.generation, c.name))
    return found
