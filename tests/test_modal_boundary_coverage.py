"""A page that can hide behind a modal must be known to be at risk (#420).

`aria-modal="true"` does nothing on QtWebEngine 6.9.2 / Chromium 130, measured
four ways in `modal_dialog.js`'s own header. What makes a dialog modal here is
that helper's walk from the surface to `<body>`, writing `aria-hidden` on each
sibling along the path.

#420: a guard protecting live regions skipped any sibling that merely
*contained* one. A page's main container contains everything, so a single
`role="status"` inside it exempted the whole page and the dialog was not modal
at all. On Settings, exposed accessibility nodes went **190 -> 214** when the
dialog opened -- *up*. The AX role was `dialog`, the accessible name was there,
focus was inside: every obvious assertion passed. `hiddenCount()` read 3 and all
three were `<script>` tags. The fix is `f5bf08d`.

**This file is the cheap half of what #420 asked for.** It cannot tell whether a
boundary is drawn -- only a running page can -- but it can tell when a page
*acquires the precondition*, which is what nobody noticed twice. #420 was
created by two separate changes that each added a `role="status"` to a page that
already had modals. Neither touched `modal_dialog.js`; neither author could have
known. So this is self-counting over the markup rather than a list someone has
to remember to extend.

Two things measured on 2026-10-07 while trying to write the expensive half, kept
here so they are not rediscovered:

* **A falling exposed-node count is NOT evidence a boundary was drawn.** Opening
  a backdrop by adding `.active` -- the way every `show*Modal()` does -- gave
  `exposed 149 -> 88` on `session-setup` with **`hiddenCount() == 0`**. The
  overlay covers content whether or not a boundary exists, and a class toggle
  leaves focus in the page, which the helper refuses to hide around (#422). So
  the walk declined everything and the fall was pure CSS. **`hiddenCount()` is
  the instrument; the exposed count alone is not.** A real scenario has to drive
  a real invoker.
* **The entry form's live region is created at RUNTIME and was absent in a
  default test session.** #420 lists `question_entry.html` as affected, read
  from source: `relation_proposals.js` appends a `role="status"` into
  `#explanation-relations` inside the gated container. Rendered, with no
  relations runtime present, that region did not exist -- so the page's markup
  carries the risk while a default build may not realise it. That is exactly the
  "same mechanism vs same consequence" distinction #420 raised about itself.
"""
from __future__ import annotations

import pathlib
import re

HTML_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "web" / "html"

LIVE_REGION = re.compile(r'aria-live|role="status"|role="alert"|role="log"')

#: Pages whose markup declares a modal surface AND carries a live region, so
#: #420's precondition is present. Being on this list is not a defect -- the
#: helper handles it correctly since `f5bf08d`. Being *absent from it while
#: qualifying* is the thing that went unnoticed twice.
KNOWN_AT_RISK = {
    "question_entry.html",
    "session_setup.html",
    "tree_editor.html",
}


def _qualifying_pages() -> set[str]:
    found = set()
    for page in sorted(HTML_DIR.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        if "data-modal-surface" in text and LIVE_REGION.search(text):
            found.add(page.name)
    return found


def test_every_page_with_a_modal_and_a_live_region_is_known() -> None:
    """A new one means somebody should count its AX tree with a modal open."""
    new = _qualifying_pages() - KNOWN_AT_RISK
    assert not new, (
        "these pages now declare a modal surface AND carry a live region, which "
        f"is #420's precondition: {sorted(new)}. That is not automatically a "
        "defect -- the helper handles it since f5bf08d -- but it has never been "
        "measured on them. Count exposed accessibility nodes with one of their "
        "modals open, driven by a REAL invoker (a class toggle is not faithful; "
        "see this module's docstring), then add the page here."
    )


def test_the_list_has_not_gone_stale() -> None:
    """A page that stops qualifying must leave the list.

    Without this the set silently becomes a historical record, and a reader
    would take it as the current at-risk surface. Same reason an exemption list
    needs a companion test asserting its entries still fail.
    """
    stale = KNOWN_AT_RISK - _qualifying_pages()
    assert not stale, (
        f"these pages no longer declare both a modal surface and a live region: "
        f"{sorted(stale)}. Remove them from KNOWN_AT_RISK so the set keeps "
        "describing the present rather than the past."
    )


def test_the_detector_would_catch_a_new_one() -> None:
    """The reader's own control.

    A source sweep whose reader is broken finds nothing and says so in the
    language of success -- measured in this repo, where an apostrophe in a
    trailing comment silently desynchronised a quote-pairing regex and the sweep
    degraded without failing. So the detector is checked against text it must
    match and text it must not.
    """
    assert LIVE_REGION.search('<div role="status"></div>')
    assert LIVE_REGION.search('<p aria-live="polite">x</p>')
    assert LIVE_REGION.search('<div role="alert">x</div>')
    assert not LIVE_REGION.search('<div role="dialog"></div>')
    assert not LIVE_REGION.search('<div class="status-bar"></div>')

    # And it must actually be finding pages, or every assertion above is
    # vacuous on a tree where the glob matched nothing.
    assert _qualifying_pages(), (
        "no page qualified at all, which means the glob or the directory is "
        "wrong rather than that the app has no modals"
    )
