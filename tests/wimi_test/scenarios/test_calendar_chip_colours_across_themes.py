"""An exam's chosen colour paints a readable chip on all six themes (#778
Wave 4, decision 9; the gate for that decision).

The chip's fill is the exam colour mixed toward the theme's background by
luminance direction (#322's rule) and its text is black or white by the
fill's luminance. Measured rendered, after each theme is applied and the grid
redrawn, because the mix direction is read off the painted body background at
render time, not at theme time. Three claims per theme: the border is the
exam's own colour, text against fill reaches 4.5:1, and the fill moved toward
the page's background rather than away from it. An exam with no colour keeps
the series-slot tokens and is the control that the inline properties are not
leaking onto every chip.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.contrast import contrast_ratio, parse_css_color, relative_luminance
from _helpers.theme_probe import THEMES
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EXAM_HEX = "#b3261e"       # a saturated red: readable text needs the mix to work

_READY = (
    "(() => { const g = document.querySelector('[data-page-gated]');"
    " return !!g && !g.hasAttribute('inert') && !!window.CalendarState"
    " && window.CalendarState.isLoading === false; })()"
)

READ = """
(() => {
  const pick = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    return {bg: cs.backgroundColor, text: cs.color, border: cs.borderLeftColor,
            coloured: el.getAttribute('data-coloured'), series: el.getAttribute('data-series')};
  };
  return JSON.stringify({
    body: getComputedStyle(document.body).backgroundColor,
    coloured: pick('#cal-grid .cal-event[data-coloured="exam"]'),
    plain: pick('#cal-grid .cal-event:not([data-coloured])'),
    marker: document.querySelector('.cal-grid [data-coloured="exam"]') !== null,
  });
})()
"""


def _wait(page: WimiPage, expr: str, *, what: str, tries: int = 300) -> None:
    for _ in range(tries):
        if page.eval_js(expr):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def _hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


@pytest.mark.slow
@pytest.mark.regression
def test_a_chosen_colour_is_readable_and_mixes_toward_the_background_on_every_theme(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    coloured = db.create_exam_context(exam_name="Coloured Exam")
    db.update_exam_context_settings(coloured.id, color_hex=EXAM_HEX)
    plain = db.create_exam_context(exam_name="Plain Exam")
    today = date.today()
    db.create_planned_session(today, exam_context_id=coloured.id, title="coloured plan")
    db.create_planned_session(today, exam_context_id=plain.id, title="plain plan")
    db.conn.commit()

    wimi_page.goto("calendar")
    _wait(wimi_page, _READY, what="the calendar gate to release")

    seen = []
    for theme in THEMES:
        wimi_page.eval_js(f"_wimiApplyThemeVariables('{theme}')")
        # Redraw: the mix direction is read off the painted body at render time.
        # renderGrid() rebuilds the rows, so a mark on the old cells vanishes
        # exactly when the new ones are drawn.
        wimi_page.eval_js("document.querySelector('#cal-grid-body td').setAttribute('data-stale', '1');"
                          " document.getElementById('cal-today').click()")
        _wait(wimi_page, "!document.querySelector('#cal-grid-body td[data-stale]')"
                         " && document.querySelectorAll('#cal-grid-body td').length > 0",
              what=f"the redraw under {theme}", tries=100)
        wimi_page.wait_for_timeout(350)       # let any colour transition settle before reading
        got = json.loads(wimi_page.eval_js(READ))
        assert got["coloured"], f"no exam-coloured chip drawn under {theme}: {got!r}"
        assert got["plain"] and got["plain"]["series"] is not None, (
            f"the uncoloured exam lost its series slot under {theme}: {got!r}")

        chip = got["coloured"]
        assert parse_css_color(chip["border"]) == _hex_rgb(EXAM_HEX), (
            f"{theme}: the border is {chip['border']}, not the exam's own colour")
        ratio = contrast_ratio(chip["text"], chip["bg"])
        assert ratio >= 4.5, f"{theme}: chip text {chip['text']} on fill {chip['bg']} is {ratio:.2f}:1"

        fill_l = relative_luminance(parse_css_color(chip["bg"]))
        body_l = relative_luminance(parse_css_color(got["body"]))
        exam_l = relative_luminance(_hex_rgb(EXAM_HEX))
        toward_bg = abs(fill_l - body_l) < abs(exam_l - body_l)
        assert toward_bg, (
            f"{theme}: the fill (L={fill_l:.3f}) did not move toward the page background "
            f"(L={body_l:.3f}) from the exam colour (L={exam_l:.3f}); #322's direction rule")
        seen.append((theme, chip["bg"]))

    fills = {bg for _, bg in seen}
    assert len(fills) >= 2, f"the fill never changed across six themes, so the direction rule is not live: {seen}"
