"""Shared helpers for the entry-detail Anki scenarios (#784 Wave 4).

Seeding goes through the test's database connection. The Anki switch and port
do not: they are device settings, keyed on the app's device id, which the
test's own connection does not carry -- so they are written through the app's
``updateUserPreferences``, the same call Settings -> Anki makes.
"""
from __future__ import annotations

import io
import json

from wimi_test.page import WimiPage

from _helpers.anki_settings import poll, poll_true

TPL = 'tag:Bank::{{qid}}'

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
       b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01'
       b'\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82')

def _png(rgb) -> bytes:
    """A real 2x2 PNG in one colour, so two images differ by their bytes."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), rgb).save(buf, 'PNG')
    return buf.getvalue()


#: The second image on card 101, on its back (#815's arrows step to it).
PNG2 = _png((200, 30, 30))

CARDS = "document.querySelectorAll('#anki-cards .anki-card').length"
STATUS = "document.getElementById('anki-status').textContent"


def seed(db) -> dict:
    """An exam, a bank with a template, and one entry with question id 7."""
    exam = db.create_exam_context(exam_name='Step X')
    bank = db.create_question_source(source_name='Bank', exam_context='Step X')
    db.anki_add_template(exam.id, bank.id, TPL)
    session = db.create_review_session(exam_context_id=exam.id, total_questions=5,
                                       total_incorrect=1, question_source_id=bank.id)
    entry = db.create_question_entry(session.id, 'A', 'B', question_id='7')
    return {'exam': exam, 'bank': bank, 'entry': entry}


def stock(anki) -> None:
    """Two cards of one note for question 7: a reviewed one with an image,
    and a new sibling."""
    anki.searches['tag:Bank::7'] = [101, 102]
    anki.add_card(101, note_id=10, interval=12, queue=2, type=2, deckName='Deck A',
                  fields={'Front': {'value': 'The aorta <img src="pic.png">', 'order': 0},
                          'Back': {'value': 'Largest artery <img src="pic2.png">',
                                   'order': 1}})
    anki.add_card(102, note_id=10, interval=0, queue=0, type=0, deckName='Deck A')
    anki.reviews[101] = [{'id': 1_700_000_000_000, 'ivl': 12, 'factor': 2500, 'time': 4000,
                          'ease': 3, 'lastIvl': 4, 'type': 1}]
    anki.media['pic.png'] = PNG
    anki.media['pic2.png'] = PNG2


def set_prefs(page: WimiPage, **prefs) -> None:
    """Write settings through the app, from whatever page is open."""
    page.goto('dashboard')
    result = page.eval_js(
        "(async () => { await api.updateUserPreferences(" + json.dumps(prefs) + ");"
        " return 'ok'; })()", await_promise=True)
    assert result == 'ok', result


def enable_anki(page: WimiPage, port: int, **prefs) -> None:
    set_prefs(page, anki_integration_enabled=True, ankiconnect_port=port, **prefs)


def open_entry(page: WimiPage, entry_id: int) -> None:
    """Open the entry and wait until the page itself is drawn."""
    page.eval_js("window.__wimiPrevDoc = true")
    page.goto('entry-detail', query={'id': entry_id})
    assert poll(page, "typeof window.__wimiPrevDoc === 'undefined'", True) is True
    assert poll_true(page, "document.getElementById('main-content').style.display === 'flex'"), \
        'the entry never drew'


def wait_for_cards(page: WimiPage, count: int) -> None:
    assert poll(page, CARDS, count) == count, (
        f'expected {count} cards; status: {page.eval_js(STATUS)!r}')


def status(page: WimiPage) -> str:
    return page.eval_js(STATUS) or ''


def expand(page: WimiPage, card_id: int) -> None:
    """Open one card's row by a real click on its toggle (#815: rows are
    collapsed by default, so a card's fields, figures and buttons are behind
    it), and wait until its body paints."""
    row = f'#anki-cards .anki-card[data-card-id="{card_id}"]'
    page.locator(css=f'{row} .anki-toggle').click()
    assert poll_true(page, f"getComputedStyle(document.querySelector('{row} .anki-card-body'))"
                           ".display !== 'none'"), f'card {card_id} did not open'
