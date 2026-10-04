"""Whether this machine can run a live-audio STT scenario, and why not (#182).

The old gate was one predicate:

    not (_qt_sees_a_microphone() and shutil.which('pw-play') and WAV.is_file())
    reason='needs a microphone and pw-play: run ./scripts/dev_virtual_mic.sh start'

``pw-play`` is PipeWire's playback client. **It does not exist on Windows or
macOS and never will**, so the conjunction was unsatisfiable on both shipping
platforms — all four live-audio scenarios skipped on a Mac or a PC *with a
working microphone and a human at the keyboard*, and told that operator to run
a bash script documented in its own header as Linux-only.

The gate conflated two independent requirements:

1. **is there an input device** — platform-neutral, ask Qt;
2. **can I synthesise deterministic input** — one platform's answer to that,
   hardcoded as though it were the only one.

Only (2) is Linux-specific, and only because the test feeds a known WAV so the
assertion can be exact.

They are separated here so the reason names the condition that actually failed,
on the platform it failed on. That matters more than usual in this file's
lineage: ``test_stt_live_probe.py`` already carries *"the skip reason names the
fix, because a skip reads exactly like a pass"*, and an earlier version of the
same probe reported "no microphone" on a box that had one and **skipped both
tests green**. This is that failure arriving from a different direction — the
reason did name a fix, for one platform, and was unactionable on the two WIMI
actually ships to.

**Windows and macOS still have no injector**, so live audio remains Linux-only
in practice. What changed is that a green run on those platforms now says so in
terms an operator there can act on, instead of pointing at PipeWire. Building
the injectors is option (2) of #182 and is tracked separately; the ``_INJECTORS``
table below is the seam for it — add an entry and both scenario files start
running, with no change to either.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pytest

REPO = Path(__file__).resolve().parents[4]
WAV = REPO / 'tests' / 'fixtures' / 'stt_runtime_sample.wav'


def qt_sees_a_microphone() -> bool:
    """Ask Qt, in this interpreter, whether any input device exists.

    An earlier version shelled out with a stripped PATH, so the child could
    not import PyQt6 and the probe reported "no microphone" on a box that had
    one. That skipped both tests green. Import directly; there is no reason to
    spawn.
    """
    try:
        from PyQt6.QtCore import QCoreApplication
        from PyQt6.QtMultimedia import QMediaDevices
    except Exception:
        return False
    if QCoreApplication.instance() is None:
        QCoreApplication([])
    return bool(QMediaDevices.audioInputs())


@dataclass(frozen=True)
class _Injector:
    """A way to put known audio into whatever Qt is listening to."""

    available: Callable[[], bool]
    hint: str


#: Per-platform audio injection. Keyed by ``sys.platform``.
#:
#: A platform absent from this table has no injector, which is a statement
#: about this repository rather than about the platform: Windows has Stereo Mix
#: (active on one of the Windows machines here) and macOS has virtual devices
#: such as BlackHole. Neither is wired up. Adding an entry here is the whole
#: change — see the module docstring.
_INJECTORS: dict[str, _Injector] = {
    'linux': _Injector(
        available=lambda: shutil.which('pw-play') is not None,
        hint='run ./scripts/dev_virtual_mic.sh start (needs PipeWire)',
    ),
}

#: What an operator on a platform with no injector would have to build. Named
#: rather than left blank, so the skip is a piece of information instead of a
#: dead end.
_NO_INJECTOR_HINT: dict[str, str] = {
    'win32': (
        'no audio injector exists for Windows yet. Stereo Mix (or another '
        'loopback capture device) is the likely route: play the WAV to the '
        'default output and let Qt capture the loopback. See #182 option 2'
    ),
    'darwin': (
        'no audio injector exists for macOS yet. A virtual audio device such '
        'as BlackHole is the likely route. See #182 option 2'
    ),
}


def live_audio_skip_reason() -> Optional[str]:
    """``None`` if this machine can run a live-audio scenario, else why not.

    Each condition is reported on its own. A single conjunction cannot tell an
    operator whether to plug in a microphone, install a tool, or give up on
    this platform — and those are three different actions.
    """
    if not WAV.is_file():
        return f'the reference WAV is missing: {WAV}'

    if not qt_sees_a_microphone():
        return (
            'Qt reports no audio input device on this machine. A live-audio '
            'scenario needs one even when the audio is synthesised, because '
            'the product records through Qt'
        )

    injector = _INJECTORS.get(sys.platform)
    if injector is None:
        return _NO_INJECTOR_HINT.get(
            sys.platform,
            f'no audio injector exists for {sys.platform} yet (#182 option 2)',
        )
    if not injector.available():
        return injector.hint

    return None


#: Shared by both live-audio scenario files, so the two cannot drift apart.
requires_live_audio = pytest.mark.skipif(
    live_audio_skip_reason() is not None,
    reason=live_audio_skip_reason() or '',
)
