"""Put one relation proposal card on the entry form WITHOUT the model (#399, #400).

Why the model is faked
----------------------
The cards only exist after a pass of the relations runtime -- 1.2 GB of torch
and 845 MB of weights -- and the test venv deliberately carries neither, so on
an ordinary machine ``getRelationExtractionStatus`` says the feature cannot
run and the module renders **nothing** (#5179; the silence scenario guards
that). ``test_relation_proposals_press_and_confirm.py`` is the scenario that
needs the real model, and it skips without one.

What #399 and #400 are about is how a card *renders*, which does not depend
on where the proposal came from. So this replaces the three bridge calls the
module makes -- status, start, poll -- on ``window.api`` from the page, and
then drives the module through its own public surface: ``loadTypes`` (real,
against the seeded exam), ``refresh`` and a hit-tested press of **Find related
topics**. Everything from the press onwards is the shipped code path; only the
answers are canned. The relation types come from the real bridge, so the type
select is the one a student sees.

``EntryState`` is read through the bare name: it is a script-scope ``const``,
and ``window.EntryState`` is ``undefined`` without an error.
"""
from __future__ import annotations

import json
from datetime import date

from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage

PASSAGE = 'Hypertension is a risk factor for stroke.'

CARD = '[data-testid="entry-form-relation-proposal"]'
REASON = '[data-testid="entry-form-relation-reason"]'
CONFIRM = '[data-testid="entry-form-relation-confirm"]'
MISREAD = '[data-testid="entry-form-relation-misread"]'
NOT_RELATED = '[data-testid="entry-form-relation-not-related"]'
FIND = '[data-testid="entry-form-relations-find"]'

_FAKE_BRIDGE = """
(() => {
  const typeId = %d;
  // FAKED: the relations runtime is not in the test venv. See the module
  // docstring of fake_relation_card.py.
  window.api.getRelationExtractionStatus = () =>
      Promise.resolve({ready: true, state: 'ready'});
  window.api.proposeRelationsForEntry = (params) => {
    window.__fakeRelToken = params.token;
    return Promise.resolve({available: true, started: true, job_id: 'fake'});
  };
  window.api.pollRelationProposals = () => Promise.resolve({
    state: 'done',
    entry_id: EntryState.currentEntry.id,
    token: window.__fakeRelToken,
    proposals: [{relation_id: 9001, from_subject_name: 'Hypertension',
                 label: 'risk factor for', to_subject_name: 'Stroke',
                 passage: %s, relation_type_id: typeId}],
  });
  return true;
})()
"""


def _seed(db) -> dict:
    exam = db.create_exam_context(
        exam_name='Card Exam', exam_description='#399/#400 -- a rendered card')
    for name in ('Hypertension', 'Stroke'):
        db.create_subject_node(
            exam_context=exam.exam_name, name=name, level_type='Topic')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='Card session', date_encountered=date.today())
    entry = db.create_question_entry(
        session.id, 'A', 'B', explanation='<p>' + PASSAGE + '</p>')
    db.conn.commit()
    types = db.get_relation_types(exam.id)
    assert types, 'the exam was seeded with no relation types'
    return {'exam_id': exam.id, 'session_id': session.id,
            'entry_id': entry.id, 'type_id': types[0]['id']}


def open_card(page: WimiPage, db) -> None:
    """Open a saved entry and get exactly one proposal card on it."""
    world = _seed(db)
    page.goto('entry-form', query={'session_id': world['session_id'],
                                   'entry': world['entry_id']})
    wait_for_release(page)

    # Positive control: the module is attached and the form opened the entry,
    # so anything missing below is the card, not the page.
    assert poll(page, "(() => typeof EntryState !== 'undefined'"
                      " && !!EntryState.relationProposals"
                      " && !!EntryState.currentEntry"
                      " && EntryState.currentEntry.id === %d)()"
                % world['entry_id']), (
        'the entry form never attached relation proposals to the seeded entry')

    assert page.eval_js(_FAKE_BRIDGE % (world['type_id'], json.dumps(PASSAGE)))
    page.eval_js("window.__fakeRelReady = false;"
                 " EntryState.relationProposals.loadTypes(%d)"
                 "  .then(() => EntryState.relationProposals.refresh())"
                 "  .then(() => { window.__fakeRelReady = true; })"
                 % world['exam_id'])
    assert poll(page, 'window.__fakeRelReady === true')
    assert poll(page, "(() => { const b = document.querySelector(%s);"
                      " return !!b && !b.disabled; })()" % json.dumps(FIND)), (
        'Find related topics never became pressable with the faked status')

    real_click(page, centre_of(page, FIND))
    assert poll(page, 'document.querySelectorAll(%s).length === 1'
                % json.dumps(CARD)), 'the faked pass drew no card'
