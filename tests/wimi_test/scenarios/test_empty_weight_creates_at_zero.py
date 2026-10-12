"""The weight field's promise, measured in a running WIMI (#447).

The Add Subject modal said **"Leave empty to auto-distribute among siblings"**
and nothing distributed anything. #447 was confirmed by reading the only code
path between the field and the database, and its report says so in as many
words: *"Not reproduced through the UI ... A UI reproduction would be worth
adding to whichever fix lands."* This is it.

The owner's decision (2026-10-07) was option (b) — change the copy, keep
Stage 2's opt-in rebalance — so the help line now says the subject is created
at 0% and points at **Rebalance siblings**. That turns the sentence into a
claim about behaviour, and a claim about behaviour wants a measurement.

What this adds over the source sweep
------------------------------------

``tests/test_tree_editor_weight_help_is_true.py`` reads the files: it proves
the shipped sentence promises nothing false and that ``saveNewNode`` still has
the branch the sentence describes. It cannot prove the sentence *renders*, and
it cannot prove the row that lands is the one the sentence claims. Both are
measured here, in one scenario, which is the point — a help line and a stored
row that agree only in two separate test files agree by coincidence.

The sibling assertion is a before-and-after comparison rather than a check
against the seeded numbers, because what matters is that nothing *moved*.
Reading the seed back would additionally hard-code how
``create_subject_node_with_weight`` splits a weight between ``subject_nodes``
and ``subject_edges`` — it writes the node's ``relative_weight`` and leaves the
edge's NULL — which is not this scenario's subject.

Why there is one case here and not two
--------------------------------------

``saveNewNode`` has two save paths for an empty field, chosen on the parent's
``weight_source``: the absolute one (``createSubjectNode``, where the bridge
defaults both exam bounds to ``0``) and the relative one (``relativeWeight``
becomes ``0``, which is ``!== null``, so ``createSubjectNodeWithWeight`` stores
a zero relative weight explicitly). This scenario was written parametrised over
both and **the second case could not be reached** — measured, then filed as
**#454**: ``getSubjectHierarchy``'s payload is a hand-written key whitelist
that omits ``weight_source`` entirely, so ``parentNode.weight_source`` is
``undefined`` and the relative branch is dead on the plain load path. It is
alive on the dimensioned one, whose nodes come from a ``SELECT *``.

A parametrisation that *looked* like two paths and silently drove one twice
would be worse than this comment, so the second case is not here. The textual
half of it — that neither branch grows a rebalance call — is swept in the unit
guard, which can see both whether or not either runs.
"""
from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _poll(page: WimiPage, expression: str, *, timeout_ms: int = 15_000) -> Any:
    """Poll until truthy, returning the last value rather than raising.

    The caller's own assertion then reports what it found, which is the
    convention the other tree scenarios use (#84).
    """
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        last = page.eval_js(expression)
        if last:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _sibling_weights(db, parent_id: int, child_id: int) -> dict[str, Any]:
    """Both levels: the mirror the chips render from, and the edge."""
    node = db.fetchone(
        'SELECT relative_weight, exam_weight_low, exam_weight_high '
        'FROM subject_nodes WHERE id = ?', (child_id,))
    edge = db.fetchone(
        'SELECT relative_weight, weight_source, is_anchor FROM subject_edges '
        'WHERE child_id = ? AND parent_id = ?', (child_id, parent_id))
    assert node is not None, f'subject {child_id} is missing'
    assert edge is not None, f'the edge {parent_id} -> {child_id} is missing'
    return {'node': dict(node), 'edge': dict(edge)}


