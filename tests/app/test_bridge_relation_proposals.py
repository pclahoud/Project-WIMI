"""The extraction slots: propose, poll, accept, reject (#60, #380).

These drive the **real** ``RelationJobs`` over a fake runtime rather than a
fake job runner, because the thing most worth protecting here is the
arrangement rather than the arithmetic: the worker gets text and labels and
nothing else, the finish phase runs on the polling thread where it may touch
the database, and a wedged worker must not be offered a retry.

A fake job runner would have made the wedge test a tautology — it would assert
that the bridge renders whatever the fake reported. With the real one, the
wedge detail comes out of ``RelationJobs._wedge_detail`` and the bridge's
override of ``retryable`` is tested against the taxonomy that genuinely says
``extraction_timeout`` is retryable.

The four tests that are guards rather than examples
---------------------------------------------------
* ``test_a_wedged_worker_is_not_offered_a_retry`` — #174. After a wedge every
  later ``start`` fails identically until WIMI restarts, so a retry button is
  a guaranteed-failing press. The taxonomy puts ``extraction_timeout`` in
  ``RETRYABLE``, so the bridge has to override it, and nothing else would
  notice if that override were dropped.
* ``test_the_worker_is_never_handed_the_database`` — the thread contract.
  ``base_db.py`` records that nothing in this application writes to the
  database from a second thread.
* ``test_an_unavailable_machine_is_a_success_not_an_error`` — the owner's
  silence decision. ``success=false`` would make the page raise a toast for a
  button that should not have been drawn.
* ``test_a_rejection_and_its_deletion_are_atomic`` — if the rejection were
  recorded and the row survived, the pair would be both suppressed and
  unwritable by hand, which is exactly the trap #4883 §6.2 found in the
  ``strength = -1`` sentinel.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

import pytest

from app.bridge import DatabaseBridge
from app.relation_extraction import availability, model_spec
from app.relation_extraction.errors import RelationExtractionError
from app.relation_extraction.errors import RelationExtractionErrorKind as Kind
from app.relation_extraction.jobs import RelationJobs
from app.relation_extraction.runtime import (
    ExtractionResult,
    Mention,
    Proposal,
)
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

pytestmark = pytest.mark.unit

EXPLANATION = (
    '<p>Chronic hypertension causes hypertensive nephrosclerosis.</p>'
    '<p>Hypertension is a risk factor for stroke.</p>'
)


def payload(response: str) -> dict:
    parsed = json.loads(response)
    assert parsed['success'] is True, parsed.get('error')
    return parsed['data']


def failure(response: str) -> str:
    parsed = json.loads(response)
    assert parsed['success'] is False, parsed.get('data')
    return parsed['error']


# ==================== the world ====================

@pytest.fixture
def world():
    """A real master and user database, and the bridge over them."""
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=Path(tmpdir))
        user = master.create_user(
            username='proposer', display_name='P', user_types=['student'])
        db = UserDatabase(
            db_path=master.ensure_user_database(user.id),
            user_id=user.id, username=user.username)
        bridge = DatabaseBridge(master_db=master, user_db=db)
        try:
            yield bridge, db
        finally:
            bridge.shutdown_relation_extraction()
            db.close()
            master.close()


@pytest.fixture
def ready(monkeypatch):
    """A machine where extraction can run: runtime found, model installed."""
    monkeypatch.setattr(availability, '_missing_runtime_packages', lambda: ())
    monkeypatch.setattr(model_spec, 'missing_files', lambda _dir: ())


@pytest.fixture
def seeded(world):
    """An exam, three subjects with an alias, and an entry with a real
    HTML explanation -- which is what the column actually holds."""
    bridge, db = world
    exam = db.create_exam_context('USMLE')
    ids = {}
    for name in ('Hypertension', 'Hypertensive nephrosclerosis', 'Stroke'):
        ids[name] = db.execute(
            "INSERT INTO subject_nodes (exam_context, name, level_type, "
            "parent_id, sort_order, status) "
            "VALUES ('USMLE', ?, 'Topic', NULL, 0, 'active')",
            (name,)).lastrowid
    db.create_subject_alias(ids['Hypertension'], 'USMLE', 'HTN',
                            alias_type='acronym')
    session = db.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, "
        "total_questions, total_incorrect) VALUES (1, ?, 1, 1)",
        (exam.id,)).lastrowid
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer, explanation) VALUES (?, 1, 'a', 'b', ?)",
        (session, EXPLANATION)).lastrowid
    db.conn.commit()
    return {'exam_id': exam.id, 'entry_id': entry, 'subjects': ids}


def _type_id(db, exam_id, label):
    for t in db.get_relation_types(exam_id, include_retired=True):
        if t['label'] == label:
            return t['id']
    raise AssertionError(f'no seeded type {label!r}')


# ==================== a runtime that loads nothing ====================

class FakeRuntime:
    """Duck-types ``RelationRuntime`` for ``RelationJobs``.

    Returns prepared proposals instead of running 845 MB of weights. Records
    what it was handed, which is how the thread contract is checked.
    """

    timeout_s = 60.0

    def __init__(self, proposals=(), *, block: threading.Event = None,
                 raises: BaseException = None) -> None:
        self.proposals = tuple(proposals)
        self.block = block
        self.raises = raises
        self.calls = []
        #: Set once the pass is genuinely under way. A test that moves the
        #: clock has to wait for this rather than for ``state == 'running'``,
        #: which is already true while the job is merely queued -- the race
        #: that made the wedge test flake before it was deterministic.
        self.entered = threading.Event()

    def extract(self, text, labels, *, cancel=None, timeout_s=None,
                threshold=None, on_pass_start=None):
        # ``threshold`` is accepted and recorded rather than ignored, and this
        # is the one parameter here worth a comment. ``feat/60-threshold-setting``
        # adds a per-call ``threshold=`` that ``RelationJobs._perform`` passes
        # straight through, so a fake without it raises ``TypeError`` the
        # moment that branch merges -- which is exactly what a trial merge of
        # the two found, 17 failures from one missing keyword. Declaring it
        # now means this file is correct on both sides of that merge.
        self.calls.append({'text': text, 'labels': tuple(labels),
                           'threshold': threshold})
        if on_pass_start is not None:
            on_pass_start()
        self.entered.set()
        if self.block is not None:
            self.block.wait(10.0)
        if self.raises is not None:
            raise self.raises
        return ExtractionResult(proposals=self.proposals, ms=12, load_ms=None)

    def unload(self) -> None:
        pass


def _proposal(head, tail, type_id, label, passage, score=0.95):
    return Proposal(
        relation_type_id=type_id, label=label,
        head=Mention(text=head, start=0, end=len(head), confidence=score),
        tail=Mention(text=tail, start=30, end=30 + len(tail), confidence=score),
        score=score, passage=passage, passage_start=0,
        passage_end=len(passage),
    )


def _install(bridge, runtime, **kwargs) -> RelationJobs:
    """Give the bridge a real job runner over a fake runtime.

    ``_relations_jobs_owned`` stays false so the bridge's re-point cannot
    replace what a test just injected -- the seam only works if an injected
    runner is left exactly as handed over.
    """
    jobs = RelationJobs(runtime=runtime, **kwargs)
    bridge._relations_jobs_obj = jobs
    bridge._relations_jobs_owned = False
    return jobs


def _await(bridge, job_id, timeout_s=10.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        report = payload(bridge.pollRelationProposals(job_id))
        if report['state'] != 'running':
            return report
        time.sleep(0.01)
    raise AssertionError(f'extraction {job_id} never finished')


# ==================== prepare: what is worth a model pass ====================

def test_an_unavailable_machine_is_a_success_not_an_error(world, seeded, monkeypatch):
    """The owner's silence decision, seen from the bridge.

    The entry form is not supposed to draw the button at all when extraction
    cannot run (#5179), but a page out of step with Settings must be able to
    go quiet. ``success=false`` would raise a toast for a button that should
    not exist.
    """
    bridge, _db = world
    monkeypatch.setattr(
        availability, '_missing_runtime_packages', lambda: ('torch',))

    data = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))

    assert data['available'] is False
    assert data['started'] is False
    assert data['state'] == 'dev_runtime_missing'


def test_an_entry_with_no_explanation_starts_nothing(world, seeded, ready):
    """An ordinary state, not an error and not worth a 16 s model load."""
    bridge, db = world
    db.execute("UPDATE question_entries SET explanation = '' WHERE id = ?",
               (seeded['entry_id'],))
    db.conn.commit()

    data = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id'], 'token': 7})))

    assert data == {'available': True, 'state': 'ready', 'started': False,
                    'reason': 'no_explanation', 'token': 7}


def test_markup_alone_counts_as_no_explanation(world, seeded, ready):
    """``<p><br></p>`` is what an editor leaves behind in an untouched field.

    Without ``plain_text`` this is a non-empty string and the model would be
    asked about it.
    """
    bridge, db = world
    db.execute("UPDATE question_entries SET explanation = ? WHERE id = ?",
               ('<p><br></p>', seeded['entry_id']))
    db.conn.commit()

    data = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))
    assert data['reason'] == 'no_explanation'


def test_an_exam_with_no_subjects_starts_nothing(world, ready):
    """Nothing to match a span against, so the pass could only waste time."""
    bridge, db = world
    exam = db.create_exam_context('EMPTY')
    session = db.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, "
        "total_questions, total_incorrect) VALUES (1, ?, 1, 1)",
        (exam.id,)).lastrowid
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer, explanation) VALUES (?, 1, 'a', 'b', ?)",
        (session, EXPLANATION)).lastrowid
    db.conn.commit()

    data = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': entry})))
    assert data['started'] is False and data['reason'] == 'no_subjects'


def test_an_unknown_entry_is_a_sentence(world, ready):
    bridge, _db = world
    assert 'not found' in failure(
        bridge.proposeRelationsForEntry(json.dumps({'entry_id': 99999})))


def test_a_missing_entry_id_is_refused(world, ready):
    bridge, _db = world
    assert 'entry_id is required' in failure(
        bridge.proposeRelationsForEntry('{}'))


def test_no_user_database_is_refused(ready):
    bridge = DatabaseBridge(master_db=None, user_db=None)
    try:
        assert 'No user database' in failure(
            bridge.proposeRelationsForEntry(json.dumps({'entry_id': 1})))
    finally:
        bridge.shutdown_relation_extraction()


# ==================== the worker gets text, never a connection ============

def test_the_worker_is_never_handed_the_database(world, seeded, ready):
    """The thread contract, and it is the contract rather than a detail.

    ``base_db.py`` records that nothing in this application writes to the
    database from a second thread, and transaction depth is tracked per
    connection with a plain counter — so the breakage would be silent and
    intermittent rather than a crash. What the worker receives is a string
    and a tuple of labels.
    """
    bridge, _db = world
    runtime = FakeRuntime()
    _install(bridge, runtime)

    started = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))
    _await(bridge, started['job_id'])

    assert len(runtime.calls) == 1
    call = runtime.calls[0]
    assert isinstance(call['text'], str)
    assert '<p>' not in call['text'], (
        'the explanation column holds HTML; the model must be given prose')
    assert call['text'].startswith('Chronic hypertension causes')
    for label in call['labels']:
        assert isinstance(label.label, str) and isinstance(label.type_id, int)


def test_the_students_threshold_reaches_the_model(world, seeded, ready):
    """The stored preference, read on this thread, handed to the pass.

    m028's column is the student's cutoff (#380: 0.80 by default, 0.10-0.95).
    The worker may not read a preference -- a preference is a database read --
    so the value has to travel as a number through ``start``.
    """
    bridge, db = world
    db.update_preferences(relation_confidence_threshold=0.35)
    runtime = FakeRuntime()
    _install(bridge, runtime)

    started = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))
    _await(bridge, started['job_id'])

    assert runtime.calls[0]['threshold'] == pytest.approx(0.35)


def test_moving_the_threshold_does_not_drop_the_loaded_model(world, seeded, ready):
    """Why the cutoff is not in the runtime's cache key.

    The runtime instance holds 845 MB of loaded weights. While the threshold
    was part of its identity, moving the Settings dial rebuilt it and the next
    pass paid a ~16 s load -- for a number that is compared against scores the
    model has already produced. This asserts the instance survives the change.
    """
    bridge, db = world
    db.update_preferences(relation_confidence_threshold=0.80)
    first = bridge._relations_runtime()

    db.update_preferences(relation_confidence_threshold=0.30)
    second = bridge._relations_runtime()

    assert second is first, (
        'the dial moved and the runtime was rebuilt, so the loaded model was '
        'dropped; the threshold must not be in _relations_runtime\'s key')
    assert bridge._relations_threshold() == pytest.approx(0.30), (
        'and the new value is still what the next pass will use')


def test_a_threshold_outside_the_range_is_refused_at_the_call(
        world, seeded, ready):
    """Not as a flooded or empty panel three seconds later.

    ``update_preferences`` already refuses an out-of-range value, so reaching
    this needs a hand-edited database -- which is exactly when a sentence
    beats silence.
    """
    bridge, db = world
    _install(bridge, FakeRuntime())
    # ``get_preferences`` CREATES the row on first read, so a fresh profile
    # has none and a bare UPDATE would match nothing -- which is how this
    # test first passed against a threshold of 0.8.
    db.get_preferences()
    db.execute("UPDATE user_preferences SET relation_confidence_threshold = 0.01")
    db.conn.commit()

    message = failure(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))
    assert 'threshold' in message and '0.95' in message


def test_the_token_comes_back_untouched(world, seeded, ready):
    """The page decides whether proposals are stale; it can only do so if
    what it sent comes back (#59 §3.5)."""
    bridge, _db = world
    _install(bridge, FakeRuntime())

    started = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id'], 'token': 'abc-42'})))
    assert started['token'] == 'abc-42'

    report = _await(bridge, started['job_id'])
    assert report['token'] == 'abc-42'
    assert report['entry_id'] == seeded['entry_id']


# ==================== the finish phase writes unconfirmed rows ============

def test_a_matched_proposal_is_written_unconfirmed_with_the_passage(
        world, seeded, ready):
    """#5494: the passage is the reason, and ``confirmed_at`` is NULL.

    So the student has an invisible relation carrying their own words, which
    is visibly different from one they wrote and is not a lie.
    """
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    passage = 'Chronic hypertension causes hypertensive nephrosclerosis.'
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'hypertensive nephrosclerosis',
                  causes, 'causes', passage)]))

    started = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))
    report = _await(bridge, started['job_id'])

    assert report['state'] == 'done'
    assert len(report['proposals']) == 1
    written = report['proposals'][0]
    assert written['from_subject_id'] == seeded['subjects']['Hypertension']
    assert written['passage'] == passage

    row = db.get_subject_relation(written['relation_id'])
    assert row['origin'] == 'extracted'
    assert row['confirmed_at'] is None
    assert row['reason'] == passage
    assert row['source_entry_id'] == seeded['entry_id']
    assert db.get_subject_relations(
        seeded['subjects']['Hypertension'])['relations'] == []


