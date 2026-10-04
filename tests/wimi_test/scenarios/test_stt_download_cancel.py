"""A download started through `api.downloadSttModel` can be cancelled (#171, #59).

Issue #171: the composite starts the job itself and kept `started.job_id` in
a local, while `pollModelDownload`'s payload was `{state, bytes, total,
size}` -- no `job_id`. So nothing a caller held could be passed to
`cancelModelDownload(jobId)`, and a download begun through the composite
could only be waited out. Plan §3.8 is explicit that *"Cancel must be
possible mid-download and must delete the `.part`"*, and the bridge already
did both correctly; only the JS composite could not reach them.

It had already cost duplication: T13 (`dictation.js`) and T14
(`settings.js`) each wrote the start+poll loop out by hand, both with a
comment saying the composite could not be cancelled.

The fix is one line of payload -- `pollModelDownload` returns `job_id` on
every branch -- and this scenario is the half of it that pytest cannot
reach. `tests/app/test_bridge_stt.py::test_every_poll_says_which_job_it_is
_about` pins the bridge payload; only a running application exercises the
seam, because the composite is JavaScript and the thing under test is
whether a page holding nothing but `onProgress`'s argument can stop a
download that is genuinely in flight.

**So this downloads for real.** There is no URL override on the bridge
slot, and faking the poll would stub out precisely the payload the bug was
in. The cost is bounded: the cancel goes in from the *first* progress
report, the read loop checks the flag once per 64 KiB chunk, and
`download.py` unlinks the `.part` before raising -- so a few hundred
kilobytes cross the wire and nothing is left on disk. `base-q5_1` is the
smallest pinned size, which matters only if the cancel is ever missed.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

#: Smallest of the pinned sizes (59.7 MB). Never fetched whole -- see above.
SIZE = 'base-q5_1'


def _the_model_host_answers() -> bool:
    """One cheap request to the pinned host, so no-network reads as a skip.

    Without this the failure would be `download_failed` where the test
    asserts `download_cancelled`, which looks like the bug coming back
    rather than like an unplugged cable.
    """
    try:
        from app.stt import model_spec
        request = urllib.request.Request(
            model_spec.download_url(SIZE), method='HEAD',
            headers={'User-Agent': 'wimi-test'})
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status < 400
    except Exception:       # noqa: BLE001 - any failure here means "skip"
        return False


requires_the_model_host = pytest.mark.skipif(
    not _the_model_host_answers(),
    reason='needs network: the pinned model host did not answer',
)


def _js(page: WimiPage, expr: str):
    """Await a promise in the page and bring the result back as JSON."""
    return json.loads(page.eval_js(
        f'(async () => JSON.stringify(await {expr}))()', await_promise=True))


@requires_the_model_host
def test_a_download_is_cancelled_through_the_composite(
    wimi_config, wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ------------------------------------------------------
    # The dashboard, not the entry form: the entry form redirects itself to
    # index.html about two seconds after load when no session is seeded,
    # which destroys the execution context mid-download and surfaces as
    # "Execution context was destroyed" rather than as anything about
    # speech. The STT API hangs off window.api and is page-agnostic.
    wimi_page.goto('dashboard')

    # Nothing of this size may already be installed, or there is no download
    # to cancel: `download_model` short-circuits on `_existing_install_is_good`
    # and hashes the file it found instead, so the cancel lands in sha256 and
    # reports "cancelled while verifying". That passed an earlier draft of the
    # kind assertion below without a byte ever crossing the wire. The harness
    # wipes `app_data_test` between sessions, but a run that failed before its
    # own teardown can leave a model behind -- so say so rather than assume it.
    _js(wimi_page, f'window.api.removeSttModel({json.dumps(SIZE)})')

    # ---- Act ----------------------------------------------------------
    # Everything this caller knows about the job comes from onProgress's
    # argument. That is the whole point: no startModelDownload call, no
    # job id smuggled out of a closure the composite does not own.
    report = _js(wimi_page, f"""(async () => {{
        let cancelled = false;
        let seen = null;
        const report = await window.api.downloadSttModel({json.dumps(SIZE)}, (p) => {{
            if (cancelled) return;         // cancel once, on the first report
            cancelled = true;
            // `|| null` so the key survives JSON.stringify when the payload
            // has no job_id -- that absence is the bug itself, and it should
            // arrive as this test's own message rather than as a KeyError.
            seen = p.job_id || null;
            window.api.cancelModelDownload(seen);
        }});
        return {{report: report, job_id: seen}};
    }})()""")

    # ---- Assert -------------------------------------------------------
    assert report['job_id'], (
        'onProgress was handed a payload with no job_id, so a page using the '
        'composite still has nothing to pass to cancelModelDownload -- this '
        'is #171 exactly as filed.')

    terminal = report['report']
    assert terminal['state'] == 'failed', (
        f'the download was not stopped: {terminal}. A download that ran to '
        f'"done" means the cancel never reached the worker.')
    assert terminal['error']['kind'] == 'download_cancelled', (
        f'stopped, but not by us: {terminal["error"]}. download_failed here '
        f'is a transport problem, not a cancel.')

    # **A download was cancelled, not a hash of a file already here.**
    # `download.py` raises download_cancelled from three places, and only two
    # of them are a transfer: `_raise_if_cancelled` before the URL is opened
    # ("cancelled before starting") and the read loop once the response is
    # open ("cancelled after N bytes"). The third is sha256 over a model that
    # was already installed ("cancelled while verifying"), which the arrange
    # step rules out -- asserted here too, because that path reaches the same
    # error kind while proving nothing about a download.
    detail = terminal['error']['detail']
    assert 'verif' not in detail, (
        f'cancelled during verification ({detail!r}), so no download ran. A '
        f'model of this size was installed despite removeSttModel above.')

    # The terminal payload identifies itself too -- the same field, on the
    # branch a page reads last.
    assert terminal['job_id'] == report['job_id']

    # §3.8's other half: a cancel is a decision not to have the model, so
    # the partial file goes. Leaving it would make the next attempt resume
    # toward something the student said no to.
    from app.stt import model_spec
    spec = model_spec.get_spec(SIZE)
    whisper_dir = (Path(wimi_config.app_data_dir)
                   / model_spec.MODELS_DIR_NAME / model_spec.WHISPER_DIR_NAME)
    part = whisper_dir / (spec.filename + model_spec.PART_SUFFIX)
    assert not part.exists(), f'cancel left {part} behind'
    assert not (whisper_dir / spec.filename).exists(), (
        'a cancelled download installed a model')
