"""Every modal is a dialog, named, and starts its own h2 (#319, #318).

Why a pattern and a guard rather than 45 hand-edits
---------------------------------------------------
#319 measured 23 of 25 modal surfaces carrying no ``role``, no ``aria-modal``
and no accessible name, and the owner's decision (2026-10-03) was **one shared
pattern across every modal surface, doing role, ``aria-modal``, the accessible
name and the heading level together** -- expressly so that *the next modal is
correct by default*. That is the shape of ``page_gate.js`` /
``docs/guides/PAGE_GATE.md`` / ``tests/test_page_gate_markup.py``: one helper,
one guide, one self-counting test. This is the test.

It discovers modals rather than listing them, so a 46th is checked the day it
is written.

What a modal surface is, and how this file finds one
----------------------------------------------------
A modal has two parts and they are **not** interchangeable:

* the **overlay** -- a full-viewport ``position: fixed`` scrim that also serves
  as the click-to-dismiss area;
* the **surface** -- the box the student sees, holding the title and the
  controls.

The overlay class set is **derived from the stylesheets**, not listed here: any
single-class selector in ``src/web/css`` that declares ``position: fixed`` and
covers the viewport. That is where a new modal comes from, so deriving it is
what makes this self-counting at the class level. ``_overlay_classes()`` is the
derivation and ``test_the_overlay_set_is_derived_and_sane`` is its control.

Each overlay that has element children must contain exactly one
``[data-modal-surface]``, and that element must not be the overlay itself. An
overlay with **no** element children is a bare scrim nested inside a wrapper
(``.relation-modal > .modal-backdrop``) and is skipped -- the same class means
"container" in one family and "scrim" in the other, and the child count is what
tells them apart.

Why the role goes on the surface and never on the overlay
---------------------------------------------------------
The two instances that existed before this landed
(``question_entry.html``'s ``#manage-tags-modal`` and ``#attach-existing-modal``)
put ``role="dialog"`` on the **overlay**, and ``subject_relations.js`` put it on
the surface -- so the convention was applied to 3 of 45 surfaces in two
different places. Settled on the surface, because the overlay *is* the
click-outside-to-dismiss region: a dialog whose own boundary contains the
"click here to leave this dialog" area is a contradiction, and its bounding box
is the whole viewport rather than the box a sighted user sees. The name also
comes from ``.modal-title``, which lives in the surface.

Why the heading is an h2
------------------------
#318 left this open ("whether a modal's heading belongs to the page's outline
or starts its own is a real question") and the owner folded it into this
pattern. ``role="dialog"`` does **not** reset the document outline -- ARIA has
no such effect -- so a modal title is still a section of the page, and one
level under its ``h1`` is the only level that is right wherever the modal sits
in document order. Dropping *down* to an h2 from an h3 section is not a skip,
so h2 is also the only choice that cannot create one.

The level was never chosen for its size. Most of these titles already carried
``font-size`` on their class, so re-tagging them was visually inert; **ten**
were styled by an **element** selector instead (three in markup --
``.quick-add-header h4``, ``.new-round-dialog h3``,
``.learn-more-content h4`` -- and seven in JavaScript-rendered modals), and
for those the CSS selector moved with the tag. That is #318's own rule: if a
class has no size of its own, the fix is a CSS rule, not a heading level.
``docs/guides/MODAL_DIALOG.md`` has the table.

What this file cannot see, and what covers it
---------------------------------------------
**Anything built by JavaScript** -- which is where 13 of the 45 surfaces live,
and where two of #317's own three defects lived. ``test_modal_dialog_js.py``
parses the template literals in ``src/web/js`` with the same tree builder and
runs the same containment rule over them.

**Whether a dialog is announced, and whether focus goes anywhere.** Attributes
are exactly what stays correct when a node has been removed from the
accessibility tree (#121), so the announcement is measured through CDP's
``Accessibility`` domain in
``tests/wimi_test/scenarios/test_modal_is_announced_as_a_dialog.py``.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB_HTML = ROOT / "src" / "web" / "html"
WEB_CSS = ROOT / "src" / "web" / "css"

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

DIALOG_ROLES = {"dialog", "alertdialog"}

# An overlay that is deliberately NOT a dialog. One entry, and it carries its
# own self-correcting control: test_a_non_dialog_overlay_is_still_not_a_dialog
# asserts it still holds nothing a student could interact with, so the day it
# grows a button it stops being exempt. `aria-modal` on a wait indicator would
# make every other thing on the page invisible to a screen reader in order to
# announce a spinner.
NON_DIALOG_OVERLAYS = {
    "pf-busy-overlay":
        "a progress scrim shown over the profile picker during a long "
        "export/import. There is nothing in it to interact with, so it is a "
        "status region, not a dialog -- and it announces nothing today, "
        "which is #333 and not this pattern's business",
}


# ---------------------------------------------------------------------------
# A minimal ancestry-aware HTML parser (the shape test_page_gate_markup.py uses)
# ---------------------------------------------------------------------------


class Element:
    __slots__ = ("tag", "attrs", "children", "parent", "line")

    def __init__(self, tag: str, attrs: dict, parent, line: int) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Element] = []
        self.parent = parent
        self.line = line

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def describe(self) -> str:
        bits = [self.tag]
        if self.attrs.get("id"):
            bits.append(f"#{self.attrs['id']}")
        if self.attrs.get("class"):
            bits.append(f".{'.'.join((self.attrs['class']).split())}")
        return f"{''.join(bits)} at line {self.line}"


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {}, None, 0)
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict(attrs), self._stack[-1], self.getpos()[0])
        self._stack[-1].children.append(node)
        if tag not in VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Element(tag, dict(attrs), self._stack[-1], self.getpos()[0])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return


def parse_source(source: str) -> Element:
    builder = TreeBuilder()
    builder.feed(source)
    return builder.root


def _parse(path: Path) -> Element:
    return parse_source(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The overlay class set, derived from the stylesheets
# ---------------------------------------------------------------------------

_SINGLE_CLASS = re.compile(r"^\.([A-Za-z0-9_-]+)$")
_FIXED = re.compile(r"position\s*:\s*fixed")


def _covers_the_viewport(body: str) -> bool:
    if re.search(r"\binset\s*:\s*0", body):
        return True
    sides = sum(
        bool(re.search(rf"\b{side}\s*:\s*0", body))
        for side in ("top", "left", "right", "bottom")
    )
    if sides == 4:
        return True
    has_top_left = (re.search(r"\btop\s*:\s*0", body)
                    and re.search(r"\bleft\s*:\s*0", body))
    spans = (re.search(r"\bwidth\s*:\s*100(%|vw)", body)
             and re.search(r"\bheight\s*:\s*100(%|vh)", body))
    return bool(has_top_left and spans)


def _overlay_classes() -> dict[str, str]:
    """Class name -> "stylesheet:line" for every full-viewport fixed overlay."""
    found: dict[str, str] = {}
    for sheet in sorted(WEB_CSS.glob("*.css")):
        src = re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"),
                     flags=re.S)
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", src):
            selector, body = match.group(1).strip(), match.group(2)
            if not _FIXED.search(body) or not _covers_the_viewport(body):
                continue
            for part in selector.split(","):
                hit = _SINGLE_CLASS.match(part.strip())
                if hit:
                    line = src.count("\n", 0, match.start(1)) + 1
                    found.setdefault(hit.group(1), f"{sheet.name}:{line}")
    return found


OVERLAY_CLASSES = _overlay_classes()


def overlays(root: Element) -> list[Element]:
    """Overlay elements that wrap content, i.e. that need a dialog inside.

    An overlay with no element children is a bare scrim nested inside a
    wrapper -- ``.relation-modal > .modal-backdrop`` -- and is not a dialog
    container. The child count is the only thing that distinguishes the two
    uses of ``.modal-backdrop`` in this tree.
    """
    out = []
    for node in root.walk():
        if node.classes() & set(OVERLAY_CLASSES) - set(NON_DIALOG_OVERLAYS):
            if any(c.tag not in ("script", "style") for c in node.children):
                out.append(node)
    return out


def surfaces(overlay: Element) -> list[Element]:
    return [n for n in overlay.walk()
            if n is not overlay and "data-modal-surface" in n.attrs]


def _ids(root: Element) -> dict[str, Element]:
    return {n.attrs["id"]: n for n in root.walk() if n.attrs.get("id")}


def accessible_name_problem(surface: Element, root: Element) -> str | None:
    """Return why this surface has no accessible name, or None if it has one."""
    label = (surface.attrs.get("aria-label") or "").strip()
    labelledby = (surface.attrs.get("aria-labelledby") or "").strip()
    if labelledby:
        table = _ids(root)
        missing = [tok for tok in labelledby.split() if tok not in table]
        if missing:
            return (f"aria-labelledby names {missing}, which no element in "
                    f"this document has as an id -- an unresolved reference "
                    f"leaves the dialog unnamed, silently")
        return None
    if label:
        return None
    return ("it has neither aria-labelledby nor aria-label, so a reader that "
            "finds the dialog is not told what it is")


def first_heading(surface: Element) -> Element | None:
    for node in surface.walk():
        if node.tag in {f"h{n}" for n in range(1, 7)}:
            return node
    return None


def _html_pages() -> list[Path]:
    pages = sorted(WEB_HTML.rglob("*.html"))
    assert pages, f"no HTML pages found under {WEB_HTML}"
    return pages


def _page_id(path: Path) -> str:
    return str(path.relative_to(WEB_HTML).as_posix())


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _html_pages(), ids=_page_id)
def test_every_overlay_contains_one_marked_surface(path: Path) -> None:
    """A modal nobody marked is a modal nobody gave dialog semantics."""
    root = _parse(path)
    found = overlays(root)
    if not found:
        pytest.skip(f"{_page_id(path)} has no modal overlay")

    for overlay in found:
        marked = surfaces(overlay)
        assert len(marked) == 1, (
            f"{_page_id(path)}: {overlay.describe()} is a modal overlay "
            f"holding {len(marked)} [data-modal-surface] elements, not 1.\n"
            f"The overlay is the scrim and the click-to-dismiss area; the "
            f"surface is the box the student sees, and it is the surface that "
            f"carries role=\"dialog\", aria-modal=\"true\" and the accessible "
            f"name (#319). See docs/guides/MODAL_DIALOG.md."
        )


@pytest.mark.parametrize("path", _html_pages(), ids=_page_id)
def test_every_marked_surface_is_a_named_dialog(path: Path) -> None:
    """role, aria-modal and a name -- the three #319 found missing together."""
    root = _parse(path)
    marked = [n for n in root.walk() if "data-modal-surface" in n.attrs]
    if not marked:
        pytest.skip(f"{_page_id(path)} has no marked modal surface")

    for surface in marked:
        role = surface.attrs.get("role")
        assert role in DIALOG_ROLES, (
            f"{_page_id(path)}: {surface.describe()} carries "
            f"data-modal-surface but role={role!r}. Without role=\"dialog\" a "
            f"modal is ordinary page content that happens to appear, and "
            f"nothing announces that a dialog opened (#319)."
        )
        assert surface.attrs.get("aria-modal") == "true", (
            f"{_page_id(path)}: {surface.describe()} is a dialog but "
            f"aria-modal={surface.attrs.get('aria-modal')!r}. Without it the "
            f"page behind the modal stays in the accessibility tree, so "
            f"arrowing past the end of the dialog walks into the page it is "
            f"covering with no boundary (#319)."
        )
        problem = accessible_name_problem(surface, root)
        assert problem is None, (
            f"{_page_id(path)}: {surface.describe()} is a dialog but "
            f"{problem} (#319)."
        )


