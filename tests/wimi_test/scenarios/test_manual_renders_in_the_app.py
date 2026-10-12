"""The manual renders in the real engine, and the way in from the dashboard works (#428).

Why this exists when `tests/test_manual_chapters.py` already covers the gate
----------------------------------------------------------------------------
Everything about the manual that Python can check is checked there: the pages
are the chapters, the chapters avoid constructs the renderer cannot draw, the
index lists exactly what is on disk. None of that runs a line of the renderer.

The renderer is a regex markdown renderer and its failure mode is never an
error. It is the wrong thing drawn in the shipped app, which is how
`parseMarkdown`'s three documented limits survived for years, and how a backtick
inside an HTML comment inside a template literal left the tree editor
permanently gated with an empty tree and nothing else wrong (2026-10-03). A
`SyntaxError` in `help_page.js` would leave every chapter showing its holding
line and would pass every test in this repo except this one.

The wrapped-bullet assertion is a measured regression, not a precaution
----------------------------------------------------------------------
The first version of `renderHelpMarkdown` ended a list run at the first wrapped
line, so

    - **Username** is required. At least three characters, and only letters,
      numbers, hyphens and underscores.

rendered as a one-item list followed by a stray paragraph. Chapter 2 produced
**17 `<ul>` elements for 6 lists**. It raised nothing, and the page still looked
broadly like a page. So the assertion below is on the *count*: one `<ul>` per
list in the markdown, and no list item orphaned into a paragraph.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANUAL_DIR = PROJECT_ROOT / "docs" / "manual"
TOUR_ARTIFACT = PROJECT_ROOT / "src" / "web" / "js" / "tour_steps.js"

#: The tour's short forms are written as HTML comments in the chapters (#430),
#: and the ONLY thing that keeps one off the page is `helpStripComments` in
#: `help_page.js`. That was measured rather than assumed: before it existed, a
#: block planted in chapter 1 rendered as an ordinary visible paragraph between
#: a heading and its first sentence -- 15 paragraphs where the chapter has 14,
#: `innerText` carrying the marker, and no DOM comment node anywhere, because
#: the paragraph branch had escaped its angle brackets. Nothing else in the
#: suite can see that: a leaked comment is neither a table nor a broken list,
#: so every other fault below stays silent on it.
TOUR_MARKER = "<!-- tour"

#: A node that exists only once `help_page.js` has rendered the embedded
#: markdown. `#help-chapter-body` itself ships in the markup, holding a
#: placeholder line, so it is not a signal that anything has happened.
RENDERED = "#help-chapter-body h2[id]"

#: What the chapter page looks like once `help_page.js` has run. Read in one
#: evaluate so the numbers describe one state of the document.
CHAPTER_SHAPE = """
(() => {
  const body = document.getElementById('help-chapter-body');
  if (!body) return JSON.stringify({ found: false });
  const embed = document.getElementById('help-chapter-source');
  const MARKER = '%s';
  return JSON.stringify({
    found: true,
    url: window.location.href,
    holding: body.querySelectorAll('.help-body-holding').length,
    error: body.querySelectorAll('.help-body-error').length,
    h1_in_body: body.querySelectorAll('h1').length,
    h2: body.querySelectorAll('h2').length,
    h2_with_id: body.querySelectorAll('h2[id]').length,
    lists: body.querySelectorAll('ul').length,
    list_items: body.querySelectorAll('li').length,
    paragraphs: body.querySelectorAll('p').length,
    strong: body.querySelectorAll('strong').length,
    page_h1: document.querySelectorAll('h1').length,
    ids: Array.from(body.querySelectorAll('[id]')).map(el => el.id),
    embed_has_marker: (embed ? embed.textContent : '').indexOf(MARKER) !== -1,
    marker_in_text: body.innerText.indexOf(MARKER) !== -1,
    marker_in_html: body.innerHTML.indexOf(MARKER) !== -1,
    text: body.innerText
  });
})()
""" % TOUR_MARKER


def _markdown_lists(markdown: str) -> tuple[int, int]:
    """``(expected <ul> count, bullet lines)`` for a chapter, outside fences.

    Counting from the source rather than hardcoding a number is what keeps this
    true of chapter 21. A run of bullets with no blank line in it becomes one
    ``<ul>``, and each descent to a deeper indent inside a run opens another --
    so the arithmetic has to follow the nesting, or a chapter that legitimately
    nests a list would fail this for the wrong reason.
    """
    lists = 0
    items = 0
    open_levels: list[int] = []
    in_fence = False
    for line in markdown.split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        bullet = re.match(r"^(\s*)[-*] +\S", line)
        if bullet:
            items += 1
            level = len(bullet.group(1)) // 2
            while open_levels and level < open_levels[-1]:
                open_levels.pop()
            if not open_levels or level > open_levels[-1]:
                open_levels.append(level)
                lists += 1
        elif not line.strip():
            # A blank line ends the run. A wrapped continuation line does not,
            # which is the distinction the renderer also has to make.
            open_levels = []
    return lists, items


def _chapters() -> list[Path]:
    chapters = sorted(MANUAL_DIR.glob("*.md"))
    assert chapters, f"no chapters under {MANUAL_DIR}"
    return chapters


def _first_chapter() -> Path:
    return _chapters()[0]


def _slug(path: Path) -> str:
    return path.name.split("_", 1)[1].removesuffix(".md")


def _tour_fragments() -> dict[str, set[str]]:
    """``{chapter slug: the heading ids the tour's links name}``.

    Read out of the committed artifact rather than re-derived from the
    markdown. Re-deriving would be circular: the artifact's fragments come from
    a Python transcription of ``helpSlugify``, so checking them against another
    Python transcription proves only that the two agree. The engine is the only
    place that can say whether the id really exists.
    """
    text = TOUR_ARTIFACT.read_text(encoding="utf-8")
    payload = text.split("window.WIMI_TOUR_STEPS = ", 1)[1].rstrip().rstrip(";")
    wanted: dict[str, set[str]] = {}
    for steps in json.loads(payload).values():
        for step in steps:
            # An orientation step (#682, docs/manual/tour/orientation.md) names
            # a control and sits in no chapter, so it carries no link to check.
            if "link" not in step:
                continue
            page, _, fragment = step["link"].partition("#")
            slug = page.removeprefix("help_").removesuffix(".html")
            wanted.setdefault(slug, set()).add(fragment)
    return wanted


def _chapter_faults(
    markdown: str, shape: dict, fragments: set[str] | None = None
) -> list[str]:
    """Everything wrong with one rendered chapter, as sentences.

    Collected rather than asserted one at a time so a run over every chapter
    reports every chapter's problems at once. The checks are the ones the
    single-chapter test above makes, minus the ones that are about the way in
    from the dashboard.
    """
    faults: list[str] = []
    if not shape["found"]:
        return ["the page has no #help-chapter-body"]
    if shape["holding"] or shape["error"]:
        faults.append(
            f"still showing its holding or error line "
            f"(holding={shape['holding']}, error={shape['error']}), so "
            f"help_page.js never rendered the embedded markdown"
        )
    if shape["h2"] < 3 or shape["h2_with_id"] != shape["h2"]:
        faults.append(
            f"{shape['h2']} h2(s), {shape['h2_with_id']} with an id -- a "
            f"heading with no id cannot be deep linked"
        )
    if shape["page_h1"] != 1 or shape["h1_in_body"]:
        faults.append(
            f"expected one h1 in the markup and none in the rendered body, "
            f"got page_h1={shape['page_h1']}, h1_in_body={shape['h1_in_body']}"
        )
    runs, bullets = _markdown_lists(markdown)
    if shape["lists"] != runs:
        faults.append(
            f"{runs} list run(s) in the markdown rendered as "
            f"{shape['lists']} <ul> -- more lists than runs is the "
            f"wrapped-bullet defect in this module's docstring"
        )
    if shape["list_items"] != bullets:
        faults.append(
            f"{bullets} bullet(s) rendered as {shape['list_items']} <li>"
        )
    if "|" in shape["text"]:
        faults.append(
            "a literal pipe reached the rendered text, which is what an "
            "unparsed table looks like"
        )
    if "](" in shape["text"]:
        faults.append("an unrendered markdown link reached the rendered text")

    # The tour's marker, both halves. The absence on its own would pass against
    # a chapter carrying no block at all, so the embed is the positive control:
    # the comment HAS to be in the page, verbatim, and HAS to be absent from
    # what the student reads.
    has_block = TOUR_MARKER in markdown
    if has_block and not shape["embed_has_marker"]:
        faults.append(
            "its markdown carries a tour block but the page's embed does not, "
            "so the control for the next check is dead and its absence from "
            "the rendered body would mean nothing"
        )
    # `innerText` is the half that fires on the measured leak: the paragraph
    # branch escapes the angle brackets, so `innerHTML` holds `&lt;!-- tour`
    # and the raw marker is not in it -- verified by stubbing the strip, which
    # reported `innerText=True, innerHTML=False` on 19 chapters. The
    # `innerHTML` half is kept for the other shape, a comment that reaches the
    # markup unescaped as a real comment node, which `innerText` cannot see.
    if shape["marker_in_text"] or shape["marker_in_html"]:
        faults.append(
            f"the tour marker reached the rendered chapter "
            f"(innerText={shape['marker_in_text']}, "
            f"innerHTML={shape['marker_in_html']}), so a student reads it. "
            f"helpStripComments in help_page.js is what prevents this"
        )

    # Every deep link the tour generates has to name a heading that exists.
    for fragment in sorted(fragments or ()):
        if fragment not in shape["ids"]:
            faults.append(
                f"a tour step links #{fragment} in this chapter and no element "
                f"has that id, so the step's 'read more' lands at the top of "
                f"the page with nothing anywhere saying so"
            )
    return faults


def test_the_dashboard_leads_to_the_manual_and_a_chapter_renders(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Dashboard -> index -> chapter, by real clicks, then read the chapter."""
    # ---- Arrange ----------------------------------------------------------
    wimi_page.goto("dashboard")

    # ---- Act: the affordance ----------------------------------------------
    wimi_page.locator(testid="dashboard-help-link").click()
    # Reaching the index at all is the first assertion: a missing or renamed
    # generated list would leave a page with a heading and nothing to press.
    wimi_page.locator(testid="help-chapter-list").expect_visible()

    slug = _first_chapter().name.split("_", 1)[1].removesuffix(".md")
    wimi_page.locator(testid=f"help-chapter-link-{slug}").click()

    # Wait on a node that exists only AFTER the renderer has run, not on
    # `#help-chapter-body`, which ships in the markup holding a "Opening this
    # chapter..." line. A navigation returns before the new document commits,
    # so waiting on the container would read the previous page or the holding
    # state and report a defect that is not there.
    wimi_page.locator(css=RENDERED).expect_visible()
    shape = json.loads(wimi_page.eval_js(CHAPTER_SHAPE))

    # ---- Assert -----------------------------------------------------------
    assert shape["found"], (
        "the chapter page has no #help-chapter-body, so the generator and this "
        "scenario disagree about the markup"
    )
    assert shape["holding"] == 0 and shape["error"] == 0, (
        f"the chapter still shows its holding or error line, so help_page.js "
        f"never rendered the embedded markdown. A SyntaxError in that file "
        f"looks exactly like this and nothing else in the suite can see it. "
        f"Shape: {shape}"
    )
    assert shape["h2"] >= 3 and shape["h2_with_id"] == shape["h2"], (
        f"the chapter's headings are missing or missing their ids, so no deep "
        f"link into it can work. Shape: {shape}"
    )

    # One h1 on the page, in the markup, and none inside the rendered body:
    # the generator writes the title and the renderer drops the source's own
    # `# ` line, because `tests/test_heading_order.py` reads markup and cannot
    # see a heading a script created.
    assert shape["page_h1"] == 1 and shape["h1_in_body"] == 0, (
        f"expected exactly one h1, in the markup rather than the rendered "
        f"body. Shape: {shape}"
    )

    runs, bullets = _markdown_lists(_first_chapter().read_text(encoding="utf-8"))
    assert shape["lists"] == runs, (
        f"the chapter's markdown has {runs} list run(s) and the page rendered "
        f"{shape['lists']} <ul> element(s). More lists than runs is the wrapped-"
        f"bullet defect in the module docstring: a run ending at its first "
        f"continuation line, leaving the remainder as a stray paragraph"
    )
    assert shape["list_items"] == bullets, (
        f"{bullets} bullet(s) in the markdown rendered as "
        f"{shape['list_items']} <li>"
    )
    assert shape["strong"] >= 1, (
        "no inline markup rendered at all, which the chapters all use"
    )


def test_a_deep_link_lands_on_the_heading_it_names(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """`help_x.html#heading` lands on that heading, on a freshly loaded page.

    What this asserts is the OUTCOME, and it deliberately does not claim to
    isolate the mechanism. Measured 2026-10-06: deleting the one call to
    `helpApplyHashTarget()` leaves this test green, because Chromium defers and
    retries its own fragment scroll until the document has finished loading and
    the chapter renders on `DOMContentLoaded`, before that retry. The shim is
    kept as cover for the day rendering becomes asynchronous; this test is not
    what would notice if it went.

    The outcome is still worth a test, and the two controls are what make it
    one. Changing only the fragment of a URL you are already on is a
    **same-document** navigation -- nothing reloads, the headings already exist,
    and the scroll is trivially correct -- so the deep link has to arrive on a
    *fresh* document. That is why this goes back to the index in between and
    then asserts, with a window marker, that the document really is new. The
    second control is the no-fragment read: a page already scrolled would make
    the final assertion pass whatever happened.
    """
    # ---- Arrange ----------------------------------------------------------
    wimi_page.goto("help")
    slug = _first_chapter().name.split("_", 1)[1].removesuffix(".md")
    page = f"help_{slug}.html"

    wimi_page.eval_js(f"window.location.href = {page!r}")
    wimi_page.locator(css=RENDERED).expect_visible()
    probe = json.loads(wimi_page.eval_js("""
      (() => {
        const ids = Array.from(
          document.querySelectorAll('#help-chapter-body h2[id]')
        ).map(h => h.id);
        return JSON.stringify({
          ids: ids,
          scroll_y: window.scrollY,
          scrollable: document.documentElement.scrollHeight > window.innerHeight
        });
      })()
    """))
    assert probe["ids"], "the chapter rendered no headings with ids"
    if not probe["scrollable"]:
        pytest.skip(
            "the chapter does not overflow this viewport, so there is no "
            "scroll position to assert on"
        )
    assert probe["scroll_y"] == 0, (
        f"the control failed: the chapter is already scrolled to "
        f"{probe['scroll_y']} with no fragment, so the assertion below would "
        f"pass whatever the shim did"
    )

    # ---- Act --------------------------------------------------------------
    # Leave the chapter, so arriving at it with a fragment is a document load
    # and not a same-document hash change. The marker is how the assertion
    # below knows which of the two happened.
    target = probe["ids"][-1]
    wimi_page.eval_js("window.__manualProbe = 1")
    wimi_page.eval_js("window.location.href = 'help.html'")
    wimi_page.locator(testid="help-chapter-list").expect_visible()
    wimi_page.eval_js(f"window.location.href = {page + '#' + target!r}")
    wimi_page.locator(css=RENDERED).expect_visible()

    # ---- Assert -----------------------------------------------------------
    after = json.loads(wimi_page.eval_js(f"""
      (() => {{
        const el = document.getElementById({target!r});
        return JSON.stringify({{
          present: !!el,
          fresh_document: typeof window.__manualProbe === 'undefined',
          scroll_y: window.scrollY
        }});
      }})()
    """))
    assert after["fresh_document"], (
        "the chapter was not reloaded, so this measured the browser's own "
        "same-document fragment scroll and says nothing about the shim"
    )
    assert after["present"], (
        f"the heading id {target!r} is not in the document after navigating to "
        f"it, so the renderer and the fragment disagree"
    )
    assert after["scroll_y"] > 0, (
        f"navigating to #{target} left the page at scroll 0. The fragment is "
        f"resolved before the markdown exists, so helpApplyHashTarget() is the "
        f"only thing that can move it -- a deep link from the app arrives at "
        f"the top of the chapter and reads as a wrong anchor"
    )


def test_every_chapter_renders_in_the_real_engine(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The same checks as the first test, over **every** chapter.

    Why this is separate from the test above rather than folded into it: that
    one is about the way in from the dashboard, by real clicks, and widening it
    would make 24 chapters' worth of rendering depend on one affordance. This
    one navigates directly and only asks whether each chapter draws.

    Why it exists at all. The test above reads ``_first_chapter()`` only, so
    until this landed the manual had **one** chapter rendered in the real
    engine and twenty-three never rendered anywhere. Four waves of #428 each
    wrote this check as a throwaway scenario, confirmed their own chapters and
    deleted it, which means every earlier chapter was unprotected the moment
    its author finished. The defect class is real and measured: the renderer's
    first version ended a list run at its first wrapped line, and chapter 2
    drew 17 ``<ul>`` for 6 lists with no error anywhere.

    One session, one navigation per chapter, and every fault collected before
    anything is asserted -- a chapter-at-a-time failure would hide the rest,
    and the cheap thing to know when a renderer change breaks something is
    whether it broke one chapter or all of them.

    Self-counting: nothing here lists the chapters, so chapter 25 is rendered
    the day it is written. The ``found_them_all`` assertion is what stops a
    discovery-based sweep passing because it discovered nothing (#121's
    lesson).

    Two things it also carries, both for the tour (#430), because this is the
    one place in the suite that runs the renderer over every chapter:

    * **the tour's marker does not reach a student**, with the page's own embed
      as the positive control. A short form is an HTML comment and
      ``help_page.js`` strips it; measured, before that strip existed the
      comment drew as an ordinary paragraph. The absence alone would pass on a
      chapter carrying no block, hence the control.
    * **every deep link the tour generates names a heading that exists.** The
      artifact's fragments come from a Python mirror of ``helpSlugify``, so
      re-deriving them in Python would prove only that the mirror agrees with
      itself. The engine is the only place that can answer it.
    """
    chapters = _chapters()
    checked: list[str] = []
    problems: dict[str, list[str]] = {}
    fragments = _tour_fragments()
    assert fragments, (
        "the tour artifact yielded no deep links, so the fragment half of "
        "this sweep would pass by checking nothing"
    )

    for path in chapters:
        page = f"help_{_slug(path)}.html"
        # Mark the current document and wait for the mark to vanish: a
        # navigation returns before the new document commits, so reading the
        # body straight away reads the previous chapter (README's rule).
        wimi_page.eval_js("window.__manualSweep = 1")
        wimi_page.eval_js(f"window.location.href = {page!r}")
        for _ in range(100):
            if wimi_page.eval_js(
                "typeof window.__manualSweep === 'undefined'"
            ) is True:
                break
            wimi_page.wait_for_timeout(100)
        else:
            raise AssertionError(
                f"{page} never replaced the previous document, so every "
                f"figure below would describe the chapter before it"
            )
        wimi_page.locator(css=RENDERED).expect_visible()
        shape = json.loads(wimi_page.eval_js(CHAPTER_SHAPE))
        checked.append(page)
        faults = _chapter_faults(
            path.read_text(encoding="utf-8"), shape, fragments.get(_slug(path))
        )
        if faults:
            problems[path.name] = faults

    assert sum(1 for p in chapters if TOUR_MARKER in p.read_text(encoding="utf-8")) > 1, (
        "no chapter carries a tour block, so the marker-leak check above is "
        "a tautology -- it would pass on a renderer that strips nothing"
    )
    assert len(checked) == len(chapters) and len(chapters) > 1, (
        f"the sweep rendered {len(checked)} of {len(chapters)} chapter(s); a "
        f"sweep that sweeps nothing passes vacuously"
    )
    assert not problems, "chapters that did not render correctly:\n" + "\n".join(
        f"  {name}: " + "; ".join(faults) for name, faults in problems.items()
    )
