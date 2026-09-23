"""The macOS bundle's architecture and Info.plist keys.

Both are things whose absence is not an error message. `target_arch`
silently produces the wrong architecture if it is left to the build host,
and a missing `NSMicrophoneUsageDescription` does not deny microphone
access on macOS -- the OS **terminates the process**. That surfaces as an
unexplained crash on the least accessible platform this project ships to,
which is the worst place for a silent failure.

Asserted at the text/AST level because a `.spec` is executed by
PyInstaller with injected globals (`SPECPATH`) and cannot be imported
here. None of this can be verified by running it: macOS has never been
built at all (#143). These assertions are the only guard until it is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

MACOS_SPEC = Path(__file__).resolve().parent.parent / 'wimi_macos.spec'


def _call_kwargs(func_name: str) -> dict:
    """Literal keyword arguments of a top-level call in the spec."""
    tree = ast.parse(MACOS_SPEC.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == func_name:
            out = {}
            for kw in node.keywords:
                try:
                    out[kw.arg] = ast.literal_eval(kw.value)
                except ValueError:
                    out[kw.arg] = kw.value  # computed, not a literal
            return out
    raise AssertionError(f"no {func_name}(...) call found in {MACOS_SPEC.name}")


@pytest.mark.unit
def test_target_arch_is_stated_not_inherited():
    """`None` means "whatever this build host is" -- a silent wrong answer."""
    assert _call_kwargs('EXE').get('target_arch') == 'arm64', (
        "wimi_macos.spec must state target_arch='arm64'. None takes the "
        "build host's architecture, so building on an Intel Mac would "
        "quietly produce an x86_64 app (#59)."
    )


@pytest.mark.unit
def test_microphone_usage_description_is_present_and_explains_itself():
    """macOS kills a process that touches the mic without this key."""
    plist = _call_kwargs('BUNDLE').get('info_plist')
    assert isinstance(plist, dict), "BUNDLE must carry a literal info_plist"

    reason = plist.get('NSMicrophoneUsageDescription')
    assert reason, (
        "NSMicrophoneUsageDescription is required before anything in this "
        "bundle opens the microphone (#59). Without it macOS TERMINATES "
        "the process -- it does not return a permission error."
    )
    # The string is shown to the student in the system prompt, so it has
    # to say what is recorded and where it goes. A placeholder would ship.
    assert len(reason) > 40, f"usage string reads like a placeholder: {reason!r}"
    assert 'microphone' in reason.lower()
    assert 'never leaves' in reason.lower(), (
        "the prompt is the one place the student is told the audio stays "
        "on their machine; say so there"
    )


@pytest.mark.unit
def test_test_and_release_bundles_keep_distinct_identifiers():
    """Two bundle ids so a test build cannot replace a real install (#144)."""
    src = MACOS_SPEC.read_text(encoding='utf-8')
    assert "'com.wimi.app.test' if TEST_BUILD else 'com.wimi.app'" in src, (
        "the test and release bundles must keep distinct bundle_identifiers"
    )
