"""The speech-to-text taxonomy's contract with everything that consumes it (#59).

Three things here are worth a test rather than a comment, because each one
breaks silently:

* **The wire values.** ``SttErrorKind`` crosses the bridge as a string and the
  page branches on it. Renaming a member is a source-level rename that the
  frontend never sees -- it just stops matching, and the student gets the
  generic message forever. So the strings are pinned.
* **The check order, in the docstring.** T2 measured that the enum alone
  cannot separate "no microphone" from "another app has it" from a Windows
  permission denial: only the order of the tests does. That order is design,
  not commentary, and a file whose docstring is quietly trimmed takes the
  design with it.
* **What is retryable.** Offering a retry for ``PERMISSION_DENIED`` on macOS
  is a lie -- TCC will not prompt again -- and offering one for
  ``NO_INPUT_DEVICE`` cannot conjure a microphone. Both exclusions are
  deliberate.
"""
from __future__ import annotations

import pytest

from app.stt import errors as stt_errors
from app.stt.errors import RETRYABLE, SttError, SttErrorKind


@pytest.mark.unit
def test_wire_values_are_stable():
    """These strings are an API the page matches on. Changing one is a break."""
    assert {k.name: k.value for k in SttErrorKind} == {
        'NO_INPUT_DEVICE': 'no_input_device',
        'PERMISSION_DENIED': 'permission_denied',
        'DEVICE_IN_USE': 'device_in_use',
        'NO_AUDIO_CAPTURED': 'no_audio_captured',
        'CAPTURE_FAILED': 'capture_failed',
        'BINARY_MISSING': 'binary_missing',
        'MODEL_MISSING': 'model_missing',
        'MODEL_CORRUPT': 'model_corrupt',
        'TRANSCRIPTION_FAILED': 'transcription_failed',
        'TRANSCRIPTION_TIMEOUT': 'transcription_timeout',
        'DOWNLOAD_FAILED': 'download_failed',
        'DOWNLOAD_CANCELLED': 'download_cancelled',
        'UNKNOWN_JOB': 'unknown_job',
    }, (
        "A member was renamed, removed or given a new value. Adding one at "
        "the end of its section is fine -- update this dict deliberately. "
        "Changing an existing value silently breaks the page's branching."
    )


@pytest.mark.unit
def test_the_check_order_is_written_down_where_it_is_implemented():
    """The order is the taxonomy (T2). Losing the docstring loses the design."""
    doc = stt_errors.__doc__ or ''
    # Scope to the numbered list itself. Searching the whole docstring finds
    # "QAudioSource" first in the paragraph that explains *why* the order
    # matters, which is earlier than the step that constructs one -- so the
    # naive version of this test failed against a correctly ordered file.
    start = doc.find('1. ``QMediaDevices')
    end = doc.find('Reorder these')
    assert 0 <= start < end, (
        "errors.py's docstring no longer carries the numbered check order "
        "as a list ending in the 'Reorder these' warning."
    )
    listing = doc[start:end]

    # The sequence, not merely the words: each step must appear after the one
    # before it, so a reordered list fails even though every term is present.
    # Step 4's marker is "Only now construct", not "QAudioSource": step 1
    # names the class too, in the clause forbidding one from existing yet.
    steps = ['audioInputs', 'isNull', 'Denied', 'Only now construct', 'peak']
    positions = [listing.find(s) for s in steps]
    assert all(p >= 0 for p in positions), (
        f"errors.py's docstring no longer documents every check: "
        f"{dict(zip(steps, positions))}"
    )
    assert positions == sorted(positions), (
        "The documented checks are out of order. Construct QAudioSource "
        "before testing for an empty device list and NO_INPUT_DEVICE, "
        "DEVICE_IN_USE and a permission denial all become OpenError."
    )
    assert 'only' in doc.lower() and 'zeros' in doc.lower(), (
        "The docstring must keep saying that the peak check is the ONLY "
        "Windows detector of the privacy toggle -- it reads like a "
        "safeguard, and someone will drop it as one."
    )


@pytest.mark.unit
@pytest.mark.parametrize('kind', [
    SttErrorKind.NO_INPUT_DEVICE,
    SttErrorKind.PERMISSION_DENIED,
])
def test_a_retry_is_not_offered_where_it_cannot_work(kind):
    assert kind not in RETRYABLE
    assert not SttError(kind).retryable


@pytest.mark.unit
def test_device_in_use_is_retryable_because_the_call_ends():
    assert SttError(SttErrorKind.DEVICE_IN_USE).retryable


@pytest.mark.unit
def test_detail_reaches_the_log_and_the_payload():
    err = SttError(SttErrorKind.MODEL_CORRUPT, 'sha256 mismatch: got abc, want def')
    assert 'sha256 mismatch' in str(err)
    assert err.to_dict() == {
        'kind': 'model_corrupt',
        'detail': 'sha256 mismatch: got abc, want def',
        'retryable': False,
    }


@pytest.mark.unit
def test_a_kind_with_no_detail_still_reads_as_something():
    assert str(SttError(SttErrorKind.NO_INPUT_DEVICE)) == 'no_input_device'
