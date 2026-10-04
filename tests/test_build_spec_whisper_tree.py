"""Both frozen builds carry the whisper.cpp tree, and carry it the same way (#59).

Neither spec can be built here: `wimi.spec` is Windows and `wimi_macos.spec`
needs a Mac, and #143 records that macOS has never been built at all. So these
tests do the strongest thing short of a build -- they **execute** each spec
with PyInstaller's injected globals stubbed out, against a synthetic
`vendor/whisper/<platform>/` tree, and assert on what the spec actually hands
to `Analysis` and `COLLECT`.

That is deliberately stronger than the text matching in
`test_build_spec_console_window.py` and `test_build_spec_macos_bundle.py`,
which guard single keyword values. What is being guarded here is a *list built
by code* -- a path, a destination prefix and a UPX exclusion that have to agree
with each other and with the fetcher. Grepping for a string would pass against
a spec that computed the wrong path.

The failure mode this file exists for: **the two spec files are near-identical
clones with no shared helper**, so a change made in one of them is a bug that
only appears on the other platform, at build time, on hardware the person
making the change probably does not have. Several tests below therefore assert
that the two agree with each other rather than that either one is right in
isolation.

What is NOT verified here, and where it is:

* that the collected binary runs -- **T18** on Windows, **T19** on macOS;
* that `sys._MEIPASS / 'whisper' / <platform>` is where the files land in a
  real bundle -- same two tasks. It is derived from PyInstaller 6.19's own
  collection code, not measured;
* the MSVC runtime question (#158), which reproduces only on a clean Windows
  machine.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WINDOWS_SPEC = REPO_ROOT / 'wimi.spec'
MACOS_SPEC = REPO_ROOT / 'wimi_macos.spec'

# (spec file, platform key, binary name) -- the fetcher's own vocabulary.
# `windows` and `macos-arm64` are the keys in scripts/fetch_whisper.py, and
# `linux` is deliberately absent from both specs: it is a development target
# that is never distributed.
SPECS = [
    pytest.param(WINDOWS_SPEC, 'windows', 'whisper-cli.exe', id='windows'),
    pytest.param(MACOS_SPEC, 'macos-arm64', 'whisper-cli', id='macos'),
]


class _Recorder:
    """Stands in for Analysis/PYZ/EXE/COLLECT/BUNDLE and records the call.

    Returns something attribute-hungry, because a spec reaches into the
    Analysis result (`a.scripts`, `a.binaries`, `a.datas`, ...) before handing
    it on.
    """

    def __init__(self, calls, name):
        self._calls = calls
        self._name = name

    def __call__(self, *args, **kwargs):
        self._calls.setdefault(self._name, []).append((args, kwargs))
        return _Anything()


class _Anything:
    def __getattr__(self, item):
        return _Anything()

    def __iter__(self):
        return iter(())


def _make_tree(root: Path, platform: str, binary: str) -> Path:
    """A minimal stand-in for a fetched/compiled vendor/whisper/<platform>/."""
    tree = root / 'vendor' / 'whisper' / platform
    tree.mkdir(parents=True)
    (tree / binary).write_bytes(b'not really a binary')
    (tree / 'LICENSE').write_text('MIT', encoding='utf-8')
    return tree


def _run_spec(spec_path: Path, specpath: Path) -> tuple[dict, dict]:
    """Execute a spec with PyInstaller's injected globals faked.

    Returns ``(globals_after, calls)``. ``specpath`` becomes ``SPECPATH``, so
    the spec resolves ``vendor/`` under a directory the test controls rather
    than under the real checkout -- where ``vendor/`` is git-ignored and may or
    may not have been fetched.
    """
    calls: dict = {}
    namespace = {
        '__name__': '__main__',
        '__file__': str(spec_path),
        'SPECPATH': str(specpath),
        'DISTPATH': str(specpath / 'dist'),
        'workpath': str(specpath / 'build'),
    }
    for injected in ('Analysis', 'PYZ', 'EXE', 'COLLECT', 'BUNDLE', 'MERGE', 'TOC', 'Tree', 'Splash'):
        namespace[injected] = _Recorder(calls, injected)

    code = compile(spec_path.read_text(encoding='utf-8'), str(spec_path), 'exec')
    exec(code, namespace)  # noqa: S102 -- executing a spec is the point
    return namespace, calls


#: The four DLLs `wimi.spec` refuses to build without (#158).
_MSVC_RUNTIME_DLLS = (
    'vcomp140.dll', 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll',
)


@pytest.fixture
def spec_env(tmp_path, monkeypatch):
    """Run a spec against a synthetic tree; yield a helper bound to tmp_path."""
    # A spec reads WIMI_BUILD_VARIANT; pin it so a variable left over in the
    # environment cannot change what these tests exercise.
    monkeypatch.delenv('WIMI_BUILD_VARIANT', raising=False)

    # `wimi.spec` raises SystemExit at import time unless the four MSVC runtime
    # DLLs are in %SystemRoot%\System32 (#158). That guard is correct for a
    # build and fatal for a read: it fires on Linux and macOS, where
    # `C:\Windows\System32` cannot exist, so *executing* either spec was
    # impossible off Windows and all nine tests in this file failed there.
    #
    # The guard is deliberately left unconditional in the spec -- #158 wanted a
    # hard failure, and a `sys.platform` check would weaken the one thing
    # standing between a build host without the redistributable and a bundle
    # whose speech-to-text dies at image load with both streams empty. So the
    # test supplies the condition instead of the spec relaxing it.
    #
    # `test_build_spec_msvc_runtime.py` covers the guard itself, by reading the
    # spec text rather than running it -- which is why it passes everywhere and
    # this file did not.
    fake_system32 = tmp_path / 'fake-windows' / 'System32'
    fake_system32.mkdir(parents=True)
    for _name in _MSVC_RUNTIME_DLLS:
        (fake_system32 / _name).write_bytes(b'not really a DLL')
    monkeypatch.setenv('SystemRoot', str(fake_system32.parent))

    def run(spec_path: Path, platform: str, binary: str, *, make_tree: bool = True):
        root = tmp_path / spec_path.stem
        root.mkdir()
        if make_tree:
            _make_tree(root, platform, binary)
        return _run_spec(spec_path, root), root

    return run


# --------------------------------------------------------------------------
# Each spec, on its own
# --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize('spec_path, platform, binary', SPECS)
def test_spec_collects_the_vendored_whisper_tree(spec_env, spec_path, platform, binary):
    """The tree reaches Analysis, from vendor/, bound for whisper/<platform>."""
    (namespace, calls), root = spec_env(spec_path, platform, binary)

    (_, analysis_kwargs), = calls['Analysis']
    collected = analysis_kwargs['binaries']

    expected_src = root / 'vendor' / 'whisper' / platform
    assert (str(expected_src), f'whisper/{platform}') in collected, (
        f'{spec_path.name} must collect the vendored whisper tree. Without it '
        'the build succeeds and the microphone button cannot work, which is '
        'the failure that has no error message.'
    )


@pytest.mark.unit
@pytest.mark.parametrize('spec_path, platform, binary', SPECS)
def test_spec_declares_the_tree_as_binaries_not_datas(spec_env, spec_path, platform, binary):
    """binaries=, decided once and applied in both clones.

    PyInstaller reclassifies by file content either way, so this does not
    change the bundle. It changes what happens when classification cannot
    answer, and it is the claim the spec makes about what these files are.
    """
    (namespace, calls), root = spec_env(spec_path, platform, binary)
    (_, analysis_kwargs), = calls['Analysis']

    dest = f'whisper/{platform}'
    assert any(entry[1] == dest for entry in analysis_kwargs['binaries'])
    assert not any(entry[1] == dest for entry in analysis_kwargs['datas']), (
        'the whisper tree belongs in binaries=, not datas=. Both spec files '
        'must agree; see the comment above the block in wimi.spec.'
    )


@pytest.mark.unit
@pytest.mark.parametrize('spec_path, platform, binary', SPECS)
def test_spec_excludes_the_tree_from_upx(spec_env, spec_path, platform, binary):
    """UPX on a third-party native binary produces something that will not run.

    Load-bearing rather than decorative: these are BINARY entries and COLLECT
    sets upx=True, so PyInstaller would compress them without this.
    """
    (namespace, calls), root = spec_env(spec_path, platform, binary)
    (_, collect_kwargs), = calls['COLLECT']

    assert collect_kwargs['upx'] is True, (
        'this test assumes UPX is on; if it were turned off the exclusion '
        'below would stop being the thing that protects the binary'
    )
    patterns = collect_kwargs['upx_exclude']
    assert patterns, f'{spec_path.name} passes an empty upx_exclude'

    # PyInstaller matches with pathlib.PurePath.match against the SOURCE path,
    # right to left. Prove the real source paths match, rather than trusting
    # the pattern to look right.
    tree = root / 'vendor' / 'whisper' / platform
    for name in (binary, 'LICENSE'):
        src = tree / name
        assert any(Path(src).match(p) for p in patterns), (
            f'{src} is not covered by upx_exclude={patterns!r}'
        )


@pytest.mark.unit
@pytest.mark.parametrize('spec_path, platform, binary', SPECS)
def test_upx_exclusion_does_not_catch_the_rest_of_the_bundle(spec_env, spec_path, platform, binary):
    """A pattern broad enough to disable UPX everywhere would hide its own bugs.

    `*.dll` and `*.dylib` are the tempting shorthands and both match every Qt
    library in the bundle.
    """
    (namespace, calls), root = spec_env(spec_path, platform, binary)
    (_, collect_kwargs), = calls['COLLECT']
    patterns = collect_kwargs['upx_exclude']

    innocent = [
        root / 'PyQt6' / 'Qt6' / 'bin' / 'Qt6Core.dll',
        root / 'PyQt6' / 'Qt6' / 'lib' / 'QtCore.framework' / 'QtCore',
        root / 'python312.dll',
        root / 'libssl.dylib',
    ]
    for path in innocent:
        assert not any(Path(path).match(p) for p in patterns), (
            f'upx_exclude={patterns!r} also disables UPX for {path}'
        )


@pytest.mark.unit
@pytest.mark.parametrize('spec_path, platform, binary', SPECS)
def test_spec_refuses_to_build_without_the_tree(spec_env, spec_path, platform, binary):
    """A missing fetch/compile step must stop the build, not ship quietly.

    The message has to name the command that fixes it: whoever hits this is
    running PyInstaller directly, so the build script that would have run the
    step is not on screen.
    """
    with pytest.raises(SystemExit) as excinfo:
        spec_env(spec_path, platform, binary, make_tree=False)

    message = str(excinfo.value)
    assert binary in message
    assert platform in message
    assert 'build_macos.sh' in message or 'fetch_whisper.py' in message, (
        f'the refusal must say how to produce the tree; it said: {message!r}'
    )


@pytest.mark.unit
@pytest.mark.parametrize('spec_path, platform, binary', SPECS)
def test_spec_bundles_no_model_weights(spec_env, spec_path, platform, binary):
    """Owner decision D2: weights download on first run, never in the installer.

    Enforced by an absence, so it is easy to undo by helpfully "completing"
    the feature in a spec file.
    """
    (namespace, calls), root = spec_env(spec_path, platform, binary)
    (_, analysis_kwargs), = calls['Analysis']

    collected = analysis_kwargs['binaries'] + analysis_kwargs['datas']
    for src, dest in collected:
        assert 'models' not in Path(dest).parts, (
            f'{spec_path.name} collects {dest!r}. Model weights must never be '
            'in the installer (D2, plan section 3.8) -- they download on first '
            'run into app_data/models/.'
        )
        assert not src.endswith('.bin'), f'{spec_path.name} collects {src!r}'


# --------------------------------------------------------------------------
# The two clones, against each other
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_both_specs_use_the_same_destination_shape(spec_env):
    """`whisper/<platform>` in both, so one resolver works in both bundles.

    T6 resolves the binary as `Path(sys._MEIPASS) / 'whisper' / <platform>`.
    If the two specs disagreed on the prefix, that resolver would be correct
    on one platform and silently wrong on the other.
    """
    dests = {}
    for spec_path, platform, binary in (p.values for p in SPECS):
        (namespace, calls), _ = spec_env(spec_path, platform, binary)
        dests[spec_path.name] = namespace['whisper_dest']
        assert namespace['WHISPER_PLATFORM'] == platform

    assert set(dests.values()) == {'whisper/windows', 'whisper/macos-arm64'}
    for name, dest in dests.items():
        assert dest.startswith('whisper/'), f'{name} collects into {dest!r}'
        assert dest.count('/') == 1, f'{name} collects into {dest!r}'


@pytest.mark.unit
@pytest.mark.parametrize('spec_path, platform, binary', SPECS)
def test_platform_key_contains_no_dot(spec_env, spec_path, platform, binary):
    """A dot would make PyInstaller rewrite the directory name on macOS.

    Directories under `Contents/Frameworks` may not contain a dot unless they
    are .framework bundles, so PyInstaller substitutes the character and leaves
    a symlink behind. The collected path would then not be the path the spec
    asked for, and the runtime's `sys._MEIPASS / 'whisper' / <platform>` would
    be resolving through a link whose existence nothing else records.

    Read out of the spec, not out of this file's own table: asserting that a
    constant declared here has no dot would prove nothing about the build.
    """
    (namespace, _), _ = spec_env(spec_path, platform, binary)

    key = namespace['WHISPER_PLATFORM']
    assert '.' not in key, (
        f'{spec_path.name} uses platform key {key!r}. Pick one without a dot; '
        'PyInstaller renames such a directory under Contents/Frameworks.'
    )


@pytest.mark.unit
def test_both_specs_wire_upx_exclude_into_collect(spec_env):
    """Computing the exclusion and then not passing it is a silent no-op."""
    for spec_path, platform, binary in (p.values for p in SPECS):
        (namespace, calls), _ = spec_env(spec_path, platform, binary)
        (_, collect_kwargs), = calls['COLLECT']
        assert collect_kwargs['upx_exclude'] == namespace['whisper_upx_exclude'], (
            f'{spec_path.name} computes whisper_upx_exclude but COLLECT gets '
            f'{collect_kwargs["upx_exclude"]!r}'
        )


def _whisper_block(spec: Path) -> list[str]:
    """The speech-to-text block, from its banner to the UPX exclusion."""
    lines = spec.read_text(encoding='utf-8').splitlines()
    start = next(i for i, ln in enumerate(lines) if 'speech-to-text' in ln)
    end = next(i for i, ln in enumerate(lines) if 'whisper_upx_exclude = ' in ln)
    return lines[start:end + 1]


#: Names belonging to the Windows-only MSVC runtime block (#158). Statements
#: mentioning any of them are the one sanctioned divergence between the specs,
#: and `test_the_msvc_runtime_block_is_windows_only` pins that they appear in
#: `wimi.spec` alone.
_MSVC_NAMES = frozenset({'MSVC_RUNTIME_DLLS', '_system32', '_missing_runtime'})


def _touches_msvc(node) -> bool:
    """Does this statement mention any of the Windows-only MSVC names?"""
    import ast

    return any(
        isinstance(sub, ast.Name) and sub.id in _MSVC_NAMES
        for sub in ast.walk(node)
    )


def _msvc_statements(spec: Path):
    """Top-level statements of the whisper block that touch the MSVC names."""
    import ast

    code = '\n'.join(
        ln for ln in _whisper_block(spec)
        if ln.strip() and not ln.lstrip().startswith('#')
    )
    return [node for node in ast.parse(code).body if _touches_msvc(node)]


def _logic_skeleton(spec: Path) -> str:
    """The block's executable statements, with every string literal erased.

    Prose is allowed to differ between the two specs -- the macOS one has to
    explain a source build that has no Windows equivalent. The *logic* is not
    allowed to differ, and that is what this compares: parse the code, replace
    every string constant with a placeholder, and dump the tree.

    **One exception, added 2026-09-26.** #158 bundles the MSVC runtime beside
    `whisper-cli.exe`, and that is Windows-only by nature -- macOS has no
    `vcruntime140.dll` and shipping one would be a bug, not parity. So
    statements touching `_MSVC_NAMES` are removed before comparing, and their
    Windows-only-ness is asserted separately rather than dropped.

    The exception is kept this narrow on purpose. Widening it to "ignore
    anything only one spec has" would retire the test: its whole value is that
    a change made in one clone and not the other is invisible until build time,
    on hardware the person making the change probably does not have.
    """
    import ast

    code = '\n'.join(
        ln for ln in _whisper_block(spec)
        if ln.strip() and not ln.lstrip().startswith('#')
    )
    tree = ast.parse(code)
    tree.body = [node for node in tree.body if not _touches_msvc(node)]

    class _EraseStrings(ast.NodeTransformer):
        def visit_Constant(self, node):  # noqa: N802 -- ast's naming
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value='<STR>'), node)
            return node

    return ast.dump(ast.fix_missing_locations(_EraseStrings().visit(tree)))


@pytest.mark.unit
def test_the_msvc_runtime_block_is_windows_only():
    """#158's DLLs must be in `wimi.spec` and must not reach `wimi_macos.spec`.

    This is the other half of the exception `_logic_skeleton` makes. Without
    it, removing the MSVC block from `wimi.spec` entirely -- the #158
    regression -- would leave the two specs trivially equal and the drift test
    green.

    It is also an assertion in its own direction: `vcruntime140.dll` in a macOS
    bundle is a bug, and a copy-paste between two near-identical clones is
    exactly how it would get there.
    """
    assert _msvc_statements(WINDOWS_SPEC), (
        'wimi.spec no longer has the MSVC runtime block (#158). Without those '
        'four DLLs beside whisper-cli.exe, speech-to-text dies at image load '
        'on any machine without the redistributable, with both streams empty.'
    )
    assert not _msvc_statements(MACOS_SPEC), (
        'wimi_macos.spec references the MSVC runtime. Those DLLs are Windows '
        'binaries; shipping them in a .app is a copy-paste between the two '
        'clones, not parity.'
    )


@pytest.mark.unit
def test_the_two_specs_carry_identical_whisper_logic():
    """The clones must not drift apart in what the whisper block *does*.

    This is the test the file exists for. `wimi.spec` and `wimi_macos.spec`
    are near-identical copies with no shared helper, so a change made in one
    of them is a bug that only appears on the other platform, at build time,
    on hardware the person making the change probably does not have. Asserting
    that the two agree is worth more than asserting either one is right.
    """
    assert _logic_skeleton(WINDOWS_SPEC) == _logic_skeleton(MACOS_SPEC), (
        'the whisper block\'s logic has drifted between wimi.spec and '
        'wimi_macos.spec. Only the string literals -- the platform key, the '
        'binary name and the message naming how to produce the tree -- may '
        'differ. Make the change in both files.'
    )


@pytest.mark.unit
@pytest.mark.parametrize('spec_path, platform, binary', SPECS)
def test_each_spec_keeps_its_reasoning(spec_path, platform, binary):
    """Neither copy may be reduced to the code with the argument stripped out.

    The binaries-versus-datas choice and the frozen path are both decisions
    somebody will otherwise re-make from scratch, and the frozen path is the
    one T6 depends on. Losing the comment from one file is exactly as bad as
    losing it from both, because whoever reads that file reads only that file.
    """
    block = '\n'.join(_whisper_block(spec_path))

    assert 'sys._MEIPASS' in block, (
        f'{spec_path.name} must state the frozen path. This codebase has two '
        'frozen base paths and the other one does not exist on macOS.'
    )
    assert 'binaries=' in block and 'datas=' in block, (
        f'{spec_path.name} must say why the tree is declared as binaries and '
        'not datas; the two produce the same bundle, which is exactly why the '
        'reason has to be written down'
    )
    comment_lines = [ln for ln in _whisper_block(spec_path) if ln.lstrip().startswith('#')]
    assert len(comment_lines) > 40, (
        f'{spec_path.name}: the whisper block has {len(comment_lines)} comment '
        'lines. The reasoning was deleted from one copy.'
    )
