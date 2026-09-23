"""Regression: the delete-subject modal tells the truth about what it
will delete, and the promote choice reaches the backend.

Issue #15, decisions 2 and 5.

The modal used to warn with ``node.children.length`` — the *rendered*
children, which come from ``subject_edges`` — while
``_delete_node_recursive`` walked the legacy ``subject_nodes.parent_id``
column, so "this will also delete N child subjects" named a set the
delete did not touch. The shape seeded here is the smallest one where
the two disagree::

        Pdel      Qkeep
           \\      /
          Shared  Exclusive

The old modal says "2 child subjects" for ``Pdel``. The truth is one
deleted (``Exclusive``) and one detached and kept (``Shared``) — or, if
the user ticks "keep direct children", none deleted and ``Exclusive``
moved to the top level.

``tests/database/test_subject_delete_semantics.py`` pins the semantics
and ``tests/app/test_bridge_subject_delete.py`` pins the slot. Neither
can see whether the modal *calls* the preview, re-renders when the
checkbox flips, or passes the flag through on confirm — that chain is
frontend-only, which is what this scenario is for.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_PREVIEW = '[data-testid="tree-delete-modal-preview"]'
_PROMOTE_ROW = '[data-testid="tree-delete-modal-promote-row"]'
_PROMOTE_TOGGLE = '[data-testid="tree-delete-modal-promote-toggle"]'


def _text(page: WimiPage, selector: str) -> str:
    return page.eval_js(
        f"(() => {{ const el = document.querySelector('{selector}'); "
        f"return el ? el.textContent.replace(/\\s+/g, ' ').trim() : ''; }})()"
    )


def _wait_for(page: WimiPage, expression: str, *, what: str, tries: int = 40) -> None:
    for _ in range(tries):
        if page.eval_js(expression):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}: {expression}")


@pytest.mark.slow
@pytest.mark.regression
def test_delete_preview_matches_the_resulting_tree(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name="Issue 15 Delete Preview",
        exam_description="Regression — the modal must not promise the wrong set",
    )
    exam_id = db.get_exam_context_by_name(exam.exam_name).id

    pdel = db.create_subject_node(
        exam_context=exam.exam_name, name="I15 Pdel", level_type="System")
    qkeep = db.create_subject_node(
        exam_context=exam.exam_name, name="I15 Qkeep", level_type="System")
    shared = db.create_subject_node(
        exam_context=exam.exam_name, name="I15 Shared",
        level_type="Topic", parent_id=pdel.id)
    exclusive = db.create_subject_node(
        exam_context=exam.exam_name, name="I15 Exclusive",
        level_type="Topic", parent_id=pdel.id)
    # Second parent edge — this is what makes Shared survive the delete.
    db.add_edge(qkeep.id, shared.id, is_primary=False)

    # ---- Act: open the modal ----------------------------------------
    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    _wait_for(
        wimi_page,
        f'!!document.querySelector(\'[data-testid="tree-node-delete-{pdel.id}"]\')',
        what="the tree to render Pdel",
    )
    wimi_page.eval_js(
        f'document.querySelector(\'[data-testid="tree-node-delete-{pdel.id}"]\').click()'
    )
    _wait_for(
        wimi_page,
        f"(() => document.querySelector('{_PREVIEW}')"
        f".textContent.indexOf('will also') >= 0)()",
        what="the preview to replace its placeholder",
    )

    # ---- Assert: the preview is truthful, not a child count ----------
    delete_text = _text(wimi_page, _PREVIEW)
    for phrase in ("1 other subject will be deleted too", "I15 Exclusive",
                   "1 shared subject will be kept", "I15 Shared"):
        assert phrase in delete_text, (
            f"preview is missing {phrase!r} — it names one deleted child and "
            f"one kept, not a child count. Got: {delete_text!r}"
        )

    assert wimi_page.eval_js(
        f"document.querySelector('{_PROMOTE_ROW}').classList.contains('hidden')"
    ) is False, (
        "the promote choice is hidden even though Pdel has an exclusive "
        "direct child — there is a real decision to offer here"
    )

    # ---- Act: flip the choice ----------------------------------------
    wimi_page.eval_js(
        f"""(() => {{
            const t = document.querySelector('{_PROMOTE_TOGGLE}');
            t.checked = true;
            t.dispatchEvent(new Event('change', {{bubbles: true}}));
        }})()"""
    )
    promote_text = _text(wimi_page, _PREVIEW)
    assert "will be deleted too" not in promote_text, (
        f"preview still threatens to delete a child after the user chose "
        f"to keep them: {promote_text!r}"
    )
    assert "1 subject will move to the top level" in promote_text, promote_text
    assert "I15 Exclusive" in promote_text

    # ---- Act: confirm -------------------------------------------------
    wimi_page.eval_js("document.getElementById('delete-node-confirm').click()")
    _wait_for(
        wimi_page,
        f'!document.querySelector(\'[data-testid="tree-node-{pdel.id}"]\')',
        what="the deleted subject to leave the tree",
    )

    # ---- Assert: the tree matches what the modal promised -------------
    state = wimi_page.eval_js(
        f"""(() => {{
            const exclusive = document.querySelector(
                '[data-testid="tree-node-{exclusive.id}"]');
            return {{
                pdel_present: !!document.querySelector(
                    '[data-testid="tree-node-{pdel.id}"]'),
                exclusive_present: !!exclusive,
                exclusive_is_root: !!exclusive
                    && !exclusive.parentElement.closest('.tree-node-children'),
                shared_under_qkeep: !!document.querySelector(
                    '[data-testid="tree-node-children-{qkeep.id}"] '
                    + '[data-testid="tree-node-{shared.id}"]')
            }};
        }})()"""
    )
    assert state["pdel_present"] is False
    assert state["exclusive_present"] is True, (
        "the promoted child vanished — the flag did not reach the backend"
    )
    assert state["exclusive_is_root"] is True, (
        "the promoted child is not at the top level; a child left holding an "
        "edge from an archived parent renders nowhere at all"
    )
    assert state["shared_under_qkeep"] is True, (
        "the shared child is not under its surviving parent — this is the "
        "orphan issue #15 calls casualty 1"
    )
