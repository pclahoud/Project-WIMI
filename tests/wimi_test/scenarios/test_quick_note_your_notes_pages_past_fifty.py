"""#848 Wave 2a: *Your notes* never cuts the list off and calls the page the
total (PR #864 round 1, finding 3).

Decision 3 made a free note's subject tag optional on the strength that Your
notes keeps an untagged note reachable, and chapter 32 says the tab lists
every note on its own. The first build asked ``listFreeNotes`` for 50, drew
no sign that anything was missing, and wrote the truncated length into the
footer and the tab count -- so a student with 51 free notes read "50 notes on
their own" under a badge of 50, and the 51st was reachable from nowhere.

The dialog now asks for one row past its page: a longer answer means the
list goes on, the footer reads *Showing the newest 50 notes on their own*,
the tab says ``50+`` and a **Show more** button draws the next page. When
the answer fits, the footer and the tab state the real total and the button
is gone.

Seeded with 53 free notes as rows (the shape ``test_free_notes.py`` uses).
The positive control is the first page itself: exactly 50 rows, so the cap
is really in force before the assertions about what the dialog says of it
mean anything.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import (
    free_notes, open_form, seed_entry, seed_free_note, wait_dialog_open,
)
from _helpers.w114_form_ready import poll

SEEDED = 53
PAGE = 50

ROW_IDS = (
    "JSON.stringify(Array.from(document.querySelectorAll('.qn-row'))"
    ".map(r => Number(r.dataset.noteId)))"
)
ROW_COUNT = "document.querySelectorAll('.qn-row').length"
TAB_COUNT = (
    "(() => { const c = document.querySelector('[data-testid=\"quick-note-list-count\"]');"
    " return c && !c.hidden ? c.textContent.trim() : null; })()"
)
FOOTER = "document.querySelector('[data-testid=\"quick-note-footer-text\"]').textContent.trim()"
MORE_VISIBLE = (
    "(() => { const b = document.querySelector('[data-testid=\"quick-note-show-more\"]');"
    " return !!b && b.checkVisibility({checkVisibilityCSS: true}); })()"
)


@pytest.mark.slow
@pytest.mark.regression
def test_your_notes_says_when_there_are_more_and_shows_them(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    world = seed_entry(db, name="QNP")
    for i in range(SEEDED):
        seed_free_note(db, f"<p>QNP note {i + 1:02d}</p>")
    all_ids = {r["id"] for r in free_notes(db)}
    assert len(all_ids) == SEEDED

    open_form(wimi_page, world["session_id"], world["entry_id"])
    wimi_page.locator(testid="entry-form-quick-note-button").click()
    wait_dialog_open(wimi_page)
    wimi_page.locator(testid="quick-note-tab-list").click()
    assert poll(wimi_page, f"{ROW_COUNT} > 0", timeout_ms=10000), (
        "the Your notes list never rendered a row")

    # ---- Assert: one page, and the dialog says it is a page ------------
    assert wimi_page.eval_js(ROW_COUNT) == PAGE, (
        f"the control is void: the first page drew {wimi_page.eval_js(ROW_COUNT)} rows, not {PAGE}")
    assert wimi_page.eval_js(FOOTER) == f"Showing the newest {PAGE} notes on their own", (
        f"the footer states the page as the total: {wimi_page.eval_js(FOOTER)!r}")
    assert wimi_page.eval_js(TAB_COUNT) == f"{PAGE}+", (
        f"the tab count states the page as the total: {wimi_page.eval_js(TAB_COUNT)!r}")
    assert wimi_page.eval_js(MORE_VISIBLE) is True, "there is no way to reach the rest"

    # ---- Act: Show more ------------------------------------------------
    wimi_page.locator(testid="quick-note-show-more").click()
    assert poll(wimi_page, f"{ROW_COUNT} === {SEEDED}", timeout_ms=10000), (
        f"Show more drew {wimi_page.eval_js(ROW_COUNT)} rows, not {SEEDED}")

    # ---- Assert: every note is reachable, and the total is now real ----
    shown = json.loads(wimi_page.eval_js(ROW_IDS))
    assert len(shown) == len(set(shown)) == SEEDED, f"rows repeat or are missing: {shown!r}"
    assert set(shown) == all_ids, (
        f"the list does not hold every free note: missing {sorted(all_ids - set(shown))!r}, "
        f"extra {sorted(set(shown) - all_ids)!r}")
    assert wimi_page.eval_js(FOOTER) == f"{SEEDED} notes on their own"
    assert wimi_page.eval_js(TAB_COUNT) == str(SEEDED)
    assert wimi_page.eval_js(MORE_VISIBLE) is False, (
        "Show more is still offered with nothing left to show")
