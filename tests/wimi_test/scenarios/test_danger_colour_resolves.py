"""Regression: every "danger" rule must resolve to the palette red.

Forgejo issue #76 -- "Entry form: five CSS rules paint nothing because
--color-danger is never defined":

    ``entry.css`` used ``var(--color-danger)`` with no fallback in five
    places and that custom property is defined nowhere in the project. A
    ``var()`` naming an undefined property with no fallback is invalid at
    computed-value time, so the declaration is discarded. The worst of the
    five is ``.entry-form.show-missing .field-has-error > label``: the half
    of the missing-field cue that *names* the field has never rendered for
    any field. It looked like it worked only because the other half
    (``box-shadow: inset 2px 0 0 var(--color-error)``) uses a defined token.
    Four further uses passed a ``#dc2626`` fallback and did paint -- a
    second, different red for the same meaning.

What the fix changes: ``--color-danger`` is gone. All eleven declarations
(nine in ``entry.css``, two in ``tree.css``) now use ``--color-error`` /
``--color-error-bg``, the palette's single red. No new token was added:
``.btn-danger`` in ``styles.css`` -- the project's own destructive-action
component -- was already painted with ``var(--color-error)``, so "danger"
and "error" were never distinct here. A second token could not have been
themed either: ``_wimiApplyThemeVariables`` applies each theme as inline
custom properties on the root element, so it only reaches the names the six
theme dictionaries in ``themes.js`` list.

Why these assertions catch the regression: an undefined ``var()`` still
*computes* to something -- the initial value for ``background-color``, the
inherited one for ``color`` -- so "is there a colour" proves nothing. Every
assertion compares against ``--color-error`` resolved live on the same page,
and every one runs again under Midnight, where the palette red moves to
``#f87171``. That second pass is what rules out both a hardcoded hex and a
statically defined ``--color-danger``: either would sit still while the
theme moved.

Companion: ``test_entry_form_missing_field_cue.py`` (#40) drives the same
cue and deliberately does not depend on this token.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

RED = 'var(--color-error)'
RED_BG = 'var(--color-error-bg)'

# (selector fragment, declared property, computed property, expected value).
# The fragment is a substring of the rule's selectorText, so a rule can grow
# a :not() or a parent without breaking the lookup.
ENTRY_RULES = [
    ['.chip-remove:hover', 'background', 'backgroundColor', RED],
    ['.media-thumbnail-btn.delete:hover', 'background', 'backgroundColor', RED],
    ['.form-group.error input', 'border-color', 'borderTopColor', RED],
    ['.form-group.error .form-help', 'color', 'color', RED],
    ['.field-has-error > label', 'color', 'color', RED],
    ['.btn-danger-text:hover', 'background', 'backgroundColor', RED_BG],
    ['.btn-danger-text:hover', 'color', 'color', RED],
    ['.manage-tag-delete:hover', 'background', 'backgroundColor', RED_BG],
    ['.manage-tag-delete:hover', 'border-color', 'borderTopColor', RED],
]
TREE_RULES = [
    ['.parent-row-action.danger:hover', 'background', 'backgroundColor',
     f'color-mix(in srgb, {RED} 12%, transparent)'],
    ['.parent-row-action.danger:hover', 'color', 'color', RED],
]

# Take each rule's declared value and resolve it through the real cascade on
# a live probe. Reading the declaration alone would report var(--color-danger)
# as happily as var(--color-error); only the computed value says whether the
# browser kept the declaration or threw it away.
SWEEP = """
(() => {
  const probe = document.createElement('span');
  document.body.appendChild(probe);
  const resolve = (prop, value, read) => {
    probe.style.cssText = '';
    probe.style.setProperty(prop, value);
    return getComputedStyle(probe)[read];
  };
  const out = [];
  for (const [frag, prop, read, want] of __RULES__) {
    let declared = null;
    for (const sheet of document.styleSheets) {
      let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
      for (const rule of rules) {
        if (rule.selectorText && rule.selectorText.includes(frag)) {
          const v = rule.style.getPropertyValue(prop);
          if (v) declared = v;
        }
      }
    }
    out.push({
      rule: frag + ' { ' + prop + ' }',
      declared: declared,
      computed: declared === null ? null : resolve(prop, declared, read),
      expected: resolve(prop, want, read),
    });
  }
  probe.remove();
  return JSON.stringify({rules: out});
})()
"""

READY = """
(() => {
  if (typeof EntryState === 'undefined') return null;
  const r = EntryState.reflectionEditor, e = EntryState.explanationEditor;
  if (!r || !e || !r.isInitialized || !e.isInitialized) return null;
  return JSON.stringify({ready: true});
})()
"""

# Typing into Your Answer arms show-missing and fills that one field, so the
# two labels read below -- one .fact-line, one .write-block -- stay missing.
ARM = """
(() => {
  const a = document.getElementById('user-answer');
  a.value = 'B';
  a.dispatchEvent(new Event('input', {bubbles: true}));
  return JSON.stringify({armed:
    document.getElementById('entry-form').classList.contains('show-missing')});
})()
"""

LABELS = """
(() => {
  const probe = document.createElement('span');
  document.body.appendChild(probe);
  probe.style.color = 'var(--color-error)';
  const errorColor = getComputedStyle(probe).color;
  probe.remove();
  const read = (id, wrapper) => {
    const row = document.getElementById(id).closest(wrapper);
    const label = row && row.querySelector(':scope > label');
    return {marked: row ? row.classList.contains('field-has-error') : null,
            color: label ? getComputedStyle(label).color : null};
  };
  return JSON.stringify({errorColor: errorColor,
                         factLine: read('correct-answer', '.fact-line'),
                         writeBlock: read('reflection-editor', '.write-block')});
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


def _labels(wimi_page: WimiPage, *, red: bool, timeout_ms: int = 3000) -> dict:
    """Both labels' colours, settled.

    Colour is a transitionable property, and getComputedStyle reports the
    interpolated value while a transition runs -- reading once, straight
    after a class or a theme lands, can report a colour on the way to the
    cue rather than the cue. Poll for the settled value, never sleep past it.
    """
    for _ in range(timeout_ms // 100):
        state = json.loads(wimi_page.eval_js(LABELS))
        matches = state['factLine']['color'] == state['errorColor']
        if matches is red:
            return state
        wimi_page.wait_for_timeout(100)
    return state


def _open_blank_entry_form(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    """Seed one session declaring a single incorrect, and open its blank entry."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Danger Colour Exam', exam_description='')
    db.create_subject_node(
        exam_context=exam.exam_name, name='Pneumonia', level_type='System',
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=1,
        session_name='Danger colour session', date_encountered=date.today(),
    )
    wimi_page.goto('entry-form', query={'session_id': session.id})
    assert _poll(wimi_page, READY) is not None, 'Entry form never finished initialising'


def _assert_sweep(wimi_page: WimiPage, rules: list, theme: str) -> None:
    """Every listed declaration resolves to the colour its token resolves to."""
    report = json.loads(wimi_page.eval_js(SWEEP.replace('__RULES__', json.dumps(rules))))
    for row in report['rules']:
        assert row['declared'] is not None, (
            f"No rule declaring {row['rule']} is loaded on this page ({theme}); the "
            'sweep cannot tell a fixed rule from a deleted one.'
        )
        assert '--color-danger' not in row['declared'], (
            f"{row['rule']} still names --color-danger ({row['declared']!r}), which is "
            'defined nowhere -- the declaration is discarded and paints nothing.'
        )
        assert row['computed'] == row['expected'], (
            f"{row['rule']} declares {row['declared']!r}, which computes to "
            f"{row['computed']!r} under {theme} while the palette red is "
            f"{row['expected']!r}. A value that does not follow the theme is either "
            'a hardcoded hex or a token the theme system cannot reach.'
        )


@pytest.mark.slow
@pytest.mark.regression
def test_missing_field_label_is_painted_with_the_palette_red(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The cue's label half paints, in a light theme and in a dark one."""
    # ---- Arrange -----------------------------------------------------
    _open_blank_entry_form(wimi_session, wimi_page)
    before = json.loads(wimi_page.eval_js(LABELS))
    assert before['factLine']['color'] != before['errorColor'], (
        f'A label was already red before the entry was touched ({before}); the rest '
        'of this test cannot tell the cue from the resting state.'
    )

    # ---- Act: the issue's repro -- touch the entry, leave the rest empty
    assert json.loads(wimi_page.eval_js(ARM))['armed'] is True, (
        'Typing in Your Answer did not arm show-missing; nothing below means anything.'
    )

    # ---- Assert ------------------------------------------------------
    light = _labels(wimi_page, red=True)
    for shape in ('factLine', 'writeBlock'):
        assert light[shape]['marked'] is True, (
            f'The {shape} field is empty and required but carries no .field-has-error '
            f'({light}); the label rule has nothing to match.'
        )
        assert light[shape]['color'] == light['errorColor'], (
            f"The {shape} label renders {light[shape]['color']} while the palette red "
            f"is {light['errorColor']} ({light}). The cue's left rule paints and its "
            'label does not -- which is #76 exactly: one of the two declarations names '
            'a custom property that does not exist, so it is discarded.'
        )

    # The palette red moves with the theme; a label that does not move with it is
    # painted by something the theme system cannot reach.
    wimi_page.eval_js(THEME.format('midnight'))
    dark = _labels(wimi_page, red=True)
    assert dark['errorColor'] != light['errorColor'], (
        f"Midnight resolved --color-error to {dark['errorColor']}, the same as the "
        'default theme; the theme switch did not take, so the check below is vacuous.'
    )
    for shape in ('factLine', 'writeBlock'):
        assert dark[shape]['color'] == dark['errorColor'], (
            f"Under Midnight the {shape} label renders {dark[shape]['color']} while "
            f"the palette red is {dark['errorColor']} ({dark}). The cue is pinned to a "
            'colour of its own instead of following the palette.'
        )


@pytest.mark.slow
@pytest.mark.regression
def test_every_danger_declaration_resolves_to_the_palette_red(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The hover and validation rules too, on both the pages that own them."""
    # ---- Arrange -----------------------------------------------------
    # These rules key off :hover and off classes no JS sets on a blank form, so
    # they are swept rather than triggered: each declaration is lifted from the
    # loaded stylesheet and resolved on a live probe in the same document.
    _open_blank_entry_form(wimi_session, wimi_page)

    # ---- Act / Assert ------------------------------------------------
    _assert_sweep(wimi_page, ENTRY_RULES, 'the default theme')
    wimi_page.eval_js(THEME.format('midnight'))
    _assert_sweep(wimi_page, ENTRY_RULES, 'Midnight')

    # tree.css carried the same two reds on the remove-parent action, and the
    # tree editor is the only page that loads it.
    wimi_page.goto('tree-editor')
    _assert_sweep(wimi_page, TREE_RULES, 'the default theme')
    wimi_page.eval_js(THEME.format('midnight'))
    _assert_sweep(wimi_page, TREE_RULES, 'Midnight')