def test_an_alias_resolves_to_its_subject(world, seeded, ready):
    """#380 decision 2, through the slot rather than only in the matcher."""
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('HTN', 'Stroke', causes, 'causes', 'HTN causes stroke.')]))

    started = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))
    report = _await(bridge, started['job_id'])

    assert report['proposals'][0]['from_subject_id'] == \
        seeded['subjects']['Hypertension']


def test_an_unmatched_end_is_reported_and_not_written(world, seeded, ready):
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'renal papillary necrosis', causes,
                  'causes', 'A sentence.')]))

    started = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))
    report = _await(bridge, started['job_id'])

    assert report['proposals'] == []
    assert len(report['unmatched']) == 1
    assert report['unmatched'][0]['tail_matched'] is False
    assert report['counts']['written'] == 0


def test_a_rejected_pair_is_not_proposed_again(world, seeded, ready):
    """#60's acceptance criterion, end to end through the slots."""
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    passage = 'Chronic hypertension causes hypertensive nephrosclerosis.'
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'hypertensive nephrosclerosis',
                  causes, 'causes', passage)]))

    first = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    relation_id = first['proposals'][0]['relation_id']

    rejected = payload(bridge.rejectRelationProposal(json.dumps({
        'relation_id': relation_id, 'kind': 'misread'})))
    assert rejected['deleted'] is True

    second = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    assert second['proposals'] == []
    assert second['counts']['suppressed'] == 1


