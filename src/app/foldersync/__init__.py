"""
Folder-based profile sync (#123, behind #22 comment #1455).

A user picks a folder inside whatever cloud client they already run. WIMI writes
sealed, generation-named archives into it and reads them back. **No provider
APIs, no OAuth, no credentials** — one code path covers Box, OneDrive, Google
Drive, iCloud, Dropbox, Syncthing, a NAS and a USB stick.

    <user-picked folder>/WIMI/<profile-uuid>/
        profile-<device>-gen-0042.wimi      database only (include_media=False)
        manifest-<device>-gen-0042.json     generation, PARENT generation,
                                            device id + name, sha256, bytes,
                                            schema version, row counts, timestamp

Module map
----------

``providers``  What each cloud client does differently — as DATA. Adding a
               provider is a row, not a code path. Box's row is the researched
               one (#123 comment #1503).
``naming``     The file naming scheme, and the provider name rules it must
               survive. Sanitises the user-influenced ``<device>`` segment to an
               allowlist, because Box silently ignores "file names containing
               special characters" without saying which.
``hydration``  Reading files that may not be locally present. The whole risk of
               the feature, and worse on Box than anywhere else: Box streams by
               default and evicts after 30 days without modification, which an
               immutable-file design triggers by construction.
``manifest``   The commit point. Written second, always.
``transport``  Push and pull against a plain directory. Knows nothing about
               clouds or databases.
``state``      The device-local profile-to-folder link. Holds no identity of
               its own: the device id is ``MasterDatabase.get_device_id()`` and
               the profile id is ``profile_identity.profile_uuid``, both landed
               by #126/#129 after this package was first written.
``service``    Wires the transport to ``profile_archive`` and ``MasterDatabase``.
               Each operation is three phases; see its *Threading* section.
``jobs``       Runs the folder-I/O phase off the caller's thread, leaving every
               database call on it.
``forks``      Telling two copies of one profile apart, so a student can
               choose between them (#124). Detection lives in ``transport``;
               this is the report that makes the choice answerable.
``resolution`` Acting on that choice, behind an unconditional verified
               export. The one module here that can destroy something.

Identity is read, never minted
------------------------------

The folder segment is the profile's own uuid, so it is **derived rather than
agreed**: two devices holding one profile compute the same path, and two
different profiles sharing a folder get separate segments. The first draft of
this package predated #129 and had to negotiate — device A minted a sync id,
wrote it into the manifest, and device B adopted whatever it found. That also
meant an unrelated profile pointed at a shared folder would join **someone
else's generation chain**, undetectably. Both are gone.

Deliberately NOT here: fork *resolution* (#124) and media (#125). Fork
*detection* is here.
"""
from .manifest import SyncManifest, build_manifest, parse_manifest, ManifestError
from .naming import (
    ConflictCopy,
    blob_name,
    find_conflict_copies,
    manifest_name,
    parse_blob_name,
    parse_manifest_name,
    recover_conflict_copy,
    sanitize_device_name,
)
from .providers import PROVIDERS, Provider, get_provider
from .forks import ForkReport, SideSummary, build_fork_report, summarise_side
from .resolution import (
    CHOICES,
    KEEP_BOTH,
    KEEP_LOCAL,
    KEEP_REMOTE,
    ProfileIsOpen,
    Resolution,
    ResolutionError,
    SafetyExport,
    SafetyExportFailed,
    resolve_fork,
    take_safety_export,
)
from .jobs import STATE_DONE, STATE_FAILED, STATE_RUNNING, SyncJobs
from .service import (
    FetchResult,
    ProfileFolderSync,
    PushPlan,
    StatusInputs,
    SyncStatus,
)
from .state import DeviceIdentity, SyncLink, SyncState
from .transport import (
    FolderScan,
    FolderTransport,
    FolderUnavailable,
    Fork,
    HeadGeneration,
    PullResult,
    PushResult,
    TransportError,
    VerificationFailure,
)

__all__ = [
    "PROVIDERS", "Provider", "get_provider",
    "sanitize_device_name", "blob_name", "manifest_name",
    "parse_blob_name", "parse_manifest_name",
    "ConflictCopy", "recover_conflict_copy", "find_conflict_copies",
    "SyncManifest", "build_manifest", "parse_manifest", "ManifestError",
    "FolderTransport", "FolderScan", "HeadGeneration", "Fork",
    "PushResult", "PullResult", "VerificationFailure",
    "TransportError", "FolderUnavailable",
    "SyncState", "SyncLink", "DeviceIdentity",
    "ProfileFolderSync", "FetchResult", "SyncStatus",
    "PushPlan", "StatusInputs",
    "SyncJobs", "STATE_RUNNING", "STATE_DONE", "STATE_FAILED",
    "ForkReport", "SideSummary", "build_fork_report", "summarise_side",
    "CHOICES", "KEEP_BOTH", "KEEP_LOCAL", "KEEP_REMOTE",
    "Resolution", "SafetyExport", "resolve_fork", "take_safety_export",
    "ResolutionError", "ProfileIsOpen", "SafetyExportFailed",
]
