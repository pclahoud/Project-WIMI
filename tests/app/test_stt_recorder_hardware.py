"""The real microphone, through the real recorder (#897). Opt-in.

``test_stt_recorder.py`` drives the recorder through fakes, and a fake
cannot reproduce what #897 was: Qt's ``isFormatSupported`` answering True
for 16 kHz on a MacBook's built-in microphone, ``start()`` succeeding,
``error()`` staying ``NoError`` -- and no byte ever arriving. The only
instrument that sees that is a real device, so this file opens one.

It is skipped unless ``WIMI_STT_HARDWARE_TEST=1`` (the ``WIMI_RELEASE_BINARY``
pattern): it needs a microphone, the OS permission already granted to the
process running pytest, and about three seconds. Run it on its own, not
inside a scenario run -- it creates a ``QCoreApplication``::

    WIMI_STT_HARDWARE_TEST=1 pytest tests/app/test_stt_recorder_hardware.py --no-cov -v

**What it asserts is that audio ARRIVES, not that it is loud.** A quiet
room may sit under the silence floor, which is the floor's business and
not this test's, so a ``NO_AUDIO_CAPTURED`` from ``stop()`` is accepted
as long as frames reached the file. A capture that delivered nothing is
the #897 failure and fails here whichever way it is reported.

Measured on the MacBook Pro M1 (macOS 26.5.1, PyQt6 6.9.1 / Qt 6.9.0),
master at fde66e1 plus this fix: passes. With the 16 kHz request forced on
(``native_format_first=False``) the second test shows the restart doing the
work -- see its docstring.
"""
from __future__ import annotations

import os
import wave

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.environ.get('WIMI_STT_HARDWARE_TEST') != '1',
        reason='needs a real microphone; set WIMI_STT_HARDWARE_TEST=1 to run',
    ),
]

CAPTURE_MS = 2_500


def _record(tmp_path, **recorder_kwargs):
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

    from app.stt.errors import SttError, SttErrorKind
    from app.stt.recorder import AudioRecorder, PermissionState, check_permission

    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None
    if check_permission() is PermissionState.DENIED:
        pytest.skip('microphone permission is denied to this process')

    recorder = AudioRecorder(**recorder_kwargs)
    levels = []
    recorder.levelChanged.connect(lambda rms, peak: levels.append(peak))
    path = tmp_path / 'hardware.wav'
    started_at = recorder.start(path)

    loop = QEventLoop()
    QTimer.singleShot(CAPTURE_MS, loop.quit)
    loop.exec()

    error = None
    try:
        recording = recorder.stop()
    except SttError as exc:
        if exc.kind is not SttErrorKind.NO_AUDIO_CAPTURED:
            raise
        error = exc
        recording = None

    with wave.open(str(path), 'rb') as handle:
        frames, rate = handle.getnframes(), handle.getframerate()
    path.unlink(missing_ok=True)
    return started_at, recorder, recording, error, frames, rate, levels


def test_the_default_microphone_delivers_audio(tmp_path):
    started_at, recorder, _recording, _error, frames, rate, levels = _record(tmp_path)

    assert frames > 0, (
        f'#897: the default input ({recorder.device.label!r}) delivered no audio in '
        f'{CAPTURE_MS} ms, starting at {started_at.sample_rate} Hz')
    seconds = frames / rate
    assert seconds > (CAPTURE_MS / 1000) * 0.5, (
        f'only {seconds:.2f}s of audio in a {CAPTURE_MS} ms capture')
    assert levels, 'audio arrived but the level meter never reported'


def test_a_forced_16k_request_still_ends_up_with_audio(tmp_path):
    """The watchdog's half, against the device that motivated it.

    On the MacBook's built-in microphone a 16 kHz request delivers nothing,
    so this capture only has audio if the first-data deadline restarted it
    at the device's format. On a device where 16 kHz genuinely works it
    records at 16 kHz and passes for the plain reason. Either way, frames.
    """
    started_at, recorder, _recording, _error, frames, rate, _levels = _record(
        tmp_path, native_format_first=False)

    assert frames > 0, (
        f'#897: a 16 kHz request on {recorder.device.label!r} ended with no audio; '
        f'the restart did not rescue it')
    if started_at.sample_rate == 16_000 and rate != 16_000:
        # Recorded for the PR: the restart, not the request, produced audio.
        print(f'restarted: requested 16000 Hz, recorded at {rate} Hz')
