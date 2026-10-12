"""Load the newest Microsoft C++ runtime before Qt can load an older one (#367).

The defect
----------
On Windows a process holds ONE ``msvcp140.dll``, and whichever library loads
first decides which. The ``PyQt6-Qt6`` wheel ships its own copy in
``PyQt6/Qt6/bin`` at **14.26.28720.3** (the 2020 toolset); torch 2.14.1 ships
none and needs a newer one. So once Qt is in the process, torch's ``c10.dll``
fails its initialisation::

    from PyQt6 import QtCore; import torch
    OSError: [WinError 1114] A dynamic link library (DLL) initialization
    routine failed. Error loading "...\\torch\\lib\\c10.dll" ...

WIMI always loads Qt before any relation-extraction code can run, so on Windows
the relations runtime could not import torch at all. Measured on Windows machine B
(Python 3.13.15, PyQt6-Qt6 6.9.2, torch 2.14.1+cpu) with
``GetModuleHandle``/``GetModuleFileName``:

    after `from PyQt6 import QtCore`:  msvcp140.dll = ...\\PyQt6\\Qt6\\bin\\MSVCP140.dll
    after `import torch` first:        msvcp140.dll = C:\\Windows\\SYSTEM32\\msvcp140.dll (14.50)

macOS and Linux have no MSVC runtime, which is why the MacBook could not see
this.

The fix
-------
Before anything imports Qt, load the newest ``msvcp140.dll`` available. Qt's
own DLLs then bind to it by name. The direction matters: a v14 binary built
against 14.26 runs on 14.50, and the reverse is not supported. So this always
loads the NEWEST available copy, never Qt's.

* **Frozen, it looks only inside the bundle** (``sys._MEIPASS``), never in
  ``System32``. A clean Windows has no Visual C++ redistributable (#158), so a
  bundle that reaches into System32 works on every developer machine and fails
  on a student's. ``wimi.spec`` already stages the System32 copy beside
  whisper-cli.exe for #158, so the bundle carries a new enough one.
* **Only where the relations runtime is meant to exist.** In a frozen build
  that is ``sys._wimi_relations_build``, the build's recorded intent (see
  ``packaging/rthook_relations_build.py``). In a checkout it is "torch can be
  found", via ``find_spec``, which executes nothing. The default artifact never
  calls the loader at all. That checkout rule is a decision, not a side
  effect, so stated plainly: **a developer whose venv has
  requirements-relations.txt installed runs every WIMI process on the
  System32 runtime family; one without it runs on Qt's, exactly as before.**
  The relations dev case cannot use ``availability.is_relations_build()``,
  which is False in every checkout by design, and preloading for every
  developer would change everyone's runtime for a feature most have not
  installed.
* **It never stops WIMI starting.** Every failure is caught and recorded in
  :func:`last_result`. A machine where this cannot be satisfied loses the
  relations feature, which is what ``RUNTIME_BROKEN`` and ``MODEL_LOAD_FAILED``
  are for. It does not lose the app.

This module imports ``ctypes``, ``os`` and the standard library only, and
nothing from ``app.relation_extraction``. ``scripts/check_relations_runtime_imports.py``
rule 2 forbids importing that package at module scope from outside it, and the
helper is about the C runtime, not about relations, so it lives here.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

DLL_NAME = 'msvcp140.dll'

#: The rest of the C++ runtime family, loaded from the SAME directory as the
#: chosen ``msvcp140.dll`` when that directory has them. Microsoft versions and
#: ships these as one set -- ``msvcp140_1``/``_2`` exist to carry newer exports
#: while ``msvcp140``'s stay stable -- so a 14.50 ``msvcp140`` beside Qt's
#: 14.26 ``msvcp140_1`` is a combination nobody ships, even though it was
#: measured working. Loading the family from one source was measured too, on
#: Windows machine B from System32: Qt imports, a QWebEngineView loads and
#: renders, torch and GLiNER2 import, and all four resolve to System32.
#:
#: Where the directory lacks a satellite it is NOT looked for elsewhere --
#: mixing sources is the thing this avoids. The frozen bundle is that case
#: today: its 14.50 copies (``_internal\\``, ``whisper\\windows\\``) carry
#: ``msvcp140`` alone, so the satellites still come from Qt's folder there.
#: :attr:`PreloadResult.satellites` records which were loaded and which not.
SATELLITES = ('msvcp140_1.dll', 'msvcp140_2.dll', 'concrt140.dll')

#: Outcomes, as plain strings so they serialise and read the same in a log.
NOT_WINDOWS = 'not_windows'
NOT_NEEDED = 'not_needed'
LOADED = 'loaded'
ALREADY_LOADED = 'already_loaded'
NONE_FOUND = 'none_found'
FAILED = 'failed'

Version = tuple[int, int, int, int]


@dataclass(frozen=True)
class PreloadResult:
    """What happened, with enough detail to diagnose it on another machine."""

    status: str
    #: The DLL now holding the name in this process, when known.
    path: Optional[str] = None
    version: Optional[Version] = None
    #: Every copy that was considered, with its file version.
    candidates: tuple[tuple[str, Optional[Version]], ...] = field(default=())
    detail: str = ''
    #: Each satellite and what happened to it: the path loaded, or why not
    #: ('absent', 'already loaded: <path>', 'failed: <error>').
    satellites: tuple[tuple[str, str], ...] = field(default=())

    def describe(self) -> str:
        ver = '.'.join(map(str, self.version)) if self.version else '?'
        if self.status in (LOADED, ALREADY_LOADED):
            text = f'{self.status}: {DLL_NAME} {ver} from {self.path}'
            if self.satellites:
                loaded = sum(1 for _, what in self.satellites
                             if not what.startswith(('absent', 'already', 'failed')))
                text += f' (+{loaded}/{len(self.satellites)} of its family)'
            return text
        return f'{self.status}: {self.detail}' if self.detail else self.status


_last_result: Optional[PreloadResult] = None
# Holds the loaded handle for the life of the process. A DLL whose last
# reference is dropped can be unloaded, and that would undo the whole point.
_keep_alive: list = []


def last_result() -> Optional[PreloadResult]:
    """The outcome of the most recent :func:`preload_newest`, or ``None``."""
    return _last_result


def should_preload() -> bool:
    """Is the relation-extraction runtime meant to be in this process?"""
    if getattr(sys, 'frozen', False):
        return bool(getattr(sys, '_wimi_relations_build', False))
    try:
        return importlib.util.find_spec('torch') is not None
    except (ImportError, ValueError):
        return False


def _search_dirs() -> list[Path]:
    """Where a copy may live, in no particular order of preference.

    Preference is by FILE VERSION, never by directory, so the order here does
    not decide anything.
    """
    if getattr(sys, 'frozen', False):
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        return [
            base,
            base / 'PyQt6' / 'Qt6' / 'bin',
            base / 'torch' / 'lib',
            base / 'whisper' / 'windows',
        ]
    dirs = [Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32']
    for package, sub in (('PyQt6', ('Qt6', 'bin')), ('torch', ('lib',))):
        try:
            spec = importlib.util.find_spec(package)
        except (ImportError, ValueError):
            spec = None
        if spec and spec.submodule_search_locations:
            dirs.append(Path(list(spec.submodule_search_locations)[0]).joinpath(*sub))
    return dirs


def file_version(path: Path) -> Optional[Version]:
    """The PE file version of *path*, or ``None`` if it cannot be read."""
    import ctypes
    from ctypes import wintypes

    ver = ctypes.WinDLL('version', use_last_error=True)
    ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, wintypes.LPDWORD]
    ver.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    ver.VerQueryValueW.argtypes = [
        wintypes.LPCVOID, wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.UINT)]

    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    ptr = wintypes.LPVOID()
    length = wintypes.UINT()
    if not ver.VerQueryValueW(buf, '\\', ctypes.byref(ptr), ctypes.byref(length)):
        return None
    # VS_FIXEDFILEINFO: dwSignature, dwStrucVersion, dwFileVersionMS,
    # dwFileVersionLS, ...
    fixed = ctypes.cast(ptr, ctypes.POINTER(wintypes.DWORD * 4)).contents
    ms, ls = fixed[2], fixed[3]
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def loaded_copy(name: str = DLL_NAME) -> Optional[str]:
    """The full path of the *name* DLL already in this process, if any."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k32.GetModuleHandleW.restype = wintypes.HMODULE
    k32.GetModuleFileNameW.argtypes = [
        wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    handle = k32.GetModuleHandleW(name)
    if not handle:
        return None
    buf = ctypes.create_unicode_buffer(1024)
    k32.GetModuleFileNameW(handle, buf, len(buf))
    return buf.value


def _load(path: str):
    import ctypes
    return ctypes.WinDLL(path)


def preload_newest(
    *,
    force: bool = False,
    search_dirs: Optional[list[Path]] = None,
    version_of: Callable[[Path], Optional[Version]] = file_version,
    already_loaded: Callable[[str], Optional[str]] = loaded_copy,
    load: Callable[[str], object] = _load,
) -> PreloadResult:
    """Load the newest ``msvcp140.dll`` found, unless one is already loaded.

    Never raises. The keyword arguments after ``force`` exist so the decision
    logic can be tested on any platform; production callers pass none of them.

    *force* skips :func:`should_preload`, for ``scripts/check_build_env.py``,
    which knows from its own flag that it is checking the relations runtime.
    """
    global _last_result
    # Idempotent once it has worked. A frozen relations build calls this
    # twice -- from packaging/rthook_relations_build.py, which is early
    # enough, and again from app.main.main(), which in a bundle is not (Qt's
    # runtime hook has loaded Qt by then). The second call would otherwise
    # report ALREADY_LOADED and overwrite the result that says what happened.
    if _last_result is not None and _last_result.status == LOADED:
        return _last_result
    try:
        result = _preload(force, search_dirs, version_of, already_loaded, load)
    except Exception as exc:  # noqa: BLE001 -- must never stop startup
        result = PreloadResult(FAILED, detail=f'{type(exc).__name__}: {exc}')
    _last_result = result
    return result


def _preload(force, search_dirs, version_of, already_loaded, load) -> PreloadResult:
    if sys.platform != 'win32':
        return PreloadResult(NOT_WINDOWS)
    if not force and not should_preload():
        return PreloadResult(NOT_NEEDED)

    present = already_loaded(DLL_NAME)
    if present:
        # Too late to choose: the name is taken for this process. Report what
        # holds it so a diagnosis does not have to guess.
        return PreloadResult(
            ALREADY_LOADED, path=present, version=version_of(Path(present)),
            detail='another library loaded it first')

    candidates = []
    for directory in (search_dirs if search_dirs is not None else _search_dirs()):
        path = directory / DLL_NAME
        if path.is_file():
            candidates.append((str(path), version_of(path)))
    found = tuple(candidates)
    versioned = [(p, v) for p, v in found if v is not None]
    if not versioned:
        return PreloadResult(
            NONE_FOUND, candidates=found,
            detail=f'no readable {DLL_NAME} in the searched directories')

    # max() keeps the first of equal versions, so ties go to the earlier dir.
    best_path, best_version = max(versioned, key=lambda pv: pv[1])
    try:
        _keep_alive.append(load(best_path))
    except OSError as exc:
        return PreloadResult(
            FAILED, path=best_path, version=best_version, candidates=found,
            detail=f'{type(exc).__name__}: {exc}')

    # The satellites import msvcp140, so they come after it, and only from
    # its own directory (see SATELLITES). A satellite that fails is recorded,
    # not fatal: msvcp140 itself -- the one torch needs -- is already in.
    satellites = []
    home = Path(best_path).parent
    for name in SATELLITES:
        held = already_loaded(name)
        path = home / name
        if held:
            satellites.append((name, f'already loaded: {held}'))
        elif not path.is_file():
            satellites.append((name, 'absent'))
        else:
            try:
                _keep_alive.append(load(str(path)))
                satellites.append((name, str(path)))
            except OSError as exc:
                satellites.append((name, f'failed: {type(exc).__name__}: {exc}'))
    return PreloadResult(
        LOADED, path=best_path, version=best_version, candidates=found,
        satellites=tuple(satellites))
