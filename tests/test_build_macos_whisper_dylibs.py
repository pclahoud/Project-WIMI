"""The macOS build copies each whisper.cpp library once, by install name (#181).

CMake writes one real file per library and two version symlinks beside it
(`libX.dylib`, `libX.<major>.dylib`). `build_macos.sh` used a `find` with no
`-type f`, so all three names matched and `cp` dereferenced each: the build
reported "18 shared libraries", which was six libraries three times over.
T19 measured that on a Mac mini M4 and it was re-measured on a MacBook Pro M1
at whisper.cpp 1.9.4 -- 13 MB in `vendor/whisper/macos-arm64/`, two-thirds of
it duplicate bytes.

dyld asks for each library by its INSTALL NAME (`otool -D`, e.g.
`@rpath/libwhisper.1.dylib`), so that is the one copy worth keeping and the
name it is kept under. The set is pinned as `MACOS_DYLIBS` in
`scripts/fetch_whisper.py` and the build refuses any other set -- on every
build, not just after a compile, because a `vendor/` tree from before the fix
carries all 18 under a stamp that still matches the pin.

Text-level, as `test_build_macos_targets_all_apple_silicon.py` is, because a
shell script's behaviour cannot be recovered without running it on a Mac. The
behaviour itself was measured there: see #181.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'build_macos.sh'


@pytest.fixture(scope='module')
def script_text() -> str:
    return SCRIPT.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def fetch_whisper():
    spec = importlib.util.spec_from_file_location(
        'fetch_whisper', ROOT / 'scripts' / 'fetch_whisper.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dylib_find(script_text: str) -> str:
    """The `find` that feeds the library copy loop, joined across its line break."""
    match = re.search(
        r"find \"\$WHISPER_SRC/build\".*?-print\)", script_text, re.DOTALL
    )
    assert match, 'the dylib find in build_macos.sh moved; update this test'
    return match.group(0)


def test_the_six_install_names_are_pinned(fetch_whisper) -> None:
    pinned = fetch_whisper.MACOS_DYLIBS
    assert sorted(pinned) == sorted(set(pinned)), 'the pin lists a library twice'
    assert set(pinned) == {
        'libwhisper.1.dylib',
        'libggml.0.dylib',
        'libggml-base.0.dylib',
        'libggml-cpu.0.dylib',
        'libggml-metal.0.dylib',
        'libggml-blas.0.dylib',
    }


def test_every_pinned_name_is_an_install_name_not_a_filename(fetch_whisper) -> None:
    # An install name carries the MAJOR version only. A full version
    # (libwhisper.1.9.4.dylib) is CMake's real filename, and a bare
    # libwhisper.dylib is a link nothing loads -- pinning either would
    # describe a copy dyld never asks for.
    for name in fetch_whisper.MACOS_DYLIBS:
        assert re.fullmatch(r'lib[a-z-]+\.\d+\.dylib', name), name


def test_the_find_matches_real_files_only(script_text: str) -> None:
    assert '-type f' in _dylib_find(script_text), (
        'without -type f the find also matches the two version symlinks per '
        'library and every one is copied three times (#181)'
    )


def test_each_library_is_copied_under_its_install_name(script_text: str) -> None:
    assert 'otool -D "$dylib"' in script_text
    assert 'cp "$dylib" "$WHISPER_DEST/$(basename "$install_name")"' in script_text


def test_the_build_reads_the_pin_rather_than_repeating_it(script_text: str, fetch_whisper) -> None:
    assert 'fetch_whisper.MACOS_DYLIBS' in script_text
    # Comments may name one as an example; a second LIST is what drifts.
    code = '\n'.join(
        line for line in script_text.splitlines()
        if not line.lstrip().startswith('#')
    )
    for name in fetch_whisper.MACOS_DYLIBS:
        assert name not in code, (
            f'{name} is spelled out in build_macos.sh; read it from '
            'MACOS_DYLIBS so there is one list, not two that drift'
        )


def test_the_set_is_checked_on_every_build_not_only_after_a_compile(script_text: str) -> None:
    # The compile branch ends by writing the stamp. A check placed inside it is
    # skipped whenever "Already built at <tag>" short-circuits -- which is
    # exactly the case of a stale 18-file tree from before this fix.
    stamp_written = script_text.index('} > "$WHISPER_STAMP"')
    branch_end = script_text.index('\nfi\n', stamp_written)
    check = script_text.index('if [ "$WHISPER_GOT" != "$WHISPER_EXPECTED" ]')
    assert check > branch_end
    assert check < script_text.index('[3/7]')


def test_the_printed_recipe_does_not_triplicate_either(fetch_whisper) -> None:
    recipe = fetch_whisper.MACOS_BUILD_RECIPE
    assert '-type f' in recipe
    assert 'otool -D' in recipe
    assert 'libwhisper*.dylib build/ggml' not in recipe, (
        "the old glob also matched CMake's version symlinks"
    )


# --------------------------------------------------------------------------
# #388: the dead copies are removed from the bundle, and the bundle re-sealed
# --------------------------------------------------------------------------


def _after_pyinstaller(script_text: str) -> str:
    return script_text[script_text.index('pyinstaller wimi_macos.spec'):]


def test_the_dead_copies_are_removed_after_the_bundle_exists(script_text: str) -> None:
    after = _after_pyinstaller(script_text)
    assert 'for name in $WHISPER_EXPECTED; do' in after, (
        'the removal must iterate the pinned set, not a glob')
    assert after.index('mv "dist/$DIST_NAME.app"') < after.index(
        'for name in $WHISPER_EXPECTED; do'), (
        'the removal runs before the bundle is in its final place')


def test_both_the_files_and_their_resources_symlinks_go(script_text: str) -> None:
    """Deleting only the files leaves six dangling links and the verify fails."""
    after = _after_pyinstaller(script_text)
    assert 'Contents/Frameworks/whisper/macos-arm64' in after
    assert 'Contents/Resources/whisper/macos-arm64' in after
    assert 'rm -f "$WHISPER_BUNDLED/$name" "$WHISPER_LINKS/$name"' in after


def test_nothing_is_deleted_unless_the_live_copy_is_at_the_top(script_text: str) -> None:
    after = _after_pyinstaller(script_text)
    loop = after[after.index('for name in $WHISPER_EXPECTED; do'):]
    guard = loop.index('Contents/Frameworks/$name" ]')
    assert guard < loop.index('rm -f'), (
        'the copy at the top of Frameworks/ must be checked before deleting')
    assert 'exit 1' in loop[guard:loop.index('rm -f')]


def test_the_bundle_is_resealed_keeping_entitlements_and_verified(script_text: str) -> None:
    after = _after_pyinstaller(script_text)
    rm = after.index('rm -f "$WHISPER_BUNDLED/$name"')
    sign = after.index('codesign --force --sign -', rm)
    verify = after.index('codesign --verify --deep --strict', sign)
    assert rm < sign < verify
    assert '--preserve-metadata=entitlements' in after[sign:verify], (
        'without the entitlements Chromium loses JIT and the mic loses audio-input')
    assert '--deep' not in after[sign:after.index('\n', after.index('"dist/$DIST_NAME/WIMI.app"', sign))], (
        'only the outer bundle is re-signed; nested code keeps its signatures')
