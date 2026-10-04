"""The two build flags are orthogonal and compose (#60, #144).

WIMI has two independent build-time questions:

* ``WIMI_BUILD_VARIANT`` -- release or test. The test variant adds one runtime
  hook, and that hook is the only thing that lets a frozen WIMI accept
  ``--test-mode`` (#144).
* ``WIMI_BUILD_RELATIONS`` -- whether the bundle carries the relation-extraction
  runtime. WIMI ships two artifacts per platform and the default one has no
  torch (#60, owner's decision 2026-10-04).

They are **separate flags rather than a four-value enum**, which is the thing
these tests exist to hold in place. An enum would need ``release / test /
relations / test-relations`` written out by hand, and a fifth concern later
would make it eight names; orthogonal flags compose, and so does the folder
name. ``WIMI_BUILD_VARIANT=relations`` must therefore be *refused* -- it is the
shape of the mistake, not an alternative spelling.

Unlike ``test_build_spec_console_window.py``, these assertions execute the
spec's variant header rather than reading it as text. That is possible because
the header depends only on ``SPECPATH`` and ``os.environ``, and it is worth
doing because the property under test is the *computed* result of two flags --
a regex over the source could not tell ``'-test' if TEST_BUILD else ''`` from a
version that had the condition inverted.

Both specs are checked on every case. CLAUDE.md records that ``wimi.spec`` and
``wimi_macos.spec`` "are clones with no shared helper and a change made in one
of them is a bug that only shows on the other platform", so a test that
checked one of them would miss exactly the drift that matters.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS = {
    'wimi.spec': REPO_ROOT / 'wimi.spec',
    'wimi_macos.spec': REPO_ROOT / 'wimi_macos.spec',
}
PACKAGING = REPO_ROOT / 'packaging'

# Everything before this marker depends only on SPECPATH and os.environ, so it
# can be executed without PyInstaller, without Qt and without torch. Splitting
# on a comment is brittle in general; here it fails loudly (the marker is
# asserted present) rather than silently evaluating the wrong thing.
_HEADER_MARKER = '# Collect all web assets'


def _eval_header(spec: Path, *, variant: str, relations: str) -> dict:
    """Execute *spec*'s variant header with the given flags and return its globals."""
    text = spec.read_text(encoding='utf-8')
    assert text.count(_HEADER_MARKER) == 1, (
        f'{spec.name}: expected exactly one {_HEADER_MARKER!r} marker; the '
        f'header split in this test needs updating alongside the spec.'
    )
    header = text.split(_HEADER_MARKER)[0]

    namespace: dict = {'SPECPATH': str(REPO_ROOT)}
    saved = os.environ.copy()
    os.environ['WIMI_BUILD_VARIANT'] = variant
    os.environ['WIMI_BUILD_RELATIONS'] = relations
    try:
        exec(compile(header, str(spec), 'exec'), namespace)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return namespace


# (variant, relations flag, expected dist name, expected hook basenames)
MATRIX = [
    ('release', '0', 'WIMI', []),
    ('test', '0', 'WIMI-test', ['rthook_test_build.py']),
    ('release', '1', 'WIMI-relations', ['rthook_relations_build.py']),
    ('test', '1', 'WIMI-test-relations',
     ['rthook_test_build.py', 'rthook_relations_build.py']),
]


@pytest.mark.unit
@pytest.mark.parametrize('spec_name', sorted(SPECS))
@pytest.mark.parametrize('variant,relations,dist_name,hooks', MATRIX)
def test_the_flags_compose_into_one_dist_name(
    spec_name: str, variant: str, relations: str, dist_name: str, hooks: list[str],
) -> None:
    """Each of the four combinations names its own folder, in both specs.

    The names are the decided ones. ``dist/WIMI`` and ``dist/WIMI-test`` are
    pre-existing and must not move: ``WIMI_TEST_BINARY`` and the build scripts'
    own clean step both name them.
    """
    namespace = _eval_header(SPECS[spec_name], variant=variant, relations=relations)

    assert namespace['DIST_NAME'] == dist_name
    assert [Path(h).name for h in namespace['runtime_hooks']] == hooks


