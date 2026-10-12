"""How many FRAMES focus takes to follow a dialog in and out (#373, #374).

Measured on the page's own requestAnimationFrame clock, not in milliseconds.
A dropped frame on a loaded machine delays the reveal and the focus move
equally, so a frame budget stays meaningful where a wall-clock budget would
turn into the flake #373 was. CLAUDE.md already warns that wall-clock figures
from a loaded run are inflated.

Why a latency at all, rather than "wait until focus is inside": that wait
passes against the defect. Before #374, focus DID arrive -- about 20 frames
(330-360 ms) after the dialog appeared, by the helper's settle pass -- and
for that whole window it sat on the control behind the dialog. A real Enter
key-repeat in the window activated that control while the dialog was open.
"""
from __future__ import annotations

import json

from wimi_test.page import WimiPage

#: Frames allowed between "the surface is visible" and "focus is inside it",
#: and between "the surface is gone" and "focus is back on the opener". The
#: defect measured ~20; a few frames is the honest cost of observing a style
#: change one frame late plus a sweep in the next.
FRAME_BUDGET = 4


def start_timeline(page: WimiPage, surface: str, opener: str, *, ms: int = 2500) -> None:
    """Record one row per animation frame, from now, for ``ms`` milliseconds."""
    page.eval_js(
        "(() => { const sel = %s, op = %s; window.__mf = [];"
        " const t0 = performance.now(); let i = 0;"
        " const tick = () => { const s = document.querySelector(sel);"
        "  const a = document.activeElement;"
        "  window.__mf.push({i: i++,"
        "   vis: !!(s && s.checkVisibility({checkVisibilityCSS: true})),"
        "   inside: !!(s && a && s.contains(a)),"
        "   onOpener: !!(a && a.matches && a.matches(op)),"
        "   focus: a ? (a.getAttribute('data-testid') || a.tagName) : null});"
        "  if (performance.now() - t0 < %d) requestAnimationFrame(tick); };"
        " requestAnimationFrame(tick); })()"
        % (json.dumps(surface), json.dumps(opener), ms))


def read_timeline(page: WimiPage) -> list[dict]:
    return json.loads(page.eval_js("JSON.stringify(window.__mf || [])"))


def frames_until(frames: list[dict], start_key: str, start_val: bool,
                 end_key: str) -> tuple[int | None, int | None]:
    """(frame the start condition first held, frames from there until
    ``end_key`` first holds), or Nones when either never happened."""
    start = next((f['i'] for f in frames if f[start_key] is start_val), None)
    if start is None:
        return None, None
    end = next((f['i'] for f in frames if f['i'] >= start and f[end_key]), None)
    return start, (None if end is None else end - start)


def wait_for(page: WimiPage, expression: str, *, what: str, tries: int = 60) -> None:
    for _ in range(tries):
        if page.eval_js(expression):
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"timed out waiting for {what}: {expression}")


def changes(frames: list[dict]) -> list[str]:
    """The timeline with repeated rows dropped, for a failure message."""
    out, prev = [], None
    for f in frames:
        key = (f['vis'], f['inside'], f['onOpener'], f['focus'])
        if key != prev:
            out.append(f"#{f['i']} vis={f['vis']} focus={f['focus']}")
            prev = key
    return out