@pytest.mark.slow
@pytest.mark.regression
def test_an_empty_weight_creates_the_subject_at_zero(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name='W447 Empty Weight',
        exam_description='#447: an empty weight field distributes nothing',
    )
    parent = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name='W447 Parent',
        level_type='System',
        exam_weight_low=20,
        exam_weight_high=20,
        weight_source='user_defined',
    )
    # 40 + 50 leaves a remainder of 10 under this parent. If anything shared
    # it out, the new subject would take part of that 10 and these two would
    # have to move to pay for it.
    kept_a = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name='W447 Sibling A', level_type='Topic',
        parent_id=parent.id, relative_weight=40, weight_source='user_estimate',
    )
    kept_b = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name='W447 Sibling B', level_type='Topic',
        parent_id=parent.id, relative_weight=50, weight_source='user_estimate',
    )
    before = {
        kept_a.id: _sibling_weights(db, parent.id, kept_a.id),
        kept_b.id: _sibling_weights(db, parent.id, kept_b.id),
    }

    wimi_page.goto('tree-editor', query={'exam_id': exam.id})

    # The modal reads the parent out of TreeState.flatNodes, so the tree has
    # to have loaded before it opens.
    # NOTE: `TreeState` is a top-level `const`, so it is NOT a property of
    # `window`; the bare name resolves from CDP's global scope chain.
    loaded = _poll(
        wimi_page,
        f'(() => typeof TreeState !== "undefined" '
        f'&& TreeState.flatNodes && TreeState.flatNodes.has({parent.id}))()',
    )
    assert loaded, 'the tree editor never loaded the seeded parent'

    opened = wimi_page.eval_js(
        f"""
        (() => {{
            window.addChild({parent.id});
            const modal = document.getElementById('node-modal');
            const name = document.getElementById('modal-node-name');
            const weight = document.getElementById('modal-node-weight');
            const help = document.querySelector(
                '#modal-simple-weight-group .form-help');
            if (!modal || !name || !weight) return null;
            name.value = 'W447 Undecided';
            return {{
                active: modal.classList.contains('active'),
                weight_value: weight.value,
                help: help ? help.textContent.trim() : null,
            }};
        }})()
        """
    )
    assert opened, 'the Add Child modal did not open'
    assert opened['active'], 'the modal is not showing'
    assert opened['weight_value'] == '', (
        f'the weight field is not empty ({opened["weight_value"]!r}); this '
        f'scenario is about what an EMPTY field does')

    # The student-visible half, read off the live DOM rather than off the file.
    help_text = opened['help']
    assert help_text, 'no help line rendered under the weight field'
    assert 'auto-distribute' not in help_text.lower(), (
        f'the shipped modal still promises automatic distribution: '
        f'{help_text!r} (#447)')
    assert '0%' in help_text, (
        f'the help line {help_text!r} does not tell the student what an empty '
        f'field stores, which is the whole of #447')
    assert 'Rebalance siblings' in help_text, (
        f'the help line {help_text!r} no longer points at the one control '
        f'that does share out a remainder')

    wimi_page.eval_js("document.getElementById('node-modal-save').click()")

    created = None
    for _ in range(60):
        created = db.fetchone(
            "SELECT id, relative_weight, exam_weight_low, exam_weight_high "
            "FROM subject_nodes WHERE name = 'W447 Undecided' "
            "AND status = 'active'")
        if created:
            break
        wimi_page.wait_for_timeout(250)
    assert created, 'the subject was never created, so nothing here is measured'

    # What the help line claims: created at 0%, not given a share.
    for column in ('relative_weight', 'exam_weight_low', 'exam_weight_high'):
        value = created[column]
        assert value is None or float(value) == 0.0, (
            f'the new subject was created with {column}={value!r}. An empty '
            f'weight field stores nothing and shares nothing out (#447); a '
            f'non-zero value here means option (a) was built, and the help '
            f'line, the import guide and subject_import.py move with it')

    # And no sibling paid for it, at either level.
    for sibling in (kept_a, kept_b):
        after = _sibling_weights(db, parent.id, sibling.id)
        assert after == before[sibling.id], (
            f'{sibling.name} changed when a subject was added beside it:\n'
            f'  before {before[sibling.id]}\n  after  {after}\n'
            f'Stage 2 removed implicit rebalance on write; creating a subject '
            f'must not rewrite its siblings')
