"""Capture, from the check order to the bytes on disk (#59, T7).

**This box has no microphone**, so everything below drives the recorder
through fakes standing in for ``QMediaDevices``, ``QAudioDevice``,
``QAudioSource`` and the ``QIODevice`` Qt fills. What that buys and what
it does not:

* The *arithmetic* is real. ``analyse_block`` and ``to_wav_pcm`` take
  ``bytes`` and are tested against buffers whose peak and RMS are known
  on paper -- no device involved, nothing faked.
* The *WAV* is real. Blocks go in through the same ``readyRead`` ->
  ``_drain`` -> ``_consume_block`` path production uses, and the file is
  read back with stdlib ``wave``.
* The *ordering* is real, and it is the point. Each ordering test makes
  **several failure conditions true at once** and asserts which one is
  reported. Swap two checks in ``AudioRecorder.start`` and a test that
  expects ``NO_INPUT_DEVICE`` starts getting ``PERMISSION_DENIED``,
  which is exactly the collapse ``errors.py`` warns about.
* What is *not* tested here is whether a real ``QAudioSource`` behaves
  like ``FakeAudioSource``. T2 measured the two facts these fakes are
  built on -- ``error()`` is already ``OpenError`` on a null device
  before ``start()``, and ``start()`` returns ``None`` rather than
  raising -- but a capture-and-play check on hardware is still
  outstanding and belongs to whoever has a microphone.

Markers: ``@pytest.mark.unit`` -- no ``QApplication``, no device, no
sound.
"""
from __future__ import annotations

import math
import struct
import wave

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtMultimedia import QAudio, QAudioFormat

