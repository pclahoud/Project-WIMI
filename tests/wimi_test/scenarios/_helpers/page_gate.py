"""Reading the accessibility tree from a scenario (#127).

Why this exists
---------------
#114 gates a page with the ``inert`` attribute. ``inert`` refuses pointer and
keyboard input and **also removes the subtree from the accessibility tree**,
which is #127: for the 0.1-0.6 s the gate holds, a screen reader reads an empty
document and is told nothing about why.

Verifying that kind of fix from attributes is close to worthless. A status
region nested *inside* the gated container has the right ``role``, the right
``aria-live``, the right text and a non-zero bounding box, and is never
announced or read -- every DOM-level check of it passes. So the assertions here
go through CDP's ``Accessibility`` domain, which is what Chromium actually
hands assistive technology.

What was measured, on the entry form, bridge calls held open by
``w114_form_ready.install_slow_bridge``:

    while the gate is up    72 nodes, 71 ignored -- ONE non-ignored node,
                            the document root, and nothing else
    after release          461 nodes, 290 non-ignored: 52 buttons,
                           3 textboxes, 4 comboboxes, the headings

What this still cannot do
-------------------------
**It is not a screen reader.** It reads the tree Chromium exposes; it does not
run NVDA, VoiceOver or Orca, and it cannot observe an announcement. So:

* "the gate's text is in the accessibility tree while the form is not" is
  measured here, and is the substance of #127;
* "a live region change is spoken" is **not** measured anywhere in this repo.
  That rests on ``role="status"`` behaving as specified, and on the separate,
  deliberate decision that content already present at registration is not
  announced. Treat it as reasoned, not verified, and say so.

Written for #127 on the entry form, and kept general because #119 (settings),
#120 (session setup), #121 (tree editor) and #122 (entry browser) are the same
defect on four more pages.
"""
from __future__ import annotations

import json

from wimi_test.page import WimiPage

GATE_SELECTOR = "[data-page-gate]"

# The gated container, addressed by the pattern's own marker rather than by a
# per-page class. `.entry-page`, `.app-container` and `.session-page` are three
# different selectors for the same role, and a probe that hardcodes one can
# only ever check one page; `data-page-gated` is what every gated page
# declares, and `tests/test_page_gate_markup.py` is what keeps it honest.
GATED_SELECTOR = "[data-page-gated]"


# ---------------------------------------------------------------------------
# The gated container
# ---------------------------------------------------------------------------


def is_inert(page: WimiPage, selector: str) -> bool | None:
    """Is ``selector``'s element currently gated?

    ``None`` means the element is not in the DOM at all, which is a different
    failure from "not gated" and must not be allowed to read as one.

    Generic in the selector because the four pages that copy this pattern each
    gate a differently-named container -- ``.entry-page`` (#114),
    ``.tree-page`` (#121), ``.app-container`` (#119, #122),
    ``.session-page`` (#120). ``w114_form_ready.is_inert`` is the entry form's
    hard-coded ancestor of this and is left alone so #114's own scenarios keep
    reading exactly what they were written against.
    """
    return page.eval_js(
        "(() => { const p = document.querySelector(%s);"
        " return p ? p.hasAttribute('inert') : null; })()" % json.dumps(selector)
    )


def assert_inside_the_window(page: WimiPage, selector: str, what: str) -> None:
    """Fail loudly if the gate lifted under the probe's feet.

    Every "input was refused" assertion is only meaningful while the page is
    still gated. An assertion made outside the window is worse than no
    assertion at all, because it passes against an unfixed page: so this says
    which of the two things went wrong rather than letting a race read as a
    confident result. Lifted from ``w114_form_ready.assert_still_in_window``,
    which is the entry-form-shaped version of the same guard.
    """
    state = is_inert(page, selector)
    if state is True:
        return
    if state is None:
        raise AssertionError(
            f"{what}: {selector} is not in the DOM, so there is no gated "
            f"container to measure. The page did not render, or the "
            f"container was renamed.")
    raise AssertionError(
        f"{what}: {selector} is not inert. Either the page was handed over "
        f"part-way through the probe -- raise the slow-bridge delay rather "
        f"than weakening the assertion -- or it never gated itself at all, "
        f"i.e. the `inert` attribute is missing from the markup and the bug "
        f"is unfixed.")


