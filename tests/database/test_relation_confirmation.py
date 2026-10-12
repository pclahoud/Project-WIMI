"""Confirming an extracted relation, and the reads extraction needs (#60).

Owner's decision (#5494): *"the reason is the passage, prefilled and editable,
and confirming is a separate act"*. An extracted relation is inserted with the
passage as its reason and `confirmed_at` NULL, and is **invisible** until the
student endorses it — `UNCONFIRMED_IS_HIDDEN` keeps it out of the deep dive's
panel and out of the incoming counts.

So the centre of this file is the pair that proves the two halves agree: an
extracted relation does not reach the panel, and confirming it is what puts it
there. Either half alone passes against a feature that does nothing.

Two others are about refusals that would otherwise arrive as an
`IntegrityError` three frames down (#66 2.2): a reason edited to blank, and a
retype onto a pair that already carries that type.

`get_extraction_vocabulary` and `existing_relation_pairs` are the two reads
the proposal filter runs on every extraction, and the comments they carry —
`status = 'active'`, `includes-unconfirmed` — are both load-bearing. Tests
here, not only in the matcher, because the matcher is handed a vocabulary and
cannot tell whether an archived subject was in it.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from database.exceptions import SubjectNodeError, ValidationError
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

pytestmark = pytest.mark.database


@pytest.fixture
def user_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterDatabase(data_dir=Path(tmpdir))
        user = master.create_user(
            username='confirm_user', display_name='Confirm',
            user_types=['student'])
        db = UserDatabase(
            db_path=master.ensure_user_database(user.id),
            user_id=user.id, username=user.username)
        try:
            yield db
        finally:
            db.close()
            master.close()


@pytest.fixture
def exam(user_db):
    return user_db.create_exam_context('USMLE').id


def _node(user_db, name: str, status: str = 'active') -> int:
    cursor = user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, "
        "sort_order, status) VALUES ('USMLE', ?, 'Topic', NULL, 0, ?)",
        (name, status))
    user_db.conn.commit()
    return cursor.lastrowid


def _type_id(user_db, exam_id: int, label: str) -> int:
    for t in user_db.get_relation_types(exam_id, include_retired=True):
        if t['label'] == label:
            return t['id']
    raise AssertionError(f'no seeded type {label!r}')


def _entry(user_db, exam_id: int, order: int = 1) -> int:
    session = user_db.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, "
        "total_questions, total_incorrect) VALUES (1, ?, 1, 1)",
        (exam_id,)).lastrowid
    cursor = user_db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer) VALUES (?, ?, 'a', 'b')",
        (session, order))
    user_db.conn.commit()
    return cursor.lastrowid


def _extracted(user_db, exam_id, from_id, to_id, *, label='causes',
               passage='Chronic hypertension causes nephrosclerosis.'):
    return user_db.create_subject_relation(
        from_id, to_id, passage,
        origin='extracted',
        source_entry_id=_entry(user_db, exam_id),
        relation_type_id=_type_id(user_db, exam_id, label),
    )


# ==================== the pair that matters ====================

def test_an_extracted_relation_is_invisible_until_confirmed(user_db, exam):
    """Half one. A proposal the student never looked at is not a relation."""
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    relation = _extracted(user_db, exam, htn, neph)

    assert relation['confirmed_at'] is None
    panel = user_db.get_subject_relations(htn)
    assert panel['relations'] == [], (
        'UNCONFIRMED_IS_HIDDEN: an unconfirmed extraction must not reach the '
        'deep dive (owner, #5494 decision 3)')


def test_confirming_is_what_puts_it_on_the_panel(user_db, exam):
    """Half two, and the control that makes half one a finding not a tautology.

    Without this, a feature that simply never rendered anything would pass the
    test above.
    """
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    relation = _extracted(user_db, exam, htn, neph)

    confirmed = user_db.confirm_subject_relation(relation['id'])

    assert confirmed['confirmed_at'] is not None
    panel = user_db.get_subject_relations(htn)
    assert len(panel['relations']) == 1
    # The panel calls it ``relation_id``; the row calls it ``id``.
    assert panel['relations'][0]['relation_id'] == relation['id']


def test_the_passage_is_the_reason_and_survives_confirmation(user_db, exam):
    """#4695 §4: the student's own sentence IS the reason, not an extra field.

    Storing offsets instead was rejected because it leaves nothing to put in a
    NOT NULL column and an edit to the entry silently invalidates them.
    """
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    passage = 'Chronic hypertension causes hypertensive nephrosclerosis.'
    relation = _extracted(user_db, exam, htn, neph, passage=passage)

    assert relation['reason'] == passage
    assert user_db.confirm_subject_relation(
        relation['id'])['reason'] == passage


# ==================== editing while confirming ====================

def test_the_student_may_edit_the_prefilled_reason(user_db, exam):
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    relation = _extracted(user_db, exam, htn, neph)

    edited = user_db.confirm_subject_relation(
        relation['id'], reason='Sustained high pressure scars the arterioles.')

    assert edited['reason'] == 'Sustained high pressure scars the arterioles.'
    assert edited['confirmed_at'] is not None


def test_a_reason_edited_to_blank_is_refused(user_db, exam):
    """Decision 2 holds on this path too, and there is no explain-later state.

    The refusal has to be a sentence rather than a CHECK constraint surfacing
    as an IntegrityError, because the student is looking at the field.
    """
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    relation = _extracted(user_db, exam, htn, neph)

    with pytest.raises(ValidationError, match='needs a reason'):
        user_db.confirm_subject_relation(relation['id'], reason='   ')

    assert user_db.get_subject_relation(
        relation['id'])['confirmed_at'] is None, 'and it stayed unconfirmed'


def test_the_type_can_be_changed_while_confirming(user_db, exam):
    """#4904: 11 of 31 rejections were "right pair, wrong type".

    Those are fixed by choosing the right type, not by rejecting a true pair,
    so retyping has to be possible at the moment of endorsement.
    """
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    relation = _extracted(user_db, exam, htn, stroke, label='causes')
    wanted = _type_id(user_db, exam, 'risk factor for')

    retyped = user_db.confirm_subject_relation(
        relation['id'], relation_type_id=wanted, change_type=True)

    assert retyped['relation_type_id'] == wanted
    assert retyped['confirmed_at'] is not None


def test_leaving_the_type_alone_is_distinguishable_from_clearing_it(user_db, exam):
    """``None`` is a legitimate value for that column, hence ``change_type``.

    Without the flag a bare default could not tell "leave the type alone" from
    "make it untyped", and one of those silently retypes a relation the
    student did not retype.
    """
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    causes = _type_id(user_db, exam, 'causes')
    relation = _extracted(user_db, exam, htn, stroke, label='causes')

    kept = user_db.confirm_subject_relation(relation['id'])
    assert kept['relation_type_id'] == causes

    cleared = user_db.confirm_subject_relation(
        relation['id'], relation_type_id=None, change_type=True)
    assert cleared['relation_type_id'] is None


def test_a_retired_type_cannot_be_chosen_while_confirming(user_db, exam):
    """A retired type is one the student said they no longer want.

    The same rule as at creation, which is why both paths call one helper.
    """
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    relation = _extracted(user_db, exam, htn, stroke)
    doomed = _type_id(user_db, exam, 'confused with')
    user_db.retire_relation_type(doomed)

    with pytest.raises(ValidationError, match='retired'):
        user_db.confirm_subject_relation(
            relation['id'], relation_type_id=doomed, change_type=True)


def test_retyping_onto_an_existing_relation_is_a_sentence(user_db, exam):
    """m026's UNIQUE would otherwise raise an IntegrityError three frames down.

    Reachable: the student already wrote *A risk factor for B* by hand, and the
    extractor proposes *A causes B* which they want to retype to the same
    thing.
    """
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    risk = _type_id(user_db, exam, 'risk factor for')
    user_db.create_subject_relation(
        htn, stroke, 'Written by hand.', relation_type_id=risk)
    proposal = _extracted(user_db, exam, htn, stroke, label='causes')

    with pytest.raises(ValidationError, match='already carry a relation'):
        user_db.confirm_subject_relation(
            proposal['id'], relation_type_id=risk, change_type=True)


def test_confirming_twice_does_not_restamp_the_endorsement(user_db, exam):
    """The student pressing twice has not done anything wrong.

    ``confirmed_at`` records the moment they endorsed it, so a second press
    must not move it later — ``COALESCE`` rather than an unconditional write.
    """
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    relation = _extracted(user_db, exam, htn, neph)

    first = user_db.confirm_subject_relation(relation['id'])
    again = user_db.confirm_subject_relation(relation['id'])
    assert again['confirmed_at'] == first['confirmed_at']

    with_edit = user_db.confirm_subject_relation(
        relation['id'], reason='Edited after confirming.')
    assert with_edit['confirmed_at'] == first['confirmed_at']
    assert with_edit['reason'] == 'Edited after confirming.'


def test_an_unknown_relation_is_a_sentence_not_a_crash(user_db):
    with pytest.raises(SubjectNodeError, match='not found'):
        user_db.confirm_subject_relation(4242)


# ==================== writing by hand onto a proposal (#382) ====================

def test_a_manual_relation_adopts_an_unconfirmed_proposal(user_db, exam):
    """Owner's decision (#382): the student's words confirm it, not a refusal.

    They have written a reason for exactly this pair and type, and #14's
    decision 2 says writing the reason IS the confirmation -- so refusing
    them would be refusing on the strength of a row they cannot see.
    """
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    entry = _entry(user_db, exam)
    causes = _type_id(user_db, exam, 'causes')
    proposal = user_db.create_subject_relation(
        htn, stroke, 'Hypertension causes stroke.', origin='extracted',
        source_entry_id=entry, relation_type_id=causes)

    result = user_db.create_subject_relation(
        htn, stroke, 'High pressure damages the vessels supplying the brain.',
        relation_type_id=causes, strength=3)

    assert result['id'] == proposal['id'], 'one relation, not two'
    assert result['adopted_proposal'] is True
    assert result['adopted_from_entry_id'] == entry
    assert result['reason'].startswith('High pressure damages')
    assert result['confirmed_at'] is not None
    assert result['strength'] == 3, "the student's strength, not the default"
    # Provenance kept: the entry really is where the pair was first noticed,
    # which is a true statement about discovery rather than about authorship.
    assert result['origin'] == 'extracted'
    assert result['source_entry_id'] == entry
    assert len(user_db.get_subject_relations(htn)['relations']) == 1


def test_a_confirmed_relation_is_still_refused(user_db, exam):
    """"Stating it twice" is still the right refusal for a visible relation.

    The adoption exists because the row was invisible. Once it is on the
    panel the student can see it and edit it, so a second one is the
    duplicate #14 refuses.
    """
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    causes = _type_id(user_db, exam, 'causes')
    user_db.create_subject_relation(
        htn, stroke, 'Written by hand.', relation_type_id=causes)

    with pytest.raises(ValidationError, match='already related'):
        user_db.create_subject_relation(
            htn, stroke, 'Again, by hand.', relation_type_id=causes)


def test_a_confirmed_extraction_is_also_still_refused(user_db, exam):
    """Endorsing a proposal makes it the student's relation, not a proposal."""
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    causes = _type_id(user_db, exam, 'causes')
    proposal = _extracted(user_db, exam, htn, stroke)
    user_db.confirm_subject_relation(proposal['id'])

    with pytest.raises(ValidationError, match='already related'):
        user_db.create_subject_relation(
            htn, stroke, 'By hand now.', relation_type_id=causes)


