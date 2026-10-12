"""Regression: "Add this relation" is the house primary button, hover included (#400).

``.relprop-confirm`` restated ``.btn-primary``'s three resting colours by hand
and copied none of its states, so the card's PRIMARY action was the one
button on it that did not answer the pointer -- while the two rejections
beside it did. Measured on a rendered card before the fix, pointer moved onto
each button with ``Input.dispatchMouseEvent`` and the transition outlasted:

    Add this relation    rgb(33, 150, 243) at rest, rgb(33, 150, 243) hovered
    the misread button   transparent at rest,     rgb(241, 245, 249) hovered

(That button was labelled "WIMI misread this" when this was measured; #398
renamed it to "Not in this entry". The selector is a testid, so only the
prose moved.)

The fix is to use the button system rather than restate it: the button carries
``btn btn-primary`` and ``.relprop-confirm`` keeps only its size. So what this
asserts is the behaviour, not the class list -- a hand-written ``:hover`` rule
would pass too, and that is fine; what must not pass is a button that does
not move.

Three things the change could silently lose, each asserted:

* **the resting colour** -- a colour left in ``.relprop-confirm`` beats
  ``.btn-primary`` by file order at equal specificity (CLAUDE.md, #309/#321);
* **the focus ring** -- ``.btn`` adds ``transition: all``, so the ring is read
  only after the transition, through a real Tab (``:focus-visible`` does not
  match a scripted ``focus()``);
* **the disabled state** -- the card disables its buttons while an answer is
  in flight, and a disabled button must neither hover nor lose its dim.

Colours are compared against the tokens as the page resolves them, never
against literals, because the student's stored primary colour rewrites
``--color-primary`` on every load (#325).

The model is FAKED -- see ``_helpers/fake_relation_card.py`` for why and how.
"""
from __future__ import annotations

import json

import pytest

from _helpers.a11y import real_key
from _helpers.fake_relation_card import CONFIRM, MISREAD, REASON, open_card
from _helpers.w114_form_ready import centre_of, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

#: Comfortably past --transition-fast (150 ms).
SETTLE_MS = 400

STYLE = """
(() => {
  const s = getComputedStyle(document.querySelector(%s));
  return JSON.stringify({bg: s.backgroundColor, border: s.borderTopColor,
    color: s.color, opacity: s.opacity, cursor: s.cursor,
    outline_style: s.outlineStyle, outline_width: s.outlineWidth});
})()
"""

TOKEN = """
(() => {
  const probe = document.createElement('div');
  probe.style.backgroundColor = 'var(%s)';
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return value;
})()
"""


def _style(page: WimiPage, selector: str) -> dict:
    return json.loads(page.eval_js(STYLE % json.dumps(selector)))


def _token(page: WimiPage, name: str) -> str:
    return page.eval_js(TOKEN % name)


def _hover(page: WimiPage, selector: str | None) -> None:
    point = centre_of(page, selector) if selector else {'x': 1, 'y': 1}
    page.tab.Input.dispatchMouseEvent(
        type='mouseMoved', x=point['x'], y=point['y'], button='none')
    page.wait_for_timeout(SETTLE_MS)


@pytest.mark.slow
@pytest.mark.regression
def test_the_confirm_button_hovers_focuses_and_disables_like_a_primary_button(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    page = wimi_page
    open_card(page, wimi_session.user.db)
    primary = _token(page, '--color-primary')
    primary_hover = _token(page, '--color-primary-hover')
    assert primary != primary_hover, (
        f'sanity: this theme has no distinct hover colour ({primary})')

    _hover(page, None)
    rest = _style(page, CONFIRM)
    assert rest['bg'] == primary and rest['border'] == primary, (
        f'the resting confirm button is not the primary colour: {rest}, '
        f'--color-primary={primary}')
    assert rest['color'] == _token(page, '--text-inverse'), rest

    # Positive control: the instrument moves a button that has a hover.
    misread_rest = _style(page, MISREAD)['bg']
    _hover(page, MISREAD)
    assert _style(page, MISREAD)['bg'] != misread_rest, (
        'hovering the misread button changed nothing, so the pointer is not '
        'reaching the card and the assertion below would prove nothing')

    _hover(page, CONFIRM)
    hovered = _style(page, CONFIRM)
    assert hovered['bg'] == primary_hover, (
        f'"Add this relation" does not respond to the pointer: hovered '
        f'{hovered["bg"]}, resting {rest["bg"]}, expected '
        f'--color-primary-hover {primary_hover} (#400)')
    assert hovered['border'] == primary_hover, hovered

    # A real Tab from the reason field lands on the button and draws the
    # app's ring (2px, styles.css "Focus"), once .btn's transition is over.
    _hover(page, None)
    real_click(page, centre_of(page, REASON))
    real_key(page, 'Tab')
    page.wait_for_timeout(SETTLE_MS)
    assert page.eval_js(
        "document.activeElement === document.querySelector(%s)"
        " && document.activeElement.matches(':focus-visible')"
        % json.dumps(CONFIRM)), 'Tab from the reason did not reach the button'
    ring = _style(page, CONFIRM)
    assert ring['outline_style'] == 'solid' and ring['outline_width'] == '2px', (
        f'the confirm button takes focus without the app focus ring: {ring}')

    # Disabled while an answer is in flight: dimmed like the rejections, and
    # the pointer must not light it up.
    page.eval_js("document.activeElement.blur();"
                 " document.querySelectorAll('.relprop-actions button')"
                 "   .forEach(b => { b.disabled = true; })")
    _hover(page, CONFIRM)
    off = _style(page, CONFIRM)
    assert off['bg'] == primary, (
        f'a disabled confirm button still hovers: {off["bg"]}')
    assert off['opacity'] == _style(page, MISREAD)['opacity'] != '1', (
        f'disabled confirm {off["opacity"]} does not dim like a disabled '
        f'rejection {_style(page, MISREAD)["opacity"]}')
    assert off['cursor'] != 'pointer', off
