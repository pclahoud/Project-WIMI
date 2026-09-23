"""Tests for ``src/app/cli.py`` and the two entry points that share it (#138).

``wimi.spec`` and ``wimi_macos.spec`` both name ``src/app/main.py`` as the
PyInstaller Analysis entry, so in a frozen build *that* file is
``__main__`` and ``run_wimi.py`` — where the parser used to live — is not
even in the bundle. ``main.py``'s ``__main__`` block called ``main()``
with no arguments, so ``getattr(args, 'test_mode', False)`` and friends
returned their defaults and every test-mode flag was silently dropped:
the debug port never opened and ``--app-data-dir`` was ignored while the
run quietly used the real ``app_data/``.

Two halves are asserted here:

* the parser itself, including the 12000-12100 validation that a fork
  would have been free to drift on;
* that the **frozen entry point** — ``python src/app/main.py`` — parses
  through that same parser. Those are subprocess tests because the whole
  defect lived in a ``if __name__ == '__main__'`` block, which an import
  never executes. They stop before any Qt import, so they are fast.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app import cli

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MAIN_PY = PROJECT_ROOT / "src" / "app" / "main.py"
RUN_WIMI = PROJECT_ROOT / "run_wimi.py"


def _run_entry_point(script: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke an entry point far enough to parse, and no further."""
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_defaults_leave_every_flag_off():
    args = cli.parse_cli_args([])

    assert args.test_mode is False
    assert args.debug_port is None
    assert args.app_data_dir is None
    assert args.mcp_server is False
    assert args.test_mcp_server is False


@pytest.mark.unit
def test_test_mode_autopicks_a_port_inside_the_range():
    args = cli.parse_cli_args(["--test-mode"])

    lo, hi = cli.DEBUG_PORT_RANGE
    assert lo <= args.debug_port <= hi


@pytest.mark.unit
def test_an_explicit_in_range_port_is_kept():
    args = cli.parse_cli_args(["--test-mode", "--debug-port", "12055"])

    assert args.debug_port == 12055


@pytest.mark.unit
@pytest.mark.parametrize("port", ["11999", "12101", "0", "8080"])
def test_a_port_outside_the_range_is_refused(port):
    with pytest.raises(SystemExit) as excinfo:
        cli.parse_cli_args(["--test-mode", "--debug-port", port])

    assert "12000" in str(excinfo.value) and "12100" in str(excinfo.value)


@pytest.mark.unit
def test_the_range_is_only_enforced_for_test_mode():
    """Without --test-mode the port is inert, so nothing is validated."""
    args = cli.parse_cli_args(["--debug-port", "8080"])

    assert args.debug_port == 8080
    assert args.test_mode is False


@pytest.mark.unit
def test_app_data_dir_survives_parsing():
    args = cli.parse_cli_args(["--app-data-dir", "/tmp/scratch-wimi"])

    assert args.app_data_dir == "/tmp/scratch-wimi"


@pytest.mark.unit
def test_mcp_server_is_a_declared_flag():
    """It is dispatched by a sys.argv peek, but strict parsing must accept it.

    ``app.main.main`` looks for ``--mcp-server`` in ``sys.argv`` before
    importing any GUI module. If the parser did not also know the flag,
    strict parsing would reject the invocation before the peek ever ran.
    """
    args = cli.parse_cli_args(["--mcp-server"])

    assert args.mcp_server is True


@pytest.mark.unit
def test_an_unknown_flag_is_an_error_not_a_shrug():
    """The #138 shape one level down: accepted-and-ignored is the worst case."""
    with pytest.raises(SystemExit):
        cli.parse_cli_args(["--app-data-dirr", "/tmp/typo"])


# ---------------------------------------------------------------------------
# The two entry points share it
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_launcher_does_not_define_a_second_parser():
    """``run_wimi.py`` must delegate, or the frozen build drifts again."""
    source = RUN_WIMI.read_text(encoding="utf-8")

    assert "app.cli" in source
    assert "add_argument" not in source


