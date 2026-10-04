"""#304: the entry-form navigation dots can be reached and pressed by keyboard.

What was wrong
--------------
``question_entry.js`` rendered every dot as::

    <div class="entry-dot ..." onclick="navigateToEntry(i)" title="Entry N">

so moving between the entries of a session was **mouse-only** -- 31 of 31
dots on the 31-entry session the audit measured. Measured here at
``c8a904b``: three ``DIV``s, ``12x12`` px, no ``role``, no ``tabindex``,
accessible name ``''``.

Two defects in one element, and the second is easy to miss
----------------------------------------------------------
A ``<div onclick>`` is unreachable (#304) *and* 12x12 px is half the
24x24 WCAG 2.2 target (#306's criterion, which the issue's own list does
not mention for the dots). Both are fixed by the same change, and neither
is fixed by making the dot bigger: the **button** is 24x24 and transparent,
the coloured 12 px dot stays a ``<span>`` inside it. The visual is
unchanged, which is why the CSS keeps `.entry-dot` as the span's class and
`test_session_progress_overflow.py` -- which counts
``#entry-dots .entry-dot`` -- still counts the same things.

Why ``el.click()`` is not used anywhere here
--------------------------------------------
It would have passed against the unfixed page: a click handler on an
unfocusable div fires perfectly well. Reachability is a real
``Input.dispatchKeyEvent`` Tab walk and activation is a real Enter, with
the assertion on the **entry that got loaded** rather than on the handler.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers import a11y
from _helpers.w114_form_ready import wait_for_form_ready

#: WCAG 2.2 SC 2.5.8 (AA).
MIN_TARGET_PX = 24


@pytest.mark.slow
@pytest.mark.regression
def test_an_entry_dot_is_reachable_pressable_and_big_enough(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    # ---- Arrange ------------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W304 Dots", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=30, total_incorrect=3,
        session_name="W304 Dots", date_encountered=date.today())
    answers = ["FIRST-ANSWER", "SECOND-ANSWER", "THIRD-ANSWER"]
    for i, answer in enumerate(answers):
        db.create_question_entry(
            review_session_id=session.id, user_answer=answer,
            correct_answer=f"CORRECT-{i}", question_id=f"Q{i}",
            reflection=f"<p>R{i}</p>", explanation="<p>E</p>",
        )
    db.conn.commit()

    wimi_page.goto("entry-form", query={"session_id": session.id})
    wait_for_form_ready(wimi_page)
    for _ in range(60):
        if wimi_page.eval_js(
            "document.querySelectorAll('#entry-dots [data-testid^=\"entry-form-nav-dot\"]')"
            ".length === 3"
        ):
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError(
            "the three navigation dots never rendered, so there is nothing "
            "to measure")

    # ---- Assert 1: the target is big enough ---------------------------
    box = a11y.rect(wimi_page, '[data-testid="entry-form-nav-dot-0"]')
    assert box is not None, "dot 0 is not laid out"
    assert box["w"] >= MIN_TARGET_PX and box["h"] >= MIN_TARGET_PX, (
        f"#306: a navigation dot is {box['w']}x{box['h']} px, under the "
        f"{MIN_TARGET_PX}x{MIN_TARGET_PX} WCAG 2.2 AA target size. Measured "
        f"12x12 before the fix. The coloured dot is allowed to stay small -- "
        f"it is the pressable box that has to be 24 px."
    )

    # ---- Assert 2: reachable by Tab, and Enter navigates --------------
    #
    # Activation is tested FIRST, and that ordering is load-bearing. The
    # dots sit early in the tab order, before the form's fields; walking
    # past those fields marks the form dirty (measured: `EntryState.isDirty`
    # goes true during a 40-press walk), and `navigateToEntry` then opens
    # the unsaved-changes modal and awaits it instead of navigating --
    # `currentEntryIndex` is assigned *after* that check. The test would
    # then fail with "Enter did not navigate" while Enter had worked
    # perfectly, which is a diagnosis nobody would get right from the
    # message. So: activate while the form is still clean, assert that it
    # IS clean, and do the read-only assertions afterwards.
    assert wimi_page.eval_js("EntryState.currentEntryIndex") == 0, (
        "arrange is void: the form did not open on the first entry, so "
        "navigating to the third proves nothing")
    a11y.start_tab_walk(wimi_page)
    third = a11y.walk_to(
        wimi_page,
        lambda s: s.get("testid") == "entry-form-nav-dot-2",
        presses=40,
    )
    assert third is not None, (
        "#304: no Tab press landed on the third navigation dot. Note "
        "`el.click()` on a dot would still have worked -- that is exactly "
        "why this uses real keys."
    )
    assert a11y.has_focus_ring(third), (
        f"#304: a dot takes focus with no visible indicator (outline "
        f"{third['outlineStyle']} {third['outlineWidth']})."
    )
    assert wimi_page.eval_js("EntryState.isDirty") is False, (
        "the Tab walk dirtied the form before Enter was pressed, so "
        "`navigateToEntry` will stop at the unsaved-changes modal and the "
        "assertion below would blame the dot. Reach the dot in fewer "
        "presses, or clear the flag deliberately and say so -- do not "
        "weaken the assertion."
    )
    a11y.real_key(wimi_page, "Enter", settle_ms=1500)

    assert wimi_page.eval_js("EntryState.currentEntryIndex") == 2, (
        "#304: Enter on the third dot did not move the form to the third "
        "entry")
    loaded = wimi_page.eval_js(
        "(() => { const t = document.getElementById('user-answer');"
        " return t ? t.value : null; })()")
    assert loaded == "THIRD-ANSWER", (
        f"#304: the form reports entry 3 but is showing {loaded!r}. The "
        f"assertion is on the entry that got loaded rather than on the "
        f"handler, because a handler firing is not navigation."
    )

    # ---- Assert 3: each dot says which entry it is --------------------
    a11y.enable(wimi_page)
    for index in range(3):
        node = a11y.ax_node(
            wimi_page, f'[data-testid="entry-form-nav-dot-{index}"]')
        assert node["role"] == "button", (
            f"#304: dot {index} is not exposed as a control: "
            f"{a11y.describe(node)}")
        assert node["name"] and str(index + 1) in node["name"], (
            f"#304: dot {index} does not name the entry it goes to: "
            f"{a11y.describe(node)}. It measured name='' before the fix, "
            f"because a `title` on a `div` with no role contributes nothing "
            f"a reader can use.")
