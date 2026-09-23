"""A release build never starts test mode (#144, owner's decision 2026-09-22).

``--test-mode`` starts a Chromium remote debugger. Release builds refuse it;
only a test build -- the same spec plus one runtime hook -- accepts it. This
checks the **artifact**, not the source: point ``WIMI_RELEASE_BINARY`` at a
release build (``build_windows.bat`` / ``./build_macos.sh`` -> ``dist/WIMI``)
and it asserts the refusal happens, and happens before any window opens.

The source-level behaviour is covered in ``tests/app/test_cli.py``; this is
the check that the build route really leaves the hook out.
"""
from __future__ import annotations

import os
import subprocess

import pytest

RELEASE = os.environ.get("WIMI_RELEASE_BINARY", "").strip()

pytestmark = pytest.mark.skipif(
    not RELEASE,
    reason="Set WIMI_RELEASE_BINARY to a release build (dist/WIMI/WIMI) to check it.",
)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([RELEASE, *args], capture_output=True, text=True,
                          timeout=120, errors="replace")


@pytest.mark.parametrize("flags", [
    ("--test-mode",),
    ("--test-mode", "--debug-port", "12050"),
    ("--debug-port", "12050"),
])
def test_a_release_build_refuses_the_debugger_flags(flags):
    result = _run(*flags)
    assert result.returncode == 2, (
        f"a release build accepted {' '.join(flags)} (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}")
    assert "not available in a release build" in result.stderr
    assert "TEST_MODE_READY" not in result.stdout, "it started test mode anyway"


def test_a_release_build_still_parses_its_command_line():
    """The gate must not break the binary: --help answers and exits 0."""
    result = _run("--help")
    assert result.returncode == 0, result.stderr
    assert "--app-data-dir" in result.stdout
