"""Tests for the frozen-binary spawn capability in ``wimi_test`` (#138).

Nothing in this project had ever driven a frozen build, and #138 is the
structural reason: the artifact ignored ``--test-mode``, so the debug
port never opened and CDP had nothing to attach to. #135 (the shipped
binary running a different Chromium from every test) was invisible for
exactly that reason.

Fixing the entry point is only half of it — the harness also has to be
able to point at the binary. ``TestConfig.wimi_binary`` (env
``WIMI_TEST_BINARY``) switches every spawn from ``python run_wimi.py`` to
the built executable, so setting one variable runs the whole regression
suite against the artifact users actually get.

The ``--app-data-dir`` assertion is the subtle one and is not tidiness: a
*relative* app-data path is resolved by ``src/app/main.py`` against its
own ``project_root``, which for a frozen build is **the directory holding
the executable**, not the harness's cwd. Left relative, the harness would
seed a user in ``<repo>/app_data_test`` while the binary opened
``<dist>/WIMI/app_data_test`` and found nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Aliased: pytest would otherwise try to collect ``TestConfig`` as a test
# class and warn. Same convention as test_process_port_picker.py.
from wimi_test.config import TestConfig as HarnessConfig
from wimi_test.process import WimiProcess


@pytest.mark.unit
def test_default_command_runs_the_launcher_through_this_interpreter():
    proc = WimiProcess(HarnessConfig())

    cmd = proc._build_command(12055)

    assert cmd[0] == sys.executable
    assert cmd[1] == "run_wimi.py"
    assert "--test-mode" in cmd
    assert cmd[cmd.index("--debug-port") + 1] == "12055"


@pytest.mark.unit
def test_a_configured_binary_replaces_the_interpreter_and_script(tmp_path):
    binary = tmp_path / "WIMI"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    proc = WimiProcess(HarnessConfig(wimi_binary=binary))

    cmd = proc._build_command(12055)

    assert cmd[0] == str(binary)
    assert sys.executable not in cmd
    assert "run_wimi.py" not in cmd
    # Same flags either way — the point of #138 is that they now work.
    assert cmd[1:4] == ["--test-mode", "--debug-port", "12055"]


@pytest.mark.unit
@pytest.mark.parametrize("frozen", [False, True], ids=["launcher", "binary"])
def test_app_data_dir_is_always_absolute(tmp_path, frozen):
    """A relative path means different directories to the two processes."""
    binary = tmp_path / "WIMI"
    config = HarnessConfig(
        app_data_dir=Path("app_data_test"),
        wimi_binary=binary if frozen else None,
    )
    proc = WimiProcess(config)

    cmd = proc._build_command(12055)

    passed = Path(cmd[cmd.index("--app-data-dir") + 1])
    assert passed.is_absolute()
    assert passed == WimiProcess._project_root() / "app_data_test"


@pytest.mark.unit
def test_an_absolute_app_data_dir_is_passed_through_unchanged(tmp_path):
    config = HarnessConfig(app_data_dir=tmp_path / "elsewhere")
    proc = WimiProcess(config)

    cmd = proc._build_command(12055)

    assert cmd[cmd.index("--app-data-dir") + 1] == str(tmp_path / "elsewhere")


@pytest.mark.unit
def test_wimi_binary_defaults_to_none():
    assert HarnessConfig().wimi_binary is None
    assert HarnessConfig.resolve().wimi_binary is None


@pytest.mark.unit
def test_wimi_binary_is_resolvable_from_the_environment(monkeypatch, tmp_path):
    binary = tmp_path / "dist" / "WIMI" / "WIMI"
    monkeypatch.setenv("WIMI_TEST_BINARY", str(binary))

    assert HarnessConfig.resolve().wimi_binary == binary


@pytest.mark.unit
def test_an_empty_wimi_binary_reads_as_unset(monkeypatch):
    """``WIMI_TEST_BINARY=`` must not mean "spawn the empty string"."""
    monkeypatch.setenv("WIMI_TEST_BINARY", "   ")

    assert HarnessConfig.resolve().wimi_binary is None
