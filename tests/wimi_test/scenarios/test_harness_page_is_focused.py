"""Harness: the page under test is treated as focused, across navigations.

On native macOS the WIMI window is not the key window during a run -- the
terminal that launched pytest is -- so ``document.hasFocus()`` was false and
Chromium never matched CSS ``:focus``. Every tooltip that opens on keyboard
focus failed to open, with the element genuinely holding focus. Offscreen
windows are always focused, so Linux never saw it. The session now turns on
``Emulation.setFocusEmulationEnabled`` when it attaches its tab
(``wimi_test/session.py``, step 4b).

This pins the two properties a scenario relies on: the document reports
focus, and ``:focus`` matches a focused element -- on the first page and
again after a goto, because a setting that did not survive navigation would
help only whichever page a scenario happened to open first.

On a focused window (offscreen, or a native window that is frontmost) this
passes with or without the call, so it is not a red test on Linux; the
positive control is the native Mac run recorded in the PR.

Markers / fixtures: ``@pytest.mark.regression``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage

PROBE = """(() => {
  const b = document.createElement('button');
  b.textContent = 'focus probe';
  document.body.appendChild(b);
  b.focus();
  const out = {
    hasFocus: document.hasFocus(),
    active: document.activeElement === b,
    matchesFocus: b.matches(':focus'),
  };
  b.remove();
  return JSON.stringify(out);
})()"""


def _probe(page: WimiPage) -> dict:
    return json.loads(page.eval_js(PROBE))


@pytest.mark.regression
def test_the_page_is_focused_and_stays_focused_across_a_goto(wimi_page: WimiPage) -> None:
    wimi_page.goto("dashboard")
    first = _probe(wimi_page)
    assert first == {"hasFocus": True, "active": True, "matchesFocus": True}, (
        f"on the first page: {first}. hasFocus false means the harness's focus "
        "emulation is off, and every :focus tooltip scenario fails on native macOS")

    wimi_page.goto("settings")
    second = _probe(wimi_page)
    assert second == {"hasFocus": True, "active": True, "matchesFocus": True}, (
        f"after a goto: {second}. The emulation did not survive navigation")
