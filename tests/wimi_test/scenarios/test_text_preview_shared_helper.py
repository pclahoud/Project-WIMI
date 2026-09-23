"""Regression: the shared rich-text preview helper, and its inert parse.

Forgejo issue #41 -- "[cleanup] Two copies of htmlToPreviewText: entry
browser and session setup":

    Fixing #3 added ``EntryBrowser.htmlToPreviewText`` -- a DOMParser-based
    "reduce stored rich-text HTML to a plain-text preview" helper. Fixing
    #34 needed exactly the same behaviour for the session-setup
    remove-entries picker and, on instruction from the issue, added a
    second copy rather than consolidating. The two bodies are now identical
    line for line, including the block-element list that decides where a
    space is inserted. [...] The security property -- parse inert, return
    ``textContent``, never touch the live document -- is also the kind of
    thing that should be stated once.

The two bodies were byte-identical (only the `function` keyword and the
doc comment differed), so there was no divergence to reconcile; the
consolidation into ``js/text_preview.js`` (``window.WimiTextPreview``) is
behaviour-preserving. This scenario pins that behaviour to the one
definition, so a later change to the block list or the whitespace
handling has to be deliberate.

Two things it guards that the per-call-site scenarios cannot:

1. **The module is actually loaded on both pages.** Scripts are linked per
   HTML page, not project-wide (CLAUDE.md, "per-page CSS link gotcha" --
   it applies to ``<script>`` just as much). A missing tag leaves
   ``window.WimiTextPreview`` undefined and the preview silently blank or
   throwing, so both consuming pages are asserted here.
2. **The parse stays inert.** This is a ``DOMParser`` call rather than a
   regex or an ``innerHTML`` round-trip precisely because
   ``parseFromString`` builds a document with no browsing context:
   scripts do not run, ``<img>`` does not fetch, ``onerror``/``onload``
   never fire, and nothing reaches the live page. Payloads that would set
   a sentinel global are fed through the helper and the sentinel is
   checked afterwards.

The per-call-site behaviour stays pinned by
``test_entry_browser_card_reflection_html.py`` (#3) and
``test_session_picker_note_html.py`` (#34).

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

MODULE_PRESENT = (
    "!!(window.WimiTextPreview"
    " && typeof window.WimiTextPreview.htmlToPreviewText === 'function')"
)

# Every case the two merged copies were written against, plus the block
# elements only their selector list mentioned (tr, blockquote, pre, h1-h6)
# and the entity/whitespace handling neither call site exercises directly.
REDUCTION_CASES = r"""
(() => {
  const f = window.WimiTextPreview.htmlToPreviewText;
  return JSON.stringify({
    empty: f(''),
    nullish: f(null),
    undef: f(undefined),
    zero: f(0),
    plain: f('just plain text'),
    nested: f('<p>Anchored on <strong>the wrong</strong> feature.</p>'
              + '<ul><li>item</li></ul>'),
    divs: f('<div>a</div><div>b</div>'),
    lineBreak: f('a<br>b'),
    headings: f('<h1>Head</h1><blockquote>Quote</blockquote><pre>Pre</pre>'),
    tableRows: f('<table><tr><td>a</td></tr><tr><td>b</td></tr></table>'),
    entities: f('&nbsp;&amp;&lt;tag&gt;&nbsp;'),
    collapse: f('<p>a\n\n   b</p>'),
    trim: f('<p>  spaced  </p>'),
    nbspOnly: f('&nbsp;')
  });
})()
"""

# Each payload would set window.__wimiInertProbe if the parse were live, or
# if the markup reached the real document. The helper's return value is
# collected too, so "it threw and we never noticed" cannot pass.
INERT_CASES = r"""
(() => {
  const f = window.WimiTextPreview.htmlToPreviewText;
  const before = {
    imgs: document.querySelectorAll('img[src*="wimi-inert-probe"]').length,
    iframes: document.querySelectorAll('iframe[src*="wimi-inert-probe"]').length
  };
  const out = {
    imgOnError: f('<img src="wimi-inert-probe-1.png"'
                  + ' onerror="window.__wimiInertProbe=1">'),
    imgAfterText: f('<p>text</p><img src="wimi-inert-probe-2.png"'
                    + ' onerror="window.__wimiInertProbe=2">'),
    scriptFirst: f('<script>window.__wimiInertProbe=3<\/script>'),
    scriptAfterText: f('<p>x</p><script>window.__wimiInertProbe=4<\/script>'),
    svgOnLoad: f('<svg><g onload="window.__wimiInertProbe=5"></g></svg>'),
    bodyOnLoad: f('<body onload="window.__wimiInertProbe=6">hi</body>'),
    iframe: f('<p>x</p><iframe src="wimi-inert-probe-3.html"></iframe>')
  };
  return JSON.stringify({
    out: out,
    probe: window.__wimiInertProbe === undefined ? null : window.__wimiInertProbe,
    before: before,
    after: {
      imgs: document.querySelectorAll('img[src*="wimi-inert-probe"]').length,
      iframes: document.querySelectorAll('iframe[src*="wimi-inert-probe"]').length
    }
  });
})()
"""


def _poll(wimi_page: WimiPage, js: str, *, timeout_ms: int = 15000):
    """Poll ``js`` until it returns something truthy (or the budget runs out)."""
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last:
            return last
        wimi_page.wait_for_timeout(200)
        elapsed += 200
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_preview_helper_is_loaded_on_both_consuming_pages(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The shared module reaches both pages that call it.

    Consolidating the helper moved it out of the page scripts, so each
    consuming page now needs its own ``<script src="../js/text_preview.js">``
    tag. Miss one and the symbol is undefined there with no build error --
    the failure mode CLAUDE.md warns about for per-page asset links.
    """
    # ---- Entry browser (issue #3's call site) ------------------------
    wimi_page.goto('entry-browser')
    assert _poll(wimi_page, MODULE_PRESENT) is True, (
        'window.WimiTextPreview is not defined on entry_browser.html -- '
        'the page is missing its <script src="../js/text_preview.js"> tag.'
    )
    assert wimi_page.eval_js(
        "window.WimiTextPreview.htmlToPreviewText('<p>a</p><ul><li>b</li></ul>')"
    ) == 'a b'

    # ---- Session setup (issue #34's call site) -----------------------
    wimi_page.goto('session-setup')
    assert _poll(wimi_page, MODULE_PRESENT) is True, (
        'window.WimiTextPreview is not defined on session_setup.html -- '
        'the page is missing its <script src="../js/text_preview.js"> tag.'
    )
    assert wimi_page.eval_js(
        "window.WimiTextPreview.htmlToPreviewText('<p>a</p><ul><li>b</li></ul>')"
    ) == 'a b'
    # The page-local copy is gone, not shadowing the shared one.
    assert wimi_page.eval_js("typeof htmlToPreviewText") == 'undefined', (
        'session_setup.js still defines its own htmlToPreviewText -- '
        'the consolidation left the duplicate behind.'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_preview_helper_reduces_stored_markup_to_one_line(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The union of what both merged copies handled, pinned once."""
    # ---- Arrange / Act -----------------------------------------------
    wimi_page.goto('entry-browser')
    assert _poll(wimi_page, MODULE_PRESENT) is True
    got = json.loads(wimi_page.eval_js(REDUCTION_CASES))

    # ---- Assert: falsy input is '' before anything is parsed ---------
    for key in ('empty', 'nullish', 'undef', 'zero'):
        assert got[key] == '', f'{key} should reduce to empty string: {got[key]!r}'

    # ---- Assert: text survives, markup does not ----------------------
    assert got['plain'] == 'just plain text', got['plain']
    assert got['nested'] == 'Anchored on the wrong feature. item', got['nested']
    for key, value in got.items():
        if key == 'entities':
            continue  # decoded student text, asserted exactly below
        assert '<' not in value and '>' not in value, (
            f'{key} leaked markup characters into the preview: {value!r}'
        )

    # ---- Assert: block boundaries become a space ---------------------
    # Without the inserted spaces these fuse ("ab", "feature.item"), which
    # is the whole reason the helper is not a plain textContent read.
    assert got['divs'] == 'a b', got['divs']
    assert got['lineBreak'] == 'a b', got['lineBreak']
    assert got['headings'] == 'Head Quote Pre', got['headings']
    assert got['tableRows'] == 'a b', got['tableRows']

    # ---- Assert: entities are decoded, whitespace collapsed ----------
    # Decoded '&lt;tag&gt;' is the one case where '<' is legitimately in
    # the output: it is the student's text, not markup, and every caller
    # puts it through textContent or escapeHtml on the way to the page.
    assert got['entities'] == '&<tag>', got['entities']
    assert got['collapse'] == 'a b', got['collapse']
    assert got['trim'] == 'spaced', got['trim']
    # \s covers U+00A0 in JS, so a note that is only &nbsp; previews empty
    # and the caller shows its "no reflection" placeholder instead.
    assert got['nbspOnly'] == '', got['nbspOnly']


@pytest.mark.slow
@pytest.mark.regression
def test_preview_helper_parse_is_inert(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Active content in a stored field neither runs nor reaches the page.

    ``DOMParser.parseFromString`` yields a document with no browsing
    context. Nothing below should execute, fetch, or be inserted anywhere.
    """
    # ---- Arrange / Act -----------------------------------------------
    wimi_page.goto('entry-browser')
    assert _poll(wimi_page, MODULE_PRESENT) is True
    result = json.loads(wimi_page.eval_js(INERT_CASES))

    # ---- Assert: nothing executed ------------------------------------
    assert result['probe'] is None, (
        'A payload fed through htmlToPreviewText executed: sentinel was set '
        f'to {result["probe"]!r}. The parse is no longer inert -- check that '
        'the helper still uses DOMParser and never innerHTML or a live node.'
    )

    # ---- Assert: nothing reached the live document -------------------
    assert result['before'] == {'imgs': 0, 'iframes': 0}, result['before']
    assert result['after'] == {'imgs': 0, 'iframes': 0}, (
        'Markup from a preview payload was inserted into the live page: '
        f'{result["after"]!r}.'
    )

    # ---- Assert: only text comes back --------------------------------
    out = result['out']
    assert out['imgOnError'] == '', out['imgOnError']
    assert out['imgAfterText'] == 'text', out['imgAfterText']
    assert out['svgOnLoad'] == '', out['svgOnLoad']
    assert out['bodyOnLoad'] == 'hi', out['bodyOnLoad']
    assert out['iframe'] == 'x', out['iframe']
    # A leading <script> is parsed into the inert document's head, so it is
    # not in body.textContent at all. One that follows body content lands in
    # the body, and its source comes back as ordinary inert text -- ugly in a
    # preview, but never executed. TinyMCE does not write <script>, so this
    # is documented rather than stripped; changing it is a behaviour change,
    # not part of the #41 consolidation.
    assert out['scriptFirst'] == '', out['scriptFirst']
    assert out['scriptAfterText'] == 'x window.__wimiInertProbe=4', (
        out['scriptAfterText']
    )