@pytest.mark.parametrize("path", _html_pages(), ids=_page_id)
def test_a_dialog_title_is_an_h2(path: Path) -> None:
    """The heading half of the pattern -- see the module docstring (#318)."""
    root = _parse(path)
    marked = [n for n in root.walk() if "data-modal-surface" in n.attrs]
    if not marked:
        pytest.skip(f"{_page_id(path)} has no marked modal surface")

    for surface in marked:
        heading = first_heading(surface)
        if heading is None:
            continue  # An image lightbox has no title; it carries aria-label.
        assert heading.tag == "h2", (
            f"{_page_id(path)}: {surface.describe()} opens with "
            f"<{heading.tag}> at line {heading.line}, not an <h2>. A dialog "
            f"title is one level under the page's h1 wherever the modal sits "
            f"in document order, which is the only level that can never "
            f"create a skip (#318). If that changes its size, the fix is the "
            f"CSS rule, never the heading level."
        )


# The per-page `<script src="../js/modal_dialog.js">` link is checked in BOTH
# directions by test_modal_dialog_js.py and deliberately not here. A page can
# reach a modal two ways -- its own markup, or a module it loads -- and three
# pages (analytics_dashboard, subject_deep_dive, entry_browser) have no modal
# in their markup at all and open one anyway. A check that only read the HTML
# would have to call those three correct for loading a helper they appear not
# to need, i.e. it would be wrong in the direction that matters.


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------


