"""Measuring keyboard reach and accessible names from a scenario (#304-#306).

Why this exists, and why none of it is a DOM read
-------------------------------------------------
Three filed bugs in this family share one property: **every obvious way to
test them passes against the unfixed page.**

* ``el.click()`` fires a click handler on an element that is not focusable
  and not in the tab order, so a scenario built on it proves nothing about
  whether a keyboard user can reach the thing. CLAUDE.md records this under
  *The Entry Form Is Inert Until It Is Ready* (#114, #285). So the only
  honest instrument for "can this be reached" is a real ``Tab`` press
  through ``Input.dispatchKeyEvent``, which is what :func:`tab_walk` does.

* An accessible *name* read off ``aria-label`` is the attribute that stays
  correct in exactly the cases where the name is wrong anyway. Chromium's
  own computation is the thing assistive tech receives, and CDP will hand
  it over per element — ``DOM.querySelector`` for the node, then
  ``Accessibility.getPartialAXTree``. That gives **``nameFrom``**, which is
  what makes #305 testable at all: ``#tree-search-input`` computes the name
  ``'Filter subjects...'`` from ``nameFrom: ['placeholder']``. A test
  asserting "the name is not empty" is **green on the unfixed page**; a test
  asserting the name does not come from a placeholder is not. Measured on
  Linux at c8a904b, before any fix.

* A ``title`` attribute does not override visible content, so an icon-only
  button computes its name from the glyph: ``.tree-action-btn`` measured
  ``name: '+'``, ``nameFrom: ['contents', 'attribute']`` — the ``title`` is
  *present as a source* and loses. That is the whole of #306, and it is
  invisible to any check that merely looks for a ``title``.

Four measured facts worth not re-deriving
-----------------------------------------
``getPartialAXTree`` needs the ``Accessibility`` **and** ``DOM`` domains
enabled; :func:`enable` does both.

**The name's source list includes the losers.** Chromium reports every
source it considered that had a value and marks the beaten ones
``superseded``, so a fixed input reports ``['attribute', 'placeholder']``
and a test reading the raw list calls the fix a bug. :func:`ax_node`
filters; see its docstring.

**An ``<iframe>`` never matches ``:focus``.** Focusing TinyMCE's editing
iframe makes it ``document.activeElement`` in the parent document, yet
``f.matches(':focus')`` is ``false`` and ``f.matches(':focus-visible')`` is
``false`` — while ``.tox-edit-area:focus-within`` is ``true``. So a focus
ring for a rich-text editor has to hang off ``:focus-within`` on an
ancestor; ``iframe:focus-visible`` is a rule that can never match. Measured
before being relied on, because the natural guess is the one that silently
does nothing.

**And a CDP Tab into an iframe is weaker still.** After a synthetic ``Tab``
that lands on the iframe, ``document.activeElement`` IS the iframe and
*every* selector is false — ``:focus``, ``:focus-visible`` and
``:focus-within`` on the iframe, ``:focus-within`` and ``:has(:focus)`` on
the wrapper, ``body:has(iframe:focus)``. ``iframe.focus()`` from script, on
the same page, gives ``:focus-within``. The key dispatch moves the active
element without setting the flags the style engine reads, which is a
property of driving a frame over CDP rather than of the product. So an
iframe focus ring has to be driven programmatically and "a real Tab lands
here" has to be a separate assertion; they cannot be combined here.
"""
from __future__ import annotations

import json
from typing import Any

from wimi_test.page import WimiPage

# ---------------------------------------------------------------------------
# Accessible names, as Chromium computes them
# ---------------------------------------------------------------------------


def enable(page: WimiPage) -> None:
    """Turn on the two CDP domains a per-element AX read needs."""
    page.tab.Accessibility.enable()
    page.tab.DOM.enable()


