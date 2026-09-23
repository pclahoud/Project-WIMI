"""
Acting on a fork, once the student has chosen (#124).

Three options, one implementation, and **one rule above all of them**:

    Export before anything, on every path, always. An export that fails
    aborts the whole flow rather than proceeding with a warning. Nothing
    here is allowed to destroy a side.

That is #124's wording and it is the reason this module is separate from the
report. :func:`build_fork_report` answers *which copy do I want*; this answers
*and now make it so, without ever being the reason a student lost work*.

The three choices
-----------------

``keep_both``
    The other side is installed as a **second profile**.
    ``install_profile_as_new()`` already forks on a name collision
    (``alice`` -> ``alice_2``) rather than overwriting, so this is mostly
    existing behaviour.

``keep_local``
    This machine's copy wins. The other side is **exported and set aside**
    rather than deleted — a student who chooses wrong at 1am must be able to
    change their mind.

``keep_remote``
    The other side wins, via ``replace_profile()``. The local copy is
    recoverable from the safety export, which is the whole reason that export
    is unconditional.

Two things that are easy to get wrong
-------------------------------------

**A verified export is not "the file exists".** A zero-byte file exists. So
the export is read back: its manifest must parse, its ``user.db`` must open,
and its entry count must match the profile it was taken from. Only then is
anything allowed to change. Anything less and the safety net is a gesture.

**"Keep both" produces two profiles with the SAME profile uuid**, and that is
correct rather than a bug — ``users.profile_uuid`` is deliberately not
``UNIQUE``, because #22 comment #1454 made "keep both" a supported outcome and
two installs of one archive are a real thing. But it means **only one of them
may be linked to the folder.** Two profiles sharing a uuid and a sync link
would both publish into the same segment and fork against each other forever.
The local profile keeps the link; the newly installed copy gets none, and
:class:`Resolution` says so explicitly so a caller cannot quietly link it.
"""
from __future__ import annotations

import shutil
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.profile_archive import (
    DB_MEMBER,
    MANIFEST_MEMBER,
    ProfileArchiveError,
    build_profile_archive,
    install_profile_as_new,
    read_profile_archive,
    replace_profile,
)

#: The student's three options. Same three at first connect as at a fork --
#: #124 keeps them one implementation because they are the same choice
#: presented at two moments, and two implementations would drift.
KEEP_BOTH = "keep_both"
KEEP_LOCAL = "keep_local"
KEEP_REMOTE = "keep_remote"
CHOICES = (KEEP_BOTH, KEEP_LOCAL, KEEP_REMOTE)


class ResolutionError(Exception):
    """A fork resolution refused to proceed. Nothing was changed."""


class ProfileIsOpen(ResolutionError):
    """``keep_remote`` was asked for on the profile that is currently open.

    ``replace_profile`` refuses this, and the refusal is right: it swaps the
    database file under a live connection. #124's acceptance list asks what
    happens to in-flight work when a fork is resolved, and this is the
    concrete answer for the one choice that overwrites — **the profile must
    be closed first**, which is the existing profile-switch path rather than
    a second mechanism invented here.

    Raised **before** the safety export, deliberately. Writing a backup for
    an operation that cannot run leaves a file the student has to reason
    about for no benefit.
    """


class SafetyExportFailed(ResolutionError):
    """The pre-flight export did not produce a usable archive.

    Raised *before* anything is touched. This is the abort #124 requires:
    without a verified copy of the local side there is no undo, and no
    choice may be applied.
    """


@dataclass
class SafetyExport:
    """The unconditional copy taken before any choice is applied."""

    path: str
    bytes: int
    entries: int
    verified: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "bytes": self.bytes,
            "entries": self.entries,
            "verified": self.verified,
        }


