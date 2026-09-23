"""Regression: archiving a subject hides its relations, and the delete
batch carries them.

Forgejo issue #14, decision 9 (owner, 2026-09-14):

    Archiving a subject hides its relations and journals them into the
    delete batch, so #37's restore brings them back with the subject.
    Consistent with #15.

and the acceptance line:

    Archiving a subject hides its relations; restoring the batch (#37)
    brings them back.

#37 (restore + the Archived panel) does not exist yet, so what is
provable today is the half this issue owns: the relation disappears from
the surviving subject's panel, the journal written by the same delete
batch carries everything a restore would need, and replaying that
journal by hand puts the relation back on screen. If the journal were
incomplete, the replay below would have nothing to work from — which is
the failure #37 would otherwise discover much later.

Hiding is asserted on the *surviving* subject's page, not the archived
one: a relation pointing at a topic the tree no longer has is the
visible defect, and the archived subject's own deep dive is not a page
the student can reach.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

REASON = 'Chronic hypertension scleroses the afferent arteriole.'


def _seed(db):
    exam = db.create_exam_context(
        exam_name='Relation Archive Exam',
        exam_description='issue #14 — archive hides and journals',
    )
    htn = db.create_subject_node(
        exam_context=exam.exam_name, name='AR Hypertension', level_type='Topic',
    )
    hn = db.create_subject_node(
        exam_context=exam.exam_name, name='AR Nephrosclerosis', level_type='Topic',
    )
    db.create_subject_relation(htn.id, hn.id, REASON)
    db.conn.commit()
    return exam.id, htn.id, hn.id


def _wait_for(page: WimiPage, expression: str, *, tries: int = 100) -> object:
    value = None
    for _ in range(tries):
        value = page.eval_js(expression)
        if value:
            return value
        page.wait_for_timeout(100)
    return value


def _reload(page: WimiPage, subject_id: int, exam_id: int) -> None:
    page.eval_js("window.__relationScenarioMark = true")
    page.goto('subject-deep-dive', query={'subject': subject_id, 'exam': exam_id})
    for _ in range(100):
        if not page.eval_js("!!window.__relationScenarioMark"):
            return
        page.wait_for_timeout(100)
    raise AssertionError('The deep dive never reloaded')


@pytest.mark.slow
@pytest.mark.regression
def test_archiving_a_subject_hides_its_relations_and_the_batch_carries_them(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam_id, htn_id, hn_id = _seed(db)

    wimi_page.goto('subject-deep-dive', query={'subject': htn_id, 'exam': exam_id})
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')",
    ), 'The seeded relation did not render before the delete'

    # ---- Act: archive the far end -------------------------------------
    result = db.delete_subject_subtree(hn_id)
    batch_id = result['batch_id']
    assert result['relations_hidden'] == 1, (
        f'The delete did not report hiding the relation: {result!r}'
    )

    # ---- Assert: the panel is gone from the surviving subject ----------
    _reload(wimi_page, htn_id, exam_id)
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-add\"]')",
    ), 'The deep dive did not finish rendering after the delete'
    assert wimi_page.eval_js(
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')"
    ) is False, (
        'The relation is still on the surviving subject after the topic it '
        'points at was archived. It now names a subject the tree does not '
        'have.'
    )

    # ---- Assert: the batch journal carries it --------------------------
    items = db.fetchall(
        "SELECT subject_node_id, parent_id, payload "
        "FROM subject_delete_batch_items "
        "WHERE batch_id = ? AND item_type = 'relation_hidden'",
        (batch_id,),
    )
    assert len(items) == 1, (
        f'The delete batch did not journal the relation: {items!r}. Without '
        f'it, #37 restores the subject and the relation stays hidden forever.'
    )
    payload = json.loads(items[0]['payload'])
    assert items[0]['subject_node_id'] == htn_id
    assert items[0]['parent_id'] == hn_id
    assert payload['reason'] == REASON
    assert payload['archived_endpoints'] == [hn_id]

    # ---- Assert: replaying the journal brings it back ------------------
    # #37 owns the real restore; this is the minimum it will do, driven
    # from the journal alone, to prove the journal is sufficient.
    db.execute(
        "UPDATE subject_relations SET hidden_batch_id = NULL WHERE id = ?",
        (payload['relation_id'],),
    )
    db.execute(
        "UPDATE subject_nodes SET status = 'active', deleted_batch_id = NULL "
        "WHERE deleted_batch_id = ?",
        (batch_id,),
    )
    db.conn.commit()

    _reload(wimi_page, htn_id, exam_id)
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')",
    ), 'Replaying the journal did not bring the relation back'
    assert wimi_page.eval_js(
        "document.querySelector('[data-testid=\"deep-dive-relations-list\"] "
        ".relation-reason').textContent.trim()"
    ) == REASON