def test_a_confirmed_relation_suppresses_the_proposal(world, seeded, ready):
    """m026's UNIQUE is enforced against the row whether or not it is visible,
    so proposing the pair again would be a refusal the student did not cause.

    **Rewritten for #382.** This used to run the extraction twice and assert
    the second pass suppressed everything -- which was true, and was the old
    behaviour: the first pass's own unconfirmed rows occupied the UNIQUE. Now
    a re-run discards them first, so that version was asserting exactly what
    the owner decided against. The claim it was *for* is unchanged and is
    tested here against a **confirmed** relation, which is what "already
    carries one" has to mean once a proposal is no longer permanent.
    """
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    passage = 'Chronic hypertension causes hypertensive nephrosclerosis.'
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'hypertensive nephrosclerosis',
                  causes, 'causes', passage)]))

    first = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    assert len(first['proposals']) == 1
    db.confirm_subject_relation(first['proposals'][0]['relation_id'])

    second = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    assert second['proposals'] == []
    assert second['counts']['suppressed'] == 1


def test_re_running_replaces_that_entrys_own_proposals(world, seeded, ready):
    """#382's expiry decision: re-extraction is the only thing that expires one.

    And the ordering inside the finish phase is what makes it work. Reading
    the suppression set *before* the discard would leave the previous run's
    own rows in it, so every pair would come back suppressed and the second
    pass would write nothing -- which is the shape the test above used to
    assert.
    """
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'hypertensive nephrosclerosis',
                  causes, 'causes', 'A sentence.')]))

    first = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    was = first['proposals'][0]['relation_id']

    second = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])

    assert second['counts']['previous_discarded'] == 1
    assert len(second['proposals']) == 1, (
        're-running must propose again, not report its own previous rows as '
        'suppressed')
    assert second['proposals'][0]['relation_id'] != was, 'a fresh row'
    assert db.get_subject_relation(was) is None, 'and the old one is gone'


