"""#304: the Exam Overview's weight rows are real controls.

What was wrong
--------------
The overview's donut legend rendered eleven rows as::

    <div class="pie-legend-item" onclick="selectNode(id)">

Measured on ``master`` at ``d7790b1`` with the page gate released: **11
clickable rows, 0 tabbable**, no role, no ``tabindex``; the accessibility
tree exposed each one as two ``StaticText`` nodes and nothing interactive,
while the donut arc beside it *was* exposed as ``graphics-symbol``. The
whole Exam Overview state -- the panel's state on page load -- contained
**zero tabbable elements**, so the only handle on the chart was mouse-only.

#304's tree-row half was fixed in ``2042790``; this is the legend half,
reached through #346 replacing the chart the legend belonged to. The
remaining half is ``.child-item`` in the node-details state, which is a
different list and keeps #304 open.

Why these assertions
--------------------
``el.click()`` succeeds against exactly the markup this is about, so reach
is a real ``Input.dispatchKeyEvent`` Tab walk and activation is a real
Enter and a real Space. Both are asserted by **consequence** -- the subject
selected and named in the details panel -- never by a handler firing.

The accessible name is checked through the AX tree rather than through
``aria-label``, because the attribute is precisely what stays correct when
the node is not exposed at all.
"""

from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers import a11y
from _helpers.tree_details import open_tree_editor


def _return_to_overview(page: WimiPage) -> None:
    page.eval_js("returnToExamOverview()")
    for _ in range(40):
        if page.eval_js("!!document.querySelector('.weight-range-row')"):
            return
        page.wait_for_timeout(100)
    raise AssertionError("the overview never came back")


