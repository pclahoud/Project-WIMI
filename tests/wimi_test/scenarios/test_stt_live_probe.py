"""The speech chain, end to end, in a running application (#59).

This is the only test that exercises the whole thing at once:

    page JS -> WebChannel -> SttBridgeMixin -> AudioRecorder ->
    a real QAudioSource in pull mode -> WAV -> worker -> whisper-cli ->
    transcript -> back to the page with the staleness fields intact

Every device assertion in ``recorder.py`` is against a fake, because the
machine it was written on has no input device -- and "no input device" is
also CI's state and is **indistinguishable from an unplugged microphone**
(T2's finding). `scripts/dev_virtual_mic.sh` supplies a real one through
PipeWire, so the capture half can be driven for real.

Requires a microphone, ``vendor/whisper/<platform>/`` and the default model
under the test ``app_data``. Skips cleanly without any of them -- and the
skip reason names the fix, because a skip reads exactly like a pass.

**It drives from the dashboard, not the entry form, and that is not
arbitrary.** The entry form redirects itself to ``index.html`` about two
seconds after load when no session has been seeded, which destroys the
execution context in the middle of a multi-second transcription and
surfaces as ``Runtime.evaluate error: Execution context was destroyed``
rather than as anything about speech. The STT API hangs off ``window.api``
and is page-agnostic, so the dashboard tests the same surface without the
race. A scenario that wants the entry form must seed a session first.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession
from _helpers.live_audio import REPO, WAV, requires_live_audio


pytestmark = [pytest.mark.slow, pytest.mark.regression]


# Both the microphone probe and the injection gate live in one helper, so
# this file and test_stt_mic_button_live.py cannot drift apart, and so the
# skip reason is specific to whichever condition actually failed (#182).


@pytest.fixture
def stt_model_installed(wimi_config) -> Path:
    """Put the default model inside the session's app_data, after the wipe.

    ``wimi_test``'s master_db fixture deletes the whole ``app_data_test``
    tree on teardown (``fixtures/core.py``), so a model placed there by
    hand survives exactly one run and then silently disappears -- which
    presents as ``model_missing`` and a skip, not as a missing file.
    Symlink it in per session instead, from ``WIMI_STT_MODEL`` or from
    wherever the measurement runs keep their models.
    """
    import os
    from app.stt import model_spec

    spec = model_spec.get_spec(None)
    candidates = []
    env = os.environ.get('WIMI_STT_MODEL')
    if env:
        candidates.append(Path(env))
    candidates.append(REPO / 'app_data' / 'models' / 'whisper' / spec.filename)

    src = next((c for c in candidates if c.is_file()), None)
    if src is None:
        pytest.skip(
            f'{spec.filename} not found. Set WIMI_STT_MODEL to a copy, or '
            f'download it once -- the harness wipes app_data between runs.')

    dest_dir = Path(wimi_config.app_data_dir) / 'models' / 'whisper'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / spec.filename
    if not dest.exists():
        dest.symlink_to(src.resolve())
    return dest


def _js(page: WimiPage, expr: str):
    """Await a promise in the page and bring the result back as JSON."""
    return json.loads(page.eval_js(
        f'(async () => JSON.stringify(await {expr}))()', await_promise=True))


@requires_live_audio
def test_speaking_into_a_real_microphone_produces_a_transcript(
    stt_model_installed: Path,
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_page.goto('dashboard')          # not entry-form -- see the module docstring

    status = _js(wimi_page, 'window.api.getSttStatus()')
    if not (status.get('engine_ready') and status.get('model_ready')):
        pytest.skip(f'engine or model not installed here: {status}')

    started = _js(wimi_page, 'window.api.startRecording()')
    assert not started.get('error'), started
    assert started['recording'] is True, started
    assert started['device']['label'], 'recording started with no named device'

    # Speak. Play the whole clip -- stopping early truncates the transcript,
    # which looks like a recognition failure and is not one.
    # The other half of the gate in _helpers/live_audio.py: that decides
    # whether this platform CAN inject audio, this does the injecting.
    # Only Linux reaches here today. A Windows or macOS injector (#182
    # option 2) needs a matching branch here as well as a table entry.
    subprocess.Popen(['pw-play', '--target=virtsink', str(WAV)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    peak = 0.0
    for _ in range(34):                  # ~5 s, longer than the fixture
        wimi_page.wait_for_timeout(150)
        level = _js(wimi_page, 'window.api.getRecordingLevel()')
        peak = max(peak, float(level.get('peak') or 0.0))
    assert peak > 0.01, (
        f'the level meter never rose above {peak} while audio was playing. '
        'Flat-with-bytes-flowing is exactly how the Windows privacy toggle '
        'presents (plan section 7), so this assertion is the one that '
        'distinguishes "muted" from "mumbled".')

    ctx = {'entry_id': 4242, 'field_key': 'explanation', 'token': 7,
           'subject_ids': []}
    result = _js(wimi_page,
                 f'window.api.transcribeRecording({json.dumps(ctx)})')
    assert not result.get('error'), result
    assert result['state'] == 'done', result

    # The staleness contract: all four come back so the page can decide
    # whether the form it is looking at is still the one that asked.
    assert result['entry_id'] == 4242
    assert result['field_key'] == 'explanation'
    assert result['token'] == 7

    text = (result.get('text') or '').lower()
    assert 'test' in text and 'speech' in text, (
        f'transcript does not resemble the fixture: {result.get("text")!r}')


@requires_live_audio
def test_the_status_call_separates_its_three_states(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Not one `available` boolean -- each has a different remedy (§3.8, §7)."""
    wimi_page.goto('dashboard')
    status = _js(wimi_page, 'window.api.getSttStatus()')
    for key in ('engine', 'model', 'mic'):
        assert key in status, f'{key!r} missing from getSttStatus(): {status}'
    assert status['mic']['devices'], 'a microphone exists but none is reported'
