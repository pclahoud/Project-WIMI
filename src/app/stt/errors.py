"""The speech-to-text failure taxonomy, and the order the checks must run in.

Every platform signal -- a ``QAudio.Error``, a missing file, a subprocess exit
code -- is mapped onto ``SttErrorKind`` in exactly one place, so the page never
sees a raw Qt enum and never has to guess what a message means.

This file is the contract between the recorder (T7), the runtime (T6) and the
downloader (T21). It is written ahead of all three so that none of them owns
it and none of them has to invent it. **Add a member at the end of its section
if you genuinely need one**, with a comment saying what produces it; do not
renumber, rename or repurpose an existing one.

The check order below is the load-bearing part
------------------------------------------------

Spike T2 (2026-09-23) measured two things that make the enum insufficient on
its own:

* ``QAudioSource.error()`` is **already** ``OpenError`` immediately after
  construction against a null device -- before ``start()`` has been called.
* ``QAudioSource.start()`` returns ``None`` on failure rather than raising.

So "no microphone", "another app holds the microphone" and (on Windows) a
permission denial all present as the same value at the same moment. What
separates them is not the enum, it is **the order in which the conditions are
tested**, which is why it is written here rather than left implicit in whatever
order somebody happened to write the code:

1. ``QMediaDevices.audioInputs()`` is empty -> ``NO_INPUT_DEVICE``.
   **Before anything else, and before any ``QAudioSource`` exists.**
2. The resolved device ``isNull()`` -> ``NO_INPUT_DEVICE``.
3. Permission is Denied -> ``PERMISSION_DENIED``. Meaningful on macOS; Qt has
   no Windows backend and its stub returns Granted unconditionally, so on
   Windows this step never fires and must not be built on.
4. **Only now construct ``QAudioSource``.** ``OpenError`` at this point ->
   ``DEVICE_IN_USE``.
5. On stop, the recording's peak never rose above the floor ->
   ``NO_AUDIO_CAPTURED``.

Reorder these and all four capture paths collapse into one unhelpful message.

Step 5 is not a safeguard, it is a detector
-------------------------------------------

With Windows' *Let desktop apps access your microphone* switched off, nothing
denies anything: the capture stack delivers a stream of zeros and every API
reports success. Since step 3 cannot fire on Windows, the peak check is the
**only** thing this feature has that notices. Treat it accordingly.

It has a second, platform-independent reason, measured on 2026-09-23: **three
seconds of digital silence does not transcribe to nothing. It transcribes to
the word " you".** So without step 5, a muted microphone does not produce an
empty field the student would notice — it produces an **invented word in the
required reflection field**, indistinguishable from something they said.

This also explains why the runtime may treat empty stdout as a failure: silence
does not produce empty stdout, so the two conditions never overlap. They are
only safe as a pair.

Neither writing field is ever disabled by any of these
------------------------------------------------------

The reflection and explanation fields are what a WIMI entry is *for*, and both
are required. The microphone is an affordance on top of them. A capture failure
must leave the student typing exactly as they did before this feature existed.

See ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §7 for the
per-kind detection, message and scenario, and §0.1 for the T2 measurements
above.
"""

from __future__ import annotations

from enum import Enum


class SttErrorKind(str, Enum):
    """What went wrong, at the granularity the student needs to act on.

    ``str`` mixin so a kind serialises through the bridge as its own name with
    no conversion, the way the codebase's other JSON-facing enums do.
    """

    # -- capture, in check order (see module docstring) ---------------------
    NO_INPUT_DEVICE = 'no_input_device'
    PERMISSION_DENIED = 'permission_denied'
    DEVICE_IN_USE = 'device_in_use'
    NO_AUDIO_CAPTURED = 'no_audio_captured'
    #: Anything else from ``QAudio.Error`` once the four above are excluded --
    #: IOError, UnderrunError, FatalError. Carries the Qt value in ``detail``.
    CAPTURE_FAILED = 'capture_failed'

    # -- transcription ------------------------------------------------------
    #: The vendored whisper.cpp binary is not where it should be. Distinct
    #: from MODEL_MISSING on purpose: the binary ships in the build and the
    #: model is downloaded, so these two have different fixes (§3.8).
    BINARY_MISSING = 'binary_missing'
    MODEL_MISSING = 'model_missing'
    #: Present but its sha256 or byte size does not match the pin. A truncated
    #: download must say so, not fail as a cryptic subprocess error.
    MODEL_CORRUPT = 'model_corrupt'
    TRANSCRIPTION_FAILED = 'transcription_failed'
    #: The subprocess exceeded its wall-clock ceiling and was killed, so one
    #: wedged run cannot hold the single worker forever.
    TRANSCRIPTION_TIMEOUT = 'transcription_timeout'

    # -- model acquisition --------------------------------------------------
    DOWNLOAD_FAILED = 'download_failed'
    DOWNLOAD_CANCELLED = 'download_cancelled'

    # -- the job layer ------------------------------------------------------
    #: Polled for a job id the executor has never heard of, or has already
    #: handed out. Mirrors the folder-sync job contract.
    UNKNOWN_JOB = 'unknown_job'


#: Kinds where offering the student a retry is honest. Everything else either
#: needs an action outside WIMI (plug in a microphone, grant permission in
#: System Settings) or will fail identically on a second press -- and a retry
#: button that cannot work is worse than no button.
RETRYABLE = frozenset({
    SttErrorKind.DEVICE_IN_USE,
    SttErrorKind.NO_AUDIO_CAPTURED,
    SttErrorKind.TRANSCRIPTION_FAILED,
    SttErrorKind.TRANSCRIPTION_TIMEOUT,
    SttErrorKind.DOWNLOAD_FAILED,
})


class SttError(Exception):
    """A failure with a ``kind`` the UI can branch on.

    ``detail`` is for the log and for a developer -- the Qt enum value, the
    subprocess stderr tail, the path that was missing. It is **not** the
    student-facing message: that copy lives with the UI, because what to say
    about ``PERMISSION_DENIED`` differs by platform and by where in the flow
    the student is, and neither of those is knowable here.
    """

    def __init__(self, kind: SttErrorKind, detail: str = '') -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f'{kind.value}: {detail}' if detail else kind.value)

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE

    def to_dict(self) -> dict:
        """The shape the bridge serialises into a failed response."""
        return {
            'kind': self.kind.value,
            'detail': self.detail,
            'retryable': self.retryable,
        }
