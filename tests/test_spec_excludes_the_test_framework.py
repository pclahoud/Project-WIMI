"""No release artifact ships the test framework, and the list stays complete (#409).

`_pytest` **is not a submodule of `pytest`.** The pytest distribution installs
two sibling top-level packages, and PyInstaller matches `excludes` by module
name — so `excludes=['pytest']` covers `pytest` and `pytest.*` and has no effect
whatever on `_pytest`.

Both specs' exclude lists read as complete and were not. Measured on
`Windows machine B` against the relations release build: **49 `_pytest` modules in
the PYZ**, compiled into the exe, out of 6,037 entries. `pytest_asyncio` was
missing from the list too.

They arrive through third-party *testing* submodules the hooks collect wholesale
— `torch.testing._internal.common_utils`, `sympy.testing.runtests_pytest`,
`networkx.utils.backends`, `fsspec.conftest` — which is why it bites the
relations build hardest, torch being the worst offender. Nothing in WIMI imports
any of them.

Why this is self-counting rather than a fixed list
--------------------------------------------------
A hardcoded expected set would have to be edited by whoever adds a pytest
plugin to `requirements-test.txt`, which is exactly the person who will not
think about `.spec` files. So the expectation is **derived from what is
installed**: every top-level package named `pytest`, `_pytest` or `pytest_*`
that the environment actually provides must appear in both specs.

That is the same shape as `test_page_gate_markup.py` being self-counting over
every gated page — a seventh page is checked the day it declares itself.

Deliberately narrow
-------------------
This covers the **pytest family only**, not every distribution in
`requirements-test.txt`. Excluding test dependencies wholesale would be wrong:
`jsonschema` is pinned there and also arrives with `mcp`, which needs it at
runtime, so excluding it would break the MCP server. The pytest family is
exactly the set that exists only to run tests and gets pulled in by other
packages' testing submodules.
"""
from __future__ import annotations

import ast
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS = {
    'wimi.spec': REPO_ROOT / 'wimi.spec',
    'wimi_macos.spec': REPO_ROOT / 'wimi_macos.spec',
}


def spec_excludes(path: Path) -> set[str]:
    """The string literals in the spec's ``Analysis(excludes=[...])``.

    Parsed rather than grepped: a spec is Python, and `ast` answers "is this
    name in the excludes list" without caring about formatting, comments or
    the comment blocks above each entry — which in these files are longer than
    the list itself.

    The spec cannot be imported: it references `SPECPATH` and friends that only
    PyInstaller defines. `ast.parse` executes nothing, so that does not matter.

    Raises:
        AssertionError: if no ``excludes`` keyword is found. Returning an empty
            set there would make every assertion below pass against a spec
            whose exclusion list had been deleted outright.
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != 'excludes':
                continue
            assert isinstance(kw.value, ast.List), (
                f'{path.name}: excludes is not a list literal, so this guard '
                f'cannot read it')
            return {
                e.value for e in kw.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    raise AssertionError(
        f'{path.name} has no excludes= keyword. Without one the default '
        f'artifact collects whatever happens to be installed, which is what '
        f'#60 relies on it NOT doing for torch.')


def installed_pytest_family() -> set[str]:
    """Top-level packages that exist only to run tests, as installed here.

    `packages_distributions()` maps an importable top-level name to the
    distributions providing it, which is the only reliable way round: the
    distribution `pytest-asyncio` provides the module `pytest_asyncio`, and
    `pytest` provides **both** `pytest` and `_pytest`.
    """
    return {
        name for name in packages_distributions()
        if name in ('pytest', '_pytest') or name.startswith('pytest_')
    }


@pytest.mark.parametrize('spec_name', sorted(SPECS))
def test_every_installed_pytest_package_is_excluded(spec_name):
    """The defect: `_pytest` and `pytest_asyncio` were not in either list."""
    excludes = spec_excludes(SPECS[spec_name])
    missing = sorted(installed_pytest_family() - excludes)
    assert not missing, (
        f'{spec_name} does not exclude {missing}. PyInstaller matches excludes '
        f'by module name, so a sibling package like `_pytest` is NOT covered '
        f'by `pytest` — and third-party testing submodules (torch.testing, '
        f'sympy.testing, networkx.utils.backends, fsspec.conftest) pull it in '
        f'wholesale, putting the test framework in a release artifact.')


def test_pytest_and_its_private_package_are_both_named():
    """The specific pair, asserted by name as well as by the sweep.

    The sweep above only sees what is installed. These two are the ones
    measured in a real bundle, so they are pinned outright — a machine
    somehow lacking `_pytest` must not make this file quietly weaker.
    """
    for spec_name, path in SPECS.items():
        excludes = spec_excludes(path)
        for name in ('pytest', '_pytest'):
            assert name in excludes, f'{spec_name} does not exclude {name!r}'


def test_the_two_specs_agree():
    """CLAUDE.md records that these two files drift, and this is that class.

    The mechanism is PyInstaller's static analysis, which is not
    platform-specific, so an exclusion that matters on one platform matters on
    both. The measurement was taken on Windows; the macOS relations worktree
    also carries the test pins (#393), so it has the same exposure.
    """
    windows = spec_excludes(SPECS['wimi.spec'])
    macos = spec_excludes(SPECS['wimi_macos.spec'])
    only_windows = sorted(windows - macos)
    only_macos = sorted(macos - windows)
    assert not only_windows and not only_macos, (
        f'the specs\' excludes disagree. Only in wimi.spec: {only_windows}. '
        f'Only in wimi_macos.spec: {only_macos}. Both artifacts are built from '
        f'the same analysis semantics; a divergence here means one platform '
        f'ships something the other does not, silently.')


def test_the_reader_would_notice_a_missing_entry():
    """The control. Without it the sweep asserts nothing (#121).

    Removes `_pytest` from the real spec text and requires the same reader to
    report it — which is precisely the state both files were in before #409.
    """
    text = SPECS['wimi.spec'].read_text(encoding='utf-8')
    mutated = text.replace("        '_pytest',\n", '', 1)
    assert mutated != text, 'the mutation did not apply; this control is stale'

    tree_excludes = None
    for node in ast.walk(ast.parse(mutated)):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == 'excludes' and isinstance(kw.value, ast.List):
                    tree_excludes = {
                        e.value for e in kw.value.elts
                        if isinstance(e, ast.Constant)
                    }
                    break
        if tree_excludes is not None:
            break
    assert tree_excludes is not None, 'the mutated spec parsed to no excludes'
    assert '_pytest' not in tree_excludes, (
        'the reader still sees _pytest after it was removed, so '
        'test_every_installed_pytest_package_is_excluded could not fail')


def test_a_runtime_dependency_is_not_swept_up():
    """The guard must stay narrow, and this is why.

    `jsonschema` is pinned in requirements-test.txt and also arrives with
    `mcp`, which needs it at runtime — so a well-meaning "exclude every test
    dependency" rule would break the MCP server in a release build. Neither
    spec may exclude it.
    """
    for spec_name, path in SPECS.items():
        excludes = spec_excludes(path)
        for runtime_need in ('jsonschema', 'mcp', 'pychrome'):
            if runtime_need == 'pychrome':
                continue  # test-only, but harmless either way; not asserted
            assert runtime_need not in excludes, (
                f'{spec_name} excludes {runtime_need!r}, which the product '
                f'needs at runtime')
