"""Regression: pressing "Find related topics" keeps focus, and the result is heard (#397).

Two defects at the same moment, the press:

* ``renderBar()`` began with ``barEl.innerHTML = ''`` and built a new button,
  so the button a keyboard user had just pressed was **removed from the DOM**
  and focus fell to ``<body>``, back at the top of a long form;
* the outcome, 0.4–8 s later, reached **no live region**, so a screen-reader
  user got no signal that anything happened, worked or failed.

THE MODEL IS FAKED, AND THAT IS DELIBERATE
------------------------------------------
This venv has no relations runtime, so the bridge reports
``dev_runtime_missing`` and the module is silent. That is what
``test_relations_are_silent_when_unavailable.py`` needs, but it leaves this
issue unreachable. Neither defect lives in the model: both are in what the
page does with an answer. So the four bridge calls the module makes for a
pass are replaced **from the page** with fakes that answer the way the real
bridge does (status ``ready``, a started job, one ``running`` poll, then a
result), and ``refresh()`` is called to pick up the ``ready``. The cards,
the database writes and the real model are
``test_relation_proposals_press_and_confirm.py``'s business, and it skips
here.

How each assertion is made
--------------------------
* **Real input.** The press is an ``Enter`` sent through
  ``Input.dispatchKeyEvent`` to the focused button, which is how a keyboard
  user presses it. ``el.click()`` would not tell us where focus goes.
  Getting focus *onto* the button in the first place is done with
  ``.focus()``: that is the precondition, not the thing under test.
* **The announcement is read from the accessibility tree**, with the page
  gate released, not off ``aria-*`` attributes. The region sits inside
  ``.entry-page``, which is ``inert`` until the form is ready, and an inert
  subtree is out of the tree with its role and text intact (#127). Those
  attributes stay correct in exactly the case where nothing is heard.
* **The region must exist, empty, BEFORE the press.** A region created
  together with its text is often not announced at all, so "a status node
  appears with the right text" would pass for that broken shape too.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.a11y import active_element, enable, real_key
from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FIND = '[data-testid="entry-form-relations-find"]'
STATUS = '[data-testid="entry-form-relations-status"]'
CARD = '[data-testid="entry-form-relation-proposal"]'

#: Installs the fakes. ``%s`` is the JSON of what the finished pass returns.
FAKE_BRIDGE = """
(() => {
  const outcome = %s;
  const a = window.api;
  let token = null, polls = 0;
  a.getRelationExtractionStatus = () => Promise.resolve(
      {ready: true, state: 'ready'});
  a.proposeRelationsForEntry = (req) => {
    token = req.token;
    return Promise.resolve({available: true, started: true, job_id: 'fake'});
  };
  // One 'running' answer, so the module really is mid-pass for a while.
  a.pollRelationProposals = () => new Promise(resolve => setTimeout(() => {
    polls += 1;
    if (polls < 2) return resolve({state: 'running'});
    resolve(Object.assign({entry_id: EntryState.currentEntry.id,
                           token: token}, outcome));
  }, 300));
  a.acceptRelationProposal = () => Promise.resolve({});
  window.__relFakePolls = () => polls;
  return EntryState.relationProposals.refresh().then(() => 'ok');
})()
"""

FOUND = {
    'state': 'done',
    'proposals': [
        {'relation_id': 901, 'relation_type_id': None, 'label': 'causes',
         'from_subject_name': 'FA Hypertension', 'to_subject_name': 'FA Stroke',
         'passage': 'Hypertension causes stroke.'},
        {'relation_id': 902, 'relation_type_id': None, 'label': 'treats',
         'from_subject_name': 'FA Metformin', 'to_subject_name': 'FA Diabetes',
         'passage': 'Metformin treats diabetes.'},
    ],
    'pending_elsewhere': [
        {'entry_id': 1, 'session_name': 'Monday block', 'entry_order': 4,
         'from_subject_name': 'FA Statins', 'label': 'treats',
         'to_subject_name': 'FA Hyperlipidaemia'},
    ],
}

FAILED = {'state': 'failed', 'wedged': False,
          'error': {'kind': 'extraction_timeout', 'retryable': True}}


def _open(wimi_session: WimiTestSession, page: WimiPage, outcome: dict) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Focus Exam',
                                  exam_description='#397')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='Focus session', date_encountered=date.today())
    entry = db.create_question_entry(
        session.id, 'A', 'B',
        explanation='<p>Hypertension causes stroke.</p>')
    db.conn.commit()

    page.goto('entry-form', query={'session_id': session.id,
                                   'entry': entry.id})
    wait_for_release(page)
    page.eval_js(FAKE_BRIDGE % json.dumps(outcome), await_promise=True)
    assert poll(page, "(() => { const b = document.querySelector('%s');"
                      " return !!b && !b.disabled; })()" % FIND), (
        'the fake said ready, but no usable Find button was drawn -- so '
        'nothing below would be measuring the press')


def _status_in_tree(page: WimiPage) -> dict:
    """The live region as Chromium hands it to assistive tech."""
    enable(page)
    tab = page.tab
    doc = tab.DOM.getDocument()
    hit = tab.DOM.querySelector(nodeId=doc['root']['nodeId'], selector=STATUS)
    if not hit.get('nodeId'):
        return {'found': False}
    nodes = tab.Accessibility.getPartialAXTree(
        nodeId=hit['nodeId'], fetchRelatives=True).get('nodes') or []
    own = next((n for n in nodes
                if (n.get('role') or {}).get('value') == 'status'), None)
    if own is None:
        return {'found': True, 'role': None, 'ignored': True, 'text': ''}
    kids = set(own.get('childIds') or [])
    text = ' '.join(str((n.get('name') or {}).get('value') or '')
                    for n in nodes if n.get('nodeId') in kids)
    return {'found': True, 'role': 'status', 'ignored': bool(own.get('ignored')),
            'text': text.strip()}


def _press_find(page: WimiPage) -> None:
    page.eval_js("document.querySelector('%s').focus()" % FIND)
    assert active_element(page).get('testid') == 'entry-form-relations-find'
    real_key(page, 'Enter')


SETTLED = ("(() => { const b = document.querySelector('%s');"
           " return !!b && b.textContent === 'Find related topics'"
           " && window.__relFakePolls() >= 2; })()" % FIND)


@pytest.mark.slow
@pytest.mark.regression
def test_the_press_keeps_focus_and_the_result_is_announced(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _open(wimi_session, wimi_page, FOUND)

    # Read before the press, asserted after the focus half so a failure of
    # either is reported for itself.
    before = _status_in_tree(wimi_page)

    _press_find(wimi_page)
    during = active_element(wimi_page)
    assert during.get('testid') == 'entry-form-relations-find', (
        f'focus left the button the student just pressed, mid-press: now on '
        f'{during}. Either the button was rebuilt instead of updated, or it '
        f'was made `disabled` -- in this Chromium a focused button that '
        f'becomes disabled drops focus to <body>, measured (#397)')

    assert before.get('role') == 'status' and not before['ignored'], (
        f'no live region was exposed before the press ({before}); one created '
        f'together with its text is often never announced')
    assert before['text'] == '', f'the region spoke before any press: {before}'
    assert poll(wimi_page, SETTLED, timeout_ms=10000), 'the fake pass never ended'

    after = active_element(wimi_page)
    assert after.get('testid') == 'entry-form-relations-find', (
        f'focus was lost when the result landed: now on {after}')
    assert wimi_page.eval_js(
        "document.querySelectorAll('%s').length" % CARD) == 2

    heard = _status_in_tree(wimi_page)
    assert not heard['ignored'], f'the live region is out of the tree: {heard}'
    assert 'WIMI suggests 2 relations' in heard['text'], heard
    assert 'already suggested on Monday block' in heard['text'], (
        f'the #390 note is on screen but was not announced: {heard}')


@pytest.mark.slow
@pytest.mark.regression
def test_a_failure_is_announced_and_try_again_keeps_focus(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _open(wimi_session, wimi_page, FAILED)
    _press_find(wimi_page)
    assert poll(wimi_page, SETTLED, timeout_ms=10000), 'the fake pass never ended'

    heard = _status_in_tree(wimi_page)
    assert 'took too long' in heard.get('text', '') and not heard.get('ignored'), (
        f'the failure is on screen but was not announced: {heard}')

    # "Try again" lives in the failure box, which the next render removes.
    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"entry-form-relations-retry\"]')"
        ".focus()")
    real_key(wimi_page, 'Enter')
    now = active_element(wimi_page)
    assert now.get('testid') == 'entry-form-relations-find', (
        f'pressing Try again dropped focus to {now}; it should land on the '
        f'Find button rather than <body>')


@pytest.mark.slow
@pytest.mark.regression
def test_answering_a_card_from_the_keyboard_keeps_focus(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _open(wimi_session, wimi_page, FOUND)
    _press_find(wimi_page)
    assert poll(wimi_page, SETTLED, timeout_ms=10000), 'the fake pass never ended'

    wimi_page.eval_js(
        "document.querySelector('%s [data-testid=\"entry-form-relation-confirm\"]')"
        ".focus()" % CARD)
    real_key(wimi_page, 'Enter')
    assert poll(wimi_page, "document.querySelectorAll('%s').length === 1"
                % CARD, timeout_ms=5000), 'the confirmed card never left'

    now = active_element(wimi_page)
    assert now.get('testid') == 'entry-form-relations-find', (
        f'the confirmed card took focus with it to {now}')
    assert 'Relation added' in _status_in_tree(wimi_page).get('text', '')