@pytest.mark.slow
@pytest.mark.regression
def test_an_overview_weight_row_is_reachable_and_activatable_by_keyboard(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ------------------------------------------------------
    #
    # Two roots, not the eleven of the Step 1 fixture: every tree row is
    # three tab stops of its own, so eleven roots put ~40 presses between
    # the toolbar and the panel and say nothing extra about the rows here.
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W304 Overview",
                                  exam_description="")
    first = db.create_subject_node(
        exam_context=exam.exam_name, name="Blood & Lymphoreticular/Immune Systems",
        level_type="System", exam_weight_low=7.0, exam_weight_high=11.0,
        sort_order=1).id
    second = db.create_subject_node(
        exam_context=exam.exam_name, name="Cardiovascular System",
        level_type="System", exam_weight_low=9.0, exam_weight_high=13.0,
        sort_order=2).id
    open_tree_editor(wimi_page, exam.id)

    rows = wimi_page.eval_js(
        "document.querySelectorAll('.weight-range-row').length")
    assert rows == 2, f"arrange is void: {rows} rows rendered, expected 2"

    # ---- Assert 1: the panel has a tab stop at all --------------------
    #
    # The pre-fix measurement, kept because it is the whole finding: on the
    # demo profile the overview exposed 0 tabbable elements against 11
    # clickable legend rows.
    tabbable = wimi_page.eval_js(
        "[...document.querySelectorAll('.exam-overview *')]"
        ".filter(e => e.tabIndex >= 0 && e.checkVisibility()).length")
    assert tabbable >= rows, (
        f"#304: the Exam Overview exposes {tabbable} tabbable elements for "
        f"{rows} rows that select a subject when clicked. A row a pointer can "
        f"press and a keyboard cannot reach is not a control.")

    # ---- Assert 2: a real Tab walk lands on a row ---------------------
    a11y.start_tab_walk(wimi_page)
    stop = a11y.walk_to(
        wimi_page,
        lambda s: s.get("testid") == f"overview-weight-row-{first}",
        presses=40)
    if stop is None:
        a11y.start_tab_walk(wimi_page)
        order = a11y.summarise(a11y.tab_walk(wimi_page, presses=40))
        raise AssertionError(
            f"#304: no Tab press reached the first weight row. The tab order "
            f"was: {order}. Note `el.click()` on the old <div> would still "
            f"have worked, which is why this is measured with real Tabs.")

    # A focus stop nobody can see is half a route. #304's own report lists
    # five focusable-but-unindicated targets beside the unreachable ones, so
    # the ring is checked here rather than assumed from #355's app-wide rule.
    assert a11y.has_focus_ring(stop), (
        f"the row takes focus with no visible indicator: {stop!r}")

    # ---- Assert 3: the name assistive tech gets is the subject AND band
    a11y.enable(wimi_page)
    node = a11y.ax_node(wimi_page, f'[data-testid="overview-weight-row-{first}"]')
    assert node["role"] == "button", (
        f"#304: the row is not exposed as an activatable control: "
        f"{a11y.describe(node)}. The legend measured as plain StaticText.")
    assert "Blood & Lymphoreticular/Immune Systems" in node["name"], (
        f"#304: the row does not announce its subject: {a11y.describe(node)}")
    assert "7–11%" in node["name"], (
        f"#304: the row announces no weight, so the chart's one accessible "
        f"reading is the subject alone: {a11y.describe(node)}")

    # ---- Assert 4: Enter selects it (by consequence) ------------------
    assert wimi_page.eval_js("TreeState.selectedNodeId") != first, (
        "arrange is void: the row's subject is already selected")
    holding = a11y.active_element(wimi_page)
    assert holding.get("testid") == f"overview-weight-row-{first}", (
        f"the probe lost the row before pressing Enter (focus is on "
        f"{holding.get('testid') or holding['tag']})")
    a11y.real_key(wimi_page, "Enter", settle_ms=800)
    assert wimi_page.eval_js("TreeState.selectedNodeId") == first, (
        "#304: Enter on the focused weight row did not select the subject")
    assert wimi_page.eval_js(
        "(() => { const p = document.querySelector('.details-panel');"
        " return (p.innerText || '').includes('Blood & Lymphoreticular'); })()"
    ) is True, (
        "#304: Enter reported a selection but the details panel does not name "
        "the subject, so nothing the student can see happened.")

    # ---- Assert 5: Space does it too ----------------------------------
    #
    # A native <button> gets Space for free and a role="button" div does not,
    # so this is the assertion that distinguishes the two implementations.
    _return_to_overview(wimi_page)
    a11y.start_tab_walk(wimi_page)
    stop = a11y.walk_to(
        wimi_page,
        lambda s: s.get("testid") == f"overview-weight-row-{second}",
        presses=40)
    assert stop is not None, "the second row is not in the tab order"
    a11y.real_key(wimi_page, " ", settle_ms=800)
    assert wimi_page.eval_js("TreeState.selectedNodeId") == second, (
        "#304: Space on the focused weight row did not select the subject. "
        "Enter alone is half a keyboard route -- Space is what a screen "
        "reader user presses on something announced as a button.")


@pytest.mark.slow
@pytest.mark.regression
def test_a_quote_in_a_subject_name_does_not_break_the_accessible_name(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The row's name is an attribute, so it needs `escapeAttr`.

    `escapeHtml` round-trips through ``textContent`` -> ``innerHTML``, which
    escapes ``&``, ``<`` and ``>`` and leaves ``"`` alone -- right for text
    content, and inside a double-quoted attribute it ends the attribute
    early and the rest of the name is parsed as markup. The row renders both
    forms of the same name, so only the attribute half can be wrong, and the
    visible text would look perfectly correct while the announced name was
    truncated to `Cardio `.
    """
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W304 Quotes", exam_description="")
    node = db.create_subject_node(
        exam_context=exam.exam_name, name='Cardio "fast" track & <b>more</b>',
        level_type="System", exam_weight_low=7.0, exam_weight_high=11.0).id
    open_tree_editor(wimi_page, exam.id)

    a11y.enable(wimi_page)
    ax = a11y.ax_node(wimi_page, f'[data-testid="overview-weight-row-{node}"]')
    assert ax["name"] == 'Cardio "fast" track & <b>more</b>, 7–11% of the exam', (
        f"the announced name is {ax['name']!r}")
    # The visible half is the control: it is correct either way, which is why
    # a test reading only the text would pass against the broken attribute.
    assert wimi_page.eval_js(
        "document.querySelector('.weight-range-name').textContent"
    ) == 'Cardio "fast" track & <b>more</b>'
