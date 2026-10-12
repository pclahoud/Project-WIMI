"""Regression: each rejection's SCOPE is on the button, not in a `title` (#398).

The two rejections reach different distances. `misread` records an m027
rejection scoped to this entry; `not_related` suppresses the pair across the
whole exam. That difference is the entire reason there are two buttons — #60's
own adjudication found **25 of 45** rejections meant the local one, so a single
Reject would have globally suppressed a true pair most times it was pressed.

It used to be stated **only** in a `title`: the labels read "WIMI misread this"
and "Not related", which distinguish the two *claims* and say nothing about
reach. A `title` never appears on a touch device, is not shown on keyboard
focus, is inconsistently exposed to screen readers, and opens about a second
after the pointer settles — so a student moving decisively between two
identically weighted buttons was never told that one of them is permanent.

Owner's decision, 2026-10-06: **put the scope in the labels and move the reason
to the tooltip.** The labels are now "Not in this entry" and "Never related".

What is measured here, and why each needs a browser
---------------------------------------------------
* **The accessible name**, through CDP rather than from `textContent`. A
  `title` *is* a name source, so "the button has a name" is true of the broken
  version too; what distinguishes them is that the name now comes from the
  button's own contents and carries the scope. `_helpers/a11y.ax_node` reports
  the winning source, which is the half a DOM read cannot see.
* **Equal visual weight**, from `getComputedStyle` on the rendered pair. The
  decision says in terms that this is a text change and not a hierarchy
  change: styling the global rejection more prominently than the local one
  would push students toward it, which is the same defect in another form. A
  source check cannot see it — one extra class in a stylesheet is enough.

The model is FAKED — see `_helpers/fake_relation_card.py` for why and how.
"""
from __future__ import annotations

import json

import pytest

from _helpers.a11y import ax_node, describe, enable
from _helpers.fake_relation_card import (
    CONFIRM,
    MISREAD,
    NOT_RELATED,
    open_card,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

#: The properties that carry visual weight. Not an exhaustive style diff: a
#: difference in, say, `cursor` is not a hierarchy, and asserting on everything
#: would make the test fail for reasons it is not about.
WEIGHT = """
(() => {
  const read = sel => {
    const s = getComputedStyle(document.querySelector(sel));
    return {bg: s.backgroundColor, color: s.color, border: s.borderTopColor,
            border_width: s.borderTopWidth, font_size: s.fontSize,
            font_weight: s.fontWeight, padding: s.padding,
            opacity: s.opacity, text_decoration: s.textDecorationLine};
  };
  return JSON.stringify({misread: read(%s), unrelated: read(%s),
                         confirm: read(%s)});
})()
"""

BOXES = """
(() => {
  const box = sel => {
    const r = document.querySelector(sel).getBoundingClientRect();
    return {w: Math.round(r.width), h: Math.round(r.height)};
  };
  return JSON.stringify({misread: box(%s), unrelated: box(%s)});
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_each_rejection_says_how_far_it_reaches(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    page = wimi_page
    open_card(page, wimi_session.user.db)
    enable(page)

    misread = ax_node(page, MISREAD)
    unrelated = ax_node(page, NOT_RELATED)

    # The control: both buttons are in the tree and not ignored, so what the
    # names say is a finding rather than a read of nothing.
    for name, node in (('misread', misread), ('not_related', unrelated)):
        assert node['found'] and not node['ignored'], (
            f'the {name} button is not exposed to assistive tech: '
            f'{describe(node)}')
        assert node['role'] == 'button', describe(node)

    assert 'contents' in misread['name_from'], (
        f'the local rejection takes its accessible name from something other '
        f'than its own visible text: {describe(misread)}. A name computed '
        f'from a `title` is the state #398 was filed about -- the student '
        f'sees one thing and the scope lives somewhere they cannot reach')
    assert 'contents' in unrelated['name_from'], describe(unrelated)

    assert 'this entry' in (misread['name'] or '').lower(), (
        f'the local rejection is named {misread["name"]!r}, which does not '
        f'say that it applies to this entry only. 25 of 45 rejections meant '
        f'this one; a student choosing it is entitled to know it is the '
        f'narrow one before they press (#398)')
    assert 'never' in (unrelated['name'] or '').lower(), (
        f'the global rejection is named {unrelated["name"]!r}, which does not '
        f'say that it suppresses the pair for good. It writes an m027 '
        f'rejection scoped to the whole exam, and that is not recoverable '
        f'from this card (#398)')

    # And the reason did not simply vanish: the decision moved it to the
    # tooltip, where it is context rather than the load-bearing half.
    titles = json.loads(page.eval_js(
        "(() => JSON.stringify({misread: document.querySelector(%s).title,"
        " unrelated: document.querySelector(%s).title}))()"
        % (json.dumps(MISREAD), json.dumps(NOT_RELATED))))
    for which, text in titles.items():
        assert text and len(text) > 20, (
            f'the {which} button lost its reason entirely ({text!r}); #398 '
            f'moved the reason to the `title`, it did not delete it')
        assert '--' not in text, (
            f'the {which} title renders verbatim and contains a literal `--` '
            f'(#396): {text!r}')


@pytest.mark.slow
@pytest.mark.regression
def test_neither_rejection_outweighs_the_other(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """Equal weight, measured rendered rather than read off a class list.

    Making the global rejection the louder of the two would push students
    toward it when they meant the local one, which costs a true relation
    across their whole exam. #398's decision calls this out explicitly: a text
    change, not a hierarchy change.
    """
    page = wimi_page
    open_card(page, wimi_session.user.db)

    weight = json.loads(page.eval_js(
        WEIGHT % (json.dumps(MISREAD), json.dumps(NOT_RELATED),
                  json.dumps(CONFIRM))))

    # Positive control: the instrument can see a difference where there is
    # one. "Add this relation" is a `.btn-primary` and must not match them.
    assert weight['misread'] != weight['confirm'], (
        'the two rejections and the primary action render identically, so '
        'this comparison could not detect a hierarchy at all')

    differing = {key for key in weight['misread']
                 if weight['misread'][key] != weight['unrelated'][key]}
    assert not differing, (
        f'the two rejections differ on {sorted(differing)}: '
        f'{weight["misread"]} vs {weight["unrelated"]}. They carry equal '
        f'weight by decision -- one quieter than the other pushes students '
        f'toward the global suppression when they meant the local one')

    # The labels differ in length, so the boxes legitimately differ in width.
    # What must not differ is height: a shorter button reads as a lesser one,
    # and WCAG 2.2 AA target size is a floor for both.
    boxes = json.loads(page.eval_js(
        BOXES % (json.dumps(MISREAD), json.dumps(NOT_RELATED))))
    assert boxes['misread']['h'] == boxes['unrelated']['h'], boxes
    for which, box in boxes.items():
        assert box['h'] >= 24 and box['w'] >= 24, (
            f'the {which} button is {box}, under the 24px floor WCAG 2.2 AA '
            f'target size sets and this project took as a decision')
