"""Microphone to WAV file, on the Qt main thread (#59, T7).

Everything between the microphone and a file on disk: enumerate, resolve
which device the student chose, ask permission, open the stream, write
the frames, measure the level, and stop. The failure taxonomy in
``errors.py`` is designed in here rather than discovered -- in
particular **the check order in that module's docstring is implemented
literally**, in :meth:`AudioRecorder.start`, and
``tests/app/test_stt_recorder.py`` fails if two of the checks swap
places.

Nothing in this module runs on a worker thread. ``QAudioSource`` is a
Qt object with a Qt event loop behind it, and ``base_db.py`` already
records that nothing in this application writes from a second thread.
Transcription is the part that goes to a worker (T6); capture does not.

Three things here are load-bearing and easy to "tidy" back into bugs
------------------------------------------------------------------

**1. The order of the checks, not the enum, separates the failures.**
T2 measured ``QAudioSource.error()`` returning ``OpenError`` *immediately
after construction* against a null device, before ``start()`` was called,
and ``start()`` returning ``None`` rather than raising. So "no
microphone", "another app holds it" and a Windows permission denial are
one indistinguishable value at one moment. ``start()`` therefore checks
the device list, then the resolved device, then permission, and only
**then** constructs a ``QAudioSource``. See ``errors.py``.

**2. The peak floor is a detector, not a safeguard, and it is
unconditional.** With Windows' *Let desktop apps access your microphone*
switched off, the capture stack denies nothing: it delivers a stream of
zeros and every API reports success. Qt has no Windows permission
backend (its stub is commented *"Optimistically returning Granted"*), so
step 3 never fires there and :data:`SILENCE_PEAK_FLOOR` is the **only**
thing this feature has that notices. But the reason it must fire is not
Windows-shaped at all: **T6 measured whisper.cpp against three seconds
of digital silence and got exit 0 and the word** ``" you"``. A silent
file is not transcribed to nothing -- it is transcribed to an invented
word, in a required field, looking exactly like something the student
said. See the constant.

**3. 16 kHz mono Int16 is asked for, never required.** T1 measured a
44.1 kHz stereo WAV transcribing byte-identically to the 16 kHz mono
original, because whisper.cpp resamples internally through bundled
miniaudio. A device that refuses the request costs a larger temporary
file, not a feature. :attr:`CaptureFormat.degraded` says it happened so
the UI can be honest about it; it is never raised as an error.

Pull mode, because push mode does not survive the PyQt6 bindings
----------------------------------------------------------------

The plan (§T7) specifies **push mode**: a ``QIODevice`` subclass handed
to ``QAudioSource.start(device)``, whose ``writeData()`` is the single
callback. That mechanism cannot be implemented on the pinned bindings.
Measured here on **PyQt6 6.9.1 / Qt 6.9.0 / sip 6.16.0**, on a plain
``QIODevice`` subclass opened ``WriteOnly``:

* ``writeData`` is invoked with **one argument, an ``int``** -- the
  *length* of the data. The bytes are never passed. The type stub says
  ``writeData(self, a0: PyQt6.sip.Buffer) -> int``, and ``PyQt6.sip``
  has no ``Buffer`` attribute at runtime.
* Returning an ``int`` (the count a ``writeData`` override is documented
  to return) raises ``TypeError: invalid result from Sink.writeData()``
  and **aborts the process**. So do ``bytes``, ``memoryview``, ``float``
  and ``bool``.
* The only accepted returns are ``None`` -- after which ``write()``
  reports ``-1``, i.e. failure, to ``QAudioSource`` -- or a *writable
  buffer* (``bytearray``/``QByteArray``), whose length becomes the
  byte count. That is ``readData``'s contract, on ``writeData``.

Either way the audio bytes are unreachable from Python. So capture uses
**pull mode**: ``QAudioSource.start()`` with no argument returns a
``QIODevice`` that Qt fills, and its ``readyRead`` signal is the
callback. Everything the plan wanted from push mode survives -- one
callback per block, one pass over the data in
:meth:`AudioRecorder._consume_block`, and no timer to keep in step with
the stream -- and the 100 ms reporting window is still sized with
``QAudioFormat.bytesForDuration()`` (3,200 bytes at 16 kHz mono Int16,
confirmed). If a future PyQt6 fixes the virtual, push mode becomes an
alternative, not an improvement.

Plan: ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §3.1, §7.
"""

from __future__ import annotations

