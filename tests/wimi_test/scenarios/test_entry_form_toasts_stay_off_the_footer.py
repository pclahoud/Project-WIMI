"""The entry form's toasts never sit on its footer controls (#932).

Every Save & Next raises a success toast ("Entry Saved / Moving to next
entry..."). The entry form's toasts are fixed to the bottom right, which is
where the sticky footer's Save & Next sits, so for the toast's whole 4 s life
it covered that button: measured on native macOS at 1400x739, the toast
occupied x 1036-1356, y 626-707 and the button 1178-1364, 662-723. A student
pressing Save & Next again inside those 4 s pressed the toast, and nothing
happened -- no save, no move, no message. ``test_review_mode_save_next_
moves_on.py`` failed intermittently on exactly that: its second press landed
on the toast whenever the harness's hit-test ran before the toast slid over.

The fix has two halves and each test here pins one:

* the container is lifted by the footer's measured height
  (``--entry-footer-clearance``, published by ``trackFooterClearance()``), so
  no toast overlaps a footer control at all;
* a toast takes no pointer events except on its close button, so a toast that
  does overlap something can never swallow the press meant for it.

The geometry is checked at the native window size and at 1130x689, the
project's reference viewport, through CDP ``Emulation.setDeviceMetricsOverride``
(the harness cannot size the window). The overlap is sampled across the
toast's slide-in, not only once it has settled, because the slide is where the
original press was lost.

Markers / fixtures: ``@pytest.mark.regression``, ``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.w114_form_ready import poll, wait_for_form_ready

FULL = dict(user_answer="a", correct_answer="b", reflection="<p>R</p>",
            explanation="<p>E</p>")
SAVE_NEXT_READY = (
    "(() => { const b = document.getElementById('btn-save-next');"
    " return !!b && !b.disabled; })()"
)

# Every footer control's rect against every painted toast's rect, plus the
# footer's own top: a toast's bottom edge must sit above the footer.
OVERLAP = """(() => {
  const r = e => { const b = e.getBoundingClientRect();
                   return {l: b.left, t: b.top, r: b.right, b: b.bottom}; };
  const hit = (a, b) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b;
  const footer = document.querySelector('.entry-footer');
  const controls = [...footer.querySelectorAll('button, a, input, select')]
    .filter(e => e.getBoundingClientRect().width > 0)
    .map(e => ({id: e.id || e.textContent.trim(), rect: r(e)}));
  const toasts = [...document.querySelectorAll('.toast-container .toast')]
    .map(e => ({text: e.textContent.trim().slice(0, 40), rect: r(e)}));
  const overlaps = [];
  for (const t of toasts) for (const c of controls)
    if (hit(t.rect, c.rect)) overlaps.push({toast: t.text, control: c.id,
                                            toastRect: t.rect, controlRect: c.rect});
  return JSON.stringify({toasts: toasts.length, controls: controls.length,
                         footerTop: footer.getBoundingClientRect().top,
                         lowestToastBottom: Math.max(-1, ...toasts.map(t => t.rect.b)),
                         overlaps, innerWidth, innerHeight});
})()"""


def _arrange_reviewed_session(wimi_session: WimiTestSession) -> int:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="T932 Exam", exam_description="")
    subj = db.create_subject_node(exam_context=exam.exam_name, name="T932 Cardiology",
                                  level_type="System")
    session = db.create_review_session(
        exam_context_id=exam.id, session_name="T932 session",
        date_encountered=date.today(), total_questions=10, total_incorrect=3)
    for _ in range(3):
        db.create_question_entry(review_session_id=session.id,
                                 primary_subject_ids=[subj.id], **FULL)
    db.conn.commit()
    return session.id


def _press_save_next_and_sample(page: WimiPage) -> list[dict]:
    """Press Save & Next once and sample the geometry through the toast's
    slide-in and after it settles (about 1 s at 50 ms)."""
    assert poll(page, SAVE_NEXT_READY, timeout_ms=10000), "Save & Next never enabled"
    page.locator(testid="entry-form-save-next-button").click()
    assert poll(page, "EntryState.currentEntryIndex === 1", timeout_ms=10000), (
        "arrange: Save & Next did not move to entry 2")
    samples = []
    for _ in range(20):
        samples.append(json.loads(page.eval_js(OVERLAP)))
        page.wait_for_timeout(50)
    return samples


def _assert_clear(samples: list[dict], where: str) -> None:
    shown = [s for s in samples if s["toasts"]]
    assert shown, f"{where}: no toast appeared after Save & Next, so nothing was measured"
    assert all(s["controls"] for s in samples), f"{where}: found no footer controls"
    bad = [s for s in shown if s["overlaps"]]
    assert not bad, (
        f"{where}: a toast overlapped a footer control in {len(bad)} of {len(shown)} "
        f"samples; first: {bad[0]['overlaps'][0]} "
        f"(viewport {bad[0]['innerWidth']}x{bad[0]['innerHeight']})")
    low = [s for s in shown if s["lowestToastBottom"] > s["footerTop"]]
    assert not low, (
        f"{where}: a toast reached below the footer's top edge: bottom "
        f"{low[0]['lowestToastBottom']} > footer top {low[0]['footerTop']}")


@pytest.mark.regression
def test_the_save_and_next_toast_stays_off_the_footer(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    session_id = _arrange_reviewed_session(wimi_session)
    wimi_page.goto("entry-form", query={"session_id": session_id, "mode": "view"})
    wait_for_form_ready(wimi_page)
    _assert_clear(_press_save_next_and_sample(wimi_page), "at the native window size")


@pytest.mark.regression
def test_at_the_reference_viewport_the_toast_stays_off_the_footer(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    session_id = _arrange_reviewed_session(wimi_session)
    emulation = wimi_page.tab._tab.Emulation
    emulation.setDeviceMetricsOverride(width=1130, height=689, deviceScaleFactor=0,
                                       mobile=False)
    try:
        wimi_page.goto("entry-form", query={"session_id": session_id, "mode": "view"})
        wait_for_form_ready(wimi_page)
        size = wimi_page.eval_js("[innerWidth, innerHeight]")
        assert size == [1130, 689], f"the viewport override did not take: {size}"
        _assert_clear(_press_save_next_and_sample(wimi_page), "at 1130x689")
    finally:
        emulation.clearDeviceMetricsOverride()


@pytest.mark.regression
def test_a_press_on_a_toast_reaches_what_is_beneath_except_its_close_button(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The second half on its own: wherever a toast is, it cannot swallow a
    press. Hit-tested at the toast's own centre and at its close button."""
    session_id = _arrange_reviewed_session(wimi_session)
    wimi_page.goto("entry-form", query={"session_id": session_id, "mode": "view"})
    wait_for_form_ready(wimi_page)
    wimi_page.eval_js("Toast.show('info', 'T932 probe', 'a toast to press on', 0)")
    assert poll(wimi_page, "!!document.querySelector('.toast.show')", timeout_ms=5000)
    wimi_page.wait_for_timeout(600)  # let the slide-in finish
    probe = json.loads(wimi_page.eval_js("""(() => {
      const t = [...document.querySelectorAll('.toast')]
        .find(e => e.textContent.includes('T932 probe'));
      const c = t.querySelector('.toast-close');
      const tr = t.getBoundingClientRect(), cr = c.getBoundingClientRect();
      const atBody = document.elementFromPoint(tr.left + 12, tr.top + tr.height / 2);
      const atClose = document.elementFromPoint(cr.left + cr.width / 2, cr.top + cr.height / 2);
      return JSON.stringify({
        bodyHitsToast: !!atBody && t.contains(atBody),
        bodyHit: atBody ? (atBody.id || atBody.className || atBody.tagName) : null,
        closeHitsClose: atClose === c});
    })()"""))
    assert probe["bodyHitsToast"] is False, (
        f"a press on the toast's body landed on the toast ({probe['bodyHit']}); "
        "it would swallow a press meant for whatever is beneath it")
    assert probe["closeHitsClose"] is True, (
        "the toast's close button no longer takes a press, so it cannot be dismissed")
