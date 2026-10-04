"""The MSVC runtime must ship BESIDE whisper-cli.exe, not just in the bundle (#158).

whisper.cpp's Windows release ships no C runtime. `dumpbin /dependents` over
all 13 vendored PE files: `ggml-base.dll` and the nine `ggml-cpu-*.dll` import
**VCOMP140** (OpenMP), and `whisper-cli.exe` itself imports `MSVCP140`,
`VCRUNTIME140` and `VCRUNTIME140_1`.

PyInstaller's `_win_includes` permits collecting all four off the build host,
and it does — **to the bundle's top level**. That is not the fix, because
Windows resolves a subprocess's imports from the directory holding the
executable, and `src/app/stt/runtime.py` launches `whisper-cli.exe` with no
`cwd`, no `env` and no `add_dll_directory`.

Measured in Windows Sandbox on 2026-09-24, a Windows with no Visual C++
redistributable installed or registered:

    15 vendored files only:   exit -1073741515 (0xC0000135,
                              STATUS_DLL_NOT_FOUND), stdout 0 bytes,
                              stderr 0 bytes
    + the four DLLs beside:   exit 0, "whisper.cpp version: 1.9.4"

Both streams empty because the loader refuses the image before `main()`. The
student's whole diagnostic is `whisper-cli exited -1073741515:` followed by
nothing, so this fails in the least debuggable way available.

Every development machine has the redistributable in System32, which is on
the default search path — so **this defect is invisible to everyone who could
find it** and appears only for a student who has never installed a Microsoft
C++ toolchain. Hence a static guard rather than a runtime one.

Assertions are text-level for the reason `test_build_spec_console_window.py`
gives: a spec is executed by PyInstaller with injected globals (`SPECPATH`),
so importing it here is not possible. The failure being guarded against is
somebody deleting a line that looks redundant because the bundle "already
has" these DLLs.

macOS needs no equivalent: Mach-O resolves via `@rpath` recorded in the
binary, not by the launching directory. #181 covers the separate dylib
problem there.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parent.parent / 'wimi.spec'

#: Exactly the four the import tables name. Not a superset: an extra entry
#: would fail the build on a host that lacks it, for a DLL nothing needs.
REQUIRED_DLLS = (
    'vcomp140.dll',
    'msvcp140.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
)


@pytest.fixture(scope='module')
def spec_text() -> str:
    return SPEC.read_text(encoding='utf-8')


def test_the_spec_names_every_dll_the_vendored_binaries_import(spec_text: str) -> None:
    for dll in REQUIRED_DLLS:
        assert dll in spec_text, (
            f'{dll} is not named in wimi.spec. All four are required: '
            f'VCOMP140 by ggml-base.dll and the nine ggml-cpu-* variants, '
            f'the other three by whisper-cli.exe itself (#158).'
        )


def test_they_are_bundled_to_the_whisper_directory_not_the_bundle_root(
    spec_text: str,
) -> None:
    """`whisper_dest` is the destination that matters, and it is the point.

    PyInstaller already puts these at the top level on its own. A change
    that dropped the destination -- or pointed it anywhere else -- would
    leave the bundle looking complete and `whisper-cli.exe` unable to start.
    """
    assert re.search(
        r'binaries\s*\+=\s*\[\s*\(\s*str\(\s*_system32\s*/\s*name\s*\)\s*,'
        r'\s*whisper_dest\s*\)\s*for\s+name\s+in\s+MSVC_RUNTIME_DLLS\s*\]',
        spec_text,
    ), (
        'The MSVC runtime DLLs are not added to `binaries` with `whisper_dest` '
        'as their destination. Collecting them anywhere else -- including the '
        'bundle root, where PyInstaller puts them by default -- does not fix '
        '#158: Windows resolves a subprocess\'s imports from the directory '
        'holding the .exe.'
    )


def test_the_build_refuses_rather_than_shipping_without_them(spec_text: str) -> None:
    """A warning would be ignored on the machines where it does not matter."""
    assert '_missing_runtime' in spec_text and re.search(
        r'if\s+_missing_runtime\s*:\s*\n\s*raise\s+SystemExit', spec_text
    ), (
        'wimi.spec must raise SystemExit when the MSVC runtime is not on the '
        'build host. Building anyway produces a bundle that fails at image '
        'load on any machine without the redistributable, with both output '
        'streams empty (#158).'
    )


def test_they_are_excluded_from_upx_by_name(spec_text: str) -> None:
    """The whisper pattern cannot cover them: UPX matching is on the SOURCE path.

    `whisper_upx_exclude` is `'whisper/windows/*'`, matched by
    `pathlib.PurePath.match` against `src_name`
    (`PyInstaller/building/utils.py:136`). These DLLs are sourced from
    System32, so that pattern does not match them and they would be the only
    files in the whisper directory that get compressed.

    PyInstaller would most likely skip them anyway -- it disables UPX for
    binaries with Control Flow Guard, which Microsoft's runtime has. "Most
    likely" is a detection that can change, and the failure it would let
    through is the same silent image-load refusal as #158 itself.
    """
    assert re.search(
        r'whisper_upx_exclude\s*\+=\s*list\(\s*MSVC_RUNTIME_DLLS\s*\)', spec_text
    ), (
        'The MSVC runtime DLLs are not added to `whisper_upx_exclude`. The '
        "existing 'whisper/windows/*' pattern matches the SOURCE path and "
        'cannot cover files coming from System32.'
    )


def test_the_dll_list_is_exactly_the_four_that_are_imported(spec_text: str) -> None:
    """Guard both directions: a dropped entry breaks a student, an added one
    breaks the build on a host that does not have it."""
    match = re.search(
        r'MSVC_RUNTIME_DLLS\s*=\s*\((?P<body>.*?)\)', spec_text, re.DOTALL
    )
    assert match, 'MSVC_RUNTIME_DLLS is not defined as a tuple in wimi.spec'
    declared = set(re.findall(r"'([^']+\.dll)'", match.group('body')))
    assert declared == set(REQUIRED_DLLS), (
        f'MSVC_RUNTIME_DLLS declares {sorted(declared)}; the vendored '
        f'binaries import exactly {sorted(REQUIRED_DLLS)} (#158, established '
        f'by dumpbin over all 13 PE files).'
    )