@pytest.mark.unit
@pytest.mark.parametrize('variant,relations,_dist,hooks', MATRIX)
def test_both_specs_agree(variant: str, relations: str, _dist: str,
                          hooks: list[str]) -> None:
    """The two clones compute the same answer, which is the drift that bites."""
    results = {
        name: _eval_header(path, variant=variant, relations=relations)
        for name, path in SPECS.items()
    }
    windows, macos = results['wimi.spec'], results['wimi_macos.spec']

    assert windows['DIST_NAME'] == macos['DIST_NAME']
    assert windows['TEST_BUILD'] == macos['TEST_BUILD']
    assert windows['RELATIONS_BUILD'] == macos['RELATIONS_BUILD']
    assert (windows['RELATIONS_RUNTIME_PACKAGES']
            == macos['RELATIONS_RUNTIME_PACKAGES'])
    assert ([Path(h).name for h in windows['runtime_hooks']]
            == [Path(h).name for h in macos['runtime_hooks']])


@pytest.mark.unit
@pytest.mark.parametrize('spec_name', sorted(SPECS))
def test_relations_is_not_a_variant_value(spec_name: str) -> None:
    """``WIMI_BUILD_VARIANT=relations`` is refused, not accepted as a synonym.

    This is the negative control for the whole design. #60's decision says to
    keep the flags orthogonal rather than adding a fourth enum value, so the
    enum must still reject the value somebody would reach for first -- and
    reject it loudly at spec time rather than quietly building a release
    bundle because the string did not match ``'test'``.
    """
    with pytest.raises(SystemExit) as excinfo:
        _eval_header(SPECS[spec_name], variant='relations', relations='0')
    assert 'WIMI_BUILD_VARIANT' in str(excinfo.value)


@pytest.mark.unit
@pytest.mark.parametrize('spec_name', sorted(SPECS))
@pytest.mark.parametrize('bad', ['yes', 'true', 'on', '2', ''])
def test_a_non_binary_relations_flag_is_refused(spec_name: str, bad: str) -> None:
    """Only '0' and '1'.

    A truthy-string check would make ``WIMI_BUILD_RELATIONS=false`` build the
    relations artifact, and an unset-versus-empty confusion would make an
    exported-but-blank variable do something different from an absent one.
    Refusing is the only behaviour that cannot surprise.
    """
    with pytest.raises(SystemExit) as excinfo:
        _eval_header(SPECS[spec_name], variant='release', relations=bad)
    assert 'WIMI_BUILD_RELATIONS' in str(excinfo.value)


@pytest.mark.unit
@pytest.mark.parametrize('spec_name', sorted(SPECS))
def test_the_default_bundle_excludes_the_relations_runtime(spec_name: str) -> None:
    """torch is in ``excludes`` for the default build and not for the relations one.

    This is what makes the default artifact deterministic rather than a
    function of what happens to be installed on the build machine.
    PyInstaller's analysis is static and ignores import scope, so without the
    exclusion a developer with the relations venv installed would collect
    gigabytes of torch into the default bundle from a *function-level* import
    -- which ``check_relations_runtime_imports.py`` deliberately permits,
    because a deferred import is the required pattern for the feature.

    The two guards cover different things and neither replaces the other: that
    gate keeps the runtime off the startup PATH, this exclusion keeps it out of
    the default BUNDLE.
    """
    text = SPECS[spec_name].read_text(encoding='utf-8')
    assert 'RELATIONS_RUNTIME_PACKAGES' in text

    default = _eval_header(SPECS[spec_name], variant='release', relations='0')
    for package in ('torch', 'transformers', 'gliner2'):
        assert package in default['RELATIONS_RUNTIME_PACKAGES']

    # The exclusion is spliced in with a conditional unpack, so assert on the
    # expression rather than re-deriving the final excludes list (which needs
    # the whole spec).
    assert '*([] if RELATIONS_BUILD else RELATIONS_RUNTIME_PACKAGES)' in text


@pytest.mark.unit
def test_both_runtime_hooks_exist_and_set_only_their_own_marker() -> None:
    """The hooks are the mechanism, so a missing file is a silent variant.

    PyInstaller would fail on a missing runtime hook, but it would fail at
    build time on one platform, during a build nobody runs often. Checking the
    files here costs nothing.

    Each hook must set *only* its own flag: a relations hook that also set
    ``_wimi_test_build`` would open #144's remote-debugger gate in a
    distributed artifact, which is the one thing that decision says nothing at
    runtime may do.
    """
    test_hook = PACKAGING / 'rthook_test_build.py'
    relations_hook = PACKAGING / 'rthook_relations_build.py'

    assert test_hook.is_file()
    assert relations_hook.is_file()

    test_source = test_hook.read_text(encoding='utf-8')
    relations_source = relations_hook.read_text(encoding='utf-8')

    assert 'sys._wimi_test_build = True' in test_source
    assert '_wimi_relations_build' not in test_source

    assert 'sys._wimi_relations_build = True' in relations_source
    assert '_wimi_test_build' not in relations_source
