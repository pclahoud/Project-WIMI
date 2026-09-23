"""Regression: the alias manager must render with real spacing.

Forgejo issue #81 -- "Nine more custom properties are used with no fallback
and defined nowhere":

    ``src/web/css/aliases.css`` used ``--spacing-xs`` / ``-sm`` / ``-md`` /
    ``-lg`` / ``-xl`` in 32 declarations. The scale is ``--space-*``; no
    ``--spacing-*`` token is defined anywhere -- not in a stylesheet, not in
    a ``themes.js`` theme dictionary, not by a ``setProperty`` call, not in
    an inline style. A ``var()`` naming an undefined property with **no
    fallback** is invalid at computed-value time, so the declaration is
    discarded and the property falls to its initial value. For ``padding``,
    ``margin`` and ``gap`` that initial value is ``0``.

    The issue's own reproduction: "open the alias manager on the tree editor
    (Manage Aliases) and inspect any ``.alias-*`` element -- every
    ``padding``/``margin``/``gap`` computes to ``0px`` while the stylesheet
    declares ``var(--spacing-md)``."

    Also in scope on the two other files this scenario covers:
    ``tree.css`` used ``--color-border`` (the token is ``--border-color``)
    and ``--text-tertiary`` (it is ``--text-muted``); ``analytics.css`` used
    ``--color-accent``, which no palette entry has ever defined, as the
    second stop of a ``linear-gradient`` -- and one invalid stop invalidates
    the whole gradient, so the bar drew nothing.

What the fix changes: every one of those uses is repointed at the token that
exists. Nothing new was defined. ``--color-accent`` became
``--color-primary-light``, matching the identical gradient already declared
at ``landing.css:179``.

Why these assertions catch the regression
-----------------------------------------
"Is the padding non-zero" is necessary but far too weak on its own: someone
could re-break the token and paper over it with a hardcoded ``1rem``. So
every assertion compares the element's computed value against
``var(--space-*)`` **resolved live on the same page**, and then moves the
token and re-reads.

That second pass is the load-bearing one, and it is the reason the fix had
to repoint rather than define ``--spacing-md`` as an alias in ``styles.css``:
the ``ui_density`` preference rewrites ``--space-sm`` / ``-md`` / ``-lg`` /
``-xl`` at runtime as inline properties on the root element (``themes.js``,
``settings.js``). A static alias would have looked correct here and then
quietly ignored the user's density setting forever. Moving the token and
requiring the padding to follow is exactly that check.

Companion: ``test_danger_colour_resolves.py`` (#76) is the same bug, one
token earlier, and its sweep helper is the model for the one below.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


# (element selector, computed property to read, the token it must resolve to).
# Every one of these declarations named a --spacing-* token before the fix and
# therefore computed to 0px.
ALIAS_BOXES = [
    ['.alias-manager .modal-header', 'paddingBottom', 'var(--space-md)'],
    ['.alias-manager .modal-header', 'marginBottom', 'var(--space-md)'],
    ['.alias-manager .modal-title', 'columnGap', 'var(--space-sm)'],
    ['.alias-manager-subject', 'paddingTop', 'var(--space-sm)'],
    ['.alias-manager-subject', 'paddingLeft', 'var(--space-md)'],
    ['.alias-manager-subject', 'marginBottom', 'var(--space-md)'],
    ['#alias-new-name', 'paddingTop', 'var(--space-sm)'],
    ['#alias-new-name', 'paddingLeft', 'var(--space-md)'],
]

# (exact selectorText, declared property, computed property, the value it must
# resolve to). Swept from the loaded stylesheet rather than triggered: these
# style states no JS sets on a resting page.
#
# The selector is matched exactly, not as a substring: `.parent-row` is a
# substring of `.parent-row-action`, which declares `border: none`, and a
# substring sweep silently reads that instead -- reporting a bug that is not
# there while saying nothing about the rule under test.
#
# All seven of tree.css's #81 declarations are here.
TREE_RULES = [
    ['.parent-row', 'border', 'borderTopColor', 'var(--border-color)'],
    ['.parent-row.is-primary', 'border-color', 'borderTopColor',
     'color-mix(in srgb, var(--color-primary) 20%, var(--border-color))'],
    ['.parent-row.confirming', 'border-color', 'borderTopColor',
     'color-mix(in srgb, var(--color-warning) 30%, var(--border-color))'],
    ['.parents-picker', 'border', 'borderTopColor', 'var(--border-color)'],
    ['.parents-picker-input', 'border', 'borderTopColor', 'var(--border-color)'],
    ['.dimension-selector-help', 'color', 'color', 'var(--text-muted)'],
    ['.dimension-info-stats', 'color', 'color', 'var(--text-muted)'],
]
# Both of analytics.css's.
ANALYTICS_RULES = [
    ['.time-bar-fill', 'background', 'backgroundImage',
     'linear-gradient(90deg, var(--color-primary), var(--color-primary-light))'],
    ['.warning-icon', 'font-size', 'fontSize', 'var(--font-size-md)'],
]

# Resolve a value through the real cascade on a live probe in the same
# document. Reading the declaration alone would report var(--spacing-md) as
# happily as var(--space-md); only the computed value says whether the browser
# kept the declaration or threw it away.
BOXES = """
(() => {
  const probe = document.createElement('div');
  document.body.appendChild(probe);
  const resolve = (read, value) => {
    probe.style.cssText = '';
    probe.style.setProperty(read.replace(/[A-Z]/g, c => '-' + c.toLowerCase()), value);
    return getComputedStyle(probe)[read];
  };
  const out = [];
  for (const [sel, read, want] of __BOXES__) {
    const el = document.querySelector(sel);
    out.push({
      box: sel + ' { ' + read + ' }',
      found: el !== null,
      computed: el ? getComputedStyle(el)[read] : null,
      expected: resolve(read, want),
    });
  }
  probe.remove();
  return JSON.stringify({boxes: out});
})()
"""

SWEEP = """
(() => {
  const probe = document.createElement('div');
  document.body.appendChild(probe);
  const resolve = (prop, value, read) => {
    probe.style.cssText = '';
    probe.style.setProperty(prop, value);
    return getComputedStyle(probe)[read];
  };
  const out = [];
  for (const [sel, prop, read, want] of __RULES__) {
    let declared = null;
    for (const sheet of document.styleSheets) {
      let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
      for (const rule of rules) {
        if (rule.selectorText === sel) {
          const v = rule.style.getPropertyValue(prop);
          if (v) declared = v;
        }
      }
    }
    out.push({
      rule: sel + ' { ' + prop + ' }',
      declared: declared,
      computed: declared === null ? null : resolve(prop, declared, read),
      expected: resolve(prop, want, read),
    });
  }
  probe.remove();
  return JSON.stringify({rules: out});
})()
"""

OPEN_MANAGER = """
(() => {{
  if (typeof AliasManager === 'undefined') return null;
  AliasManager.open({0}, {1}, 'Pneumonia');
  const modal = document.getElementById('alias-manager-modal');
  if (!modal || !modal.classList.contains('active')) return null;
  if (!document.querySelector('.alias-manager-subject')) return null;
  return JSON.stringify({{open: true}});
}})()
"""

# Stand in for the ui_density preference without a preference round-trip: it
# writes exactly these inline properties on the root element.
DENSITY = """
(() => {
  document.documentElement.style.setProperty('--space-md', '3.5rem');
  document.documentElement.style.setProperty('--space-sm', '2.5rem');
  return JSON.stringify({moved: true});
})()
"""


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


def _assert_boxes(wimi_page: WimiPage, *, phase: str, zero_ok: bool = False) -> None:
    """Every listed element's box metric equals what its token resolves to."""
    report = json.loads(wimi_page.eval_js(BOXES.replace('__BOXES__', json.dumps(ALIAS_BOXES))))
    for row in report['boxes']:
        assert row['found'], (
            f"No element matches {row['box']} ({phase}); the check cannot tell a "
            'restyled modal from an unrendered one.'
        )
        if not zero_ok:
            assert row['expected'] != '0px', (
                f"{row['box']} expects 0px ({phase}) -- the token this compares against "
                'resolved to nothing, so the assertion below would pass on the bug.'
            )
        assert row['computed'] == row['expected'], (
            f"{row['box']} computes to {row['computed']!r} ({phase}) while its token "
            f"resolves to {row['expected']!r}. That is #81: the declaration names a "
            'custom property defined nowhere, so it is discarded and the property '
            'falls to its initial value.'
        )


