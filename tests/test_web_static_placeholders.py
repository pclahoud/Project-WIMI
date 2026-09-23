"""The detail page must not ship placeholder text that reads like real data.

Issue #83. ``entry_detail.html`` was authored from a design mockup and kept the
mockup's sample values in the markup: the difficulty badge said ``Hard``, the
source said ``UWorld Block 5``, the date said ``Dec 27, 2025``. JavaScript
replaces all of them on render, so nobody noticed -- but a *plausible* value
sitting in the document before the render is not harmless:

* Two regression scenarios wait for the badge with ``textContent.trim() != ''``
  and then read it. The literal ``Hard`` satisfies "non-empty" the instant the
  new document commits, so the guard passed on an unrendered page and the test
  read the placeholder. The tell was that the wrong value was *always* ``Hard``.
* Worse, the residue can be permanent rather than a race. ``renderDifficultyBadge``
  early-returns for an entry with no rating and only sets ``display: none`` -- it
  never clears the text. An unrated entry therefore kept ``Hard`` in its DOM for
  the life of the page. The same shape applies to the four meta fields and the
  navigation position indicator, each of which hides its node without clearing
  it when the datum is absent.

The invariant below is what makes both failure modes impossible: a node that
JavaScript populates ships **no readable value**. Emoji chrome (the meta-row
icons) is allowed through because JS only writes the sibling ``.meta-text``.

Keep this test cheap and static -- it parses the shipped asset, spawns nothing,
and is the reason a future mockup paste fails in seconds instead of surfacing as
an intermittent scenario failure weeks later.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

WEB_HTML = Path(__file__).resolve().parents[1] / 'src' / 'web' / 'html'

VOID_ELEMENTS = {'img', 'br', 'input', 'hr', 'meta', 'link', 'source', 'area'}

# Every node in entry_detail.html that entry_detail.js writes into. Each must
# ship without a readable value. `attachment-count` is deliberately absent: it
# ships `0`, which is a true zero-state rather than a stand-in for unknown data.
ENTRY_DETAIL_POPULATED_IDS = [
    'difficulty-badge',
    'position-indicator',
    'source-name',
    'entry-date',
    'question-id',
    'time-spent',
    'user-answer',
    'correct-answer',
    'reflection-content',
    'explanation-content',
    'subject-path',
    'tags-container',
]

# The entry form shipped `Entry 1 of 0` in its header counter -- a fabricated
# (and self-contradictory) count, visible at first paint, that
# `renderEntryNavigation` overwrites with the real `Entry N of M`. Found by the
# #83 sweep. Its own scenario, test_session_progress_overflow, gates on the
# pager dots rather than this text, so emptying it costs that guard nothing.
QUESTION_ENTRY_POPULATED_IDS = [
    'entry-counter',
]

_READABLE = re.compile(r'[A-Za-z0-9]')


class _TextOfElement(HTMLParser):
    """Collect the served text of elements carrying one of `wanted` ids."""

    def __init__(self, wanted: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self._wanted = wanted
        self._stack: list[tuple[str, str | None]] = []
        self._open: list[str] = []
        self.text: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_ELEMENTS:
            return
        element_id = dict(attrs).get('id')
        self._stack.append((tag, element_id))
        if element_id in self._wanted:
            self._open.append(element_id)
            self.text.setdefault(element_id, [])

    def handle_endtag(self, tag: str) -> None:
        while self._stack:
            open_tag, element_id = self._stack.pop()
            if element_id in self._wanted and self._open and self._open[-1] == element_id:
                self._open.pop()
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        for element_id in self._open:
            self.text[element_id].append(data)


class _ClassOfElement(HTMLParser):
    """Collect the served class list of elements carrying one of `wanted` ids."""

    def __init__(self, wanted: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self._wanted = wanted
        self.classes: dict[str, set[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get('id')
        if element_id in self._wanted:
            self.classes[element_id] = set((attributes.get('class') or '').split())

    # A void element can still carry an id and a class, so unlike the text
    # parser this one has no reason to skip them.
    handle_startendtag = handle_starttag


def _served_text(page: str, wanted: list[str]) -> dict[str, str]:
    """The textContent of each wanted id as the document is served."""
    parser = _TextOfElement(set(wanted))
    parser.feed((WEB_HTML / page).read_text(encoding='utf-8'))
    missing = [i for i in wanted if i not in parser.text]
    assert not missing, f'{page} no longer contains: {missing}'
    return {i: ' '.join(''.join(chunks).split()) for i, chunks in parser.text.items()}


def _served_classes(page: str, wanted: list[str]) -> dict[str, set[str]]:
    """The class list of each wanted id as the document is served.

    Some of the claims below are made in a class rather than in text -- a
    status dot has no text at all, it is painted entirely by `.running` /
    `.stopped` / `.error`. A guard that only read textContent would miss them.
    """
    parser = _ClassOfElement(set(wanted))
    parser.feed((WEB_HTML / page).read_text(encoding='utf-8'))
    missing = [i for i in wanted if i not in parser.classes]
    assert not missing, f'{page} no longer contains: {missing}'
    return parser.classes


@pytest.mark.unit
@pytest.mark.parametrize('element_id', ENTRY_DETAIL_POPULATED_IDS)
def test_entry_detail_ships_no_readable_placeholder(element_id: str) -> None:
    """A JS-populated node on the detail page ships no value a reader could trust."""
    text = _served_text('entry_detail.html', ENTRY_DETAIL_POPULATED_IDS)[element_id]
    assert not _READABLE.search(text), (
        f"entry_detail.html ships #{element_id} carrying {text!r}. A node that "
        f'JavaScript populates must start with no readable value: anything that '
        f'reads the DOM before the render -- a test waiting on '
        f'textContent.trim() != \'\', or a user on an entry where this datum is '
        f'absent and the node is merely hidden -- would take it for real data. '
        f'See issue #83.'
    )


@pytest.mark.unit
@pytest.mark.parametrize('element_id', QUESTION_ENTRY_POPULATED_IDS)
def test_question_entry_ships_no_readable_placeholder(element_id: str) -> None:
    """The entry form's header counter ships no invented count."""
    text = _served_text('question_entry.html', QUESTION_ENTRY_POPULATED_IDS)[element_id]
    assert not _READABLE.search(text), (
        f"question_entry.html ships #{element_id} carrying {text!r}. The header "
        f'counter is rendered from the real slot count; shipping a number here '
        f'states a total the form has not counted yet. See issue #83.'
    )


