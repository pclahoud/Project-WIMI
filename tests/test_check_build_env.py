"""Tests for ``scripts/check_build_env.py`` — the #135 build environment guard.

These test the *pure* parts: pin parsing and name normalisation, plus the
invariant that the real ``requirements-prod.txt`` still declares the pins the
guard exists to protect. The runtime Qt checks are deliberately not tested —
they read the loaded library, so a test could only assert that this machine is
what it is, which is what the guard already reports.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "check_build_env.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_build_env", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_build_env"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guard():
    return _load()


@pytest.mark.unit
def test_script_exists():
    assert SCRIPT.exists(), "the build scripts call this; it must be present"


@pytest.mark.unit
def test_normalise_follows_pep503(guard):
    assert guard._normalise("PyQt6_sip") == "pyqt6-sip"
    assert guard._normalise("PyQt6-WebEngine-Qt6") == "pyqt6-webengine-qt6"
    assert guard._normalise("python.json.logger") == "python-json-logger"


@pytest.mark.unit
def test_parses_exact_pins_only(guard, tmp_path):
    """`>=` is not a claim about an exact version, so there is nothing to check."""
    req = tmp_path / "r.txt"
    req.write_text(
        "# a comment\n"
        "\n"
        "PyQt6==6.9.1\n"
        "python-json-logger>=2.0.0\n"
        "Pillow==11.3.0  # trailing comment\n"
        "pyinstaller>6.0\n",
        encoding="utf-8",
    )
    pins = guard.parse_pins(req)
    assert pins == {"pyqt6": "6.9.1", "pillow": "11.3.0"}


@pytest.mark.unit
def test_real_requirements_pin_the_qt_binaries(guard):
    """The hole #135 went through: bindings pinned, binaries floating.

    ``PyQt6`` and ``PyQt6-WebEngine`` are thin wrappers. ``PyQt6-Qt6`` and
    ``PyQt6-WebEngine-Qt6`` carry the Qt and Chromium binaries that actually
    get bundled, and they are transitive dependencies — pinning only the
    bindings lets the shipped Chromium float inside the binding's range.
    Do not remove these pins.
    """
    pins = guard.parse_pins(PROJECT_ROOT / "requirements-prod.txt")
    for required in (
        "pyqt6",
        "pyqt6-webengine",
        "pyqt6-qt6",
        "pyqt6-webengine-qt6",
    ):
        assert required in pins, (
            f"{required} is not pinned in requirements-prod.txt. See #135: the "
            f"Qt binary wheels decide which Chromium ships, and an unpinned one "
            f"shipped Chromium 134 while every test ran 130."
        )


@pytest.mark.unit
def test_expected_chromium_is_declared(guard):
    """The one fact no package pin states, so it has to be asserted somewhere."""
    assert isinstance(guard.EXPECTED_CHROMIUM_MAJOR, int)
    assert guard.EXPECTED_CHROMIUM_MAJOR > 0


@pytest.mark.unit
def test_python_range_is_coherent(guard):
    assert guard.MIN_PYTHON <= guard.MAX_TESTED_PYTHON


@pytest.mark.unit
@pytest.mark.parametrize("script", ["build_windows.bat", "build_macos.sh"])
def test_build_scripts_call_the_guard(script):
    """A guard the build does not run is the comment it replaced."""
    text = (PROJECT_ROOT / script).read_text(encoding="utf-8")
    assert "check_build_env.py" in text, (
        f"{script} does not invoke the build environment guard"
    )
    assert "--warn-only" not in text, (
        f"{script} runs the guard with --warn-only, which cannot stop a build"
    )