def _assert_sweep(wimi_page: WimiPage, rules: list, page: str) -> None:
    """Every listed declaration resolves to what its token resolves to."""
    report = json.loads(wimi_page.eval_js(SWEEP.replace('__RULES__', json.dumps(rules))))
    for row in report['rules']:
        assert row['declared'] is not None, (
            f"No rule declaring {row['rule']} is loaded on {page}; the sweep cannot "
            'tell a fixed rule from a deleted one.'
        )
        assert row['computed'] == row['expected'], (
            f"{row['rule']} declares {row['declared']!r}, which computes to "
            f"{row['computed']!r} on {page} while its token resolves to "
            f"{row['expected']!r}. An undefined var() with no fallback is discarded."
        )


def _open_alias_manager(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    """Seed one subject, open the tree editor, and open its alias manager."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Alias Spacing Exam', exam_description='')
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name='Pneumonia', level_type='System',
    )
    wimi_page.goto('tree-editor')
    opened = _poll(
        wimi_page, OPEN_MANAGER.format(subject.id, json.dumps(exam.exam_name)),
    )
    assert opened is not None, 'The alias manager never opened; nothing below is meaningful.'


@pytest.mark.slow
@pytest.mark.regression
def test_alias_manager_spacing_follows_the_space_scale(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The modal's padding, margins and gaps render, and track the token."""
    # ---- Arrange -----------------------------------------------------
    _open_alias_manager(wimi_session, wimi_page)

    # ---- Assert: the issue's repro -- no .alias-* metric may be 0px ---
    _assert_boxes(wimi_page, phase='default density')

    # ---- Assert: and it is the live token, not a hardcoded rem -------
    # The ui_density preference rewrites --space-* on the root element. A
    # declaration pinned to a value of its own, or reading a statically
    # defined --spacing-* alias, would sit still while the scale moved.
    assert json.loads(wimi_page.eval_js(DENSITY))['moved'] is True
    _assert_boxes(wimi_page, phase='after the spacing scale moved')


@pytest.mark.slow
@pytest.mark.regression
def test_tree_and_analytics_tokens_resolve(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#81's other two files: the borders paint and the gradient draws."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Token Sweep Exam', exam_description='')
    db.create_subject_node(
        exam_context=exam.exam_name, name='Pneumonia', level_type='System',
    )

    # ---- Act / Assert ------------------------------------------------
    # .parent-row's border is the sharp end: two of tree.css's --color-border
    # uses sat inside color-mix(), and an invalid var() there invalidates the
    # whole color-mix, so border-color was dropped and the cascade fell back
    # to a `border` shorthand that was itself invalid -- leaving border-style
    # at its initial `none`. The rows had no border at all.
    wimi_page.goto('tree-editor')
    _assert_sweep(wimi_page, TREE_RULES, 'the tree editor')

    wimi_page.goto('analytics')
    _assert_sweep(wimi_page, ANALYTICS_RULES, 'the analytics dashboard')