@pytest.mark.unit
def test_difficulty_badge_is_empty() -> None:
    """The reported instance, named so a regression says what broke.

    The badge is what two regression scenarios read back to check the word the
    entry form offered is the word the detail page shows. A placeholder here
    makes both of them assert against static markup.
    """
    text = _served_text('entry_detail.html', ['difficulty-badge'])['difficulty-badge']
    assert text == '', (
        f'The difficulty badge ships {text!r} instead of empty. This is issue '
        f'#83 exactly: the scenarios wait for a non-empty badge, so a word here '
        f'lets them read the placeholder as if it were the rendered difficulty.'
    )


# ---------------------------------------------------------------------------
# Issue #89 -- tree_editor.html
# ---------------------------------------------------------------------------

# The toolbar weight badge and the dimension badge each ship a *real possible
# value* of the thing they describe, so the document asserts a fact before
# anything has looked it up:
#
# * `weight-config-badge` says `User Defined`. It is the one node here that is
#   visible at first paint -- nothing from it up to `.tree-page` carries
#   `hidden` or `display: none`. `updateWeightConfigBadge` awaits
#   `api.getWeightConfig` and then writes either `Official (N)` / the source
#   name or `User Defined`. So an exam whose weights *were* imported from an
#   official outline -- the case the import format exists for -- spends the
#   round trip telling the student their official weights are hand-entered.
# * `dimension-info-badge` says `Required`. `updateDimensionInfo` writes
#   `Required`, `Multi-select`, the two joined, or `Optional` -- and `Optional`
#   is the fallback branch, so the shipped word is not even the JS-side
#   default. For a non-required first dimension the DOM states the opposite of
#   the truth for the duration of the awaits in `initializeTreeEditor`.
#
# Deliberately NOT listed, and the distinction is the whole point: the siblings
# `dimension-info-name` (`Dimension Name`), `empty-dimension-name`
# (`Dimension`) and `dimension-info-description` (`Dimension description will
# appear here`) read as literal field-name filler, not as data. No dimension is
# called `Dimension Name`, so no reader can mistake it for one. #83's precedent
# was to leave honest filler alone.
TREE_EDITOR_POPULATED_IDS = [
    'weight-config-badge',
    'dimension-info-badge',
]


@pytest.mark.unit
@pytest.mark.parametrize('element_id', TREE_EDITOR_POPULATED_IDS)
def test_tree_editor_ships_no_readable_placeholder(element_id: str) -> None:
    """A badge on the tree editor ships no weight source or requirement."""
    text = _served_text('tree_editor.html', TREE_EDITOR_POPULATED_IDS)[element_id]
    assert not _READABLE.search(text), (
        f'tree_editor.html ships #{element_id} carrying {text!r}. Both badges '
        f'state a fact the page has not read yet -- the weight badge before '
        f'`getWeightConfig` resolves, the dimension badge before a dimension '
        f'is chosen -- and each ships a value its own JavaScript really '
        f'writes, so a reader cannot tell the placeholder from a result. See '
        f'issue #89.'
    )


@pytest.mark.unit
def test_tree_weight_badge_ships_no_icon_either() -> None:
    """The gear is an assertion too, and the readable-character guard misses it.

    `updateWeightConfigBadge` writes the icon as well as the text: it sets
    a clipboard glyph for official weights and a gear for user-defined ones.
    Emptying only `.badge-text` would leave the badge painting the gear, which
    says the same wrong thing in a glyph that ``[A-Za-z0-9]`` does not match.
    """
    text = _served_text('tree_editor.html', ['weight-config-badge'])['weight-config-badge']
    assert text == '', (
        f'#weight-config-badge ships {text!r} instead of nothing at all. Its '
        f'icon span carries a weight-source claim exactly as its text span '
        f'does, so both must ship empty. See issue #89.'
    )


