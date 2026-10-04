"""Every page that ships `inert` must also ship a voice, outside the gate (#127).

Why this is a markup test and not a scenario
--------------------------------------------
#114's gate works by shipping a page container with the `inert` attribute.
`inert` refuses pointer and keyboard input, which is the point, and it also
removes the whole subtree from the **accessibility tree**, which is #127:
measured on the entry form through CDP's ``Accessibility.getFullAXTree``, while
the gate is up the tree holds **one** non-ignored node -- the document root --
out of 72, against 290 of 461 once the gate lifts.

The fix is a ``[data-page-gate]`` status element that is *not* inside the gated
container. Putting it inside is the one way to get this wrong that produces no
symptom whatsoever:

* the element is in the DOM, so ``querySelector`` finds it;
* its text is right, so ``textContent`` reads correctly;
* ``getBoundingClientRect`` is non-zero, so it is laid out;
* ``role`` and ``aria-live`` are present, so an attribute check passes.

It is simply never announced and never read, and nothing anywhere says so. A
scenario built from DOM reads would pass against it, exactly as #114's own
tests would have passed against an ungated page had they been built from
``el.value = 'x'``. So the check is on the markup, where the mistake lives.

This matters now rather than later because **#119 (settings), #120 (session
setup), #121 (tree editor) and #122 (entry browser) are the same #114 defect on
four more pages** and are queued to be fixed by copying the entry form. This
test is what makes copying it wrong fail loudly. It is deliberately
self-counting: it discovers gated pages rather than listing them, so a fifth
page gets checked the day it is written and nobody has to remember to add it
here.

What a page-level gate is
-------------------------
A direct child of ``<body>`` carrying ``inert``. That boundary is doing real
work: ``inert`` is also legitimately used on small widgets deep inside a page
(a button that is not yet armed), and those have no business carrying a
document-level status region. A gate that covers the page is at the top of the
page.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

WEB_HTML = Path(__file__).resolve().parents[1] / "src" / "web" / "html"

# Void elements never have children, so the parser must not push them.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class _Element:
    __slots__ = ("tag", "attrs", "children", "parent", "line", "text")

    def __init__(self, tag: str, attrs: dict, parent, line: int) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Element] = []
        self.parent = parent
        self.line = line
        self.text: list[str] = []

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def has_ancestor(self, other: _Element) -> bool:
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False

    def inner_text(self) -> str:
        return " ".join(
            part for node in self.walk() for part in node.text
        ).strip()


class _TreeBuilder(HTMLParser):
    """A minimal ancestry-aware HTML parser.

    It only needs to be right about nesting, attributes and character data,
    which ``html.parser`` gives for well-formed markup. The project's pages are
    hand-written and well-formed; an unclosed tag shows up here as a wrong
    ancestor and fails loudly rather than silently, which is the right
    direction for a check whose whole purpose is catching a silent mistake.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("#document", {}, None, 0)
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Element(tag, dict(attrs), self._stack[-1], self.getpos()[0])
        self._stack[-1].children.append(node)
        if tag not in VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = _Element(tag, dict(attrs), self._stack[-1], self.getpos()[0])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        stripped = data.strip()
        if stripped:
            self._stack[-1].text.append(stripped)


def _parse_source(source: str) -> _Element:
    builder = _TreeBuilder()
    builder.feed(source)
    return builder.root


def _parse(path: Path) -> _Element:
    return _parse_source(path.read_text(encoding="utf-8"))


def _body(root: _Element) -> _Element | None:
    for node in root.walk():
        if node.tag == "body":
            return node
    return None


def _gated_containers(root: _Element) -> list[_Element]:
    """Direct children of <body> that ship `inert` -- see the module docstring."""
    body = _body(root)
    if body is None:
        return []
    return [c for c in body.children if "inert" in c.attrs]


def _gate_voices(root: _Element) -> list[_Element]:
    return [n for n in root.walk() if "data-page-gate" in n.attrs]


def _html_pages() -> list[Path]:
    pages = sorted(WEB_HTML.rglob("*.html"))
    assert pages, f"no HTML pages found under {WEB_HTML}"
    return pages


