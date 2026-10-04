"""#301's caveat has one definition, reaches every page that uses it, and
cannot leave a page worse than it found it.

`_build_subject_path` filters archived ancestors (#301), so a path can be
shorter than the student remembers. The owner's decision was to explain that
rather than accept it, in a hover tooltip. `src/web/js/archived_ancestor_note.js`
is the one definition.

What is guarded statically, and why
-----------------------------------
The behaviour is pinned by a scenario
(`tests/wimi_test/scenarios/test_archived_ancestor_note.py`), which drives a
real archived parent through a real page. That test cannot see a *fourth*
surface appearing somewhere it does not look, and three of this feature's
failure modes are silent:

1. **The per-page `<script>` link.** `CLAUDE.md` records this gotcha for
   stylesheets; it is the same for scripts. Miss the link and
   `ArchivedAncestorNote` is `undefined` on that page only -- and because
   every caller guards on `typeof` (see 2), the page renders perfectly and
   the explanation is simply never there. No error anywhere.
2. **The `typeof` guard itself.** It is what makes 1 a missing explanation
   rather than a `ReferenceError` mid-render. A caller that drops it turns a
   forgotten script tag into a broken subject breadcrumb.
3. **The classes living in `styles.css`.** That is the one stylesheet every
   page links. In any other file the note renders as a bare letter `i` with
   browser defaults -- visible, meaningless, and passing every DOM assertion
   anybody would write.

And one decision is enforced by the presence of a selector: the tooltip opens
on `:focus` as well as `:hover`. `title=` was rejected for this precisely
because it never appears on keyboard focus, so a hover-only reimplementation
would be the rejected option wearing the accepted option's class names.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / 'src' / 'web'
WEB_JS = WEB / 'js'
WEB_HTML = WEB / 'html'
WEB_CSS = WEB / 'css'

HELPER = WEB_JS / 'archived_ancestor_note.js'
HELPER_SRC_SUFFIX = '/archived_ancestor_note.js'
GLOBAL = 'ArchivedAncestorNote'

#: Vendored libraries are not ours to police.
VENDORED = ('lib',)

#: The two classes the helper emits. Both must be defined in `styles.css`.
EMITTED_CLASSES = ('archived-ancestors-note', 'archived-ancestors-tooltip')


def _first_party_js() -> list[Path]:
    return sorted(
        p for p in WEB_JS.rglob('*.js')
        if not any(part in VENDORED for part in p.relative_to(WEB_JS).parts)
    )


class _ScriptSources(HTMLParser):
    """The `src` of every <script> a page links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag != 'script':
            return
        src = dict(attrs).get('src')
        if src:
            self.sources.append(src)

    handle_startendtag = handle_starttag


def _linked_scripts(page: Path) -> list[str]:
    parser = _ScriptSources()
    parser.feed(page.read_text(encoding='utf-8'))
    return parser.sources


def _linked_first_party_scripts(page: Path) -> list[Path]:
    out = []
    for src in _linked_scripts(page):
        if src.startswith('qrc:'):
            continue
        candidate = (page.parent / src).resolve()
        if candidate.is_file() and WEB_JS in candidate.parents:
            out.append(candidate)
    return out


@pytest.mark.unit
def test_the_helper_is_the_only_definition() -> None:
    """One statement of the sentence, so two cannot drift apart.

    The wording names the Archived subjects panel as the way to undo
    (#37/#252); a second copy is how one of them stops saying that.
    """
    definers = [
        p.relative_to(REPO).as_posix() for p in _first_party_js()
        if f'window.{GLOBAL}' in p.read_text(encoding='utf-8')
    ]
    assert definers == ['src/web/js/archived_ancestor_note.js'], (
        f'window.{GLOBAL} is defined in {definers}.'
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    'page', sorted(WEB_HTML.rglob('*.html')), ids=lambda p: p.name,
)
def test_the_script_link_matches_the_use_in_both_directions(
    page: Path,
) -> None:
    """A page that calls it links it, and a page that links it calls it.

    Both directions, because each failure is silent in its own way: without
    the link the explanation never appears (the `typeof` guard swallows it),
    and with an unused link the page carries dead weight that reads as
    though the feature were present there.

    Only directly-linked scripts are examined. `api/_loader.js` pulls its
    modules in at runtime, so a call added down there would not be seen --
    said rather than left to be found, and no api module uses it today.
    """
    linked_srcs = _linked_scripts(page)
    links_helper = any(
        src.endswith(HELPER_SRC_SUFFIX) for src in linked_srcs)

    users = [
        script.relative_to(REPO).as_posix()
        for script in _linked_first_party_scripts(page)
        if script != HELPER and GLOBAL in script.read_text(encoding='utf-8')
    ]

    if users:
        assert links_helper, (
            f'{page.relative_to(REPO)} links {users}, which call {GLOBAL}, '
            f'but does not link archived_ancestor_note.js. Every caller '
            f'guards on `typeof`, so the page will render fine and simply '
            f'never explain a shortened path (#301).'
        )
    else:
        assert not links_helper, (
            f'{page.relative_to(REPO)} links archived_ancestor_note.js but '
            f'none of its scripts use {GLOBAL}. Remove the link, or the '
            f'page reads as though it explained shortened paths.'
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    'script',
    [p for p in _first_party_js()
     if p != HELPER and GLOBAL in p.read_text(encoding='utf-8')],
    ids=lambda p: p.name,
)
def test_every_caller_guards_on_typeof(script: Path) -> None:
    """The guard is what makes a forgotten script tag cost the explanation
    and not the page.

    #127's measurement is the precedent: with the page-gate helper deleted
    entirely the entry form still released and was typeable -- it degraded
    to silence, never to a dead page. Same property, same reason.
    """
    text = script.read_text(encoding='utf-8')
    uses = len(re.findall(rf'\b{GLOBAL}\s*\.', text))
    guards = len(re.findall(
        rf"typeof\s+{GLOBAL}\s*!==\s*['\"]undefined['\"]", text))
    assert guards >= 1, (
        f'{script.relative_to(REPO)} calls {GLOBAL} {uses} time(s) with no '
        f'`typeof {GLOBAL} !== "undefined"` guard. A page missing the '
        f'<script> tag would then throw mid-render and lose the breadcrumb '
        f'itself, which is worse than the unexplained path #301 set out to '
        f'fix.'
    )


