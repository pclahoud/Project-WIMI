"""The macOS build must not compile whisper.cpp for the build host's CPU (#178).

ggml defaults `GGML_NATIVE=ON`, which compiles with `-mcpu=native`. T19's
build log on a Mac mini M4:

    ARM -march/-mcpu not found, -mcpu=native will be used
    -mcpu=native+dotprod+i8mm+nosve+sme

`-mcpu=native` resolved to `apple-m4` there, emitting **`+bf16 +i8mm +sme
+sme2`**. **SME exists only on M4**; `i8mm` and `bf16` are absent on M1. So a
release cut on an M4 can emit instructions an M1, M2 or M3 cannot execute —
and it passes every test on the machine that built it, which is why this
needs a static guard rather than a runtime one.

`wimi_macos.spec` already refuses the same mistake one level up: it states
`target_arch='arm64'` rather than `None`, because *"None means whatever this
build host happens to be, so building on an Intel Mac would quietly produce
an x86_64 app"*. #178 is that, in the CPU feature set rather than the
architecture.

Text-level for the reason `test_build_spec_console_window.py` gives, and
because a shell script's effective flags cannot be recovered without running
it — which needs a Mac.

**Not the best available fix**, and the test does not pretend otherwise:
`GGML_CPU_ALL_VARIANTS` would build several CPU backends and select at
runtime, which is what the Windows build already does (T18 and T19 measured
`cascadelake` and `haswell` loading on two machines). On ARM that also needs
`GGML_BACKEND_DL` and interacts with the dylib collection #181 covers. These
assertions guard the property that matters — the artifact does not depend on
the build host's CPU — so a future switch to `ALL_VARIANTS` should update
them rather than be blocked by them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'build_macos.sh'


@pytest.fixture(scope='module')
def script_text() -> str:
    return SCRIPT.read_text(encoding='utf-8')


def test_ggml_native_is_explicitly_off(script_text: str) -> None:
    """The flag must be stated. Absent means ON, which means `-mcpu=native`."""
    assert '-DGGML_NATIVE=OFF' in script_text, (
        "build_macos.sh does not pass -DGGML_NATIVE=OFF. ggml defaults it ON "
        "and compiles with -mcpu=native, so the shipped libggml-cpu is built "
        "for whichever Mac ran the build -- an M4 emits SME/i8mm/bf16 that an "
        "M1 cannot execute (#178). Omitting the flag is not neutral."
    )


def test_it_is_in_the_cmake_invocation_not_merely_mentioned(script_text: str) -> None:
    """A flag in a comment configures nothing.

    This file is mostly comments explaining why the flag is there, so
    substring-matching alone would pass on an explanation of a fix that had
    been reverted.
    """
    configure = re.search(
        r'cmake\s+-S\s+"\$WHISPER_SRC".*?;\s*then', script_text, re.DOTALL
    )
    assert configure, 'could not find the cmake configure invocation in build_macos.sh'
    assert '-DGGML_NATIVE=OFF' in configure.group(0), (
        '-DGGML_NATIVE=OFF appears in build_macos.sh but not in the cmake '
        'configure command. A flag in a comment compiles nothing (#178).'
    )


def test_no_explicit_native_march_or_mcpu_creeps_back(script_text: str) -> None:
    """`GGML_NATIVE=OFF` plus a hand-rolled `-mcpu=native` would be the same bug.

    Comment lines are stripped first. The comment above the fix quotes T19's
    build log verbatim, `-mcpu=native+dotprod+i8mm+nosve+sme` included, and
    the evidence for the bug must not read as the bug.
    """
    code = '\n'.join(
        line for line in script_text.splitlines()
        if not line.lstrip().startswith('#')
    )
    offenders = [
        m for m in re.findall(r'-m(?:cpu|arch)=\S+', code) if 'native' in m
    ]
    assert not offenders, (
        f'build_macos.sh names a native CPU target in executable code: '
        f'{offenders}. That reintroduces #178 regardless of GGML_NATIVE.'
    )


def test_the_recorded_flags_match_the_flags_actually_passed(script_text: str) -> None:
    """The manifest records `cmake_flags` for provenance; a drifted record lies.

    Someone reading a built artifact's manifest to find out how it was
    compiled must not be told something different from what the script ran.
    """
    recorded = re.search(r'\\"cmake_flags\\":\s*\\"([^\\]*)\\"', script_text)
    assert recorded, 'no cmake_flags line found in the manifest block'
    declared = set(re.findall(r'-D[A-Za-z_]+=\S+', recorded.group(1)))

    configure = re.search(
        r'cmake\s+-S\s+"\$WHISPER_SRC".*?;\s*then', script_text, re.DOTALL
    )
    assert configure
    passed = {
        # The invocation carries shell punctuation the manifest does not:
        # quoting around '@loader_path' and the ';' that ends the `if !`.
        f.replace("'", '').replace('"', '').rstrip(';')
        for f in re.findall(r"-D[A-Za-z_]+=\S+", configure.group(0))
        if not f.startswith('-DCMAKE_BUILD_TYPE')  # not part of the recorded set
    }

    assert declared == passed, (
        f'The manifest records {sorted(declared)} but the cmake invocation '
        f'passes {sorted(passed)}. The recorded flags are how somebody later '
        f'finds out what an artifact was built with (#178).'
    )
