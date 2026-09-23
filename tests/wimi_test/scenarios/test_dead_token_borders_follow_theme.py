"""Regression: the eight declarations that guarded a dead token must follow the theme.

Forgejo issue #97 -- "The same dead tokens used *with* a hardcoded fallback
paint a light-theme border in every dark theme":

    ``--color-border`` and ``--font-size-base`` are defined nowhere. #76 and
    #81 fixed the half of that rename written ``var(--X)`` with no fallback,
    where the declaration is discarded outright. This is the other half:
    ``var(--color-border, #e0e0e0)`` is *valid*, so nothing complained -- it
    simply resolved to the fallback every single time. Six borders across
    ``settings.css`` and ``entry.css`` were therefore pinned to a near-white
    hairline (``#e0e0e0`` / ``#e2e8f0`` / ``#ccc``) that glares against every
    dark palette, while every neighbouring border followed ``--border-color``.

What the fix changes: both names are gone from ``src/``. The six borders name
``var(--border-color)``, which every theme dictionary in ``themes.js`` carries.
``weight.css``'s ``var(--font-size-base, 0.9375rem)`` became
``var(--font-size-sm)`` -- 15px is not on the scale, and every other text rule
in that same card is already ``--font-size-sm``. ``tree.css``'s subtitle
separator became ``var(--text-muted)`` and NOT ``--border-color``: it is text,
and a border grey on a dark ground is near-invisible. That is a zero-pixel
change, because ``> * + *::before`` cannot attach to a first child,
``renderDetailSubtitle`` always emits ``.details-subtitle-level`` first, and
every span that can follow it is itself ``--text-muted``.

Why these assertions catch the regression: a hardcoded fallback *does* paint,
so "is there a border colour" proves nothing -- that is exactly how this
survived three filings. Every assertion compares against the token resolved
live on the same page, runs again under Midnight where the token moves, and
carries a negative control: the pre-fix declaration itself
(``var(--color-border, #e0e0e0)``) is resolved on the same probe, and the test
asserts the two disagree under Midnight. If they ever agree, the comparison has
stopped discriminating and the rest of the file is vacuous.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Injected into the live document so the real cascade applies to real boxes.
# These rules key off classes no JS creates on a blank page (a note card needs
# saved notes; the breakdown card needs analytics), so they are built rather
# than triggered -- the stylesheet, the theme and the cascade are the page's.
ENTRY_HTML = '<div class="note-card"><div class="note-card-header">h</div></div>'
TREE_HTML = (
    '<div class="weight-source-breakdown-card"><ul class="breakdown-list">'
    '<li class="breakdown-row">r</li></ul></div>'
    '<div class="details-subtitle"><span class="details-subtitle-level">a</span>'
    '<span class="details-subtitle-parents">b</span></div>'
)

# label -> (selector, pseudo-element or null, computed property to read).
ENTRY_TARGETS = {
    'note-card border': ['.note-card', None, 'borderTopColor'],
    'note-card-header border-bottom': ['.note-card-header', None, 'borderBottomColor'],
}
TREE_TARGETS = {
    'breakdown-row border': ['.breakdown-row', None, 'borderTopColor'],
    'subtitle separator colour': ['.details-subtitle-parents', '::before', 'color'],
}
SETTINGS_TARGETS = {
    'mcp-connect-instructions border-top': ['#mcpConnectInstructions', None,
                                            'borderTopColor'],
    'mcp-config-block border': ['.mcp-config-block', None, 'borderTopColor'],
    'mcp-config-header border-bottom': ['.mcp-config-header', None,
                                        'borderBottomColor'],
    'mcp-copy-btn border': ['.mcp-copy-btn', None, 'borderTopColor'],
}

# Resolve every value through the real cascade on a live probe, so the
# comparison follows the theme rather than a hex copied into this file.
# `dead*` are the pre-fix declarations verbatim: the negative controls.
PROBE = """
(() => {
  __PREPARE__
  const host = document.createElement('div');
  document.body.appendChild(host);
  host.innerHTML = __HTML__;
  const probe = document.createElement('span');
  document.body.appendChild(probe);
  const resolve = (prop, value, read) => {
    probe.style.cssText = '';
    probe.style.setProperty(prop, value);
    return getComputedStyle(probe)[read];
  };
  const scope = __HTML__ === '' ? document : host;
  const out = {}, widths = {};
  for (const [label, spec] of Object.entries(__TARGETS__)) {
    const el = scope.querySelector(spec[0]);
    out[label] = el ? getComputedStyle(el, spec[1])[spec[2]] : null;
    widths[label] = el ? getComputedStyle(el).width : null;
  }
  const res = {
    targets: out,
    widths: widths,
    borderColor: resolve('border-top-color', 'var(--border-color)', 'borderTopColor'),
    textMuted: resolve('color', 'var(--text-muted)', 'color'),
    deadGrey: resolve('border-top-color', 'var(--color-border, #e0e0e0)',
                      'borderTopColor'),
    deadSlate: resolve('border-top-color', 'var(--color-border, #e2e8f0)',
                       'borderTopColor'),
    fontSm: resolve('font-size', 'var(--font-size-sm)', 'fontSize'),
    deadFont: resolve('font-size', 'var(--font-size-base, 0.9375rem)', 'fontSize'),
    rowFont: (() => {
      const r = scope.querySelector('.breakdown-row');
      return r ? getComputedStyle(r).fontSize : null;
    })(),
  };
  host.remove();
  probe.remove();
  return JSON.stringify(res);
})()
"""

# The MCP panel is display:none until its nav item is picked, and the
# instructions block until the server reports running. A box in a display:none
# subtree reports `width: auto` rather than a used width, which would make the
# layout check below vacuous. This runs inside the read, not before it: the
# block is shown and measured in one evaluation, so the tail of
# `refreshMcpStatus` cannot re-hide it in between.
SHOW_MCP_PANEL = """
  const nav = document.querySelector('.settings-nav-item[data-panel="mcp_server"]');
  if (nav) nav.click();
  const block = document.getElementById('mcpConnectInstructions');
  if (block) block.style.display = 'block';