def _describe(path: Path, node: _Element) -> str:
    return f"{path.name}:{node.line} <{node.tag} class={node.attrs.get('class')!r}>"


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _html_pages(), ids=lambda p: p.name)
def test_a_gated_page_has_a_voice(path: Path) -> None:
    """A page-level `inert` container implies a `[data-page-gate]` element."""
    root = _parse(path)
    gated = _gated_containers(root)
    if not gated:
        pytest.skip(f"{path.name} has no page-level gate")

    voices = _gate_voices(root)
    assert voices, (
        f"{path.name} ships a page-level `inert` container "
        f"({', '.join(_describe(path, g) for g in gated)}) but has no "
        f"[data-page-gate] element. `inert` removes that subtree from the "
        f"accessibility tree, so the page is not merely refusing input -- it "
        f"reads as an empty document to a screen reader and announces nothing "
        f"when that stops being true (#127). Add the one-line status element "
        f"from docs/guides/PAGE_GATE.md."
    )


@pytest.mark.parametrize("path", _html_pages(), ids=lambda p: p.name)
def test_the_voice_is_not_inside_the_gate(path: Path) -> None:
    """The mistake with no symptom: a status region inside the inert subtree."""
    root = _parse(path)
    gated = _gated_containers(root)
    if not gated:
        pytest.skip(f"{path.name} has no page-level gate")

    for voice in _gate_voices(root):
        for container in gated:
            assert not voice.has_ancestor(container), (
                f"{_describe(path, voice)} carries [data-page-gate] but sits "
                f"INSIDE {_describe(path, container)}, which ships `inert`. "
                f"`inert` removes its whole subtree from the accessibility "
                f"tree, so this status region is exactly as unannounced as "
                f"the page it was added to describe -- and every DOM-level "
                f"check of it still passes (#127). Move it out, to a sibling "
                f"of the gated container."
            )


@pytest.mark.parametrize("path", _html_pages(), ids=lambda p: p.name)
def test_the_voice_can_actually_speak(path: Path) -> None:
    """A bare <div> announces nothing, however good its text is."""
    root = _parse(path)
    if not _gate_voices(root):
        pytest.skip(f"{path.name} has no page gate")

    for voice in _gate_voices(root):
        role = voice.attrs.get("role")
        live = voice.attrs.get("aria-live")
        assert role == "status" or live in {"polite", "assertive"}, (
            f"{_describe(path, voice)} carries [data-page-gate] but is not a "
            f"live region (role={role!r}, aria-live={live!r}). Changing the "
            f"text of an ordinary element announces nothing, so the handover "
            f"would be as silent as before (#127)."
        )


@pytest.mark.parametrize("path", _html_pages(), ids=lambda p: p.name)
def test_the_holding_message_ships_in_the_markup(path: Path) -> None:
    """No window may exist in which the page is gated and silent.

    The `inert` attribute is in the markup rather than set from script for
    exactly this reason (#114); the message that explains it has to arrive on
    the same terms, or the first frames of a slow load are silent again.
    """
    root = _parse(path)
    if not _gate_voices(root):
        pytest.skip(f"{path.name} has no page gate")

    for voice in _gate_voices(root):
        assert voice.inner_text(), (
            f"{_describe(path, voice)} is an empty [data-page-gate] element. "
            f"The holding message belongs in the markup, like the `inert` "
            f"attribute it explains -- a message installed by script leaves "
            f"the start of every slow load gated and silent (#127)."
        )


@pytest.mark.parametrize("path", _html_pages(), ids=lambda p: p.name)
def test_the_parser_can_see_the_page_at_all(path: Path) -> None:
    """The guard that stops a parse failure reading as a clean page.

    Four of the checks here skip a page with no page-level gate, and "no
    page-level gate" is what a *failed parse* also looks like: if ``<body>``
    is not found, ``_gated_containers`` returns an empty list and the page
    goes green by skipping. That is not hypothetical -- ``tree_editor.html``
    embeds a whole markdown document, and the pages that #119-#122 will gate
    are among the largest in the tree.

    Measured when this was written: all twelve pages parse, each with its
    page container as a direct child of ``<body>`` --
    ``settings.html``/``entry_browser.html`` ``div.app-container``,
    ``session_setup.html`` ``div.session-page``, ``tree_editor.html``
    ``div.tree-page`` -- so the ``<body>``-child rule reaches every page the
    four queued issues target.
    """
    root = _parse(path)
    body = _body(root)
    assert body is not None, (
        f"the parser found no <body> in {path.name}, so every gate check in "
        f"this file skips it silently. Fix the parser or the markup; do not "
        f"let this page pass by being unreadable")
    assert body.children, (
        f"{path.name}'s <body> parsed with no children, which no page in this "
        f"tree has. The checks here would all skip it")


