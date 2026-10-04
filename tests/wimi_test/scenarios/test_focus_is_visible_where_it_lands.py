"""#304: the five focusable things that took focus invisibly now show it.

The Tab walk in #304's audit found five elements that **accept focus and
draw nothing**: the entry form's two TinyMCE editing iframes, the two
analytics info tooltips, and the entry browser's "? Search Syntax" help
div. Three of them say so in the stylesheet in as many words --
``.sunburst-info-icon:focus``, ``.efficiency-info-icon:focus`` and
``.search-help-icon:focus`` each end with ``outline: none`` -- so the fix
is an outline and this file reads the computed outline.

The iframes need a different rule, and the obvious one can never match
-----------------------------------------------------------------------
Measured here before writing any CSS: focusing TinyMCE's editing iframe
makes it ``document.activeElement``, yet

    f.matches(':focus')          -> false
    f.matches(':focus-visible')  -> false
    .tox-edit-area:focus-within  -> true

Focus is inside the child document, so an ``iframe:focus-visible`` rule is
one that silently never applies -- it would look like a fix, pass review,
and do nothing. The ring therefore hangs off ``:focus-within`` on the
``.tox-edit-area`` wrapper, and that is what is asserted.

Why a real Tab press and not ``el.focus()``
-------------------------------------------
``:focus-visible`` matches on keyboard focus, not on a programmatic
``focus()`` call, so a probe built on ``el.focus()`` can report "no ring"
against a perfectly good ``:focus-visible`` rule *and* report a ring
against none. Everything here lands focus with
``Input.dispatchKeyEvent``.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers import a11y
from _helpers import page_gate as pg
from _helpers.w114_form_ready import wait_for_form_ready


@pytest.mark.slow
@pytest.mark.regression
def test_the_rich_text_editors_show_where_the_caret_went(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W304 Focus", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name="W304 Focus", date_encountered=date.today())
    db.conn.commit()

    wimi_page.goto("entry-form", query={"session_id": session.id})
    wait_for_form_ready(wimi_page)
    for _ in range(60):
        if wimi_page.eval_js(
            "document.querySelectorAll('.tox-edit-area iframe').length >= 2"
        ):
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError(
            "both TinyMCE editors never mounted, so there is nothing to "
            "measure")

    # ---- 1. the editors really are Tab stops -------------------------
    # Measured with real keys, because that is the only thing that shows
    # they are reachable at all.
    landed = a11y.walk_to(
        wimi_page, lambda s: s["tag"] == "IFRAME", presses=45)
    assert landed is not None, (
        "no Tab press reached a TinyMCE editing iframe; the entry form's "
        "two editors are focus stops and the walk should find one")
    assert "tox-edit-area__iframe" in (landed.get("cls") or ""), (
        f"the Tab walk landed on an iframe that is not a TinyMCE editing "
        f"area ({landed.get('cls')!r}), so the stop being measured is not "
        f"the one #304 names")

    # ---- 2. the ring, which has to be driven programmatically ---------
    #
    # This is the one assertion in these files that cannot use a real key,
    # and the reason is measured rather than assumed. In the state a CDP
    # Tab leaves behind, `document.activeElement` IS the iframe and every
    # selector CSS could hang a ring on is false:
    #
    #   :focus / :focus-visible / :focus-within on the iframe   false
    #   .tox-edit-area:focus-within, :has(:focus)               false
    #   body:has(iframe:focus)                                  false
    #
    # After `iframe.focus()` from script, on the same page:
    #
    #   iframe:focus-within        true
    #   .tox-edit-area:focus-within true, outline "solid 2px"
    #
    # So the synthetic key dispatch moves `activeElement` without setting
    # the flags the style engine reads -- a property of driving a frame
    # over CDP, not of the product, since `:focus-within` demonstrably
    # resolves on this very element. The split is deliberate: step 1 proves
    # the stop exists with real keys, step 2 proves the ring resolves. What
    # is NOT verified here is the two together, and no instrument in this
    # repo can do it.
    #
    # Note `iframe:focus` is false even programmatically, which is why the
    # rule is `:focus-within` on the wrapper. An `iframe:focus-visible`
    # rule would read as a fix and never match.
    wimi_page.eval_js(
        "document.querySelector('.tox-edit-area iframe').focus()")
    wimi_page.wait_for_timeout(200)

    ring = a11y.focus_within_ring(wimi_page, ".tox-edit-area:focus-within")
    assert ring["found"], (
        "#304: `iframe.focus()` did not make any `.tox-edit-area` match "
        "`:focus-within`. Either the wrapper class changed or the focus "
        "did not take -- and if THIS fails, the measurement above is what "
        "to re-check, not the CSS.")
    assert a11y.has_focus_ring(ring), (
        f"#304: the focused rich-text editor draws no focus indicator "
        f"(outline {ring['outlineStyle']} {ring['outlineWidth']}). A "
        f"keyboard user tabbing through the entry form cannot tell that the "
        f"caret is now in the reflection editor -- the single most valuable "
        f"field on the page.")


@pytest.mark.slow
@pytest.mark.regression
def test_the_analytics_info_tooltips_show_their_focus(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W304 Analytics",
                                  exam_description="")
    subject = db.create_subject_node_with_weight(
        exam_context=exam.exam_name, name="Cardio", level_type="System",
        exam_weight_low=20, exam_weight_high=30, weight_source="official")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=2,
        session_name="W304 Analytics", date_encountered=date.today())
    for i in range(2):
        db.create_question_entry(
            review_session_id=session.id, user_answer=f"A{i}",
            correct_answer=f"B{i}", question_id=f"Q{i}",
            reflection="<p>r</p>", explanation="<p>e</p>",
            primary_subject_ids=[subject.id])
    db.conn.commit()

    wimi_page.goto("analytics")
    wimi_page.wait_for_timeout(4000)

    findings: list[str] = []
    for selector, what in ((".sunburst-info-icon", "the By Subject tooltip"),
                           (".efficiency-info-icon",
                            "the efficiency-confidence tooltip")):
        present = wimi_page.eval_js(
            f"document.querySelectorAll('{selector}').length")
        if not present:
            findings.append(
                f"{selector} ({what}) did not render, so it was not checked")
            continue
        a11y.start_tab_walk(wimi_page)
        stop = a11y.walk_to(
            wimi_page,
            lambda s, c=selector.lstrip("."): c in (s.get("cls") or ""),
            presses=70)
        if stop is None:
            findings.append(
                f"{selector} ({what}) carries tabindex=0 but no Tab press "
                f"reached it")
            continue
        if not a11y.has_focus_ring(stop):
            findings.append(
                f"{selector} ({what}): focused with outline "
                f"{stop['outlineStyle']} {stop['outlineWidth']} -- its "
                f":focus rule ends in `outline: none`")

    assert not findings, (
        "#304: analytics info tooltips that take focus invisibly:\n  "
        + "\n  ".join(findings))


@pytest.mark.slow
@pytest.mark.regression
def test_the_search_syntax_help_shows_focus_and_says_what_it_is(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The fifth of #304's five -- and it had no accessible name either.

    It is a ``div[tabindex=0]`` whose contents are a ``?`` followed by the
    whole syntax table, so a reader lands on it and is read the table with
    no indication of what it is. An ``aria-label`` gives it a name; the
    tooltip text stays readable as content.
    """
    wimi_page.goto("entry-browser")
    pg.wait_for_release(wimi_page)
    wimi_page.wait_for_timeout(600)
    a11y.enable(wimi_page)

    node = a11y.ax_node(wimi_page, ".search-help-icon")
    assert node["found"], "the search-syntax help icon is not in the DOM"
    assert node["name"] and "search" in node["name"].lower(), (
        f"#304: the search-syntax help icon has no name of its own: "
        f"{a11y.describe(node)}")

    a11y.start_tab_walk(wimi_page)
    stop = a11y.walk_to(
        wimi_page,
        lambda s: "search-help-icon" in (s.get("cls") or ""),
        presses=40)
    assert stop is not None, (
        "the search-syntax help icon carries tabindex=0 but no Tab press "
        "reached it")
    assert a11y.has_focus_ring(stop), (
        f"#304: the search-syntax help icon takes focus with outline "
        f"{stop['outlineStyle']} {stop['outlineWidth']} -- "
        f"`.search-help-icon:focus` sets `outline: none`, so a keyboard "
        f"user cannot see that the tooltip they just opened belongs to the "
        f"thing they are on.")