def ax_node(page: WimiPage, selector: str, *, nth: int = 0) -> dict:
    """What assistive tech is handed for ``selector``.

    Returns ``{"found", "role", "name", "ignored", "name_from",
    "all_sources"}``.

    **``name_from`` is the WINNING source only.** Chromium reports every
    source it considered that had a value and marks the losers
    ``superseded``, so an input carrying both an ``aria-label`` and a
    ``placeholder`` reports *both* -- and a test reading the raw list
    cannot tell a fixed control from a broken one. Measured on
    ``#tree-search-input`` after adding the label: name
    ``'Filter subjects'``, sources ``['attribute', 'placeholder']``, with
    the placeholder superseded. Filtering is therefore the difference
    between an assertion that works and one that reports the fix as the
    bug. ``all_sources`` keeps the unfiltered list for failure messages.

    Source types worth knowing: ``'attribute'`` (``aria-label``, and
    ``title`` as a last resort), ``'contents'`` (visible text -- #306's
    glyph problem), ``'placeholder'`` (#305's), ``'relatedElement'``
    (a ``<label for>``).

    ``nth`` selects among matches; it goes through ``querySelectorAll`` in
    the page and marks the chosen element, because ``DOM.querySelector``
    takes no index.
    """
    marker = "__a11yProbeTarget"
    marked = page.eval_js(
        "(() => { const els = document.querySelectorAll(%s);"
        " document.querySelectorAll('[%s]').forEach(e =>"
        "   e.removeAttribute('%s'));"
        " const el = els[%d]; if (!el) return false;"
        " el.setAttribute('%s', '1'); return true; })()"
        % (json.dumps(selector), marker, marker, nth, marker)
    )
    missing = {"found": False, "role": None, "name": None,
               "ignored": None, "name_from": [], "all_sources": []}
    if marked is not True:
        return dict(missing)

    tab = page.tab
    doc = tab.DOM.getDocument()
    hit = tab.DOM.querySelector(nodeId=doc["root"]["nodeId"],
                                selector=f"[{marker}]")
    node_id = hit.get("nodeId")
    if not node_id:
        return dict(missing)

    partial = tab.Accessibility.getPartialAXTree(nodeId=node_id,
                                                 fetch_relatives=False)
    nodes = partial.get("nodes") or []
    if not nodes:
        return dict(missing)
    node = nodes[0]
    name_obj = node.get("name") or {}
    raw = [s for s in (name_obj.get("sources") or []) if s.get("value")]
    return {
        "found": True,
        "role": (node.get("role") or {}).get("value"),
        "name": name_obj.get("value"),
        "ignored": bool(node.get("ignored")),
        "name_from": [s.get("type") for s in raw if not s.get("superseded")],
        "all_sources": [
            s.get("type") + ("(superseded)" if s.get("superseded") else "")
            for s in raw
        ],
    }


def describe(node: dict) -> str:
    """A quotable one-liner for an assertion message."""
    if not node["found"]:
        return "not in the DOM"
    return (f"role={node['role']!r} name={node['name']!r} "
            f"name_from={node['name_from']!r} "
            f"all_sources={node.get('all_sources')!r} "
            f"ignored={node['ignored']}")


# ---------------------------------------------------------------------------
# Real keyboard input
# ---------------------------------------------------------------------------

#: ``key`` -> ``(windowsVirtualKeyCode, text)``. ``text`` is ``None`` for
#: keys that produce no character; passing one for ``Tab`` inserts a tab.
_KEYS: dict[str, tuple[int, str | None]] = {
    "Tab": (9, None),
    "Enter": (13, "\r"),
    " ": (32, " "),
    "F2": (113, None),
    "Escape": (27, None),
    "ArrowRight": (39, None),
    "ArrowDown": (40, None),
}


def real_key(page: WimiPage, key: str, *, settle_ms: int = 40) -> None:
    """Press ``key`` for real, through CDP.

    ``rawKeyDown`` plus ``keyUp`` is what the browser's own default
    activation behaviour runs off, so a native ``<button>`` turns Enter and
    Space into a click without the scenario simulating one -- which is the
    point. ``el.click()`` would report success against an element that is
    not focusable at all.
    """
    code, text = _KEYS[key]
    down: dict[str, Any] = {
        "type": "keyDown" if text else "rawKeyDown",
        "key": key,
        "windowsVirtualKeyCode": code,
        "nativeVirtualKeyCode": code,
    }
    if text:
        down["text"] = text
    page.tab.Input.dispatchKeyEvent(**down)
    page.tab.Input.dispatchKeyEvent(
        type="keyUp", key=key, windowsVirtualKeyCode=code,
        nativeVirtualKeyCode=code)
    page.wait_for_timeout(settle_ms)


def real_type(page: WimiPage, text: str, *, settle_ms: int = 120) -> None:
    """Type into whatever has focus. Lands nowhere when nothing does."""
    page.tab.Input.insertText(text=text)
    page.wait_for_timeout(settle_ms)


ACTIVE_ELEMENT = """
(() => {
  const a = document.activeElement;
  if (!a || a === document.body) return JSON.stringify({tag: 'BODY'});
  const cs = getComputedStyle(a);
  const r = a.getBoundingClientRect();
  return JSON.stringify({
    tag: a.tagName,
    cls: (a.className || '').toString(),
    id: a.id || null,
    testid: a.getAttribute('data-testid'),
    role: a.getAttribute('role'),
    label: a.getAttribute('aria-label'),
    text: (a.textContent || '').trim().slice(0, 40),
    outlineStyle: cs.outlineStyle,
    outlineWidth: cs.outlineWidth,
    // Effective opacity, walking the ancestors. A ring drawn inside an
    // `opacity: 0` group is itself transparent, so an outline check alone
    // passes against a focused control nobody can see -- which is exactly
    // what the tree editor's per-row action buttons were.
    opacity: (() => {
      let el = a, o = 1;
      while (el && el.nodeType === 1) {
        o *= parseFloat(getComputedStyle(el).opacity || '1');
        el = el.parentElement;
      }
      return Math.round(o * 1000) / 1000;
    })(),
    w: Math.round(r.width * 10) / 10,
    h: Math.round(r.height * 10) / 10
  });
})()
"""