"""

# `refreshMcpStatus` runs at the tail of `init()` and rewrites this panel when
# it resolves. Wait for it, so the theme pass below is not racing a late write.
MCP_SETTLED = """
(() => {
  if (typeof settingsPage === 'undefined' || !settingsPage) return null;
  const text = document.getElementById('mcpStatusText');
  if (!text) return null;
  const settled = text.textContent.trim();
  if (settled === '' || settled.startsWith('Checking')) return null;
  return JSON.stringify({settled: settled});
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


def _read(wimi_page: WimiPage, targets: dict, html: str = '', prepare: str = '') -> dict:
    """Resolve every target plus the live reference values on the current page.

    ``prepare`` runs in the *same* evaluation as the read, so nothing the page
    does asynchronously can land between making an element visible and
    measuring it.
    """
    js = PROBE.replace('__TARGETS__', json.dumps(targets))
    js = js.replace('__HTML__', json.dumps(html))
    return json.loads(wimi_page.eval_js(js.replace('__PREPARE__', prepare)))


def _assert_borders(state: dict, targets: dict, theme: str) -> None:
    """Every listed border resolves to whatever --border-color resolves to."""
    for label in targets:
        assert state['targets'][label] is not None, (
            f'No element matched {label!r} on this page ({theme}); the check cannot '
            'tell a fixed rule from a deleted one.'
        )
        assert state['widths'][label] not in (None, 'auto', '0px'), (
            f'{label} computes to {state["widths"][label]} wide under {theme}; it is '
            'not being laid out, so the colour read from it is not one a student sees.'
        )
        assert state['targets'][label] == state['borderColor'], (
            f'{label} resolves to {state["targets"][label]!r} under {theme} while '
            f'--border-color is {state["borderColor"]!r}. A border that does not '
            'follow the palette is pinned to a hardcoded colour -- which is #97: the '
            'var() named a token defined nowhere, so the fallback always won.'
        )


def _assert_controls(state: dict, theme: str) -> None:
    """The pre-fix declarations must disagree with the fixed ones, or nothing here bites.

    Dark themes only, and that restriction is the whole story of this bug.
    ``styles.css`` sets ``--border-color: var(--color-gray-200)`` and
    ``--color-gray-200`` is ``#e2e8f0`` -- the exact hex ``entry.css``
    hardcoded. Under the default light theme the broken declaration and the
    correct one therefore resolve to the *same* colour, so a light-theme check
    cannot tell them apart no matter how it is written. That coincidence is why
    six borders shipped wrong through three filings: the only place they ever
    looked wrong is a palette nobody was testing in.
    """
    for name in ('deadGrey', 'deadSlate'):
        assert state[name] != state['borderColor'], (
            f'Under {theme} the pre-fix declaration resolves to {state[name]!r}, the '
            f'same as --border-color. The assertions in this file cannot fail, so '
            'they prove nothing about the fix.'
        )
    assert state['deadFont'] != state['fontSm'], (
        f'Under {theme} var(--font-size-base, 0.9375rem) resolves to '
        f'{state["deadFont"]!r}, the same as --font-size-sm; the font check below is '
        'vacuous.'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_mcp_panel_borders_follow_the_palette_in_both_themes(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """settings.css's four repointed borders, on the panel that owns them."""
    # ---- Arrange -----------------------------------------------------
    wimi_page.goto('settings')
    assert _poll(wimi_page, MCP_SETTLED) is not None, (
        'refreshMcpStatus never resolved; a late write could re-hide the panel '
        'between the two theme passes below.'
    )

    # ---- Act / Assert: the default (light) theme ---------------------
    light = _read(wimi_page, SETTINGS_TARGETS, prepare=SHOW_MCP_PANEL)
    _assert_borders(light, SETTINGS_TARGETS, 'the default theme')

    # ---- Assert: the same, under a dark theme ------------------------
    wimi_page.eval_js(THEME.format('midnight'))
    dark = _read(wimi_page, SETTINGS_TARGETS, prepare=SHOW_MCP_PANEL)
    assert dark['borderColor'] != light['borderColor'], (
        f'Midnight resolved --border-color to {dark["borderColor"]!r}, the same as the '
        'default theme; the theme switch did not take, so the check below is vacuous.'
    )
    _assert_controls(dark, 'Midnight')
    _assert_borders(dark, SETTINGS_TARGETS, 'Midnight')


@pytest.mark.slow
@pytest.mark.regression
def test_note_card_breakdown_row_and_separator_follow_the_palette(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """entry.css's two borders, weight.css's font size and tree.css's separator."""
    # ---- Arrange / Act / Assert: the entry form ----------------------
    wimi_page.goto('entry-form')
    light = _read(wimi_page, ENTRY_TARGETS, ENTRY_HTML)
    _assert_borders(light, ENTRY_TARGETS, 'the default theme')

    wimi_page.eval_js(THEME.format('midnight'))
    dark = _read(wimi_page, ENTRY_TARGETS, ENTRY_HTML)
    assert dark['borderColor'] != light['borderColor'], (
        f'Midnight resolved --border-color to {dark["borderColor"]!r}, the same as the '
        'default theme; the theme switch did not take.'
    )
    _assert_controls(dark, 'Midnight')
    _assert_borders(dark, ENTRY_TARGETS, 'Midnight')

    # ---- The tree editor owns both weight.css and tree.css -----------
    wimi_page.goto('tree-editor')
    wimi_page.eval_js(THEME.format('midnight'))
    tree = _read(wimi_page, TREE_TARGETS, TREE_HTML)
    _assert_controls(tree, 'Midnight')
    _assert_borders(tree, {'breakdown-row border': TREE_TARGETS['breakdown-row border']},
                    'Midnight')

    assert tree['rowFont'] == tree['fontSm'], (
        f'The breakdown row renders at {tree["rowFont"]!r} while --font-size-sm is '
        f'{tree["fontSm"]!r}. 0.9375rem is not a step on the scale, and every other '
        'text rule in that card is --font-size-sm.'
    )
    # The separator is text, so it must track --text-muted, not the border grey.
    assert tree['targets']['subtitle separator colour'] == tree['textMuted'], (
        f'The subtitle separator renders '
        f'{tree["targets"]["subtitle separator colour"]!r} under Midnight while '
        f'--text-muted is {tree["textMuted"]!r}.'
    )
    assert tree['textMuted'] != tree['borderColor'], (
        'Under Midnight --text-muted and --border-color resolve alike, so the check '
        'above cannot tell the separator being repointed at the border grey -- the '
        'one repoint #97 explicitly warns against -- from the correct one.'
    )
