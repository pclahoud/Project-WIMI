"""The efficiency score is withdrawn from the product, and stays withdrawn (#146).

#146 measured that the score **cannot report a bad result**: on a realistic
15-row blueprint every distribution a student could plausibly produce lands
88-99 and rates *Excellent*, `Fair` and `Needs Improvement` are unreachable,
and perfect alignment scores 99.1 rather than 100 because real blueprints do
not total 100% and #64 forbids rescaling them.

The owner's decision (2026-10-05) is **none of the five fixes #146 proposed**:

    "We have yet to discuss this. The feature should be disabled for the
    time being."

So this file pins two things that are easy to get wrong in opposite
directions.

**That it is off.** A product decision recorded only in an issue comment is
one refactor away from being undone -- somebody tidying a flag they cannot
find a reason for, or restoring a header that looks accidentally deleted.
Re-enabling must turn a test red.

**That it is only off, not gone.** "Disabled for the time being" means the
discussion is still to come, so the arithmetic, the payload keys, the
preference column and the render helpers all have to survive. A later sweep
deleting `renderEfficiencyValue` as dead code would turn a one-word reversal
into a reconstruction, and would do it while every test still passed.

Why a source test rather than a DOM one
---------------------------------------
`EFFICIENCY_SCORE_ENABLED` is a top-level `const`, which is a **script-scope
binding and not a property of `window`** -- the hazard CLAUDE.md records for
`EntryState`, `settingsPage` and `TreeState`. So a scenario cannot read the
flag through `window.` at all, and reading it the wrong way reports a
working feature as broken. `test_efficiency_score_is_disabled.py` reads the
file; `tests/wimi_test/scenarios/test_efficiency_score_is_not_drawn.py`
asserts the consequence in a real page. Two instruments, one for the switch
and one for the pixels.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEIGHT_JS = REPO_ROOT / 'src' / 'web' / 'js' / 'weight_analysis.js'
SETTINGS_HTML = REPO_ROOT / 'src' / 'web' / 'html' / 'settings.html'
ANALYTICS_PY = (REPO_ROOT / 'src' / 'database' / 'domains'
                / 'analytics_advanced.py')

FLAG = 'EFFICIENCY_SCORE_ENABLED'


def flag_value(source: str) -> bool:
    """Read the flag's declared value out of the module source.

    A function rather than an inline regex so the control below can run
    the *same* reader over mutated text -- the shape
    `test_settings_panel_selectors.py` uses, and the reason its sweep is
    evidence rather than decoration.

    Raises:
        AssertionError: if the declaration is absent or not a literal.
            Silently returning False there would make every assertion in
            this file pass against a module that had deleted the flag.
    """
    match = re.search(
        r'^const\s+' + FLAG + r'\s*=\s*(true|false)\s*;', source,
        re.MULTILINE)
    assert match, (
        f'{FLAG} is not declared as a top-level const with a literal '
        f'true/false. #146 requires one readable switch; a computed value '
        f'cannot be checked here and a missing one makes this whole file '
        f'vacuous.')
    return match.group(1) == 'true'


@pytest.fixture(scope='module')
def weight_js() -> str:
    return WEIGHT_JS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def settings_html() -> str:
    return SETTINGS_HTML.read_text(encoding='utf-8')


# ==================== it is off ====================

def test_the_score_is_disabled(weight_js):
    """The decision itself."""
    assert flag_value(weight_js) is False, (
        'the efficiency score is enabled. #146 is an OPEN product question '
        "-- the owner's words were \"we have yet to discuss this\" -- and "
        'the score cannot report a bad result, so enabling it shows every '
        'student "Excellent" including the ones it should not. Re-enable '
        'only with a decision recorded on #146.')


def test_the_reader_would_catch_it_being_switched_on(weight_js):
    """The control, without which the test above asserts nothing.

    A guard for an absence has to be shown capable of failing (#121). This
    runs the real reader over the real file with one token changed.
    """
    mutated = weight_js.replace(
        f'const {FLAG} = false;', f'const {FLAG} = true;')
    assert mutated != weight_js, 'the mutation did not apply; reader is stale'
    assert flag_value(mutated) is True, (
        'flag_value cannot tell true from false, so '
        'test_the_score_is_disabled would pass whatever the flag said')


def test_the_header_is_not_rendered_inline(weight_js):
    """`render()` must go through the gate, not around it.

    The markup used to sit inline in `render()`'s template literal. Left
    there, the flag would be a decoration with no effect -- which reads as
    a disabled feature to anybody grepping for the flag.
    """
    render = weight_js[weight_js.index('\n    render() {'):]
    render = render[:render.index('\n    }\n')]
    assert 'renderEfficiencyHeader()' in render, (
        'render() does not call renderEfficiencyHeader(), so the #146 flag '
        'does not control what is drawn')
    for leaked in ('efficiency-header', 'efficiency-score-value',
                   'EFFICIENCY SCORE'):
        assert leaked not in render, (
            f'render() still emits {leaked!r} directly, bypassing the flag')


def test_the_gate_returns_nothing_rather_than_an_empty_box(weight_js):
    """An empty `.efficiency-header` is not "disabled", it is a gap.

    `.weight-analysis-layout` is a grid, and a grid spaces an empty child
    exactly as it spaces a full one -- the mistake #60's proposal panel
    made with a `gap` over two empty boxes. So the gate returns `''` and
    contributes no element at all.
    """
    gate = weight_js[weight_js.index('renderEfficiencyHeader() {'):]
    gate = gate[:gate.index('\n    }\n')]
    assert f'if (!{FLAG})' in gate, 'the gate does not test the flag'
    assert "return '';" in gate, (
        'the gate must return an empty string, not an empty container')
    assert gate.index(f'if (!{FLAG})') < gate.index('efficiency-header'), (
        'the flag check must come before the markup, or the markup is '
        'built and then thrown away -- and the next reader will "simplify" '
        'the dead branch away')


def test_the_settings_control_is_hidden_too(settings_html):
    """A setting that changes nothing a student can see (#289, #174).

    Its only effect is choosing one-number-or-range for a score that is
    not drawn. Hidden, not deleted: `settings.js` binds it by `data-field`,
    so a value set before this is still loaded and saved rather than lost.
    """
    anchor = settings_html.index('id="efficiency_show_confidence_band"')
    group_start = settings_html.rindex('<div class="form-group"', 0, anchor)
    opening_tag = settings_html[group_start:settings_html.index('>', group_start)]
    assert 'hidden' in opening_tag, (
        'the efficiency-band checkbox is still offered while the score it '
        'decorates is hidden, so Settings presents a control over nothing')
    # Still wired, so re-enabling is one attribute.
    assert 'data-field="efficiency_show_confidence_band"' in settings_html, (
        'the input lost its data-field binding, so the preference no longer '
        'loads or saves -- that is removal, not disabling')


# ==================== it is only off, not gone ====================

@pytest.mark.parametrize('name', [
    '_calculate_efficiency_score',
    '_get_efficiency_rating',
    '_build_efficiency_band',
])
def test_the_arithmetic_survives(name):
    """"Disabled for the time being" is not "deleted".

    #146 is still open and still needs these to be measurable. Deleting
    them would make the five options in its body unevaluable without a
    rewrite, and nothing would have gone red.
    """
    source = ANALYTICS_PY.read_text(encoding='utf-8')
    assert f'def {name}(' in source, (
        f'{name} is gone. #146 is disabled pending a discussion, not '
        f'resolved -- the arithmetic has to still be there to discuss.')


@pytest.mark.parametrize('key', [
    'efficiency_score', 'efficiency_rating', 'efficiency_band',
])
def test_the_payload_keys_survive(key):
    """The backend keeps answering; only the page stops asking."""
    source = ANALYTICS_PY.read_text(encoding='utf-8')
    assert f"'{key}'" in source, (
        f'{key} is no longer in the analytics payload. Hiding the score is '
        f'a frontend decision; removing it from the payload is a different '
        f'and larger one that #146 has not taken.')


def test_the_focus_check_comes_back_with_the_score(weight_js):
    """The coverage this disable quietly removed, tied to the flag.

    `test_focus_is_visible_where_it_lands.py` checked `.efficiency-info-icon`
    for a visible focus ring (#304). The icon is no longer rendered, and that
    scenario treats a selector which never renders as a **finding** -- so it
    had to stop looking, and running the scenario selection is what caught
    it rather than anything in this file.

    The loss is real: restore the score without restoring that selector and
    the icon comes back with its focus ring unchecked. Nothing would fail.

    So the two are coupled here. While the score is off the selector must be
    absent; the moment someone flips the flag, `test_the_score_is_disabled`
    goes red and points at #146, where this requirement is written down.
    """
    scenario = (REPO_ROOT / 'tests' / 'wimi_test' / 'scenarios'
                / 'test_focus_is_visible_where_it_lands.py')
    source = scenario.read_text(encoding='utf-8')
    disabled = flag_value(weight_js) is False
    checks_the_icon = '(".efficiency-info-icon"' in source

    if disabled:
        assert not checks_the_icon, (
            'the focus scenario still checks .efficiency-info-icon while '
            '#146 has the score hidden, so it will report "did not render, '
            'so it was not checked" on every run')
    else:
        assert checks_the_icon, (
            'the efficiency score has been re-enabled but '
            'test_focus_is_visible_where_it_lands.py no longer checks '
            '.efficiency-info-icon -- the icon is focusable (tabindex=0) and '
            'its focus ring is now unverified (#304). Put the selector back '
            'in that file\'s tuple.')


@pytest.mark.parametrize('helper', [
    'renderEfficiencyValue',
    'renderEfficiencyBandNote',
    'renderEfficiencyInfoIcon',
])
def test_the_render_helpers_survive(weight_js, helper):
    """These render nothing today and are not dead code.

    They are the other half of the flag. A sweep deleting them would turn
    a one-word reversal into a reconstruction of #133's band rendering,
    and would pass every test while doing it -- which is exactly why this
    is asserted rather than left to a comment.

    **Asserted as a DEFINITION, not as an occurrence**, and that distinction
    is measured rather than fussy. The first version of this test looked for
    `f'{helper}('` anywhere in the file and **passed with the method
    deleted** -- because `renderEfficiencyHeader`'s markup still *calls*
    `${this.renderEfficiencyBandNote()}`, so the name was still present
    while the method was gone. The mutant that proved it: delete the method
    body from the source and the whole file still reported 14 passed.
    """
    definition = f'\n    {helper}() {{'
    assert definition in weight_js, (
        f'{helper} has no method definition. It is unreachable only while '
        f'{FLAG} is false; restoring the score needs it back. (Note a call '
        f'site alone is not enough -- that is what this assertion used to '
        f'accept.)')
