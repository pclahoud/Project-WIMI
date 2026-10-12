"""Regression: Settings tells the truth about relation suggestions (#60, #5183).

The owner's decision is that a machine which cannot extract relations gets
**one line in Settings and silence everywhere else**. Before this panel's
status line existed, Settings carried the feature's description and its
confidence dial and said nothing about whether anything could run — so on
every machine it described something unreachable, with no way to fetch the
model from inside WIMI at all.

What this asserts, and why each one needs a browser
---------------------------------------------------
* **The line resolves.** `Checking…` is the markup's placeholder; a status
  read that threw would leave it there, and a `catch` that swallowed the
  failure would look identical in the source.
* **The DOM agrees with the bridge.** The scenario asks
  `getRelationExtractionStatus()` itself and compares the state it reports
  with the dot's class and the Download button's visibility. A renderer
  branch that painted the sentence and left a stale button is the failure
  this shape exists to prevent, and no source check can see it.
* **The dial is visible whatever the state is.** That is the decision argued
  from where m028 lives: the cutoff is `user_preferences`, so it travels in a
  `.wimi`, and a student on the build without the runtime is setting it for
  the machine that has it.

**State-agnostic on purpose.** This machine happens to report
`dev_runtime_missing` (no torch in `.venv`) and a machine with the relations
venv reports `ready` or `model_not_downloaded`. Asserting any one of those
would make the test a property of the machine rather than of the page, which
is #186's lesson. It asserts the *relationship* between the reported state
and what is drawn, which holds on all five.
"""
from __future__ import annotations

import json

import pytest

from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

#: Every state the bridge may report, from ``AvailabilityState``. A sixth
#: would make ``renderRelationsStatus`` fall through to its ``default``
#: branch, which says so rather than painting a lie -- and this list is what
#: notices.
KNOWN_STATES = {
    'ready', 'not_in_this_build', 'runtime_broken',
    'model_not_downloaded', 'dev_runtime_missing',
}

#: Which states may offer a Download button. ``not_in_this_build`` is
#: actionable and still gets none: the action is to fetch the other artifact,
#: which no button here can perform (#174).
MAY_OFFER_DOWNLOAD = {'model_not_downloaded'}

PANEL = '[data-testid="settings-relations-status"]'

DOM = """
(() => {
  const dot = document.querySelector('#relationsStatusDot');
  const text = document.querySelector('[data-testid="settings-relations-status-text"]');
  const download = document.querySelector('[data-testid="settings-relations-download"]');
  const dial = document.querySelector('#relation_confidence_threshold');
  const seen = el => !!el && el.getBoundingClientRect().height > 0;
  return JSON.stringify({
    dot_class: dot ? dot.className : null,
    text: text ? text.textContent.trim() : null,
    download_visible: seen(download),
    dial_visible: seen(dial),
    dial_disabled: dial ? dial.disabled : null,
  });
})()
"""

#: Asked of the bridge from the page, parked on a global, then polled -- the
#: documented way to read an async answer out of a scenario.
ASK_BRIDGE = """
(() => {
  window.__relStatus = null;
  window.api.getRelationExtractionStatus()
    .then(s => { window.__relStatus = JSON.stringify(s); })
    .catch(e => { window.__relStatus = JSON.stringify({error: String(e)}); });
  return 'asked';
})()
"""


def _dom(page: WimiPage) -> dict:
    return json.loads(page.eval_js(DOM))


def _open_panel(page: WimiPage) -> None:
    page.goto("settings")
    assert poll(page, "(() => !!document.querySelector('%s'))()" % PANEL), (
        "the Related Topics status block never rendered")
    wait_for_release(page)
    real_click(page, centre_of(page, '[data-testid="settings-nav-related-topics"]'))
    assert poll(page, "JSON.parse((%s)).dial_visible" % DOM.strip()), (
        "the Related Topics panel never became visible")


@pytest.mark.slow
@pytest.mark.regression
def test_the_availability_line_resolves_and_agrees_with_the_bridge(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _open_panel(wimi_page)

    # The line must stop saying "Checking..." -- the placeholder is what a
    # swallowed failure would leave behind.
    assert poll(wimi_page,
                "!JSON.parse((%s)).text.startsWith('Checking')" % DOM.strip()), (
        "the status line never resolved; it still reads the markup's "
        "placeholder, which is what a status read that threw would leave")

    wimi_page.eval_js(ASK_BRIDGE)
    assert poll(wimi_page, "window.__relStatus !== null"), (
        "getRelationExtractionStatus never answered")
    status = json.loads(wimi_page.eval_js("window.__relStatus"))
    assert 'error' not in status, status

    dom = _dom(wimi_page)
    state = status['state']

    assert state in KNOWN_STATES, (
        f"{state} is not an AvailabilityState this page knows how to draw; "
        f"renderRelationsStatus would fall through to its default branch")
    assert dom['text'], "the line is empty"

    # The dot carries the same verdict as the sentence. Colour is never the
    # only carrier -- the dot is aria-hidden and the text says the state in
    # words -- but a dot disagreeing with the words is still wrong.
    expected_dot = {
        'ready': 'ready',
        'model_not_downloaded': 'action',
        'not_in_this_build': 'action',
        'dev_runtime_missing': 'action',
        'runtime_broken': 'problem',
    }[state]
    assert expected_dot in dom['dot_class'], (
        f"state {state} drew dot {dom['dot_class']!r}, expected "
        f"{expected_dot!r} -- a ready dot on an unavailable feature, or a "
        f"problem dot on a first-run state, both read as the opposite of "
        f"what is true")

    if state in MAY_OFFER_DOWNLOAD:
        assert dom['download_visible'], (
            "the model is not downloaded and nothing offers to fetch it, "
            "which is the state this panel exists to resolve")
    else:
        assert not dom['download_visible'], (
            f"state {state} offers a Download button that cannot help. "
            f"#174: a message may not direct a press when nothing is "
            f"pressable")


@pytest.mark.slow
@pytest.mark.regression
def test_the_dial_stays_available_whatever_the_state(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """The cutoff travels in a `.wimi`, so it is settable on any machine.

    Hiding or disabling it where the runtime is absent would make a
    travelling preference unsettable on whichever machine happens to be in
    front of the student -- including the common case of setting it on a
    laptop for the desktop that took the larger download.
    """
    _open_panel(wimi_page)
    assert poll(wimi_page,
                "!JSON.parse((%s)).text.startsWith('Checking')" % DOM.strip())

    dom = _dom(wimi_page)
    assert dom['dial_visible'], (
        "the confidence dial is not visible. It must be available in every "
        "availability state -- see the panel comment in settings.html")
    assert dom['dial_disabled'] is False, (
        "the confidence dial is disabled. Same decision: a travelling "
        "preference stays settable")