def test_the_overlay_set_is_derived_and_sane() -> None:
    """The derivation is the self-counting half; a broken one reads as clean.

    Every check above skips a page with no overlay, and "no overlay" is also
    what an empty ``OVERLAY_CLASSES`` looks like. These are the scrim classes
    in the tree when this landed, each from a different stylesheet family, so
    if the CSS parse stops seeing them the whole file cannot quietly skip.
    """
    assert OVERLAY_CLASSES, (
        "no full-viewport fixed overlay class was derived from "
        f"{WEB_CSS}; every check in this file would skip every page")
    for expected in (
        "modal-backdrop",          # session/tree/wizard/landing -- most modals
        "profile-modal-backdrop",  # profiles.css
        "lightbox-modal",          # detail.css
        "media-modal",             # media.css
        "relation-modal",          # subject_relations.css
        "goal-modal",              # analytics.css
        "image-browser-modal",     # media.css
        "rich-editor-math-modal",  # rich_editor.css
        "new-round-dialog-overlay",  # entry.css
    ):
        assert expected in OVERLAY_CLASSES, (
            f".{expected} is a full-viewport fixed overlay in this tree but "
            f"the derivation did not find it; the guard is now blind to every "
            f"modal built on it. Derived: {sorted(OVERLAY_CLASSES)}")

    # The inner scrims are `position: absolute`, which is what keeps them out
    # of the set -- if one ever reads as an overlay, `overlays()` would demand
    # a dialog inside a scrim.
    for scrim in ("lightbox-backdrop", "media-modal-backdrop",
                  "image-browser-backdrop", "rich-editor-math-backdrop"):
        assert scrim not in OVERLAY_CLASSES, (
            f".{scrim} is an inner scrim (position: absolute) and must not be "
            f"treated as an overlay container")


