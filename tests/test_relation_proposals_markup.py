"""The entry form's relation proposals: the wiring nothing else can check (#60).

`relation_proposals.js` builds everything it renders, so there is almost no
markup to assert. What there *is* is the wiring between four files that fail
silently when it is wrong:

* a mount id the module looks up — `getElementById` answers null and the
  `if (!mountEl) return null` after it swallows that, so the feature simply
  never appears;
* a per-page `<link>` for the stylesheet — WIMI loads CSS per page, so classes
  defined in a file this page does not link render with browser defaults and
  no error anywhere (the gotcha that bit Stage 9's Weight Sources card);
* a `<script>` tag before `question_entry.js`, which calls
  `window.attachRelationProposals` from `initRichTextEditors`;
* the mount living **inside** the gated container, so the page gate's `inert`
  covers it.

That last one is the one with no symptom. A button outside `.entry-page` is
pressable while the form is still gated, and #114 is the whole file about what
happens to work done in that window: `resetFormForNewEntry()` and the editors'
queued `''` discard it, with `isDirty` still false and no error anywhere.

The copy assertions are deliberate too. Two of them pin decisions that read as
arbitrary wording and are not:

* **two rejections, named**, because the kind decides the scope and #60's
  adjudication found 25 of 45 rejections meant "you misread my sentence";
* **no "try again" in the wedge sentence**, because after a wedge every later
  attempt fails identically until a restart (#174).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = REPO_ROOT / 'src' / 'web'
HTML = WEB / 'html' / 'question_entry.html'
MODULE = WEB / 'js' / 'relation_proposals.js'
PAGE_JS = WEB / 'js' / 'question_entry.js'
CSS = WEB / 'css' / 'relation_proposals.css'

MOUNT_ID = 'explanation-relations'


@pytest.fixture(scope='module')
def html() -> str:
    return HTML.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def module_js() -> str:
    return MODULE.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def page_js() -> str:
    return PAGE_JS.read_text(encoding='utf-8')


# ==================== the wiring ====================

def test_the_mount_the_module_looks_up_exists(html, module_js):
    """Otherwise `if (!mountEl) return null` swallows the whole feature."""
    assert f"getElementById('{MOUNT_ID}')" in PAGE_JS.read_text(encoding='utf-8')
    assert f'id="{MOUNT_ID}"' in html


def test_the_page_links_the_stylesheet(html):
    """CSS is per page here. Without the link the cards render unstyled."""
    assert 'css/relation_proposals.css' in html


def test_the_page_loads_the_module_before_its_caller(html):
    """`question_entry.js` calls `attachRelationProposals` during init."""
    module_at = html.index('js/relation_proposals.js')
    caller_at = html.index('js/question_entry.js')
    assert module_at < caller_at, (
        'relation_proposals.js must be loaded before question_entry.js, '
        'which calls window.attachRelationProposals from '
        'initRichTextEditors()')


def test_the_mount_is_inside_the_gated_container(html):
    """The one with no symptom.

    `.entry-page` ships `inert` and `markEntryFormReady()` removes it. A
    button outside that container is pressable while the form still discards
    everything done to it (#114) — and the page looks completely normal.
    """
    gated_at = html.index('data-page-gated')
    mount_at = html.index(f'id="{MOUNT_ID}"')
    assert gated_at < mount_at, 'the mount is before the gated container opens'

    # And inside it rather than after it: the gate's own voice is the one
    # thing that is deliberately a sibling, and test_page_gate_markup.py
    # guards that. Everything else belongs within.
    after_mount = html[mount_at:]
    assert '</body>' in after_mount
    depth_closers = after_mount.count('</div>')
    assert depth_closers >= 2, (
        'the mount appears to be outside the page container; it must be '
        'nested inside .entry-page so inert covers it')


def test_the_mount_is_immediately_after_the_explanation(html):
    """#4695: inline confirmation, "not a later review queue".

    Verification gets more expensive the further it sits from the writing, so
    the proposals belong under the field they were read from rather than in a
    panel elsewhere on the page.
    """
    explanation_at = html.index('id="explanation-editor"')
    mount_at = html.index(f'id="{MOUNT_ID}"')
    reflection_at = html.index('id="reflection-editor"')
    assert explanation_at < mount_at
    assert reflection_at < explanation_at, 'sanity: reflection comes first'
    between = html[explanation_at:mount_at]
    assert 'write-block' not in between, (
        'something else opens between the explanation and the proposals; '
        'they must sit in the same block as the field they read')


def test_the_host_reads_its_context_at_call_time(page_js):
    """A captured entry id is the one thing that must never be captured.

    A pass runs for seconds, and in that window the student may save, move on
    or reset. `getContext` is an arrow function evaluated per call for the
    same reason `initDictation`'s is (#59 §3.5).
    """
    attach = page_js[page_js.index('function initRelationProposals'):]
    attach = attach[:attach.index('\n}\n')]
    assert 'getContext: () =>' in attach, (
        'getContext must be a function the module calls, not a value')
    assert 'EntryState.currentEntry?.id' in attach


def test_the_button_is_re_parked_but_the_cards_are_not_rebuilt(page_js, module_js):
    """The silent-data-loss shape, in miniature.

    The host calls `update()` from `markDirty()`, which fires on every edit.
    If that rebuilt the proposal list, a student part way through editing a
    proposal's reason would lose it the moment they touched the explanation —
    with no error. `update` is therefore bound to the bar's render alone.
    """
    assert 'EntryState.relationProposals?.update()' in page_js
    assert 'update: renderBar,' in module_js, (
        'update must re-draw the bar only; binding it to the full render '
        'discards an in-progress edit to a card')


def test_a_new_entry_clears_the_previous_suggestions(page_js):
    """A finished list left on screen would belong to the last entry."""
    reset = page_js[page_js.index('function resetFormForNewEntry'):]
    reset = reset[:reset.index('\n}\n')]
    assert 'relationProposals?.clear()' in reset


# ==================== the decisions the copy carries ====================

def test_rejecting_offers_both_kinds_and_neither_is_a_default(module_js):
    """m027's scope rule, in the UI.

    `misread` suppresses the pair for this entry only; `not_related`
    suppresses it everywhere. #60's adjudication found **25 of 45** rejections
    meant the first, so a single Reject button would have globally suppressed
    a true pair most of the time it was pressed.
    """
    assert "'misread'" in module_js and "'not_related'" in module_js
    assert 'entry-form-relation-misread' in module_js
    assert 'entry-form-relation-not-related' in module_js
    # No third path that rejects without a kind.
    assert module_js.count('rejectRelationProposal') == 1
    call = module_js[module_js.index('rejectRelationProposal'):]
    call = call[:call.index('})')]
    assert 'kind: kind' in call, 'the kind must be passed, never defaulted'


def test_each_rejection_states_its_scope_in_its_label(module_js):
    """#398, owner's decision: put the scope in the labels.

    The two rejections reach different distances — `misread` suppresses the
    pair on this entry, `not_related` suppresses it everywhere — and that is
    the entire reason there are two buttons. It used to be stated **only** in
    a `title`: never shown on a touch device, not shown on keyboard focus,
    inconsistently exposed to screen readers, and about a second late for a
    decisive mouse. So a student who hovered neither button chose between two
    equally weighted presses without being told that one of them reaches
    across their whole exam.

    What this asserts is that the scope is in the *visible* text of each
    button. The accompanying scenario measures the accessible name Chromium
    actually computes, which is the half a source read cannot do.
    """
    card = module_js[module_js.index('function buildCard('):]
    card = card[:card.index('\n        }\n')]

    labels = dict(re.findall(r"(misread|unrelated)\.textContent = '([^']*)'",
                             card))
    assert set(labels) == {'misread', 'unrelated'}, (
        f'could not read both rejection labels out of buildCard: {labels}')

    assert 'this entry' in labels['misread'].lower(), (
        f"the local rejection's label, {labels['misread']!r}, does not say "
        f"that it applies to this entry only. The scope must be visible; a "
        f"`title` is not (#398)")
    assert 'never' in labels['unrelated'].lower(), (
        f"the global rejection's label, {labels['unrelated']!r}, does not say "
        f"that it suppresses the pair for good. A student pressing it is "
        f"entitled to know that before they press it (#398)")
    assert labels['misread'] != labels['unrelated']

    # The reason is what moved to the tooltip, and it had better still be
    # there: the decision gives up the reason-framing in the LABEL, not the
    # reason.
    titles = dict(re.findall(r"(misread|unrelated)\.title = '([^']*)'", card))
    assert set(titles) == {'misread', 'unrelated'}, (
        'a rejection lost its reason entirely; the decision moved it to the '
        '`title`, it did not delete it')


def test_neither_rejection_is_styled_more_quietly_than_the_other(module_js):
    """Equal weight, which #398 calls a text change and not a hierarchy one.

    25 of 45 rejections meant the local one, so it is not the secondary
    choice. One class for both buttons is what keeps that true — a variant
    class on either would let the two drift apart in a stylesheet nobody
    reads next to this file.
    """
    card = module_js[module_js.index('function buildCard('):]
    card = card[:card.index('\n        }\n')]
    classes = re.findall(r"el\('button', '([^']*)', \{", card)
    rejects = [c for c in classes if 'reject' in c]
    assert len(rejects) == 2, f'expected two rejection buttons, found {rejects}'
    assert rejects[0] == rejects[1] == 'relprop-reject', (
        f'the two rejections carry different classes ({rejects}), so one can '
        f'be made quieter than the other without this file changing')


def test_the_disabled_find_button_explains_itself_in_visible_text(module_js):
    """The other half of #398, and the one with no symptom in the source.

    The only explanation for the greyed button was `findButton.title`, which
    opens on hover — and a `disabled` button cannot take focus at all, so a
    keyboard user can never surface it, while a touch user has no hover to
    surface it with. Measured both ways in
    `tests/wimi_test/scenarios/test_relations_find_says_why_it_cannot_run.py`,
    which also records that #398's own stated mechanism (Chromium dispatching
    no mouse events to a disabled control) is **false** on this engine.
    """
    assert 'findButton.title' not in module_js, (
        'the Find button is explaining itself through a `title` again, which '
        'a keyboard or touch user cannot read on a disabled control (#398)')

    bar = module_js[module_js.index('function renderBar('):]
    bar = bar[:bar.index('\n        }\n')]
    assert 'showHint(' in bar, (
        'renderBar must draw the reason the button is unavailable. It cannot '
        'live in renderList: `update()` is bound to renderBar alone, so a '
        'sentence drawn from the list would not follow the explanation as '
        'the student types')

    # One vocabulary for the state, whether it is reached before a press or
    # from the bridge's refusal after one.
    #
    # This asserted the literal `describeNotStarted('no_explanation')` until
    # #483, which is the defect it was pinning: the argument was FIXED, so the
    # sentence named the empty-explanation case even when the real blocker was
    # an unsaved entry -- the commoner of the two, since entry_id is null
    # until the first autosave. The requirement was always reuse rather than
    # that argument, so it is now asserted as reuse, and the argument is
    # required to be computed.
    assert 'hintEl.textContent = describeNotStarted(' in module_js, (
        'the hint must reuse describeNotStarted so the pre-press sentence and '
        'the post-refusal one cannot drift apart')
    assert "hintEl.textContent = describeNotStarted('" not in module_js, (
        'the hint names a FIXED reason again (#483). The button is greyed when '
        'the entry is unsaved OR the explanation is empty, so a constant '
        'argument is wrong in whichever case it does not name')

    # Removed, not emptied: an emptied node stays in the accessibility tree
    # and would need `:empty` to collapse, which is forbidden outright.
    hint = module_js[module_js.index('function showHint('):]
    hint = hint[:hint.index('\n        }\n')]
    assert 'removeChild(hintEl)' in hint, (
        'the hint must leave the tree when the button is pressable; emptying '
        'it leaves a node announcing nothing and needs `:empty` to collapse')
    assert 'aria-describedby' in hint


def test_the_wedge_sentence_directs_no_press(module_js):
    """#174. After a wedge, every later attempt fails identically.

    The guard is both halves: the copy says restart rather than retry, and
    the button is drawn from `retryable` with `wedged` overriding it.
    """
    wedge_copy = module_js[module_js.index('if (wedged) {'):]
    wedge_copy = wedge_copy[:wedge_copy.index('}')]
    assert 'Restart' in wedge_copy
    for forbidden in ('try again', 'Try again'):
        assert forbidden not in wedge_copy, (
            'the wedge sentence must not direct a retry; the worker refuses '
            'every later start until WIMI restarts')
    assert 'failure.error.retryable && !failure.wedged' in module_js, (
        'the retry button must be gated on the payload AND on wedged')


def test_the_reason_is_prefilled_and_editable(module_js):
    """#5494, and #60's "do not assert a label the student clicks past".

    The passage goes into a textarea the student can see and change, not
    behind the Confirm button. That is the anti-rubber-stamp property: both
    the sentence and the type are in front of them when they confirm.
    """
    assert "el('textarea', 'relprop-reason'" in module_js
    assert 'reason.value = proposal.passage;' in module_js
    assert "el('select', 'relprop-type'" in module_js


def test_confirming_without_a_type_list_keeps_the_proposed_type(module_js):
    """The data-corrupting path, found by reading rather than by a failure.

    `getRelationTypes` can legitimately return nothing — an exam with no
    active types, or a read that was refused. An empty `<select>` yields
    `''`, which becomes `null`, which differs from the proposal's own type —
    so `changeType` would be true and confirming would have **untyped the
    relation**. The student was never shown a choice, so keeping the proposed
    type is the only honest answer.
    """
    assert 'if (relationTypes.length) {' in module_js, (
        'the select must not be built when there is nothing to put in it')
    accept = module_js[module_js.index('function accept('):]
    accept = accept[:accept.index('\n        }\n')]
    assert 'var offered = typeValue !== null;' in accept
    assert 'changed = offered &&' in accept, (
        'changeType must be false when no select was offered, or confirming '
        'strips the type the model proposed')


def test_an_unavailable_machine_renders_nothing(module_js):
    """#5179: no disabled button, no notice, no placeholder.

    Both render halves return early on `!ready`, so an unavailable machine is
    indistinguishable from a build without the feature.
    """
    for half in ('renderBar', 'renderList'):
        body = module_js[module_js.index(f'function {half}('):]
        body = body[:body.index('\n        }\n')]
        assert 'if (!ready) return;' in body, (
            f'{half} must render nothing when the feature cannot run')


def test_every_class_the_module_uses_is_styled(module_js):
    """The per-page CSS gotcha, swept rather than remembered."""
    css = CSS.read_text(encoding='utf-8')
    used = set(re.findall(r"el\('[a-z]+', '(relprop[\w-]*)'", module_js))
    assert used, 'no classes parsed out of the module'
    missing = sorted(name for name in used if f'.{name}' not in css)
    assert not missing, f'{missing} are used but never styled'


def test_the_wrappers_occupy_nothing_when_the_feature_is_silent():
    """"Degrade to absent" has to mean absent in the layout too.

    The module keeps its bar and its list as permanent children so the button
    can be re-drawn without rebuilding the cards. A flex container with a
    `gap` over two empty boxes contributes one gap's height — on every entry,
    on every machine where the feature cannot run, under the explanation,
    for a feature the student is not supposed to know exists.

    So the wrappers are `display: contents` with no gap, and the spacing is
    `margin-top` on the elements the module actually creates, which an absent
    element cannot contribute. `:empty` would say this in one line and is
    exactly what #134/#136/#141 forbid.
    """
    css = CSS.read_text(encoding='utf-8')
    for selector in ('.relprop {', '.relprop-bar-wrap,'):
        block = css[css.index(selector):]
        block = block[:block.index('}')]
        assert 'display: contents' in block, (
            f'{selector} must not form a box; an empty one would still take '
            f'up a gap')
        assert 'gap:' not in block, (
            f'{selector} carries a gap, which two empty children would still '
            f'space apart')
    # And the spacing really is on the created elements.
    for selector in ('.relprop-bar {', '.relprop-card {'):
        block = css[css.index(selector):]
        block = block[:block.index('}')]
        assert 'margin-top' in block, f'{selector} has no spacing of its own'


def test_a_pair_waiting_elsewhere_is_a_note_with_nothing_to_press(module_js):
    """#390, owner's decision: say so on the card -- and only say so.

    There is nothing on THIS entry to answer, so the note must carry no
    Confirm and no Reject. It is drawn from `renderList`, after that
    function's `!ready` return, so an unavailable machine stays silent
    (#5179) whatever the bridge sent.
    """
    note = module_js[module_js.index('function buildPendingNote('):]
    note = note[:note.index('\n        }\n')]
    assert 'entry-form-relations-pending' in note
    for control in ("'button'", "'select'", "'textarea'", 'Confirm', 'reject'):
        assert control not in note, f'the pending note offers {control}'

    render = module_js[module_js.index('function renderList('):]
    render = render[:render.index('\n        }\n')]
    assert render.index('if (!ready) return;') < render.index('buildPendingNote(')


# ==================== the accounting sentence (#396) ====================

def js_string_literals(source: str) -> list[str]:
    """Every single-quoted literal in `source`, comments skipped.

    This file's `--` is the repo's ASCII convention for *comments*, so a sweep
    that did not skip them would flag almost every line. What is left is text
    that reaches a student: `textContent`, `title`, toast messages.

    **This was three regexes until #398, and they desynchronised.** The
    trailing-comment pattern required the comment body to contain no `'`, and
    line 81 of the module is::

        var MAX_POLLS = 400;  // 160 s, well past the runtime's own 60 s ceiling

    That apostrophe survives the strip and then pairs with the next real
    quote, so from there on the "literals" the reader returned were the *code
    between* the literals, inverted. Measured: the first entry it yielded was
    ``"s own 60 s ceiling\\n\\n    function el(tag, ...``, and the whole file
    after line 81 — which is all of the copy — was outside anything it looked
    at. A `--` in any of those strings would not have been found. The sweep
    below was passing on a file it could not read, and
    :func:`test_the_reader_does_not_desynchronise` is here so that cannot
    recur silently.

    A scanner rather than a regex, because the states genuinely nest: a `//`
    inside a string is not a comment, and a quote inside a comment is not a
    string. It is still ~20 lines, and it is shared with
    `test_relations_panel_vocabulary.py` so the two sweeps cannot drift to
    two different readers.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        char = source[i]
        if char == '/' and i + 1 < n and source[i + 1] == '/':
            newline = source.find('\n', i)
            i = n if newline < 0 else newline + 1
        elif char == '/' and i + 1 < n and source[i + 1] == '*':
            close = source.find('*/', i + 2)
            i = n if close < 0 else close + 2
        elif char in '"`':
            quote, i = char, i + 1
            while i < n and source[i] != quote:
                i += 2 if source[i] == '\\' else 1
            i += 1
        elif char == "'":
            i += 1
            buf: list[str] = []
            while i < n and source[i] != "'":
                if source[i] == '\\':
                    buf.append(source[i:i + 2])
                    i += 2
                else:
                    buf.append(source[i])
                    i += 1
            out.append(''.join(buf))
            i += 1
        else:
            i += 1
    return out


#: The sweeps below read it under its old name.
_student_facing_strings = js_string_literals


def test_the_reader_does_not_desynchronise(module_js):
    """The control for the control, added with #398.

    Both sweeps in this file are only as good as the reader, and a desynced
    reader fails *open* — it returns plausible-looking text and finds nothing.
    So: literals from the top, the middle and the bottom of the module come
    back verbatim, and the one at the bottom is the real test, because it sits
    well past the apostrophe that broke the regex version.
    """
    literals = js_string_literals(module_js)
    for expected in (
        'use strict',                      # the first line of the module
        'Write the explanation first — that is what WIMI ',  # ~line 150
        'Not in this entry',               # a label, mid-file
        'The model files are missing or damaged. Settings → ',  # past line 81
        'Relation added. It is on the subject’s Related ',    # near the end
    ):
        assert expected in literals, (
            f'the reader did not return {expected!r} as a literal. It is in '
            f'the file, so the reader has desynchronised and every sweep '
            f'built on it is passing over text it cannot see')


def test_no_student_facing_string_contains_a_double_hyphen(module_js):
    """#396's third defect, swept rather than fixed once.

    The `misread` button's `title` read "may well be related -- this sentence
    just does not say so", and `title` renders verbatim. The `--` is this
    repo's convention for ASCII *comments*; the same file already used real
    punctuation in the wedge sentence and both reject toasts, so it was an
    oversight and not house style.

    A sweep because the next one will be in a different string.
    """
    offenders = [s for s in _student_facing_strings(module_js) if '--' in s]
    assert not offenders, (
        f'these student-visible strings contain a literal `--`, which renders '
        f'verbatim: {offenders}. Use an em dash (\\u2014); `--` is the ASCII '
        f'convention for comments, not for copy.')


def test_the_sweep_would_catch_one(module_js):
    """The control. Without it the sweep passes on a file it cannot read.

    Re-introduces #396's own string and requires the same reader to find it —
    which also proves the comment-stripping has not become so aggressive that
    it eats real literals.
    """
    mutated = module_js.replace(
        'may well be related — this', 'may well be related -- this')
    assert mutated != module_js, (
        'the mutation did not apply, so this control is stale and the sweep '
        'above proves nothing. Note the file carries a REAL em dash (U+2014), '
        'not the escape sequence `\\u2014` — matching the em dashes already in '
        'the wedge sentence and both reject toasts.')
    assert any('--' in s for s in _student_facing_strings(mutated)), (
        'the reader cannot see a `--` inside a single-quoted literal, so the '
        'sweep above proves nothing')


def test_the_ambiguous_clause_names_what_was_found(module_js):
    """"2 where a name matches two subjects" never said 2 of what.

    And its two ternary arms were byte-identical, so the singular/plural
    choice was dead code that read as live — the shape that survives review
    because it looks like it is doing something.
    """
    note = module_js[module_js.index('function buildExtraNote('):]
    note = note[:note.index('\n        }\n')]

    arms = re.findall(r"\?\s*'([^']*)'\s*\n?\s*:\s*'([^']*)'", note)
    assert arms, 'no singular/plural ternary found in buildExtraNote'
    for singular, plural in arms:
        assert singular != plural, (
            f'a ternary in buildExtraNote has identical arms ({singular!r}), '
            f'so it decides nothing')

    assert 'name that matches' in note and 'names that each match' in note, (
        'the ambiguous clause must name what was found, not just count it')


def test_the_plural_follows_the_item_count_not_the_clause_count(module_js):
    """`parts.length > 1` made three items in one clause read "that".

    The clauses are joined with "and", so their number says how many KINDS of
    thing were found — never how many things. Three unmatched connections is
    one clause and three items.
    """
    note = module_js[module_js.index('function buildExtraNote('):]
    note = note[:note.index('\n        }\n')]
    assert 'parts.length > 1' not in note, (
        'the plural still keys off the number of clauses joined, so one '
        'clause describing three items reads "so it did not suggest that"')
    assert "items > 1 ? 'those' : 'that'" in note, (
        'the plural must follow the summed item count')
    assert "(extra.unmatched || 0) + (extra.ambiguous || 0)" in note, (
        'the item count must sum both kinds; either alone undercounts')
