"""The build gate must check WHICH Python it is, not just that a venv exists (#183).

Both build scripts do this:

    if not exist ".venv\\Scripts\\activate.bat"  ...   <- passes: the file exists
    call .venv\\Scripts\\activate.bat                  <- silently does nothing useful
    python scripts\\check_build_env.py                 <- whatever `python` is on PATH

**Checking that `activate.bat` exists creates false confidence**, because the
failure mode is an activate script that is present and broken. A venv hardcodes
absolute paths; rename or move the directory and `activate` exports a
`VIRTUAL_ENV` that no longer exists, prepends a `Scripts`/`bin` that is not
there, and leaves the system interpreter on PATH with no warning.

That happened on a Windows machine here — a `.venv` created as `venv` — and the
build ran on the system Python. It surfaced **only by luck**: the system
interpreter happened to differ from the venv in one pinned package, so
`check_pins` caught it. Had they agreed on every pin, the build would have
completed from an environment nobody selected and reported nothing unusual.
That is #135 through a different door: the gate verifies *an* environment, and
nothing verified it was the *right* one.

`sys.prefix` is the honest answer, because the interpreter sets it — a stale
`VIRTUAL_ENV` cannot forge it.

These drive the real function with a substituted project root, rather than
asserting on the build scripts' text, because the question is whether the gate
*refuses*, not whether a line is present.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'check_build_env.py'


@pytest.fixture(scope='module')
def gate():
    spec = importlib.util.spec_from_file_location('check_build_env_i', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(gate, monkeypatch, project_root: Path, prefix: Path):
    monkeypatch.setattr(gate, 'PROJECT_ROOT', project_root)
    monkeypatch.setattr(sys, 'prefix', str(prefix))
    problems: list[str] = []
    notes: list[str] = []
    gate.check_interpreter(problems, notes)
    return problems, notes


def test_a_foreign_interpreter_is_refused(gate, monkeypatch, tmp_path):
    """The defect: building from a Python that is not the checkout's venv."""
    (tmp_path / '.venv').mkdir()
    elsewhere = tmp_path / 'system-python'
    elsewhere.mkdir()

    problems, _ = _run(gate, monkeypatch, tmp_path, elsewhere)

    assert len(problems) == 1, f'expected a refusal, got {problems}'
    text = problems[0]
    # Both paths, or the reader cannot tell what went wrong -- "wrong venv" is
    # true and unactionable when the whole failure mode is not knowing which
    # interpreter you got.
    assert str(elsewhere) in text
    assert str((tmp_path / '.venv').resolve()) in text


def test_the_projects_own_venv_is_accepted(gate, monkeypatch, tmp_path):
    """Negative control.

    Without it, a check that appended a problem unconditionally would pass the
    test above and block every build on a correctly configured machine — which
    is how a gate gets commented out.
    """
    venv = tmp_path / '.venv'
    venv.mkdir()

    problems, notes = _run(gate, monkeypatch, tmp_path, venv)

    assert problems == []
    assert notes == []


def test_a_checkout_with_no_venv_is_a_note_not_a_refusal(gate, monkeypatch, tmp_path):
    """Absent is not wrong.

    The gate is runnable from a git worktree or a machine using a different
    environment manager, and refusing there would teach people to skip it —
    which costs more than the check is worth.
    """
    elsewhere = tmp_path / 'some-python'
    elsewhere.mkdir()

    problems, notes = _run(gate, monkeypatch, tmp_path, elsewhere)

    assert problems == []
    assert len(notes) == 1
    assert 'could not be checked' in notes[0]


def test_a_symlinked_or_relative_path_still_matches(gate, monkeypatch, tmp_path):
    """`.resolve()` on both sides, so an equivalent path is not a false alarm.

    A false refusal here is worse than no check: it fires on a correct machine,
    at the moment someone is trying to ship.
    """
    venv = tmp_path / '.venv'
    venv.mkdir()
    indirect = tmp_path / 'sub' / '..' / '.venv'
    (tmp_path / 'sub').mkdir()

    problems, _ = _run(gate, monkeypatch, tmp_path, indirect)
    assert problems == [], f'an equivalent path was reported as a mismatch: {problems}'


def test_the_gate_actually_runs_the_check(gate):
    """Wiring, by AST — the function is useless if `main()` never calls it.

    A substring search would match the `def` line and pass while the call was
    gone; that exact mutation survived a text search in #185's guard.
    """
    import ast

    called = any(
        isinstance(node, ast.Call)
        and getattr(node.func, 'id', None) == 'check_interpreter'
        for node in ast.walk(ast.parse(SCRIPT.read_text(encoding='utf-8')))
    )
    assert called, 'check_build_env.py defines check_interpreter but never calls it'
