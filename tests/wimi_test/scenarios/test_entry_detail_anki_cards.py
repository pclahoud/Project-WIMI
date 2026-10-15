"""Regression: the entry page's Anki section, against a real HTTP server.

The section is drawn from the cache and refreshed on the worker when stale. A
never-fetched entry is stale, so opening it asks the fake AnkiConnect and then
draws two cards. In card mode the review-derived figures are labelled
*estimated* and Anki's factor reads as Ease (owner decision 11); in note mode
the two cards of one note are one block, and the per-card figures are left
out (decision 10).

The negative arms: with Anki switched off the section stays hidden (its
computed display, not just its attribute), and with Anki closed after a fetch
a refresh leaves the cached cards on screen and says so (#784 finding 1, seen
through the page). The lightbox backdrop's computed display is read at load as
well: a class rule beating ``hidden`` painted the calendar's dialogs at load
with every static sweep green (#778).

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.anki_entry import (
    enable_anki, expand, open_entry, seed, set_prefs, status, stock, wait_for_cards,
)
from _helpers.anki_settings import poll_true
from tests._fake_ankiconnect import FakeAnkiConnect
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _section_shown(page: WimiPage) -> bool:
    """What paints, not what the attribute says: a class rule's display beats
    ``hidden`` (#778), and reading ``.hidden`` first made a mutant that dropped
    the stylesheet's ``[hidden]`` rule pass this test."""
    return page.eval_js(
        "getComputedStyle(document.getElementById('anki-section')).display") != 'none'


@pytest.mark.slow
@pytest.mark.regression
def test_card_mode_draws_the_fetched_cards_with_labelled_estimates(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    world = seed(wimi_session.user.db)
    with FakeAnkiConnect() as anki:
        stock(anki)
        enable_anki(wimi_page, anki.port)
        open_entry(wimi_page, world['entry'].id)

        wait_for_cards(wimi_page, 2)
        assert poll_true(wimi_page, "document.getElementById('anki-status').textContent"
                                    " === 'Up to date with Anki.'"), status(wimi_page)
        assert _section_shown(wimi_page)
        assert 'findCards' in anki.actions()

        card = "document.querySelector('#anki-cards .anki-card[data-card-id=\"101\"]')"
        # #815: collapsed, a row is the card's own words and one line of
        # figures -- never its deck as the title, and none of the fields.
        assert wimi_page.eval_js(f"{card}.querySelector('.anki-card-title').textContent")             == 'The aorta'
        collapsed = wimi_page.eval_js(f"{card}.innerText")
        assert 'Largest artery' not in collapsed and 'Stability' not in collapsed, collapsed
        assert 'Deck A' in collapsed and 'Interval 12 days' in collapsed, collapsed

        expand(wimi_page, 101)
        first = wimi_page.eval_js(f"{card}.innerText")
        for label in ('Stability (estimated)', 'Recall now (estimated)', 'Next review (estimated)',
                      'Ease', '250%', '12 days', 'The aorta', 'Largest artery'):
            assert label in first, (label, first)
        assert 'Difficulty' not in first
        assert wimi_page.eval_js(
            f"{card}.querySelector('.anki-thumb[data-filename=\"pic.png\"]') !== null"),             'the image should be a thumbnail, not a file name'
    assert 'fetched from Anki' in wimi_page.eval_js(
        "document.getElementById('anki-synced').textContent")


@pytest.mark.slow
@pytest.mark.regression
def test_note_mode_draws_one_block_per_note(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    world = seed(wimi_session.user.db)
    with FakeAnkiConnect() as anki:
        stock(anki)
        enable_anki(wimi_page, anki.port, anki_display_mode='note')
        open_entry(wimi_page, world['entry'].id)
        wait_for_cards(wimi_page, 1)

    block = wimi_page.eval_js("document.querySelector('#anki-cards .anki-card').innerText")
    assert '2 cards' in block and 'The aorta' in block, block
    assert '(estimated)' not in block, 'per-card figures belong to card mode only'


@pytest.mark.slow
@pytest.mark.regression
def test_with_anki_off_the_section_stays_hidden_and_the_backdrop_is_closed(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    world = seed(wimi_session.user.db)
    set_prefs(wimi_page, anki_integration_enabled=False)
    open_entry(wimi_page, world['entry'].id)
    # Positive control: the page drew its entry, so the section had its chance.
    assert poll_true(wimi_page, "document.getElementById('entry-heading').textContent"
                                " !== 'Loading entry…'")
    wimi_page.wait_for_timeout(500)
    assert not _section_shown(wimi_page)
    display = wimi_page.eval_js(
        "getComputedStyle(document.querySelector('.lightbox-modal')).display")
    assert display == 'none', f'the lightbox paints at load: display {display!r}'


@pytest.mark.slow
@pytest.mark.regression
def test_anki_closed_keeps_the_cached_cards_on_screen(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    world = seed(wimi_session.user.db)
    with FakeAnkiConnect() as anki:
        stock(anki)
        enable_anki(wimi_page, anki.port)
        open_entry(wimi_page, world['entry'].id)
        wait_for_cards(wimi_page, 2)
    # The fake has stopped: nothing listens on the saved port now.

    wimi_page.locator(css='#anki-refresh').click()
    assert poll_true(wimi_page, "document.getElementById('anki-status')"
                                ".textContent.startsWith('Anki is not answering')"), status(wimi_page)
    assert 'Showing what was fetched' in status(wimi_page)
    assert wimi_page.eval_js(
        "document.getElementById('anki-status').classList.contains('is-error')")
    wait_for_cards(wimi_page, 2)
    assert sorted(wimi_session.user.db.anki_entry_card_ids(world['entry'].id)) == [101, 102]