def test_a_different_type_is_not_a_collision_at_all(user_db, exam):
    """m026's UNIQUE is per (from, to, type), so there is nothing to adopt.

    Worth asserting because it bounds the whole feature: adoption can only
    ever involve the *same* type, so it never retypes anything.
    """
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    _extracted(user_db, exam, htn, stroke, label='causes')

    risk = _type_id(user_db, exam, 'risk factor for')
    written = user_db.create_subject_relation(
        htn, stroke, 'A separate claim.', relation_type_id=risk)

    assert 'adopted_proposal' not in written
    assert written['origin'] == 'user'


def test_an_ordinary_create_carries_no_adoption_keys(user_db, exam):
    """The two synthetic keys are set on one path and nowhere else."""
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    row = user_db.create_subject_relation(htn, stroke, 'Just mine.')

    assert 'adopted_proposal' not in row
    assert 'adopted_from_entry_id' not in row
    assert 'adopted_proposal' not in user_db.get_subject_relation(row['id'])


def test_an_extraction_does_not_adopt_another_extraction(user_db, exam):
    """Only ``origin='user'`` adopts. Two passes are the discard's business.

    An extractor writing over another extractor's unconfirmed row would make
    #382's expiry rule unobservable, and the proposal's own entry would be
    silently rewritten to the newer one.
    """
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    _extracted(user_db, exam, htn, stroke)

    with pytest.raises(ValidationError, match='already related'):
        user_db.create_subject_relation(
            htn, stroke, 'From another pass.', origin='extracted',
            source_entry_id=_entry(user_db, exam, order=2),
            relation_type_id=_type_id(user_db, exam, 'causes'))


