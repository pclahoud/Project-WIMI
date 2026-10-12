"""A gate's reported location reads the same on every host (#621).

``check_css_tokens.py``, ``check_css_empty_selector.py`` and
``check_ascii_prints.py`` each report ``file:line``. They built it as
``f"{path.relative_to(root)}:{line}"``, and ``str()`` of a ``WindowsPath``
renders backslashes, so the same gate on the same commit printed
``src\\web\\css\\a.css:1`` on Windows and ``src/web/css/a.css:1`` elsewhere.
Two of ``test_check_css_tokens.py``'s tests could therefore never pass on
Windows. A location is a repo-relative identifier, not a path to open, so the
fix is ``as_posix()`` in the gates, not a looser assertion in the tests.

**Why the paths here are ``PureWindowsPath``.** On Linux and macOS ``str(path)``
and ``path.as_posix()`` are the same string, so a test built from host paths
passes against the unfixed spelling on every platform CI runs. A
``PureWindowsPath`` keeps its backslashes on any host, so these tests fail on
Linux for the defect they guard.

The second half checks that each gate's output actually goes through
``location()``: a correct helper that a gate does not call would fix nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path, PureWindowsPath

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GATES = ("check_css_tokens", "check_css_empty_selector", "check_ascii_prints")


def _load(name: str):
    """Load a fresh copy of a gate by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        f"_posix_{name}", PROJECT_ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
@pytest.mark.parametrize("name", GATES)
def test_a_windows_path_is_reported_with_forward_slashes(name):
    gate = _load(name)
    root = PureWindowsPath(r"C:\repo")
    path = root / "src" / "web" / "css" / "a.css"

    assert gate.location(path, root, 12) == "src/web/css/a.css:12"


SENTINEL = "SENTINEL-621"


def _sentinel(path, root, line):
    return f"{SENTINEL}:{line}"


@pytest.mark.unit
def test_the_token_audit_reports_through_location(tmp_path, monkeypatch):
    gate = _load("check_css_tokens")
    css = tmp_path / "src" / "web" / "css"
    css.mkdir(parents=True)
    (css / "a.css").write_text(
        ".a { color: var(--nowhere); background: var(--also-nowhere, red); }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "location", _sentinel)

    result = gate.audit(tmp_path)

    assert result.undefined == {"--nowhere": [f"{SENTINEL}:1"]}
    assert result.dead_fallback == {"--also-nowhere": [f"{SENTINEL}:1"]}


@pytest.mark.unit
def test_the_empty_selector_gate_reports_through_location(tmp_path, monkeypatch, capsys):
    gate = _load("check_css_empty_selector")
    css = tmp_path / "src" / "web" / "css"
    css.mkdir(parents=True)
    (css / "a.css").write_text(".a:empty { display: none; }\n", encoding="utf-8")
    monkeypatch.setattr(gate, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(gate, "location", _sentinel)

    assert gate.main() == 1
    assert f"  {SENTINEL}:1\n" in capsys.readouterr().err


@pytest.mark.unit
def test_the_ascii_print_gate_reports_through_location(tmp_path, monkeypatch, capsys):
    gate = _load("check_ascii_prints")
    src = tmp_path / "src"
    src.mkdir()
    (src / "offender.py").write_text('print("caf\u00e9")\n', encoding="utf-8")
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCANNED_ROOTS", ("src",))
    monkeypatch.setattr(gate, "location", _sentinel)

    assert gate.main() == 1
    assert f"  {SENTINEL}:1: " in capsys.readouterr().err
