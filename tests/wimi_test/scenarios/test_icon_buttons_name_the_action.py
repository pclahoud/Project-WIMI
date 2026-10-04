"""#306: an icon-only button is announced as its action, not its glyph.

Why ``title`` is not the fix, measured rather than recited
----------------------------------------------------------
``title`` does **not** override visible content in the accessible-name
computation: contents win and ``title`` is only a last resort. Chromium
reports both as contributing sources, which is what makes this look
already-handled when it is not. At ``c8a904b``::

    .tree-action-btn    name='+'   name_from=['contents', 'attribute']
    #btn-import-help    name='❓'  name_from=['contents', 'attribute']
    #btn-cancel         name='✕'   name_from=['contents', 'attribute']
    .wizard-logo-link   name='📚'  name_from=['contents', 'attribute']

Every one of those carries a ``title``. So the assertion here is that the
name is **not the glyph** -- a test that merely looked for a ``title``
would have been green on all four.

``error-viewer.html`` is the counter-example the issue points at and it is
already right (``aria-label="Clear errors"`` beside ``title="Clear"``), so
it is included below as a **positive control**: if the measurement were
wrong about how names are computed, the error viewer's buttons would fail
too, and the whole file would be suspect rather than just the fix.

Target size
-----------
Same elements, different criterion (WCAG 2.2 SC 2.5.8, AA, 24x24). The
three measured under it were the entry form's chip ``×`` (16x16), the
timer's ``↻`` new-round button (17x16) and the analytics S/M/L size
toggles (22 px tall). The chip's ``×`` is grown for real rather than
padded with a pseudo-element: a 24 px ``::after`` overlay leaves
``getBoundingClientRect`` reporting 16, so the next audit would find the
same number and the student would get a bigger target by accident of
stacking order.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers import a11y
from _helpers import page_gate as pg
from _helpers.w114_form_ready import wait_for_form_ready

MIN_TARGET_PX = 24

#: Glyphs that must never be an accessible name.
GLYPHS = {"+", "\U0001F5D1️", "\U0001F5D1", "❓", "×", "✕",
          "\U0001F4DA", "↻", "⏸", "✖", "⨯"}


def _check_name(page: WimiPage, selector: str, what: str, expect_word: str,
                findings: list[str], *, nth: int = 0) -> None:
    node = a11y.ax_node(page, selector, nth=nth)
    if not node["found"]:
        findings.append(f"{selector} ({what}): not in the DOM")
        return
    name = (node["name"] or "").strip()
    if not name:
        findings.append(f"{selector} ({what}): announced unnamed -- "
                        f"{a11y.describe(node)}")
    elif name in GLYPHS:
        findings.append(
            f"{selector} ({what}): announced as its GLYPH -- "
            f"{a11y.describe(node)}. A `title` does not override visible "
            f"content; use `aria-label`.")
    elif expect_word.lower() not in name.lower():
        findings.append(
            f"{selector} ({what}): named {name!r}, which does not mention "
            f"{expect_word!r} -- the name should say the action")


@pytest.mark.slow
@pytest.mark.regression
def test_the_tree_editors_icon_buttons_say_what_they_do(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W306 Tree", exam_description="")
    root = db.create_subject_node(
        exam_context=exam.exam_name, name="Cardiology", level_type="System")
    db.conn.commit()

    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    pg.wait_for_release(wimi_page)
    for _ in range(60):
        if wimi_page.eval_js(
                "document.querySelectorAll('.tree-action-btn').length >= 2"):
            break
        wimi_page.wait_for_timeout(100)
    else:
        raise AssertionError("the tree never rendered its per-row actions")
    a11y.enable(wimi_page)

    findings: list[str] = []
    _check_name(wimi_page, f'[data-testid="tree-node-add-child-{root.id}"]',
                "the per-row + button", "child", findings)
    _check_name(wimi_page, f'[data-testid="tree-node-delete-{root.id}"]',
                "the per-row wastebasket", "delete", findings)
    _check_name(wimi_page, "#btn-import-help",
                "the import-format help button", "help", findings)

    # The import-help modal's close button, opened so it can be measured
    # at all -- a hidden button reports role='none', ignored=True.
    wimi_page.eval_js("document.getElementById('btn-import-help').click()")
    wimi_page.wait_for_timeout(900)
    _check_name(wimi_page, '[data-testid="tree-import-help-modal-close"]',
                "the import-help modal close", "close", findings)

    assert not findings, (
        "#306: tree-editor icon buttons still announced as glyphs:\n  "
        + "\n  ".join(findings))


@pytest.mark.slow
@pytest.mark.regression
def test_the_entry_forms_chip_and_timer_buttons_are_named_and_large_enough(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W306 Entry", exam_description="")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name="W306 Entry", date_encountered=date.today())
    db.conn.commit()

    wimi_page.goto("entry-form", query={"session_id": session.id})
    wait_for_form_ready(wimi_page)
    a11y.enable(wimi_page)

    # Render a tag chip through the page's OWN render function, so the
    # markup and the computed box are the shipped ones rather than a
    # hand-built imitation.
    rendered = wimi_page.eval_js(
        "(() => { try {"
        "  EntryState.formData.tags = [{id: 4242, name: 'Misread Question',"
        "    color: '#6B7280', description: 'x'}];"
        "  renderTagChips();"
        "  return document.querySelectorAll('.chip-remove').length; }"
        " catch (e) { return String(e); } })()")
    assert rendered == 1, (
        f"could not render a chip through renderTagChips() to measure "
        f"(got {rendered!r})")

    # `.chip` runs a 0.2 s `chipIn` keyframe animating `transform: scale(0.9)`
    # to `scale(1)`, and `getBoundingClientRect` reports the TRANSFORMED box.
    # Measuring on the render tick reads 90% of the real size -- which is why
    # a 24 px button first measured 21.6, and is very likely why the issue
    # reports 16x16 for a control whose rule said `1rem`. Wait for the
    # transform to settle rather than sleeping a guessed interval.
    for _ in range(40):
        if wimi_page.eval_js(
            "(() => { const c = document.querySelector('.chip');"
            " return !!c && getComputedStyle(c).transform === 'none'; })()"
        ):
            break
        wimi_page.wait_for_timeout(50)
    else:
        raise AssertionError(
            "the chip's entry animation never settled, so any size read "
            "here would be a fraction of the real box")

    findings: list[str] = []
    _check_name(wimi_page, ".chip-remove", "a chip's remove button",
                "remove", findings)

    box = a11y.rect(wimi_page, ".chip-remove")
    assert box is not None, "the chip remove button is not laid out"
    if box["w"] < MIN_TARGET_PX or box["h"] < MIN_TARGET_PX:
        findings.append(
            f".chip-remove: {box['w']}x{box['h']} px, under the "
            f"{MIN_TARGET_PX}x{MIN_TARGET_PX} WCAG 2.2 AA target "
            f"(measured 16x16 before the fix)")

    # The timer buttons only exist while a timer is showing.
    shown = wimi_page.eval_js(
        "(() => { const t = document.getElementById('session-timer');"
        "  const n = document.getElementById('btn-new-round');"
        "  if (!t || !n) return false;"
        "  t.style.display = 'flex'; n.style.display = 'inline-block';"
        "  return true; })()")
    assert shown is True, "the session timer controls are not in the DOM"
    wimi_page.wait_for_timeout(200)
    _check_name(wimi_page, "#btn-new-round", "the timer new-round button",
                "round", findings)
    _check_name(wimi_page, "#btn-timer-pause", "the timer pause button",
                "pause", findings)
    for selector in ("#btn-new-round", "#btn-timer-pause"):
        tbox = a11y.rect(wimi_page, selector)
        if tbox and (tbox["w"] < MIN_TARGET_PX or tbox["h"] < MIN_TARGET_PX):
            findings.append(
                f"{selector}: {tbox['w']}x{tbox['h']} px, under the "
                f"{MIN_TARGET_PX}x{MIN_TARGET_PX} target "
                f"(the new-round button measured 17x16 before the fix)")

    assert not findings, (
        "#306 on the entry form:\n  " + "\n  ".join(findings))


@pytest.mark.slow
@pytest.mark.regression
def test_the_wizard_header_and_the_analytics_toggles(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="W306 Misc", exam_description="")
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name="Renal", level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name="W306 Misc", date_encountered=date.today())
    db.create_question_entry(
        review_session_id=session.id, user_answer="A", correct_answer="B",
        question_id="Q0", reflection="<p>r</p>", explanation="<p>e</p>",
        primary_subject_ids=[subject.id])
    db.conn.commit()

    findings: list[str] = []

    # ---- exam wizard --------------------------------------------------
    wimi_page.goto("exam-wizard")
    wimi_page.wait_for_timeout(2000)
    a11y.enable(wimi_page)
    _check_name(wimi_page, "#btn-cancel", "the wizard close cross",
                "cancel", findings)
    _check_name(wimi_page, ".wizard-logo-link", "the wizard home logo",
                "home", findings)
    # Open a Learn More modal so its close button can be measured.
    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"wizard-step1-learn-simple\"]')"
        ".click()")
    wimi_page.wait_for_timeout(900)
    _check_name(wimi_page, "#modal-learn-simple .modal-close",
                "a Learn More modal close", "close", findings)

    # ---- entry browser ------------------------------------------------
    wimi_page.goto("entry-browser")
    pg.wait_for_release(wimi_page)
    wimi_page.wait_for_timeout(600)
    a11y.enable(wimi_page)
    _check_name(wimi_page, "#clearSearch", "the clear-search cross",
                "clear", findings)

    # ---- analytics size toggles --------------------------------------
    wimi_page.goto("analytics")
    wimi_page.wait_for_timeout(4000)
    sizes = wimi_page.eval_js(
        "(() => { const els = document.querySelectorAll('.size-preset-btn');"
        " if (!els.length) return null;"
        " let worst = null;"
        " els.forEach(e => { const r = e.getBoundingClientRect();"
        "   if (!worst || r.height < worst[1]) worst ="
        "     [Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10];"
        " }); return JSON.stringify({n: els.length, worst: worst}); })()")
    assert sizes, "the analytics size toggles did not render"
    import json as _json
    parsed = _json.loads(sizes)
    w, h = parsed["worst"]
    if w < MIN_TARGET_PX or h < MIN_TARGET_PX:
        findings.append(
            f".size-preset-btn: smallest is {w}x{h} px across "
            f"{parsed['n']} buttons, under the {MIN_TARGET_PX}x"
            f"{MIN_TARGET_PX} target (measured 22 px tall before the fix)")

    assert not findings, (
        "#306 on the wizard, entry browser and analytics:\n  "
        + "\n  ".join(findings))


@pytest.mark.slow
@pytest.mark.regression
def test_the_error_viewer_is_still_the_counter_example(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Positive control for the whole file.

    #306 names ``error-viewer.html`` as already correct. If these pass and
    the others fail, the measurement is sound and the fix is missing
    elsewhere; if these fail too, the measurement itself is wrong and
    nothing else in this file should be believed. That distinction is worth
    one short test -- it is the same reason #121 insists on a positive
    control beside an accessibility assertion.
    """
    wimi_page.goto("error-viewer")
    wimi_page.wait_for_timeout(1500)
    a11y.enable(wimi_page)

    findings: list[str] = []
    for nth, (what, word) in enumerate((("statistics", "statistic"),
                                        ("clear", "clear"),
                                        ("export", "export"),
                                        ("minimize", "minimi"))):
        _check_name(wimi_page, ".viewer-controls button",
                    f"the error viewer's {what} button", word, findings,
                    nth=nth)

    assert not findings, (
        "the error viewer's buttons were supposed to be the already-correct "
        "counter-example, so this failing means the NAME MEASUREMENT is "
        "wrong rather than the app:\n  " + "\n  ".join(findings))
