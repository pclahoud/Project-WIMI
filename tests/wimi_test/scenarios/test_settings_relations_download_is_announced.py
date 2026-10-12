"""Regression: the relations model download is exposed to assistive tech (#401).

Settings -> Related Topics downloads 845 MB, the longest operation in the app,
and reported it to sighted users only. Measured through CDP's Accessibility
domain on the unfixed page, with a download running at 412 of 845 MB:

    .feature-progress-track   role 'none', ignored       (the bar's track)
    #relationsDownloadBar     role 'generic', no value   (a width, nothing else)
    #relationsDownloadError   role 'none', ignored, then 'paragraph' on failure
    whole tree                0 progressbars, 0 alerts, 1 status (the page gate)

So a screen reader heard nothing while the transfer ran and nothing when it
failed. After the fix the same snapshot has the track as a ``progressbar``
named "Model download" carrying ``valuetext`` in megabytes, the error line as
an ``alert`` that is in the tree -- empty -- *before* anything fails, and the
availability line as a polite ``status``.

Why the AX tree and not the attributes
--------------------------------------
``role="alert"`` on an element that is ``display: none`` until its text
arrives is exactly the markup a DOM check passes and a screen reader misses:
the region must be in the tree before its text changes. So the error line is
asserted to be an exposed ``alert`` while it is still empty, and to be
rendered (never ``display: none``) at every step. What this cannot observe is
an announcement itself -- CDP is not a screen reader (CLAUDE.md, #127); that
a change to an exposed live region is spoken rests on the spec.

The progress text beside the bar is asserted NOT to be live: it changes on
every 400 ms poll, and #401's own caution is that a live region there would
talk continuously over the whole download.

The download is FAKED from the page: the four bridge calls ``settings.js``
makes (status, start, poll, and the status re-read) are replaced on
``window.api``, so nothing is fetched and the 845 MB model is never touched.
Everything from the button press on is the shipped code path.
"""
from __future__ import annotations

import json

import pytest

from _helpers.a11y import enable
from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

TOTAL = 845_000_000

FAKE_BRIDGE = """
(() => {
  window.__dl = {state: 'idle', bytes: 0};
  const model = {installed: false, total_bytes: %(total)d,
                 bytes_still_needed: %(total)d};
  // FAKED: no real download. See the module docstring.
  window.api.getRelationExtractionStatus = () => Promise.resolve({
    state: 'model_not_downloaded', ready: false, model: model,
    download: window.__dl.state === 'running'
        ? {state: 'running', job_id: 'fake'} : null});
  window.api.startRelationModelDownload = () => {
    window.__dl.state = 'running';
    return Promise.resolve({job_id: 'fake', total_bytes: %(total)d,
                            bytes_still_needed: %(total)d, file_count: 8});
  };
  window.api.pollRelationModelDownload = () => {
    if (window.__dl.state === 'running') {
      return Promise.resolve({state: 'running', bytes: window.__dl.bytes,
          total: %(total)d, file_index: 3, file_count: 8,
          file: 'model.safetensors'});
    }
    return Promise.resolve({state: 'failed', error: {kind: 'download_failed',
        detail: 'connection reset', retryable: true}});
  };
  window.__statusRead = false;
  settingsPage.refreshRelatedTopics().then(() => { window.__statusRead = true; });
  return true;
})()
""" % {'total': TOTAL}

DISPLAYS = """
(() => JSON.stringify({
  error: getComputedStyle(document.querySelector('#relationsDownloadError')).display,
  error_text: document.querySelector('#relationsDownloadError').textContent.trim(),
}))()
"""


def _ax(page: WimiPage, selector: str) -> dict:
    """Role, name, value and properties Chromium exposes for ``selector``."""
    tab = page.tab
    root = tab.DOM.getDocument()['root']['nodeId']
    node_id = tab.DOM.querySelector(nodeId=root, selector=selector).get('nodeId')
    assert node_id, f'{selector} is not in the DOM'
    nodes = tab.Accessibility.getPartialAXTree(
        nodeId=node_id, fetch_relatives=False).get('nodes') or []
    assert nodes, f'{selector} has no accessibility node'
    node = nodes[0]
    return {
        'role': (node.get('role') or {}).get('value'),
        'ignored': bool(node.get('ignored')),
        'name': (node.get('name') or {}).get('value'),
        'value': (node.get('value') or {}).get('value'),
        'props': {p['name']: (p.get('value') or {}).get('value')
                  for p in node.get('properties') or []},
    }


def _displays(page: WimiPage) -> dict:
    return json.loads(page.eval_js(DISPLAYS))


@pytest.mark.slow
@pytest.mark.regression
def test_the_download_reports_progress_and_failure_to_assistive_tech(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    page = wimi_page
    page.goto('settings')
    wait_for_release(page)
    real_click(page, centre_of(page, '[data-testid="settings-nav-related-topics"]'))
    assert poll(page, "!document.querySelector('#relationsStatusText')"
                      ".textContent.startsWith('Checking')")
    enable(page)

    page.eval_js(FAKE_BRIDGE)
    assert poll(page, 'window.__statusRead === true')
    # Positive control: the faked state really offers the download, so the
    # rest is measured on a running transfer and not on an absent panel.
    assert page.eval_js("document.querySelector("
                        "'[data-testid=\"settings-relations-download\"]')"
                        ".getBoundingClientRect().height > 0"), (
        'model_not_downloaded drew no Download button')

    status = _ax(page, '#relationsStatusText')
    assert status['role'] == 'status' and status['props'].get('live') == 'polite', (
        f'the availability line is not a polite live region: {status}')

    # The alert must be in the tree BEFORE it has anything to say.
    before = _ax(page, '#relationsDownloadError')
    assert before['role'] == 'alert' and not before['ignored'], (
        f'the download error line is not an exposed alert while empty, so its '
        f'first message cannot be announced: {before}')
    assert _displays(page)['error'] != 'none'

    real_click(page, centre_of(page, '[data-testid="settings-relations-download"]'))
    page.eval_js('window.__dl.bytes = 412000000')
    assert poll(page, "document.querySelector('#relationsDownloadText')"
                      ".textContent.startsWith('412 of 845 MB')"), (
        'the faked poll never reached the bar')

    bar = _ax(page, '#relationsDownloadTrack')
    assert bar['role'] == 'progressbar' and not bar['ignored'], (
        f'the download bar exposes no progress semantics: {bar} (#401)')
    assert bar['name'], f'the progressbar has no accessible name: {bar}'
    assert bar['props'].get('valuemin') == 0 and bar['props'].get('valuemax') == 100, bar
    assert '412 of 845 MB' in (bar['props'].get('valuetext') or ''), (
        f'the progressbar does not say how far along it is in words: {bar}')
    assert page.eval_js("document.querySelector('#relationsDownloadTrack')"
                        ".getAttribute('aria-valuenow')") == '49'

    ticking = _ax(page, '#relationsDownloadText')
    assert 'live' not in ticking['props'], (
        f'the per-poll progress text is a live region and would talk over the '
        f'whole download: {ticking}')

    page.eval_js("window.__dl.state = 'failed'")
    assert poll(page, "document.querySelector('#relationsDownloadError')"
                      ".textContent.includes('did not finish')"), (
        'the failed download wrote no error')
    after = _ax(page, '#relationsDownloadError')
    assert after['role'] == 'alert' and not after['ignored'], (
        f'a failed 845 MB download is not exposed as an alert: {after}')
    assert after['props'].get('live') == 'assertive', after
    assert _displays(page)['error'] != 'none'