# ---------------------------------------------------------------------------
# The accessibility tree
# ---------------------------------------------------------------------------


def enable_accessibility(page: WimiPage) -> None:
    """Turn the CDP ``Accessibility`` domain on. Call once, before reading."""
    page.tab.Accessibility.enable()


def ax_snapshot(page: WimiPage) -> dict:
    """What assistive technology would be handed, right now.

    Returns ``{"total", "ignored", "exposed", "names", "roles"}``.
    ``exposed`` counts nodes that are NOT ignored -- the ones a screen reader
    can reach. ``names`` is every non-ignored accessible name, which is what
    a reader would actually say.
    """
    tree = page.tab.Accessibility.getFullAXTree()
    nodes = tree.get("nodes", [])
    names: list[str] = []
    roles: dict[str, int] = {}
    exposed = 0
    for node in nodes:
        if node.get("ignored"):
            continue
        exposed += 1
        role = (node.get("role") or {}).get("value") or "?"
        roles[role] = roles.get(role, 0) + 1
        name = (node.get("name") or {}).get("value")
        if name:
            names.append(str(name))
    return {
        "total": len(nodes),
        "ignored": len(nodes) - exposed,
        "exposed": exposed,
        "names": names,
        "roles": roles,
    }


def ax_mentions(snapshot: dict, fragment: str) -> bool:
    """Is ``fragment`` in any accessible name a reader could reach?"""
    lowered = fragment.lower()
    return any(lowered in name.lower() for name in snapshot["names"])


def ax_summary(snapshot: dict) -> str:
    """A short, quotable description for an assertion message."""
    return (
        f"{snapshot['exposed']} exposed of {snapshot['total']} nodes; "
        f"roles={snapshot['roles']}; names={snapshot['names'][:12]}"
    )


# ---------------------------------------------------------------------------
# The gate element
# ---------------------------------------------------------------------------


GATE_STATE = """
(() => {
  const gate = document.querySelector('[data-page-gate]');
  if (!gate) return JSON.stringify({present: false});
  return JSON.stringify({
    present: true,
    text: (gate.textContent || '').trim(),
    role: gate.getAttribute('role'),
    live: gate.getAttribute('aria-live'),
    state: gate.getAttribute('data-gate-state'),
    announced: gate.getAttribute('data-gate-announced'),
    // The one thing that matters and that no other check can see: whether
    // this element is itself inside something `inert`. `closest('[inert]')`
    // finds the attribute on self or any ancestor.
    insideInert: gate.closest('[inert]') !== null,
    // opacity:0 is deliberate -- it keeps the node in the accessibility tree
    // while hiding it from sight. display:none or visibility:hidden would
    // remove it, which is the bug.
    display: getComputedStyle(gate).display,
    visibility: getComputedStyle(gate).visibility,
    pointerEvents: getComputedStyle(gate).pointerEvents,
    opacity: getComputedStyle(gate).opacity
  });
})()
"""

# The sighted half. `.page-gate` is transparent at rest and animates to
# opacity 1 after a 250 ms delay, so a warm load never flashes a banner. These
# two expressions are what a scenario polls on: a token that does not resolve
# or an animation that never fires both show up here and nowhere else.
GATE_IS_VISIBLE = (
    "(() => { const g = document.querySelector('[data-page-gate]');"
    " return !!g && getComputedStyle(g).opacity === '1'; })()"
)
GATE_IS_TRANSPARENT = (
    "(() => { const g = document.querySelector('[data-page-gate]');"
    " return !!g && getComputedStyle(g).opacity === '0'; })()"
)


def gate_state(page: WimiPage) -> dict:
    return json.loads(page.eval_js(GATE_STATE))