# ==================== discarding on re-extraction (#382) ====================

def test_discarding_removes_only_this_entrys_unconfirmed_extractions(
        user_db, exam):
    """Three predicates, and dropping any one loses the student's work."""
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    neph = _node(user_db, 'Nephrosclerosis')
    mine = _node(user_db, 'Something else')
    entry = _entry(user_db, exam)
    other_entry = _entry(user_db, exam, order=2)
    causes = _type_id(user_db, exam, 'causes')

    doomed = user_db.create_subject_relation(
        htn, stroke, 'Unconfirmed, this entry.', origin='extracted',
        source_entry_id=entry, relation_type_id=causes)
    confirmed = user_db.create_subject_relation(
        htn, neph, 'Confirmed extraction.', origin='extracted',
        source_entry_id=entry, relation_type_id=causes)
    user_db.confirm_subject_relation(confirmed['id'])
    elsewhere = user_db.create_subject_relation(
        stroke, neph, 'Unconfirmed, another entry.', origin='extracted',
        source_entry_id=other_entry, relation_type_id=causes)
    by_hand = user_db.create_subject_relation(
        htn, mine, 'Written by hand, naming the entry.',
        source_entry_id=entry, relation_type_id=causes)

    assert user_db.discard_unconfirmed_proposals_for_entry(entry) == 1

    assert user_db.get_subject_relation(doomed['id']) is None
    assert user_db.get_subject_relation(confirmed['id']) is not None, \
        'a confirmed extraction is the student\'s relation'
    assert user_db.get_subject_relation(elsewhere['id']) is not None, \
        'another entry\'s proposals are not this run\'s business'
    assert user_db.get_subject_relation(by_hand['id']) is not None, \
        'origin=user is never a proposal, whatever entry it names'