def test_re_running_keeps_what_the_student_confirmed_or_rejected(
        world, seeded, ready):
    """The two things a re-run must never undo.

    A confirmed extraction is a relation the student endorsed, and a
    rejection is a judgement they recorded. Both survive, by different
    mechanisms -- ``confirmed_at IS NULL`` in the discard, and m027 being its
    own table.
    """
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    risk = _type_id(db, seeded['exam_id'], 'risk factor for')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'hypertensive nephrosclerosis', causes,
                  'causes', 'One.'),
        _proposal('hypertension', 'Stroke', risk, 'risk factor for', 'Two.'),
    ]))

    first = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    by_type = {p['relation_type_id']: p['relation_id']
               for p in first['proposals']}
    kept = by_type[causes]
    db.confirm_subject_relation(kept)
    payload(bridge.rejectRelationProposal(json.dumps({
        'relation_id': by_type[risk], 'kind': 'not_related'})))

    second = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])

    assert db.get_subject_relation(kept) is not None, (
        'a confirmed extraction is the student\'s relation, not a proposal')
    assert db.get_subject_relation(kept)['confirmed_at'] is not None
    assert second['proposals'] == [], (
        'one pair is confirmed and the other rejected, so neither is proposed')
    assert second['counts']['suppressed'] == 2
    assert second['counts']['previous_discarded'] == 0, (
        'there was nothing unconfirmed left to discard')


