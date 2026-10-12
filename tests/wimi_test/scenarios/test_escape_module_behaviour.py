"""``WimiEscape`` in a real page: what it escapes, and that the result is inert (#548).

There is no Node in this project's toolchain, so the module is exercised where
it runs: its source is evaluated in a WIMI page and the cases are checked in
Chromium. The last check is the one that matters -- the escaped payload is put
through ``innerHTML`` in an attribute and in content, and nothing executes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SOURCE = (Path(__file__).resolve().parents[3] / 'src' / 'web' / 'js'
          / 'escape.js').read_text(encoding='utf-8')

PROBE = """
(() => {
  const E = window.WimiEscape;
  const payload = `"><img src=x onerror="window.__esc_fired=1">'`;
  const host = document.createElement('div');
  host.innerHTML = `<span title="${E.attr(payload)}" data-x='${E.attr(payload)}'>${E.html(payload)}</span>`;
  document.body.appendChild(host);
  return JSON.stringify({
    amp: E.html('a & b'), lt: E.html('<b>'), quotes: E.html(`"'`),
    nul: E.html(null), undef: E.html(undefined), zero: E.html(0),
    num: E.html(12.5), bool: E.html(false), same: E.attr === E.html,
    imgs: host.querySelectorAll('img').length,
    title: host.querySelector('span').getAttribute('title'),
    datax: host.querySelector('span').getAttribute('data-x'),
    text: host.querySelector('span').textContent,
    payload: payload,
  });
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_wimiescape_escapes_and_the_result_is_inert(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    wimi_page.goto('dashboard')
    wimi_page.eval_js(SOURCE)
    state = json.loads(wimi_page.eval_js(PROBE))
    wimi_page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    fired = wimi_page.eval_js('window.__esc_fired === 1')

    assert state['amp'] == 'a &amp; b'
    assert state['lt'] == '&lt;b&gt;'
    assert state['quotes'] == '&quot;&#39;', 'both quotes, so either attribute style is safe'
    assert (state['nul'], state['undef']) == ('', '')
    assert state['zero'] == '0', 'a count of zero must not vanish'
    assert (state['num'], state['bool']) == ('12.5', 'false')
    assert state['same'], 'attr and html are one function'

    assert not fired and state['imgs'] == 0, 'the escaped payload executed'
    assert state['title'] == state['payload'], 'the attribute round-trips exactly'
    assert state['datax'] == state['payload'], 'single-quoted attribute too'
    assert state['text'] == state['payload'], 'content round-trips exactly'
