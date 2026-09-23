"""Regression: the parent context reorders the relations panel and
hides nothing.

Forgejo issue #14, decision 5 (owner, 2026-09-14):

    Relations are subject-wide, never scoped to a parent context — but
    the panel emphasises by context. Both *hypertension → eclampsia* and
    *hypertension → RPGN* are true of hypertension. What differs is
    relevance: viewing hypertension under Pregnancy should surface
    eclampsia first, under Cardiovascular should surface RPGN first, and
    with no context selected should show both. **Ordering, not
    filtering.** Hiding a true relation is the expensive error in a
    mistakes log, and it would contradict the deep dive's existing
    deliberate divergence from strict §5.4.

The shape below is the issue's own worked example. The assertions come
in pairs on purpose: the leading row *and* the full set, in each of the
three views. A test that only checked the top item would pass an
implementation that filtered — which is exactly the mistake the decision
was written to prevent, and the one the existing multi-parent selector
(which genuinely does narrow the entry rollups beside this panel) makes
easy to fall into.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _seed(db):
    """Hypertension under Cardiovascular *and* Pregnancy.

    Eclampsia lives under Pregnancy; RPGN lives under Renal, which is
    neither of hypertension's parents.
    """
    exam = db.create_exam_context(
        exam_name='Relation Context Exam',
        exam_description='issue #14 — context orders, never filters',
    )
    cardio = db.create_subject_node(
        exam_context=exam.exam_name, name='CO Cardiovascular',
        level_type='System',
    )
    preg = db.create_subject_node(
        exam_context=exam.exam_name, name='CO Pregnancy', level_type='System',
    )
    renal = db.create_subject_node(
        exam_context=exam.exam_name, name='CO Renal', level_type='System',
    )
    htn = db.create_subject_node(
        exam_context=exam.exam_name, name='CO Hypertension',
        level_type='Topic', parent_id=cardio.id,
    )
    db.add_edge(preg.id, htn.id, is_primary=False)
    eclampsia = db.create_subject_node(
        exam_context=exam.exam_name, name='CO Eclampsia', level_type='Topic',
        parent_id=preg.id,
    )
    rpgn = db.create_subject_node(
        exam_context=exam.exam_name, name='CO RPGN', level_type='Topic',
        parent_id=renal.id,
    )
    db.create_subject_relation(
        htn.id, eclampsia.id, 'Pre-existing HTN raises the risk of eclampsia.')
    db.create_subject_relation(
        htn.id, rpgn.id, 'Malignant hypertension can present as an RPGN picture.')
    db.conn.commit()
    return exam.id, htn.id, cardio.id, preg.id


def _wait_for(page: WimiPage, expression: str, *, tries: int = 100) -> object:
    value = None
    for _ in range(tries):
        value = page.eval_js(expression)
        if value:
            return value
        page.wait_for_timeout(100)
    return value


_NAMES_JS = """
    (() => Array.from(document.querySelectorAll(
        '[data-testid="deep-dive-relations-list"] .relation-subject'
    )).map(el => el.textContent.trim()))()
"""


def _names_after(page: WimiPage, expected_first: str) -> list:
    """Poll until the list settles, then return it.

    The panel refetches asynchronously on a context change, so reading
    once straight after dispatching ``change`` can catch the previous
    render.
    """
    for _ in range(100):
        names = page.eval_js(_NAMES_JS)
        if names and names[0] == expected_first:
            return names
        page.wait_for_timeout(100)
    return page.eval_js(_NAMES_JS)


@pytest.mark.slow
@pytest.mark.regression
def test_context_reorders_the_panel_and_hides_nothing(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    exam_id, htn_id, cardio_id, preg_id = _seed(wimi_session.user.db)
    wimi_page.goto('subject-deep-dive', query={'subject': htn_id, 'exam': exam_id})
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"deep-dive-relations-panel\"]')",
    ), 'The Related Topics panel never rendered'
    assert _wait_for(
        wimi_page,
        "!!document.querySelector('[data-testid=\"multi-parent-selector-control\"]')",
    ), 'The multi-parent selector never rendered'

    both = {'CO Eclampsia', 'CO RPGN'}

    # ---- Assert: no context — both, in either order --------------------
    assert set(wimi_page.eval_js(_NAMES_JS)) == both, (
        'With no parent context selected the panel must show every '
        'relation on the subject.'
    )

    # ---- Act + assert: under Pregnancy ---------------------------------
    _select_parent(wimi_page, preg_id)
    under_preg = _names_after(wimi_page, 'CO Eclampsia')
    assert under_preg[0] == 'CO Eclampsia', (
        f'Under Pregnancy, eclampsia should lead. Got {under_preg!r}.'
    )
    assert set(under_preg) == both, (
        f'Under Pregnancy the panel dropped a relation: {under_preg!r}. '
        f'Decision 5 is ordering, not filtering — RPGN is still true of '
        f'hypertension while you are looking at it under Pregnancy.'
    )

    # ---- Act + assert: under Cardiovascular ----------------------------
    _select_parent(wimi_page, cardio_id)
    under_cardio = _names_after(wimi_page, 'CO RPGN')
    assert under_cardio[0] == 'CO RPGN', (
        f'Under Cardiovascular, RPGN should lead — eclampsia belongs to a '
        f'different parent context of the same subject and is demoted, not '
        f'removed. Got {under_cardio!r}.'
    )
    assert set(under_cardio) == both, (
        f'Under Cardiovascular the panel dropped a relation: {under_cardio!r}.'
    )

    # ---- Act + assert: back to all parents -----------------------------
    _select_parent(wimi_page, None)
    back = _names_after(wimi_page, under_cardio[0])
    assert set(back) == both


def _select_parent(page: WimiPage, parent_id) -> None:
    """Drive the "Show as part of" selector.

    Direct ``.value`` + ``dispatchEvent`` rather than a click: CDP clicks
    on a ``<select>`` do not reliably produce ``change`` (the established
    workaround, see ``test_multi_parent_selector_refilter``).
    """
    value = '' if parent_id is None else str(parent_id)
    ok = page.eval_js(
        f"""
        (() => {{
            const sel = document.querySelector(
                '[data-testid="multi-parent-selector-control"]');
            if (!sel) return false;
            sel.value = {value!r};
            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()
        """
    )
    assert ok, 'Could not dispatch change on the multi-parent selector'