@pytest.mark.unit
@pytest.mark.parametrize("script", [MAIN_PY, RUN_WIMI], ids=["frozen", "launcher"])
def test_entry_point_help_lists_every_flag(script):
    result = _run_entry_point(script, "--help")

    assert result.returncode == 0, result.stderr
    for flag in ("--test-mode", "--debug-port", "--app-data-dir", "--mcp-server"):
        assert flag in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("script", [MAIN_PY, RUN_WIMI], ids=["frozen", "launcher"])
def test_entry_point_rejects_an_unknown_flag(script):
    result = _run_entry_point(script, "--not-a-real-flag")

    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("script", [MAIN_PY, RUN_WIMI], ids=["frozen", "launcher"])
def test_entry_point_enforces_the_debug_port_range(script):
    """The validation must reach the frozen path, not just the launcher."""
    result = _run_entry_point(script, "--test-mode", "--debug-port", "23456")

    assert result.returncode != 0
    assert "outside the allowed range" in (result.stderr + result.stdout)


# ==================== #144: release builds refuse test mode ====================

@pytest.fixture
def frozen_release(monkeypatch):
    """A frozen bundle built without the test hook: a release build."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, cli.TEST_BUILD_MARKER, raising=False)


@pytest.fixture
def frozen_test_build(monkeypatch):
    """A frozen bundle whose runtime hook ran: a test build."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, cli.TEST_BUILD_MARKER, True, raising=False)


@pytest.mark.parametrize("argv", [
    ["--test-mode"],
    ["--test-mode", "--debug-port", "12050"],
    ["--debug-port", "12050"],
])
def test_a_release_build_refuses_the_debugger_flags(frozen_release, argv, capsys):
    """Owner's decision on #144: release builds never get the flag."""
    with pytest.raises(SystemExit) as exc:
        cli.parse_cli_args(argv)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not available in a release build" in err
    assert "build_windows.bat test" in err, "the refusal must say how to get a test build"


def test_a_release_build_still_takes_the_rest_of_its_command_line(frozen_release):
    """--app-data-dir opens nothing, so the gate leaves it alone."""
    args = cli.parse_cli_args(["--app-data-dir", "/tmp/somewhere"])
    assert args.test_mode is False and args.app_data_dir == "/tmp/somewhere"
    assert cli.parse_cli_args([]).test_mode is False


def test_a_test_build_accepts_test_mode(frozen_test_build):
    args = cli.parse_cli_args(["--test-mode", "--debug-port", "12050"])
    assert args.test_mode is True and args.debug_port == 12050


def test_a_development_run_is_never_gated(monkeypatch):
    """The harness spawns run_wimi.py; gating it would break every scenario."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, cli.TEST_BUILD_MARKER, raising=False)
    assert cli.parse_cli_args(["--test-mode", "--debug-port", "12050"]).test_mode is True


def test_no_environment_variable_opens_the_gate(frozen_release, monkeypatch):
    """The variant is baked in at build time. An env var at run time is not a key."""
    for name in ("WIMI_BUILD_VARIANT", "WIMI_TEST_BUILD", "WIMI_TEST_MODE"):
        monkeypatch.setenv(name, "test")
    with pytest.raises(SystemExit):
        cli.parse_cli_args(["--test-mode"])


def test_the_runtime_hook_is_what_marks_a_test_build():
    hook = PROJECT_ROOT / "packaging" / "rthook_test_build.py"
    result = subprocess.run(
        [sys.executable, "-c",
         "import runpy, sys; runpy.run_path(sys.argv[1]); "
         f"print(getattr(sys, {cli.TEST_BUILD_MARKER!r}, False))", str(hook)],
        capture_output=True, text=True, timeout=60)
    assert result.stdout.strip() == "True", result.stderr


@pytest.mark.parametrize("spec", ["wimi.spec", "wimi_macos.spec"])
def test_only_the_test_variant_of_each_spec_includes_the_hook(spec):
    """One spec, two variants: the hook must be conditional, and the only difference."""
    text = (PROJECT_ROOT / spec).read_text()
    hook_lines = [l for l in text.splitlines() if "rthook_test_build.py" in l]
    assert hook_lines and all("if TEST_BUILD else []" in l for l in hook_lines), hook_lines
    assert "runtime_hooks=runtime_hooks" in text
    assert "os.environ.get('WIMI_BUILD_VARIANT', 'release')" in text, (
        "a spec that defaults to anything but release would ship the hook")