import array
import logging
import math
import wave
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QCoreApplication, QMicrophonePermission, QObject, Qt, pyqtSignal
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices

from .errors import SttError, SttErrorKind

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# What we ask a device for, and how we measure what it gives back
# ---------------------------------------------------------------------------

#: The format we ask for. A request, not a requirement -- see the module
#: docstring's point 3.
REQUESTED_SAMPLE_RATE = 16_000
REQUESTED_CHANNELS = 1

#: How much audio one level report covers, in microseconds. Passed to
#: ``QAudioFormat.bytesForDuration``, which answers **3,200 bytes** at
#: 16 kHz mono Int16. Qt delivers blocks at whatever cadence its backend
#: chooses, so the window is accumulated across blocks rather than
#: assumed to be one.
LEVEL_WINDOW_US = 100_000

#: Peak amplitude, normalised to 0.0-1.0, below which a recording is
#: reported as :attr:`SttErrorKind.NO_AUDIO_CAPTURED` instead of being
#: transcribed.
#:
#: **What this is protecting against, and there are two things, not
#: one.** The second is the reason the floor is unconditional.
#:
#: 1. *How a recording comes to be silent, on Windows.* **Settings ->
#:    Privacy & security -> Microphone -> Let desktop apps access your
#:    microphone**, switched off. Nothing fails: ``QAudioSource`` opens,
#:    ``readyRead`` fires, frames arrive, the file grows -- and every
#:    sample is zero. Qt has no Windows permission backend to ask (T2
#:    finding 4), so no error surfaces anywhere and the student speaks
#:    for ninety seconds into a file of silence.
#:
#: 2. *What happens to a silent file downstream, on every platform.*
#:    **The engine does not return nothing. T6 measured whisper.cpp
#:    against three seconds of digital silence and got exit 0 and the
#:    word ``" you"``.** So without this check a muted microphone does
#:    not produce an empty reflection -- it produces an invented word,
#:    dropped into a required field, indistinguishable from something
#:    the student said. That is worse than an empty transcript and worse
#:    than an error, because it is wrong and it looks fine.
#:
#: Reason 1 is why silence happens and is Windows-shaped. **Reason 2 is
#: why silence must never be transcribed and has no platform**: a muted
#: input on macOS, a mic gain at zero, a capture that opened against the
#: wrong device -- any of them reaches the same hallucinated sentence.
#: Anyone porting this, or tempted to drop the check on a platform where
#: the privacy toggle does not exist, is looking at the wrong reason.
#:
#: 0.002 is roughly 64 counts at Int16 (-54 dBFS). It sits ~30x above a
#: single-LSB dither (a stack that emits near-zero noise rather than
#: exact zeros still reads as silent) and far below any real speech,
#: whose peaks run 0.05-0.9 even from a distant, quiet talker. A
#: recording that a human would call "quiet but audible" must not trip
#: it; ``test_a_quiet_but_real_recording_is_not_silence`` is that guard.
SILENCE_PEAK_FLOOR = 0.002


class PermissionState(str, Enum):
    """Microphone permission, as three plain values.

    Deliberately not ``Qt.PermissionStatus``: callers and tests should
    not need Qt imported to reason about permission, and on Windows this
    value is decorative anyway (Qt's stub returns Granted regardless of
    what the OS thinks).
    """

    GRANTED = 'granted'
    DENIED = 'denied'
    UNDETERMINED = 'undetermined'


@dataclass(frozen=True)
class _Coding:
    """How one ``QAudioFormat.SampleFormat`` is laid out in memory."""

    typecode: str      # array module typecode, native endianness (what Qt gives us)
    width: int         # bytes per sample
    offset: int        # value subtracted to centre the samples (UInt8 only)
    scale: float       # divisor that maps a centred sample onto -1.0..1.0
    wav_coding: str    # what it becomes in the WAV file (see to_wav_pcm)


#: Sample codings by short name. The name, not the Qt enum, is what the
#: pure functions below take, so the arithmetic is testable with nothing
#: but ``bytes``.
SAMPLE_CODINGS = {
    'uint8': _Coding('B', 1, 128, 128.0, 'uint8'),
    'int16': _Coding('h', 2, 0, 32768.0, 'int16'),
    'int32': _Coding('i', 4, 0, 2147483648.0, 'int32'),
    # WAV is a PCM container; stdlib `wave` writes WAVE_FORMAT_PCM and
    # has no IEEE-float mode. A float-preferring device (WASAPI often
    # does) is therefore converted to Int16 on the way to disk. That is
    # a format conversion, not a resample, and it happens one block at a
    # time in `to_wav_pcm`.
    'float': _Coding('f', 4, 0, 1.0, 'int16'),
}