def test_the_pages_with_modals_are_actually_covered() -> None:
    """Four checks above skip, and a failed parse looks exactly like a skip."""
    expected = {
        "index.html": 1,
        "entry_detail.html": 1,
        "profile_select.html": 5,
        "question_entry.html": 9,
        "session_setup.html": 9,
        "tree_editor.html": 3,
        "wizards/exam_wizard.html": 4,
    }
    for name, least in expected.items():
        root = _parse(WEB_HTML / name)
        count = len(overlays(root))
        assert count >= least, (
            f"expected at least {least} modal overlays in {name}, found "
            f"{count} -- the parser is not seeing this page, so every check "
            f"in this file skips it")


def test_a_non_dialog_overlay_is_still_not_a_dialog() -> None:
    """An exemption may not outlive its reason (test_heading_order.py's shape).

    ``NON_DIALOG_OVERLAYS`` is exempt because there is nothing in it to
    interact with. That is a property of the markup, so it is checked rather
    than asserted: the day one of these grows a control it becomes a dialog,
    and this fails instead of quietly exempting it.
    """
    focusable = {"a", "button", "input", "select", "textarea", "summary"}
    seen = set()
    for path in _html_pages():
        root = _parse(path)
        for node in root.walk():
            hit = node.classes() & set(NON_DIALOG_OVERLAYS)
            if not hit:
                continue
            seen |= hit
            controls = [n.tag for n in node.walk() if n.tag in focusable
                        or "tabindex" in n.attrs]
            assert not controls, (
                f"{_page_id(path)}: {node.describe()} is listed in "
                f"NON_DIALOG_OVERLAYS as "
                f"{NON_DIALOG_OVERLAYS[sorted(hit)[0]]!r}, but it now holds "
                f"{controls}. Something a student can reach inside a "
                f"full-viewport scrim is a dialog: delete the exemption and "
                f"give it the pattern (#319).")
    assert seen == set(NON_DIALOG_OVERLAYS), (
        f"NON_DIALOG_OVERLAYS names {sorted(set(NON_DIALOG_OVERLAYS) - seen)}, "
        f"which no page uses. A stale exemption hides a live failure, exactly "
        f"as a stale xfail does -- delete the line")


