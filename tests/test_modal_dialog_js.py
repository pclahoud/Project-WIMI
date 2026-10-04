"""The modal pattern reaches the modals JavaScript builds too (#319).

Why this file exists at all
---------------------------
``tests/test_modal_dialog_markup.py`` reads ``src/web/html`` and **13 of this
tree's 45 modal surfaces are not there**. They are built at runtime by
``goal_widget.js``, ``export_dialog.js``, ``image_browser.js``,
``rich_editor.js``, ``alias_manager.js``, ``subject_relations.js``,
``media_upload.js`` (four), ``import_export.js`` (two) and
``question_entry.js``. #319's own measurement was taken over the HTML pages, so
none of these were in its count of 25 -- and ``analytics_dashboard.html``,
``subject_deep_dive.html`` and ``entry_browser.html`` did not appear in its
table at all, although each of them opens a modal.

That is #317's lesson, which this repo has now learned twice: **a markup-only
sweep misses what JavaScript renders**, and two of #317's three heading
defects lived in exactly these files.

How a modal is found in a .js file
----------------------------------
Eleven of the thirteen are written as HTML in a template literal, so the whole
source is fed to the same tree builder the markup guard uses and the **same**
overlay/surface rule is applied to whatever markup comes out. The parser is
restricted to real HTML element names, so a JavaScript ``i<len`` cannot be read
as a tag and skew the nesting.

The other two are built with ``createElement``, where there is no markup to
parse. Those fall to a coarser per-file rule: a file that writes an overlay
class into ``className`` must also write ``data-modal-surface``. **That rule
cannot count**, so a *second* DOM-built modal added to one of those two files
would pass. It is stated rather than hidden: ``export_dialog.js`` and
``question_entry.js`` have one each, and
``test_both_construction_styles_are_detected`` pins that both styles are seen
at all.

What this file does NOT check
-----------------------------
Plugins. ``plugin_loader.js`` injects third-party JS on every page with access
to ``window.api``, and a plugin that builds a modal is outside this tree.
``docs/guides/MODAL_DIALOG.md`` says so for plugin authors.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.test_modal_dialog_markup import (
    DIALOG_ROLES,
    NON_DIALOG_OVERLAYS,
    OVERLAY_CLASSES,
    Element,
    accessible_name_problem,
    first_heading,
    overlays,
    surfaces,
)

ROOT = Path(__file__).resolve().parents[1]
WEB_JS = ROOT / "src" / "web" / "js"
WEB_HTML = ROOT / "src" / "web" / "html"

MARKER = "data-modal-surface"

# The helper itself names the marker as a selector and creates no modal. Every
# other first-party module is swept.
HELPER = "modal_dialog.js"

# Real HTML element names only. A JavaScript `i<len` or `a<b.length` would
# otherwise be parsed as a tag and push a bogus frame onto the ancestry stack,
# which is the one way this parse could be quietly wrong.
HTML_TAGS = {
    "a", "abbr", "article", "aside", "b", "blockquote", "br", "button",
    "canvas", "caption", "code", "col", "colgroup", "dd", "details", "dialog",
    "div", "dl", "dt", "em", "fieldset", "figcaption", "figure", "footer",
    "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "iframe",
    "img", "input", "label", "legend", "li", "main", "nav", "ol", "optgroup",
    "option", "p", "pre", "progress", "section", "select", "small", "span",
    "strong", "sub", "summary", "sup", "table", "tbody", "td", "textarea",
    "tfoot", "th", "thead", "tr", "u", "ul",
}
VOID_TAGS = {"br", "col", "hr", "img", "input"}

_CLASS_WRITE = re.compile(
    r"""(?:\.className\s*=\s*|setAttribute\(\s*['"]class['"]\s*,\s*)"""
    r"""['"]([^'"]*)['"]""")

_DIALOG_OVERLAYS = set(OVERLAY_CLASSES) - set(NON_DIALOG_OVERLAYS)


class _JsMarkupReader(HTMLParser):
    """Build a tree from whatever HTML a .js file contains, ignoring the rest."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#fragment", {}, None, 0)
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if tag not in HTML_TAGS:
            return
        node = Element(tag, dict(attrs), self._stack[-1], self.getpos()[0])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if tag not in HTML_TAGS:
            return
        node = Element(tag, dict(attrs), self._stack[-1], self.getpos()[0])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        if tag not in HTML_TAGS:
            return
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return


# Doc comments only: a block comment that STARTS A LINE. The obvious
# `/\*.*?\*/` is wrong here and was measured to be wrong -- `media_upload.js`
# contains `accept="image/*"` inside its template, and the nearest `*/` after
# that is in a doc comment 120 lines further down, so a naive strip swallowed
# the whole template and the four media modals parsed as **zero**. That is the
# failure this file's inventory control exists to catch, and it caught it on
# the first run.
_DOC_COMMENT = re.compile(r"(?m)^[ \t]*/\*.*?\*/", re.S)


def parse_js_markup(source: str) -> Element:
    """Parse the markup a module *renders*, ignoring its doc comments.

    A modal drawn in a comment is not a modal: ``modal_dialog.js``'s own
    header shows the pattern it reads, and
    ``test_the_helper_is_not_swept_as_a_modal`` is what asserts the helper
    writes no dialogs of its own. Commented-out markup is not rendered either.
    """
    reader = _JsMarkupReader()
    reader.feed(_DOC_COMMENT.sub("", source))
    return reader.root


def _js_modules() -> list[Path]:
    found = sorted(p for p in WEB_JS.rglob("*.js")
                   if "lib" not in p.parts and p.name != HELPER)
    assert found, f"no first-party JavaScript found under {WEB_JS}"
    return found


def _module_id(path: Path) -> str:
    return str(path.relative_to(WEB_JS).as_posix())


def _writes_an_overlay_class(source: str) -> list[str]:
    """Overlay classes written through className / setAttribute('class')."""
    out = []
    for match in _CLASS_WRITE.finditer(source):
        hit = set(match.group(1).split()) & _DIALOG_OVERLAYS
        if hit:
            out.append(match.group(1))
    return out


def builds_a_modal(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if _writes_an_overlay_class(source):
        return True
    if MARKER in source:
        return True
    return bool(overlays(parse_js_markup(source)))


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _js_modules(), ids=_module_id)
def test_a_templated_overlay_holds_one_marked_surface(path: Path) -> None:
    """The markup guard's rule, applied to markup that lives in a .js file."""
    root = parse_js_markup(path.read_text(encoding="utf-8"))
    found = overlays(root)
    if not found:
        pytest.skip(f"{_module_id(path)} renders no modal overlay markup")

    for overlay in found:
        marked = surfaces(overlay)
        assert len(marked) == 1, (
            f"{_module_id(path)}: {overlay.describe()} is a modal overlay "
            f"holding {len(marked)} [{MARKER}] elements, not 1. The surface "
            f"inside it -- not the scrim -- carries role=\"dialog\", "
            f"aria-modal=\"true\" and the accessible name (#319). See "
            f"docs/guides/MODAL_DIALOG.md."
        )


@pytest.mark.parametrize("path", _js_modules(), ids=_module_id)
def test_a_templated_surface_is_a_named_dialog_with_an_h2(path: Path) -> None:
    root = parse_js_markup(path.read_text(encoding="utf-8"))
    marked = [n for n in root.walk() if MARKER in n.attrs]
    if not marked:
        pytest.skip(f"{_module_id(path)} renders no marked surface markup")

    for surface in marked:
        assert surface.attrs.get("role") in DIALOG_ROLES, (
            f"{_module_id(path)}: {surface.describe()} carries {MARKER} but "
            f"role={surface.attrs.get('role')!r} (#319).")
        assert surface.attrs.get("aria-modal") == "true", (
            f"{_module_id(path)}: {surface.describe()} is a dialog but "
            f"aria-modal={surface.attrs.get('aria-modal')!r}, so the page "
            f"behind it stays in the accessibility tree (#319).")
        problem = accessible_name_problem(surface, root)
        assert problem is None, (
            f"{_module_id(path)}: {surface.describe()} is a dialog but "
            f"{problem} (#319).")
        heading = first_heading(surface)
        if heading is not None:
            assert heading.tag == "h2", (
                f"{_module_id(path)}: {surface.describe()} opens with "
                f"<{heading.tag}> at line {heading.line}, not an <h2> "
                f"(#318). If that changes its size, the fix is the CSS rule.")


@pytest.mark.parametrize("path", _js_modules(), ids=_module_id)
def test_a_dom_built_overlay_marks_its_surface(path: Path) -> None:
    """A module that builds an overlay in code must mark a surface somewhere.

    This is the coarse half and it **cannot count**: a module with two
    DOM-built modals and one marker would pass. It is paired with
    ``test_both_construction_styles_are_detected``, which names every
    JavaScript-built surface in the tree and asserts each module is reached by
    one rule or the other.
    """
    source = path.read_text(encoding="utf-8")
    written = _writes_an_overlay_class(source)
    if not written:
        pytest.skip(f"{_module_id(path)} builds no overlay with className")

    assert MARKER in source, (
        f"{_module_id(path)} writes the overlay class(es) {written} into "
        f"className but never writes {MARKER}, so the dialog it builds has no "
        f"role, no aria-modal and no accessible name (#319). Put all four on "
        f"the SURFACE element, not on the backdrop -- "
        f"docs/guides/MODAL_DIALOG.md has both spellings."
    )


@pytest.mark.parametrize("path", _js_modules(), ids=_module_id)
def test_a_surface_marked_in_code_is_also_a_named_dialog(path: Path) -> None:
    """``setAttribute`` modals: the attributes the parse cannot see.

    When the marker is written as markup, the surface is in the parse and
    ``test_a_templated_surface_is_a_named_dialog_with_an_h2`` reads its
    attributes directly. When it is written with ``setAttribute`` there is no
    markup, so the three companions are checked per file instead -- coarse, and
    the only thing available short of executing the module.
    """
    source = path.read_text(encoding="utf-8")
    if not re.search(rf"""setAttribute\(\s*['"]{MARKER}['"]""", source):
        pytest.skip(f"{_module_id(path)} marks no surface with setAttribute")

    for attr, why in (
        ("role", "nothing announces that a dialog opened"),
        ("aria-modal", "the page behind it stays in the accessibility tree"),
    ):
        assert re.search(rf"""setAttribute\(\s*['"]{attr}['"]""", source), (
            f"{_module_id(path)} marks a modal surface with setAttribute but "
            f"never sets {attr!r} the same way, so {why} (#319)")
    assert re.search(r"""setAttribute\(\s*['"]aria-label(ledby)?['"]""",
                     source), (
        f"{_module_id(path)} marks a modal surface with setAttribute but sets "
        f"neither aria-labelledby nor aria-label, so a reader that finds the "
        f"dialog is not told what it is (#319)")


@pytest.mark.parametrize("path", sorted(WEB_HTML.rglob("*.html")),
                         ids=lambda p: str(p.relative_to(WEB_HTML).as_posix()))
def test_a_page_that_can_open_a_modal_loads_the_helper(path: Path) -> None:
    """Both directions, because the per-page <script> link is the gotcha.

    Stylesheets and scripts are loaded by individual pages (CLAUDE.md's
    per-page CSS link gotcha, one layer over), and a page can reach a modal two
    ways: its own markup, or a module it loads. Three pages --
    ``analytics_dashboard.html``, ``subject_deep_dive.html`` and
    ``entry_browser.html`` -- have **no modal in their markup at all** and open
    one anyway, which is precisely why this check cannot live in the markup
    guard. Without the helper those dialogs take no focus on open and restore
    none on close, which is the half of #319 that attributes cannot provide.
    """
    page = str(path.relative_to(WEB_HTML).as_posix())
    source = path.read_text(encoding="utf-8")

    from tests.test_modal_dialog_markup import parse_source
    own_markup = bool(overlays(parse_source(source)))

    via_modules = sorted(
        _module_id(js) for js in _js_modules()
        if f"js/{_module_id(js)}" in source and builds_a_modal(js))

    loads = f"js/{HELPER}" in source

    if own_markup or via_modules:
        assert loads, (
            f"{page} can open a modal (own markup: {own_markup}; modules that "
            f"build one: {via_modules or 'none'}) but does not load "
            f"js/{HELPER}. Add the <script> tag; see "
            f"docs/guides/MODAL_DIALOG.md.")
    else:
        assert not loads, (
            f"{page} loads js/{HELPER} but can open no modal, in its markup "
            f"or through any module it loads. Drop the tag -- otherwise the "
            f"link stops being evidence that a page with modals has one.")


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------


def test_both_construction_styles_are_detected() -> None:
    """The inventory, and the control that makes the coarse rule honest.

    Every check above skips a module that renders no modal, and "renders no
    modal" is also what a broken parse looks like. These are the thirteen
    JavaScript-built surfaces in the tree when this landed, with how many each
    module owns, so the file cannot go green by seeing nothing.
    """
    templated = {           # found by parsing the module's own markup
        "media_upload.js": 4,
        "alias_manager.js": 1,
    }
    dom_built = {           # found only by the coarse className rule
        "export_dialog.js": 1,
        "question_entry.js": 1,
    }
    # Built with createElement for the overlay and a template for the inside,
    # so the overlay is invisible to the parse and the className rule is what
    # reaches them.
    mixed = {
        "goal_widget.js": 1,
        "image_browser.js": 1,
        "rich_editor.js": 1,
        "subject_relations.js": 1,
        "import_export.js": 2,
    }

    for name, count in templated.items():
        root = parse_js_markup((WEB_JS / name).read_text(encoding="utf-8"))
        found = overlays(root)
        assert len(found) == count, (
            f"expected {count} templated modal overlay(s) in {name}, parsed "
            f"{len(found)} -- the JS markup parse is not seeing this file, so "
            f"every templated check skips it")

    for name in {**dom_built, **mixed}:
        source = (WEB_JS / name).read_text(encoding="utf-8")
        assert _writes_an_overlay_class(source), (
            f"{name} builds its overlay with className and the detector no "
            f"longer sees it, so test_a_dom_built_overlay_marks_its_surface "
            f"skips the file entirely")

    total = sum(templated.values()) + sum(dom_built.values()) \
        + sum(mixed.values())
    assert total == 13, f"the inventory no longer adds up to 13: {total}"

    marked = sum(
        (WEB_JS / name).read_text(encoding="utf-8").count(MARKER)
        for name in {**templated, **dom_built, **mixed})
    assert marked >= total, (
        f"{total} JavaScript-built modal surfaces are named in this "
        f"inventory but only {marked} {MARKER} markers are written across "
        f"those files")


def test_the_js_parser_cannot_be_fooled_by_javascript() -> None:
    """Negative control for the one way this parse could be silently wrong.

    ``for (var i = 0; i<len; i++)`` contains ``<len``, which ``html.parser``
    reads as a start tag. Pushing it would skew every ancestry test after it,
    so the reader ignores anything that is not a real HTML element name --
    and a modal written *after* such a line must still be found.
    """
    root = parse_js_markup(
        "for (var i = 0; i<arr.length; i++) {}\n"
        "if (a<b && c>d) {}\n"
        'el.innerHTML = `<div class="modal-backdrop" id="x">'
        '<div class="modal" data-modal-surface role="dialog" aria-modal="true" '
        'aria-label="L"><h2>T</h2></div></div>`;\n')
    found = overlays(root)
    assert len(found) == 1, (
        f"expected the one modal overlay, parsed {[o.describe() for o in found]}")
    assert len(surfaces(found[0])) == 1, (
        "the surface inside the overlay was not seen, so the JS parse cannot "
        "check nesting at all")

    # The `accept="image/*"` trap: a `/*` inside a template literal must not
    # start a comment, or everything after it until the next `*/` disappears.
    # This is media_upload.js's real shape, reduced.
    root = parse_js_markup(
        'el.innerHTML = `<input type="file" accept="image/*" hidden>'
        '<div class="media-rename-modal" id="r">'
        '<div class="media-rename-content" data-modal-surface role="dialog" '
        'aria-modal="true" aria-label="L"><h2>T</h2></div></div>`;\n'
        "/**\n * A doc comment well after it.\n */\n")
    assert len(overlays(root)) == 1, (
        'a `/*` inside a template literal is swallowing the markup after it; '
        'that is how four media modals once parsed as zero')


def test_the_js_checks_would_catch_each_mistake() -> None:
    """Every rule, asserted to be detectable, in the shapes that shipped."""
    # 1. A templated overlay with no marked surface -- plain #319.
    root = parse_js_markup(
        'x.innerHTML = `<div class="media-rename-modal" id="r">'
        '<div class="media-modal-backdrop"></div>'
        '<div class="media-rename-content"><h4>Rename</h4></div></div>`;')
    found = overlays(root)
    assert len(found) == 1 and surfaces(found[0]) == [], (
        "an unmarked JS-built overlay reads as marked")

    # 2. A marked surface with an h4 title -- media_upload.js's real shape.
    root = parse_js_markup(
        'x.innerHTML = `<div class="media-rename-modal" id="r">'
        '<div class="media-rename-content" data-modal-surface role="dialog" '
        'aria-modal="true" aria-labelledby="t"><h4 id="t">Rename</h4>'
        "</div></div>`;")
    surface = surfaces(overlays(root)[0])[0]
    heading = first_heading(surface)
    assert heading is not None and heading.tag == "h4", (
        "the heading rule is vacuous on JS-built markup")

    # 3. A dangling aria-labelledby inside a template.
    root = parse_js_markup(
        'x.innerHTML = `<div class="relation-modal">'
        '<div class="modal-content" data-modal-surface role="dialog" '
        'aria-modal="true" aria-labelledby="gone"><h2 id="t">T</h2>'
        "</div></div>`;")
    surface = surfaces(overlays(root)[0])[0]
    assert accessible_name_problem(surface, root) is not None, (
        "an unresolved aria-labelledby in a JS template reads as a name")

    # 3b. A setAttribute-marked surface missing its companions.
    half_done = ("m.setAttribute('data-modal-surface', '');\n"
                 "m.setAttribute('role', 'dialog');\n")
    assert re.search(r"""setAttribute\(\s*['"]role['"]""", half_done)
    assert not re.search(r"""setAttribute\(\s*['"]aria-modal['"]""",
                         half_done), (
        "the setAttribute rule cannot see a missing aria-modal, so "
        "test_a_surface_marked_in_code_is_also_a_named_dialog proves nothing")

    # 4. The className rule, in both syntaxes, and a miss that must not fire.
    assert _writes_an_overlay_class("m.className = 'modal-backdrop active';")
    assert _writes_an_overlay_class(
        "m.setAttribute('class', 'image-browser-modal');")
    assert not _writes_an_overlay_class("m.className = 'modal-title';"), (
        "'modal-title' is not an overlay; the detector is matching on a "
        "substring and would demand a dialog for every title element")
    assert not _writes_an_overlay_class("m.className = 'toast-container';")

    # 5. Positive control: a correct JS-built modal must trip nothing.
    root = parse_js_markup(
        'x.innerHTML = `<div class="modal-backdrop" id="x">'
        '<div class="modal" data-modal-surface role="dialog" aria-modal="true" '
        'aria-labelledby="t"><h2 class="modal-title" id="t">T</h2>'
        "</div></div>`;")
    found = overlays(root)
    surface = surfaces(found[0])[0]
    assert surface.attrs.get("role") == "dialog"
    assert surface.attrs.get("aria-modal") == "true"
    assert accessible_name_problem(surface, root) is None
    assert first_heading(surface).tag == "h2"


def test_the_helper_is_not_swept_as_a_modal() -> None:
    """modal_dialog.js names the marker as a selector and builds no dialog.

    Excluding it is a choice rather than an oversight, so it is checked: if
    the helper ever starts writing dialog markup, that is a design change and
    this says so instead of the sweep silently skipping it.
    """
    helper = WEB_JS / HELPER
    assert helper.exists(), f"{HELPER} is gone; the pattern has no focus half"
    assert helper not in _js_modules(), (
        f"{HELPER} is being swept as though it built a modal")
    assert not overlays(parse_js_markup(helper.read_text(encoding="utf-8"))), (
        f"{HELPER} now renders modal overlay markup of its own, which is not "
        f"what it is for -- it reads the marker, it does not write dialogs")
