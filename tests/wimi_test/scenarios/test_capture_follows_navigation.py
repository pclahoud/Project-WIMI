"""Regression: the driven page is the page the window is showing.

The harness once attached to a ``QWebEnginePage`` with no view. Qt lists
a CDP target for every live page, ``test_mode.install_on_view`` left the
page it replaced alive, and ``MainWindow.__init__`` had already given
that page ``index.html`` -- so it carried a convincing "WIMI - ..." title
and ``WimiBrowser.primary_tab``, which matched on title, chose it.

Nothing in the suite noticed, and nothing could have. Driving a detached
page fails *upward*: it navigates, ``document.title`` and ``location``
report the new page, bridge calls return, every assertion about DOM state
passes. Only the pixels stay behind, because the window is showing a
different page entirely. Two further symptoms were written up for months
as permanent Qt limitations -- ``Page.captureScreenshot`` hanging, and CSS
transitions never advancing -- and both were this: a page nobody
composites produces no frames.

So this scenario asserts on the one thing a detached page cannot fake.

1. **The target says it is visible.** Direct check of the property
   ``primary_tab`` now screens on.
2. **Captures change when the page changes.** Compared on mean colour,
   not bytes: the dashboard opens on a tall saturated blue hero band and
   settings does not, so a capture that follows navigation swings by a
   wide margin while a stale frame cannot move at all. Byte equality
   would be too weak -- the ``QWidget.grab()`` stand-in that briefly
   replaced CDP capture returned images that differed by a few hundred
   bytes of encoder noise while showing the same frozen page all run.
3. **A capture returns at all**, within a bounded wait, which it did not
   when the target had no compositor.
"""
from __future__ import annotations

import io

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# How far apart two pages' mean colour must sit to count as "different
# page". Dashboard vs settings is ~150 on the blue channel; encoder noise
# and antialiasing move it by less than 1.
_MIN_MEAN_DELTA = 40.0


def _mean_rgb(png: bytes) -> tuple[float, float, float]:
    """Mean RGB of the page's top region, where the hero band lives."""
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    band = im.crop((int(w * 0.2), int(h * 0.05), int(w * 0.8), int(h * 0.45)))
    px = list(band.getdata())
    n = len(px)
    return tuple(sum(p[i] for p in px) / n for i in range(3))  # type: ignore[return-value]


@pytest.mark.regression
@pytest.mark.slow
def test_capture_follows_navigation(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    assert (
        wimi_page.eval_js("document.visibilityState") == "visible"
    ), (
        "the attached CDP target reports itself hidden, which means it has "
        "no view -- the window is showing some other page and every capture "
        "from this session will be of that other page"
    )

    wimi_page.goto("dashboard")
    wimi_page.wait_for_timeout(2000)
    dashboard = wimi_page.screenshot(timeout_ms=20000)

    wimi_page.goto("settings")
    wimi_page.wait_for_timeout(2000)
    settings = wimi_page.screenshot(timeout_ms=20000)

    assert dashboard and settings, "captureScreenshot returned no bytes"

    a, b = _mean_rgb(dashboard), _mean_rgb(settings)
    delta = max(abs(x - y) for x, y in zip(a, b))
    assert delta >= _MIN_MEAN_DELTA, (
        f"dashboard and settings captured as the same image "
        f"(mean RGB {a} vs {b}, max delta {delta:.1f}). The capture is not "
        f"following navigation -- suspect the attached target, not the "
        f"screenshot command. See TEST_INFRASTRUCTURE.md 12c."
    )