def test_discarding_leaves_the_rejections_alone(user_db, exam):
    """Otherwise re-running would re-propose what the student rejected."""
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    entry = _entry(user_db, exam)
    causes = _type_id(user_db, exam, 'causes')
    user_db.create_subject_relation(
        htn, stroke, 'A proposal.', origin='extracted',
        source_entry_id=entry, relation_type_id=causes)
    user_db.record_relation_rejection(
        htn, stroke, kind='misread', relation_type_id=causes,
        source_entry_id=entry)

    user_db.discard_unconfirmed_proposals_for_entry(entry)

    assert (htn, stroke, causes) in user_db.rejected_pairs_for_entry(entry)


def test_discarding_nothing_is_not_an_error(user_db, exam):
    assert user_db.discard_unconfirmed_proposals_for_entry(
        _entry(user_db, exam)) == 0


def test_every_relation_write_path_survives_a_real_logger(tmp_path):
    """The guard for a whole class of bug these fixtures cannot see.

    Every other fixture in this suite builds its ``UserDatabase`` with
    ``error_logger=None``, so `if self.error_logger:` is false and **none of
    the log calls on these paths ever execute**. That is not hypothetical
    cover: `confirm_subject_relation` and `record_relation_rejection` both
    shipped `error_logger.log(message, level='INFO')`, and
    ``ErrorLogger.log`` takes ``level`` as its **first positional**
    argument -- so the message bound to ``level`` and then collided with the
    keyword. ``TypeError``, at the moment a student presses Save, under 167
    passing tests.

    It was found by a regression scenario, which runs the real application
    and therefore has a real logger. This is the cheap version of that
    discovery: attach one and call each path once. It asserts nothing about
    what is logged -- `tests/app/test_logger_drains_on_quit.py` owns that --
    only that the calls are callable.

    CLAUDE.md's logging invariant 2 already says omitting the logger
    "silently disables those calls". What it recorded as the cost was *lost
    log lines*; the cost is also *untested code on a write path*.
    """
    from app_logging import ErrorLogger

    logger = ErrorLogger(app_name='RelationWriteTest',
                         log_dir=tmp_path / 'logs', flush_interval=60.0)
    master = MasterDatabase(data_dir=tmp_path / 'app_data', error_logger=logger)
    user = master.create_user(username='logged', display_name='L',
                              user_types=['student'])
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username,
                      error_logger=logger)
    try:
        assert db.error_logger is not None, 'the premise of this test'
        exam_id = db.create_exam_context('USMLE').id
        a = _node(db, 'Hypertension')
        b = _node(db, 'Stroke')
        c = _node(db, 'Nephrosclerosis')
        causes = _type_id(db, exam_id, 'causes')
        entry = _entry(db, exam_id)

        # create (user) -- the path that already used .info correctly
        mine = db.create_subject_relation(a, c, 'By hand.', relation_type_id=causes)
        # create (extracted), then confirm -- the first broken call site
        proposal = db.create_subject_relation(
            a, b, 'From an explanation.', origin='extracted',
            source_entry_id=entry, relation_type_id=causes)
        db.confirm_subject_relation(proposal['id'])
        # reject -- the second broken call site
        db.record_relation_rejection(b, c, kind='not_related')
        # adopt -- #382's new path, which logs too. A FOURTH subject, because
        # the pair above is confirmed now and a confirmed relation is rightly
        # refused rather than adopted; my first version of this test used the
        # same pair and was refused by the rule it was meant to exercise.
        d = _node(db, 'Retinopathy')
        db.create_subject_relation(
            a, d, 'From an explanation.', origin='extracted',
            source_entry_id=entry, relation_type_id=causes)
        adopted = db.create_subject_relation(
            a, d, 'Replaced by hand.', relation_type_id=causes)
        assert adopted['adopted_proposal'] is True
        db.delete_subject_relation(mine['id'])
    finally:
        db.close()
        master.close()
        logger.cleanup(wait=False)