# `array` typecode sizes are platform-defined. Everything above assumes
# the widths in the table; a platform where they differ would write a
# WAV whose header lies about its own frames.
for _name, _spec in SAMPLE_CODINGS.items():
    if array.array(_spec.typecode).itemsize != _spec.width:
        raise RuntimeError(
            f"array typecode {_spec.typecode!r} is "
            f"{array.array(_spec.typecode).itemsize} bytes here, not {_spec.width}"
        )
del _name, _spec


@dataclass(frozen=True)
class BlockStats:
    """One pass over one block of audio: how loud, and how much of it."""

    samples: int
    peak: float          # 0.0-1.0
    sum_squares: float   # of the normalised samples, so windows combine exactly

    @property
    def rms(self) -> float:
        if self.samples <= 0:
            return 0.0
        return math.sqrt(self.sum_squares / self.samples)


def analyse_block(data: bytes, coding: str) -> BlockStats:
    """Peak and sum-of-squares for one block, in a single pass.

    ``sum_squares`` rather than an RMS so that a window spanning several
    blocks -- which is the normal case, since Qt picks the block size --
    combines without weighting error. Trailing bytes that do not make a
    whole sample are ignored here; :meth:`AudioRecorder._consume_block`
    is what carries them over to the next block.
    """
    spec = SAMPLE_CODINGS[coding]
    usable = len(data) - (len(data) % spec.width)
    if usable <= 0:
        return BlockStats(0, 0.0, 0.0)

    buf = array.array(spec.typecode)
    buf.frombytes(bytes(data[:usable]))
    values: Sequence[Any] = [v - spec.offset for v in buf] if spec.offset else buf

    # max(max, -min) rather than max(abs(v) for v in ...): both branches
    # are one C-level pass, and Python ints do not overflow on -(-32768).
    peak_raw = max(max(values), -min(values))
    peak = min(1.0, abs(peak_raw) / spec.scale)

    total = 0.0
    for value in values:
        total += value * value
    return BlockStats(len(buf), peak, total / (spec.scale * spec.scale))


def to_wav_pcm(data: bytes, coding: str) -> bytes:
    """The bytes as they go into the WAV file.

    Identity for the integer codings -- Qt hands over native-endian PCM
    and that is exactly what ``wave`` wants. Float is converted to Int16,
    because stdlib ``wave`` has no IEEE-float mode and pulling in a
    dependency to store a format whisper.cpp will resample anyway is a
    bad trade.
    """
    spec = SAMPLE_CODINGS[coding]
    if spec.wav_coding == coding:
        return bytes(data)

    usable = len(data) - (len(data) % spec.width)
    src = array.array(spec.typecode)
    src.frombytes(bytes(data[:usable]))
    out = array.array('h')
    for value in src:
        # Clamp before scaling: a float stream may exceed 1.0, and
        # wrapping it would turn a loud passage into a click.
        clamped = -1.0 if value < -1.0 else (1.0 if value > 1.0 else value)
        out.append(int(clamped * 32767.0))
    return out.tobytes()


def wav_sample_width(coding: str) -> int:
    """Bytes per sample in the WAV file, which is not always the capture width."""
    return SAMPLE_CODINGS[SAMPLE_CODINGS[coding].wav_coding].width


class LevelAccumulator:
    """Running peak and RMS over as many blocks as you feed it."""

    def __init__(self) -> None:
        self.samples = 0
        self.byte_count = 0
        self.peak = 0.0
        self._sum_squares = 0.0

    def add(self, stats: BlockStats, byte_count: int = 0) -> None:
        self.samples += stats.samples
        self.byte_count += byte_count
        self._sum_squares += stats.sum_squares
        if stats.peak > self.peak:
            self.peak = stats.peak

    @property
    def rms(self) -> float:
        if self.samples <= 0:
            return 0.0
        return math.sqrt(self._sum_squares / self.samples)

    def reset(self) -> None:
        self.samples = 0
        self.byte_count = 0
        self.peak = 0.0
        self._sum_squares = 0.0


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InputDevice:
    """One microphone, as the settings UI and the recorder see it.

    ``id`` is ``QAudioDevice.id()`` decoded to text. It is what
    ``device_settings.stt_input_device_id`` stores (T8) -- a device id
    names a machine's hardware, so it is device-local and must not
    travel in a ``.wimi``; see CLAUDE.md's *Device Identity*.
    """

    id: str
    label: str
    is_default: bool
    is_null: bool = False
    #: The underlying ``QAudioDevice``. Excluded from equality and repr
    #: so a test can build one of these from nothing.
    qt_device: Any = field(default=None, compare=False, repr=False)


