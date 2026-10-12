"""#60's model-backed scenario must stay reachable on Windows (#389, measured).

`tests/wimi_test/scenarios/test_relation_proposals_press_and_confirm.py` makes
the pinned GLiNER2 weights present in the run's app data. It did that with
`Path.symlink_to`, and on `Windows machine B` every test in the file ERRORed at
setup:

    OSError: [WinError 1314] A required privilege is not held by the client

`SeCreateSymbolicLinkPrivilege` needs an elevated account or Developer Mode, so
on an ordinary Windows account the file never reached its body at all. Not a
product defect and not a failure anyone would read as one -- four setup errors,
and #60's only end-to-end test silently unrunnable on the platform.

Why this guard exists rather than a comment
-------------------------------------------
**No run on Linux or macOS can detect the regression.** `symlink_to` works
there, so a future change collapsing the fallback back to one call would be
green on both, and Windows runs are rare enough that it could sit broken for
weeks. That is the condition under which this project enforces a rule instead of
stating it -- the same argument as `check_css_empty_selector.py`, where the
engine that breaks is not the one most tests run on.

This is a **source** check because the thing it protects is a mechanism, not an
outcome: the scenario's own assertions pass whichever way the files arrive.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO = (REPO_ROOT / 'tests' / 'wimi_test' / 'scenarios'
            / 'test_relation_proposals_press_and_confirm.py')


def unguarded_symlink_calls(source: str) -> list[int]:
    """Line numbers where ``symlink_to`` is called outside a ``try``.

    A function so the control below can run the same reader over mutated text.

    **Parsed, not grepped**, and the control is what forced that. The first
    version looked for an `except OSError` within twelve lines and declared the
    call guarded if it found one — which passed the mutant, because moving the
    call out of its `try` leaves it twelve lines above the `os.link` branch's
    own `except OSError`. A reader that cannot fail is the thing this file
    exists to prevent, one level up.

    So this walks the AST and asks the structural question: is the call inside
    the body of a `try` that catches `OSError`? Nothing textual can answer that.
    """
    tree = ast.parse(source)
    found: list[int] = []

    def catches_oserror(handler: ast.ExceptHandler) -> bool:
        names = []
        if isinstance(handler.type, ast.Name):
            names = [handler.type.id]
        elif isinstance(handler.type, ast.Tuple):
            names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
        elif handler.type is None:
            return True  # a bare except catches it too
        return 'OSError' in names

    def walk(node: ast.AST, guarded: bool) -> None:
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'symlink_to'
                and not guarded):
            found.append(node.lineno)
        if isinstance(node, ast.Try):
            protects = any(catches_oserror(h) for h in node.handlers)
            for child in node.body:
                walk(child, guarded or protects)
            for group in (node.handlers, node.orelse, node.finalbody):
                for child in group:
                    walk(child, guarded)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, guarded)

    walk(tree, False)
    return sorted(found)


@pytest.fixture(scope='module')
def source() -> str:
    return SCENARIO.read_text(encoding='utf-8')


def test_the_scenario_does_not_rely_on_symlinks(source):
    """The defect itself: a bare ``symlink_to`` is unreachable on Windows."""
    bare = unguarded_symlink_calls(source)
    assert not bare, (
        f'symlink_to is called unguarded at line(s) {bare}. On an ordinary '
        f'Windows account that raises WinError 1314 and every test in the file '
        f'ERRORs at setup, so #60 loses its only end-to-end test on that '
        f'platform. Fall back to os.link and then to a copy.')


def test_the_reader_would_catch_a_bare_call(source):
    """The control. Without it the test above asserts nothing (#121).

    Replaces the guarded call with a bare one and requires the same reader to
    find it.
    """
    mutated = source.replace(
        """    try:
        dst.symlink_to(src)
        return 'symlink'
    except (OSError, NotImplementedError):
        pass""",
        '    dst.symlink_to(src)')
    assert mutated != source, (
        'the mutation did not apply, so this control is stale and '
        'test_the_scenario_does_not_rely_on_symlinks proves nothing')
    assert unguarded_symlink_calls(mutated), (
        'the reader cannot see a bare symlink_to call')


@pytest.mark.parametrize('mechanism', ['symlink_to', 'os.link', 'copyfile'])
def test_all_three_mechanisms_are_present(source, mechanism):
    """Each is load-bearing on a different machine.

    * ``symlink_to`` costs nothing and is what POSIX gets;
    * ``os.link`` needs no privilege, so it is the Windows answer -- and it is
      safe against the HF cache, because unlinking one name leaves the file
      while another name remains;
    * ``copyfile`` is the cross-volume fallback, and the only branch that
      spends 845 MB.

    Measured on Linux by denying each in turn: ``symlink`` / ``hardlink`` /
    ``copy``, all three producing byte-identical readable files, all three
    removed by the teardown's ``unlink``, with the source intact after.
    """
    assert mechanism in source, (
        f'{mechanism} is gone from the placement chain. Dropping os.link '
        f'breaks Windows; dropping copyfile breaks a cross-volume HF cache.')


def test_the_teardown_removes_whatever_was_placed(source):
    """The fallback changes what teardown is deleting, so it must not assume.

    A hard link and a copy are ordinary files, not symlinks. The teardown
    unlinks a recorded list rather than testing what each entry is -- and it
    must stay `missing_ok`, or one already-removed entry raises inside the
    `finally` and skips the rest, masking the real error with a cleanup error.
    """
    assert 'placed.unlink(missing_ok=True)' in source, (
        'the teardown must unlink what the fixture recorded, tolerantly')
    assert 'rmtree' not in re.sub(r'#.*|"""[\s\S]*?"""', '', source), (
        'rmtree is back in the executable code. It deleted a real 845 MB '
        'model during review of #389; the teardown removes only what the '
        'fixture created')