def test_the_picker_still_offers_a_partner_held_only_by_a_proposal(
        user_db, exam):
    """Without this, #382's adoption is unreachable from the panel.

    The candidate picker excludes partners already related by the requested
    type, and an unconfirmed extraction used to count -- because the pair
    would have been *refused* at write time, so offering it would have walked
    the student into that refusal. Decision 1 replaced the refusal with an
    adoption, which makes the exclusion the thing preventing the fix.

    Measured before the change: with an unconfirmed ``causes`` proposal in
    place, this returned **no candidates**, so the student saw the partner
    silently missing from the list rather than any explanation at all.
    """
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    causes = _type_id(user_db, exam, 'causes')

    def offered():
        return [r['name'] for r in user_db.search_relatable_subjects(
            htn, 'Nephro', direction='outgoing', relation_type_id=causes)]

    assert offered() == ['Nephrosclerosis'], 'the control: nothing in the way'

    proposal = _extracted(user_db, exam, htn, neph, label='causes')
    assert offered() == ['Nephrosclerosis'], (
        'an unconfirmed proposal must not hide its partner, or the student '
        'cannot write the relation that would adopt it')

    # And the moment it becomes a real relation, it hides the partner again --
    # which is the behaviour the exclusion is actually for.
    user_db.confirm_subject_relation(proposal['id'])
    assert offered() == [], (
        'a confirmed relation of that type must still exclude the partner; '
        'otherwise the picker offers a pair that create_subject_relation '
        'rightly refuses')


