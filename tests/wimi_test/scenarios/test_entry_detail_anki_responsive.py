"""Regression: a slow Anki never freezes the window (#784 finding 5).

The plugin called AnkiConnect on the Qt main thread, so a slow answer froze
WIMI for up to ten seconds per call. Here the fake AnkiConnect waits 3 s
before every answer. While the entry's refresh is waiting, a bridge round trip
from the page -- which needs the main thread -- must come back quickly, and
the page must stay usable. The refresh still completes afterwards: that is the
positive control showing the slow call really was in flight.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.anki_entry import enable_anki, open_entry, seed, status, stock, wait_for_cards
from _helpers.anki_settings import poll_true
from tests._fake_ankiconnect import FakeAnkiConnect
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

ROUND_TRIP = ("(async () => { const t = performance.now(); await api.getUserPreferences();"
              " return performance.now() - t; })()")


@pytest.mark.slow
@pytest.mark.regression
def test_the_window_answers_while_anki_is_slow(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    world = seed(wimi_session.user.db)
    with FakeAnkiConnect() as anki:
        stock(anki)
        enable_anki(wimi_page, anki.port)
        anki.delay_s = 3.0
        open_entry(wimi_page, world['entry'].id)

        assert poll_true(wimi_page, "document.getElementById('anki-status')"
                                    ".textContent.startsWith('Checking Anki')"), status(wimi_page)
        elapsed_ms = wimi_page.eval_js(ROUND_TRIP, await_promise=True)
        still_waiting = status(wimi_page).startswith('Checking Anki')
        assert still_waiting, 'the refresh ended before the probe; nothing was measured'
        assert elapsed_ms < 1000, (
            f'a bridge round trip took {elapsed_ms:.0f} ms while Anki was slow: '
            'the main thread is blocked')
        # The page's own controls still work: the entry's heading is drawn and
        # the Refresh button is disabled rather than accepting a second press.
        assert wimi_page.eval_js("document.getElementById('anki-refresh').disabled")

        wait_for_cards(wimi_page, 2)
        assert poll_true(wimi_page, "document.getElementById('anki-status').textContent"
                                    " === 'Up to date with Anki.'", timeout_ms=20000)