def test_one_refused_proposal_does_not_lose_the_others(world, seeded, ready):
    """A passage over MAX_REASON_LENGTH is a run-on sentence, not a bug.

    Truncating it would store words the student did not write as their own
    reason, so it is refused and reported while the rest are written.
    """
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    risk = _type_id(db, seeded['exam_id'], 'risk factor for')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'hypertensive nephrosclerosis', causes,
                  'causes', 'x' * 2500),
        _proposal('hypertension', 'Stroke', risk, 'risk factor for',
                  'Hypertension is a risk factor for stroke.'),
    ]))

    report = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])

    assert len(report['proposals']) == 1
    assert len(report['refused']) == 1
    assert 'characters' in report['refused'][0]['error']


# ==================== failure, cancellation and the wedge ================

def test_a_failure_arrives_with_its_kind(world, seeded, ready):
    bridge, _db = world
    _install(bridge, FakeRuntime(raises=RelationExtractionError(
        Kind.OUT_OF_MEMORY, 'ran out of memory', detail='DefaultCPUAllocator')))

    report = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])

    assert report['state'] == 'failed'
    assert report['error']['kind'] == 'out_of_memory'
    assert report['error']['retryable'] is False, (
        'a second identical pass on the same machine fails the same way')
    assert report['wedged'] is False


def test_a_wedged_worker_is_not_offered_a_retry(world, seeded, ready):
    """#174, and the taxonomy is against us here, which is the point.

    ``extraction_timeout`` is in ``RETRYABLE`` -- an overrunning pass really
    is worth retrying. A **wedge** is not: ``RelationJobs`` refuses every
    later ``start`` with the same error until WIMI restarts, so a retry
    button would be a guaranteed-failing press. The bridge therefore
    overrides ``retryable``, and this is the only test that would notice if
    that override were dropped.
    """
    bridge, _db = world
    held = threading.Event()
    clock = [0.0]
    runtime = FakeRuntime(block=held)
    try:
        _install(bridge, runtime, clock=lambda: clock[0])

        started = payload(bridge.proposeRelationsForEntry(
            json.dumps({'entry_id': seeded['entry_id']})))
        job_id = started['job_id']

        # Wait for the pass to be genuinely under way, then move the clock
        # past twice the runtime's ceiling. Waiting for ``state == 'running'``
        # instead is a race: that is already true while the job is queued, so
        # the clock could jump before ``pass_started`` was ever written and
        # the watchdog would have nothing to measure.
        assert runtime.entered.wait(5.0), 'the pass never started'
        clock[0] = 10_000.0

        report = payload(bridge.pollRelationProposals(job_id))
        assert report['state'] == 'failed'
        assert report['wedged'] is True
        assert report['error']['kind'] == 'extraction_timeout'
        assert report['error']['retryable'] is False, (
            'after a wedge every start fails identically until a restart; '
            'offering "Try again" spends the student on a press that cannot '
            'work (#174)')
    finally:
        held.set()


def test_the_taxonomy_really_does_call_a_timeout_retryable():
    """The control for the test above. Without it that assertion is vacuous.

    If ``extraction_timeout`` were simply not retryable, the bridge's override
    would be doing nothing and nobody would know.
    """
    from app.relation_extraction.errors import RETRYABLE
    assert Kind.EXTRACTION_TIMEOUT in RETRYABLE


def test_cancelling_reports_whether_there_was_anything_to_stop(world, seeded, ready):
    bridge, _db = world
    held = threading.Event()
    try:
        _install(bridge, FakeRuntime(block=held))
        started = payload(bridge.proposeRelationsForEntry(
            json.dumps({'entry_id': seeded['entry_id']})))

        assert payload(bridge.cancelRelationExtraction(
            started['job_id']))['cancelled'] is True
        assert payload(bridge.cancelRelationExtraction(
            'nope'))['cancelled'] is False
    finally:
        held.set()


