"""#305: every listed form control has a real label, not a placeholder.

The instrument is the point
---------------------------
"Has an accessible name" is **green on the unfixed page** for half of
these, because Chromium falls back to the ``placeholder`` when nothing
better exists: ``#tree-search-input`` measured

    role='textbox'  name='Filter subjects...'  name_from=['placeholder']

at ``c8a904b``. That is precisely the defect #305 describes -- a
placeholder is not announced as the name by every assistive technology and
disappears the moment the user types -- so the assertion has to be about
**where the name came from**, which CDP reports as ``name_from``.
``Accessibility.getPartialAXTree`` gives it per element; nothing readable
from ``aria-*`` attributes can.

The three pre-fix measurements this file is written against, all on Linux
at ``c8a904b``:

    #tree-search-input   name='Filter subjects...'  name_from=['placeholder']
    #time-unit           name=''                    name_from=[]
    #type-simple         name=''                    name_from=[]   (role=radio)

One correction to the issue
---------------------------
#305 says of the two wizard radios that "clicking the text does not select
the radio either". **Measured, it does.** ``setupExamTypeSelection``
attaches a click listener to the whole ``.exam-type-card``, so a click on
the title selects it, and a real ``ArrowRight`` on the focused radio moves
``checked`` *and* the card's ``.selected`` class (because arrow selection
dispatches a click on the radio, which bubbles to the card). Both were
measured before the fix. The real defect is only the missing name -- a
``<label for>`` fixes that and makes the association explicit rather than
JS-mediated, which is worth having either way.

The table also lists **ten** controls under a title saying eleven. Ten is
what is checked here. Two further unnamed controls turned up in the same
sweep and are checked where they belong rather than here: the
search-syntax help icon in ``test_focus_is_visible_where_it_lands.py``
(it is one of #304's five unindicated focus stops) and the entry browser's
clear-search button in ``test_icon_buttons_name_the_action.py`` (it is
named by its glyph, which is #306, not a placeholder).
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers import a11y
from _helpers import page_gate as pg
from _helpers.w114_form_ready import wait_for_form_ready

# (route, selector, what it is). One row per control in #305's table,
# in the issue's own order, plus the two extras noted above.
CONTROLS: list[tuple[str, str, str]] = [
    ("tree-editor", "#tree-search-input", "the subject filter"),
    ("entry-browser", "#searchInput", "the entry search box"),
    ("entry-form", "#time-unit", "the seconds/minutes picker"),
    ("settings", "#primary_color_hex_picker", "the primary colour swatch"),
    ("settings", "#secondary_color_hex_picker", "the secondary colour swatch"),
    ("exam-wizard", "#type-simple", "the Simple Exam radio"),
    ("exam-wizard", "#type-multi", "the Multi-Dimensional Exam radio"),
    ("error-viewer", "#level-filter", "the log level filter"),
    ("error-viewer", "#category-filter", "the log category filter"),
    ("error-viewer", "#search-filter", "the log search box"),
]


def _settle(page: WimiPage, route: str, exam_id: int, session_id: int) -> None:
    """Open ``route`` and wait for whatever that page's readiness is."""
    query = {}
    if route == "tree-editor":
        query = {"exam_id": exam_id}
    elif route == "entry-form":
        query = {"session_id": session_id}
    page.goto(route, query=query or None)
    if route == "entry-form":
        wait_for_form_ready(page)
    elif route in {"tree-editor", "entry-browser", "settings"}:
        pg.wait_for_release(page)
    else:
        page.wait_for_timeout(1200)
    page.wait_for_timeout(600)


