"""Regression: entry browser cards show reflection HTML as escaped text.

Forgejo issue #3 -- "Entry browser cards show reflection HTML as escaped
text":

    card previews print the reflection's markup literally, e.g.
    ``<p>hypertension, cardiac context - I anchored on the wrong
    feature.</p>`` with the ``<p>`` tags visible. [...] the first card's
    innerText was ``"Medium\\nSep 10, 2026\\nhypertension\\n...\\n<p>seeded
    reflection text</p>"``, so the tags are text nodes, not markup.

Why it failed: reflections are stored as HTML because TinyMCE writes them
that way (``create_question_entry(reflection='<p>...</p>')``), and
``createEntryCard`` in ``entry_browser.js`` assigned that string straight
to ``reflectionPreview.textContent``. ``textContent`` escapes, so every
tag became visible text. The entry detail page renders the same field
through ``RichContentRenderer`` and never showed the problem.

What the fix changes: the card reduces the stored HTML to plain text
before assigning ``textContent`` -- parsed in an inert ``DOMParser``
document (never injected into the live page), block boundaries turned
into spaces. A two-line clamped preview has no room for lists, headings
or KaTeX, so stripping beats rendering here.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

REFLECTION_HTML = (
    '<p>Anchored on <strong>the wrong</strong> feature.</p>'
    '<ul><li>item</li></ul>'
)
CARD_COUNT = "document.querySelectorAll('#entryGrid [data-entry-id]').length"
PREVIEW = (
    "(() => { const p = document.querySelector("
    "'#entryGrid [data-entry-id] .reflection-preview');"
    " return JSON.stringify({"
    "  text: p.textContent,"
    "  innerText: p.innerText,"
    "  elementChildren: p.children.length,"
    "  markupDescendants: p.querySelectorAll('p, strong, ul, li').length,"
    "  cardInnerText: p.closest('[data-entry-id]').innerText }); })()"
)


def _poll(wimi_page: WimiPage, js: str, want, *, timeout_ms: int = 10000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db) -> None:
    """One exam, one session, one entry whose reflection is nested HTML."""
    exam = db.create_exam_context(exam_name='Card Preview Exam', exam_description='')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name='Card preview session', date_encountered=date.today(),
    )
    db.create_question_entry(
        review_session_id=session.id, user_answer='a', correct_answer='b',
        reflection=REFLECTION_HTML, explanation='<p>Explanation</p>',
    )


@pytest.mark.slow
@pytest.mark.regression
def test_card_preview_shows_reflection_as_plain_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    _seed(wimi_session.user.db)

    # ---- Act ---------------------------------------------------------
    wimi_page.goto('entry-browser')
    cards = _poll(wimi_page, CARD_COUNT, 1)
    assert cards == 1, f'Expected 1 card, got {cards!r}'
    preview = json.loads(wimi_page.eval_js(PREVIEW))

    # ---- Assert: the words survive, the markup does not --------------
    for word in ('Anchored on', 'the wrong', 'feature.', 'item'):
        assert word in preview['text'], (
            f'Preview lost {word!r}: {preview["text"]!r}'
        )
    # The reporter's symptom: '<' and '>' from the stored HTML shown as text.
    assert '<' not in preview['text'] and '>' not in preview['text'], (
        f'Card preview prints reflection markup as text: {preview["text"]!r}. '
        'createEntryCard assigned the stored HTML to textContent.'
    )
    assert '<' not in preview['cardInnerText'], preview['cardInnerText']
    # Stripped, not rendered: nothing in the card was built from the markup.
    assert preview['elementChildren'] == 0 and preview['markupDescendants'] == 0, (
        f'Reflection markup was rendered into the card: {preview!r}'
    )
    # Block boundaries become spaces, so the list item does not fuse onto
    # the paragraph ("feature.item").
    assert 'feature. item' in preview['text'], preview['text']