def test_an_unknown_job_polls_as_a_failure(world, ready):
    bridge, _db = world
    _install(bridge, FakeRuntime())
    report = payload(bridge.pollRelationProposals('nope'))

    assert report['state'] == 'failed'
    assert report['error']['kind'] == 'unknown_job'
    assert report['job_id'] == 'nope'


def test_a_stray_poll_does_not_build_a_runtime(world, ready):
    """A poll of an id nobody issued must not start a worker thread.

    ``_relations_jobs()`` builds a runtime and a daemon worker on first use,
    so reaching for it here would mean a stray poll -- from a page reloaded
    with a stale id -- constructing the machinery for a job that does not
    exist. The answer is ``unknown_job`` either way.
    """
    bridge, _db = world
    assert getattr(bridge, '_relations_jobs_obj', None) is None

    report = payload(bridge.pollRelationProposals('nope'))

    assert report['error']['kind'] == 'unknown_job'
    assert getattr(bridge, '_relations_jobs_obj', None) is None
    assert getattr(bridge, '_relations_runtime_obj', None) is None


def test_the_previous_extraction_is_forgotten_when_a_new_one_starts(
        world, seeded, ready):
    """Not on the first terminal poll, and not this one.

    A page polls once more after it sees a result, so forgetting earlier
    turns that into ``unknown_job`` -- which it would render as a failure.
    Forgetting the previous one instead keeps memory bounded: each finished
    job holds a vocabulary of the whole exam in its ``finish`` closure.
    """
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'Stroke', causes, 'causes', 'A sentence.')]))

    first = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id']
    done = _await(bridge, first)
    assert done['state'] == 'done'
    assert payload(bridge.pollRelationProposals(first))['state'] == 'done', (
        'the second poll of a finished job still answers')

    second = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id']
    _await(bridge, second)

    assert payload(bridge.pollRelationProposals(first))['error']['kind'] == \
        'unknown_job'
    assert payload(bridge.pollRelationProposals(second))['state'] == 'done'


def test_a_closed_profile_mid_pass_is_reported_not_written(world, seeded, ready):
    """The database is swapped on a profile switch, so ``finish`` has to
    resolve ``self.user_db`` at call time rather than capturing it."""
    bridge, _db = world
    held = threading.Event()
    causes = _type_id(bridge.user_db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'Stroke', causes, 'causes', 'A sentence.')],
        block=held))

    started = payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))
    kept, bridge.user_db = bridge.user_db, None
    held.set()
    try:
        report = _await(bridge, started['job_id'])
        assert report['state'] == 'done'
        assert report['reason'] == 'profile_closed'
        assert report['proposals'] == []
    finally:
        bridge.user_db = kept


# ==================== accept ====================

def test_accepting_confirms_and_the_relation_becomes_visible(world, seeded, ready):
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'Stroke', causes, 'causes', 'A sentence.')]))
    report = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    relation_id = report['proposals'][0]['relation_id']

    confirmed = payload(bridge.acceptRelationProposal(
        json.dumps({'relation_id': relation_id})))

    assert confirmed['confirmed_at'] is not None
    panel = db.get_subject_relations(seeded['subjects']['Hypertension'])
    assert [r['relation_id'] for r in panel['relations']] == [relation_id]


def test_accepting_with_an_edited_reason_and_a_new_type(world, seeded, ready):
    """#4904: 11 of 31 rejections were "right pair, wrong type"."""
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    risk = _type_id(db, seeded['exam_id'], 'risk factor for')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'Stroke', causes, 'causes', 'A sentence.')]))
    report = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    relation_id = report['proposals'][0]['relation_id']

    confirmed = payload(bridge.acceptRelationProposal(json.dumps({
        'relation_id': relation_id,
        'reason': 'High pressure damages the vessels that supply the brain.',
        'relation_type_id': risk,
        'change_type': True,
    })))

    assert confirmed['relation_type_id'] == risk
    assert confirmed['reason'].startswith('High pressure damages')


def test_a_blank_reason_is_refused_with_its_sentence(world, seeded, ready):
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'Stroke', causes, 'causes', 'A sentence.')]))
    report = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])

    message = failure(bridge.acceptRelationProposal(json.dumps({
        'relation_id': report['proposals'][0]['relation_id'],
        'reason': '  '})))
    assert 'needs a reason' in message


def test_accepting_needs_a_relation_id(world, ready):
    bridge, _db = world
    assert 'relation_id is required' in failure(
        bridge.acceptRelationProposal('{}'))


# ==================== reject ====================

def test_the_kind_has_no_default(world, seeded, ready):
    """A rejection whose kind nobody recorded cannot be scoped, and guessing
    is exactly how the ``strength = -1`` sentinel behaved."""
    bridge, _db = world
    message = failure(bridge.rejectRelationProposal(json.dumps({
        'from_subject_id': seeded['subjects']['Hypertension'],
        'to_subject_id': seeded['subjects']['Stroke']})))

    assert 'kind is required' in message
    assert 'misread' in message and 'not_related' in message


