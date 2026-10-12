"""The tour runs in screen order, and steps on one anchor are slides (#682).

The owner's decisions of 2026-10-10:

- **Order: sort by screen position at runtime**, top to bottom, left to right,
  when the queue is built. The manual's order was chapter order, which is why
  the tour "jumps all over each page".
- **The question bank pane gets several slides on the entry form's button.**
  The pane is a second QWebEngineView the page's tour cannot reach, so the
  slides are several steps on one anchor. The runner makes them ONE stop, keyed
  `page:anchor` as before, so no stored seen key changes meaning.

Fixtures on the dashboard, placed with `position: fixed` so every box is exact:
no real page has five boxes in a known arrangement, and the real pages' orders
are asserted by their own tour scenarios.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PANEL = """(() => {
  const p = document.querySelector('[data-testid="tour-panel"]');
  if (!p) return null;
  const q = s => p.querySelector(`[data-testid="${s}"]`);
  return {count: q('tour-count').textContent, title: q('tour-title').textContent,
          text: q('tour-text').textContent, slide: q('tour-slide') && q('tour-slide').textContent,
          more: q('tour-more') && q('tour-more').getAttribute('href'),
          next: q('tour-next').textContent};
})()"""
NEXT = "document.querySelector('[data-testid=\"tour-next\"]').click()"
SEEN = "window.api.getTourState().then(s => s.seen)"


def _step(anchor: str, text: str, section: str = "S", **extra) -> dict:
    step = {"page": "dashboard", "anchor": anchor, "text": text,
            "chapter": "the_first_hour", "chapter_title": "Your first hour",
            "section": section, "link": f"help_the_first_hour.html#{section.lower()}"}
    step.update(extra)
    return step


def _place(page: WimiPage, boxes: dict[str, tuple[int, int, int, int]]) -> None:
    """One fixed element per anchor: (top, left, width, height), named by its id."""
    page.eval_js(
        "((boxes) => { for (const [id, [t, l, w, h]] of Object.entries(boxes)) {"
        " const el = document.createElement('div'); el.setAttribute('data-tour-anchor', id);"
        " el.textContent = id; el.style.cssText = `position: fixed; top: ${t}px;"
        " left: ${l}px; width: ${w}px; height: ${h}px; overflow: hidden; z-index: 1;`;"
        " document.body.append(el); } })(%s)" % json.dumps(boxes))


def _walk(page: WimiPage) -> list[dict]:
    panels = []
    for _ in range(20):
        panel = page.eval_js(PANEL)
        if panel is None:
            return panels
        panels.append(panel)
        page.eval_js(NEXT)
    raise AssertionError(f"the tour did not end: {panels}")


def _start(page: WimiPage, steps: list[dict]) -> int:
    page.eval_js(f"window.WIMI_TOUR_STEPS = {{dashboard: {json.dumps(steps)}}}")
    return page.eval_js("WimiTour.start('dashboard')", await_promise=True)


@pytest.fixture
def dashboard(wimi_page: WimiPage) -> WimiPage:
    wimi_page.goto("dashboard")
    assert poll(wimi_page, "typeof WimiTour !== 'undefined' && LandingState.isLoading === false",
                timeout_ms=30000)
    wimi_page.eval_js("window.api.setTourAutoStartForTest(true)", await_promise=True)
    return wimi_page


@pytest.mark.slow
@pytest.mark.regression
def test_steps_run_top_to_bottom_then_left_to_right_whatever_the_manual_order(
    wimi_session: WimiTestSession, dashboard: WimiPage,
) -> None:
    _place(dashboard, {
        "fx-low-left": (500, 100, 200, 40),
        "fx-top": (120, 700, 200, 40),
        # One row whose tops differ: the checkbox-sized box is centred beside
        # the tall one but starts 11 px below it, and sits to its LEFT.
        "fx-row-tall": (300, 600, 200, 40),
        "fx-row-small": (311, 300, 18, 18),
        # A container taller than three times the box beside it is not its row.
        "fx-container": (290, 900, 200, 400),
    })
    manual = ["fx-low-left", "fx-row-tall", "fx-container", "fx-top", "fx-row-small"]
    assert _start(dashboard, [_step(a, f"Step on {a}.") for a in manual]) == 5
    assert [p["title"] for p in _walk(dashboard)] == [
        "About: fx-top", "About: fx-container", "About: fx-row-small",
        "About: fx-row-tall", "About: fx-low-left"]


@pytest.mark.slow
@pytest.mark.regression
def test_two_anchors_on_one_box_keep_the_manuals_order_either_way_round(
    wimi_session: WimiTestSession, dashboard: WimiPage,
) -> None:
    """Identical boxes tie on position, so the manual's order decides. It is
    written into the comparator, not left to the engine's sort stability, and
    both written orders are asserted so a tie broken by anything else fails."""
    _place(dashboard, {"fx-one": (200, 200, 120, 40), "fx-two": (200, 200, 120, 40)})
    for first, second in (("fx-one", "fx-two"), ("fx-two", "fx-one")):
        dashboard.eval_js("window.api.resetTour()", await_promise=True)
        _start(dashboard, [_step(first, "First written."), _step(second, "Second written.")])
        assert [p["text"] for p in _walk(dashboard)] == ["First written.", "Second written."], (
            first, second)


@pytest.mark.slow
@pytest.mark.regression
def test_steps_on_one_anchor_are_one_stop_whose_slides_keep_the_manuals_order(
    wimi_session: WimiTestSession, dashboard: WimiPage,
) -> None:
    _place(dashboard, {"fx-button": (400, 200, 160, 40), "fx-above": (100, 200, 160, 40)})
    steps = [_step("fx-button", "Slide one.", "Opening"),
             _step("fx-above", "The other stop."),
             _step("fx-button", "Slide two.", "Tabs"),
             _step("fx-button", "Slide three.", "Logins")]
    assert _start(dashboard, steps) == 2, "three steps on one anchor are one stop"

    panels = _walk(dashboard)
    assert [(p["count"], p["slide"], p["text"], p["next"]) for p in panels] == [
        ("Tip 1", None, "The other stop.", "Next"),
        ("Tip 2", "1 of 3", "Slide one.", "Next"),
        ("Tip 2", "2 of 3", "Slide two.", "Next"),
        ("Tip 2", "3 of 3", "Slide three.", "Done"),
    ], panels
    # Each slide links its own section.
    assert [p["more"] for p in panels[1:]] == [
        "help_the_first_hour.html#opening", "help_the_first_hour.html#tabs",
        "help_the_first_hour.html#logins"]
    # One identity for the stop, as `page:anchor` always was.
    seen = dashboard.eval_js(SEEN, await_promise=True)
    assert sorted(seen) == ["dashboard:fx-above", "dashboard:fx-button"], seen


@pytest.mark.slow
@pytest.mark.regression
def test_a_rebuild_keeps_the_slide_being_read(
    wimi_session: WimiTestSession, dashboard: WimiPage,
) -> None:
    """A page re-starts its tour on a view change; that must not send a
    student on slide 2 back to slide 1."""
    _place(dashboard, {"fx-button": (400, 200, 160, 40)})
    _start(dashboard, [_step("fx-button", "Slide one."), _step("fx-button", "Slide two."),
                       _step("fx-button", "Slide three.")])
    dashboard.eval_js(NEXT)
    assert dashboard.eval_js(PANEL)["slide"] == "2 of 3"
    assert dashboard.eval_js("WimiTour.start('dashboard')", await_promise=True) == 1
    panel = dashboard.eval_js(PANEL)
    assert (panel["slide"], panel["text"]) == ("2 of 3", "Slide two."), panel


@pytest.mark.slow
@pytest.mark.regression
def test_a_step_with_no_manual_section_shows_without_read_more(
    wimi_session: WimiTestSession, dashboard: WimiPage,
) -> None:
    """The owner's tour-only kind (decision 1) has no section to link, so the
    generator will emit it without `link`, `section` or `chapter_title`."""
    _place(dashboard, {"fx-label": (200, 200, 160, 40)})
    step = {"page": "dashboard", "anchor": "fx-label", "text": "This is the date filter."}
    assert _start(dashboard, [step]) == 1
    panel = dashboard.eval_js(PANEL)
    assert panel["text"] == "This is the date filter." and panel["more"] is None, panel
    assert "undefined" not in json.dumps(panel), panel


@pytest.mark.slow
@pytest.mark.regression
def test_a_sequence_is_recorded_seen_on_its_last_slide_so_leaving_part_way_repeats_it(
    wimi_session: WimiTestSession, dashboard: WimiPage,
) -> None:
    """Owner, 2026-10-10 (#682 decision 5): a student who reads two of three
    slides and leaves is shown the sequence again, rather than never seeing
    the rest."""
    slides = [_step("fx-button", "Slide one."), _step("fx-button", "Slide two."),
              _step("fx-button", "Slide three.")]
    _place(dashboard, {"fx-button": (400, 200, 160, 40)})
    _start(dashboard, slides)
    dashboard.eval_js(NEXT)
    assert dashboard.eval_js(PANEL)["slide"] == "2 of 3"
    dashboard.wait_for_timeout(500)  # past any seen-write a slide might have made
    assert dashboard.eval_js(SEEN, await_promise=True) == []

    # The student leaves: the page goes and comes back.
    dashboard.eval_js("window.__previousDocument = true")
    dashboard.goto("dashboard")
    assert poll(dashboard, "window.__previousDocument !== true && typeof WimiTour !== 'undefined'"
                " && LandingState.isLoading === false", timeout_ms=30000)
    _place(dashboard, {"fx-button": (400, 200, 160, 40)})
    assert _start(dashboard, slides) == 1
    assert dashboard.eval_js(PANEL)["text"] == "Slide one."
    dashboard.eval_js(NEXT)
    dashboard.eval_js(NEXT)
    assert dashboard.eval_js(PANEL)["slide"] == "3 of 3"
    for _ in range(50):  # the seen-write is asynchronous
        if "dashboard:fx-button" in dashboard.eval_js(SEEN, await_promise=True):
            break
        dashboard.wait_for_timeout(100)
    # The reload started the dashboard's real tour first, so its own step is
    # in the list too.
    assert "dashboard:fx-button" in dashboard.eval_js(SEEN, await_promise=True), (
        "the last slide did not record the sequence")


@pytest.mark.slow
@pytest.mark.regression
def test_the_counter_runs_on_for_a_step_that_renders_after_the_tour_ended(
    wimi_session: WimiTestSession, dashboard: WimiPage,
) -> None:
    """Owner, 2026-10-10 (#682 decision 6): "Tip 6", not "Tip 1 of 1". The
    tree editor's shared-parents chip renders only once rows are expanded, and
    the restart after "Tip 5 of 5" was measured there on 11f4932."""
    _place(dashboard, {"fx-a": (100, 200, 160, 40), "fx-b": (200, 200, 160, 40)})
    steps = [_step("fx-a", "First."), _step("fx-b", "Second."), _step("fx-late", "Late.")]
    assert _start(dashboard, steps) == 2
    assert [p["count"] for p in _walk(dashboard)] == ["Tip 1", "Tip 2"]

    _place(dashboard, {"fx-late": (300, 200, 160, 40)})
    assert _start(dashboard, steps) == 1
    panel = dashboard.eval_js(PANEL)
    assert (panel["count"], panel["text"]) == ("Tip 3", "Late."), panel
    # The queue's length is kept for a later choice to show it again.
    assert dashboard.eval_js(
        "document.querySelector('[data-testid=\"tour-count\"]').dataset.tourTotal") == "1"
