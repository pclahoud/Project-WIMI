"""Resolve CSS declarations on a live page, under every theme, with a control.

Shared by the dead-token scenarios (#76 / #81 / #97 / #102). Extracted per
``tests/wimi_test/scenarios/README.md``'s file-size budget: the machinery is
the same for any future filing in that family, while each scenario keeps only
its own table of targets.

The thing this exists to make possible: an undefined ``var()`` still computes
to *something*, so asserting "there is a colour" proves nothing. Declarations
are read out of the page's own stylesheets through CSSOM — which is also what
lets ``:hover`` rules be checked at all — and re-resolved on a probe in the
real document, so every value follows whichever theme is applied rather than a
hex copied into a test file.

A target is ``[selectorText, property to set on the probe, computed property
to read back, the palette token it must resolve to, the pre-fix declaration
verbatim]``. That last entry is the control, and :func:`check_across_themes`
fails if it agrees with its token in all six themes — a comparison that cannot
fail proves nothing about the fix. Pass ``None`` for it only where the repoint
was a dead *nested* fallback that already resolved to a real token.
"""
from __future__ import annotations

import json

from wimi_test.page import WimiPage


THEMES = ['default', 'midnight', 'warm_study', 'forest', 'nord', 'high_contrast']

# Reads each target's declaration out of the page's own stylesheets, then
# resolves three things on one probe in the live document: the shipped
# declaration, the palette token it should name, and the pre-fix declaration.
# Everything goes through the real cascade, so the values follow whichever
# theme is applied rather than a hex copied into this file.
PROBE = """
(() => {
  const wanted = __TARGETS__;
  const byselector = {};
  // A CSSStyleRule also exposes `cssRules` (nested CSS), so recursing on the
  // mere presence of that list skips every rule there is. Record the selector
  // first, then descend only into a list that has something in it.
  const collect = (rules) => {
    for (const rule of rules) {
      if (rule.selectorText) {
        byselector[rule.selectorText.replace(/\\s+/g, ' ').trim()] = rule;
      }
      if (rule.cssRules && rule.cssRules.length) collect(rule.cssRules);
    }
  };
  for (const sheet of document.styleSheets) {
    try { collect(sheet.cssRules); } catch (e) { /* cross-origin */ }
  }
  const probe = document.createElement('span');
  document.body.appendChild(probe);
  const resolve = (setProp, value, readProp) => {
    probe.style.cssText = '';
    probe.style.setProperty(setProp, value);
    return getComputedStyle(probe)[readProp];
  };
  const out = {};
  for (const [label, spec] of Object.entries(wanted)) {
    const [selector, setProp, readProp, token, deadDecl] = spec;
    const rule = byselector[selector];
    const declared = rule ? rule.style.getPropertyValue(setProp) : null;
    out[label] = {
      found: !!rule,
      declared: declared,
      shipped: declared ? resolve(setProp, declared, readProp) : null,
      token: resolve(setProp, token, readProp),
      dead: deadDecl ? resolve(setProp, deadDecl, readProp) : null,
    };
  }
  probe.remove();
  return JSON.stringify(out);
})()
"""

# The note card is the one target also measured as a laid-out box, the way
# #97's scenario does it, so this file is not purely CSSOM.
NOTE_CARD_PROBE = """
(() => {
  const host = document.createElement('div');
  document.body.appendChild(host);
  host.innerHTML =
    '<div class="note-card"><div class="note-card-header">h</div></div>';
  const card = host.querySelector('.note-card');
  const header = host.querySelector('.note-card-header');
  const probe = document.createElement('span');
  document.body.appendChild(probe);
  const resolve = (value) => {
    probe.style.cssText = '';
    probe.style.setProperty('background', value);
    return getComputedStyle(probe).backgroundColor;
  };
  const res = {
    cardBackground: getComputedStyle(card).backgroundColor,
    cardWidth: getComputedStyle(card).width,
    headerBackground: getComputedStyle(header).backgroundColor,
    bgPrimary: resolve('var(--bg-primary)'),
    bgSecondary: resolve('var(--bg-secondary)'),
  };
  host.remove();
  probe.remove();
  return JSON.stringify(res);
})()
"""

# #102's separate finding: `.weight-slider-track` never rendered — the class
# is applied nowhere in src/ and nothing ever set --fill-percent — so the
# rule was deleted rather than repointed.
SLIDER_TRACK_PROBE = """
(() => {
  let found = false;
  const walk = (rules) => {
    for (const rule of rules) {
      if (rule.selectorText && rule.selectorText.includes('weight-slider-track')) {
        found = true;
      }
      if (rule.cssRules && rule.cssRules.length) walk(rule.cssRules);
    }
  };
  for (const sheet of document.styleSheets) {
    try { walk(sheet.cssRules); } catch (e) { /* cross-origin */ }
  }
  return JSON.stringify({
    ruleStillPresent: found,
    classUsed: !!document.querySelector('.weight-slider-track'),
  });
})()
"""

THEME = ("(() => {{ _wimiApplyThemeVariables('{0}'); "
         "return JSON.stringify({{ok: true}}); }})()")


def _read(page: WimiPage, targets: dict) -> dict:
    return json.loads(page.eval_js(PROBE.replace('__TARGETS__', json.dumps(targets))))


def check_across_themes(page: WimiPage, targets: dict, where: str) -> None:
    """Assert every target follows its token in all six themes, with a control.

    The control requirement is per target and per file: a pre-fix declaration
    that agrees with its token in *every* theme cannot distinguish the fix from
    the bug, so the target's other assertions would be vacuous.
    """
    discriminated: dict[str, bool] = {label: False for label in targets}
    token_moved = False
    first_tokens: dict[str, str] = {}

    for theme in THEMES:
        page.eval_js(THEME.format(theme))
        state = _read(page, targets)

        for label, spec in targets.items():
            got = state[label]
            assert got['found'], (
                f'No rule matched {spec[0]!r} on {where}. The stylesheet is not '
                'linked here, or the rule was deleted — either way this check '
                'cannot tell a fixed declaration from a missing one.'
            )
            assert got['declared'] and got['declared'].strip(), (
                f'{label} on {where} declares nothing for {spec[1]!r}.'
            )
            assert '--' not in got['declared'] or 'var(' in got['declared'], (
                f'{label} declares {got["declared"]!r}, which is not a var().'
            )
            assert got['shipped'] == got['token'], (
                f'{label} on {where} resolves to {got["shipped"]!r} under '
                f'{theme} while {spec[3]} resolves to {got["token"]!r}. The '
                f'declaration is {got["declared"]!r} — a value that does not '
                'follow the palette is pinned to a hardcoded colour, which is '
                'the whole of this bug family (#76, #81, #97, #102).'
            )
            if got['dead'] is not None and got['dead'] != got['token']:
                discriminated[label] = True
            if label in first_tokens and first_tokens[label] != got['token']:
                token_moved = True
            first_tokens.setdefault(label, got['token'])

    assert token_moved, (
        f'No token on {where} resolved differently in any of {THEMES}; the theme '
        'switch never took, so every assertion above is about one palette.'
    )
    for label, spec in targets.items():
        if spec[4] is None:
            continue  # nested dead fallback: it already resolved correctly
        assert discriminated[label], (
            f'The pre-fix declaration for {label} ({spec[4]}) resolves to the same '
            f'value as {spec[3]} in all six themes, so this target cannot tell the '
            'fix from the bug. That is exactly how #97 survived three filings — '
            'find a theme where they differ or the assertion is worthless.'
        )


