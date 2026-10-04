"""A config that never read the environment must not reach a session (#185).

Every ``WIMI_TEST_*`` variable is read inside ``TestConfig.resolve()``, not in
``__init__``. So a bare ``TestConfig()`` carries pure dataclass defaults and
silently discards all of them.

That inverts the usual safety gradient. Omitting ``config=`` works, because
both consumers fall back to ``resolve()``; writing the *more explicit-looking*
``config=TestConfig()`` is the broken form. Being careful was the unsafe move,
and there is no bare ``TestConfig(`` construction anywhere in the repo — the
trap is reachable only by someone deliberately spelling out what they meant.

What it cost: a probe sent to read ``binary_dir()`` from inside a frozen bundle
was built with ``TestConfig()``, so ``WIMI_TEST_BINARY`` was ignored, the
session spawned ``python run_wimi.py``, and the probe reported a **dev** path.
That is precisely the shape of a #138-class frozen-mode defect, which is what
the probe had been sent to hunt. It was nearly filed as a real finding, and it
invalidated a model-download measurement that had to be redone.

The failure is maximally deceptive: no exception, no warning, and a *plausible
wrong answer* — a real path to a real binary, differing from the expected one
in exactly the direction the investigation was looking for.

A warning rather than a refusal: a unit test wanting hermetic defaults is a
legitimate reason to construct one directly. Handing one to something that
spawns a real WIMI is not.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wimi_test.config import (
    TestConfig,
    UnresolvedConfigWarning,
    warn_if_unresolved,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------- the trap itself

def test_a_bare_config_does_not_see_the_environment(monkeypatch):
    """The defect, demonstrated rather than described.

    This is the whole issue in three lines: the same environment, two ways of
    building a config, two different answers — and the wrong one is silent.
    """
    monkeypatch.setenv('WIMI_TEST_BINARY', '/tmp/some-frozen-binary')

    assert TestConfig().wimi_binary is None, (
        'a bare TestConfig() picked up WIMI_TEST_BINARY; if that is now true, '
        'this whole issue is obsolete and the warning should go'
    )
    # Compare Paths, not their str(). `str(Path('/tmp/x'))` is
    # `'\\tmp\\x'` on Windows, so a POSIX literal can never match there --
    # the assertion failed for the separator rather than for the value it
    # exists to check (#257).
    assert TestConfig.resolve().wimi_binary == Path('/tmp/some-frozen-binary')


def test_resolve_marks_what_it_builds_and_direct_construction_does_not():
    assert TestConfig.resolve().resolved_from_environment is True
    assert TestConfig().resolved_from_environment is False


# ------------------------------------------------------------------ the guard

def test_an_unresolved_config_warns(recwarn):
    warn_if_unresolved(TestConfig(), consumer='WimiTestSession')

    matches = [w for w in recwarn if issubclass(w.category, UnresolvedConfigWarning)]
    assert len(matches) == 1, f'expected one warning, got {[w.category for w in recwarn]}'

    text = str(matches[0].message)
    # The message has to name the variable and the consequence. "Config not
    # resolved" would be true and useless -- the reader needs to know their
    # session is about to run the dev launcher and report dev paths.
    assert 'WIMI_TEST_BINARY' in text
    assert 'run_wimi.py' in text
    assert 'TestConfig.resolve()' in text


def test_a_resolved_config_is_silent(recwarn):
    """Negative control.

    Without this, a helper that warned unconditionally would pass the test
    above and make every correct session noisy — which is how a warning gets
    filtered out globally and stops working.
    """
    warn_if_unresolved(TestConfig.resolve(), consumer='WimiTestSession')
    assert [w for w in recwarn if issubclass(w.category, UnresolvedConfigWarning)] == []


# ------------------------------------------------------- the wiring, not the helper

@pytest.mark.parametrize('module', ['session.py', 'page.py'])
def test_both_consumers_actually_call_the_guard(module):
    """The helper is worthless if nothing invokes it.

    Source-level because the alternative is constructing a real
    ``WimiTestSession``, which spawns WIMI over CDP — far too much machinery to
    assert one function call, and it would make a unit test depend on a working
    graphics stack.
    """
    import ast

    source = (REPO_ROOT / 'wimi_test' / module).read_text(encoding='utf-8')
    called = any(
        isinstance(node, ast.Call)
        and getattr(node.func, 'id', None) == 'warn_if_unresolved'
        for node in ast.walk(ast.parse(source))
    )
    # A substring search is not enough here, and that is not hypothetical:
    # the first version of this test looked for 'warn_if_unresolved' in the
    # text, and deleting the CALL left the IMPORT behind, so the mutation
    # passed. The import is what makes the name present; only a Call node
    # makes it run.
    assert called, (
        f'wimi_test/{module} imports warn_if_unresolved but never calls it, so '
        f'a directly constructed TestConfig reaches a live session silently '
        f'again (#185)'
    )


def test_nothing_in_the_repo_constructs_a_bare_config_for_a_session():
    """The state #185 found and the state to stay in.

    Every call site uses ``resolve()`` or omits the argument. If this ever
    fails, the warning above will have fired at runtime first — but a test is
    cheaper than noticing a warning in a log.
    """
    offenders = []
    for path in REPO_ROOT.rglob('*.py'):
        if any(part in {'.git', '.venv', 'node_modules'} for part in path.parts):
            continue
        if path.name == Path(__file__).name:
            continue
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if 'config=TestConfig()' in line.replace(' ', ''):
                offenders.append(f'{path.relative_to(REPO_ROOT)}:{n}')
    assert not offenders, (
        f'these pass a bare TestConfig() to a session: {offenders}. Pass no '
        f'config at all, or TestConfig.resolve() (#185).'
    )