@dataclass
class Resolution:
    """What was done, and what remains recoverable."""

    choice: str
    safety_export: SafetyExport
    #: Where the losing side was put, when one was set aside rather than used.
    set_aside_path: Optional[str] = None
    #: ``keep_both`` only: the second profile that now exists locally.
    installed_user_id: Optional[int] = None
    installed_username: Optional[str] = None
    installed_profile_uuid: Optional[str] = None
    #: True when the local database was replaced in place.
    replaced_local: bool = False
    #: ``keep_both``: the new profile must NOT be linked to the same folder.
    #: Two profiles sharing a uuid and a link would fork against each other
    #: forever. Stated rather than left for a caller to infer.
    installed_profile_must_not_sync: bool = False
    notes: List[str] = field(default_factory=list)
    #: Set by the sync layer, not here: whether the choice still has to be
    #: sent to the folder, and what that send will publish (#148). A choice
    #: is local until the student sends it.
    send_needed: Optional[bool] = None
    pending: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "choice": self.choice,
            "safety_export": self.safety_export.to_dict(),
            "set_aside_path": self.set_aside_path,
            "installed_user_id": self.installed_user_id,
            "installed_username": self.installed_username,
            "installed_profile_uuid": self.installed_profile_uuid,
            "replaced_local": self.replaced_local,
            "installed_profile_must_not_sync": self.installed_profile_must_not_sync,
            "notes": list(self.notes),
            "send_needed": self.send_needed,
            "pending": self.pending,
        }


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _count_entries(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _verify_archive(path: Path, *, expect_entries: Optional[int]) -> int:
    """Read an archive back and prove it is usable. Returns its entry count.

    A file existing is not a backup. This opens the zip, parses the manifest,
    extracts ``user.db`` and counts its entries, so a truncated write, a
    half-flushed file or a disk that silently dropped the bytes is caught
    **before** anything irreversible happens.
    """
    import tempfile

    if not path.is_file() or path.stat().st_size == 0:
        raise SafetyExportFailed(f"export {path} is missing or empty")

    try:
        inventory = read_profile_archive(path)
    except (ProfileArchiveError, OSError, zipfile.BadZipFile) as exc:
        raise SafetyExportFailed(f"export {path} did not read back: {exc}") from exc

    if not inventory.get("manifest"):
        raise SafetyExportFailed(f"export {path} has no usable manifest")

    work = Path(tempfile.mkdtemp(prefix="verify-export-"))
    try:
        with zipfile.ZipFile(str(path)) as zf:
            names = set(zf.namelist())
            if DB_MEMBER not in names or MANIFEST_MEMBER not in names:
                raise SafetyExportFailed(
                    f"export {path} is missing {DB_MEMBER} or {MANIFEST_MEMBER}")
            zf.extract(DB_MEMBER, str(work))
        try:
            found = _count_entries(work / DB_MEMBER)
        except sqlite3.Error as exc:
            raise SafetyExportFailed(
                f"export {path} contains an unreadable database: {exc}") from exc
    finally:
        shutil.rmtree(str(work), ignore_errors=True)

    if expect_entries is not None and found != expect_entries:
        raise SafetyExportFailed(
            f"export {path} holds {found} entries but the profile has "
            f"{expect_entries} — refusing to treat it as a backup")
    return found


def take_safety_export(
    master_db, user_id: int, safety_dir: str | Path, *, label: str = "before-resolve"
) -> SafetyExport:
    """The unconditional first step. Raises rather than returning a bad copy.

    Media is included. This is a recovery copy rather than a sync payload, so
    an image the student cannot get back is the same loss as a row they cannot
    get back — the reason sync archives omit media (#125: cost per generation)
    does not apply to a copy taken once.
    """
    directory = Path(safety_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"wimi-{label}-user{int(user_id)}-{_timestamp()}.wimi"

    try:
        build_profile_archive(master_db, user_id, dest, include_media=True)
    except Exception as exc:  # noqa: BLE001 - re-raised as the abort
        raise SafetyExportFailed(
            f"could not export the local profile before resolving: {exc}"
        ) from exc

    live_path = Path(master_db.ensure_user_database(user_id))
    expected = _count_entries(live_path)
    found = _verify_archive(dest, expect_entries=expected)

    return SafetyExport(
        path=str(dest), bytes=dest.stat().st_size, entries=found, verified=True
    )


def resolve_fork(
    master_db,
    *,
    user_id: int,
    choice: str,
    incoming_archive: str | Path,
    safety_dir: str | Path,
    active_user_id: Optional[int] = None,
) -> Resolution:
    """Apply the student's choice, after securing an undo.

    Args:
        user_id: the profile on **this** machine.
        choice: one of :data:`CHOICES`.
        incoming_archive: the other side, already staged and SHA-256 verified
            by ``fetch``/``pull``. Never re-verified here — that is the
            transport's job and duplicating it would let the two disagree.
        safety_dir: where the pre-flight export and any set-aside copy go.
            Somewhere durable and **outside the sync folder**: writing a
            backup into the folder we are resolving a conflict in is how the
            backup becomes part of the conflict.
        active_user_id: the profile currently open, if any. Passed through
            honestly rather than omitted — ``replace_profile`` refuses to
            overwrite an open profile, and defeating that guard by passing
            ``None`` would swap a database out from under a live connection.

    Raises:
        ResolutionError: on an unknown choice or a missing archive; nothing
            is changed.
        ProfileIsOpen: ``keep_remote`` on the open profile. Close it first.
        SafetyExportFailed: if the export cannot be taken or does not verify;
            nothing is changed.

    Note that ``keep_both`` and ``keep_local`` are safe with the profile
    open: neither touches the local database. Only the overwrite is gated,
    which keeps the common cases usable from Settings without a detour.
    """
    if choice not in CHOICES:
        raise ResolutionError(
            f"unknown choice {choice!r}; expected one of {', '.join(CHOICES)}")

    incoming = Path(incoming_archive)
    if not incoming.is_file():
        raise ResolutionError(f"the other side is not readable at {incoming}")

    if (
        choice == KEEP_REMOTE
        and active_user_id is not None
        and int(active_user_id) == int(user_id)
    ):
        raise ProfileIsOpen(
            "This profile is open, so it cannot be replaced yet. Switch to "
            "another profile (or the profile picker) and choose again — the "
            "other copy stays in the folder until you do."
        )

    # ---- the rule. Before anything, on every path, always. ----------------
    safety = take_safety_export(master_db, user_id, safety_dir)

    result = Resolution(choice=choice, safety_export=safety)
    directory = Path(safety_dir)

    if choice == KEEP_LOCAL:
        # This machine wins, and the other side is kept rather than dropped.
        # A student who chooses wrong at 1am must be able to change their mind.
        aside = directory / f"wimi-other-side-{_timestamp()}.wimi"
        shutil.copy2(str(incoming), str(aside))
        _verify_archive(aside, expect_entries=None)
        result.set_aside_path = str(aside)
        result.notes.append(
            "This device's copy was kept. The other copy was not deleted — it "
            "is saved beside the backup and can still be installed.")
        return result

    if choice == KEEP_BOTH:
        installed = install_profile_as_new(master_db, incoming)
        result.installed_user_id = installed.get("user_id")
        result.installed_username = installed.get("username")
        result.installed_profile_uuid = installed.get("profile_uuid")
        result.installed_profile_must_not_sync = True
        result.notes.append(
            f"Both copies were kept. The other one is now a separate profile "
            f"named {result.installed_username!r}.")
        result.notes.append(
            "Only this device's original profile stays linked to the sync "
            "folder. The new copy carries the same profile id, so linking it "
            "to the same folder would have the two publish into one history "
            "and fork against each other.")
        return result

    # ---- keep_remote -------------------------------------------------------
    try:
        replace_profile(
            master_db,
            incoming,
            target_user_id=user_id,
            active_user_id=active_user_id,
            confirm_replace=True,
            # A sync archive carries no media (#125). Without this the
            # replace renames the student's media aside, copies nothing in,
            # and deletes the aside copy on success -- every image gone.
            keep_existing_media=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise ResolutionError(
            f"the replace failed: {exc}. This device's copy is unchanged on "
            f"disk and a verified backup is at {safety.path}"
        ) from exc

    result.replaced_local = True
    result.notes.append(
        f"The other copy replaced this device's. The previous contents are "
        f"recoverable from {safety.path}.")
    return result


__all__ = [
    "KEEP_BOTH",
    "KEEP_LOCAL",
    "KEEP_REMOTE",
    "CHOICES",
    "ResolutionError",
    "ProfileIsOpen",
    "SafetyExportFailed",
    "SafetyExport",
    "Resolution",
    "take_safety_export",
    "resolve_fork",
]
