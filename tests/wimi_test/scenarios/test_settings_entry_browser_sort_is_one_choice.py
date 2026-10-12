"""Regression: the entry browser's default sort direction does something (#504).

The entry browser reads ONE value, ``entry_review_default_sort_field``, and
it already carries the direction (``date_desc``). Settings offered that
field with the direction baked into each option *and* a separate Default Sort
Direction that nothing read. Now the page shows the two halves -- Date or
Difficulty, Ascending or Descending -- and stores them joined, which is the
value the browser has always read. ``entry_browser.js`` is untouched.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FRESH = "typeof window.__wimiPrevDoc === 'undefined' && typeof window.api === 'object'"
RELEASED = "!document.querySelector('[data-page-gated][inert]')"
FIELD = "document.getElementById('entry_review_default_sort_field').value"
DIRECTION = "document.getElementById('entry_review_default_sort_direction').value"


def _poll(page: WimiPage, read, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _open_settings(page: WimiPage) -> None:
    page.eval_js("window.__wimiPrevDoc = true")
    page.goto("settings")
    assert _poll(page, lambda: page.eval_js(FRESH), True) is True
    assert _poll(page, lambda: page.eval_js(RELEASED), True) is True, "settings stayed gated"


def _choose(page: WimiPage, select_id: str, value: str) -> None:
    page.eval_js(
        f"(() => {{ const el = document.getElementById('{select_id}');"
        f" el.value = '{value}'; el.dispatchEvent(new Event('change', {{bubbles: true}})); }})()")


@pytest.mark.slow
@pytest.mark.regression
def test_the_direction_is_stored_where_the_browser_reads_it(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.update_settings(entry_review_default_sort_field="date_desc",
                       entry_review_default_sort_direction="desc")
    _open_settings(wimi_page)
    assert (wimi_page.eval_js(FIELD), wimi_page.eval_js(DIRECTION)) == ("date", "desc")

    _choose(wimi_page, "entry_review_default_sort_field", "difficulty")
    _choose(wimi_page, "entry_review_default_sort_direction", "asc")
    wimi_page.eval_js("document.getElementById('saveBtn').click()")

    def stored():
        p = db.get_preferences()
        return (p.entry_review_default_sort_field, p.entry_review_default_sort_direction)

    assert _poll(wimi_page, stored, ("difficulty_asc", "asc")) == ("difficulty_asc", "asc"), (
        f"the browser reads entry_review_default_sort_field; it holds {stored()!r}")

    _open_settings(wimi_page)
    assert (wimi_page.eval_js(FIELD), wimi_page.eval_js(DIRECTION)) == ("difficulty", "asc"), (
        "a fresh visit must show the saved pair")


@pytest.mark.slow
@pytest.mark.regression
def test_the_legacy_default_is_shown_as_what_the_browser_does_with_it(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The column's default, "answered_incorrectly_date", is no option; the
    browser falls back to newest-first for it, so that is what is shown."""
    db = wimi_session.user.db
    db.update_settings(entry_review_default_sort_field="answered_incorrectly_date",
                       entry_review_default_sort_direction="asc")

    _open_settings(wimi_page)

    assert (wimi_page.eval_js(FIELD), wimi_page.eval_js(DIRECTION)) == ("date", "desc")
