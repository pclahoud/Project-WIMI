"""Regression: a card's image opens in the page's own lightbox, and saving it
puts it in Attachments.

#815: an image is a thumbnail in the open card, not a file name with two
buttons. Clicking it fetches the bytes through the bridge (only an image this
entry's cards show may be fetched) and opens them in the existing lightbox
rather than a second modal. **The arrows, and the arrow keys, step through
every image on that card** in field order, fetching each as it is reached and
wrapping at the ends (owner, #815); the caption names the field and the
position, because the file name is usually a hash. **Save to Attachments lives in the
lightbox**: it attaches the image, the attachments grid redraws through
``reloadAttachments``, and the button turns into a disabled *In Attachments*
so the same image cannot be attached twice -- including when it is opened
again. The control: an ordinary attachment opened in the same lightbox
offers no Save at all.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.a11y import real_key
from _helpers.anki_entry import (
    enable_anki, expand, open_entry, seed, status, stock, wait_for_cards,
)
from _helpers.anki_settings import poll_true
from tests._fake_ankiconnect import FakeAnkiConnect
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

VIEW = '#anki-cards .anki-card[data-card-id="101"] .anki-thumb[data-filename="pic.png"]'
SAVE = '#lightbox-save'
CAPTION = "document.getElementById('lightbox-caption').textContent"
SRC = "document.getElementById('lightbox-image').src"
SAVE_SHOWN = "getComputedStyle(document.getElementById('lightbox-save')).display !== 'none'"


@pytest.mark.slow
@pytest.mark.regression
def test_view_opens_the_lightbox_and_save_attaches_once(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed(db)
    with FakeAnkiConnect() as anki:
        stock(anki)
        enable_anki(wimi_page, anki.port)
        open_entry(wimi_page, world['entry'].id)
        wait_for_cards(wimi_page, 2)
        assert wimi_page.eval_js("document.getElementById('attachment-count').textContent") == '0'
        expand(wimi_page, 101)
        assert poll_true(wimi_page, f"document.querySelector('{VIEW} img').getAttribute('src')"
                                    "?.startsWith('data:image/png;base64,')"),             'the thumbnail never got its image'

        # ---- View: the existing lightbox, the image's bytes, the card's arrows
        wimi_page.locator(css=VIEW).click()
        assert poll_true(wimi_page, "document.getElementById('lightbox-modal')"
                                    ".classList.contains('active')"), status(wimi_page)
        assert wimi_page.eval_js(
            "document.getElementById('lightbox-image').src.startsWith('data:image/png;base64,')")
        assert wimi_page.eval_js(CAPTION) == 'Front, image 1 of 2'
        assert wimi_page.eval_js(
            "getComputedStyle(document.getElementById('lightbox-next')).display") == 'block'
        first_src = wimi_page.eval_js(SRC)

        # ---- The arrow keys step through the card's images, and wrap
        real_key(wimi_page, 'ArrowRight')
        assert poll_true(wimi_page, f"{CAPTION} === 'Back, image 2 of 2'"),             (wimi_page.eval_js(CAPTION), status(wimi_page))
        assert wimi_page.eval_js(SRC) != first_src, 'the caption moved but the picture did not'
        real_key(wimi_page, 'ArrowRight')
        assert poll_true(wimi_page, f"{CAPTION} === 'Front, image 1 of 2'"), 'no wrap at the end'
        assert wimi_page.eval_js(SRC) == first_src
        real_key(wimi_page, 'ArrowLeft')
        assert poll_true(wimi_page, f"{CAPTION} === 'Back, image 2 of 2'"), 'no wrap backwards'
        wimi_page.locator(css='#lightbox-next').click()
        assert poll_true(wimi_page, f"{CAPTION} === 'Front, image 1 of 2'"),             'the on-screen arrow does not step'
        assert wimi_page.eval_js(SAVE_SHOWN), 'an Anki image must offer Save in the lightbox'
        assert wimi_page.eval_js(f"document.querySelector('{SAVE}').textContent")             == 'Save to Attachments'
        assert db.get_entry_media_list(world['entry'].id) == [], 'viewing must not attach'

        # ---- Save, from the lightbox: one attachment, the button stands down
        wimi_page.locator(css=SAVE).click()
        assert poll_true(wimi_page, "document.getElementById('anki-status').textContent"
                                    " === 'Saved pic.png to Attachments.'"), status(wimi_page)
        assert poll_true(wimi_page, f"document.querySelector('{SAVE}').disabled")
        assert wimi_page.eval_js(f"document.querySelector('{SAVE}').textContent") == 'In Attachments'
        wimi_page.locator(css='#lightbox-close').click()
        assert poll_true(wimi_page, "!document.getElementById('lightbox-modal')"
                                    ".classList.contains('active')")

    assert wimi_page.eval_js("document.getElementById('attachment-count').textContent") == '1'
    assert wimi_page.eval_js("document.querySelectorAll('#attachments-grid .attachment-thumb')"
                             ".length") == 1
    assert [m.original_filename for m in db.get_entry_media_list(world['entry'].id)]         == ['pic.png']

    # ---- Opened again it is still In Attachments, so it cannot attach twice
    wimi_page.locator(css=VIEW).click()
    assert poll_true(wimi_page, "document.getElementById('lightbox-modal')"
                                ".classList.contains('active')")
    assert wimi_page.eval_js(f"document.querySelector('{SAVE}').disabled")
    assert wimi_page.eval_js(f"document.querySelector('{SAVE}').textContent") == 'In Attachments'
    wimi_page.locator(css='#lightbox-close').click()

    # ---- Control: an ordinary attachment in the same lightbox offers no Save
    wimi_page.locator(css='#attachments-grid .attachment-thumb').click()
    assert poll_true(wimi_page, "document.getElementById('lightbox-modal')"
                                ".classList.contains('active')"), 'the attachment never opened'
    assert not wimi_page.eval_js(SAVE_SHOWN), 'Save is for Anki images only'
