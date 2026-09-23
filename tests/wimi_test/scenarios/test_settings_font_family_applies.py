"""Regression: Settings -> Appearance, Font Family is stored but never applied.

Forgejo issue #44 -- "[bug] Settings: the Font Family preference is stored
but never applied":

    The **Font Family** control saves a preference that nothing ever reads.
    The value round-trips to the database correctly, but no stylesheet,
    theme applier or live-preview path consumes it, so choosing a typeface
    changes nothing on screen -- now or after a restart. [...] ``font_family``
    is absent from ``SettingsPage.VISUAL_FIELDS`` [...] Grepping the tree for
    ``font_family`` [...] returns only three hits: ``settings.js:18`` (the
    ``DEFAULTS`` entry), and the ``<label>``/``<select>`` in ``settings.html``.

Why it failed: ``styles.css`` already declares ``--font-family`` and ``body``
already consumes it, but nothing ever wrote that custom property. The other
Appearance preferences reach the DOM through two paired appliers -- the
page-load IIFE at the foot of ``themes.js`` (which runs on every page) and
``SettingsPage.applyLivePreview``. ``font_family`` was in neither, and
``VISUAL_FIELDS`` did not list it, so it could not even preview.

What the fix changes: ``themes.js`` grows a ``WIMI_FONT_STACKS`` map and a
``_wimiApplyFontFamily`` applier alongside ``_wimiApplyThemeVariables``; both
appliers call it, ``VISUAL_FIELDS`` gains ``font_family``, and the select
offers the stacks the map names.

Decisiveness: the assertions read *computed* style, not the stored value and
not a class name -- reading the preference back would have passed against the
bug. Chromium reports the declared stack rather than the face fontconfig
resolves, which is the right granularity: a headless runner cannot be promised
any typeface is installed, but the generic family the stack ends in differs
either way.

The third test is the other half of the fix: a UI font must not reflow the
student's own notes. ``.rich-content`` carries its own stack (matched to
TinyMCE's ``content_style`` so view and edit modes agree), code runs on
``--font-mono``, and KaTeX renders in its own ``KaTeX_*`` faces.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# The preference under test. 'serif' ends in a generic family no default
# stack in the tree shares, so "did it change?" needs no installed font.
CHOSEN = 'serif'

# Reflection HTML covering all three surfaces the font must NOT touch:
# prose (.rich-content), code (--font-mono) and math (KaTeX_*).
REFLECTION = (
    '<p>Missed the second-order term.</p>'
    '<pre><code>SELECT 1;</code></pre>'
    '<span class="math-tex" data-formula="x^2"></span>'
)

CHROME = """
(() => JSON.stringify({
  marker: window.__wimiFontProbe === 1,
  body: getComputedStyle(document.body).fontFamily,
  mono: getComputedStyle(document.documentElement)
          .getPropertyValue('--font-mono').trim()
}))()
"""

CONTENT = """
(() => { const el = document.getElementById('reflection-content');
  const ready = !!el && el.classList.contains('rich-content');
  const code = ready ? el.querySelector('code') : null;
  const math = ready ? el.querySelector('.katex') : null;
  return JSON.stringify({
    marker: window.__wimiFontProbe === 1,
    ready,
    body: getComputedStyle(document.body).fontFamily,
    rich: ready ? getComputedStyle(el).fontFamily : null,
    code: code ? getComputedStyle(code).fontFamily : null,
    math: math ? getComputedStyle(math).fontFamily : null
  }); })()