def device_identifier(qt_device: Any) -> str:
    """``QAudioDevice.id()`` as text, decoded the same way every time."""
    raw = qt_device.id()
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).decode('utf-8', 'replace')
    try:
        return bytes(raw.data()).decode('utf-8', 'replace')   # QByteArray
    except AttributeError:
        return str(raw)


class _QtMediaDevices:
    """The default seam onto ``QMediaDevices``' statics, so tests can replace it."""

    def audioInputs(self) -> List[Any]:
        return list(QMediaDevices.audioInputs())

    def defaultAudioInput(self) -> Any:
        return QMediaDevices.defaultAudioInput()


def list_input_devices(media_devices: Any = None) -> List[InputDevice]:
    """Every microphone this machine currently offers, default first-flagged."""
    source = media_devices or _QtMediaDevices()
    default = source.defaultAudioInput()
    default_id = device_identifier(default) if default is not None and not default.isNull() else None
    devices: List[InputDevice] = []
    for qt_device in source.audioInputs():
        identifier = device_identifier(qt_device)
        devices.append(InputDevice(
            id=identifier,
            label=qt_device.description(),
            is_default=identifier == default_id,
            is_null=qt_device.isNull(),
            qt_device=qt_device,
        ))
    return devices


def resolve_input_device(
    devices: Sequence[InputDevice],
    preferred_id: Optional[str],
) -> Tuple[Optional[InputDevice], bool]:
    """Pick the device to record from, and say whether the choice was honoured.

    Returns ``(device, honoured)``. ``honoured`` is False when a stored
    ``stt_input_device_id`` named a device that is no longer here -- an
    unplugged USB headset must fall back to the default rather than
    brick the feature, and the UI may want to say so once.
    """
    if not devices:
        return None, preferred_id is None

    if preferred_id:
        for device in devices:
            if device.id == preferred_id:
                return device, True

    for device in devices:
        if device.is_default:
            return device, preferred_id is None
    return devices[0], preferred_id is None


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------

_PERMISSION_STATES = {
    Qt.PermissionStatus.Granted: PermissionState.GRANTED,
    Qt.PermissionStatus.Denied: PermissionState.DENIED,
    Qt.PermissionStatus.Undetermined: PermissionState.UNDETERMINED,
}


def check_permission() -> PermissionState:
    """Current microphone permission.

    **Expect ``GRANTED`` on Windows, always.** Qt has no Windows
    permission backend: ``qpermissions.cpp`` falls through to a stub
    commented *"Optimistically returning Granted"*, and Qt's own 6.5
    announcement lists backends for macOS/iOS/Android/WASM only. Nothing
    Windows-specific may be built on this return value; the peak check
    at :data:`SILENCE_PEAK_FLOOR` is that platform's only detector.

    With no ``QCoreApplication`` yet -- which no production path has, but
    a test might -- there is nobody to ask, so the answer is
    ``UNDETERMINED`` rather than a guess in either direction.
    """
    app = QCoreApplication.instance()
    if app is None:
        return PermissionState.UNDETERMINED
    return _PERMISSION_STATES.get(
        app.checkPermission(QMicrophonePermission()), PermissionState.UNDETERMINED
    )


def request_permission(callback: Callable[[PermissionState], None]) -> None:
    """Ask for microphone permission and hand the outcome to ``callback``.

    Meaningful on macOS, where TCC prompts once and then remembers the
    answer system-wide. On Windows it resolves Granted without asking
    anyone (see :func:`check_permission`).

    The handler Qt invokes is typed as receiving the permission object,
    and ``QMicrophonePermission`` carries no ``status()`` of its own in
    these bindings -- so when the object cannot answer, the result is
    re-read with :func:`check_permission` rather than assumed.
    """
    app = QCoreApplication.instance()
    if app is None:
        callback(PermissionState.UNDETERMINED)
        return

    def _handler(permission: Any) -> None:
        status = getattr(permission, 'status', None)
        if callable(status):
            callback(_PERMISSION_STATES.get(status(), PermissionState.UNDETERMINED))
        else:
            callback(check_permission())

    app.requestPermission(QMicrophonePermission(), _handler)