# ==================== the two reads extraction runs ====================

def test_the_vocabulary_is_every_active_subject_with_its_aliases(user_db, exam):
    """#380 decision 2: exam-wide, all dimensions, aliases included."""
    htn = _node(user_db, 'Hypertension')
    stroke = _node(user_db, 'Stroke')
    user_db.create_subject_alias(htn, 'USMLE', 'HTN', alias_type='acronym')

    by_id = {row['id']: row for row in user_db.get_extraction_vocabulary('USMLE')}

    assert set(by_id) == {htn, stroke}
    assert by_id[htn]['aliases'] == ['HTN']
    assert by_id[stroke]['aliases'] == [], 'a subject with none gets a list'


def test_an_archived_subject_is_not_in_the_vocabulary(user_db, exam):
    """Its relations are hidden by decision 9, so proposing one writes a row
    nobody can see — the same reason ``_relation_subject_row`` refuses an
    archived endpoint."""
    _node(user_db, 'Hypertension')
    _node(user_db, 'Retired topic', status='archived')

    names = {row['name'] for row in user_db.get_extraction_vocabulary('USMLE')}
    assert names == {'Hypertension'}


def test_another_exams_subjects_are_not_in_the_vocabulary(user_db, exam):
    _node(user_db, 'Hypertension')
    user_db.execute(
        "INSERT INTO subject_nodes (exam_context, name, level_type, parent_id, "
        "sort_order, status) VALUES ('MCAT', 'Hypertension', 'Topic', NULL, 0, "
        "'active')")
    user_db.conn.commit()

    vocabulary = user_db.get_extraction_vocabulary('USMLE')
    assert len(vocabulary) == 1


def test_existing_pairs_include_unconfirmed_extractions(user_db, exam):
    """The load-bearing one, and it looks like a bug if you do not know why.

    m026's UNIQUE is enforced against an unconfirmed row as much as a
    confirmed one, so a proposal for that pair would reach
    ``create_subject_relation`` and be refused — a refusal the student did not
    cause. The filter therefore has to see rows the panel cannot.
    """
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    relation = _extracted(user_db, exam, htn, neph)
    causes = _type_id(user_db, exam, 'causes')

    pairs = user_db.existing_relation_pairs('USMLE')
    assert (htn, neph, causes) in pairs
    assert user_db.get_subject_relations(htn)['relations'] == [], (
        'the same row is simultaneously invisible to the panel; that is the '
        'point of this read existing separately')

    user_db.confirm_subject_relation(relation['id'])
    assert (htn, neph, causes) in user_db.existing_relation_pairs('USMLE')


def test_existing_pairs_is_scoped_to_the_exam(user_db, exam):
    htn = _node(user_db, 'Hypertension')
    neph = _node(user_db, 'Nephrosclerosis')
    _extracted(user_db, exam, htn, neph)

    assert user_db.existing_relation_pairs('USMLE')
    assert user_db.existing_relation_pairs('MCAT') == set()