@pytest.mark.unit
@pytest.mark.parametrize('css_class', EMITTED_CLASSES)
def test_the_classes_are_defined_in_the_stylesheet_every_page_links(
    css_class: str,
) -> None:
    """The per-page CSS link gotcha, enforced rather than remembered.

    `styles.css` is the one sheet every page links. Anywhere else and the
    note renders as a bare `i` with browser defaults on the pages that did
    not link that file -- which is visible, meaningless, and passes every
    DOM-presence assertion.
    """
    selector = re.compile(rf'\.{re.escape(css_class)}\b')
    defining = sorted(
        p.name for p in WEB_CSS.glob('*.css')
        if selector.search(p.read_text(encoding='utf-8'))
    )
    assert defining == ['styles.css'], (
        f'.{css_class} is defined in {defining}. It must be in styles.css '
        f'and nowhere else.'
    )


@pytest.mark.unit
def test_the_tooltip_opens_on_keyboard_focus_too() -> None:
    """The reason `title=` was rejected, kept true.

    A hover-only reimplementation would be the rejected mechanism wearing
    the accepted one's class names -- and it would look correct in every
    screenshot. The `:focus-visible` ring is checked alongside because
    `:focus { outline: none }` above it is what made three of #304's
    invisible focus stops.
    """
    css = (WEB_CSS / 'styles.css').read_text(encoding='utf-8')
    assert '.archived-ancestors-note:hover .archived-ancestors-tooltip' in css
    assert '.archived-ancestors-note:focus .archived-ancestors-tooltip' in css, (
        'the tooltip does not open on keyboard focus, which is exactly the '
        'failure `title=` was rejected for (#301)'
    )
    assert '.archived-ancestors-note:focus-visible' in css, (
        'the host carries tabindex="0" and `:focus { outline: none }`, so '
        'without this rule Tab lands on it and nothing is drawn (#304)'
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    'names, expected_fragment',
    [
        ([], ''),
        (['Parent'], '"Parent" is archived'),
        (['A', 'B'], '"A" and "B" are archived'),
        (['A', 'B', 'C'], '"A", "B" and "C" are archived'),
    ],
    ids=['none', 'one', 'two', 'three'],
)
def test_the_sentence_is_documented_for_every_arity(
    names, expected_fragment,
) -> None:
    """A source check that the three joining branches exist and the empty
    case returns nothing.

    This is deliberately a weak static mirror of
    `ArchivedAncestorNote.sentence`; the strong form runs the real function
    in the real page, in the scenario. Kept here because the empty case is
    the whole of "only where a path was actually shortened", and a
    scenario covering one arity would not notice a plural branch that
    renders `"A"and"B"`.
    """
    text = HELPER.read_text(encoding='utf-8')
    if not names:
        assert "if (list.length === 0) return '';" in text, (
            'the empty case must return nothing, or the note appears with '
            'no names in it and the affordance stops meaning anything'
        )
        return
    # The joining branches, by arity.
    assert 'quoted.length === 1' in text
    assert 'quoted.length === 2' in text
    assert "' and '" in text
    assert "'is archived'" in text and "'are archived'" in text
    assert 'Archived subjects' in text, (
        'the sentence must name where to undo -- #37 landed, and a warning '
        'that denies an existing way forward is worse than none (#252)'
    )