def assert_gate_can_be_heard(state: dict, *, where: str) -> None:
    """Every precondition for the gate being audible at all, in one place."""
    assert state["present"], (
        f"{where}: no [data-page-gate] element on the page. The gated "
        f"container is removed from the accessibility tree by `inert`, so "
        f"without this element there is nothing for a screen reader to read "
        f"and nothing to announce the handover (#127)."
    )
    assert state["insideInert"] is False, (
        f"{where}: the [data-page-gate] element is itself inside an `inert` "
        f"subtree, so it is removed from the accessibility tree along with "
        f"everything else -- unannounced and unreadable, with every "
        f"DOM-level check of it still passing (#127)."
    )
    assert state["role"] == "status" or state["live"] in {"polite", "assertive"}, (
        f"{where}: the gate is not a live region (role={state['role']!r}, "
        f"aria-live={state['live']!r}), so changing its text announces "
        f"nothing (#127)."
    )
    assert state["display"] != "none" and state["visibility"] != "hidden", (
        f"{where}: the gate is hidden with display={state['display']!r} / "
        f"visibility={state['visibility']!r}, both of which remove it from "
        f"the accessibility tree. Hide it with opacity, which does not "
        f"(#127)."
    )


# ---------------------------------------------------------------------------
# The gated container, generically (#119, #120)
# ---------------------------------------------------------------------------
#
# These three are the per-page half of what `w114_form_ready.py` holds for the
# entry form (`is_inert`, `wait_for_form_ready`, `assert_still_in_window`),
# written against `[data-page-gated]` and a DOM attribute instead of against
# `.entry-page` and `EntryState`. That matters beyond tidiness: a page gate is
# the absence of an attribute, and a probe that waits on a page's own JS flag
# is waiting on the *second* thing a correct implementation clears. Reading the
# attribute reads the gate itself.


def is_gated(page: WimiPage) -> bool:
    """Is the page's gated container still refusing input?"""
    return page.eval_js(
        "(() => { const p = document.querySelector('[data-page-gated]');"
        " return p ? p.hasAttribute('inert') : null; })()"
    ) is True


def wait_for_release(page: WimiPage, *, timeout_ms: int = 60000,
                     step_ms: int = 25) -> None:
    """Block until the gate lifts, and say which failure it was if it does not.

    A page that never releases is a far worse bug than the one the gate fixes
    (#114's rule), so this distinguishes "still gated" from "never gated at
    all" -- the second would mean the `inert` attribute had been dropped from
    the markup, which no other assertion here would notice.
    """
    waited = 0
    while waited < timeout_ms:
        gated = page.eval_js(
            "(() => { const p = document.querySelector('[data-page-gated]');"
            " return p ? p.hasAttribute('inert') : null; })()")
        if gated is False:
            return
        if gated is None:
            raise AssertionError(
                "there is no [data-page-gated] container on this page, so it "
                "never gated itself -- the `inert` attribute or the marker "
                "has been dropped from the markup (#114, #119, #120)")
        page.wait_for_timeout(step_ms)
        waited += step_ms
    raise AssertionError(
        f"the page was still gated after {timeout_ms} ms. Its release "
        f"function is not being reached -- it belongs in a `finally` and on "
        f"every early return, because a permanently gated page is far worse "
        f"than the bug the gate fixes (#114)")


def assert_still_gated(page: WimiPage, what: str) -> None:
    """Fail loudly if the load window closed under the probe's feet.

    Every "input was refused" assertion is only meaningful while the page is
    still gated. Checked on both sides of each gesture so a race produces this
    message rather than a confident, wrong one.
    """
    if is_gated(page):
        return
    raise AssertionError(
        f"{what}: the page is no longer gated, so what follows would be "
        f"measuring the wrong state. Raise the bridge delay rather than "
        f"weakening the assertion -- an assertion made outside the window is "
        f"worse than no assertion at all. (If the page was never gated, this "
        f"is #119/#120 unfixed: `inert` missing from the markup.)")
