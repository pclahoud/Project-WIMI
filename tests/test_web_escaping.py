"""One escaping module, and an instrument that can see the class (#548).

#324, #525 and #546 were one defect found three times: a value a student typed
or imported reached ``innerHTML`` unescaped. They were found one page at a
time, by accident, because the obvious search -- ``grep innerHTML | grep '${'``
-- sees a tenth of the sinks: a template literal opens on the ``innerHTML =``
line and interpolates on the lines below, which is where #324's
``${chip.label}`` sat. ``tests/_web_sinks.py`` reads each sink whole.

This module holds:

* **the finder's own control** -- it must locate the two known sinks in the
  code as it stood before #517 and #533 fixed them. A discovery sweep whose
  reader silently stops matching reports a clean tree, and that is the
  failure mode of every sweep in this project;
* **the link check** for ``escape.js``, both directions, exactly as
  ``test_web_local_date.py`` does for ``LocalDate``.

The gate that bans local escaping helpers comes in stage 3 (#548), once
stage 2 has moved every page onto ``WimiEscape``: turning it on first would
fail on all of them and block the tree.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests._web_sinks import ROOT, first_party_js, sinks_in

WEB_HTML = ROOT / 'src' / 'web' / 'html'

#: #324's sink, verbatim from entry_browser.js before PR #517. The label is
#: interpolated two lines below the `innerHTML =`, which is the shape a
#: line-wise grep cannot see.
BEFORE_517 = '''        this.elements.filterChips.innerHTML = chips.map(chip => `
            <span class="filter-chip" data-testid="browser-filter-chip-${chip.type}">
                ${chip.label}
                <button type="button" class="remove-chip" data-type="${chip.type}" data-testid="browser-filter-chip-${chip.type}-remove" aria-label="Remove filter ${this.escapeAttr(chip.label)}">×</button>
            </span>
        `).join('');
'''

#: #525's sink, verbatim from subject_deep_dive.js before PR #533.
BEFORE_533 = '''            item.innerHTML = `
                <div class="recent-entry-date">${dateStr}</div>
                <div class="recent-entry-subject">${entry.subject_name}</div>
                <div class="recent-entry-note">${entry.reflection || entry.explanation || 'No notes'}</div>
            `;
'''


@pytest.mark.unit
@pytest.mark.parametrize('source, needle', [
    pytest.param(BEFORE_517, 'chip.label', id='324-entry-browser-chip'),
    pytest.param(BEFORE_533, 'entry.subject_name', id='525-deep-dive-recent'),
])
def test_the_finder_sees_the_known_sinks(source: str, needle: str) -> None:
    sinks = sinks_in(ROOT / 'probe.js', source)
    assert len(sinks) == 1, sinks
    assert needle in sinks[0].interpolations, (
        f'the finder read {sinks[0].interpolations} and missed {needle!r} -- '
        f'a sweep built on it would report this defect as clean')


@pytest.mark.unit
def test_a_line_wise_grep_would_have_missed_324() -> None:
    """Why the finder exists: the interpolation is not on the sink's line."""
    sink_line = next(l for l in BEFORE_517.splitlines() if 'innerHTML' in l)
    assert 'chip.label' not in sink_line


@pytest.mark.unit
def test_the_finder_ignores_comparisons_and_comments() -> None:
    source = ("if (el.innerHTML === '') {}\n"
              "// el.innerHTML = `${x}`;\n"
              "el.textContent = `${x}`;\n")
    assert sinks_in(ROOT / 'probe.js', source) == []


# --------------------------------------------------------------- the link


class _Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag == 'script' and dict(attrs).get('src'):
            self.sources.append(dict(attrs)['src'])

    handle_startendtag = handle_starttag


def _pages() -> list[Path]:
    return sorted(WEB_HTML.rglob('*.html'))


def _linked(page: Path) -> list[str]:
    parser = _Scripts()
    parser.feed(page.read_text(encoding='utf-8'))
    return parser.sources


#: Shared page modules whose global must be linked wherever it is used, and
#: only there. ``rich_html.js`` (#589) is the formatted-content counterpart of
#: ``escape.js``.
SHARED_MODULES = (('escape.js', 'WimiEscape'), ('rich_html.js', 'WimiRichHtml'))


