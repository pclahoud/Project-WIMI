"""Regression: the MCP status row must not claim a state it has not read.

Forgejo issue #90 -- "[bug] settings.html asserts the MCP server is
'Stopped' before it has asked, and the catch that should hide the panel
hides nothing":

    ``settings.html`` shipped ``<span class="mcp-status-dot stopped">`` and
    ``<span class="mcp-status-text">Stopped</span>``. ``Stopped`` is one of
    exactly three states ``_updateMcpStatusUI`` writes (``Running on port
    N``, ``Error: ...``, ``Stopped``), so this is an assertion, not a
    placeholder -- made before ``refreshMcpStatus()`` has awaited
    ``api.getMcpServerStatus()``. If the MCP server was left running from a
    previous session, the settings DOM states the opposite of the truth.

    Separately, the catch meant to hide the panel on an older bridge hid
    nothing: the panel stayed visible showing whatever the markup shipped.

What the fix changes: a neutral fourth state. The markup ships
``.mcp-status-dot.unknown`` / ``Checking...``, and the catch renders
``Status unavailable`` through ``_setMcpStatusUnavailable`` instead of
leaving ``Stopped`` standing. The panel deliberately still does not hide --
that catch fires for any failure of the call, transient ones included, and
removing a settings panel on a failed read would take away the only way to
retry.

Why these assertions catch the regression, and why they are here rather
than only in ``tests/test_web_static_placeholders.py``: the static guard
proves the *markup* no longer ships ``stopped``, but it cannot prove the
new class paints anything. ``.mcp-status-dot`` sets only size and shape, so
a dot whose state class resolves to nothing is an invisible dot -- and an
undefined ``var()`` still *computes* to something (the initial value for
``border-color`` is ``currentColor``), so "is there a colour" proves
nothing either. Every assertion below compares against ``--text-muted``
resolved live on the same page, and every one runs again under Midnight,
where that token moves. That second pass is what rules out a hardcoded hex
and a token the theme system cannot reach: either would sit still while the
theme moved. This is the shape ``test_danger_colour_resolves.py`` (#76)
established.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# What the document ships. Rendered from `Checking&hellip;`.
SHIPPED_TEXT = 'Checking…'

# The three states `_updateMcpStatusUI` paints. Shipping any of them is the bug.
DETERMINED = ('running', 'stopped', 'error')

# `refreshMcpStatus` runs at the tail of `init()`. Wait for it to land before
# touching anything, so nothing below races a late write onto the same node.
SETTLED = """
(() => {
  if (typeof settingsPage === 'undefined' || !settingsPage) return null;
  if (typeof settingsPage._setMcpStatusUnavailable !== 'function') return null;
  const text = document.getElementById('mcpStatusText');
  if (!text) return null;
  const settled = text.textContent.trim();
  if (settled === '' || settled === '\\u2026' || settled.startsWith('Checking')) return null;
  return JSON.stringify({settled: settled});
})()
"""

# Activate the panel. It is `display: none` until then, and a dot inside a
# display:none subtree has no used width -- which would make the "is it
# actually a 10px ring" half of this test vacuous.
OPEN_PANEL = """
(() => {
  const nav = document.querySelector('.settings-nav-item[data-panel="mcp_server"]');
  const panel = document.querySelector('.settings-panel[data-panel="mcp_server"]');
  if (!nav || !panel) return null;
  nav.click();
  return JSON.stringify({active: panel.classList.contains('active'),
                         display: getComputedStyle(panel).display});
})()
"""

# Drive the real catch-path renderer, then read what it painted. `--text-muted`
# and the `.stopped` grey are resolved on a live probe in the same document, so
# the comparison follows the cascade rather than a value copied into this file.
PROBE = """
(() => {
  settingsPage._setMcpStatusUnavailable();
  const dot = document.getElementById('mcpStatusDot');
  const text = document.getElementById('mcpStatusText');
  const probe = document.createElement('span');
  document.body.appendChild(probe);
  const resolve = (value) => {
    probe.style.cssText = '';
    probe.style.setProperty('border-top-color', value);
    return getComputedStyle(probe).borderTopColor;
  };
  const muted = resolve('var(--text-muted)');
  const stoppedGrey = resolve('var(--color-text-tertiary, #999)');
  probe.remove();
  const s = getComputedStyle(dot);
  return JSON.stringify({
    classes: Array.from(dot.classList),
    text: text.textContent.trim(),
    border: s.borderTopColor,
    background: s.backgroundColor,
    width: s.width,
    muted: muted,
    stoppedGrey: stoppedGrey,
  });
})()
"""

THEME = "(() => {{ _wimiApplyThemeVariables('{0}'); return JSON.stringify({{ok: true}}); }})()"


def _poll(wimi_page: WimiPage, js: str, *, timeout_ms: int = 20000):
    """Poll ``js`` until it returns something other than ``null``."""
    for _ in range(timeout_ms // 200):
        try:
            result = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            result = None
        if result is not None:
            return json.loads(result)
        wimi_page.wait_for_timeout(200)
    return None


def _assert_muted_ring(state: dict, theme: str) -> None:
    """The dot is a ring in the palette's muted colour, not a filled state dot."""
    assert 'unknown' in state['classes'], (
        f"_setMcpStatusUnavailable left the dot as {state['classes']!r} under "
        f'{theme}; the unresolved state is the one thing it exists to paint.'
    )
    assert not set(state['classes']) & set(DETERMINED), (
        f"The unresolved dot carries {state['classes']!r} under {theme} -- one of the "
        f'three determined states. "We could not read the status" is being rendered '
        f'as a claim about the server.'
    )
    assert state['border'] == state['muted'], (
        f"The unknown dot's border resolves to {state['border']!r} under {theme} "
        f"while --text-muted is {state['muted']!r}. A border that does not follow "
        f'the palette is either a hardcoded colour or a token the theme system '
        f'cannot reach -- and if the declaration were discarded outright the dot '
        f'would paint nothing at all, since .mcp-status-dot sets only size and shape.'
    )
    assert state['background'] in ('rgba(0, 0, 0, 0)', 'transparent'), (
        f"The unknown dot is filled with {state['background']!r} under {theme} "
        f'instead of hollow. The ring is what distinguishes "not yet asked" from '
        f'the grey .stopped dot it may be one refresh away from becoming.'
    )
    assert state['border'] != state['stoppedGrey'], (
        f"Under {theme} the unknown ring and the .stopped fill are both "
        f"{state['border']!r}; the new state is indistinguishable from the state it "
        f'was introduced to stop impersonating.'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_unresolved_mcp_status_paints_a_muted_ring_in_both_themes(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The neutral state renders, and follows the theme, in light and dark."""
    # ---- Arrange -----------------------------------------------------
    wimi_page.goto('settings')
    settled = _poll(wimi_page, SETTLED)
    assert settled is not None, 'refreshMcpStatus never resolved; nothing below is timed'
    assert settled['settled'] != SHIPPED_TEXT, (
        f'The status text is still {SHIPPED_TEXT!r} after init settled. The neutral '
        f'state is meant to be transient -- if JavaScript never replaces it, the row '
        f'has traded a wrong answer for no answer.'
    )

    panel = _poll(wimi_page, OPEN_PANEL)
    assert panel is not None and panel['active'], (
        f'The MCP panel did not activate ({panel}); a dot in a display:none subtree '
        f'has no used width, so the ring check below would prove nothing.'
    )

    # ---- Act / Assert: the default (light) theme ---------------------
    light = json.loads(wimi_page.eval_js(PROBE))
    assert light['text'] == 'Status unavailable', (
        f"The failed-read path rendered {light['text']!r}. Before #90 it rendered "
        f'nothing at all and left the shipped "Stopped" standing, so a bridge that '
        f'could not answer the question looked like a confident answer to it.'
    )
    assert light['width'] == '10px', (
        f"The dot computes to {light['width']} wide; it is not being laid out, so "
        f'the colours read below are not the ones a student would see.'
    )
    _assert_muted_ring(light, 'the default theme')

    # ---- Assert: the same, under a dark theme ------------------------
    wimi_page.eval_js(THEME.format('midnight'))
    dark = json.loads(wimi_page.eval_js(PROBE))
    assert dark['muted'] != light['muted'], (
        f"Midnight resolved --text-muted to {dark['muted']!r}, the same as the default "
        f'theme; the theme switch did not take, so the check below is vacuous.'
    )
    _assert_muted_ring(dark, 'Midnight')
