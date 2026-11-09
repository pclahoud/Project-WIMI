"""Regression: the Import Format Guide's footer is inside the dialog and on screen.

The dialog is ``.modal-xl`` with ``max-height: 90vh``, and its body was given
``max-height: calc(90vh - 8.75rem)`` -- a fixed 140 px allowance for
everything that is not the body. The header, the footer and the dialog's own
padding take about 224 px, so with the 45,000-character guide filling the
body the footer overflowed the dialog box by about 84 px. The box is centred
with 5vh below it, so on any ordinary window the footer -- *Copy the whole
guide* (#452) and *Close* -- sat below the bottom of the window.

Measured rendered, because a guessed allowance is what produced the bug:
the footer's box must lie inside the dialog's box, and the dialog's inside
the viewport. The first assertion holds at any window height, so the test
does not depend on the offscreen arm's larger viewport (CLAUDE.md, *OFFSCREEN
ALSO CHANGES THE GEOMETRY*).
"""
from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _wait_for(wimi_page: WimiPage, js: str, timeout_ms: int = 5000) -> Any:
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        last = wimi_page.eval_js(js)
        if last:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


_GEOMETRY = """
(() => {
  const box = document.querySelector('[data-testid="tree-import-help-modal-container"]');
  const body = document.getElementById('import-help-content');
  const foot = box && box.querySelector('.modal-footer');
  if (!box || !foot || !body) return null;
  const b = box.getBoundingClientRect(), f = foot.getBoundingClientRect();
  return { boxTop: b.top, boxBottom: b.bottom, footTop: f.top, footBottom: f.bottom,
           footHeight: f.height, innerHeight: window.innerHeight,
           bodyScrolls: body.scrollHeight > body.clientHeight + 1 };
})()
"""


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("viewport", [None, (1130, 689)], ids=["window", "1130x689"])
def test_the_guide_footer_is_inside_the_dialog_and_on_screen(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
    viewport,
) -> None:
    """``1130x689`` is this project's reference viewport, Windows machine B's
    clamped window; offscreen never clamps, so it is emulated here."""
    if viewport is not None:
        width, height = viewport
        wimi_page.tab.Emulation.setDeviceMetricsOverride(
            width=width, height=height, deviceScaleFactor=1, mobile=False)
    try:
        _check(wimi_page)
    finally:
        if viewport is not None:
            wimi_page.tab.Emulation.clearDeviceMetricsOverride()


def _check(wimi_page: WimiPage) -> None:
    wimi_page.goto("tree-editor")
    _wait_for(wimi_page, "!!document.getElementById('btn-import-help')")
    wimi_page.eval_js("document.getElementById('btn-import-help').click()")
    _wait_for(wimi_page, "!!document.querySelector('#import-help-content h2')")

    # The open transition scales the box; wait until two reads agree.
    previous, geo = None, None
    for _ in range(40):
        geo = wimi_page.eval_js(_GEOMETRY)
        if geo and previous and geo == previous:
            break
        previous = geo
        wimi_page.wait_for_timeout(100)
    assert geo, "the import guide dialog did not open"

    # Positive control: the guide must actually fill the body, or the
    # overflow this test is about cannot occur and a pass means nothing.
    assert geo["bodyScrolls"], f"the guide body does not scroll, so nothing was tested: {geo!r}"
    assert geo["footHeight"] > 0, f"the footer has no height: {geo!r}"

    assert geo["footBottom"] <= geo["boxBottom"] + 0.5, (
        f"the footer overflows the dialog by {geo['footBottom'] - geo['boxBottom']:.0f} px: {geo!r}")
    assert geo["boxTop"] >= -0.5 and geo["boxBottom"] <= geo["innerHeight"] + 0.5, (
        f"the dialog does not fit the window: {geo!r}")
