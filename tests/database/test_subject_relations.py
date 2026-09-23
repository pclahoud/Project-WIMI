"""Tests for student-authored subject relations — issue #14.

The feature's whole value is the sentence the student writes, so the
tests are organised by the decision each one pins rather than by method:

- decision 2: a relation cannot exist without a reason.
- decision 4: one row, rendered from both ends with the right direction.
- decision 5: subject-wide; the parent context **orders** and never
  filters. The set is identical under every context.
- decision 6: relations cross dimensions and carry none of their own.
- decision 7: a cycle between two subjects is accepted.
- decision 8: the strength grade including the refuted sentinel.
- decision 9: archiving hides the relations and journals them into the
  delete batch, so #37's restore can bring them back.
- decision 11: zero relations is a normal state and returns an empty
  list, not an error.

Plus the two things the issue asks to be built in from the start:
stable ids separate from human labels, and the soft fan-in cap.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from database import MasterDatabase, UserDatabase
from database.domains.relations import (
    FANIN_SOFT_CAP,
    STRENGTH_CERTAIN,
    STRENGTH_LIKELY,
    STRENGTH_POSSIBLE,
    STRENGTH_REFUTED,
)
from database.exceptions import SubjectNodeError, ValidationError


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir):
    db = MasterDatabase(data_dir=temp_dir)
    yield db
    db.close()


@pytest.fixture
def user_db(master_db):
    user = master_db.create_user(
        username="relations_user",
        display_name="Relations User",
        user_types=["student"],
    )
    db = UserDatabase(
        db_path=master_db.ensure_user_database(user.id),
        user_id=user.id,
        username=user.username,
    )
    yield db
    db.close()


# ---------------------------------------------------------------- helpers


def _node(user_db, name: str, *, dimension_id=None) -> int:
    cursor = user_db.execute(
        "INSERT INTO subject_nodes "
        "(exam_context, name, level_type, parent_id, sort_order, status, "
        " dimension_id) "
        "VALUES ('USMLE', ?, 'Topic', NULL, 0, 'active', ?)",
        (name, dimension_id),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _dimension(user_db, name: str) -> int:
    exam = user_db.fetchone(
        "SELECT id FROM exam_contexts WHERE exam_name = 'USMLE'"
    )
    exam_id = exam['id'] if exam else user_db.execute(
        "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, 'USMLE')",
        (user_db.user_id,),
    ).lastrowid
    cursor = user_db.execute(
        "INSERT INTO exam_dimensions (exam_id, name, display_order) "
        "VALUES (?, ?, (SELECT COALESCE(MAX(display_order), 0) + 1 "
        "               FROM exam_dimensions WHERE exam_id = ?))",
        (exam_id, name, exam_id),
    )
    user_db.conn.commit()
    return cursor.lastrowid


def _hypertension_shape(user_db):
    """The issue's worked example.

    Hypertension sits under both Cardiovascular and Pregnancy.
    Eclampsia sits under Pregnancy; RPGN sits under Renal, which is
    neither of hypertension's parents.
    """
    cardio = _node(user_db, "Cardiovascular")
    preg = _node(user_db, "Pregnancy")
    renal = _node(user_db, "Renal")
    htn = _node(user_db, "Hypertension")
    eclampsia = _node(user_db, "Eclampsia")
    rpgn = _node(user_db, "RPGN")
    user_db.add_edge(cardio, htn, is_primary=True)
    user_db.add_edge(preg, htn, is_primary=False)
    user_db.add_edge(preg, eclampsia, is_primary=True)
    user_db.add_edge(renal, rpgn, is_primary=True)
    return cardio, preg, renal, htn, eclampsia, rpgn


def _names(payload):
    return [r['other_subject_name'] for r in payload['relations']]


# ------------------------------------------- decision 2: the reason is mandatory


def test_a_relation_cannot_be_saved_without_a_reason(user_db):
    """The decision that makes this metacognitive rather than a
    bookmarking feature. No "explain later" state exists, so the write
    path refuses rather than parking the relation."""
    a, b = _node(user_db, "A"), _node(user_db, "B")

    for blank in (None, "", "   ", "\n\t "):
        with pytest.raises(ValidationError):
            user_db.create_subject_relation(a, b, blank)

    assert user_db.fetchone(
        "SELECT COUNT(*) AS n FROM subject_relations"
    )['n'] == 0


def test_the_reason_is_stored_verbatim_after_trimming(user_db):
    a, b = _node(user_db, "A"), _node(user_db, "B")
    created = user_db.create_subject_relation(
        a, b, "  Chronic HTN scleroses the afferent arteriole.  "
    )
    assert created['reason'] == "Chronic HTN scleroses the afferent arteriole."


def test_an_absurdly_long_reason_is_refused(user_db):
    a, b = _node(user_db, "A"), _node(user_db, "B")
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(a, b, "x" * 5000)


# ------------------------------ decision 4: one row, rendered from both ends


def test_a_relation_renders_on_both_subjects_with_the_right_direction(user_db):
    htn = _node(user_db, "Hypertension")
    hn = _node(user_db, "Hypertensive Nephrosclerosis")
    user_db.create_subject_relation(htn, hn, "HTN damages the glomerulus.")

    from_side = user_db.get_subject_relations(htn)
    to_side = user_db.get_subject_relations(hn)

    assert len(from_side['relations']) == 1
    assert len(to_side['relations']) == 1

    out = from_side['relations'][0]
    inc = to_side['relations'][0]
    # One row: the same relation seen from each end.
    assert out['relation_id'] == inc['relation_id']
    assert out['direction'] == 'outgoing'
    assert out['other_subject_name'] == 'Hypertensive Nephrosclerosis'
    assert inc['direction'] == 'incoming'
    assert inc['other_subject_name'] == 'Hypertension'
    # The sentence is the payload, and it is the same sentence on both.
    assert out['reason'] == inc['reason'] == "HTN damages the glomerulus."


def test_the_same_ordered_pair_cannot_be_stated_twice(user_db):
    a, b = _node(user_db, "A"), _node(user_db, "B")
    user_db.create_subject_relation(a, b, "First statement.")
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(a, b, "Same thing again.")


# ------------------- decision 5: context orders the panel and filters nothing


def test_context_reorders_and_hides_nothing(user_db):
    """The issue's worked example, and the test that would fail a
    filtering implementation.

    Both relations are true of hypertension. Under Pregnancy, eclampsia
    leads; under Cardiovascular, RPGN leads because eclampsia belongs to
    a *different* context of the same subject. Under neither, both show.
    Every view contains both.
    """
    cardio, preg, _renal, htn, eclampsia, rpgn = _hypertension_shape(user_db)
    user_db.create_subject_relation(
        htn, eclampsia, "Pre-existing HTN raises the risk of eclampsia."
    )
    user_db.create_subject_relation(
        htn, rpgn, "Malignant HTN can present as an RPGN picture."
    )

    no_context = user_db.get_subject_relations(htn)
    under_preg = user_db.get_subject_relations(htn, primary_parent_id=preg)
    under_cardio = user_db.get_subject_relations(htn, primary_parent_id=cardio)

    # Ordering.
    assert _names(under_preg)[0] == 'Eclampsia'
    assert _names(under_cardio)[0] == 'RPGN'

    # And — the half a top-item-only assertion would miss — the *set* is
    # identical in all three views. Hiding a true relation is the
    # expensive error in a mistakes log.
    expected = {'Eclampsia', 'RPGN'}
    assert set(_names(no_context)) == expected
    assert set(_names(under_preg)) == expected
    assert set(_names(under_cardio)) == expected
    assert len(no_context['relations']) == 2


def test_context_rank_explains_the_ordering(user_db):
    """The rank is in the payload so the panel can say *why* something
    leads, and so a regression here is legible rather than an unexplained
    reshuffle."""
    cardio, preg, _renal, htn, eclampsia, rpgn = _hypertension_shape(user_db)
    user_db.create_subject_relation(htn, eclampsia, "Risk factor.")
    user_db.create_subject_relation(htn, rpgn, "Malignant phase.")

    ranks = {
        r['other_subject_name']: r['context_rank']
        for r in user_db.get_subject_relations(
            htn, primary_parent_id=cardio
        )['relations']
    }
    # Eclampsia sits under Pregnancy, another parent of hypertension —
    # demoted, not hidden. RPGN sits under neither, so it is neutral.
    assert ranks['Eclampsia'] > ranks['RPGN']

    ranks_preg = {
        r['other_subject_name']: r['context_rank']
        for r in user_db.get_subject_relations(
            htn, primary_parent_id=preg
        )['relations']
    }
    assert ranks_preg['Eclampsia'] < ranks_preg['RPGN']
    assert ranks_preg['Eclampsia'] == 0


def test_a_single_parent_subject_is_unaffected_by_context(user_db):
    _cardio, _preg, _renal, htn, eclampsia, _rpgn = _hypertension_shape(user_db)
    user_db.create_subject_relation(eclampsia, htn, "Eclampsia is hypertensive.")

    plain = user_db.get_subject_relations(eclampsia)
    assert len(plain['relations']) == 1


# --------------------------------------- decision 6: relations cross dimensions


def test_a_cross_dimension_relation_is_created_and_labelled(user_db):
    """`subject_edges` treats cross-dimensional containment as a
    Non-Goal. Relations are a different table and are not bound by it —
    for a multi-dimensional exam this is the feature's most valuable
    capability."""
    systems = _dimension(user_db, "Systems")
    disciplines = _dimension(user_db, "Disciplines")
    htn = _node(user_db, "Hypertension", dimension_id=systems)
    pharm = _node(user_db, "ACE Inhibitors", dimension_id=disciplines)

    user_db.create_subject_relation(
        htn, pharm, "First-line treatment; I keep missing the cough."
    )

    payload = user_db.get_subject_relations(htn)
    row = payload['relations'][0]
    assert row['crosses_dimension'] is True
    assert row['other_dimension_name'] == 'Disciplines'

    # ...and the relation itself carries no dimension of its own.
    stored = user_db.get_subject_relation(row['relation_id'])
    assert 'dimension_id' not in stored


def test_a_same_dimension_relation_is_not_labelled_as_crossing(user_db):
    systems = _dimension(user_db, "Systems")
    a = _node(user_db, "A", dimension_id=systems)
    b = _node(user_db, "B", dimension_id=systems)
    user_db.create_subject_relation(a, b, "Same dimension.")
    assert user_db.get_subject_relations(a)['relations'][0][
        'crosses_dimension'] is False


def test_no_dimension_at_all_never_claims_a_crossing(user_db):
    """A single-dimension exam must never show a label it cannot
    explain."""
    a, b = _node(user_db, "A"), _node(user_db, "B")
    user_db.create_subject_relation(a, b, "Plain exam.")
    row = user_db.get_subject_relations(a)['relations'][0]
    assert row['crosses_dimension'] is False
    assert row['other_dimension_name'] is None


# ------------------------------------------------ decision 7: cycles are fine


def test_a_cycle_between_two_subjects_is_accepted_and_both_render(user_db):
    """*A causes B* while *B exacerbates A* can both be true. The
    prerequisite-graph lesson, where a cycle is incoherent, does not
    transfer."""
    htn = _node(user_db, "Hypertension")
    ckd = _node(user_db, "Chronic Kidney Disease")

    user_db.create_subject_relation(htn, ckd, "HTN causes CKD.")
    user_db.create_subject_relation(ckd, htn, "CKD worsens HTN.")

    htn_side = user_db.get_subject_relations(htn)
    ckd_side = user_db.get_subject_relations(ckd)

    assert len(htn_side['relations']) == 2
    assert len(ckd_side['relations']) == 2
    assert {r['direction'] for r in htn_side['relations']} == {
        'outgoing', 'incoming'}
    assert {r['direction'] for r in ckd_side['relations']} == {
        'outgoing', 'incoming'}


def test_a_self_loop_is_refused(user_db):
    """Not a cycle between two subjects — a row with no content."""
    a = _node(user_db, "A")
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(a, a, "It relates to itself.")


# ------------------------------------- decision 8: strength and the sentinel


def test_the_refuted_sentinel_is_stored_and_labelled(user_db):
    a, b = _node(user_db, "A"), _node(user_db, "B")
    user_db.create_subject_relation(
        a, b, "Looked this up — the names rhyme, the mechanisms do not.",
        strength=STRENGTH_REFUTED,
    )
    row = user_db.get_subject_relations(a)['relations'][0]
    assert row['strength'] == STRENGTH_REFUTED
    assert row['is_refuted'] is True
    assert 'not related' in row['strength_label'].lower()


def test_refuted_relations_sort_below_real_ones(user_db):
    a = _node(user_db, "A")
    for name, strength in (("Refuted", STRENGTH_REFUTED),
                           ("Possible", STRENGTH_POSSIBLE),
                           ("Certain", STRENGTH_CERTAIN)):
        user_db.create_subject_relation(
            a, _node(user_db, name), f"{name} link.", strength=strength
        )
    assert _names(user_db.get_subject_relations(a)) == [
        'Certain', 'Possible', 'Refuted']


def test_an_unknown_strength_is_refused(user_db):
    a, b = _node(user_db, "A"), _node(user_db, "B")
    with pytest.raises(ValidationError):
        user_db.create_subject_relation(a, b, "Reason.", strength=7)


def test_a_refuted_relation_does_not_count_toward_fan_in(user_db):
    """"Checked — not related" is an annotation about an absence. Letting
    it fill the congestion budget would be backwards."""
    target = _node(user_db, "Target")
    for i in range(FANIN_SOFT_CAP + 1):
        user_db.create_subject_relation(
            _node(user_db, f"Source {i}"), target, "Not actually related.",
            strength=STRENGTH_REFUTED,
        )
    payload = user_db.get_subject_relations(target)
    assert payload['incoming_count'] == 0
    assert payload['fanin_over_cap'] is False


# ------------------------------------------------ the soft fan-in cap


def test_fan_in_reports_over_the_soft_cap_without_refusing_anything(user_db):
    """Math Academy's heuristic: three or four incoming edges is where
    congestion starts. Soft on purpose — a cap that refused would leave a
    true relation unrecorded, which is the more expensive error."""
    target = _node(user_db, "Target")
    for i in range(FANIN_SOFT_CAP):
        user_db.create_subject_relation(
            _node(user_db, f"Source {i}"), target, f"Reason {i}."
        )
    payload = user_db.get_subject_relations(target)
    assert payload['incoming_count'] == FANIN_SOFT_CAP
    assert payload['fanin_over_cap'] is True

    # One more still goes in.
    user_db.create_subject_relation(
        _node(user_db, "One more"), target, "Also true."
    )
    assert user_db.get_subject_relations(target)[
        'incoming_count'] == FANIN_SOFT_CAP + 1


def test_the_picker_reports_fan_in_for_each_candidate(user_db):
    source = _node(user_db, "Source")
    crowded = _node(user_db, "Crowded topic")
    for i in range(FANIN_SOFT_CAP):
        user_db.create_subject_relation(
            _node(user_db, f"Feeder {i}"), crowded, f"Reason {i}."
        )
    results = user_db.search_relatable_subjects(source, "Crowded")
    assert len(results) == 1
    assert results[0]['incoming_count'] == FANIN_SOFT_CAP
    assert results[0]['fanin_over_cap'] is True


# ------------------------------------ decision 9: archive hides and journals


def test_archiving_a_subject_hides_its_relations_and_journals_them(user_db):
    htn = _node(user_db, "Hypertension")
    hn = _node(user_db, "Hypertensive Nephrosclerosis")
    relation = user_db.create_subject_relation(
        htn, hn, "HTN damages the glomerulus."
    )

    result = user_db.delete_subject_subtree(hn)
    batch_id = result['batch_id']

    # Hidden from both ends — a relation pointing at a subject the tree
    # no longer has is worse than none.
    assert user_db.get_subject_relations(htn)['relations'] == []
    assert result['relations_hidden'] == 1

    # ...and stamped with the batch, so restore knows what to undo.
    assert user_db.get_subject_relation(relation['id'])[
        'hidden_batch_id'] == batch_id

    items = user_db.fetchall(
        "SELECT item_type, subject_node_id, parent_id, payload "
        "FROM subject_delete_batch_items "
        "WHERE batch_id = ? AND item_type = 'relation_hidden'",
        (batch_id,),
    )
    assert len(items) == 1
    assert items[0]['subject_node_id'] == htn
    assert items[0]['parent_id'] == hn
    payload = json.loads(items[0]['payload'])
    assert payload['relation_id'] == relation['id']
    assert payload['reason'] == "HTN damages the glomerulus."
    assert payload['archived_endpoints'] == [hn]


def test_restoring_from_the_journal_brings_the_relation_back(user_db):
    """#37 owns the restore UI; what m019 and this delete path owe it is
    a journal complete enough to replay. Replaying it by hand here is
    what proves that."""
    htn = _node(user_db, "Hypertension")
    hn = _node(user_db, "Hypertensive Nephrosclerosis")
    user_db.create_subject_relation(htn, hn, "HTN damages the glomerulus.")

    batch_id = user_db.delete_subject_subtree(hn)['batch_id']
    assert user_db.get_subject_relations(htn)['relations'] == []

    # The two mutations a restore would replay, from the journal alone.
    for item in user_db.fetchall(
        "SELECT payload FROM subject_delete_batch_items "
        "WHERE batch_id = ? AND item_type = 'relation_hidden'",
        (batch_id,),
    ):
        user_db.execute(
            "UPDATE subject_relations SET hidden_batch_id = NULL WHERE id = ?",
            (json.loads(item['payload'])['relation_id'],),
        )
    user_db.execute(
        "UPDATE subject_nodes SET status = 'active', deleted_batch_id = NULL "
        "WHERE deleted_batch_id = ?",
        (batch_id,),
    )
    user_db.conn.commit()

    back = user_db.get_subject_relations(htn)['relations']
    assert len(back) == 1
    assert back[0]['reason'] == "HTN damages the glomerulus."


def test_an_unrelated_delete_leaves_relations_alone(user_db):
    a, b = _node(user_db, "A"), _node(user_db, "B")
    bystander = _node(user_db, "Bystander")
    user_db.create_subject_relation(a, b, "Still true.")

    result = user_db.delete_subject_subtree(bystander)

    assert result['relations_hidden'] == 0
    assert len(user_db.get_subject_relations(a)['relations']) == 1


def test_a_relation_to_an_archived_subject_cannot_be_created(user_db):
    a, gone = _node(user_db, "A"), _node(user_db, "Gone")
    user_db.delete_subject_subtree(gone)
    with pytest.raises(SubjectNodeError):
        user_db.create_subject_relation(a, gone, "Would be invisible anyway.")


# --------------------------------- decision 11: zero relations is normal


def test_zero_relations_returns_an_empty_list_not_an_error(user_db):
    """The normal state for months. The caller renders nothing at all."""
    a = _node(user_db, "A")
    payload = user_db.get_subject_relations(a)
    assert payload['relations'] == []
    assert payload['incoming_count'] == 0
    assert payload['outgoing_count'] == 0
    assert payload['fanin_over_cap'] is False


def test_an_unknown_subject_raises(user_db):
    with pytest.raises(SubjectNodeError):
        user_db.get_subject_relations(999999)


# ------------------------------ stable ids separate from human labels


def test_renaming_a_subject_does_not_orphan_the_relation(user_db):
    """Metacademy's explicit design decision. The panel resolves the
    label at read time, so a rename shows through rather than breaking
    the link."""
    a, b = _node(user_db, "Hypertension"), _node(user_db, "HN")
    user_db.create_subject_relation(a, b, "Causal.")

    user_db.execute(
        "UPDATE subject_nodes SET name = 'Essential hypertension' WHERE id = ?",
        (a,),
    )
    user_db.conn.commit()

    assert user_db.get_subject_relations(b)['relations'][0][
        'other_subject_name'] == 'Essential hypertension'


# ------------------------------------------------ the candidate picker


def test_the_picker_excludes_the_subject_and_partners_in_that_direction(user_db):
    a = _node(user_db, "Alpha")
    b = _node(user_db, "Alpha beta")
    _node(user_db, "Alpha gamma")
    user_db.create_subject_relation(a, b, "Already stated.")

    outgoing = {r['name'] for r in user_db.search_relatable_subjects(
        a, "Alpha", direction='outgoing')}
    assert outgoing == {'Alpha gamma'}


def test_the_picker_still_offers_a_partner_for_the_reverse_direction(user_db):
    """Decision 7 from the authoring side, and the reason the exclusion
    is direction-aware rather than blanket.

    ``A→B`` says nothing about ``B→A``. A picker that hid every existing
    partner would leave *A causes B while B exacerbates A* writable only
    through the database — the cycle would be "allowed" in the schema and
    unreachable in the product.
    """
    a = _node(user_db, "Alpha")
    b = _node(user_db, "Alpha beta")
    user_db.create_subject_relation(a, b, "A leads to B.")

    reverse = {r['name'] for r in user_db.search_relatable_subjects(
        a, "Alpha", direction='incoming')}
    assert 'Alpha beta' in reverse

    # ...and from B's own page, A is still offered as a target.
    from_b = {r['name'] for r in user_db.search_relatable_subjects(
        b, "Alpha", direction='outgoing')}
    assert 'Alpha' in from_b


def test_the_picker_excludes_archived_subjects(user_db):
    a = _node(user_db, "Alpha")
    gone = _node(user_db, "Alpha gone")
    user_db.delete_subject_subtree(gone)
    assert user_db.search_relatable_subjects(a, "Alpha") == []


def test_the_picker_spans_dimensions(user_db):
    """Decision 6 again, from the authoring side: the candidate list must
    not be silently scoped to the subject's own dimension."""
    systems = _dimension(user_db, "Systems")
    disciplines = _dimension(user_db, "Disciplines")
    htn = _node(user_db, "Hypertension", dimension_id=systems)
    _node(user_db, "Hypertension pharmacology", dimension_id=disciplines)

    results = user_db.search_relatable_subjects(htn, "Hypertension")
    assert [r['name'] for r in results] == ['Hypertension pharmacology']
    assert results[0]['crosses_dimension'] is True


# ------------------------------------------------ deletion of a relation


def test_a_relation_can_be_removed(user_db):
    a, b = _node(user_db, "A"), _node(user_db, "B")
    created = user_db.create_subject_relation(a, b, "Mistyped.")

    assert user_db.delete_subject_relation(created['id']) is True
    assert user_db.get_subject_relations(a)['relations'] == []
    assert user_db.delete_subject_relation(created['id']) is False


def test_origin_user_is_confirmed_at_creation(user_db):
    """Writing the reason *is* the confirmation for a user-authored
    relation. #60's extracted ones stay unconfirmed until a human says
    so, which is what ``confirmed_at`` is for."""
    a, b = _node(user_db, "A"), _node(user_db, "B")
    user = user_db.create_subject_relation(a, b, "I wrote this.")
    assert user['origin'] == 'user'
    assert user['confirmed_at'] is not None

    c = _node(user_db, "C")
    extracted = user_db.create_subject_relation(
        a, c, "A model proposed this.", origin='extracted',
        strength=STRENGTH_LIKELY,
    )
    assert extracted['confirmed_at'] is None
