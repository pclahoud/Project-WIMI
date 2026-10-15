"""Regression: Suspend then Unsuspend sends exactly one request each.

The plugin re-bound its click handler on every render, so after one refresh a
single Suspend press suspended and then unsuspended. The panel delegates one
listener, attached once. Pressing Suspend and then Unsuspend must reach Anki as
one ``suspend`` and one ``unsuspend`` -- with the queue read back after the
unsuspend (#800 review 3) -- and the badge must follow. Focus stays on the
button the student pressed, although a press re-renders the card list.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.anki_entry import enable_anki, expand, open_entry, seed, status, stock, wait_for_cards
from _helpers.anki_settings import poll_true
from tests._fake_ankiconnect import FakeAnkiConnect
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

BUTTON = '#anki-cards .anki-card[data-card-id="101"] button[data-focus-key="suspension:101"]'
CARD = "document.querySelector('#anki-cards .anki-card[data-card-id=\"101\"]')"


def _press(page: WimiPage) -> None:
    page.locator(css=BUTTON).click()


@pytest.mark.slow
@pytest.mark.regression
def test_suspend_then_unsuspend_is_one_request_each(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    world = seed(wimi_session.user.db)
    with FakeAnkiConnect() as anki:
        stock(anki)
        enable_anki(wimi_page, anki.port)
        open_entry(wimi_page, world['entry'].id)
        wait_for_cards(wimi_page, 2)
        assert poll_true(wimi_page, "document.getElementById('anki-status').textContent"
                                    " === 'Up to date with Anki.'")
        expand(wimi_page, 101)
        # Opening the card fetches its thumbnail from Anki (#815); let that
        # finish so the request log below holds only the suspend round trips.
        assert poll_true(wimi_page, "Array.from(document.querySelectorAll('#anki-cards .anki-card"
                                    "[data-card-id=\"101\"] .anki-thumb img'))"
                                    ".every(i => i.getAttribute('src') !== null)"), status(wimi_page)
        anki.requests.clear()

        _press(wimi_page)
        assert poll_true(wimi_page, "document.getElementById('anki-status').textContent"
                                    " === 'Suspended in Anki.'"), status(wimi_page)
        assert 'Suspended' in wimi_page.eval_js(f"{CARD}.querySelector('.anki-card-head').innerText")
        assert anki.cards[101]['queue'] == -1
        assert wimi_page.eval_js("document.activeElement.dataset.focusKey") == 'suspension:101'

        _press(wimi_page)
        assert poll_true(wimi_page, "document.getElementById('anki-status').textContent"
                                    " === 'Unsuspended in Anki.'"), status(wimi_page)
        assert 'Suspended' not in wimi_page.eval_js(
            f"{CARD}.querySelector('.anki-card-head').innerText")
        assert anki.actions() == ['suspend', 'unsuspend', 'cardsInfo'], anki.actions()
        assert anki.cards[101]['queue'] == 2, 'a review card goes back to review, not new'