def test_a_misread_is_scoped_to_its_entry(world, seeded, ready):
    """25 of 45 rejections meant "you misread my sentence". The same pair may
    extract perfectly from a different explanation tomorrow."""
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'Stroke', causes, 'causes', 'A sentence.')]))
    report = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])

    result = payload(bridge.rejectRelationProposal(json.dumps({
        'relation_id': report['proposals'][0]['relation_id'],
        'kind': 'misread'})))

    assert result['rejection']['kind'] == 'misread'
    assert result['rejection']['source_entry_id'] == seeded['entry_id']
    assert db.rejected_pairs_for_entry(None) == set(), (
        'a misread suppresses nothing outside its own entry'
    )
    assert db.rejected_pairs_for_entry(seeded['entry_id'])


def test_a_rejection_and_its_deletion_are_atomic(world, seeded, ready, monkeypatch):
    """Recording the rejection without removing the row is the worst state.

    The pair would be suppressed *and* still occupy m026's UNIQUE, so the
    student could neither be proposed it again nor write it by hand -- which
    is the trap #4883 §6.2 found in the sentinel, reached another way.
    """
    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    _install(bridge, FakeRuntime([
        _proposal('hypertension', 'Stroke', causes, 'causes', 'A sentence.')]))
    report = _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': seeded['entry_id']})))['job_id'])
    relation_id = report['proposals'][0]['relation_id']

    def explode(_rid):
        raise RuntimeError('the delete failed')
    monkeypatch.setattr(db, 'delete_subject_relation', explode)

    assert 'the delete failed' in failure(bridge.rejectRelationProposal(
        json.dumps({'relation_id': relation_id, 'kind': 'not_related'})))

    assert db.get_subject_relation(relation_id) is not None
    assert db.rejected_pairs_for_entry(seeded['entry_id']) == set(), (
        'the rejection rolled back with the delete, so the pair is neither '
        'suppressed nor orphaned')


def test_rejecting_a_pair_with_no_row_is_allowed(world, seeded, ready):
    """"These two are not related" is a judgement a student may record
    without a proposal in front of them."""
    bridge, db = world
    result = payload(bridge.rejectRelationProposal(json.dumps({
        'from_subject_id': seeded['subjects']['Hypertension'],
        'to_subject_id': seeded['subjects']['Stroke'],
        'kind': 'not_related'})))

    assert result['deleted'] is False
    assert db.rejected_pairs_for_entry(None)


def test_rejecting_an_unknown_relation_is_a_sentence(world, ready):
    bridge, _db = world
    assert 'not found' in failure(bridge.rejectRelationProposal(
        json.dumps({'relation_id': 4242, 'kind': 'misread'})))


# ==================== #390: a pair waiting on another entry ====================
#
# Owner's decision on #390: when a pair is suppressed because an UNANSWERED
# proposal for it sits on another entry, the card says so, naming that entry.
# A suppressed pair can be in four states and only that one gets a note --
# each of the other three is asserted silent below, because each would read
# as a bug if it named an entry.

PENDING_PASSAGE = 'Chronic hypertension causes hypertensive nephrosclerosis.'


def _second_entry(db, seeded) -> int:
    session = db.fetchone(
        'SELECT review_session_id FROM question_entries WHERE id = ?',
        (seeded['entry_id'],))['review_session_id']
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer, explanation) VALUES (?, 2, 'a', 'b', ?)",
        (session, EXPLANATION)).lastrowid
    db.conn.commit()
    return entry


def _propose_on(bridge, entry_id) -> dict:
    return _await(bridge, payload(bridge.proposeRelationsForEntry(
        json.dumps({'entry_id': entry_id})))['job_id'])


def _same_pair_runtime(db, seeded):
    causes = _type_id(db, seeded['exam_id'], 'causes')
    return causes, FakeRuntime([
        _proposal('hypertension', 'hypertensive nephrosclerosis',
                  causes, 'causes', PENDING_PASSAGE)])


def test_a_pair_waiting_on_another_entry_is_named(world, seeded, ready):
    bridge, db = world
    causes, runtime = _same_pair_runtime(db, seeded)
    _install(bridge, runtime)
    db.execute("UPDATE review_sessions SET session_name = 'IM Day 11'")
    db.conn.commit()
    other = _second_entry(db, seeded)

    first = _propose_on(bridge, seeded['entry_id'])
    assert len(first['proposals']) == 1      # left unanswered

    second = _propose_on(bridge, other)
    assert second['proposals'] == []
    assert second['pending_elsewhere'] == [{
        'from_subject_name': 'Hypertension',
        'to_subject_name': 'Hypertensive nephrosclerosis',
        'label': 'causes',
        'relation_type_id': causes,
        'entry_id': seeded['entry_id'],
        'session_name': 'IM Day 11',
        'entry_order': 1,
    }]