def active_element(page: WimiPage) -> dict:
    return json.loads(page.eval_js(ACTIVE_ELEMENT))


def start_tab_walk(page: WimiPage) -> None:
    """Park focus at the document start so a Tab walk is reproducible."""
    page.eval_js(
        "(() => { if (document.activeElement && document.activeElement.blur)"
        "   document.activeElement.blur();"
        " const h = document.querySelector('h1, h2, header');"
        " if (h && h.scrollIntoView) h.scrollIntoView({block: 'start'}); })()")
    page.wait_for_timeout(60)


def tab_walk(page: WimiPage, *, presses: int) -> list[dict]:
    """Press Tab ``presses`` times, recording where focus landed each time.

    Returns one entry per press. A walk that returns to ``BODY`` has wrapped
    past the end of the document, so the stops before that are the whole
    tab order -- which is how "this element is not reachable" is measured
    rather than asserted.
    """
    stops: list[dict] = []
    for _ in range(presses):
        real_key(page, "Tab")
        stops.append(active_element(page))
    return stops


def walk_to(page: WimiPage, matcher, *, presses: int = 40) -> dict | None:
    """Tab until ``matcher(stop)`` is true. Returns the stop, or ``None``.

    ``None`` means the element is **not in the tab order** -- the #304
    finding -- and callers should quote :func:`tab_walk`'s full list in the
    failure message so the reader can see what *was* reachable.
    """
    for _ in range(presses):
        real_key(page, "Tab")
        stop = active_element(page)
        if matcher(stop):
            return stop
    return None


def summarise(stops: list[dict]) -> str:
    """The tab order, short enough to put in an assertion message."""
    return " -> ".join(
        s.get("testid") or s.get("id") or
        (s["tag"] + "." + (s.get("cls") or "").split(" ")[0])
        for s in stops)


# ---------------------------------------------------------------------------
# Focus indication and target size
# ---------------------------------------------------------------------------


def has_focus_ring(stop: dict) -> bool:
    """Is there a drawn outline on the focused element, and can it be seen?

    Only the ``outline`` is read. A ``box-shadow`` ring would also be
    visible, but every site these tests cover sets ``outline: none``
    explicitly (measured: ``.sunburst-info-icon:focus``,
    ``.efficiency-info-icon:focus`` and ``.search-help-icon:focus`` all do),
    so the fix is an outline and the assertion follows the fix.

    The **opacity** term is not belt-and-braces. The tree editor's per-row
    action buttons live in a group at ``opacity: 0`` revealed on row hover,
    so a keyboard user landed on a button that was focusable, in the
    accessibility tree, and entirely invisible -- and an outline added to
    that button would have been invisible with it. A ring behind zero
    opacity is not a focus indicator, so it does not count as one here.
    """
    if stop.get("opacity") is not None and stop["opacity"] <= 0.05:
        return False
    if stop.get("outlineStyle") in (None, "none"):
        return False
    width = stop.get("outlineWidth") or "0px"
    try:
        return float(width.replace("px", "")) > 0
    except ValueError:
        return True


FOCUS_WITHIN_RING = """
(() => {
  const el = document.querySelector(%s);
  if (!el) return JSON.stringify({found: false});
  const cs = getComputedStyle(el);
  return JSON.stringify({
    found: true,
    focusWithin: el.matches(':focus-within'),
    outlineStyle: cs.outlineStyle,
    outlineWidth: cs.outlineWidth
  });
})()
"""


def focus_within_ring(page: WimiPage, selector: str) -> dict:
    """Read a ``:focus-within`` ring, for a control that is an iframe.

    See the module docstring: an ``<iframe>`` never matches ``:focus``, so
    this is the only shape of rule that can indicate focus inside one.
    """
    return json.loads(page.eval_js(FOCUS_WITHIN_RING % json.dumps(selector)))


def rect(page: WimiPage, selector: str, *, nth: int = 0) -> dict | None:
    """Rendered box of ``selector``, or ``None`` when it is not laid out."""
    raw = page.eval_js(
        "(() => { const el = document.querySelectorAll(%s)[%d];"
        " if (!el) return null; const r = el.getBoundingClientRect();"
        " return JSON.stringify({w: Math.round(r.width * 10) / 10,"
        " h: Math.round(r.height * 10) / 10}); })()"
        % (json.dumps(selector), nth)
    )
    return json.loads(raw) if raw else None
