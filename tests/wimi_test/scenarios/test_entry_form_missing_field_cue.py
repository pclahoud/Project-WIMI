"""Regression: the missing-field cue must reach the two rich text editors.

Forgejo issue #40 -- "Entry form: the missing-field cue never appears on the
reflection and explanation editors":

    Once the student touches an entry, ``show-missing`` turns on the per-field
    cue that points at required fields still empty. It appears for Your
    Answer, Correct Answer and Primary Subject(s), but never for the two rich
    text editors, which are the two most important required fields.

Why it failed: ``markFieldState`` resolved the wrapper to mark with
``el.closest('.fact-line, .fact-row, .form-group')``. Both editors sit in a
``.write-block``, which is in none of those three and has no ancestor that is,
so ``closest()`` returned null and both calls returned early -- the marks were
computed as "missing" and then written nowhere.

What the fix changes: ``.write-block`` joins that selector list, and because a
260-420px editor is a different shape from a one-line fact row, ``entry.css``
gives it its own cue -- the border on ``.rich-editor-container`` instead of the
inset left rule, which the editor's own opaque background paints over.

Why these assertions catch the regression: the class half and the painted half
are checked separately. Asserting only that ``.field-has-error`` landed would
pass for a cue that renders nowhere, which is exactly the state the issue
describes. ``#user-answer`` is probed as a control so a broken arming step
cannot masquerade as this bug.

Deliberately not asserted here: the coloured *label* half
(``.field-has-error > label``). It named ``var(--color-danger)``, defined
nowhere in the project, so that declaration was dead for every field --
issue #76, which this scenario deliberately does not depend on. #76 repointed
it at ``--color-error``; ``test_danger_colour_resolves.py`` guards it.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Null until the page finishes its async start-up: both TinyMCE instances live
# (so isEmpty() answers truthfully and the container has a painted box) and the
# MediaUpload component mounted.
READY = """
(() => {
  if (typeof EntryState === 'undefined') return null;
  const r = EntryState.reflectionEditor, e = EntryState.explanationEditor;
  if (!r || !e || !r.isInitialized || !e.isInitialized) return null;
  const media = document.getElementById('media-upload-container');
  if (!media || !media.children.length) return null;
  return JSON.stringify({ready: true});
})()
"""

# Both halves of the cue for one field: the class the JS toggles, and the style
# the CSS actually paints. --color-error is resolved through a throwaway
# element so the comparison survives a palette change.
CUE_STATE = """
(() => {
  const el = document.getElementById('__ID__');
  const form = document.getElementById('entry-form');
  if (!el || !form) return null;
  const probe = document.createElement('span');
  probe.style.color = 'var(--color-error)';
  form.appendChild(probe);
  const errorColor = getComputedStyle(probe).color;
  probe.remove();
  const marked = el.closest('.field-has-error');
  const rect = el.getBoundingClientRect();
  return JSON.stringify({
    armed: form.classList.contains('show-missing'),
    marked: marked ? marked.className : null,
    markedInForm: !!(marked && marked.closest('#entry-form')),
    filled: !!el.closest('.field-has-content'),
    borderColor: getComputedStyle(el).borderTopColor,
    errorColor: errorColor,
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  });
})()
"""

# Typing one character into Your Answer is what arms show-missing -- the cue is
# deliberately absent until the student has touched the entry.
ARM = """
(() => {
  const a = document.getElementById('user-answer');
  a.value = 'B';
  a.dispatchEvent(new Event('input', {bubbles: true}));
  return JSON.stringify({armed:
    document.getElementById('entry-form').classList.contains('show-missing')});
})()
"""

# setContent() does not fire the editor's change event; markDirty + validateForm
# is verbatim the onChange handler initRichTextEditors installs.
FILL_REFLECTION = """
(() => {
  EntryState.reflectionEditor.setContent('<p>I misread the timeline.</p>');
  markDirty();
  validateForm();
  return JSON.stringify({empty: EntryState.reflectionEditor.isEmpty()});
})()
"""


def _poll(wimi_page: WimiPage, js: str, *, timeout_ms: int = 20000):
    """Poll ``js`` until it returns something other than ``null``."""
    elapsed = 0
    while elapsed < timeout_ms:
        try:
            result = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            result = None
        if result is not None:
            return json.loads(result)
        wimi_page.wait_for_timeout(200)
        elapsed += 200
    return None


def _cue(
    wimi_page: WimiPage, element_id: str, *, error_border=None, timeout_ms: int = 3000,
) -> dict:
    """One field's cue state, settled.

    .rich-editor-container transitions border-color, and getComputedStyle
    resolves to the interpolated value while a transition runs -- reading once,
    straight after the class lands, reports a colour on the way to the cue and
    not the cue. Poll for the settled value rather than sleeping past it.
    """
    probe, elapsed = CUE_STATE.replace('__ID__', element_id), 0
    state = json.loads(wimi_page.eval_js(probe))
    while error_border is not None and elapsed < timeout_ms:
        if (state['borderColor'] == state['errorColor']) is error_border:
            break
        wimi_page.wait_for_timeout(100)
        elapsed += 100
        state = json.loads(wimi_page.eval_js(probe))
    return state


def _open_blank_entry_form(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    """Seed one session declaring a single incorrect, and open its blank entry."""
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Missing Cue Exam', exam_description='')
    db.create_subject_node(
        exam_context=exam.exam_name, name='Pneumonia', level_type='System',
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=20, total_incorrect=1,
        session_name='Missing cue session', date_encountered=date.today(),
    )
    wimi_page.goto('entry-form', query={'session_id': session.id})
    assert _poll(wimi_page, READY) is not None, (
        'Entry form never finished initialising (both editors ready, media mounted)'
    )


@pytest.mark.slow
@pytest.mark.regression
def test_empty_editors_show_the_missing_field_cue(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Both required editors are marked, and the mark is actually painted."""
    # ---- Arrange -----------------------------------------------------
    _open_blank_entry_form(wimi_session, wimi_page)

    # An untouched blank entry is not a wall of red.
    assert _cue(wimi_page, 'reflection-editor')['armed'] is False, (
        'show-missing was on before the student touched anything; the cue is '
        'meant to arm on the first edit only.'
    )

    # ---- Act: the issue's repro -- touch the entry, leave both editors empty
    assert json.loads(wimi_page.eval_js(ARM))['armed'] is True, (
        'Typing in Your Answer did not arm show-missing; nothing below can mean '
        'anything.'
    )

    # ---- Assert ------------------------------------------------------
    # Control: a field the issue says does work, so a broken arming step cannot
    # be mistaken for this bug.
    control = _cue(wimi_page, 'user-answer')
    assert control['filled'] is True, (
        f'Your Answer holds text but was not marked filled ({control}).'
    )

    for element_id in ('reflection-editor', 'explanation-editor'):
        state = _cue(wimi_page, element_id, error_border=True)
        assert state['marked'] is not None, (
            f'#{element_id} is empty and required, but no ancestor carries '
            f'.field-has-error ({state}). markFieldState resolves the wrapper '
            "with closest(); if the editors' wrapper is not in that selector "
            'list the mark is computed and written nowhere.'
        )
        assert state['markedInForm'], (
            f'The wrapper marked for #{element_id} is outside #entry-form, so '
            f'.entry-form.show-missing can never style it ({state}).'
        )
        # A cue on a box with no pixels is not a cue.
        assert state['width'] > 0 and state['height'] > 100, (
            f'#{element_id} has no painted box ({state}); the editor did not '
            'render, so nothing below measures the cue.'
        )
        assert state['borderColor'] == state['errorColor'], (
            f"#{element_id} renders its border as {state['borderColor']} while "
            f"the error colour is {state['errorColor']} ({state}). The class "
            'landed but nothing visible changed -- the inset left rule the fact '
            "rows use is painted under the editor's opaque background, so the "
            'editors need a cue on their own outline.'
        )


