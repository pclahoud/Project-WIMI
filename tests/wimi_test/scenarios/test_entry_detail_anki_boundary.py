"""Measurement: the lightbox still draws an accessibility boundary once the
Anki section's live region is on the page (#420, KNOWN_AT_RISK).

Wave 4 put a ``role="status"`` inside ``#main-content``, a page that already
had a modal surface: #420's precondition. A live region inside the page's main
container once exempted the whole page from the helper's walk, so the dialog
was not modal at all while its role, name and focus all looked right. This is
the measurement ``tests/test_modal_boundary_coverage.py`` asks for before the
page joins ``KNOWN_AT_RISK``: a REAL hit-tested click on a card image's View
button -- an invoker inside the section that carries the live region -- opens
the lightbox, the exposed node count falls, and ``modal_dialog.js`` holds
``aria-hidden`` attributes (the instrument; a falling count alone is not).

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.anki_entry import enable_anki, expand, open_entry, seed, stock, wait_for_cards
from _helpers.anki_settings import poll_true
from _helpers.page_gate import ax_snapshot, ax_summary, enable_accessibility
from tests._fake_ankiconnect import FakeAnkiConnect
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

VIEW = '#anki-cards .anki-card[data-card-id="101"] .anki-thumb[data-filename="pic.png"]'


@pytest.mark.slow
@pytest.mark.regression
def test_the_lightbox_draws_a_boundary_with_the_anki_status_present(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    world = seed(wimi_session.user.db)
    with FakeAnkiConnect() as anki:
        stock(anki)
        enable_anki(wimi_page, anki.port)
        open_entry(wimi_page, world['entry'].id)
        wait_for_cards(wimi_page, 2)
        # Precondition, measured rather than assumed: the live region is rendered.
        assert wimi_page.eval_js(
            "getComputedStyle(document.getElementById('anki-section')).display") != 'none'
        assert wimi_page.eval_js(
            "document.getElementById('anki-status').getAttribute('role')") == 'status'

        expand(wimi_page, 101)
        enable_accessibility(wimi_page)
        before = ax_snapshot(wimi_page)
        assert 'dialog' not in before['roles'], f'a dialog is exposed already: {ax_summary(before)}'

        wimi_page.locator(css=VIEW).click()
        assert poll_true(wimi_page, "document.getElementById('lightbox-modal')"
                                    ".classList.contains('active')"), 'the lightbox never opened'

    after = ax_snapshot(wimi_page)
    for _ in range(30):
        if after['exposed'] < before['exposed'] and 'dialog' in after['roles']:
            break
        wimi_page.wait_for_timeout(100)
        after = ax_snapshot(wimi_page)
    assert 'dialog' in after['roles'], f'the lightbox is not exposed: {ax_summary(after)}'
    assert after['exposed'] < before['exposed'], (
        f"opening the lightbox did not reduce what the tree exposes "
        f"({before['exposed']} -> {after['exposed']})\n"
        f"before: {ax_summary(before)}\nafter: {ax_summary(after)}")
    held = wimi_page.eval_js("(() => window.ModalDialog ? window.ModalDialog.hiddenCount() : -1)()")
    assert held > 0, f'the tree shrank but modal_dialog.js holds nothing (held={held})'
