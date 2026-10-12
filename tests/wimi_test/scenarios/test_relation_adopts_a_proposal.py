"""Regression: writing a relation by hand confirms a proposal instead of being
refused by it (#60, #382).

Owner's decision, 2026-10-05. Extraction writes its proposals into
`subject_relations` as `origin='extracted'` with `confirmed_at` NULL, and
`UNCONFIRMED_IS_HIDDEN` keeps them off this very panel until the student
endorses one. So a student who never looked at them, and who then links the
same two subjects by hand, used to be **refused** — *"Edit or remove it rather
than stating it twice"*, naming a row that is not in the panel. #174 broken by
a message rather than by a button.

Now the save confirms that row with the student's own sentence. #14's decision
2 says writing the reason *is* the confirmation, so they have already done
what confirming requires.

Why this needs a browser
------------------------
The database half is covered in `tests/database/test_relation_confirmation.py`.
What only a real page can show is that the student **gets their relation and
is told what happened**: one row on the panel, their words in it, and a note
saying WIMI had already suggested it. A version that saved correctly and said
nothing would pass every unit test and still leave the student thinking they
created something they did not.

The proposal is seeded directly rather than extracted, deliberately: this
scenario is about the collision, and running a real model here would make it
depend on 845 MB of weights and on #364's packaging.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

REASON = 'High pressure scars the small vessels in the kidney over years.'


def _seed(db) -> tuple[int, int, int, int, int]:
    """Two topics, an entry, and an UNCONFIRMED extracted relation between them.

    Returns ``(exam_context_id, htn, hn, relation_id, type_id)``.

    **The proposal carries a type, and the scenario then selects that same
    type in the modal.** m026's UNIQUE is per ``(from, to,
    relation_type_id)``, so an untyped proposal does not collide with a typed
    manual relation at all -- the first version of this seeded an untyped one
    and correctly got two separate relations and no adoption.
    """
    exam = db.create_exam_context(
        exam_name='Adoption Exam',
        exam_description='#382 — a hand-written relation adopts a proposal',
    )
    htn = db.create_subject_node(
        exam_context=exam.exam_name, name='AD Hypertension', level_type='Topic',
    )
    hn = db.create_subject_node(
        exam_context=exam.exam_name, name='AD Hypertensive Nephrosclerosis',
        level_type='Topic',
    )
    session = db.execute(
        "INSERT INTO review_sessions (user_id, exam_context_id, "
        "total_questions, total_incorrect) VALUES (1, ?, 1, 1)",
        (exam.id,)).lastrowid
    entry = db.execute(
        "INSERT INTO question_entries (review_session_id, entry_order, "
        "user_answer, correct_answer, explanation) "
        "VALUES (?, 1, 'a', 'b', '<p>Chronic hypertension causes it.</p>')",
        (session,)).lastrowid
    db.conn.commit()

    causes = next(t for t in db.get_relation_types(exam.id)
                  if t['label'] == 'causes')
    proposal = db.create_subject_relation(
        htn.id, hn.id, 'Chronic hypertension causes it.',
        origin='extracted', source_entry_id=entry,
        relation_type_id=causes['id'],
    )
    db.conn.commit()
    return exam.id, htn.id, hn.id, proposal['id'], causes['id']


def _wait_for(page: WimiPage, expression: str, *, tries: int = 100) -> object:
    value = None
    for _ in range(tries):
        value = page.eval_js(expression)
        if value:
            return value
        page.wait_for_timeout(100)
    return value


@pytest.mark.slow
@pytest.mark.regression
def test_writing_the_relation_by_hand_confirms_the_hidden_proposal(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    exam_id, subject_id, other_id, proposal_id, type_id = _seed(db)

    wimi_page.goto('subject-deep-dive', query={'subject': subject_id,
                                               'exam': exam_id})

    # The proposal is invisible: the panel renders the bare "link a related
    # topic" action, not a card. If this ever fails, UNCONFIRMED_IS_HIDDEN has
    # stopped working and the rest of the scenario is about nothing.
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-add\"]')",
    ), 'the add action never rendered'
    assert not wimi_page.eval_js(
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')"
    ), ('an unconfirmed extraction reached the panel; it must be hidden until '
        'the student confirms it (#5494)')

    # Link the same two subjects by hand.
    wimi_page.locator(testid='deep-dive-relations-add').click()
    assert _wait_for(
        wimi_page, "!!document.querySelector('[data-testid=\"relation-modal\"]')"
    ), 'the authoring modal never opened'

    # Choose the same type the proposal carries. Without this the modal's
    # default option decides what collides, which would make the scenario
    # depend on m026's seed ordering rather than on the behaviour.
    wimi_page.eval_js(
        "(() => { const s = document.querySelector("
        "'[data-testid=\"relation-direction\"]');"
        f" s.value = '{type_id}|outgoing';"
        " s.dispatchEvent(new Event('change', {bubbles: true}));"
        " return s.value; })()")

    wimi_page.locator(testid='relation-search').fill('Nephro')
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid^=\"relation-result-\"]')",
    ), 'the candidate never appeared'
    wimi_page.eval_js(
        "document.querySelector('[data-testid^=\"relation-result-\"]').click()")
    assert _wait_for(
        wimi_page,
        "(() => { const el = document.querySelector("
        "'[data-testid=\"relation-chosen\"]'); return el && !el.hidden; })()",
    ), 'the chosen subject never showed'

    wimi_page.locator(testid='relation-reason').fill(REASON)
    assert _wait_for(
        wimi_page,
        "!document.querySelector('[data-testid=\"relation-save\"]').disabled",
    ), 'Save stayed disabled with a reason written'
    wimi_page.locator(testid='relation-save').click()

    # The panel now carries exactly one relation -- the adopted row, not a
    # second one -- and says what happened.
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')",
    ), 'the relations panel never appeared after saving'
    note = _wait_for(
        wimi_page,
        "(() => { const el = document.querySelector("
        "'[data-testid=\"deep-dive-relations-adopted-note\"]');"
        " return el ? el.textContent : ''; })()",
    )
    assert note and 'already suggested' in note, (
        'the student pressed Save and what happened was a confirmation of a '
        'row they had never seen. Saving quietly would leave them thinking '
        'they created something they did not')

    rows = db.fetchall(
        "SELECT id, reason, origin, confirmed_at, source_entry_id "
        "FROM subject_relations WHERE from_subject_id = ? AND to_subject_id = ?",
        (subject_id, other_id),
    )
    assert len(rows) == 1, f'expected one relation, found {len(rows)}'
    row = rows[0]
    assert row['id'] == proposal_id, 'the proposal was adopted, not replaced'
    assert row['reason'] == REASON, "the student's words, not the passage"
    assert row['confirmed_at'] is not None
    # Provenance kept: the entry is where the pair was first noticed, which is
    # a statement about discovery rather than about who wrote the sentence.
    assert row['origin'] == 'extracted'
    assert row['source_entry_id'] is not None
