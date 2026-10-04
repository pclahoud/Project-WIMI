"""The shipped macOS first-launch instructions must not tell anyone to
right-click -> Open (#179).

The instruction was wrong, not merely unhelpful. On a quarantined copy of the
adhoc-signed, un-notarized build, `open WIMI.app` raises *"Apple could not
verify 'WIMI' is free of malware that may harm your Mac or compromise your
privacy"* whose only buttons are **Move to Trash** and **Done** -- there is no
Open button -- and a Control-click Open from Finder raises the identical
dialog. Measured on a Mac mini M4 / macOS 26.2, MDM-managed, non-admin
account (#179: T19 2026-09-24, and the working route 2026-10-02).

So `build_macos.sh`'s closing message and `docs/BUILD_MACOS.md` were both
walking a recipient into a dialog whose prominent action is to delete the app.
The supported route is `xattr -dr com.apple.quarantine /path/to/WIMI.app` from
Terminal, until the build is signed and notarized (#274).

**Why a source check.** Nothing about this is observable from Linux or
Windows, and it is observable on macOS only by quarantining a copy on a
machine that did not build it -- which is why the wrong instruction survived
from the first macOS build until #179 measured it. The same reasoning as
`tests/test_build_spec_msvc_runtime.py`: the thing being guarded is a *string
that ships*, the failure is invisible to everyone who could find it, and a
static assertion is the only guard available on the platforms CI runs on.

**The scanner has to tolerate the refutation.** These files now say, on
purpose, that a context-menu Open does *not* work -- so matching the phrase
alone would flag the honest history and push the next author into deleting it.
Each match is therefore judged inside a **sentence**, and a sentence that
carries the instruction must also carry one of `_REFUTATIONS`. The window is a
sentence rather than a paragraph so a refutation cannot be borrowed from the
sentence next door; `test_a_refutation_elsewhere_is_not_a_licence` is the
control for that.

Three deliberate non-assertions:

- **Nothing here claims "Open Anyway" works.** It is unmeasured -- it did not
  appear on the one host where anyone looked -- so the test only requires that
  a file mentioning it also says it is untested.
- **`First Launch.command` is not required to be absent.** It is useful on the
  build host; only its advertising was wrong. What is asserted is the absence
  of the "without terminal" claim.
- **No test here depends on the quarantine command staying the supported
  route.** The owner chose it on 2026-10-02 and #274 is meant to replace it
  with a signed, notarized build. What this file guards is narrower and
  outlives that: the context-menu instruction is false on macOS 26.2 whichever
  route ships. `test_each_file_names_the_supported_route` is the one assertion
  tied to today's choice, and it is a single constant to edit when #274 lands.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The two files a macOS recipient's instructions actually come from. The
#: build script because it is the last thing the person distributing the app
#: reads, and the doc because it is what they are pointed at.
#:
#: `docs/testing/T19_MACOS_VERIFICATION.md` is deliberately NOT here: it is a
#: measurement record that quotes the broken instruction as its finding, and a
#: guard that forced a report to redact what it measured would be worse than
#: no guard.
SHIPPED_INSTRUCTIONS = (
    ROOT / 'build_macos.sh',
    ROOT / 'docs' / 'BUILD_MACOS.md',
)

#: "Use the context menu, then pick Open." Every spelling of the gesture, then
#: `open` within a short run. The `-> `, `→` and `and select "..."` joiners all
#: fit inside it.
#:
#: The gap deliberately allows `.`, which an earlier version did not -- and
#: that version missed the *original* instruction, because `'First
#: Launch.command' -> Open` has a period in the filename, as does `Ctrl-click
#: WIMI.app and select Open`. Excluding periods to approximate a sentence
#: boundary is unnecessary anyway: `_sentences` has already made the window a
#: sentence before this runs.
_CONTEXT_MENU_OPEN = re.compile(
    r'(right[\s-]*click|control[\s-]*click|ctrl[\s-]*click'
    r'|secondary[\s-]*click|context[\s-]*menu)'
    r'[^\n]{0,80}?\bopen\b',
    re.IGNORECASE,
)

#: A sentence carrying the gesture is acceptable only if it also says the
#: gesture fails. Kept short and literal on purpose -- a long list of near
#: synonyms would let a vaguely-worded instruction through.
_REFUTATIONS = (
    'does not work',
    'did not work',
    'no open button',
    'same dialog',
    'identical dialog',
    'identical refusal',
    'is refused',
    'not an alternative',
    'do not restore it',
)

#: The #179 route, and the flag it removes. Asserted present so that
#: *deleting* the instructions cannot pass this file -- silence about first
#: launch is the other way to ship something false.
_SUPPORTED_ROUTE = 'xattr -dr com.apple.quarantine'

#: `build_macos.sh` carried "bypass Gatekeeper without terminal" about the
#: helper script. The phrase is only a claim when nothing in the sentence
#: denies it -- "cannot be handed to anyone without a Terminal step" is the
#: *correct* statement and uses the same words, which an earlier version of
#: this file flagged. See `test_a_denial_of_a_no_terminal_path_is_allowed`.
_NO_TERMINAL_CLAIM = re.compile(
    r'without\s+(?:a\s+|the\s+|using\s+)?terminal', re.IGNORECASE
)
_NO_TERMINAL_DENIALS = ('cannot', 'no way', 'never', 'impossible', 'not possible')


def _sentences(text: str) -> list[str]:
    """Sentence-sized windows, with paragraph soft-wraps joined first.

    Markdown prose and consecutive `echo` lines both wrap a sentence across
    source lines, so a line-at-a-time window would split the instruction away
    from its refutation and flag correct text.
    """
    out: list[str] = []
    for paragraph in re.split(r'\n\s*\n', text):
        joined = ' '.join(line.strip() for line in paragraph.splitlines())
        out.extend(part for part in re.split(r'(?<=[.!?])\s+', joined) if part)
    return out


def _offending_sentences(text: str) -> list[str]:
    """Sentences that tell the reader to open the app from a context menu."""
    offenders = []
    for sentence in _sentences(text):
        if not _CONTEXT_MENU_OPEN.search(sentence):
            continue
        lowered = sentence.lower()
        if not any(refutation in lowered for refutation in _REFUTATIONS):
            offenders.append(sentence)
    return offenders


def _no_terminal_claims(text: str) -> list[str]:
    """Sentences asserting that something works with no Terminal involved."""
    claims = []
    for sentence in _sentences(text):
        if not _NO_TERMINAL_CLAIM.search(sentence):
            continue
        lowered = sentence.lower()
        if not any(denial in lowered for denial in _NO_TERMINAL_DENIALS):
            claims.append(sentence)
    return claims


@pytest.fixture(scope='module')
def shipped() -> dict[Path, str]:
    return {path: path.read_text(encoding='utf-8') for path in SHIPPED_INSTRUCTIONS}


@pytest.mark.parametrize('path', SHIPPED_INSTRUCTIONS, ids=lambda p: p.name)
def test_no_shipped_instruction_says_to_open_from_the_context_menu(
    path: Path, shipped: dict[Path, str]
) -> None:
    offenders = _offending_sentences(shipped[path])
    assert offenders == [], (
        f'{path.name} tells a recipient to open WIMI from a Finder context '
        f'menu. On macOS 26.2 that dialog has no Open button -- only Move to '
        f'Trash and Done -- so this walks a student into deleting the app '
        f'(#179, measured). The supported route is '
        f'`{_SUPPORTED_ROUTE} /path/to/WIMI.app` from Terminal. Offending '
        f'sentences: {offenders}'
    )


@pytest.mark.parametrize('path', SHIPPED_INSTRUCTIONS, ids=lambda p: p.name)
def test_each_file_names_the_supported_route(
    path: Path, shipped: dict[Path, str]
) -> None:
    """Removing the instructions entirely must not pass this file.

    The failure being guarded is "the shipped text is wrong", and an empty
    section is wrong in the same direction: the recipient still cannot open
    the app and now has nothing to go on.
    """
    assert _SUPPORTED_ROUTE in shipped[path], (
        f'{path.name} does not name `{_SUPPORTED_ROUTE}`, the supported '
        f'first-launch route (#179). Deleting the wrong instruction is not '
        f'the same as fixing it.'
    )


@pytest.mark.parametrize('path', SHIPPED_INSTRUCTIONS, ids=lambda p: p.name)
def test_each_file_says_the_route_needs_terminal(
    path: Path, shipped: dict[Path, str]
) -> None:
    """`First Launch.command` cannot bootstrap itself, so the step is manual.

    Double-clicking the helper hits the same refusal as the app, because the
    `.command` file is quarantined too (#179, T19). A reader who is not told
    to open Terminal has no way to run the command above.
    """
    assert 'terminal' in shipped[path].lower(), (
        f'{path.name} gives a command without saying it has to be run from '
        f'Terminal. The shipped `First Launch.command` is refused when '
        f'double-clicked, so there is no click-only path (#179).'
    )


@pytest.mark.parametrize('path', SHIPPED_INSTRUCTIONS, ids=lambda p: p.name)
def test_nothing_claims_a_no_terminal_path(
    path: Path, shipped: dict[Path, str]
) -> None:
    """`build_macos.sh:313` carried exactly this claim about the helper script.

    Judged per sentence and exempted by a denial, for the same reason the
    context-menu check is: both files now *say* that no no-Terminal path
    exists, in those words, and that sentence has to stay writable.
    """
    claims = _no_terminal_claims(shipped[path])
    assert claims == [], (
        f'{path.name} claims a no-Terminal path. `First Launch.command` is '
        f'quarantined like the app and is refused when double-clicked, so no '
        f'such path exists (#179). Offending sentences: {claims}'
    )


@pytest.mark.parametrize('path', SHIPPED_INSTRUCTIONS, ids=lambda p: p.name)
def test_open_anyway_is_only_mentioned_as_untested(
    path: Path, shipped: dict[Path, str]
) -> None:
    """Nobody has measured "Open Anyway" working, on any host.

    It did not appear in System Settings on the one host where anyone looked
    (#179, 2026-09-25), and that host was MDM-managed and non-admin, so its
    absence is not evidence about an unmanaged Mac either. A file may say so;
    it may not offer it as a route.
    """
    text = shipped[path]
    if 'open anyway' not in text.lower():
        return
    lowered = text.lower()
    assert 'untested' in lowered or 'not appear' in lowered, (
        f'{path.name} mentions "Open Anyway" without saying it is untested. '
        f'Nobody has measured it working, and on a managed Mac it may not '
        f'appear at all (#179).'
    )


# --- negative controls -----------------------------------------------------
#
# A source check that matches nothing is indistinguishable from a passing one,
# so each of these pins a thing the scanner must still recognise.


def test_the_check_would_catch_the_original_instructions() -> None:
    """The two exact strings #179 was filed about.

    `build_macos.sh:350` and `docs/BUILD_MACOS.md:115` as they stood at
    `724ba5e`. If a reformat or a rename stops the scanner seeing these, the
    tests above silently stop protecting anything.
    """
    originals = (
        'echo "  Recipients unzip, then right-click \'First Launch.command\' -> Open"',
        'Alternatively, right-click the app and select "Open" from the context '
        'menu, then click "Open" in the dialog.',
    )
    for original in originals:
        assert _offending_sentences(original) == [original.strip()], (
            f'the scanner no longer recognises the original #179 instruction: '
            f'{original!r}'
        )


@pytest.mark.parametrize('spelling', [
    "right-click 'First Launch.command' -> Open",
    'Right click the app, then Open',
    'Control-click the app and choose Open',
    'Ctrl-click WIMI.app and select Open',
    'Use the context menu and pick Open',
    'secondary-click the bundle, then Open it',
])
def test_the_check_catches_each_spelling_of_the_gesture(spelling: str) -> None:
    """One per way somebody could rewrite it. Apple's own documentation uses
    "Control-click", so that spelling is the likeliest reintroduction."""
    assert _offending_sentences(spelling), (
        f'the scanner did not recognise {spelling!r}'
    )


def test_a_refutation_elsewhere_is_not_a_licence() -> None:
    """The window is a sentence, not a paragraph, and this is why.

    A paragraph window would let one honest "that does not work" excuse an
    instruction three sentences later -- which is exactly the shape the fixed
    files have, since they explain the history beside the correct command.
    """
    paragraph = (
        'A Control-click Open from Finder raises the identical dialog. '
        'Right-click the app and select Open from the context menu.'
    )
    offenders = _offending_sentences(paragraph)
    assert offenders == [
        'Right-click the app and select Open from the context menu.'
    ], offenders


def test_the_check_would_catch_the_original_no_terminal_claim() -> None:
    """`build_macos.sh:313` as it stood at `724ba5e`.

    The comment was the only place the "without terminal" belief was written
    down, and it is why the closing message said what it said.
    """
    original = (
        '# Generate First Launch.command for recipients to bypass Gatekeeper '
        'without terminal'
    )
    assert _no_terminal_claims(original) == [original], _no_terminal_claims(original)


def test_a_denial_of_a_no_terminal_path_is_allowed() -> None:
    """The fixed files say this, and an earlier version of this file flagged it.

    "Cannot be handed to anyone without a Terminal step" is the *correct*
    statement built from the same words as the claim. A check that forbids the
    phrase outright pushes the next author into deleting the warning to get
    green, which is the opposite of what #179 is for.
    """
    assert _no_terminal_claims(
        'The macOS build cannot be handed to anyone without a Terminal step.'
    ) == []


def test_the_refutation_exemption_is_not_a_blanket() -> None:
    """A sentence using the gesture words without the instruction is fine.

    This is the other direction: the scanner must not demand a refutation
    from prose that never tells anyone to do anything, or the next author
    writing about Finder at all has to work around it.
    """
    assert _offending_sentences(
        'A right-click selects the bundle in Finder.'
    ) == []
