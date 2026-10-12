"""Regression: the "Required" chip on the selected dimension tab is readable in every theme.

The selected tab is filled with ``--color-primary`` and its text is
``--text-inverse``, the colour meant for that fill. The chip inside it
re-tints its own background to ``--color-primary-bg`` but inherited the tab's
``--text-inverse``, so in a dark theme it painted dark text on a dark tint:
reported by the owner from a dark-mode screenshot of the tree editor's
dimension bar. ``--color-primary-text`` is the token made for that tint, and
``tests/test_theme_text_contrast.py`` holds that pair to AA statically; this
measures it rendered.

Each theme is stored as the student's preference and the page is loaded
fresh, because that is the only path that reproduces the report. Applying
the theme variables inside an already-loaded page does not: measured, the
in-page switch put Midnight's chip at a passing ratio while a real Midnight
load painted ``#0f172a`` on ``#1f3550``. The primary colour stored with each
theme is that theme's own ``primaryColorHex``, which Settings stores on a theme pick and the owner's
profile carries (Midnight, ``#60a5fa``).
"""

from __future__ import annotations

import json

import pytest

from _helpers.contrast import AA_BODY_TEXT, contrast_ratio, is_transparent
from _helpers.tree_details import wait_for
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

THEMES = ['default', 'midnight', 'warm_study', 'forest', 'nord', 'high_contrast']

MEASURE = """
(() => {
  const chip = document.querySelector('.dimension-tab.active .dimension-tab-badge');
  if (!chip) return null;
  const cs = getComputedStyle(chip);
  return JSON.stringify({fg: cs.color, bg: cs.backgroundColor});
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_the_selected_tabs_required_chip_clears_aa_in_every_theme(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name="Chip Contrast", exam_description="")
    exam_id = db.get_exam_context_by_name(exam.exam_name).id
    for order, name in enumerate(("Site of Care", "Physician Task", "System"), 1):
        db.create_dimension(exam_id, name, order, is_required=True)

    wimi_page.goto("tree-editor", query={"exam_id": exam_id})
    wait_for(wimi_page, "typeof WIMI_THEMES === 'object'", what="themes.js")
    primaries = json.loads(wimi_page.eval_js(
        "JSON.stringify(Object.fromEntries(Object.entries(WIMI_THEMES)"
        ".map(([k, v]) => [k, v.primaryColorHex || null])))"))

    failures = []
    for theme in THEMES:
        prefs = {"theme_name": theme}
        if primaries.get(theme):
            prefs["primary_color_hex"] = primaries[theme]
        db.update_preferences(**prefs)
        wimi_page.goto("tree-editor", query={"exam_id": exam_id})
        raw = wait_for(wimi_page, MEASURE,
                       what=f"the selected tab's Required chip under {theme}")
        # Let `.dimension-tab { transition: all }` settle before reading.
        wimi_page.wait_for_timeout(400)
        m = json.loads(wimi_page.eval_js(MEASURE))
        assert raw and not is_transparent(m["bg"]), (
            f"{theme}: the chip has no background {m!r}")
        ratio = contrast_ratio(m["fg"], m["bg"])
        if ratio < AA_BODY_TEXT:
            failures.append(f"{theme}: {m['fg']} on {m['bg']} = {ratio:.2f}:1")
    assert not failures, (
        "The selected tab's Required chip is below the "
        f"{AA_BODY_TEXT}:1 bar: {failures}. It must take --color-primary-text, "
        "the text token for the primary tint, not the tab's --text-inverse.")