@pytest.mark.slow
@pytest.mark.regression
def test_cue_clears_on_the_editor_that_was_filled(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Writing a reflection clears its cue and leaves the explanation's alone."""
    # ---- Arrange -----------------------------------------------------
    _open_blank_entry_form(wimi_session, wimi_page)
    wimi_page.eval_js(ARM)

    # ---- Act ---------------------------------------------------------
    assert json.loads(wimi_page.eval_js(FILL_REFLECTION))['empty'] is False, (
        'setContent() left the reflection editor reporting empty; the fill step '
        'did not happen.'
    )

    # ---- Assert ------------------------------------------------------
    reflection = _cue(wimi_page, 'reflection-editor', error_border=False)
    assert reflection['marked'] is None, (
        f'The reflection holds text but is still marked missing ({reflection}).'
    )
    assert reflection['filled'] is True, (
        f'The reflection was not marked filled ({reflection}); markFieldState '
        'toggles both classes on the same wrapper.'
    )
    assert reflection['borderColor'] != reflection['errorColor'], (
        f'The reflection still renders the error border ({reflection}).'
    )

    explanation = _cue(wimi_page, 'explanation-editor', error_border=True)
    assert explanation['marked'] is not None, (
        f'Filling the reflection cleared the explanation cue too ({explanation}); '
        'each field is marked independently.'
    )
    assert explanation['borderColor'] == explanation['errorColor'], (
        f'The explanation is still empty and required but no longer renders the '
        f'error border ({explanation}).'
    )
