"""Regression: the details panel is a named region and announces its swaps (#345).

Selecting a subject replaces the whole details panel, and the swap was
silent: ``#details-panel`` carried no role, no name and no live region, nor
did anything inside it, so there was no landmark to jump to and nothing told
a screen reader that 2,000 px of new content had appeared.

The fix keeps focus where the student is (moving it on every Enter in the
tree would throw a keyboard user out of the tree) and announces the change
through a polite ``role="status"`` line inside the panel instead.

Measured through the accessibility tree, not ``aria-*`` attributes: the
attributes are exactly what stays correct when a node has been removed from
the tree. The page is gated, so the gate's release is waited for first --
inside an ``inert`` container every assertion about absence is a tautology
(#121). No screen reader was run; CDP cannot observe speech, so "it is
spoken" rests on the spec, as #127 records.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.a11y import ax_node, enable
from _helpers.tree_details import (
    open_tree_editor, seed_step1_roots, select_subject, wait_for)

ANNOUNCER_TEXT = ("(() => { const e = document.getElementById("
                  "'details-announcer'); return e ? e.textContent : null; })()")


@pytest.mark.slow
@pytest.mark.regression
def test_the_details_panel_is_a_named_region_that_announces_selection(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    seeded = seed_step1_roots(wimi_session.user.db, "W345 Announce")
    open_tree_editor(wimi_page, seeded["exam"].id)
    enable(wimi_page)

    panel = ax_node(wimi_page, "#details-panel")
    assert panel["found"] and not panel["ignored"], (
        f"The details panel is not in the accessibility tree at all: {panel!r}. "
        "The gate should have released; check before reading anything else.")
    assert panel["role"] == "region" and panel["name"] == "Details", (
        f"The details panel is exposed as {panel['role']!r} named "
        f"{panel['name']!r}; a screen-reader user needs a named region to "
        "navigate to (#345).")

    select_subject(wimi_page, seeded["child"])
    status = ax_node(wimi_page, "#details-announcer")
    said = wait_for(
        wimi_page,
        f"(() => {{ const t = {ANNOUNCER_TEXT}; "
        "return t && t.includes('Anemias') ? t : null; })()",
        what="the status line to name the selected subject")

    assert status["found"] and not status["ignored"] and status["role"] == "status", (
        f"The panel's status line is not an exposed status region: {status!r}. "
        "A clipped element stays in the tree; display:none would not.")
    assert said == "Showing details for Anemias", said

    wimi_page.locator(testid="tree-show-overview").click()
    back = wait_for(
        wimi_page,
        f"(() => {{ const t = {ANNOUNCER_TEXT}; "
        "return t && t.includes('overview') ? t : null; })()",
        what="the status line to announce the return to the overview")
    assert back == "Showing the exam overview", back


@pytest.mark.slow
@pytest.mark.regression
def test_the_status_line_does_not_keep_the_page_exposed_behind_a_dialog(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The status line must not sit inside the page container.

    ``modal_dialog.js`` hides what is behind a dialog by writing
    ``aria-hidden`` on each sibling along the dialog's path, and skips any
    sibling that CONTAINS a live region so a toast stays audible. #345's
    status line, first placed inside the details panel, therefore exempted
    the whole page container: measured, ``.tree-page`` carried no
    ``aria-hidden`` behind the delete dialog, against ``"true"`` with the
    line at the top of ``<body>``. The direct attribute is asserted rather
    than an exposed-node count, because test_modal_is_announced_as_a_dialog's
    count fails on master on Windows machine A for an unrelated reason.
    """
    seeded = seed_step1_roots(wimi_session.user.db, "W345 Dialog")
    open_tree_editor(wimi_page, seeded["exam"].id)
    root = seeded["roots"][0]
    wait_for(wimi_page,
             f"!!document.querySelector('[data-testid=\"tree-node-delete-{root}\"]')",
             what="the root's delete button")
    wimi_page.eval_js(
        f"document.querySelector('[data-testid=\"tree-node-delete-{root}\"]').click()")
    hidden = wait_for(
        wimi_page,
        "document.querySelector('[data-page-gated]').getAttribute('aria-hidden')",
        what="the dialog to hide the page container behind it")
    assert hidden == "true", hidden

