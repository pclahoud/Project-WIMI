#!/usr/bin/env python3
"""Two-machine folder-sync probe (#123). Run the same script on both devices.

Why a script and not a test
---------------------------
Everything folder sync does against a *plain local directory* is already
covered by 151 unit tests. What is not covered, and cannot be, is what a real
cloud client does to that directory: whether it syncs our extensions at all,
whether it evicts our files, what an evicted file looks like to ``os.stat``,
and how long a read of one takes. Those need real hardware, a real account and
two real machines, and the answers are *observations*, not assertions -- so
this prints findings rather than passing or failing.

It exists because comment #1503 ranked one of those answers as **inference**:
Box never documents its Windows API, and we deduced the Cloud Files API from
Box shipping ``C:\\Program Files\\Box\\Box\\FS\\cf\\cfctl.exe``. ``residency``
is written against that deduction. One run of ``probe.py residency`` confirms
or refutes it.

Safety
------
**This never touches a real profile.** ``--app-data`` is required, must not be
the repo's own ``app_data``, and the profile it seeds is created by this script
in that scratch directory. Free Box keeps one version and has **no trash
recovery**, so a clobbered file is simply gone -- which is also why
``--folder`` should be a subfolder you made for this, not the root of anyone's
Box.

Usage
-----
::

    # Once per machine, in this order.
    python scripts/foldersync_probe.py env      --app-data D:\\wimi-probe
    python scripts/foldersync_probe.py seed     --app-data D:\\wimi-probe
    python scripts/foldersync_probe.py link     --app-data D:\\wimi-probe \\
        --folder "C:\\Users\\you\\Box\\WIMI-sync-test" --provider box

    # Machine A publishes; machine B looks. Then swap.
    python scripts/foldersync_probe.py push     --app-data D:\\wimi-probe
    python scripts/foldersync_probe.py look     --app-data D:\\wimi-probe

    # The eviction question, without waiting 30 days: right-click the folder
    # in Explorer -> "Free up space", then:
    python scripts/foldersync_probe.py residency --app-data D:\\wimi-probe
    python scripts/foldersync_probe.py hydrate   --app-data D:\\wimi-probe

Every command prints a ``RESULT`` JSON blob on its last line so the output can
be pasted back verbatim and compared between machines.

Measuring on Box without destroying the measurement
---------------------------------------------------
Box streams by default, so a file that has just arrived from another device
is **cloud-only until something reads it** -- and reading it is a one-way
door. Two rules, both learned the hard way on 2026-09-21:

1.  **``discover`` and ``look`` read every manifest.** Since #147 neither
    hashes a blob that is not local, but both open each manifest, which on
    a streaming client fetches it -- and on 2026-09-21, before #147, both
    hashed whole blobs too, which is what burned the first specimen. So to
    measure an arrival without disturbing it, run ``residency`` FIRST,
    always, and poll by listing names only::

        python -c "import os,sys; print(sorted(os.listdir(sys.argv[1])))" "<segment>"

    ``os.listdir`` is measured not to open any file (see below). A graphical
    file manager is not safe: preview panes and thumbnailers open files.

2.  **In Streem mode, Box logs every open with its access mask**, per
    process, at
    ``%LOCALAPPDATA%/Box/Box/logs/Box_Streem_0_<date>.log`` (forward slashes
    here only so this docstring needs no escaping; Windows uses backslashes).
    That is how to prove a measurement was clean rather than assume it.
    **In Cloud Files mode the log stays empty** (measured 2026-09-22), and
    a clean measurement can only be shown by attributes -- a recall bit
    still set after the operation. ``env --folder`` says which mode.

    **``0x1`` means different things on a file and on a directory.** It is
    ``FILE_READ_DATA`` on a file but ``FILE_LIST_DIRECTORY`` on a directory,
    so the name-only poll legitimately logs ``desiredAccess: 0x100001`` on
    the *segment directory* every time. Judging by the bit alone flags every
    directory listing as a hydration. **Check the path first, then the bit.**

    Measured signatures on Box Drive 2.53.223 in Streem mode, both machines:

    =====================  ==============================================
    ``os.stat``            ``0x100080`` SYNCHRONIZE | FILE_READ_ATTRIBUTES,
                           no ``onReadFile``, no download. Cannot hydrate.
    a real read            ``0x120089`` + ``onReadFile`` +
                           ``reportDownloadCompleteImpl
                           backgroundDownload: false``
    =====================  ==============================================

Attribute readings, for decoding ``raw_st_file_attributes``. Box Drive has
two storage modes and can change between them with no update (#123 comment
#1951); ``env --folder`` reports which as ``box_mode``.

Streem mode (a mount point onto a FAT32-reporting virtual volume)::

    0x3000   OFFLINE | NOT_CONTENT_INDEXED    cloud-only          dataless
    0x2000   NOT_CONTENT_INDEXED              downloaded by Box   resident
    0x2020   ARCHIVE | NOT_CONTENT_INDEXED    written locally     resident

Cloud Files mode (a Cloud Files sync root)::

    0x400020 RECALL_ON_DATA_ACCESS | ARCHIVE  cloud-only          dataless
    0x20     ARCHIVE                          local               resident

Each mode sets exactly one residency bit the other never does -- OFFLINE in
Streem, RECALL_ON_DATA_ACCESS in Cloud Files -- which is why ``residency``
masks both. ``NOT_CONTENT_INDEXED`` is set in every Streem state and carries
no signal; ``ARCHIVE`` means nothing about residency in either mode.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

PROBE_USERNAME = "foldersync_probe"


# --------------------------------------------------------------------------- safety

def resolve_app_data(raw: str) -> Path:
    """A scratch app-data directory, and never the real one.

    The rule in CLAUDE.md is that real user data in ``app_data/`` is off
    limits; this makes that structural rather than a thing to remember at
    2am on the second machine.
    """
    path = Path(raw).expanduser().resolve()
    real = (REPO_ROOT / "app_data").resolve()
    if path == real or real in path.parents or path in real.parents:
        raise SystemExit(
            f"refusing to use {path}: it is inside (or contains) the repo's real "
            f"app_data. Pass a scratch directory, e.g. --app-data D:\\wimi-probe"
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def emit(label: str, payload: dict) -> None:
    """Print a human summary, then one machine-readable line."""
    print()
    print(f"RESULT {label}")
    print(json.dumps(payload, indent=2, default=str))


# --------------------------------------------------------------------------- windows facts

#: Reparse tags that tell Box's two storage modes apart (#123 comment #1951).
REPARSE_TAG_MOUNT_POINT = 0xA0000003
REPARSE_TAG_CLOUD = 0x9000001A
#: ``IO_REPARSE_TAG_CLOUD_MASK``: CLOUD, CLOUD_1 .. CLOUD_F differ only in
#: these bits. Box's sync root measured as ``0x9000701A`` (CLOUD_7) and its
#: files as ``0x9000401A`` (CLOUD_4) -- all one family.
REPARSE_TAG_CLOUD_MASK = 0x0000F000
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def reparse_meaning(tag) -> str:
    """A reparse tag, named."""
    if tag is None:
        return "unread"
    tag = int(tag)
    if tag == 0:
        return "none"
    if tag == REPARSE_TAG_MOUNT_POINT:
        return "IO_REPARSE_TAG_MOUNT_POINT"
    if tag & ~REPARSE_TAG_CLOUD_MASK == REPARSE_TAG_CLOUD:
        n = (tag & REPARSE_TAG_CLOUD_MASK) >> 12
        return "IO_REPARSE_TAG_CLOUD" + (f"_{n:X}" if n else "") + " (Cloud Files)"
    if tag == 0xA000000C:
        return "IO_REPARSE_TAG_SYMLINK"
    return "other"


def classify_box_mode(tag, sync_roots=None):
    """Which of Box Drive's two storage modes a folder is in: ``(mode, evidence)``.

    Box has **two**, and a machine can change between them with no update:
    measured on one machine and one version (2.53.223) twelve hours apart,
    2026-09-21/22 (#123 comment #1951).

    ``streem``
        The Box root is a mount point (``0xA0000003``) onto a virtual volume
        Box's driver presents, reporting FAT32. An evicted file is ``0x3000``
        -- OFFLINE, no recall flag. Box's Streem log records every open.
    ``cloud_files``
        The Box root is a Cloud Files sync root (a CLOUD-family tag) and
        registers in ``SyncRootManager``. An evicted file is ``0x400020`` --
        RECALL_ON_DATA_ACCESS, no OFFLINE. The Streem log stays empty.
    ``none``
        No reparse point anywhere between the folder and its drive root --
        not inside a streaming root at all.
    ``unknown``
        The tag could not be read, or is some other kind of reparse point.

    ``tag`` is the first reparse tag found walking up from the folder
    (``0`` for none found, ``None`` if it could not be read). ``sync_roots``
    is the ``SyncRootManager`` subkey count, used only to flag a
    contradiction -- never to decide, because it counts roots machine-wide
    and says nothing about *this* folder.
    """
    if tag is None:
        return "unknown", "the reparse tag could not be read"
    tag = int(tag)
    if tag == 0:
        return "none", "no reparse point between the folder and its drive root"
    if tag & ~REPARSE_TAG_CLOUD_MASK == REPARSE_TAG_CLOUD:
        evidence = f"Cloud Files reparse tag 0x{tag:08X}"
        if not sync_roots:
            evidence += "; but no SyncRootManager entry -- contradictory, check by hand"
        return "cloud_files", evidence
    if tag == REPARSE_TAG_MOUNT_POINT:
        evidence = "mount point onto another volume (Box's virtual volume)"
        if sync_roots:
            evidence += (f"; SyncRootManager has {sync_roots} entr"
                         f"{'y' if sync_roots == 1 else 'ies'}, from some other provider or a stale root")
        return "streem", evidence
    return "unknown", f"reparse tag 0x{tag:08X} ({reparse_meaning(tag)}) is neither mode"


def reparse_signal(info: dict):
    """What one directory's readings say: a tag, ``0`` for none, ``None`` for unreadable.

    **Any** source counts, because the Cloud Files filter hides the reparse
    point from most of them. Measured on a Windows 11 machine, 2026-09-22, on a
    live Box sync root that ``fsutil`` reports as ``0x9000701A``:

    ====================================  =================================
    ``GetFileAttributesW``                ``0x30`` -- reparse bit HIDDEN
    ``FSCTL_GET_REPARSE_POINT``           fails, 4390 NOT_A_REPARSE_POINT
    ``os.lstat``                          tag ``0x0``
    ``FindFirstFileW`` (parent listing)   ``0x430``, ``dwReserved0``
                                          ``0x9000701A`` -- the truth
    ====================================  =================================

    The listing is truthful only for the sync ROOT, because the root is
    listed from its parent, which sits outside the filter. Below the root
    even the listing reads ``0`` (``WIMI-lineage-test``: fsutil
    ``0x9000601A``, listing ``0``). So a walk upward must keep going past
    directories that read as plain, and it reaches the root.
    """
    bit = any(int(info.get(k) or 0) & FILE_ATTRIBUTE_REPARSE_POINT
              for k in ("attributes_raw", "find_attributes_raw"))
    tag = info.get("find_tag") or info.get("fsctl_tag") or 0
    if tag:
        return int(tag)
    return None if bit else 0


def _win_reparse_tag(path: str) -> dict:
    """Every reading of one directory's reparse point. Windows only; never raises.

    See :func:`reparse_signal` for why no single reading is trusted:
    ``GetFileAttributesW``, ``FSCTL_GET_REPARSE_POINT`` and ``os.lstat`` are
    all hidden from by the Cloud Files filter, and ``FindFirstFileW``'s
    ``dwReserved0`` (read from the parent's listing -- no handle on the
    object itself) is the one that told the truth, at the sync root.

    The FSCTL is still attempted when any source sees a reparse point, and
    its failure is kept: "a listing shows a tag while the FSCTL says 4390"
    is itself the signature of the filter at work.
    """
    import ctypes
    from ctypes import wintypes

    out: dict = {}
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    invalid = wintypes.HANDLE(-1).value

    get_attrs = k32.GetFileAttributesW
    get_attrs.argtypes = [wintypes.LPCWSTR]
    get_attrs.restype = wintypes.DWORD
    attrs = get_attrs(path)
    if attrs == 0xFFFFFFFF:
        out["attributes_error"] = f"GetFileAttributesW failed, GetLastError={ctypes.get_last_error()}"
    else:
        out["attributes_raw"] = int(attrs)

    find_first = k32.FindFirstFileW
    find_first.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.WIN32_FIND_DATAW)]
    find_first.restype = wintypes.HANDLE
    find_close = k32.FindClose
    find_close.argtypes = [wintypes.HANDLE]
    data = wintypes.WIN32_FIND_DATAW()
    handle = find_first(path, ctypes.byref(data))
    if handle in (None, invalid):
        out["find_error"] = f"FindFirstFileW failed, GetLastError={ctypes.get_last_error()}"
    else:
        try:
            out["find_attributes_raw"] = int(data.dwFileAttributes)
            if data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
                out["find_tag"] = int(data.dwReserved0)
        finally:
            find_close(handle)

    if not (out.get("find_tag") or any(
            int(out.get(k) or 0) & FILE_ATTRIBUTE_REPARSE_POINT
            for k in ("attributes_raw", "find_attributes_raw"))):
        return out

    create = k32.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    ioctl = k32.DeviceIoControl
    ioctl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                      wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                      wintypes.LPVOID]
    ioctl.restype = wintypes.BOOL
    close = k32.CloseHandle
    close.argtypes = [wintypes.HANDLE]

    FILE_READ_ATTRIBUTES = 0x80
    SHARE_ALL = 0x1 | 0x2 | 0x4
    OPEN_EXISTING = 3
    OPEN_REPARSE_POINT_AND_BACKUP = 0x00200000 | 0x02000000
    FSCTL_GET_REPARSE_POINT = 0x000900A8
    h = create(path, FILE_READ_ATTRIBUTES, SHARE_ALL, None, OPEN_EXISTING,
               OPEN_REPARSE_POINT_AND_BACKUP, None)
    if h in (None, invalid):
        out["fsctl_error"] = f"CreateFileW failed, GetLastError={ctypes.get_last_error()}"
        return out
    try:
        buf = ctypes.create_string_buffer(16 * 1024)   # MAXIMUM_REPARSE_DATA_BUFFER_SIZE
        returned = wintypes.DWORD()
        if ioctl(h, FSCTL_GET_REPARSE_POINT, None, 0, buf, len(buf),
                 ctypes.byref(returned), None) or returned.value >= 4:
            out["fsctl_tag"] = int.from_bytes(buf.raw[:4], "little")
        else:
            err = ctypes.get_last_error()
            out["fsctl_error"] = f"FSCTL_GET_REPARSE_POINT failed, GetLastError={err}" + (
                " (NOT_A_REPARSE_POINT: hidden by a filter)" if err == 4390 else "")
    finally:
        close(h)
    return out


def windows_cloud_facts(folder=None) -> dict:
    """What Windows itself says about the sync mechanism actually in play.

    Box Drive has two storage modes and can switch between them with no
    update (#123 comment #1951) -- see :func:`classify_box_mode`. ``box_mode``
    is the answer, with ``box_mode_evidence`` saying what it rests on; the
    rest are the raw facts behind it.

    ``box_cfctl_present`` is evidence of nothing on its own: Box ships
    ``FS\\cf\\cfctl.exe`` in both modes.

    Returns ``{}`` off Windows, and never raises: a probe that dies gathering
    context is worse than one that reports less of it.
    """
    facts: dict = {}
    if sys.platform != "win32":
        return facts

    try:
        import winreg
        sync_root = (r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                     r"\Explorer\SyncRootManager")
        for hive, label in ((winreg.HKEY_LOCAL_MACHINE, "hklm"),
                            (winreg.HKEY_CURRENT_USER, "hkcu")):
            try:
                key = winreg.OpenKey(hive, sync_root)
                try:
                    facts[f"cloud_files_sync_roots_{label}"] = winreg.QueryInfoKey(key)[0]
                finally:
                    winreg.CloseKey(key)
            except FileNotFoundError:
                facts[f"cloud_files_sync_roots_{label}"] = None
    except Exception as exc:
        facts["sync_root_error"] = str(exc)

    if not folder:
        facts["box_mode"] = "unknown"
        facts["box_mode_evidence"] = "no --folder given; the mode belongs to a folder, not a machine"
        return facts

    # Stage 2 runs `env` BEFORE the folder is created, so walk up to the
    # nearest existing ancestor rather than failing.
    probe_dir = Path(folder)
    while not probe_dir.exists() and probe_dir != probe_dir.parent:
        probe_dir = probe_dir.parent
    facts["nearest_existing"] = str(probe_dir)
    facts["requested_folder_exists"] = Path(folder).exists()

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        target = str(probe_dir)
        if not target.endswith("\\"):
            target += "\\"

        facts["drive_type"] = int(kernel32.GetDriveTypeW(ctypes.c_wchar_p(target)))
        facts["drive_type_meaning"] = {
            0: "unknown", 1: "no_root_dir", 2: "removable", 3: "fixed",
            4: "remote/network", 5: "cdrom", 6: "ramdisk",
        }.get(facts["drive_type"], "?")

        # GetVolumeInformationW wants a VOLUME ROOT, not any directory on it:
        # handed a subdirectory it fails with ERROR_DIR_NOT_ROOT (144). An
        # earlier version walked up only while the path did not exist, so as
        # soon as the sync folder was actually created it stopped there and
        # lost every volume field -- on precisely the machines that were set
        # up. GetVolumePathNameW is the API that answers "which volume is
        # this path on", and for a mount point like the Box root it returns
        # the mount point itself, which is what we want to describe.
        vol_root = ctypes.create_unicode_buffer(261)
        if kernel32.GetVolumePathNameW(ctypes.c_wchar_p(target), vol_root, 261):
            root = vol_root.value
        else:
            facts["volume_path_error"] = (
                f"GetVolumePathNameW failed, GetLastError={kernel32.GetLastError()}")
            root = target
        facts["volume_measured_at"] = root

        name = ctypes.create_unicode_buffer(261)
        fsname = ctypes.create_unicode_buffer(261)
        serial, maxlen, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        if kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), name, 261,
            ctypes.byref(serial), ctypes.byref(maxlen),
            ctypes.byref(flags), fsname, 261,
        ):
            facts["volume_label"] = name.value
            facts["filesystem"] = fsname.value
            facts["max_component_len"] = int(maxlen.value)
            facts["volume_flags"] = f"0x{int(flags.value):08X}"
        else:
            facts["volume_error"] = (
                f"GetVolumeInformationW failed on {root!r}, "
                f"GetLastError={kernel32.GetLastError()}")
    except Exception as exc:
        facts["volume_error"] = f"{type(exc).__name__}: {exc}"

    # The reparse tag is the discriminator between Box's two modes. Walk up
    # from the folder to the first reparse point, reading each directory with
    # Win32 calls that do NOT traverse cloud reparse points -- os.lstat does,
    # and reported "none" on a Cloud Files root (see _win_reparse_tag).
    tag = None
    try:
        probe = Path(folder)
        tag = 0
        while probe != probe.parent:
            if probe.exists():
                info = _win_reparse_tag(str(probe))
                signal = reparse_signal(info)
                if signal != 0:
                    facts["reparse_point_at"] = str(probe)
                    for key in ("attributes_raw", "find_attributes_raw"):
                        if key in info:
                            facts[f"reparse_{key[:-4]}"] = f"0x{info[key]:08X}"
                    for key in ("find_tag", "fsctl_tag"):
                        if info.get(key) is not None:
                            facts[f"reparse_{key}"] = f"0x{info[key]:08X}"
                    for key in ("attributes_error", "find_error", "fsctl_error"):
                        if key in info:
                            facts[f"reparse_{key}"] = info[key]
                    # Kept beside the real reading so the blind ones stay
                    # visible: in Cloud Files mode this reads 0x0.
                    facts["lstat_reparse_tag"] = (
                        f"0x{int(getattr(os.lstat(str(probe)), 'st_reparse_tag', 0)):08X}")
                    facts["reparse_hidden_from_attributes"] = bool(
                        signal and not (int(info.get("attributes_raw") or 0)
                                        & FILE_ATTRIBUTE_REPARSE_POINT))
                    tag = signal
                    facts["reparse_tag"] = f"0x{signal:08X}" if signal else None
                    facts["reparse_meaning"] = reparse_meaning(signal)
                    break
            probe = probe.parent
        else:
            facts["reparse_tag"] = None
    except Exception as exc:
        facts["reparse_error"] = f"{type(exc).__name__}: {exc}"
        tag = None

    facts["box_mode"], facts["box_mode_evidence"] = classify_box_mode(
        tag, facts.get("cloud_files_sync_roots_hklm"))
    return facts


# --------------------------------------------------------------------------- env

def cmd_env(args) -> int:
    """What this machine is, before anything is changed on it."""
    app_data = resolve_app_data(args.app_data)

    info = {
        "hostname": socket.gethostname(),
        "platform": sys.platform,
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        # A wrong-interpreter run is otherwise almost invisible: on one machine
        # the only difference was webengine 6.9.1 vs 6.9.2, and four package
        # "mismatches" that were really a system Python being read instead of
        # the venv. Reported first-class so a mis-launched probe is obvious.
        "executable": sys.executable,
        "prefix": sys.prefix,
        "in_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "app_data": str(app_data),
    }

    try:
        from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        info["qt"] = QT_VERSION_STR
        info["pyqt"] = PYQT_VERSION_STR
    except Exception as exc:
        info["qt_error"] = str(exc)

    try:
        from PyQt6.QtWebEngineCore import qWebEngineChromiumVersion, qWebEngineVersion
        info["chromium"] = qWebEngineChromiumVersion()
        info["webengine"] = qWebEngineVersion()
    except Exception as exc:
        info["chromium_error"] = str(exc)

    # #135 shipped Chromium 134 while every test ran 130. Record it here so a
    # disagreement between the two machines is visible before it costs a day.
    try:
        from database.master_db import MasterDatabase
        db = MasterDatabase(data_dir=app_data, error_logger=None)
        try:
            info["device_id"] = db.get_device_id()
            info["device_name"] = db.get_device_name()
        finally:
            db.close()
    except Exception as exc:
        info["device_error"] = str(exc)

    # Box ships cfctl.exe in BOTH of its modes, so its presence says nothing
    # about which one this machine is in -- read box_mode for that. Kept
    # because the first round's wrong deduction started here, and the field
    # being present in old reports is how that history stays legible.
    if sys.platform == "win32":
        info["box_cfctl_present"] = Path(
            r"C:\Program Files\Box\Box\FS\cf\cfctl.exe").is_file()
    # Self-guarding: returns {} off Windows, so no platform test here.
    info.update(windows_cloud_facts(getattr(args, "folder", None)))

    emit("env", info)
    return 0


# --------------------------------------------------------------------------- seed

def _open_master(app_data: Path):
    from database.master_db import MasterDatabase
    return MasterDatabase(data_dir=app_data, error_logger=None)


def _probe_user(master):
    return master.get_user(username=PROBE_USERNAME)


def cmd_seed(args) -> int:
    """Add a session of entries to the throwaway profile, creating it if needed.

    **Re-runnable, and that is the point.** Generating a fork means each
    device must add work of its own between pushes, so this gets called more
    than once on one app-data.

    It used to insert an exam named ``Probe <hostname> <date>`` every time
    and die on the second run of the same day against
    ``UNIQUE (user_id, exam_name)`` -- which is exactly when it is wanted,
    and which cost a live two-machine test its window. The exam is now
    reused when it already exists and only the session and entries are new.

    Why not make the name unique per run instead: a profile accumulating one
    exam context per invocation is not what any student's data looks like,
    and the archive stats that #124's fork report reads would then measure
    the probe rather than the shape of a real profile.
    """
    from database.user_db import UserDatabase

    app_data = resolve_app_data(args.app_data)
    master = _open_master(app_data)
    try:
        user = _probe_user(master)
        if user is None:
            user = master.create_user(
                username=PROBE_USERNAME, display_name="Folder sync probe")

        db_path = master.ensure_user_database(user.id)
        db = UserDatabase(db_path=db_path, user_id=user.id,
                          username=user.username,
                          device_id=master.get_device_id())
        try:
            exam_name = f"Probe {socket.gethostname()} {date.today()}"
            with db.transaction():
                row = db.execute(
                    "SELECT id FROM exam_contexts WHERE user_id = ? AND exam_name = ?",
                    (user.id, exam_name),
                ).fetchone()
                if row is not None:
                    exam_id = row[0]
                else:
                    cur = db.execute(
                        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                        (user.id, exam_name),
                    )
                    exam_id = cur.lastrowid
                cur = db.execute(
                    "INSERT INTO review_sessions "
                    "(user_id, exam_context_id, total_questions, total_incorrect) "
                    "VALUES (?, ?, ?, ?)",
                    (user.id, exam_id, 10, args.entries),
                )
                session_id = cur.lastrowid
                start = db.execute(
                    "SELECT COUNT(*) FROM question_entries").fetchone()[0]
                for i in range(start + 1, start + 1 + args.entries):
                    db.execute(
                        "INSERT INTO question_entries "
                        "(review_session_id, entry_order, user_answer, correct_answer) "
                        "VALUES (?, ?, ?, ?)",
                        (session_id, i, f"a{i}", f"c{i}"),
                    )
            total = db.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
            sessions = db.execute("SELECT COUNT(*) FROM review_sessions").fetchone()[0]
            profile_uuid = db.get_profile_uuid()
        finally:
            db.close()
        master.record_profile_uuid(user.id, profile_uuid)

        emit("seed", {
            "user_id": user.id,
            "profile_uuid": profile_uuid,
            "entries_added": args.entries,
            "entries_total": total,
            "sessions_total": sessions,
            "device_id": master.get_device_id(),
        })
    finally:
        master.close()
    return 0


# --------------------------------------------------------------------------- sync

def _sync(app_data: Path, *, required: bool = True):
    """Open the registry and the sync service.

    ``required=False`` for the read-only commands, because the receiving
    machine legitimately has no profile of its own when it first looks at a
    folder -- and demanding one there would force a fetch, which would read
    the files and destroy the very measurement we came for.
    """
    from app.foldersync import ProfileFolderSync
    master = _open_master(app_data)
    user = _probe_user(master)
    if user is None and required:
        master.close()
        raise SystemExit("no probe profile yet -- run `seed` on this machine first")
    return master, user, ProfileFolderSync(master, timeout_s=60.0)


def cmd_link(args) -> int:
    app_data = resolve_app_data(args.app_data)
    master, user, sync = _sync(app_data)
    try:
        # What is already there, said out loud before committing to it.
        found = sync.discover(args.folder, args.provider)
        link = sync.link(user.id, args.folder, args.provider)
        emit("link", {
            "folder": link.folder,
            "provider": link.provider_id,
            "sync_id": link.sync_id,
            "already_in_folder": found,
        })
    finally:
        master.close()
    return 0


def cmd_push(args) -> int:
    app_data = resolve_app_data(args.app_data)
    master, user, sync = _sync(app_data)
    try:
        started = time.monotonic()
        result = sync.push(user.id)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        emit("push", {
            "generation": result.generation,
            "parent_generation": result.parent_generation,
            "blob": result.blob_name,
            "manifest": result.manifest_name,
            "bytes": result.bytes,
            "elapsed_ms": elapsed_ms,
            "device_id": master.get_device_id(),
        })
    finally:
        master.close()
    return 0


def cmd_look(args) -> int:
    """What is in the folder now -- the other machine's generation, or not yet.

    'Nothing new' and 'the other device has not uploaded yet' are the same
    observation from here, which is the whole reason the UI never draws a
    tick. This prints what was seen and when, and nothing more.
    """
    app_data = resolve_app_data(args.app_data)
    master, user, sync = _sync(app_data)
    try:
        started = time.monotonic()
        status = sync.status(user.id)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        emit("look", {
            "elapsed_ms": elapsed_ms,
            "head_generation": status.head_generation,
            "head_device": status.head_device,
            "head_created_at": status.head_created_at,
            # After #147 detection no longer proves the head's bytes are
            # sound: a head whose blob is still in the cloud is reported
            # unverified rather than downloaded to check.
            "head_verified": status.head_verified,
            "last_pushed_generation": status.last_pushed_generation,
            # #148/#149: where this copy stands, and any unsent choice.
            # base_relation 'superseded' is the losing side of a choice made
            # on the other machine -- the thing the owner required be said.
            "base_generation": status.base_generation,
            "base_relation": status.base_relation,
            "relation_detail": status.relation_detail,
            "pending": status.pending,
            "pending_state": status.pending_state,
            "rejected": status.rejected,
            "forks": status.forks,
            "conflict_copies": status.conflict_copies,
            "problems": status.problems,
        })
    finally:
        master.close()
    return 0


def cmd_fetch(args) -> int:
    """Stage and verify the newest generation. Installs nothing."""
    app_data = resolve_app_data(args.app_data)
    master, user, sync = _sync(app_data)
    try:
        started = time.monotonic()
        result = sync.fetch(user.id)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        emit("fetch", {
            "generation": result.generation,
            "elapsed_ms": elapsed_ms,
            "schema_verdict": result.schema_verdict,
            "schema_reason": result.schema_reason,
            "blocked": result.blocked,
            "summary": result.summary,
            "skipped": [
                {"generation": f.generation, "reason": f.reason}
                for f in result.skipped
            ],
        })
    finally:
        master.close()
    return 0


def cmd_discover(args) -> int:
    """What profiles live in a folder, without linking to it.

    Works on a machine that holds none of them. ``local_profiles`` is empty
    there, which is the honest answer and the one the receiving device sees
    first.
    """
    from app.foldersync import ProfileFolderSync

    app_data = resolve_app_data(args.app_data)
    master = _open_master(app_data)
    try:
        sync = ProfileFolderSync(master, timeout_s=60.0)
        started = time.monotonic()
        found = sync.discover(args.folder, args.provider)
        emit("discover", {
            "folder": args.folder,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "found": found,
        })
    finally:
        master.close()
    return 0


def cmd_pull(args) -> int:
    """Verify and stage a generation from a folder this machine has no link to.

    This is #123's headline acceptance criterion: *a profile pushed on device
    A appears on device B, byte-identical, verified by SHA-256*. No local
    profile is needed -- ``fetch_from`` resolves the head, checks the blob's
    digest against its manifest, stages it, and runs the existing schema
    preflight. Nothing is installed unless ``--install`` is passed.
    """
    from app.foldersync import ProfileFolderSync

    app_data = resolve_app_data(args.app_data)
    master = _open_master(app_data)
    try:
        sync = ProfileFolderSync(master, timeout_s=args.timeout)
        started = time.monotonic()
        result = sync.fetch_from(args.folder, args.sync_id, args.provider)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)

        payload = {
            "generation": result.generation,
            "elapsed_ms": elapsed_ms,
            "schema_verdict": result.schema_verdict,
            "schema_reason": result.schema_reason,
            "blocked": result.blocked,
            "summary": result.summary,
            "archive_path": result.archive_path,
            "skipped": [
                {"generation": f.generation, "reason": f.reason}
                for f in result.skipped
            ],
        }

        if args.install and not result.blocked:
            from app.profile_archive import install_profile_as_new
            installed = install_profile_as_new(master, Path(result.archive_path))
            # What this machine now holds descends from that generation, and
            # only this machine can say so (#149). Without it the installed
            # profile's first push is a root, and both machines are told
            # their copies share no history.
            sync.record_install(int(installed["user_id"]), args.sync_id, result.manifest)
            payload["installed"] = {
                "user_id": installed.get("user_id"),
                "username": installed.get("username"),
                "profile_uuid": installed.get("profile_uuid"),
                "already_installed_as": installed.get("already_installed_as"),
            }
        emit("pull", payload)
    finally:
        master.close()
    return 0


def cmd_fork_report(args) -> int:
    """Find a fork and compare its two sides (#124).

    **This downloads both sides.** Deliberate, and the opposite of #147's
    decision for status: looking at a folder happens constantly and must be
    free, while choosing between two copies of your profile is a deliberate
    act and there is no honest answer without reading both.

    Prints the four figures per side that make the choice answerable --
    entries, date range, device and when it wrote, and the subjects unique
    to that side. ``compared: false`` means a side could not be read, and
    the empty "only here" lists then mean NOBODY LOOKED rather than "the two
    agree". Those are different states and the output keeps them apart.
    """
    app_data = resolve_app_data(args.app_data)
    master, user, sync = _sync(app_data)
    try:
        started = time.monotonic()
        report = sync.fork_report(user.id)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        if report is None:
            emit("fork-report", {"elapsed_ms": elapsed_ms, "fork": None,
                                 "note": "no fork -- the ordinary case"})
            return 0
        payload = report.to_dict()
        payload["elapsed_ms"] = elapsed_ms
        emit("fork-report", payload)
    finally:
        master.close()
    return 0


def cmd_resolve(args) -> int:
    """Apply a choice to a fork, behind an unconditional verified export (#124).

    ``--blob-name`` names the side, not a generation: the two sides of a
    fork normally share a generation number, so a number cannot say which
    one was chosen.

    ``active_user_id`` is None here because the probe holds no open
    profile -- it is not the app. In the app the bridge closes and reopens
    the profile around ``keep_remote`` (#148).

    **Nothing is sent** (#148). The choice applies to this machine and is
    recorded as pending; ``push`` sends it. The output says whether a send
    is needed at all -- taking the folder's only copy needs none.
    """
    from app.foldersync.resolution import resolve_fork

    app_data = resolve_app_data(args.app_data)
    safety = Path(args.safety_dir) if args.safety_dir else (app_data / "foldersync" / "safety")
    master, user, sync = _sync(app_data)
    try:
        link = sync.state.get_link(user.id)
        if link is None:
            raise SystemExit("not linked -- run `link` first")

        started = time.monotonic()
        staged = sync.stage_for_resolution(
            link, args.blob_name, sync._device_identity().device_id)
        staged_ms = round((time.monotonic() - started) * 1000, 1)

        started = time.monotonic()
        result = resolve_fork(
            master,
            user_id=user.id,
            choice=args.choice,
            incoming_archive=staged["archive_path"],
            safety_dir=safety,
            active_user_id=None,
        )
        send = sync.finish_resolution(user.id, args.choice, staged, result)
        payload = result.to_dict()
        payload["send_needed"] = send["send_needed"]
        payload["pending"] = send["pending"]
        payload["staged_from"] = staged["archive_path"]
        payload["stage_ms"] = staged_ms
        payload["resolve_ms"] = round((time.monotonic() - started) * 1000, 1)
        emit("resolve", payload)
    finally:
        master.close()
    return 0


# --------------------------------------------------------------------------- residency

def _sync_dir_for(folder: str, sync_id: str) -> Path:
    from app.foldersync.naming import ROOT_DIR_NAME
    return Path(folder) / ROOT_DIR_NAME / sync_id


def _target(args, sync, user):
    """Which folder segment to look at -- from the link, or named explicitly.

    The second device has **no link and no copy of the profile** when it first
    looks, so every read-only command has to work unlinked. That is not a
    convenience: it is the only way to measure an arrived file *before*
    anything reads it, and reading it is what hydrates it. ``fetch_from``
    needs no local profile either, which is what makes the byte-identical
    check possible on a machine that has never seen this profile.
    """
    if args.folder and args.sync_id:
        return str(Path(args.folder)), str(args.sync_id), str(args.provider)
    link = sync.state.get_link(user.id) if user is not None else None
    if link is None:
        raise SystemExit(
            "not linked, and no --folder/--sync-id given. On the receiving "
            "machine pass both: run `discover --folder ...` to see what is there."
        )
    return link.folder, link.sync_id, link.provider_id


def cmd_residency(args) -> int:
    """Inspect every file WITHOUT reading it, and so without hydrating it.

    This is the measurement comment #1503 asked for. On Windows a
    ``determinate: true`` with ``dataless: true`` after 'Free up space'
    confirms Box uses the Cloud Files API; ``determinate: false`` means
    ``st_file_attributes`` was absent and our detection is blind on this
    Python. Either answer is worth having -- the second would mean the
    hydration guard never fires on Windows.
    """
    from app.foldersync.hydration import residency

    app_data = resolve_app_data(args.app_data)
    master, user, sync = _sync(app_data, required=False)
    try:
        f, sid, _prov = _target(args, sync, user)
        folder = _sync_dir_for(f, sid)
        files = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
        emit("residency", {
            "sync_dir": str(folder),
            "platform": sys.platform,
            "files": [
                {
                    "name": p.name,
                    **{k: v for k, v in vars(residency(p)).items() if k != "path"},
                    "raw_st_file_attributes": getattr(
                        os.stat(str(p)), "st_file_attributes", None),
                    "raw_st_flags": getattr(os.stat(str(p)), "st_flags", None),
                }
                for p in files
            ],
        })
    finally:
        master.close()
    return 0


def cmd_hydrate(args) -> int:
    """Read every file with the bounded reader, and time it.

    Run straight after 'Free up space'. A long first read and a short second
    is Box materialising on open, which is the behaviour the whole hydration
    layer is built around.
    """
    from app.foldersync.hydration import residency, sha256_bounded

    app_data = resolve_app_data(args.app_data)
    master, user, sync = _sync(app_data, required=False)
    try:
        f, sid, _prov = _target(args, sync, user)
        folder = _sync_dir_for(f, sid)
        readings = []
        for p in sorted(x for x in folder.iterdir() if x.is_file()):
            before = residency(p)
            started = time.monotonic()
            try:
                digest = sha256_bounded(p, timeout_s=args.timeout)
                error = None
            except Exception as exc:
                digest, error = None, f"{type(exc).__name__}: {exc}"
            first_ms = round((time.monotonic() - started) * 1000, 1)

            started = time.monotonic()
            try:
                sha256_bounded(p, timeout_s=args.timeout)
            except Exception:
                pass
            second_ms = round((time.monotonic() - started) * 1000, 1)

            readings.append({
                "name": p.name,
                "dataless_before": before.dataless,
                "determinate": before.determinate,
                "first_read_ms": first_ms,
                "second_read_ms": second_ms,
                "sha256": digest[:16] + "..." if digest else None,
                "error": error,
            })
        emit("hydrate", {"sync_dir": str(folder), "timeout_s": args.timeout,
                         "readings": readings})
    finally:
        master.close()
    return 0


# --------------------------------------------------------------------------- names

def cmd_names(args) -> int:
    """Would this folder's paths survive Box's rules?

    Box's path limit is 255 characters and applies to the PATH, not the name,
    so a deep user-chosen folder plus a 36-character uuid plus a device name
    is a realistic way to breach it. Checking at folder-pick time is a
    property of the choice; this reports it for a real prefix.
    """
    from app.foldersync import naming
    from app.foldersync.providers import get_provider

    app_data = resolve_app_data(args.app_data)
    master, user, sync = _sync(app_data)
    try:
        link = sync.state.get_link(user.id)
        folder = link.folder if link else args.folder
        sync_id = link.sync_id if link else "0" * 36
        provider = get_provider(args.provider if not link else link.provider_id)
        identity = sync._device_identity()
        # Pass the real device id: the name carries 8 hex characters of it,
        # so budgeting without it understates the path by 9 and could wave
        # through a folder that is actually over Box's 255-character limit.
        blob = naming.blob_name(identity.slug, 9999, identity.device_id)
        manifest = naming.manifest_name(identity.slug, 9999, identity.device_id)
        longest = str(Path(folder) / naming.ROOT_DIR_NAME / sync_id / blob)
        emit("names", {
            "folder": folder,
            "device_slug": identity.slug,
            "device_tag": naming.device_tag(identity.device_id),
            "example_blob": blob,
            "example_manifest": manifest,
            "longest_path": longest,
            "longest_path_chars": len(longest),
            "provider_max_path_chars": provider.max_path_chars,
            "over_budget": bool(provider.max_path_chars
                                and len(longest) > provider.max_path_chars),
            "blocked_extensions": sorted(provider.blocked_extensions),
        })
    finally:
        master.close()
    return 0


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--app-data", required=True,
                        help="scratch app-data directory; never the real one")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn, needs_folder in (
        ("env", cmd_env, False),
        ("seed", cmd_seed, False),
        ("link", cmd_link, True),
        ("push", cmd_push, False),
        ("look", cmd_look, False),
        ("fetch", cmd_fetch, False),
        ("discover", cmd_discover, True),
        ("pull", cmd_pull, True),
        ("fork-report", cmd_fork_report, False),
        ("resolve", cmd_resolve, False),
        ("residency", cmd_residency, False),
        ("hydrate", cmd_hydrate, False),
        ("names", cmd_names, False),
    ):
        p = sub.add_parser(name, help=(fn.__doc__ or "").strip().split("\n")[0])
        p.set_defaults(func=fn)
        if needs_folder:
            p.add_argument("--folder", required=True,
                           help="the cloud-synced folder (make a subfolder for this)")
        else:
            p.add_argument("--folder", default=None)
        p.add_argument("--provider", default="box")
        # The receiving machine names the segment explicitly: it has no link,
        # and must be able to look before it reads.
        p.add_argument("--sync-id", default=None,
                       help="profile uuid naming the folder segment; "
                            "required on a machine with no link")
        if name == "seed":
            p.add_argument("--entries", type=int, default=25)
        if name in ("hydrate", "pull"):
            p.add_argument("--timeout", type=float, default=120.0)
        if name == "resolve":
            p.add_argument("--choice", required=True,
                           choices=("keep_both", "keep_local", "keep_remote"))
            p.add_argument("--blob-name", required=True,
                           help="the chosen SIDE. Not a generation number: "
                                "both sides of a fork usually share one")
            p.add_argument("--safety-dir", default=None,
                           help="where the pre-flight export goes; defaults "
                                "inside --app-data, never the sync folder")
        if name == "pull":
            p.add_argument("--install", action="store_true",
                           help="also install the verified archive as a new "
                                "profile (off by default: verifying is the "
                                "acceptance criterion, installing is extra)")

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        from console_encoding import configure_stdio
        configure_stdio()
    except Exception:
        pass
    sys.exit(main())