from app.stt.errors import RETRYABLE, SttError, SttErrorKind
from app.stt.recorder import (
    LEVEL_WINDOW_US,
    SILENCE_PEAK_FLOOR,
    AudioRecorder,
    InputDevice,
    LevelAccumulator,
    PermissionState,
    analyse_block,
    list_input_devices,
    map_audio_error,
    resolve_input_device,
    to_wav_pcm,
    wav_sample_width,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def audio_format(rate=16_000, channels=1, sample_format=QAudioFormat.SampleFormat.Int16):
    """A real ``QAudioFormat`` -- it is a value type and needs no app."""
    fmt = QAudioFormat()
    fmt.setSampleRate(rate)
    fmt.setChannelCount(channels)
    fmt.setSampleFormat(sample_format)
    return fmt


class FakeAudioDevice:
    def __init__(self, identifier='mic-1', label='Fake Microphone', *,
                 null=False, supports_request=True, preferred=None):
        self._id = identifier
        self._label = label
        self._null = null
        self._supports = supports_request
        self._preferred = preferred if preferred is not None else audio_format(44_100, 2)

    def id(self):
        return self._id.encode('utf-8')

    def description(self):
        return self._label

    def isNull(self):
        return self._null

    def isFormatSupported(self, _fmt):
        return self._supports

    def preferredFormat(self):
        return self._preferred


class FakeMediaDevices:
    def __init__(self, devices, default=None):
        self._devices = list(devices)
        if default is not None:
            self._default = default
        elif self._devices:
            self._default = self._devices[0]
        else:
            self._default = FakeAudioDevice('', '', null=True)

    def audioInputs(self):
        return list(self._devices)

    def defaultAudioInput(self):
        return self._default


class FakeIO(QObject):
    """Stands in for the ``QIODevice`` ``QAudioSource.start()`` returns."""

    readyRead = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._buffer = b''

    def push(self, data):
        """Qt delivering a block: buffer it, then fire the callback."""
        self._buffer += data
        self.readyRead.emit()

    def readAll(self):
        data, self._buffer = self._buffer, b''
        return data


class FakeAudioSource(QObject):
    stateChanged = pyqtSignal(object)

    def __init__(self, device, fmt, *, error=QAudio.Error.NoError, error_on_start=None):
        super().__init__()
        self.device = device
        self.format = fmt
        self.io = FakeIO()
        self.started = False
        self.stopped = False
        self._error = error
        self._error_on_start = error_on_start

    def error(self):
        return self._error

    def start(self):
        self.started = True
        if self._error_on_start is not None:
            self._error = self._error_on_start
        return self.io

    def stop(self):
        self.stopped = True

    def fail_mid_capture(self, error):
        self._error = error
        self.stateChanged.emit(0)


def build_recorder(devices, *, permission=PermissionState.GRANTED,
                   error=QAudio.Error.NoError, error_on_start=None,
                   preferred_device_id=None):
    """A recorder over fakes, plus the list of sources it constructed."""
    constructed = []

    def factory(qt_device, fmt):
        source = FakeAudioSource(qt_device, fmt, error=error, error_on_start=error_on_start)
        constructed.append(source)
        return source

    recorder = AudioRecorder(
        preferred_device_id=preferred_device_id,
        media_devices=FakeMediaDevices(devices),
        permission_probe=lambda: permission,
        audio_source_factory=factory,
    )
    return recorder, constructed


def exploding_recorder(devices, *, permission=PermissionState.GRANTED):
    """A recorder whose factory fails the test if it is ever reached."""
    def factory(_device, _fmt):
        raise AssertionError(
            'a QAudioSource was constructed before the pre-construction '
            'checks had excluded the cases that share OpenError'
        )

    return AudioRecorder(
        media_devices=FakeMediaDevices(devices),
        permission_probe=lambda: permission,
        audio_source_factory=factory,
    )


def sine(seconds, *, rate=16_000, amplitude=0.5, freq=220.0):
    count = int(seconds * rate)
    return struct.pack('<%dh' % count, *[
        int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(count)
    ])


# ---------------------------------------------------------------------------
# 1. The check order -- the design, and what a swap would do
# ---------------------------------------------------------------------------

def test_no_devices_is_no_input_device_and_nothing_is_constructed(tmp_path):
    """Step 1. A QAudioSource must not exist yet, or OpenError means nothing."""
    recorder = exploding_recorder([], permission=PermissionState.DENIED)

    with pytest.raises(SttError) as caught:
        recorder.start(tmp_path / 'capture.wav')

    assert caught.value.kind is SttErrorKind.NO_INPUT_DEVICE
    assert not (tmp_path / 'capture.wav').exists()


def test_a_null_device_is_no_input_device_and_nothing_is_constructed(tmp_path):
    """Step 2. Permission is denied here too: step 1's answer must still win."""
    recorder = exploding_recorder(
        [FakeAudioDevice(null=True)], permission=PermissionState.DENIED
    )

    with pytest.raises(SttError) as caught:
        recorder.start(tmp_path / 'capture.wav')

    assert caught.value.kind is SttErrorKind.NO_INPUT_DEVICE


def test_a_denial_is_permission_denied_and_nothing_is_constructed(tmp_path):
    """Step 3. The device is fine, so the denial is the whole story."""
    recorder = exploding_recorder(
        [FakeAudioDevice()], permission=PermissionState.DENIED
    )

    with pytest.raises(SttError) as caught:
        recorder.start(tmp_path / 'capture.wav')

    assert caught.value.kind is SttErrorKind.PERMISSION_DENIED


def test_an_undetermined_permission_does_not_block_the_capture(tmp_path):
    """Only Denied stops us. Undetermined is what Qt says before it has asked."""
    recorder, constructed = build_recorder(
        [FakeAudioDevice()], permission=PermissionState.UNDETERMINED
    )

    recorder.start(tmp_path / 'capture.wav')

    assert constructed and constructed[0].started


def test_open_error_after_the_earlier_checks_is_device_in_use(tmp_path):
    """Step 4, and only step 4: with 1-3 excluded, OpenError means in use."""
    recorder, constructed = build_recorder(
        [FakeAudioDevice()], error=QAudio.Error.OpenError
    )

    with pytest.raises(SttError) as caught:
        recorder.start(tmp_path / 'capture.wav')

    assert caught.value.kind is SttErrorKind.DEVICE_IN_USE
    assert caught.value.retryable, 'retry works once the other app releases the mic'
    assert len(constructed) == 1, 'the source is constructed exactly once, at step 4'


def test_open_error_arriving_at_start_is_also_device_in_use(tmp_path):
    """T2: start() returns None rather than raising, so error() is the signal."""
    recorder, _ = build_recorder(
        [FakeAudioDevice()], error_on_start=QAudio.Error.OpenError
    )

    with pytest.raises(SttError) as caught:
        recorder.start(tmp_path / 'capture.wav')

    assert caught.value.kind is SttErrorKind.DEVICE_IN_USE
    assert not (tmp_path / 'capture.wav').exists(), 'a failed start leaves no file'


def test_one_source_reporting_one_error_yields_three_different_kinds(tmp_path):
    """The whole argument for the order, in one test.

    The QAudioSource is identical in all three rows -- it reports
    OpenError, which T2 found is what a null device, a busy device and
    (on Windows) a denial all look like. What separates them is which
    check ran first. Reorder ``start`` and these answers move.
    """
    scenarios = [
        ([], PermissionState.DENIED, SttErrorKind.NO_INPUT_DEVICE),
        ([FakeAudioDevice(null=True)], PermissionState.DENIED, SttErrorKind.NO_INPUT_DEVICE),
        ([FakeAudioDevice()], PermissionState.DENIED, SttErrorKind.PERMISSION_DENIED),
        ([FakeAudioDevice()], PermissionState.GRANTED, SttErrorKind.DEVICE_IN_USE),
    ]
    seen = []
    for devices, permission, _expected in scenarios:
        recorder, _ = build_recorder(
            devices, permission=permission, error=QAudio.Error.OpenError
        )
        with pytest.raises(SttError) as caught:
            recorder.start(tmp_path / 'capture.wav')
        seen.append(caught.value.kind)

    assert seen == [expected for _d, _p, expected in scenarios]


@pytest.mark.parametrize('error, expected', [
    (QAudio.Error.OpenError, SttErrorKind.DEVICE_IN_USE),
    (QAudio.Error.IOError, SttErrorKind.CAPTURE_FAILED),
    (QAudio.Error.UnderrunError, SttErrorKind.CAPTURE_FAILED),
    (QAudio.Error.FatalError, SttErrorKind.CAPTURE_FAILED),
])
def test_the_remaining_qaudio_errors_map_onto_the_catch_all(error, expected):
    assert map_audio_error(error) is expected


# ---------------------------------------------------------------------------
# 2. The arithmetic, as pure functions over known buffers
# ---------------------------------------------------------------------------

def test_silence_measures_zero():
    stats = analyse_block(b'\x00\x00' * 1600, 'int16')
    assert stats.samples == 1600
    assert stats.peak == 0.0
    assert stats.rms == 0.0


def test_a_full_scale_square_measures_one():
    block = struct.pack('<8h', *([32767, -32768] * 4))
    stats = analyse_block(block, 'int16')
    assert stats.peak == pytest.approx(1.0, abs=1e-4)
    assert stats.rms == pytest.approx(1.0, abs=1e-4)


def test_a_full_scale_sine_peaks_at_one_and_reads_root_two_below_it():
    stats = analyse_block(sine(0.1, amplitude=1.0), 'int16')
    assert stats.peak == pytest.approx(1.0, abs=1e-3)
    assert stats.rms == pytest.approx(0.7071, abs=5e-3)


def test_a_quiet_but_real_signal_measures_small_and_nonzero():
    """Well under a normal voice, well over the silence floor."""
    stats = analyse_block(sine(0.1, amplitude=0.02), 'int16')
    assert stats.peak == pytest.approx(0.02, abs=1e-3)
    assert stats.peak > SILENCE_PEAK_FLOOR * 5
    assert stats.rms > 0.0


def test_uint8_samples_are_centred_on_128():
    assert analyse_block(bytes([128] * 64), 'uint8').peak == 0.0
    assert analyse_block(bytes([255, 1]), 'uint8').peak == pytest.approx(1.0, abs=0.01)


def test_float_samples_measure_like_their_int16_equivalent():
    floats = struct.pack('<4f', 0.5, -0.5, 0.25, 0.0)
    ints = struct.pack('<4h', 16384, -16384, 8192, 0)
    as_float = analyse_block(floats, 'float')
    as_int = analyse_block(ints, 'int16')
    assert as_float.peak == pytest.approx(as_int.peak, abs=1e-4)
    assert as_float.rms == pytest.approx(as_int.rms, abs=1e-4)


def test_a_trailing_partial_sample_is_ignored_by_the_arithmetic():
    assert analyse_block(b'\x00\x01\x02', 'int16').samples == 1


def test_windows_combine_exactly_across_blocks():
    """Why BlockStats carries sum_squares and not an RMS."""
    whole = sine(0.2, amplitude=0.3)
    half = len(whole) // 2

    combined = LevelAccumulator()
    combined.add(analyse_block(whole[:half], 'int16'))
    combined.add(analyse_block(whole[half:], 'int16'))
    at_once = analyse_block(whole, 'int16')

    assert combined.rms == pytest.approx(at_once.rms, abs=1e-9)
    assert combined.peak == pytest.approx(at_once.peak, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. The silence detector -- why a silent file must never be transcribed
# ---------------------------------------------------------------------------

def test_a_muted_microphone_never_reaches_the_engine_that_invents_a_word(tmp_path):
    """The consequence the floor exists for, not the number it uses.

    T6 measured whisper.cpp against three seconds of digital silence:
    exit 0, and the word ``" you"`` on stdout. So a muted microphone
    does not produce an empty reflection -- it produces an **invented
    word in a required field**, indistinguishable from something the
    student said. Three seconds of exactly that audio, and the recorder
    must refuse to hand it on.

    Note what this does *not* depend on: Windows. The privacy toggle is
    how a recording comes to be silent on one platform; this is what
    happens to a silent file on every platform, so the check is
    unconditional.
    """
    recorder, _ = build_recorder([FakeAudioDevice()])
    path = tmp_path / 'silent.wav'
    recorder.start(path)
    recorder.capture_device.push(b'\x00\x00' * 16_000 * 3)

    with pytest.raises(SttError) as caught:
        recorder.stop()

    assert caught.value.kind is SttErrorKind.NO_AUDIO_CAPTURED
    assert SttErrorKind.NO_AUDIO_CAPTURED in RETRYABLE
    assert path.exists(), 'the file stays put; the caller decides what to do with it'


def test_a_capture_that_produced_nothing_at_all_is_also_silence(tmp_path):
    recorder, _ = build_recorder([FakeAudioDevice()])
    recorder.start(tmp_path / 'empty.wav')

    with pytest.raises(SttError) as caught:
        recorder.stop()

    assert caught.value.kind is SttErrorKind.NO_AUDIO_CAPTURED


def test_a_quiet_but_real_recording_is_not_silence(tmp_path):
    """The floor must not reject a student who simply spoke quietly."""
    recorder, _ = build_recorder([FakeAudioDevice()])
    recorder.start(tmp_path / 'quiet.wav')
    recorder.capture_device.push(sine(3.0, amplitude=0.02))

    recording = recorder.stop()

    assert not recording.silent
    assert recording.peak == pytest.approx(0.02, abs=1e-3)
    assert recording.duration_seconds == pytest.approx(3.0, abs=0.01)


def test_a_stated_failure_is_reported_instead_of_being_rediagnosed_as_silence(tmp_path):
    """A stream that died reports why it died, and keeps what it got (SS7)."""
    recorder, constructed = build_recorder([FakeAudioDevice()])
    raised = []
    recorder.errorOccurred.connect(lambda kind, detail: raised.append((kind, detail)))
    recorder.start(tmp_path / 'partial.wav')
    recorder.capture_device.push(sine(0.5, amplitude=0.4))
    constructed[0].fail_mid_capture(QAudio.Error.IOError)

    recording = recorder.stop()

    assert recording.capture_error is not None
    assert recording.capture_error.kind is SttErrorKind.CAPTURE_FAILED
    assert raised and raised[0][0] == 'capture_failed'
    assert recording.frames == 8_000, 'the first half-second survives the failure'


# ---------------------------------------------------------------------------
# 4. The WAV file
# ---------------------------------------------------------------------------

def test_the_wav_reads_back_with_what_was_written(tmp_path):
    recorder, _ = build_recorder([FakeAudioDevice()])
    path = tmp_path / 'speech.wav'
    payload = sine(1.5, amplitude=0.4)
    recorder.start(path)
    for offset in range(0, len(payload), 3200):
        recorder.capture_device.push(payload[offset:offset + 3200])

    recording = recorder.stop()

    with wave.open(str(path), 'rb') as handle:
        assert handle.getframerate() == 16_000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == len(payload) // 2
        assert handle.readframes(handle.getnframes()) == payload
    assert recording.frames == len(payload) // 2
    assert recording.duration_seconds == pytest.approx(1.5, abs=0.01)


def test_the_header_is_patched_on_close(tmp_path):
    """``writeframesraw`` leaves the sizes at zero until ``close()`` fixes them.

    Read the RIFF and data chunk sizes out of the bytes rather than
    trusting ``wave`` to read back its own convention: an unpatched
    header is a file every player reports as empty while the payload
    sits right there on disk.
    """
    recorder, _ = build_recorder([FakeAudioDevice()])
    path = tmp_path / 'patched.wav'
    payload = sine(0.25, amplitude=0.5)
    recorder.start(path)
    recorder.capture_device.push(payload)
    recorder.stop()

    raw = path.read_bytes()
    riff_size = struct.unpack('<I', raw[4:8])[0]
    data_index = raw.index(b'data')
    data_size = struct.unpack('<I', raw[data_index + 4:data_index + 8])[0]

    assert data_size == len(payload)
    assert riff_size == len(raw) - 8


def test_a_partial_frame_is_carried_over_rather_than_written(tmp_path):
    """Half a frame would make the header lie about the file's own length."""
    device = FakeAudioDevice(supports_request=False, preferred=audio_format(16_000, 2))
    recorder, _ = build_recorder([device])
    path = tmp_path / 'stereo.wav'
    recorder.start(path)

    recorder.capture_device.push(b'\x01\x02\x03\x04\x05')   # 5 bytes: one frame + 1
    recorder.capture_device.push(b'\x06\x07\x08')           # completes the second

    recording = recorder.stop()

    assert recording.frames == 2
    with wave.open(str(path), 'rb') as handle:
        assert handle.getnframes() == 2
        assert handle.readframes(2) == b'\x01\x02\x03\x04\x05\x06\x07\x08'


def test_a_float_device_is_written_to_disk_as_int16(tmp_path):
    """stdlib ``wave`` has no IEEE-float mode, and WASAPI often prefers float."""
    device = FakeAudioDevice(
        supports_request=False,
        preferred=audio_format(48_000, 1, QAudioFormat.SampleFormat.Float),
    )
    recorder, _ = build_recorder([device])
    path = tmp_path / 'float.wav'
    recorder.start(path)
    recorder.capture_device.push(struct.pack('<4f', 1.0, -1.0, 0.5, 0.0))

    recording = recorder.stop()

    assert recorder.capture_format.coding == 'float'
    assert recording.sample_width == 2
    assert recording.frames == 4
    with wave.open(str(path), 'rb') as handle:
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 48_000
        assert struct.unpack('<4h', handle.readframes(4)) == (32767, -32767, 16383, 0)


def test_to_wav_pcm_passes_integer_codings_through_untouched():
    block = struct.pack('<3h', 7, -7, 0)
    assert to_wav_pcm(block, 'int16') == block
    assert wav_sample_width('int16') == 2
    assert wav_sample_width('float') == 2


def test_abort_discards_the_file(tmp_path):
    recorder, _ = build_recorder([FakeAudioDevice()])
    path = tmp_path / 'cancelled.wav'
    recorder.start(path)
    recorder.capture_device.push(sine(0.2))

    recorder.abort()

    assert not path.exists()
    assert not recorder.is_recording


def test_stopping_when_nothing_is_running_is_a_stated_error(tmp_path):
    recorder, _ = build_recorder([FakeAudioDevice()])
    with pytest.raises(SttError) as caught:
        recorder.stop()
    assert caught.value.kind is SttErrorKind.CAPTURE_FAILED


# ---------------------------------------------------------------------------
# 5. The level meter's window
# ---------------------------------------------------------------------------

def test_the_reporting_window_is_3200_bytes_at_16k_mono_int16(tmp_path):
    """The number T7 names, taken from ``bytesForDuration`` and not hardcoded."""
    recorder, _ = build_recorder([FakeAudioDevice()])
    fmt = recorder.start(tmp_path / 'levels.wav')

    assert LEVEL_WINDOW_US == 100_000
    assert fmt.report_bytes == 3_200
    assert fmt.sample_rate == 16_000 and fmt.channels == 1 and fmt.coding == 'int16'


def test_one_level_report_per_window_however_qt_blocks_the_data(tmp_path):
    """Qt picks the block size, so the window is accumulated, not assumed."""
    recorder, _ = build_recorder([FakeAudioDevice()])
    levels = []
    recorder.levelChanged.connect(lambda rms, peak: levels.append((rms, peak)))
    recorder.start(tmp_path / 'levels.wav')

    payload = sine(0.3, amplitude=0.5)          # exactly three windows
    for offset in range(0, len(payload), 512):  # in blocks that do not divide it
        recorder.capture_device.push(payload[offset:offset + 512])
    recorder.stop()

    assert len(levels) == 3
    assert all(0.0 < peak <= 1.0 for _rms, peak in levels)


def test_a_muted_stream_reports_a_flat_line_while_it_runs(tmp_path):
    """The honest half of the detection: the student sees it as they speak."""
    recorder, _ = build_recorder([FakeAudioDevice()])
    levels = []
    recorder.levelChanged.connect(lambda rms, peak: levels.append((rms, peak)))
    recorder.start(tmp_path / 'muted.wav')

    recorder.capture_device.push(b'\x00\x00' * 16_000)   # one second of zeros

    assert len(levels) == 10
    assert all(rms == 0.0 and peak == 0.0 for rms, peak in levels)


# ---------------------------------------------------------------------------
# 6. Format: a request, never a requirement
# ---------------------------------------------------------------------------

def test_a_device_that_accepts_the_request_records_at_16k_mono_int16(tmp_path):
    recorder, _ = build_recorder([FakeAudioDevice(supports_request=True)])
    fmt = recorder.start(tmp_path / 'ok.wav')

    assert not fmt.degraded
    assert (fmt.sample_rate, fmt.channels, fmt.sample_width) == (16_000, 1, 2)


def test_a_device_that_refuses_it_records_at_its_preferred_format(tmp_path):
    """A quality choice, not a failure: whisper.cpp resamples internally (T1)."""
    device = FakeAudioDevice(supports_request=False, preferred=audio_format(44_100, 2))
    recorder, _ = build_recorder([device])
    path = tmp_path / 'preferred.wav'

    fmt = recorder.start(path)
    recorder.capture_device.push(sine(0.1, rate=44_100 * 2, amplitude=0.6))
    recording = recorder.stop()

    assert fmt.degraded
    assert (fmt.sample_rate, fmt.channels) == (44_100, 2)
    assert fmt.report_bytes == 17_640, '100 ms of 44.1 kHz stereo Int16'
    assert recording.degraded_format
    with wave.open(str(path), 'rb') as handle:
        assert handle.getframerate() == 44_100
        assert handle.getnchannels() == 2


def test_an_unusable_preferred_format_is_a_stated_capture_failure(tmp_path):
    """T2's probe box answered preferredFormat() with all zeros."""
    empty = QAudioFormat()
    recorder, _ = build_recorder([FakeAudioDevice(supports_request=False, preferred=empty)])

    with pytest.raises(SttError) as caught:
        recorder.start(tmp_path / 'nope.wav')

    assert caught.value.kind is SttErrorKind.CAPTURE_FAILED


# ---------------------------------------------------------------------------
# 7. Which microphone -- device_settings.stt_input_device_id (T8)
# ---------------------------------------------------------------------------

def devices_for_resolution():
    return [
        InputDevice(id='built-in', label='Built-in', is_default=True),
        InputDevice(id='usb-headset', label='USB Headset', is_default=False),
    ]


def test_no_preference_takes_the_default_device():
    device, honoured = resolve_input_device(devices_for_resolution(), None)
    assert device.id == 'built-in'
    assert honoured


def test_a_stored_device_id_is_honoured():
    device, honoured = resolve_input_device(devices_for_resolution(), 'usb-headset')
    assert device.id == 'usb-headset'
    assert honoured


def test_an_unplugged_preferred_device_falls_back_to_the_default():
    """An unplugged USB mic must not brick the feature."""
    device, honoured = resolve_input_device(devices_for_resolution(), 'usb-headset-gone')
    assert device.id == 'built-in'
    assert not honoured, 'the UI may want to say the choice could not be kept'


def test_the_recorder_records_from_the_device_it_was_pointed_at(tmp_path):
    devices = [FakeAudioDevice('built-in', 'Built-in'), FakeAudioDevice('usb', 'USB Headset')]
    recorder, constructed = build_recorder(devices, preferred_device_id='usb')

    recorder.start(tmp_path / 'chosen.wav')

    assert recorder.device.id == 'usb'
    assert recorder.device_choice_honoured
    assert constructed[0].device is devices[1]


def test_the_recorder_falls_back_when_the_stored_device_is_gone(tmp_path):
    devices = [FakeAudioDevice('built-in', 'Built-in')]
    recorder, constructed = build_recorder(devices, preferred_device_id='usb-gone')

    recorder.start(tmp_path / 'fallback.wav')

    assert recorder.device.id == 'built-in'
    assert not recorder.device_choice_honoured
    assert constructed[0].device is devices[0]


def test_listing_devices_reports_id_label_and_which_one_is_default():
    devices = [FakeAudioDevice('a', 'Mic A'), FakeAudioDevice('b', 'Mic B')]
    listed = list_input_devices(FakeMediaDevices(devices, default=devices[1]))

    assert [(d.id, d.label, d.is_default) for d in listed] == [
        ('a', 'Mic A', False),
        ('b', 'Mic B', True),
    ]


def test_listing_devices_on_a_machine_with_none_returns_nothing():
    assert list_input_devices(FakeMediaDevices([])) == []