# ---------------------------------------------------------------------------
# The recording itself
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaptureFormat:
    """The format a recording is actually running at."""

    sample_rate: int
    channels: int
    coding: str
    #: Bytes per sample in the WAV file. Differs from the capture width
    #: when a float-preferring device sent us to Int16.
    sample_width: int
    #: Bytes of captured audio per level report -- ``bytesForDuration``
    #: of :data:`LEVEL_WINDOW_US`, which is 3,200 at 16 kHz mono Int16.
    report_bytes: int
    #: True when the device refused 16 kHz mono Int16 and we took its
    #: ``preferredFormat()`` instead. A quality note, never a failure.
    degraded: bool

    @property
    def capture_frame_bytes(self) -> int:
        return SAMPLE_CODINGS[self.coding].width * self.channels

    @property
    def wav_frame_bytes(self) -> int:
        return self.sample_width * self.channels


@dataclass(frozen=True)
class Recording:
    """What a finished capture produced."""

    path: Path
    sample_rate: int
    channels: int
    sample_width: int
    frames: int
    peak: float
    rms: float
    degraded_format: bool
    #: Set when the stream failed part-way. The file is still here and
    #: still holds everything that arrived before the failure -- do not
    #: discard the student's first sentence to report a problem with
    #: their second (§7).
    capture_error: Optional[SttError] = None

    @property
    def duration_seconds(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return self.frames / float(self.sample_rate)

    @property
    def silent(self) -> bool:
        return self.peak < SILENCE_PEAK_FLOOR


class _WavSink:
    """Incremental WAV writing: frames as they arrive, header patched on close.

    ``writeframesraw`` appends without touching the header;
    ``Wave_write.close()`` seeks back and fixes the sizes. T2 validated
    this, which is why there is no hand-rolled 44-byte header here.
    """

    def __init__(self, path: Path, *, sample_rate: int, channels: int, sample_width: int) -> None:
        self.path = path
        self._writer = wave.open(str(path), 'wb')
        self._writer.setnchannels(channels)
        self._writer.setsampwidth(sample_width)
        self._writer.setframerate(sample_rate)
        self.bytes_written = 0

    def write(self, data: bytes) -> None:
        if not data:
            return
        self._writer.writeframesraw(data)
        self.bytes_written += len(data)

    def close(self) -> None:
        self._writer.close()


def map_audio_error(error: Any) -> SttErrorKind:
    """A ``QAudio.Error`` onto the taxonomy, **after** the pre-construction checks.

    Only reached once an empty device list, a null device and a denial
    have been excluded, which is what lets ``OpenError`` mean
    "something else has the microphone" here. Reached any earlier it
    means all three at once and none of them usefully.
    """
    name = getattr(error, 'name', None) or str(error)
    if 'OpenError' in name:
        return SttErrorKind.DEVICE_IN_USE
    return SttErrorKind.CAPTURE_FAILED


class AudioRecorder(QObject):
    """One microphone capture, from ``start(path)`` to ``stop()``.

    Main thread only. Construct one per window (or one per capture --
    it is cheap); ``start`` and ``stop`` may be called repeatedly.

    Signals
    -------
    ``levelChanged(rms, peak)``
        Every :data:`LEVEL_WINDOW_US` of audio, both normalised 0.0-1.0.
        This is what drives the live level meter, which is the honest
        half of the silent-capture detection: the student sees a flat
        line *while they are still speaking* rather than ninety seconds
        later.
    ``errorOccurred(kind, detail)``
        The stream failed part-way. ``kind`` is an
        :class:`~app.stt.errors.SttErrorKind` value. The capture keeps
        whatever already reached the file and ``stop()`` still returns a
        :class:`Recording`, with ``capture_error`` set.

    The Qt seams are injectable because the check order is the design
    and a test has to be able to prove no ``QAudioSource`` was
    constructed before it was allowed to be.
    """

    levelChanged = pyqtSignal(float, float)
    errorOccurred = pyqtSignal(str, str)

    def __init__(
        self,
        *,
        preferred_device_id: Optional[str] = None,
        media_devices: Any = None,
        permission_probe: Optional[Callable[[], PermissionState]] = None,
        audio_source_factory: Optional[Callable[[Any, QAudioFormat], Any]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        """
        ``preferred_device_id`` is ``device_settings.stt_input_device_id``
        (T8), read by the caller and passed in -- this module never
        touches a database. ``None`` means "use the default device",
        and an id that no longer matches any device falls back to the
        default rather than failing (:func:`resolve_input_device`).
        """
        super().__init__(parent)
        self.preferred_device_id = preferred_device_id
        self._media_devices = media_devices or _QtMediaDevices()
        self._permission_probe = permission_probe or check_permission
        self._audio_source_factory = audio_source_factory or self._build_audio_source

        self._source: Any = None
        self._io: Any = None
        self._sink: Optional[_WavSink] = None
        self._format: Optional[CaptureFormat] = None
        self._path: Optional[Path] = None
        self._overall = LevelAccumulator()
        self._window = LevelAccumulator()
        self._pending = b''
        self._capture_error: Optional[SttError] = None
        self._device: Optional[InputDevice] = None
        self._device_honoured = True

    # -- state ----------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._sink is not None

    @property
    def capture_format(self) -> Optional[CaptureFormat]:
        return self._format

    @property
    def device(self) -> Optional[InputDevice]:
        """The device this capture resolved to, once started."""
        return self._device

    @property
    def device_choice_honoured(self) -> bool:
        """False when ``preferred_device_id`` named a device that is gone."""
        return self._device_honoured

    @property
    def capture_device(self) -> Any:
        """The ``QIODevice`` Qt is filling. ``None`` when not recording."""
        return self._io

    # -- the check order ------------------------------------------------

    def start(self, path: Any) -> CaptureFormat:
        """Open the microphone and begin writing ``path``.

        Runs ``errors.py``'s check order **in that order**. Raises
        :class:`~app.stt.errors.SttError`; on any failure nothing is
        left open and no file is left behind.
        """
        if self.is_recording:
            raise SttError(SttErrorKind.CAPTURE_FAILED, 'a recording is already running')

        # 1. No microphones at all. Before anything else, and before any
        #    QAudioSource exists -- see the module docstring.
        devices = list_input_devices(self._media_devices)
        if not devices:
            raise SttError(SttErrorKind.NO_INPUT_DEVICE, 'no audio input devices')

        # 2. The device we resolved to is null.
        device, honoured = resolve_input_device(devices, self.preferred_device_id)
        if device is None or device.is_null or device.qt_device is None:
            raise SttError(SttErrorKind.NO_INPUT_DEVICE, 'the selected audio input device is null')
        if not honoured:
            logger.info(
                "stt: preferred input device %r is gone; falling back to %r",
                self.preferred_device_id, device.label,
            )

        # 3. Permission. Meaningful on macOS; on Windows this is Granted
        #    regardless of what the OS thinks, so nothing may depend on
        #    it there.
        if self._permission_probe() is PermissionState.DENIED:
            raise SttError(SttErrorKind.PERMISSION_DENIED, 'microphone permission denied')

        # 4. Only now is a QAudioSource allowed to exist.
        qt_format, capture_format = self._resolve_format(device)
        source = self._audio_source_factory(device.qt_device, qt_format)
        error = source.error()
        if error is not None and self._is_error(error):
            raise SttError(
                map_audio_error(error),
                f'QAudioSource reported {getattr(error, "name", error)} on construction',
            )

        self._device = device
        self._device_honoured = honoured
        self._format = capture_format
        self._path = Path(path)
        self._overall = LevelAccumulator()
        self._window = LevelAccumulator()
        self._pending = b''
        self._capture_error = None
        self._source = source

        try:
            self._sink = _WavSink(
                self._path,
                sample_rate=capture_format.sample_rate,
                channels=capture_format.channels,
                sample_width=capture_format.sample_width,
            )
        except OSError as exc:
            self._source = None
            raise SttError(SttErrorKind.CAPTURE_FAILED, f'cannot write {self._path}: {exc}') from exc

        try:
            self._begin_stream(source)
        except SttError:
            self._teardown(delete_file=True)
            raise
        return capture_format

    def _begin_stream(self, source: Any) -> None:
        io = source.start()
        error = source.error()
        if error is not None and self._is_error(error):
            raise SttError(
                map_audio_error(error),
                f'QAudioSource reported {getattr(error, "name", error)} on start',
            )
        if io is None:
            # start() returns None rather than raising (T2), so a None
            # here with no error set is a failure with nothing to
            # report -- which is exactly the catch-all's job.
            raise SttError(SttErrorKind.CAPTURE_FAILED, 'QAudioSource.start() returned no device')

        self._io = io
        io.readyRead.connect(self._drain)
        state_changed = getattr(source, 'stateChanged', None)
        if state_changed is not None:
            state_changed.connect(self._on_state_changed)

    # -- the one callback -----------------------------------------------

    def _drain(self) -> None:
        """``readyRead``: take everything Qt has, in one pass."""
        if self._io is None or self._sink is None:
            return
        data = bytes(self._io.readAll())
        if data:
            self._consume_block(data)

    def _consume_block(self, data: bytes) -> None:
        """Append to the WAV and update the running level. One pass.

        Every byte is analysed exactly once and written exactly once.
        The block is cut at the reporting-window boundary rather than
        taken whole, because Qt -- not this module -- decides how much
        audio arrives per callback: a block carrying half a window must
        not report, and a block carrying a second of audio (a stalled
        UI thread, and that is precisely when a meter matters) owes ten
        reports rather than one averaged over the whole second.

        Driven directly by ``tests/app/test_stt_recorder.py``, because a
        fake ``QIODevice`` is the only way to exercise this without a
        microphone.
        """
        fmt = self._format
        sink = self._sink
        if fmt is None or sink is None:
            return

        # Carry a partial frame over rather than writing it: `wave`
        # counts frames by dividing bytes, so half a frame makes the
        # header lie about the file's own length.
        buffered = self._pending + bytes(data)
        frame_bytes = fmt.capture_frame_bytes
        usable = len(buffered) - (len(buffered) % frame_bytes)
        self._pending = buffered[usable:]
        block = buffered[:usable]

        offset = 0
        while offset < len(block):
            remaining = fmt.report_bytes - self._window.byte_count
            if remaining <= 0:                              # pragma: no cover - reset below
                remaining = fmt.report_bytes
            piece = block[offset:offset + remaining]
            offset += len(piece)

            stats = analyse_block(piece, fmt.coding)
            self._overall.add(stats, len(piece))
            self._window.add(stats, len(piece))
            sink.write(to_wav_pcm(piece, fmt.coding))

            if self._window.byte_count >= fmt.report_bytes:
                self.levelChanged.emit(self._window.rms, self._window.peak)
                self._window.reset()

    def _on_state_changed(self, _state: Any) -> None:
        source = self._source
        if source is None:
            return
        error = source.error()
        if error is None or not self._is_error(error):
            return
        kind = map_audio_error(error)
        detail = f'QAudioSource reported {getattr(error, "name", error)} while recording'
        if self._capture_error is None:
            self._capture_error = SttError(kind, detail)
            logger.warning("stt: %s", detail)
            self.errorOccurred.emit(kind.value, detail)

    # -- stopping --------------------------------------------------------

    def stop(self) -> Recording:
        """Stop, close the file, and report what was captured.

        Raises :attr:`SttErrorKind.NO_AUDIO_CAPTURED` when the peak never
        rose above :data:`SILENCE_PEAK_FLOOR` and nothing else already
        went wrong -- a capture that failed for a *stated* reason is
        reported as that reason, not re-diagnosed as silence. The WAV is
        left on disk either way, at the path given to :meth:`start`.
        """
        if not self.is_recording:
            raise SttError(SttErrorKind.CAPTURE_FAILED, 'no recording in progress')

        fmt = self._format
        assert fmt is not None and self._path is not None   # guarded by is_recording

        source = self._source
        if source is not None:
            try:
                source.stop()
            except Exception as exc:                        # pragma: no cover - Qt teardown
                logger.warning("stt: QAudioSource.stop() failed: %s", exc)
        self._drain()                                       # whatever Qt still held

        sink = self._sink
        bytes_written = sink.bytes_written if sink is not None else 0
        self._teardown(delete_file=False)

        frames = bytes_written // fmt.wav_frame_bytes if fmt.wav_frame_bytes else 0
        recording = Recording(
            path=self._path,
            sample_rate=fmt.sample_rate,
            channels=fmt.channels,
            sample_width=fmt.sample_width,
            frames=frames,
            peak=self._overall.peak,
            rms=self._overall.rms,
            degraded_format=fmt.degraded,
            capture_error=self._capture_error,
        )
        if recording.capture_error is None and recording.silent:
            raise SttError(
                SttErrorKind.NO_AUDIO_CAPTURED,
                f'peak {recording.peak:.5f} never rose above {SILENCE_PEAK_FLOOR} '
                f'over {recording.duration_seconds:.1f}s ({recording.path})',
            )
        return recording

    def abort(self) -> None:
        """Stop and discard. Never raises -- it is the cancel path."""
        if not self.is_recording:
            return
        source = self._source
        if source is not None:
            try:
                source.stop()
            except Exception as exc:                        # pragma: no cover - Qt teardown
                logger.warning("stt: QAudioSource.stop() failed during abort: %s", exc)
        self._teardown(delete_file=True)

    def _teardown(self, *, delete_file: bool) -> None:
        if self._io is not None:
            try:
                self._io.readyRead.disconnect(self._drain)
            except (AttributeError, TypeError, RuntimeError):   # pragma: no cover - Qt teardown
                pass
        if self._source is not None:
            state_changed = getattr(self._source, 'stateChanged', None)
            if state_changed is not None:
                try:
                    state_changed.disconnect(self._on_state_changed)
                except (AttributeError, TypeError, RuntimeError):   # pragma: no cover
                    pass
        if self._sink is not None:
            try:
                self._sink.close()
            except Exception as exc:                        # pragma: no cover
                logger.warning("stt: closing the WAV failed: %s", exc)
        if delete_file and self._path is not None:
            try:
                self._path.unlink(missing_ok=True)
            except OSError as exc:                          # pragma: no cover
                logger.warning("stt: could not remove %s: %s", self._path, exc)
        self._sink = None
        self._io = None
        self._source = None
        self._pending = b''

    # -- format ----------------------------------------------------------

    def _resolve_format(self, device: InputDevice) -> Tuple[QAudioFormat, CaptureFormat]:
        """Ask for 16 kHz mono Int16; take what the device offers if refused."""
        wanted = QAudioFormat()
        wanted.setSampleRate(REQUESTED_SAMPLE_RATE)
        wanted.setChannelCount(REQUESTED_CHANNELS)
        wanted.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        qt_device = device.qt_device
        degraded = not qt_device.isFormatSupported(wanted)
        chosen = qt_device.preferredFormat() if degraded else wanted
        if degraded:
            logger.info(
                "stt: %r refused 16 kHz mono Int16; recording at %d Hz x%d %s",
                device.label, chosen.sampleRate(), chosen.channelCount(),
                chosen.sampleFormat(),
            )

        coding = self._coding_name(chosen.sampleFormat())
        if coding is None or chosen.sampleRate() <= 0 or chosen.channelCount() <= 0:
            raise SttError(
                SttErrorKind.CAPTURE_FAILED,
                f'{device.label!r} offers no usable audio format '
                f'({chosen.sampleRate()} Hz x{chosen.channelCount()} {chosen.sampleFormat()})',
            )

        # Align the window down to whole frames. bytesForDuration has no
        # obligation to land on a frame boundary at an awkward sample
        # rate, and a window that does not would drift the cut in
        # _consume_block off the frame grid one byte at a time.
        frame_bytes = SAMPLE_CODINGS[coding].width * chosen.channelCount()
        raw_window = chosen.bytesForDuration(LEVEL_WINDOW_US)
        report_bytes = max(frame_bytes, (raw_window // frame_bytes) * frame_bytes)

        return chosen, CaptureFormat(
            sample_rate=chosen.sampleRate(),
            channels=chosen.channelCount(),
            coding=coding,
            sample_width=wav_sample_width(coding),
            report_bytes=report_bytes,
            degraded=degraded,
        )

    @staticmethod
    def _coding_name(sample_format: Any) -> Optional[str]:
        return {
            QAudioFormat.SampleFormat.UInt8: 'uint8',
            QAudioFormat.SampleFormat.Int16: 'int16',
            QAudioFormat.SampleFormat.Int32: 'int32',
            QAudioFormat.SampleFormat.Float: 'float',
        }.get(sample_format)

    @staticmethod
    def _build_audio_source(qt_device: Any, qt_format: QAudioFormat) -> QAudioSource:
        return QAudioSource(qt_device, qt_format)

    @staticmethod
    def _is_error(error: Any) -> bool:
        """True unless this is ``QAudio.Error.NoError``."""
        if error == QAudio.Error.NoError:
            return False
        return 'NoError' not in (getattr(error, 'name', None) or str(error))
