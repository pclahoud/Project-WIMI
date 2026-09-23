"""The Windows build hides its console WINDOW, it does not give up stdout (#142).

A terminal window opening beside the GUI is a bug (#142). ``console=False``
is the obvious fix and the wrong one: a windowed Windows build has no
standard streams, so every ``print()`` diagnostic becomes a no-op, and the
harness learns WIMI is up by reading ``TEST_MODE_READY:port=N`` off stdout
(#138, #137). PyInstaller's ``hide_console`` hides the window while leaving
the streams real, so both concerns are satisfied at once.

These assertions are text-level on purpose: a spec file is executed by
PyInstaller with ``SPECPATH`` and other injected globals, so importing it
here is not possible, and the failure mode being guarded against is
somebody editing the flag.

macOS is the opposite case and must stay that way: ``wimi_macos.spec`` sets
``console=False`` because an ``.app`` bundle cannot be a console app, which
is why ``configure_stdio()`` has to survive ``sys.stdout is None``
(``tests/app/test_console_encoding.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SPEC_DIR = Path(__file__).resolve().parent.parent
WINDOWS_SPEC = SPEC_DIR / 'wimi.spec'
MACOS_SPEC = SPEC_DIR / 'wimi_macos.spec'

# The EXE() call's own keywords, not any word appearing in a comment.
_CONSOLE_KWARG = re.compile(r'^\s*console\s*=\s*(True|False)\s*,', re.MULTILINE)
_HIDE_CONSOLE_KWARG = re.compile(r"^\s*hide_console\s*=\s*'([a-z-]+)'\s*,", re.MULTILINE)

# PyInstaller rejects anything else (PyInstaller/building/api.py).
_VALID_HIDE_CONSOLE = {'hide-early', 'minimize-early', 'hide-late', 'minimize-late'}


@pytest.mark.unit
def test_windows_build_stays_a_console_app():
    """console=False would silence print() and break TEST_MODE_READY."""
    matches = _CONSOLE_KWARG.findall(WINDOWS_SPEC.read_text(encoding='utf-8'))

    assert matches == ['True'], (
        "wimi.spec must keep console=True. A windowed Windows build has no "
        "stdout, so TEST_MODE_READY:port=N never reaches the harness (#138) "
        "and every startup print() is silently dropped (#137). To stop the "
        "terminal window appearing, use hide_console -- see #142."
    )


@pytest.mark.unit
def test_windows_build_hides_the_console_window():
    """#142: the window must not sit beside the GUI for the whole session."""
    matches = _HIDE_CONSOLE_KWARG.findall(WINDOWS_SPEC.read_text(encoding='utf-8'))

    assert len(matches) == 1, (
        "wimi.spec must set hide_console exactly once; without it the console "
        "window opens beside the GUI (#142)."
    )
    assert matches[0] in _VALID_HIDE_CONSOLE, (
        f"hide_console={matches[0]!r} is not one of {sorted(_VALID_HIDE_CONSOLE)}; "
        "PyInstaller raises ValueError at build time for anything else."
    )
    assert matches[0] == 'hide-early', (
        "hide-early hides the window as soon as the PKG archive is found, so a "
        "bootloader failure before that point is still readable. A 'late' "
        "setting leaves the window up for longer with no benefit here."
    )


@pytest.mark.unit
def test_macos_build_is_windowed_and_sets_no_hide_console():
    """An .app cannot be a console app; hide_console is Windows-only."""
    text = MACOS_SPEC.read_text(encoding='utf-8')

    assert _CONSOLE_KWARG.findall(text) == ['False'], (
        "wimi_macos.spec must keep console=False -- a macOS .app bundle must "
        "not be a console app."
    )
    assert not _HIDE_CONSOLE_KWARG.findall(text), (
        "hide_console is Windows-only; PyInstaller warns and ignores it "
        "elsewhere, so setting it in the macOS spec is noise that reads like "
        "a working setting."
    )
