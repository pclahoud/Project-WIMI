"""The two chart lists must name the same charts (#604).

A chart on the analytics dashboard is named in **two** places:

* ``CHART_SELECTORS`` in ``analytics_dashboard.js`` -- where the section lives
  on the page. Read by the per-exam visibility pass, by the student-wide
  settings pass, and (through ``Object.keys(...).filter(...)``) by the
  ``summary`` settings group.
* ``CHART_DEFINITIONS`` in ``settings.js`` -- the key, the label the student
  reads, and whether the chart is dimension-only. ``renderChartToggles``
  builds the tick list from it.

**Neither derives from the other and nothing kept them in sync.** They were
identical by care, 12 keys each, when this test was written -- which is also
the moment the invariant was most likely to break, because #604 was adding the
thirteenth.

Either direction fails silently, which is why this is a test rather than a
convention:

* a key in ``CHART_SELECTORS`` only -- the section cannot be switched off
  per exam. No tick, no error, and it is still hidden by the ``summary``
  group, so it *half* works.
* a key in ``CHART_DEFINITIONS`` only -- a tick the student can press that
  hides nothing. It saves, it reloads, it reports success.

The second is the worse one and the harder to notice: #504's whole subject was
settings that were stored and read by nothing.

This is a source check for the same reason ``test_web_local_date.py`` is: the
lists are JavaScript object literals, there is no build step, and a scenario
would have to open two pages to compare them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "src" / "web" / "js" / "analytics_dashboard.js"
SETTINGS = ROOT / "src" / "web" / "js" / "settings.js"


def _selector_keys(src: str) -> list[str]:
    """The keys of `const CHART_SELECTORS = { ... }`, read as one block."""
    m = re.search(r"const CHART_SELECTORS\s*=\s*\{(.*?)\n\};", src, re.S)
    assert m, "CHART_SELECTORS has moved or changed shape; this reader is stale"
    return re.findall(r"^\s*'([a-z_]+)'\s*:", m.group(1), re.M)


def _definition_keys(src: str) -> list[str]:
    """The `key:` values of `this.CHART_DEFINITIONS = [ ... ]`."""
    m = re.search(r"CHART_DEFINITIONS\s*=\s*\[(.*?)\n\s*\];", src, re.S)
    assert m, "CHART_DEFINITIONS has moved or changed shape; this reader is stale"
    return re.findall(r"key:\s*'([a-z_]+)'", m.group(1))


def test_the_two_lists_name_the_same_charts():
    """The headline, in both directions and with the offenders named."""
    selectors = _selector_keys(DASHBOARD.read_text(encoding="utf-8"))
    definitions = _definition_keys(SETTINGS.read_text(encoding="utf-8"))

    only_page = sorted(set(selectors) - set(definitions))
    only_settings = sorted(set(definitions) - set(selectors))

    assert not only_page, (
        f"on the page but with no settings tick: {only_page}. Add it to "
        f"CHART_DEFINITIONS in settings.js with the label the student reads, "
        f"or the section cannot be switched off per exam")
    assert not only_settings, (
        f"a settings tick that hides nothing: {only_settings}. Add it to "
        f"CHART_SELECTORS in analytics_dashboard.js with the selector of the "
        f"section it hides -- a switch over nothing is #504's defect")


def test_neither_list_is_empty_and_the_readers_still_work():
    """The control.

    Both readers are regexes over a JavaScript literal, and a regex that
    matches nothing would make the test above pass by comparing two empty
    sets. #322's sweep came back empty and skipped 18 cases with no error;
    the same failure is available here for free.
    """
    selectors = _selector_keys(DASHBOARD.read_text(encoding="utf-8"))
    definitions = _definition_keys(SETTINGS.read_text(encoding="utf-8"))

    assert len(selectors) >= 12, (
        f"CHART_SELECTORS read {len(selectors)} keys; it had 12 before #604 "
        f"added one, so the reader is probably broken rather than the list "
        f"shrinking")
    assert len(definitions) >= 12, (
        f"CHART_DEFINITIONS read {len(definitions)} keys; same reasoning")
    assert len(set(selectors)) == len(selectors), (
        f"a duplicate key in CHART_SELECTORS: {selectors}")
    assert len(set(definitions)) == len(definitions), (
        f"a duplicate key in CHART_DEFINITIONS: {definitions}")


def test_every_selector_matches_something_in_the_page():
    """A selector naming no element hides nothing, and says nothing about it.

    `applyPreferenceVisibility` does `querySelector(selector)` and skips a
    `null` -- so a typo'd or renamed selector is a switch the student can set
    which silently has no effect. That is the same shape as the tick with no
    section, reached from the other side.

    Checked against the markup rather than a live page: these are all class or
    id selectors on static sections.
    """
    page = (ROOT / "src" / "web" / "html" / "analytics_dashboard.html").read_text(
        encoding="utf-8")
    src = DASHBOARD.read_text(encoding="utf-8")
    block = re.search(r"const CHART_SELECTORS\s*=\s*\{(.*?)\n\};", src, re.S)
    pairs = re.findall(r"^\s*'([a-z_]+)'\s*:\s*'([^']+)'", block.group(1), re.M)
    assert pairs, "the selector reader found no pairs"

    missing = []
    for key, selector in pairs:
        token = selector.lstrip('.#')
        if selector.startswith('#'):
            present = f'id="{token}"' in page
        else:
            present = f'class="{token}' in page or f' {token}"' in page or \
                f'"{token}"' in page or f' {token} ' in page
        if not present:
            missing.append((key, selector))

    assert not missing, (
        f"these CHART_SELECTORS entries match nothing in "
        f"analytics_dashboard.html, so their settings switch does nothing: "
        f"{missing}")