def test_an_entrys_own_rerun_names_nothing(world, seeded, ready):
    """Its own previous proposals are discarded, not "waiting elsewhere"."""
    bridge, db = world
    _causes, runtime = _same_pair_runtime(db, seeded)
    _install(bridge, runtime)

    _propose_on(bridge, seeded['entry_id'])
    again = _propose_on(bridge, seeded['entry_id'])
    assert len(again['proposals']) == 1
    assert again['pending_elsewhere'] == []


def test_a_rejected_pair_gets_no_note_even_while_pending_elsewhere(
        world, seeded, ready):
    """The student's own rejection wins, though the pending row still exists.

    The matcher sees one union and cannot say which source suppressed a
    pair; re-surfacing a pair the student rejected undoes the rejection.
    """
    bridge, db = world
    causes, runtime = _same_pair_runtime(db, seeded)
    _install(bridge, runtime)
    other = _second_entry(db, seeded)
    _propose_on(bridge, seeded['entry_id'])           # pending on entry 1
    payload(bridge.rejectRelationProposal(json.dumps({
        'from_subject_id': seeded['subjects']['Hypertension'],
        'to_subject_id': seeded['subjects']['Hypertensive nephrosclerosis'],
        'relation_type_id': causes,
        'kind': 'not_related'})))

    second = _propose_on(bridge, other)
    assert second['proposals'] == []
    assert second['pending_elsewhere'] == []


def test_a_confirmed_relation_gets_no_note(world, seeded, ready):
    """It is on the deep-dive panel already; "waiting for you" would be false."""
    bridge, db = world
    _causes, runtime = _same_pair_runtime(db, seeded)
    _install(bridge, runtime)
    other = _second_entry(db, seeded)
    first = _propose_on(bridge, seeded['entry_id'])
    db.confirm_subject_relation(first['proposals'][0]['relation_id'])

    second = _propose_on(bridge, other)
    assert second['proposals'] == []
    assert second['pending_elsewhere'] == []


def test_a_hand_written_relation_gets_no_note(world, seeded, ready):
    """``origin='user'`` has no entry to name at all."""
    bridge, db = world
    causes, runtime = _same_pair_runtime(db, seeded)
    _install(bridge, runtime)
    db.create_subject_relation(
        seeded['subjects']['Hypertension'],
        seeded['subjects']['Hypertensive nephrosclerosis'],
        'Written by hand.', relation_type_id=causes)

    report = _propose_on(bridge, seeded['entry_id'])
    assert report['proposals'] == []
    assert report['pending_elsewhere'] == []


def test_a_hidden_proposal_is_not_reported_as_pending(world, seeded, ready):
    """Hidden means a subject was archived (#15); naming an entry reads as a bug.

    Driven at the query, because an archived subject is also out of the
    vocabulary, so the matcher never reaches the pair through the bridge.
    """
    bridge, db = world
    _causes, runtime = _same_pair_runtime(db, seeded)
    _install(bridge, runtime)
    other = _second_entry(db, seeded)
    first = _propose_on(bridge, seeded['entry_id'])
    assert db.pending_proposals_elsewhere('USMLE', other)   # control

    db.execute("UPDATE subject_relations SET hidden_batch_id = 'b1' WHERE id = ?",
               (first['proposals'][0]['relation_id'],))
    db.conn.commit()
    assert db.pending_proposals_elsewhere('USMLE', other) == {}


def test_a_pair_with_no_name_gets_no_note(world, seeded):
    """``MatchedProposal``'s names are Optional; a note must never say None."""
    from app.relation_extraction.matching import MatchedProposal

    bridge, db = world
    causes = _type_id(db, seeded['exam_id'], 'causes')
    key = (1, 2, causes)

    class _Db:
        @staticmethod
        def pending_proposals_elsewhere(_exam, _entry):
            return {key: {'entry_id': 9, 'session_name': 'S', 'entry_order': 1}}

    unnamed = MatchedProposal(
        proposal=_proposal('a', 'b', causes, 'causes', 'x'),
        from_subject_id=1, to_subject_id=2)
    named = MatchedProposal(
        proposal=_proposal('a', 'b', causes, 'causes', 'x'),
        from_subject_id=1, to_subject_id=2,
        from_subject_name='A', to_subject_name='B')

    assert bridge._relations_pending_elsewhere(
        _Db, (unnamed,), set(), 'USMLE', 5, frozenset()) == []
    assert len(bridge._relations_pending_elsewhere(
        _Db, (named,), set(), 'USMLE', 5, frozenset())) == 1   # control