@pytest.mark.unit
def test_tree_weight_badge_ships_hidden() -> None:
    """The badge must not paint an empty pill while the answer is in flight.

    Unlike every other node in this module, this one is visible at first paint,
    so emptying it alone would trade a wrong claim for a blank grey chip in the
    toolbar. The page's own idiom is to ship `hidden` and have JavaScript
    remove it once there is something true to show (`dimension-info`,
    `tree-search-count`, `tree-search-clear` all do this), and
    `updateWeightConfigBadge` now follows it. A failure here means the badge
    would render before `getWeightConfig` resolved -- or, if JS stopped
    removing the class, never render at all.
    """
    classes = _served_classes('tree_editor.html', ['weight-config-badge'])['weight-config-badge']
    assert 'hidden' in classes, (
        f'#weight-config-badge ships classes {sorted(classes)!r} without '
        f'`hidden`. It is the only JS-populated node on these pages that is '
        f'visible at first paint, so it must ship hidden and be revealed by '
        f'`updateWeightConfigBadge`. See issue #89.'
    )


# ---------------------------------------------------------------------------
# Issue #90 -- settings.html
# ---------------------------------------------------------------------------

# The MCP status row is the one case in this module where the fix is NOT to
# empty the node. A status indicator with no status is not more honest than a
# wrong one -- it is a blank dot and a blank line where the page has promised
# the reader a state. So settings.html ships a real fourth state, `unknown` /
# `Checking...`, which says the true thing: the page has not asked yet.
#
# The invariant is therefore narrower and stated directly: the markup must not
# ship any of the three *determined* states. `_updateMcpStatusUI` writes
# exactly `Running on port N`, `Error: ...` and `Stopped`, painting the dot
# `.running`, `.error` and `.stopped` respectively. Shipping `Stopped` with a
# `.stopped` dot -- what the page did before #90 -- states the server is not
# running before `refreshMcpStatus` has awaited `api.getMcpServerStatus()`,
# and an MCP server left running from a previous session makes that the
# opposite of the truth.
MCP_DETERMINED_STATE_CLASSES = {'running', 'stopped', 'error'}

# Substrings of the three strings `_updateMcpStatusUI` can write. `Stopped` is
# the whole string; the other two are prefixes of one built with a port or an
# error message.
MCP_DETERMINED_STATE_TEXTS = ['Running on port', 'Error:', 'Stopped']


@pytest.mark.unit
def test_mcp_status_dot_ships_no_determined_state() -> None:
    """The dot carries its whole meaning in a class, so the class is the claim."""
    classes = _served_classes('settings.html', ['mcpStatusDot'])['mcpStatusDot']
    asserted = classes & MCP_DETERMINED_STATE_CLASSES
    assert not asserted, (
        f'settings.html ships #mcpStatusDot with {sorted(asserted)!r}. '
        f'`.mcp-status-dot` sets only size and shape, so the state class is '
        f'the entire visible claim; shipping one states a server state before '
        f'`refreshMcpStatus` has asked for it. Use `.unknown`. See issue #90.'
    )


@pytest.mark.unit
def test_mcp_status_text_ships_no_determined_state() -> None:
    """...and the text beside it must not assert one either."""
    text = _served_text('settings.html', ['mcpStatusText'])['mcpStatusText']
    asserted = [s for s in MCP_DETERMINED_STATE_TEXTS if s in text]
    assert not asserted, (
        f'settings.html ships #mcpStatusText carrying {text!r}, which contains '
        f'{asserted!r} -- one of the three states `_updateMcpStatusUI` writes. '
        f'That is an assertion about a server nothing has queried yet. A '
        f'neutral fourth state is what belongs here. See issue #90.'
    )


@pytest.mark.unit
def test_mcp_status_ships_the_unknown_state() -> None:
    """The neutral state is positively required, not merely allowed.

    Emptying the text alone would leave the dot painting `stopped` grey, and
    dropping the class alone would leave it transparent -- `.mcp-status-dot`
    sets no colour of its own. Both halves have to ship the new state, so both
    are asserted here rather than left to the two negative guards above.
    """
    classes = _served_classes('settings.html', ['mcpStatusDot'])['mcpStatusDot']
    text = _served_text('settings.html', ['mcpStatusText'])['mcpStatusText']
    assert 'unknown' in classes, (
        f'#mcpStatusDot ships {sorted(classes)!r} without `unknown`, so it '
        f'paints no colour at all until JavaScript resolves. See issue #90.'
    )
    assert _READABLE.search(text), (
        f'#mcpStatusText ships {text!r}. Unlike every other node in this '
        f'module this one must NOT be empty: a status row with no status is a '
        f'blank line where the page promised a state. See issue #90.'
    )
