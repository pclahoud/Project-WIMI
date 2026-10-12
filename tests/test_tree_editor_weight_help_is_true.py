"""The weight field's help text may not promise a distribution (#447).

For as long as anyone can date it, the Add/Edit Subject modal said **"Leave
empty to auto-distribute among siblings"**. Nothing auto-distributed. In
``saveNewNode`` an empty field reads as ``0`` and neither save branch sends a
weight, so the subject was created at 0% and no sibling moved;
``rebalance_sibling_edge_weights`` has exactly one caller in ``src/web/js/``,
the **Rebalance siblings** button. The capability the sentence described
existed and was simply never invoked on save.

It was worse than a stray tooltip for two reasons, and both are why this file
exists rather than a one-line diff and nothing else.

* **The claim was quoted.** ``docs/examples/subject_tree_import_format.md``
  drew #64's decision 3 as a *contrast* between the import rule (0%, the
  blueprint did not weight this) and the editor's field ("share out the
  remainder"), then vouched for the help text by name. ``CLAUDE.md`` and
  ``subject_import.py``'s module docstring restated it. Four documents agreed
  with each other and none of them agreed with the code.
* **The guide ships inside the app.** The ❓ *Import Format Help* modal renders
  it from a generated embed in ``tree_editor.html`` (#69), so a student read
  the promise twice, in two places, and got 0% both times.

The owner's decision (2026-10-07) was to **change the copy, not build the
distribution** — option (b) on #447 — which keeps Stage 2's opt-in rebalance
intact. So the sweeps below are about copy, with one tripwire: if anybody ever
builds option (a), :func:`test_an_empty_field_still_sends_no_weight` goes red
and says that the help string has to move with it.

On the shape of the sweeps
--------------------------

Two lessons from ``test_relation_proposals_markup.py`` are built in.

* **A source sweep's reader needs its own control.** That file's quote-pairing
  regex desynchronised on an apostrophe in a trailing comment and went on
  reading *the code between* the literals, finding nothing, passing. Here the
  reader has a cheaper way to fail the same way: this modal carries **two**
  ``form-help`` lines, and an unanchored match would silently return the
  weight-*range* one — a sentence that has never made a false promise and
  would sail through every assertion below.
* **A sweep needs a mutation control**, or it proves only that it ran. There
  are two here: the historical string, and a subtler mutant that keeps the
  button's name but puts the sharing back on the empty field. The second is
  the one worth having, because the first is the wording nobody would retype.

One place is deliberately **not** swept: ``docs/manual/20_weights.md`` (and the
page generated from it at ``src/web/html/help_weights.html``) quotes the retired
hint verbatim while explaining the shipped behaviour correctly. That chapter was
being written when #447 was found, so its reading is generous rather than wrong
— and it is the one copy that goes stale by this change rather than by a future
one. It is owned elsewhere; a sweep over it would be red on arrival with nobody
able to fix it here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML = REPO_ROOT / 'src' / 'web' / 'html' / 'tree_editor.html'
TREE_JS = REPO_ROOT / 'src' / 'web' / 'js' / 'tree_editor.js'
WEIGHT_JS = REPO_ROOT / 'src' / 'web' / 'js' / 'weight_editor.js'
GUIDE = REPO_ROOT / 'docs' / 'examples' / 'subject_tree_import_format.md'

#: The id of the simple-weight input. The help line under it is the subject of
#: this file; the one under ``modal-weight-low`` / ``-high`` is not.
WEIGHT_INPUT_ID = 'modal-node-weight'

#: The button the honest copy points at, spelled as it is rendered.
REBALANCE_LABEL = 'Rebalance siblings'

#: Wordings that can only ever be the false promise. Deliberately short: a ban
#: on "share out the remainder" would also forbid the *true* sentence about
#: what the button does, and a guard that forbids honest copy gets deleted.
FORBIDDEN = (
    'auto-distribute',
    'auto distribute',
    'autodistribute',
    'distribute among siblings',
    'distributed among siblings',
)

#: Verbs that describe moving weight around. Allowed in the help line only
#: after the button is named, never as something leaving the field empty does.
DISTRIBUTION_WORDS = ('distribut', 'share', 'split', 'spread', 'balance')

OLD_WORDING = 'Leave empty to auto-distribute among siblings'

#: The subtler mutant, and the one a future edit would plausibly write: it
#: keeps the pointer, so every "does it name the button" check passes, and
#: still tells the student that emptiness itself shares the remainder.
SUBTLE_MUTANT = (
    'Leave empty to share the remainder among siblings. '
    'Rebalance siblings can redo it later.'
)


# --------------------------------------------------------------------------- #
# The reader
# --------------------------------------------------------------------------- #

def read_weight_help(html: str) -> str | None:
    """The ``form-help`` line belonging to the simple weight input.

    Anchored on the input's id and bounded by the end of its ``<div>`` group,
    so it cannot fall through to the weight-range group's help line further
    down the modal. Returns ``None`` when the anchor is gone, which is a
    failure the caller can see — the alternative, matching the next
    ``form-help`` anywhere in the file, is how this sweep would come to pass
    over a sentence it is not reading.
    """
    anchor = html.find(f'id="{WEIGHT_INPUT_ID}"')
    if anchor < 0:
        return None
    # The simple-weight group closes before the range group opens.
    end = html.find('id="modal-range-weight-group"', anchor)
    region = html[anchor:end if end > 0 else len(html)]
    match = re.search(r'<p class="form-help">(.*?)</p>', region, re.S)
    return match.group(1).strip() if match else None


@pytest.fixture(scope='module')
def html() -> str:
    return HTML.read_text(encoding='utf-8')


# --------------------------------------------------------------------------- #
# The predicate
# --------------------------------------------------------------------------- #

def promise_faults(help_text: str) -> list[str]:
    """Every way ``help_text`` promises a distribution that does not happen.

    Empty means the sentence is honest. A list rather than a bool so a failure
    says which rule broke, and so the controls below can assert that a mutant
    breaks a *specific* one rather than merely breaking something.
    """
    faults: list[str] = []
    lowered = help_text.lower()

    for phrase in FORBIDDEN:
        if phrase in lowered:
            faults.append(f'says {phrase!r}, which describes no code path')

    if '0%' not in help_text:
        faults.append('never states the weight the subject is actually created at')

    pointer = help_text.find(REBALANCE_LABEL)
    if pointer < 0:
        faults.append(
            f'does not name {REBALANCE_LABEL!r}, the only thing in WIMI that '
            f'shares out a remainder')
        pointer = len(help_text)

    for word in DISTRIBUTION_WORDS:
        at = lowered.find(word)
        if 0 <= at < pointer:
            faults.append(
                f'uses {word!r} before naming {REBALANCE_LABEL!r}, so the '
                f'sharing reads as something leaving the field empty does')

    return faults


# --------------------------------------------------------------------------- #
# The reader's own controls
# --------------------------------------------------------------------------- #

def test_the_reader_finds_the_line_under_the_weight_input(html):
    """Verbatim, and from the file rather than from a construction."""
    help_text = read_weight_help(html)
    assert help_text, 'no form-help line found under the simple weight input'
    assert help_text in html, 'the reader returned text that is not in the file'


def test_the_reader_does_not_fall_through_to_the_range_group(html):
    """The desync this reader can suffer, made to happen on purpose.

    With the anchor renamed the reader must report nothing. If it instead
    returned the weight-*range* group's help line — "Define a weight range
    (e.g., 20% - 25%)" — every assertion in this file would be measuring a
    sentence that was never the problem, and the sweep would pass with the
    false promise still shipping.
    """
    mutated = html.replace(f'id="{WEIGHT_INPUT_ID}"', 'id="renamed-elsewhere"')
    assert mutated != html, 'the mutation did not apply; this control is stale'

    assert read_weight_help(mutated) is None, (
        'the reader found a form-help line with its anchor gone, so it is '
        'matching by position in the file rather than by the input it belongs '
        'to')

    # And the line it would have drifted onto really is there to drift onto,
    # or the control above proves nothing about fall-through.
    assert 'Define a weight range' in html


# --------------------------------------------------------------------------- #
# The sweep
# --------------------------------------------------------------------------- #

def test_the_shipped_help_line_promises_no_distribution(html):
    help_text = read_weight_help(html)
    assert help_text is not None
    faults = promise_faults(help_text)
    assert not faults, (
        f'the weight field\'s help text {help_text!r} promises a '
        f'distribution WIMI does not perform (#447): ' + '; '.join(faults))


def test_the_sweep_would_catch_the_old_wording():
    """The control. Without it this file proves only that it executed."""
    faults = promise_faults(OLD_WORDING)
    assert faults, (
        f'{OLD_WORDING!r} is the exact sentence #447 was filed about and the '
        f'sweep finds nothing wrong with it')
    joined = ' '.join(faults)
    assert 'auto-distribute' in joined
    assert 'never states the weight' in joined, (
        'the old wording also never said what an empty field stores, and the '
        'sweep did not notice that half')
    assert REBALANCE_LABEL in joined, 'the old wording named no button either'


def test_the_sweep_would_catch_a_mutant_that_keeps_the_pointer():
    """The control worth having.

    Nobody would retype ``auto-distribute``. What a later edit plausibly
    writes is a sentence that mentions the button — satisfying any check for
    "does it point somewhere" — while still telling the student that leaving
    the field empty is itself what shares the remainder. The positional rule
    is the only thing standing between that mutant and a green run.
    """
    faults = promise_faults(SUBTLE_MUTANT)
    assert faults, f'{SUBTLE_MUTANT!r} slipped through'
    joined = ' '.join(faults)
    assert 'before naming' in joined, (
        f'the mutant was caught, but not by the positional rule: {faults}. '
        f'That rule is the one covering wordings nobody has written yet')
    assert not any(phrase in SUBTLE_MUTANT.lower() for phrase in FORBIDDEN), (
        'the mutant contains a forbidden phrase, so it is testing the easy '
        'rule and not the positional one')


def test_the_honest_line_is_not_caught_by_its_own_rules():
    """The other direction: a guard that fails everything guards nothing."""
    honest = (
        'Leave empty and the subject is created at 0%. Rebalance siblings, '
        "in the weight panel, shares out a parent's remainder when you ask "
        'it to.'
    )
    assert not promise_faults(honest), (
        'the rules reject a sentence that states the outcome and attributes '
        'the sharing to the button, so they cannot be satisfied')


# --------------------------------------------------------------------------- #
# The pointer has to point at something
# --------------------------------------------------------------------------- #

def test_the_button_the_help_line_names_is_the_button_that_exists():
    """#174, one layer out: the copy may not direct a press at nothing.

    Removing the pointer entirely was offered to the owner on #447 and not
    chosen, because the old hint was the only thing in the UI gesturing at the
    one control that shares a remainder. Keeping it costs this assertion: the
    label in the help line must be the label on the button.
    """
    weight_js = WEIGHT_JS.read_text(encoding='utf-8')
    assert REBALANCE_LABEL in weight_js, (
        f'the help line points at {REBALANCE_LABEL!r} and no such label is '
        f'rendered in weight_editor.js')
    assert 'rebalanceSiblings()' in weight_js, (
        'the label exists but nothing calls the rebalance; the pointer is '
        'decorative')


# --------------------------------------------------------------------------- #
# The tripwire
# --------------------------------------------------------------------------- #

def test_an_empty_field_still_sends_no_weight():
    """The reason the copy says 0%, asserted so the two cannot drift apart.

    This is the half #447 chose *not* to change. ``parseFloat('') || 0`` makes
    an empty field a zero, and from there ``simpleWeight !== null &&
    simpleWeight > 0`` is false, so no exam weight is sent and nothing
    consults the siblings.

    **If you are reading this because it went red:** you have probably built
    #447's option (a), the field keeping its original promise. That is a
    legitimate decision and it needs the owner's sign-off on #447 — and when
    it lands, the help line, the import guide's table and
    ``subject_import.py``'s weight decision 3 all move with it, because they
    describe this branch.
    """
    tree_js = TREE_JS.read_text(encoding='utf-8')
    save = tree_js[tree_js.index('async function saveNewNode('):]
    save = save[:save.index('\n}\n')]

    assert "parseFloat(simpleInput?.value) || 0" in save, (
        'the empty-field reading changed; re-derive what an empty box stores '
        'before trusting the help text')
    assert 'simpleWeight !== null && simpleWeight > 0' in save, (
        'the guard that drops a zero weight is gone, so an empty field may '
        'now store something; check the help line still describes it')
    for call in ('rebalanceSiblings', 'rebalance_sibling', 'rebalanceSibling'):
        assert call not in save, (
            f'saveNewNode now calls {call!r}. Creating a subject rebalances '
            f'its siblings, which is #447 option (a) and Stage 2 removed it '
            f'deliberately; the help line and the import guide have to be '
            f'updated in the same change')


# --------------------------------------------------------------------------- #
# The guide, in the repo and in the app
# --------------------------------------------------------------------------- #

def guide_sources() -> dict[str, str]:
    """The markdown and the copy of it that ships inside the app.

    ``check_import_guide_sync.py`` already proves the two are byte-identical,
    so sweeping both is nearly redundant — nearly, because the embed is what a
    student reads and a sweep over the source alone would have nothing to say
    on the day the generator is bypassed.
    """
    html = HTML.read_text(encoding='utf-8')
    start = html.index('id="import-help-source"')
    embed = html[start:html.index('</script>', start)]
    return {'markdown': GUIDE.read_text(encoding='utf-8'), 'embed': embed}


@pytest.mark.parametrize('which', ['markdown', 'embed'])
def test_the_import_guide_does_not_repeat_the_promise(which):
    """It said the editor's field means "Share out the remainder among
    siblings", in a table, and then vouched for the help text by name.

    Both halves are now gone. What replaced them is not a deletion: the two
    rules still differ, in what the zero *records* — the blueprint did not
    weight this, against the student has not decided yet — and #64's decision
    3 is still drawn as two rows.
    """
    text = guide_sources()[which]
    lowered = text.lower()
    for phrase in FORBIDDEN:
        assert phrase not in lowered, (
            f'the {which} copy of the import guide still says {phrase!r}; it '
            f'renders in the app, so a student reads the false promise twice')

    row = next(
        (line for line in text.splitlines()
         if line.startswith('|') and "tree editor's weight field" in line),
        None)
    assert row is not None, (
        "the guide no longer has a row for the tree editor's weight field; "
        '#64 decision 3 is a contrast of two rules and needs both rows')
    assert '0%' in row, (
        f'the row for the editor\'s field, {row!r}, does not say 0%. Both '
        f'sides store 0%; only the meaning differs')
    assert 'remainder' not in row.lower(), (
        f'the row for the editor\'s field, {row!r}, still attributes a '
        f'remainder to it')


def test_the_guide_sweep_would_catch_the_old_table_row():
    """The control, and it checks the reader as well as the rule.

    The row is found by the words in it rather than by a line number, so this
    also fails if the extraction stops matching — which would otherwise leave
    the assertions above reading ``None`` and skipping.
    """
    old_row = ("| The tree editor's weight field | Share out the remainder "
               'among siblings |')
    assert '0%' not in old_row and 'remainder' in old_row.lower(), (
        'the row this control is built from is not the one that was wrong')

    text = GUIDE.read_text(encoding='utf-8')
    rows = [line for line in text.splitlines()
            if line.startswith('|') and "tree editor's weight field" in line]
    assert len(rows) == 1, (
        f'expected exactly one row describing the editor\'s weight field, '
        f'found {len(rows)}; the reader above would be ambiguous')
    assert rows[0] != old_row, 'the old row is still in the guide'