@pytest.mark.slow
@pytest.mark.regression
def test_no_listed_control_takes_its_name_from_a_placeholder_or_nothing(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange ------------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W305", exam_description="")
    db.create_subject_node(
        exam_context=exam.exam_name, name="Renal", level_type="System")
    from datetime import date
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name="W305", date_encountered=date.today())
    db.conn.commit()

    # ---- Act ----------------------------------------------------------
    # Every control is measured before anything is asserted, so one run
    # reports every control that is still wrong instead of the first.
    findings: list[str] = []
    checked = 0
    current_route = None
    for route, selector, what in CONTROLS:
        if route != current_route:
            _settle(wimi_page, route, exam.id, session.id)
            a11y.enable(wimi_page)
            current_route = route
        node = a11y.ax_node(wimi_page, selector)
        if not node["found"]:
            findings.append(
                f"{route} {selector} ({what}): not in the DOM, so this row "
                f"of #305's table no longer describes the page")
            continue
        checked += 1
        name = (node["name"] or "").strip()
        if not name:
            findings.append(
                f"{route} {selector} ({what}): announced unnamed -- "
                f"{a11y.describe(node)}")
        elif "placeholder" in node["name_from"]:
            findings.append(
                f"{route} {selector} ({what}): the name comes from the "
                f"PLACEHOLDER -- {a11y.describe(node)}")

    # ---- Assert -------------------------------------------------------
    assert checked == len(CONTROLS), (
        f"only {checked} of {len(CONTROLS)} controls were reachable to "
        f"measure; the unreachable ones are listed below and the result is "
        f"not a verdict on the rest:\n  " + "\n  ".join(findings))
    assert not findings, (
        "#305: controls still announced unnamed or named by their "
        "placeholder:\n  " + "\n  ".join(findings) +
        "\n\nA placeholder is not a label: it is not announced as the name "
        "by every assistive technology and it vanishes as soon as the user "
        "types. Fix with `aria-label`, or a `<label for>` where there is "
        "visible text to associate."
    )


@pytest.mark.slow
@pytest.mark.regression
def test_the_wizard_card_title_is_the_radio_label(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The name comes from the visible title, and pressing it still selects.

    This is the half of #305's wizard row that an ``aria-label`` would
    *not* satisfy. The card's visible ``<h3>`` is what looks like the
    label, so that is what has to be associated -- and associating it must
    not break the pointer path that already worked (measured: it did work
    before the fix, contrary to the issue text).
    """
    wimi_page.goto("exam-wizard")
    wimi_page.wait_for_timeout(2000)
    a11y.enable(wimi_page)

    for selector, expected in (("#type-simple", "Simple Exam"),
                               ("#type-multi", "Multi-Dimensional Exam")):
        node = a11y.ax_node(wimi_page, selector)
        assert node["name"] and expected in node["name"], (
            f"#305: {selector} is not named by its card title: "
            f"{a11y.describe(node)}")
        assert "relatedElement" in node["name_from"], (
            f"#305: {selector}'s name does not come from an associated "
            f"`<label>` ({a11y.describe(node)}). An `aria-label` would "
            f"satisfy the name on its own, but only a real `<label for>` "
            f"makes the visible title press the radio, which is what the "
            f"issue asks for.")

    # The association must not cost the pointer behaviour that worked.
    before = wimi_page.eval_js(
        "document.getElementById('type-multi').checked")
    assert before is False, "arrange is void: the Multi radio is already on"
    # Tab into a radio group lands on the CHECKED radio, i.e. Simple; the
    # arrow then moves to Multi. Landing on Multi first and pressing right
    # would wrap back to Simple and assert nothing.
    landed = a11y.walk_to(
        wimi_page, lambda s: s.get("id") == "type-simple", presses=25)
    assert landed is not None, (
        "#305/#304: the exam-type radios are not reachable by Tab at all")

    # The radio sits in a `.card-radio` wrapper at `opacity: 0`, so Tab
    # lands on a control that cannot be seen and no ring on the radio
    # itself could ever show -- it is transparent with its wrapper. The
    # card has to carry the indicator. Measured here rather than assumed,
    # because `has_focus_ring` on the radio would report `False` whether or
    # not the card is doing its job.
    assert landed["opacity"] == 0, (
        f"the Simple radio is no longer invisible (opacity "
        f"{landed['opacity']}), so the reasoning below no longer applies "
        f"-- re-read it rather than deleting the assertion")
    card_ring = a11y.focus_within_ring(
        wimi_page, '.exam-type-card:has(input[type="radio"]:focus-visible)')
    assert card_ring["found"] and a11y.has_focus_ring(card_ring), (
        f"#305/#304: Tab lands on an invisible radio and the card shows "
        f"nothing ({card_ring}). The control the student can see is the "
        f"card, so the card is what has to carry the focus.")
    a11y.real_key(wimi_page, "ArrowRight", settle_ms=400)
    state = wimi_page.eval_js(
        "(() => JSON.stringify({"
        " multi: document.getElementById('type-multi').checked,"
        " card: document.getElementById('card-multi')"
        "   .classList.contains('selected')}))()")
    assert '"multi":true' in state and '"card":true' in state, (
        f"the keyboard route through the radio group regressed: {state}. "
        f"This worked before the fix (measured) and the label association "
        f"must not take it away.")