def test_the_checks_would_catch_each_mistake() -> None:
    """Negative control: every rule above, asserted to be detectable.

    Without this a parser that quietly found nothing would look exactly like a
    clean tree -- which is how #319's own defect survived every test in the
    repo, and how 3 of 45 surfaces came to carry the convention in two
    different places.
    """
    # 1. An overlay with no marked surface at all -- plain #319.
    root = parse_source(
        '<html><body><div class="modal-backdrop" id="x">'
        '<div class="modal"><h2 class="modal-title">T</h2></div>'
        "</div></body></html>")
    found = overlays(root)
    assert len(found) == 1, "the overlay was not recognised"
    assert surfaces(found[0]) == [], (
        "an unmarked overlay reads as marked, so "
        "test_every_overlay_contains_one_marked_surface proves nothing")

    # 2. The role on the OVERLAY rather than the surface -- the shape the two
    #    pre-existing instances had, which is why it must not pass.
    root = parse_source(
        '<html><body><div class="modal-backdrop" id="x" role="dialog" '
        'aria-modal="true" aria-labelledby="t">'
        '<div class="modal"><h2 class="modal-title" id="t">T</h2></div>'
        "</div></body></html>")
    found = overlays(root)
    assert surfaces(found[0]) == [], (
        "dialog semantics on the overlay satisfy the surface check")

    # 3. A marked surface with no name, and one whose aria-labelledby dangles.
    root = parse_source(
        '<html><body><div class="modal-backdrop" id="x">'
        '<div class="modal" data-modal-surface role="dialog" '
        'aria-modal="true"><h2 id="t">T</h2></div></body></html>')
    surface = surfaces(overlays(root)[0])[0]
    assert accessible_name_problem(surface, root) is not None, (
        "an unnamed dialog reads as named")
    root = parse_source(
        '<html><body><div class="modal-backdrop" id="x">'
        '<div class="modal" data-modal-surface role="dialog" '
        'aria-modal="true" aria-labelledby="nope"><h2 id="t">T</h2></div>'
        "</body></html>")
    surface = surfaces(overlays(root)[0])[0]
    problem = accessible_name_problem(surface, root)
    assert problem and "no element" in problem, (
        "a dangling aria-labelledby reads as a name; an unresolved reference "
        "leaves the dialog unnamed with no error anywhere")

    # 4. The heading rule, in the shape #318 recorded (h3 modal titles).
    root = parse_source(
        '<html><body><div class="modal-backdrop" id="x">'
        '<div class="modal" data-modal-surface role="dialog" '
        'aria-modal="true" aria-labelledby="t">'
        '<h3 class="modal-title" id="t">T</h3></div></body></html>')
    heading = first_heading(surfaces(overlays(root)[0])[0])
    assert heading is not None and heading.tag == "h3", (
        "the heading reader cannot see a modal title, so the h2 rule is "
        "vacuous")

    # 5. A bare nested scrim must be skipped, or the guard demands a dialog
    #    inside the click-to-dismiss div (.relation-modal's shape).
    root = parse_source(
        '<html><body><div class="relation-modal">'
        '<div class="modal-backdrop"></div>'
        '<div class="modal-content" data-modal-surface role="dialog" '
        'aria-modal="true" aria-label="L"><h2>T</h2></div>'
        "</div></body></html>")
    found = overlays(root)
    assert [o.classes() & set(OVERLAY_CLASSES) for o in found] \
        == [{"relation-modal"}], (
        f"expected only the wrapper to be treated as the overlay, got "
        f"{[o.describe() for o in found]} -- a childless .modal-backdrop is a "
        f"scrim, not a dialog container")

    # 6. Positive control: a correct modal must trip nothing, or these rules
    #    are simply failing on everything.
    root = parse_source(
        '<html><body><div class="modal-backdrop" id="x">'
        '<div class="modal" data-modal-surface role="dialog" '
        'aria-modal="true" aria-labelledby="t">'
        '<h2 class="modal-title" id="t">Title</h2></div></body></html>')
    found = overlays(root)
    assert len(found) == 1
    marked = surfaces(found[0])
    assert len(marked) == 1
    assert marked[0].attrs.get("role") == "dialog"
    assert marked[0].attrs.get("aria-modal") == "true"
    assert accessible_name_problem(marked[0], root) is None
    assert first_heading(marked[0]).tag == "h2"
