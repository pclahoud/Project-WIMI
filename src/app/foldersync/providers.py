"""
Provider quirks — as DATA, not as branches in the transport.

The transport (``transport.py``) is provider-agnostic: it writes and reads a
plain directory and never asks which cloud client is watching it. Everything
a specific client does differently lives in this table, so adding OneDrive or
Dropbox is a new row, not a new code path — and the one provider with no API
at all (iCloud) is not a special case.

Every Box field below is sourced. See #123 comment #1503 for the full
research write-up and the evidence ranking used; the short-form citation on
each field points at the Box page it came from:

  docs/drive-tech   docs.box.com .../box-drive/deploying-and-managing-box-drive
                    /technical-information-for-box-drive-administrators
  docs/drive-about  docs.box.com .../box-drive/getting-started-with-box-drive/about-box-drive
  docs/drive-offline  .../box-drive/getting-started-with-box-drive/making-content-available-offline
  docs/rename       .../box-fundamentals/for-users/staying-organized
                    /managing-files-and-folders/rename-files-and-folders
  dev/limitations   developer.box.com/guides/files/limitations
  kb/conflicts      support.box.com/hc/en-us/articles/360044193873  (File Version Conflicts)
  kb/ignored        support.box.com/hc/en-us/articles/360044195433  (File Types Ignored or Blocked)

NOTHING in this module talks to a provider API. These are filesystem facts
about a folder that a desktop client happens to keep synced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Pattern, Tuple


# --------------------------------------------------------------------- conflict copies

@dataclass(frozen=True)
class ConflictPattern:
    """
    Recognises a provider's conflict copy and recovers the name it was a copy OF.

    ``regex`` must define groups ``base`` (the original file name, rebuilt from
    the match) and ``marker`` (whatever the provider appended — a number, an
    email, a device name, a timestamp). ``description`` is shown to the user.
    """
    regex: Pattern[str]
    description: str

    def match(self, filename: str) -> Optional[Tuple[str, str]]:
        """Return ``(original_name, marker)`` if this is a conflict copy, else None."""
        m = self.regex.match(filename)
        if not m:
            return None
        groups = m.groupdict()
        marker = (groups.get("marker") or "").strip()
        stem = groups.get("stem") or ""
        ext = groups.get("ext") or ""
        return (stem + ext, marker)


# Box: "Documents with conflicts will either be appended with a number or
# email address in parentheses."  -- kb/conflicts, stated VERBATIM and
# IDENTICALLY in both the "on PCs" and "on Mac" sections of that article, so
# there is no platform difference to branch on.
#
# Box does NOT document whether the parenthetical lands before or after the
# extension, so we match BOTH rather than betting on one. Box Shuttle's docs
# use the same idiom with a word marker ("(Conflicted Copy)"), so the marker
# is not constrained to digits/emails either.
_BOX_CONFLICT_BEFORE_EXT = ConflictPattern(
    regex=re.compile(r"^(?P<stem>.+?)\s*\((?P<marker>[^()/\\]{1,128})\)(?P<ext>\.[A-Za-z0-9.]+)$"),
    description="Box conflict copy (marker in parentheses before the extension)",
)
_BOX_CONFLICT_AFTER_EXT = ConflictPattern(
    regex=re.compile(r"^(?P<stem>.+?)(?P<ext>\.[A-Za-z0-9.]+)\s*\((?P<marker>[^()/\\]{1,128})\)$"),
    description="Box conflict copy (marker in parentheses after the extension)",
)

# Other providers, carried so the table is visibly a table. Only Box is
# claimed to be research-backed at the level of #1503; these are recorded
# from this issue's earlier per-provider passes (#22 comment #964).
_ONEDRIVE_CONFLICT = ConflictPattern(
    regex=re.compile(r"^(?P<stem>.+)-(?P<marker>[A-Za-z0-9][A-Za-z0-9 _-]{0,62})(?P<ext>\.[A-Za-z0-9.]+)$"),
    description="OneDrive conflict copy (device name appended before the extension)",
)
_DROPBOX_CONFLICT = ConflictPattern(
    regex=re.compile(
        r"^(?P<stem>.+?)\s*\((?P<marker>.{1,128}?conflicted copy.{0,64}?)\)(?P<ext>\.[A-Za-z0-9.]+)$",
        re.IGNORECASE,
    ),
    description="Dropbox conflicted copy",
)
_SYNCTHING_CONFLICT = ConflictPattern(
    regex=re.compile(
        r"^(?P<stem>.+?)\.sync-conflict-(?P<marker>\d{8}-\d{6}-[A-Z0-9]+)(?P<ext>\.[A-Za-z0-9.]+)$"
    ),
    description="Syncthing conflict copy",
)


# --------------------------------------------------------------------- the table

@dataclass(frozen=True)
class Provider:
    """What one cloud client does to a folder we are using as a transport."""

    id: str
    display_name: str

    #: Default synced-folder locations, per ``sys.platform`` value. Used only to
    #: *suggest* a folder in a picker — never to assume one exists.
    default_folders: Dict[str, List[str]] = field(default_factory=dict)

    #: Patterns that identify a conflict copy this provider creates.
    conflict_patterns: List[ConflictPattern] = field(default_factory=list)

    #: Maximum full path length the service accepts, or None if unconstrained.
    max_path_chars: Optional[int] = None

    #: File extensions the client refuses to sync, silently. Lowercase, dotted.
    blocked_extensions: frozenset = frozenset()

    #: Name shapes the client silently ignores. Each is a callable name -> bool
    #: in ``naming.py``; here we only record the human description, because the
    #: *rules* are shared across providers and the *reasons* are not.
    ignored_name_rules: Tuple[str, ...] = ()

    #: True when the client keeps files remote by default and materialises on read.
    streaming_by_default: bool = False

    #: True when the client evicts on a *schedule*, not only under storage pressure.
    #: This is the one that punishes immutable files: a file that is never
    #: modified is, by construction, always the oldest candidate for eviction.
    scheduled_eviction: bool = False

    #: The user-facing name of the "keep this locally" setting, for UI copy.
    pin_setting_label: Optional[str] = None

    #: Free-tier ceilings, where they are published. Informational.
    free_total_bytes: Optional[int] = None
    free_max_file_bytes: Optional[int] = None
    free_versions_kept: Optional[int] = None

    #: Things a human needs to be told. Surfaced in the sync panel, not logged.
    caveats: Tuple[str, ...] = ()


_GIB = 1024 ** 3
_MIB = 1024 ** 2


BOX = Provider(
    id="box",
    display_name="Box (Box Drive)",
    # docs/drive-tech. NOTE the macOS path: the install guide and the Finder
    # sidebar both say "~/Box", but the real mount is under the directory Apple
    # reserves for File Provider extensions. Both are listed; neither is assumed.
    default_folders={
        "win32": [r"%USERPROFILE%\Box"],
        "darwin": ["~/Library/CloudStorage/Box-Box", "~/Box"],
    },
    conflict_patterns=[_BOX_CONFLICT_BEFORE_EXT, _BOX_CONFLICT_AFTER_EXT],
    # docs/rename: "Folder paths have a limit of 255 characters so keep folder
    # and file names as concise as possible to avoid running up against this
    # limit." This is a limit on the PATH, not the name.
    max_path_chars=255,
    # kb/ignored: a CLOSED list of ten, all Outlook PST and QuickBooks.
    # `.wimi` and `.json` are not in it, and neither is `.zip` -- so an
    # ordinary zip under an unusual extension is unaffected.
    blocked_extensions=frozenset({
        ".pst", ".qbw", ".nd", ".qbw.tlg", ".des",
        ".qba", ".qba.tlg", ".qbr", ".qby", ".qdt",
    }),
    ignored_name_rules=(
        "names starting with '.' are treated as hidden and are not synced",
        "names starting with '~' are treated as temporary and are not synced",
        "'.tmp' and '.bak' are treated as temporary/backup and are not synced",
        "names that are exactly 8 uppercase hex digits with no extension are ignored",
        "'file names containing special characters' are ignored -- Box does not "
        "say which, so we allowlist rather than trust an enumeration",
        "folder names ending in '.' sync but are unopenable on Windows",
    ),
    # docs/drive-about: "Box Drive is a productivity tool that streams all your
    # content from Box... without occupying any hard drive space."
    streaming_by_default=True,
    # docs/drive-tech: "Box Drive deletes a cached file: when the file cache has
    # not been modified for the past 30 days". Our files are written once and
    # never modified, so they start that clock immediately and are also first
    # in line when the cache fills ("those cached files that have gone the
    # longest without being modified"). Immutability is the WORST case for
    # Box's cache policy -- which is why hydration is the normal path here.
    scheduled_eviction=True,
    # docs/drive-offline. The legacy Windows menu said "Make Available Offline";
    # 2.47+ says "Always keep on this device". The reverse is "Free up space".
    pin_setting_label="Always keep on this device",
    free_total_bytes=10 * _GIB,
    free_max_file_bytes=250 * _MIB,
    free_versions_kept=1,
    caveats=(
        "Box Drive keeps files online-only by default and evicts a cached file "
        "after 30 days without modification, so a sealed archive is normally NOT "
        "local when you come back to it.",
        "Logging out of Box Drive deletes all cached files, including files "
        "marked for offline access and the offline preferences themselves.",
        "'Mark for Offline' can be disabled org-wide by a Box admin, which "
        "silently returns all pinned content to online-only.",
        "On the free Individual plan Box keeps 1 file version and offers no "
        "file recovery, so a clobbered file is unrecoverable. Generation-named "
        "files never clobber, so this never applies to us.",
        "A file that fails to upload becomes a Box 'problem item', and logging "
        "out deletes problem items -- so a local write is never proof of a sync.",
        "Box documents that a database file modified in place produces conflict "
        "copies even with a single user, and recommends copying the file out of "
        "the Box folder to work on it. We only ever place sealed snapshots.",
    ),
)


ONEDRIVE = Provider(
    id="onedrive",
    display_name="OneDrive",
    default_folders={"win32": [r"%USERPROFILE%\OneDrive"], "darwin": ["~/OneDrive"]},
    conflict_patterns=[_ONEDRIVE_CONFLICT],
    streaming_by_default=True,
    pin_setting_label="Always keep on this device",
    caveats=(
        "OneDrive's default exclusion list is expanding and fails with no error.",
    ),
)

GOOGLE_DRIVE = Provider(
    id="google_drive",
    display_name="Google Drive",
    default_folders={"win32": [r"G:\My Drive"], "darwin": ["~/Google Drive", "/Volumes/GoogleDrive"]},
    conflict_patterns=[_BOX_CONFLICT_BEFORE_EXT],  # Drive also uses " (1)"
    streaming_by_default=True,
    pin_setting_label="Available offline",
    caveats=(
        "Google Drive moves sync casualties into a 'lost_and_found/' folder "
        "rather than leaving a sibling conflict copy.",
    ),
)

ICLOUD = Provider(
    id="icloud",
    display_name="iCloud Drive",
    default_folders={
        "win32": [r"%USERPROFILE%\iCloudDrive"],
        "darwin": ["~/Library/Mobile Documents/com~apple~CloudDocs"],
    },
    conflict_patterns=[],  # iCloud resolves conflicts invisibly; no sibling appears.
    streaming_by_default=True,
    pin_setting_label='Turn off "Optimize Mac Storage"',
    caveats=(
        "iCloud resolves same-path conflicts invisibly -- no sibling file "
        "appears and a plain directory listing cannot tell a conflict happened. "
        "Generation-named files avoid the situation entirely.",
    ),
)

DROPBOX = Provider(
    id="dropbox",
    display_name="Dropbox",
    default_folders={"win32": [r"%USERPROFILE%\Dropbox"], "darwin": ["~/Dropbox"]},
    conflict_patterns=[_DROPBOX_CONFLICT],
    streaming_by_default=True,
    pin_setting_label="Make available offline",
)

SYNCTHING = Provider(
    id="syncthing",
    display_name="Syncthing",
    conflict_patterns=[_SYNCTHING_CONFLICT],
    streaming_by_default=False,
)

#: A folder nobody is watching -- a NAS mount, a USB stick, or a test directory.
#: This is what the spike proves itself against, and it is deliberately the
#: least capable row: no conflict patterns, no eviction, no path ceiling.
GENERIC = Provider(
    id="generic",
    display_name="Local folder",
    streaming_by_default=False,
)


PROVIDERS: Dict[str, Provider] = {
    p.id: p for p in (GENERIC, BOX, ONEDRIVE, GOOGLE_DRIVE, ICLOUD, DROPBOX, SYNCTHING)
}

DEFAULT_PROVIDER_ID = GENERIC.id


def get_provider(provider_id: Optional[str]) -> Provider:
    """Look up a provider, falling back to the generic folder for anything unknown."""
    if not provider_id:
        return GENERIC
    return PROVIDERS.get(str(provider_id).strip().lower(), GENERIC)


def all_conflict_patterns() -> List[ConflictPattern]:
    """
    Every provider's conflict pattern, for the startup hunt.

    We scan with ALL of them regardless of which provider the user named,
    because the user may have moved the folder between clients, and because a
    conflict copy found by the "wrong" pattern is still a recoverable file.
    """
    seen: List[ConflictPattern] = []
    for provider in PROVIDERS.values():
        for pattern in provider.conflict_patterns:
            if pattern not in seen:
                seen.append(pattern)
    return seen
