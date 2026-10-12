"""Regression: the math dialog shows a stored formula exactly (#548 stage 3b).

``rich_editor.js``'s ``_showMathDialog`` put the formula being edited into
``value="..."`` with a local ``.replace(/"/g, '&quot;')`` -- enough to keep
a quote from ending the attribute, so it was never an injection, but it
left ``&`` alone. The parser then decoded any entity-shaped run in the
formula, so ``\\text{AT&amp;T}`` opened in the dialog as ``\\text{AT&T}``
and pressing Update wrote the changed formula back over the student's.
It now goes through ``WimiEscape.attr``, the one escaping definition, and
the stage-3 gate's no-local-escaping rule covers it like everything else.

The formula comes from a ``.math-tex`` element's ``data-formula`` in a
stored reflection, which a session or profile import delivers as-is.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll, seed_empty_session, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FORMULA = r'\text{AT&amp;T} < x "y" &lt;' + " 'z'"


@pytest.mark.slow
@pytest.mark.regression
def test_math_dialog_shows_the_stored_formula_exactly(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    session_id = seed_empty_session(wimi_session.user.db, name='Math')
    wimi_page.goto('entry-form', query={'session_id': session_id})
    wait_for_form_ready(wimi_page)
    assert poll(wimi_page, "typeof katex !== 'undefined'"), 'KaTeX never loaded'

    wimi_page.eval_js(
        f"EntryState.reflectionEditor._showMathDialog({json.dumps(FORMULA)}, null)")
    assert poll(wimi_page, "!!document.querySelector('.rich-editor-math-input')"), (
        'the math dialog never opened')
    shown = wimi_page.eval_js(
        "document.querySelector('.rich-editor-math-input').value")
    wimi_page.eval_js("document.querySelector('.rich-editor-math-cancel').click()")

    assert shown == FORMULA, f'the dialog changed the formula: {shown!r}'
