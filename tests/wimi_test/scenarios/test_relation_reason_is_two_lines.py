"""Regression: the proposal's reason field is the two lines it asks for (#399).

``buildCard()`` creates the reason textarea with ``rows="2"``, and for as long
as the card existed that attribute did nothing: ``styles.css`` gives every
``textarea`` a ``min-height`` of 6.25rem, ``.relprop-reason`` declared none,
and a class that does not declare a property cannot undo an element rule that
does. Measured on a rendered card before the fix, light theme, 14px text:

    getComputedStyle(reason).height   100px   (min-height 100px, rows 2)

against **52px** for two 21px lines plus 4+4px padding and a 1px border each
side (border-box). Per card, on the page the student spends most time on.

Why this is a rendered measurement and not a source check
---------------------------------------------------------
The defect is a declaration that reads as in effect and is not -- #321's
class. A test that greps for ``rows: '2'`` or for a ``min-height`` in
``relation_proposals.css`` passes against plenty of broken versions (a
min-height of 6.25rem, a selector the global rule outranks). So this reads the
height Chromium laid out, and then moves ``rows`` to prove the attribute is
what governs it: a fix that merely pinned the field at 52px would pass the
first assertion and fail the second.

The model is FAKED -- see ``_helpers/fake_relation_card.py`` for why and how.
"""
from __future__ import annotations

import json

import pytest

from _helpers.fake_relation_card import REASON, open_card
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

MEASURE = """
(() => {
  const r = document.querySelector(%s);
  const s = getComputedStyle(r);
  const px = v => parseFloat(v) || 0;
  return JSON.stringify({
    rows: r.rows,
    height: r.getBoundingClientRect().height,
    line: px(s.lineHeight),
    chrome: px(s.paddingTop) + px(s.paddingBottom)
          + px(s.borderTopWidth) + px(s.borderBottomWidth),
    resize: s.resize,
    max_height: s.maxHeight,
  });
})()
""" % json.dumps(REASON)


def _measure(page: WimiPage) -> dict:
    return json.loads(page.eval_js(MEASURE))


def _expected(m: dict) -> float:
    return m['rows'] * m['line'] + m['chrome']


@pytest.mark.slow
@pytest.mark.regression
def test_the_reason_field_is_as_tall_as_its_rows(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    open_card(wimi_page, wimi_session.user.db)

    m = _measure(wimi_page)
    assert m['rows'] == 2, f'sanity: the card asks for {m["rows"]} rows'
    assert m['line'] > 0, f'line-height did not resolve to pixels: {m}'
    assert abs(m['height'] - _expected(m)) <= 1, (
        f"the reason field renders {m['height']}px tall where rows=2 asks for "
        f"{_expected(m)}px ({m['line']}px lines + {m['chrome']}px padding and "
        f"border). 100px is styles.css's global textarea min-height winning "
        f"over the card (#399)")

    # Editable on purpose (#5494): it must still grow, and nothing may clip a
    # long reason.
    assert m['resize'] == 'vertical', m
    assert m['max_height'] == 'none', m

    # And the attribute is what decides it, not a pinned height that happens
    # to agree with it today.
    wimi_page.eval_js("document.querySelector(%s).rows = 4" % json.dumps(REASON))
    wimi_page.wait_for_timeout(50)
    four = _measure(wimi_page)
    assert abs(four['height'] - _expected(four)) <= 1, (
        f"with rows=4 the field is {four['height']}px, not {_expected(four)}px "
        f"-- something other than `rows` is setting its height")
