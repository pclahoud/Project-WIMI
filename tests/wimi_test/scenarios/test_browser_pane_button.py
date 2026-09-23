"""Regression: the entry form's "Open question bank" button.

The button toggles the embedded browser pane from the page the student
is actually working on, beside Add Entries.

Two properties, and the second is the one worth a scenario: the button
must follow the pane's state even when the pane was toggled from
somewhere else (the View menu, Ctrl+B, the pane's own close button).
A label that says "Open" over an already-open pane reads as broken.

Markers / fixtures
------------------

* ``@pytest.mark.slow`` -- spawns a real WIMI subprocess.
* ``@pytest.mark.regression`` -- registered in ``pytest.ini``.
* Fixtures: ``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _wait_for(wimi_page: WimiPage, js: str, *, timeout_ms: int = 10000) -> Any:
    elapsed = 0
    last: Any = None
    while elapsed < timeout_ms:
        last = wimi_page.eval_js(js)
        if last:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_question_bank_button_toggles_and_follows_the_pane(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(
        exam_name='Question Bank Button Regression',
        exam_description='Entry-form pane toggle',
    )
    review_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=3,
        total_incorrect=3,
        session_name='Pane button session',
        date_encountered=date.today(),
    )

    wimi_page.goto('entry-form', query={'session_id': review_session.id})

    # Visible at all only when a pane controller is attached.
    assert _wait_for(
        wimi_page,
        "(() => { const b = document.getElementById('btn-question-bank');"
        " return b && !b.hidden ? 'shown' : ''; })()",
    ) == 'shown', 'The question bank button never appeared.'

    assert wimi_page.eval_js(
        "document.getElementById('btn-question-bank').textContent.trim()"
    ) == 'Open question bank'

    # Clicking opens the pane and the label names what the NEXT press does.
    opened = wimi_page.eval_js(
        """
        (async () => {
            document.getElementById('btn-question-bank').click();
            await new Promise(r => setTimeout(r, 1500));
            const status = await window.api.getBrowserPaneStatus();
            return {
                label: document.getElementById('btn-question-bank').textContent.trim(),
                paneOpen: !!(status && status.open),
                tabCount: status && status.tab_count
            };
        })()
        """,
        await_promise=True,
    )
    assert opened.get('paneOpen') is True, f'The pane did not open: {opened!r}'
    # One tab, so the tab bar stays hidden and the pane looks exactly as
    # it did before tabs existed. The bar only earns its vertical space
    # once a second tab exists, which in practice means a site opened a
    # popup or the student pressed +.
    assert opened.get('tabCount') == 1, (
        f'A freshly opened pane should hold exactly one tab: {opened!r}'
    )
    assert opened.get('label') == 'Hide question bank', (
        f'The label must name what pressing it will do next: {opened!r}'
    )

    # Closed from ELSEWHERE (the View menu, Ctrl+B, the pane's own X):
    # the label must stop claiming the pane is open.
    #
    # The pane emits browser:pane_state for this, and that DOES work in
    # the app — Qt's own runJavaScript result callback confirms the
    # script runs and its side effects land. This harness cannot observe
    # it: pychrome's Runtime.evaluate and Qt's runJavaScript are
    # different JavaScript worlds, so a global set by one is invisible to
    # the other. See docs/planning/TEST_INFRASTRUCTURE.md.
    #
    # So the event is NOT what this test exercises. It asserts the focus
    # resync, which is the path that does not depend on injection and is
    # when a stale label would actually be seen.
    followed = wimi_page.eval_js(
        """
        (async () => {
            await window.api.closeBrowserPane();
            window.dispatchEvent(new Event('focus'));
            await new Promise(r => setTimeout(r, 800));
            const st = await window.api.getBrowserPaneStatus();
            return JSON.stringify({
                label: document.getElementById('btn-question-bank').textContent.trim(),
                paneOpen: !!(st && st.open)
            });
        })()
        """,
        await_promise=True,
    )
    import json
    followed = json.loads(followed)
    assert followed['paneOpen'] is False, f'The pane did not close: {followed!r}'
    assert followed['label'] == 'Open question bank', (
        f'The button kept claiming the pane was open after it was closed '
        f'elsewhere: {followed!r}'
    )