@pytest.mark.unit
@pytest.mark.parametrize('module, symbol', SHARED_MODULES, ids=[m for m, _ in SHARED_MODULES])
@pytest.mark.parametrize('page', _pages(), ids=lambda p: p.name)
def test_a_page_whose_scripts_use_a_shared_module_links_it(
        page: Path, module: str, symbol: str) -> None:
    sources = _linked(page)
    js = {p.name: p for p in first_party_js()}
    uses = [s for s in sources if Path(s).name in js and Path(s).name != module
            and symbol in js[Path(s).name].read_text(encoding='utf-8')]
    inline = symbol in page.read_text(encoding='utf-8')
    linked = [s for s in sources if Path(s).name == module]
    if uses or inline:
        assert linked, (
            f'{page.name} uses {symbol} (via {uses or "an inline script"}) but '
            f'does not link {module}, so it is undefined on that page only')
        first_user = min(sources.index(s) for s in uses) if uses else len(sources)
        assert sources.index(linked[0]) < first_user, (
            f'{page.name} links {module} after a script that uses it')
    else:
        assert not linked, (
            f'{page.name} links {module} but nothing on the page uses it')


# --------------------------------------------------------------- the gate
#
# Stage 3 (#548). No first-party script, and no page's inline <script>, may
# DEFINE an escaping helper of its own. It bans the declaration, not the call:
# deciding whether a given interpolation is escaped means parsing template
# literals, and a parser that desynchronises fails OPEN -- this repo has the
# worked example. A declaration is a plain pattern and cannot. It is also the
# property that made the old state dangerous: 21 copies that disagreed, leaking
# between pages as globals, with which one ran decided by a <script> list.
# No allowlist. escape.js is the one definition and is the only file exempt.

from tests._web_sinks import ESCAPE_DEFINITION, escape_definitions  # noqa: E402


class _InlineScripts(HTMLParser):
    """The text of every inline <script> a page carries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self._in = False

    def handle_starttag(self, tag, attrs) -> None:
        a = dict(attrs)
        if tag == 'script' and not a.get('src') and a.get('type') in (None, '', 'text/javascript', 'module'):
            self._in = True
            self.blocks.append('')

    def handle_endtag(self, tag) -> None:
        if tag == 'script':
            self._in = False

    def handle_data(self, data) -> None:
        if self._in:
            self.blocks[-1] += data


@pytest.mark.unit
@pytest.mark.parametrize(
    'script', [p for p in first_party_js() if p.name != 'escape.js'],
    ids=lambda p: p.name)
def test_no_page_script_defines_its_own_escaping(script: Path) -> None:
    found = escape_definitions(script)
    assert not found, (
        f'{script.relative_to(ROOT)} defines {found}. Use WimiEscape.html / '
        f'WimiEscape.attr (escape.js), and link escape.js on the page -- or, '
        f'for a simple row, build it from text nodes. A local copy is how the '
        f'21 disagreeing helpers of #548 happened.')


@pytest.mark.unit
@pytest.mark.parametrize('page', _pages(), ids=lambda p: p.name)
def test_no_page_defines_its_own_escaping_inline(page: Path) -> None:
    parser = _InlineScripts()
    parser.feed(page.read_text(encoding='utf-8'))
    found = [d for block in parser.blocks for d in escape_definitions(page, block)]
    assert not found, (
        f'{page.name} defines {found} in an inline <script> -- the shape '
        f'error-viewer.html had until #548 stage 2. Use WimiEscape.')


@pytest.mark.unit
@pytest.mark.parametrize('source', [
    pytest.param("function escapeHtml(text) {\n  return text;\n}\n", id='function'),
    pytest.param("    _escapeHtml(text) {\n        return text;\n    },\n", id='method'),
    pytest.param("const escapeAttr = (t) => t;\n", id='arrow'),
    pytest.param("    escapeRelationHtml(value) {\n    }\n", id='renamed'),
])
def test_the_gate_fires_on_every_helper_shape_it_replaced(source: str) -> None:
    """Negative control: each shape the 21 helpers took is still detected."""
    assert ESCAPE_DEFINITION.search(source), source


@pytest.mark.unit
@pytest.mark.parametrize('source', [
    "el.innerHTML = WimiEscape.html(name);\n",
    "const safe = WimiEscape.attr(label);\n",
    "if (needsEscape(x)) {}\n",
    "    return escapeHtml(text);\n",
])
def test_the_gate_does_not_fire_on_calls(source: str) -> None:
    """A call is not a definition: the gate bans declarations only."""
    assert not ESCAPE_DEFINITION.search(source), source


@pytest.mark.unit
def test_the_inline_reader_sees_the_error_viewer_shape() -> None:
    """Control for the inline half: error-viewer.html's copy, as it was."""
    page = ('<html><body><script src="../js/a.js"></script><script>\n'
            '  class ErrorViewer {\n'
            '            escapeHtml(text) {\n'
            '                const div = document.createElement("div");\n'
            '                return div.innerHTML;\n'
            '            }\n'
            '  }\n</script></body></html>')
    parser = _InlineScripts()
    parser.feed(page)
    assert [d[1] for b in parser.blocks for d in escape_definitions(ROOT, b)] == ['escapeHtml']