def test_the_entry_form_is_actually_covered() -> None:
    """The suite above skips a page with no gate; make sure one is not skipping.

    Four of these tests are parametrised over every page and skip the ones
    without a gate, so if `question_entry.html` ever stopped being recognised
    the whole file would go green by skipping. This is the test that cannot.
    """
    root = _parse(WEB_HTML / "question_entry.html")
    gated = _gated_containers(root)
    voices = _gate_voices(root)
    assert len(gated) == 1, (
        f"expected exactly one page-level gate on the entry form, found "
        f"{len(gated)} -- #114's `inert` attribute on .entry-page is the one")
    assert len(voices) == 1, (
        f"expected exactly one [data-page-gate] voice on the entry form, "
        f"found {len(voices)}")
    assert "data-page-gated" in gated[0].attrs, (
        "the gated container has lost its data-page-gated marker")
    assert not voices[0].has_ancestor(gated[0])


def test_the_checks_would_catch_the_mistake(tmp_path: Path) -> None:
    """Negative control.

    Three ways to get the pattern wrong, each built here and each asserted to
    be caught, plus a correct page asserted to pass. Without this, a checker
    that found nothing because its parsing was broken would look exactly like
    a clean tree -- which is how the original defect survived #114's whole
    test suite.
    """
    # 1. The voice nested inside the gate: no symptom anywhere else.
    root = _parse_source(
        "<html><body>\n"
        '  <div class="entry-page" inert>\n'
        '    <div data-page-gate role="status">Preparing&hellip;</div>\n'
        "  </div>\n"
        "</body></html>"
    )
    gated, voices = _gated_containers(root), _gate_voices(root)
    assert len(gated) == 1, "the control's gated container was not recognised"
    assert len(voices) == 1, "the control's gate element was not recognised"
    assert voices[0].has_ancestor(gated[0]), (
        "the ancestry check cannot see a gate element nested inside the inert "
        "container, so test_the_voice_is_not_inside_the_gate proves nothing")

    # 2. A gated page with no voice at all -- plain #127.
    root = _parse_source(
        '<html><body>\n  <div class="entry-page" inert><p>hi</p></div>\n'
        "</body></html>"
    )
    assert _gated_containers(root), "a gated page with no voice was not detected"
    assert not _gate_voices(root)

    # 3. A voice that cannot speak, and one with nothing to say.
    root = _parse_source(
        "<html><body>\n"
        "  <div data-page-gate>Preparing&hellip;</div>\n"
        '  <div data-page-gate-empty data-page-gate role="status"></div>\n'
        '  <div class="entry-page" inert><p>hi</p></div>\n'
        "</body></html>"
    )
    voices = _gate_voices(root)
    assert len(voices) == 2
    assert voices[0].attrs.get("role") != "status"
    assert voices[0].attrs.get("aria-live") is None, (
        "the live-region check would pass this one, so it proves nothing")
    assert voices[1].inner_text() == "", (
        "inner_text() does not see an empty element as empty, so "
        "test_the_holding_message_ships_in_the_markup proves nothing")

    # 4. Positive control: a correct page must trip nothing, or the checks are
    #    simply failing on everything.
    root = _parse_source(
        "<html><body>\n"
        '  <div data-page-gate role="status" aria-live="polite">Preparing&hellip;</div>\n'
        '  <div class="entry-page" inert data-page-gated><p>hi</p></div>\n'
        "</body></html>"
    )
    gated, voices = _gated_containers(root), _gate_voices(root)
    assert gated and voices
    assert not voices[0].has_ancestor(gated[0])
    assert voices[0].attrs.get("role") == "status"
    assert voices[0].inner_text()


def test_a_widget_level_inert_is_not_mistaken_for_a_page_gate() -> None:
    """The <body>-child boundary, which is what keeps this check precise.

    `inert` on a small control deep inside a page (a microphone button that is
    not armed yet) is legitimate and needs no document-level status region.
    Flagging those would make the check noise, and noise is how a check stops
    being read.
    """
    root = _parse_source(
        "<html><body>\n"
        '  <div class="page">\n'
        '    <form><button inert>Dictate</button></form>\n'
        "  </div>\n"
        "</body></html>"
    )
    assert _gated_containers(root) == [], (
        "an `inert` button nested inside the page was treated as a page-level "
        "gate; this check would then demand a status region on every page that "
        "disables a control")
