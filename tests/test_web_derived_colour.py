"""A derived colour is a mix, not an offset -- and there is one mixer.

Forgejo issue #307 -- "[bug] A custom primary colour produces an off-palette
cyan, because ``_adjustColor`` adds a flat +180 per channel".

The defect, and why a flat offset cannot work
---------------------------------------------
The three tokens derived from ``primary_color_hex`` were produced by adding
one constant to each of R, G and B and clamping at 0/255. A channel with
headroom moves the whole amount; a channel without it stops at the bound. The
channels therefore move by *different* amounts, and the ratios between them
are what hue is, so the hue moves. Measured on the six shipped theme primaries
at the ``+180`` used for ``--color-primary-bg``:

=============  ==========  =============================  ==================
primary        hue         ``+180`` additive              hue after
=============  ==========  =============================  ==================
``#059669``    161.4 deg   ``#b9ffff``                    180.0 deg
``#2563eb``    221.2 deg   ``#d9ffff``                    180.0 deg
``#60a5fa``    213.1 deg   ``#ffffff``                    hue destroyed
``#b45309``     26.0 deg   ``#ffffbd``                     60.0 deg
``#5e81ac``    213.1 deg   ``#ffffff``                    hue destroyed
``#3391ff``    212.4 deg   ``#e7ffff``                    180.0 deg
=============  ==========  =============================  ==================

So the issue's single Forest observation was not a corner case: **every**
shipped primary collapses onto cyan, yellow or pure white, and two of the six
lose their hue entirely -- ``--color-primary-bg`` is literally ``#ffffff``,
behind the text of every badge and focus ring that uses it. The ``-25`` and
``+20`` tokens clip too, 3.0-3.5 deg on a saturated colour.

The replacement is a proportional mix toward white (positive ratio) or black
(negative): ``c + (255 - c) * t`` and ``c * (1 - t)``. Each multiplies every
channel's distance from the endpoint by the same factor, so ``max - min`` and
``mid - min`` scale together and the hue is preserved *exactly* -- to within
8-bit rounding, measured at <= 1.9 deg over the same inputs. A clamp is never
needed, because both forms are bounded by construction.

What this module guards, and why statically
-------------------------------------------
The arithmetic itself is pinned by a scenario
(``tests/wimi_test/scenarios/test_derived_colour_keeps_its_hue.py``), which
calls the shipped function in the real engine over a table of inputs. Three
things that scenario cannot see:

1. **There were two copies of the broken arithmetic**, and the issue named
   only one. ``settings.js:_adjustColor`` drove the live preview;
   ``themes.js:_wimiAdjustColor`` drove *every page load*, which is why the
   bug was visible on surfaces (``browser.css``, the deep dive) that the
   settings page never renders. A scenario that evaluates one of them passes
   while the other is still wrong.
2. **The ratio is on a different scale from the offset it replaced.** A call
   site left on the old scale would pass ``180`` as a ratio -- and with the
   clamp correctly gone, nothing would bound the result.
3. **A clamp coming back** is the clipping coming back, under whatever name.

Each test carries a negative control built from the pre-fix source, because a
source check that cannot reject the original is not a check.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB_JS = REPO / 'src' / 'web' / 'js'

#: Vendored libraries are not ours to police.
VENDORED = ('lib',)

#: The one mixer. Defined in themes.js, which every page already loads, and
#: used from there by the one applier both colour paths call.
MIXER = '_wimiMixColor'

#: The file the mixer and the applier belong to.
HOME = 'themes.js'

#: Both spellings of the retired additive helper.
RETIRED = ('_wimiAdjustColor', '_adjustColor')

#: The tokens derived from the two stored colours. Writing any of these from
#: more than one module is how #307 came to have two copies.
DERIVED_TOKENS = (
    '--color-primary-hover',
    '--color-primary-light',
    '--color-primary-bg',
    '--color-secondary-hover',
)

#: The pre-fix helper, verbatim from themes.js at c8a904b. Every test below
#: runs its own predicate over this as a control.
PRE_FIX_SOURCE = """
function _wimiAdjustColor(hex, amount) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    r = Math.max(0, Math.min(255, r + amount));
    g = Math.max(0, Math.min(255, g + amount));
    b = Math.max(0, Math.min(255, b + amount));
    return '#' + [r, g, b].map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
}
root.setProperty('--color-primary-hover', _wimiAdjustColor(prefs.primary_color_hex, -25));
root.setProperty('--color-primary-light', _wimiAdjustColor(prefs.primary_color_hex, 20));
root.setProperty('--color-primary-bg', _wimiAdjustColor(prefs.primary_color_hex, 180));
"""


def _first_party_scripts() -> list[Path]:
    return sorted(
        p for p in WEB_JS.rglob('*.js')
        if not any(part in VENDORED for part in p.relative_to(WEB_JS).parts)
    )


def _function_body(source: str, name: str) -> str | None:
    """The text of ``function name(...) { ... }``, braces matched.

    A regex cannot do this: the body contains braces, and stopping at the
    first ``}`` would read only as far as the first nested block -- which in
    the pre-fix helper is before its clamps.
    """
    match = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if not match:
        return None
    depth, i = 0, match.end() - 1
    while i < len(source):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[match.end():i]
        i += 1
    return None


def _call_arguments(source: str, name: str) -> list[list[str]]:
    """The argument list of every ``name(...)`` call, split at top level.

    Paren-walked rather than matched. This was a regex forbidding parens in
    the ratio position, and #322 put a call there -- so the ratio stopped
    being *found* instead of being reported as unresolvable, and the call
    count fell to 3. A check whose hole is "the argument got complicated"
    is the hole this file exists to close.
    """
    calls = []
    for match in re.finditer(r'\b' + re.escape(name) + r'\s*\(', source):
        depth, i, start = 0, match.end() - 1, match.end()
        while i < len(source):
            if source[i] == '(':
                depth += 1
            elif source[i] == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        else:
            continue
        inner, args, depth, last = source[start:i], [], 0, 0
        for j, ch in enumerate(inner):
            if ch in '([':
                depth += 1
            elif ch in ')]':
                depth -= 1
            elif ch == ',' and depth == 0:
                args.append(inner[last:j])
                last = j + 1
        args.append(inner[last:])
        calls.append([a.strip() for a in args])
    return calls

#: ``var NAME = <numeric literal>;`` -- how the ratios are declared, so each
#: number appears once with the measurement that chose it.
_CONST = re.compile(r'\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(-?[0-9.]+)\s*;')

#: A channel clamp of either bound -- the signature of an arithmetic that can
#: clip. Spelled loosely so a reformat does not slip past.
_CLAMP = re.compile(r'Math\.(?:min|max)\s*\(\s*(?:0|255)\b|Math\.(?:min|max)\s*\([^)]*\b255\b')


def _has_clamp(source: str) -> bool:
    return bool(_CLAMP.search(source))


def _chooser_ratios(source: str, call: str) -> list[float] | None:
    """Every ratio a ``RATIO(...)`` helper can return, or ``None``.

    #322 made one ratio a *choice* rather than a constant: a dark theme's
    ``--color-primary-bg`` has to mix toward black and a light theme's toward
    white, so ``_wimiPrimaryBgRatio`` returns one of two constants. That is a
    legitimate shape and this check follows it one level deep rather than
    exempting it -- by reading the helper's ``return`` expressions and
    resolving the identifiers in them against the helper's own constants, so
    EVERY value it can hand the mixer is range-checked.

    The luminance threshold declared in the same body is deliberately not
    swept up: it is a constant in that function and not a ratio, and the
    difference is exactly what reading the returns rather than the
    declarations buys.
    """
    match = re.fullmatch(r'([A-Za-z_$][\w$]*)\s*\(.*\)', call, flags=re.S)
    if not match:
        return None
    body = _function_body(source, match.group(1))
    if body is None:
        return None
    constants = {name: float(raw) for name, raw in _CONST.findall(body)}
    values = []
    for expression in re.findall(r'\breturn\b([^;]*);', body, flags=re.S):
        names = re.findall(r'[A-Za-z_$][\w$]*', expression)
        numbers = re.findall(r'-?\d+\.?\d*', expression)
        found = [constants[n] for n in names if n in constants]
        found += [float(n) for n in numbers]
        if not found:
            return None          # a return this cannot read is not a pass
        values += found
    return values or None


def _ratios(source: str) -> tuple[list[float], list[str]]:
    """Every ratio actually passed to the mixer, resolved, plus the unresolved.

    A ratio is written as a literal, as a numeric constant declared in the
    same file, or -- since #322 -- as a call to a helper in the same file that
    returns only such constants, in which case *all* of its possible values
    are resolved. Anything else is returned as unresolved rather than ignored:
    a computed ratio would be a hole in this check, not an exemption from it.
    """
    constants = {name: float(raw) for name, raw in _CONST.findall(source)}
    # The declaration's own parameter list is not a call site.
    source = re.sub(r'function\s+' + re.escape(MIXER) + r'\s*\([^)]*\)', '', source)
    resolved, unresolved = [], []
    for args in _call_arguments(source, MIXER):
        if len(args) != 2:
            unresolved.append(', '.join(args))
            continue
        raw = args[1]
        try:
            resolved.append(float(raw))
            continue
        except ValueError:
            pass
        if raw in constants:
            resolved.append(constants[raw])
            continue
        chooser = _chooser_ratios(source, raw)
        if chooser is not None:
            resolved += chooser
        else:
            unresolved.append(raw)
    return resolved, unresolved


def _bad_ratios(source: str) -> list[float]:
    return [value for value in _ratios(source)[0] if abs(value) > 1]


@pytest.mark.unit
def test_the_retired_additive_helper_is_gone_under_both_names() -> None:
    """Neither copy of the clipping arithmetic may survive anywhere."""
    offenders = {
        str(path.relative_to(REPO)): name
        for path in _first_party_scripts()
        for name in RETIRED
        if name in path.read_text(encoding='utf-8')
    }
    assert not offenders, (
        f'The additive colour helper is still present: {offenders}. It adds a '
        'flat constant to each channel and clamps, so a channel with no '
        'headroom stops while the others keep going and the hue moves '
        '(#307: #059669 + 180 -> #b9ffff, a cyan). There were two copies of '
        'this function and the issue named only one -- themes.js runs on every '
        'page load, settings.js only on its own panel.'
    )
    # Control: the predicate does reject the source it was written against.
    assert any(name in PRE_FIX_SOURCE for name in RETIRED)


@pytest.mark.unit
def test_the_mixer_is_defined_exactly_once_and_lives_in_themes_js() -> None:
    """Two definitions is the shape of the defect, not an implementation detail."""
    homes = [
        str(path.relative_to(REPO)) for path in _first_party_scripts()
        if _function_body(path.read_text(encoding='utf-8'), MIXER) is not None
    ]
    assert len(homes) == 1, (
        f'{MIXER} is defined in {len(homes)} first-party scripts ({homes}); it '
        'must be defined once. #307 was one function copied into two files, so '
        'fixing the one the issue named left the other -- the page-load path, '
        'i.e. every surface outside Settings -- still producing the cyan.'
    )
    assert homes[0].endswith(HOME), (
        f'{MIXER} lives in {homes[0]}; it belongs in {HOME}, which every page '
        'already loads and which owns the other two appearance appliers '
        '(_wimiApplyThemeVariables, _wimiApplyFontFamily).'
    )


@pytest.mark.unit
def test_the_mixer_needs_no_channel_clamp() -> None:
    """A clamp means the arithmetic can leave the range, i.e. can clip."""
    source = (WEB_JS / HOME).read_text(encoding='utf-8')
    body = _function_body(source, MIXER)
    assert body is not None, f'{MIXER} is not defined in {HOME}'
    assert not _has_clamp(body), (
        f'{MIXER} clamps a channel to 0 or 255. A proportional mix cannot '
        'leave the range -- c + (255 - c) * t stays in [c, 255] and c * (1 - t) '
        'in [0, c] for t in [0, 1] -- so a clamp here means the arithmetic is '
        'additive again and the hue can move (#307).'
    )
    # Control: the same predicate finds the clamps in the pre-fix helper.
    pre_fix_body = _function_body(PRE_FIX_SOURCE, '_wimiAdjustColor')
    assert pre_fix_body is not None
    assert _has_clamp(pre_fix_body), (
        'The clamp predicate does not fire on the pre-fix helper, so it cannot '
        'be read as evidence about the shipped one.'
    )


@pytest.mark.unit
def test_every_mix_ratio_is_a_fraction_not_a_channel_offset() -> None:
    """The ratio scale is not the offset scale, and nothing bounds a mistake."""
    calls, offenders, opaque = 0, {}, {}
    for path in _first_party_scripts():
        source = path.read_text(encoding='utf-8')
        resolved, unresolved = _ratios(source)
        calls += len(resolved) + len(unresolved)
        if _bad_ratios(source):
            offenders[str(path.relative_to(REPO))] = _bad_ratios(source)
        if unresolved:
            opaque[str(path.relative_to(REPO))] = unresolved
    assert calls >= len(DERIVED_TOKENS), (
        f'Only {calls} {MIXER} calls were found; the four derived tokens '
        f'{DERIVED_TOKENS} each need one.'
    )
    assert not opaque, (
        f'A mix ratio this check cannot resolve: {opaque}. Write it as a '
        'literal, as a numeric constant in the same file, or as a call to a '
        'helper in the same file that returns only such constants -- an '
        'expression leaves nothing here able to tell a fraction from a '
        'channel offset.'
    )
    assert not offenders, (
        f'A mix ratio outside [-1, 1]: {offenders}. The pre-fix helper took a '
        'channel offset (-25, +20, +180) and the replacement takes a fraction '
        'of the distance to white or black. A call site left on the old scale '
        'passes 180 as a ratio, and the clamp that used to hide that is gone '
        'by design (#307).'
    )
    # Control: all three pre-fix amounts are exactly what this rejects.
    assert sorted(_bad_ratios(PRE_FIX_SOURCE.replace('_wimiAdjustColor', MIXER))) == [
        -25.0, 20.0, 180.0,
    ]


@pytest.mark.unit
def test_the_derived_tokens_are_written_from_one_module() -> None:
    """Two writers is how the two copies stayed in step long enough to ship."""
    writers: dict[str, list[str]] = {}
    for path in _first_party_scripts():
        source = path.read_text(encoding='utf-8')
        written = [
            token for token in DERIVED_TOKENS
            if re.search(r'setProperty\s*\(\s*[\'"]' + re.escape(token) + r'[\'"]', source)
        ]
        if written:
            writers[str(path.relative_to(REPO))] = written
    assert len(writers) == 1, (
        f'The derived colour tokens are written from {len(writers)} modules '
        f'({writers}). They must be written from one applier, called by both '
        'the page-load path and the live preview -- the same shape '
        '_wimiApplyFontFamily already has. Two writers is how #307 shipped: '
        'settings.js and themes.js each derived the tokens for themselves.'
    )
    assert next(iter(writers)).endswith(HOME), (
        f'The derived tokens are written from {next(iter(writers))} rather than '
        f'{HOME}, which owns the other appearance appliers.'
    )


@pytest.mark.unit
def test_a_chosen_ratio_is_resolved_through_its_helper_not_exempted() -> None:
    """#322 made one ratio a choice; the range check has to follow it.

    ``--color-primary-bg`` mixes toward white on a light theme and toward
    black on a dark one, so its ratio is now ``_wimiPrimaryBgRatio(...)``
    rather than a constant at the call site. Two things could have gone
    wrong and neither would have failed anything:

    * the old call-site regex forbade parens in the ratio position, so the
      call was not *found* -- the mixer call count silently fell to 3; and
    * a resolver that gave up on a call would have put the ratio in
      ``opaque``, which is at least loud, but one that skipped it would have
      exempted the only ratio in the file that can take two values.

    So this asserts the shipped helper resolves to BOTH of its constants,
    and that the two mutations a reader would worry about are caught. The
    controls matter more than the positive case: without them "resolves to
    [-0.68, 0.85]" is equally true of a resolver that hardcoded that list.
    """
    source = (WEB_JS / HOME).read_text(encoding='utf-8')
    resolved, unresolved = _ratios(source)
    assert not unresolved, f'unresolved ratios in {HOME}: {unresolved}'
    assert -0.68 in resolved and 0.85 in resolved, (
        f'{HOME} resolves the mix ratios {resolved}, which does not include '
        'both branches of the primary-background choice. #322 is a DIRECTION '
        'bug: a check that saw only one branch would pass a build that mixed '
        'the wrong way on half the themes.'
    )

    # Control 1: a channel offset hidden inside the helper is still flagged.
    offset = source.replace('var BG_DARK = -0.68;', 'var BG_DARK = -180;')
    assert offset != source, 'the BG_DARK declaration was not found to mutate'
    assert _bad_ratios(offset), (
        'A ratio of -180 declared inside the chooser was not reported. The '
        'range check is not reaching through the helper, so moving a ratio '
        'into one is a way out of this file.'
    )

    # Control 2: a return this cannot read is unresolved, not assumed fine.
    opaque = source.replace('return isDark ? BG_DARK : BG;',
                            'return isDark ? someGlobal : otherGlobal;')
    assert opaque != source, 'the chooser return was not found to mutate'
    assert _ratios(opaque)[1], (
        'A chooser returning values this check cannot resolve was treated as '
        'resolved. An unreadable return must land in `opaque` -- that is the '
        'difference between a hole and a reported gap.'
    )