"""

# populateForm fills the primary-colour text input, which carries no value
# attribute in the markup -- a DOM-only signal that preferences landed.
PREFS_LOADED = "document.getElementById('primary_color_hex').value !== ''"


def _generic(stack: str) -> str:
    """The generic family a computed font-family stack falls back to.

    ``sans-serif`` *endswith* ``serif``, so the last entry is compared
    whole; otherwise every default in the tree would satisfy a
    "is it serif now?" check without anything having changed.
    """
    return stack.rsplit(',', 1)[-1].strip().strip('\'"').lower()


def _probe(wimi_page: WimiPage, js: str, *, fresh: bool = False,
           timeout_ms: int = 10000) -> dict:
    """Poll until the document has committed (and, for CONTENT, rendered)."""
    elapsed, last = 0, {}
    while elapsed < timeout_ms:
        try:
            last = json.loads(wimi_page.eval_js(js))
        except Exception:  # context torn down mid-navigation
            last = {}
        settled = last.get('ready', True) and not (fresh and last.get('marker'))
        if last and settled:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed_entry(db) -> int:
    exam = db.create_exam_context(exam_name='Font Exam', exam_description='')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name='Font session',
    )
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer='a', correct_answer='b',
        reflection=REFLECTION,
    )
    return entry.id


@pytest.mark.slow
@pytest.mark.regression
def test_stored_font_family_reaches_a_page_that_is_not_settings(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The saved preference must style the whole app, not just its own panel."""
    # ---- Arrange: the default, as rendered -----------------------------
    db = wimi_session.user.db
    wimi_page.goto('dashboard')
    before = _probe(wimi_page, CHROME)['body']
    assert before, 'Could not read the dashboard body font'

    # ---- Act -----------------------------------------------------------
    db.update_preferences(font_family=CHOSEN)
    wimi_page.eval_js('window.__wimiFontProbe = 1')
    wimi_page.goto('dashboard')
    after = _probe(wimi_page, CHROME, fresh=True)

    # ---- Assert --------------------------------------------------------
    assert after.get('body') != before, (
        f'Saving font_family={CHOSEN!r} left the dashboard on {before!r}. '
        'The preference is stored but no applier writes --font-family, so '
        'nothing on screen changes (issue #44).'
    )
    assert _generic(after['body']) == 'serif', (
        f'font_family={CHOSEN!r} rendered as {after["body"]!r}; the applied '
        'stack must fall back to the generic family the option names.'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_choosing_a_font_previews_before_it_is_saved(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Appearance previews its other fields live; font_family must join them."""
    # ---- Arrange -------------------------------------------------------
    wimi_page.goto('settings')
    elapsed = 0
    while elapsed < 10000 and wimi_page.eval_js(PREFS_LOADED) is not True:
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    before = _probe(wimi_page, CHROME)['body']

    # ---- Act: change the select the way a user does ---------------------
    offered = json.loads(wimi_page.eval_js(
        "JSON.stringify(Array.from(document.getElementById('font_family')"
        ".options).map(o => o.value))"
    ))
    assert CHOSEN in offered, (
        f'The Font Family select offers {offered!r}, which has no {CHOSEN!r} '
        'option to choose -- with a single typeface the control cannot '
        'demonstrate anything.'
    )
    wimi_page.eval_js(
        "(() => { const s = document.getElementById('font_family');"
        f" s.value = {CHOSEN!r};"
        " s.dispatchEvent(new Event('change', {bubbles: true})); })()"
    )
    # Poll rather than read once: `transition: all` rules are common in this
    # tree, and a discrete property read mid-transition reports the old value.
    elapsed, after = 0, {}
    while elapsed < 5000:
        after = _probe(wimi_page, CHROME)
        if _generic(after.get('body', '')) == 'serif':
            break
        wimi_page.wait_for_timeout(100)
        elapsed += 100

    # ---- Assert --------------------------------------------------------
    assert after.get('body') != before, (
        f'Picking {CHOSEN!r} left the panel on {before!r}. font_family is '
        'missing from VISUAL_FIELDS, so _onFieldChange never calls '
        'applyLivePreview for it (issue #44).'
    )
    assert _generic(after['body']) == 'serif', after


@pytest.mark.slow
@pytest.mark.regression
def test_the_ui_font_leaves_notes_code_and_math_alone(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """A UI preference must not reflow content the student wrote."""
    # ---- Arrange -------------------------------------------------------
    db = wimi_session.user.db
    entry_id = _seed_entry(db)
    db.update_preferences(font_family=CHOSEN)

    # ---- Act -----------------------------------------------------------
    wimi_page.goto('entry-detail', query={'id': entry_id})
    probe = _probe(wimi_page, CONTENT)

    # ---- Assert: the chrome did change ---------------------------------
    assert probe.get('ready'), f'Reflection never rendered as rich content: {probe!r}'
    assert _generic(probe['body']) == 'serif', (
        f'The page chrome did not take the preference: {probe!r}'
    )

    # ---- Assert: the content did not -----------------------------------
    assert _generic(probe['rich']) == 'sans-serif', (
        f'The saved reflection now renders in the UI font ({probe["rich"]!r}). '
        '.rich-content carries its own stack on purpose, matched to TinyMCE\'s '
        'content_style so view and edit modes agree; a UI preference must not '
        'reflow notes the student already wrote.'
    )
    assert probe['code'] is not None and _generic(probe['code']) == 'monospace', (
        f'Code in a reflection left its monospace stack: {probe["code"]!r}'
    )
    assert probe['math'] is not None and 'KaTeX' in probe['math'], (
        f'Rendered math left the KaTeX faces: {probe["math"]!r}'
    )
    mono = _probe(wimi_page, CHROME)['mono']
    assert _generic(mono) == 'monospace', (
        f'--font-mono was overwritten by the UI font preference: {mono!r}'
    )
