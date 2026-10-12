"""The manual's chapters, its generated pages, and the gate between them (#428).

The manual is one markdown file per chapter under ``docs/manual/``, and
``scripts/check_manual_sync.py`` generates a page per chapter plus the chapter
list inside ``help.html``. This file covers the three things that have to be
right for that arrangement to be worth trusting:

* the gate **notices** a desync and ``--write`` repairs one;
* every chapter stays inside what the help page's renderer actually supports,
  because the failure mode of a regex renderer is never an error -- it is the
  wrong thing drawn in the shipped app, where nobody is looking. That is how
  ``parseMarkdown``'s three documented limits survived for as long as they did;
* every generated page carries the stylesheet and the script it needs, which is
  the per-page CSS link gotcha one layer over: a page that silently renders with
  browser defaults looks like a styling regression, not a missing ``<link>``.

Self-counting, deliberately
---------------------------
Nothing here lists the chapters. The checks discover them, so **chapter 21 is
checked the day it is written** and nobody has to remember to add it. Same
property ``tests/test_page_gate_markup.py`` has for gated pages, and it is why
the two "the sweep is not vacuous" tests near the bottom are not optional: a
discovery-based check that discovers nothing passes.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_manual_sync.py"
MANUAL_DIR = PROJECT_ROOT / "docs" / "manual"
WEB_HTML = PROJECT_ROOT / "src" / "web" / "html"
HELP_INDEX = WEB_HTML / "help.html"
RENDERER = PROJECT_ROOT / "src" / "web" / "js" / "help_page.js"


def _load_script():
    """Import the gate by path -- ``scripts/`` is not a package.

    The arrangement ``tests/test_import_guide_sync.py`` and
    ``tests/test_check_css_tokens.py`` both use, for the same reason: an
    ``__init__.py`` added only to make a test importable would change how the
    gates are run in CI.
    """
    spec = importlib.util.spec_from_file_location("check_manual_sync", SCRIPT_PATH)
    assert spec and spec.loader, f"could not load {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_script()


def _chapters() -> list[Path]:
    paths = sorted(MANUAL_DIR.glob("*.md"))
    assert paths, f"no chapters found under {MANUAL_DIR}"
    return paths


def _chapter_pages() -> list[Path]:
    return sorted(
        path for path in WEB_HTML.glob("help_*.html")
        if sync.CHAPTER_PAGE.match(path.name)
    )


def _chapter_id(path: Path) -> str:
    return path.name


def _prose_lines(markdown: str) -> list[tuple[int, str]]:
    """``(line number, text)`` for every line outside a fenced code block."""
    out: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(markdown.split("\n"), start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((number, line))
    return out


# --------------------------------------------------------------------------- #
# The detectors, each with a control further down
# --------------------------------------------------------------------------- #

TABLE_SEPARATOR = re.compile(r"\|[-|: ]+\|\s*")
EXTERNAL_LINK = re.compile(r"\]\(\s*(https?|file|mailto|data):", re.I)
INTERNAL_LINK = re.compile(r"\]\(\s*([^):\s]+\.html)(#[^)\s]*)?\s*\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(")


def unsupported_constructs(markdown: str) -> dict[str, list[int]]:
    """Line numbers, per construct the chapter renderer does not support."""
    found: dict[str, list[int]] = {
        "table": [], "blockquote": [], "image": [], "external link": [],
    }
    for number, line in _prose_lines(markdown):
        stripped = line.strip()
        if stripped.startswith(">"):
            found["blockquote"].append(number)
        if stripped.startswith("|") and not TABLE_SEPARATOR.fullmatch(stripped):
            found["table"].append(number)
        if TABLE_SEPARATOR.fullmatch(stripped) and stripped.count("|") >= 2:
            found["table"].append(number)
        if IMAGE.search(line):
            found["image"].append(number)
        if EXTERNAL_LINK.search(line):
            found["external link"].append(number)
    return {name: lines for name, lines in found.items() if lines}


# --------------------------------------------------------------------------- #
# The gate notices, and --write repairs
# --------------------------------------------------------------------------- #

CHAPTER = (
    "# A chapter\n"
    "\n"
    "## In short\n"
    "\n"
    "One sentence that the index shows.\n"
    "\n"
    "## Body\n"
    "\n"
    "Body text.\n"
)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A miniature repo with one chapter, an index shell, and both in sync."""
    (tmp_path / "docs" / "manual").mkdir(parents=True)
    (tmp_path / "src" / "web" / "html").mkdir(parents=True)
    (tmp_path / sync.MANUAL_DIR / "01_a_chapter.md").write_text(
        CHAPTER, encoding="utf-8"
    )
    (tmp_path / sync.INDEX_PAGE).write_text(
        "<body>\n"
        f"    {sync.INDEX_OPEN}\n"
        f"    {sync.INDEX_CLOSE}\n"
        "</body>\n",
        encoding="utf-8",
    )
    sync.write(tmp_path)
    return tmp_path


@pytest.mark.unit
def test_write_makes_a_fresh_repo_clean(fake_repo: Path):
    """``--write`` is what produces a clean tree in the first place."""
    assert sync.audit(fake_repo) == {}
    assert (fake_repo / sync.HTML_DIR / "help_a_chapter.html").is_file()


@pytest.mark.unit
def test_gate_fails_on_a_hand_edited_chapter_page(fake_repo: Path):
    """Editing a generated page by hand is the failure #428 exists to stop.

    The deliberate-desync check: without it the gate could be comparing a
    string to itself and nobody would know.
    """
    page = fake_repo / sync.HTML_DIR / "help_a_chapter.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace("Body text.", "Drifted text."),
        encoding="utf-8",
    )

    problems = sync.audit(fake_repo)
    assert str(sync.HTML_DIR / "help_a_chapter.html") in problems

    sync.write(fake_repo)
    assert sync.audit(fake_repo) == {}
    assert "Body text." in page.read_text(encoding="utf-8")


@pytest.mark.unit
def test_gate_fails_on_a_hand_edited_index(fake_repo: Path):
    """The chapter list is generated too, so it can drift the same way."""
    index = fake_repo / sync.INDEX_PAGE
    index.write_text(
        index.read_text(encoding="utf-8").replace("A chapter", "A chaptre"),
        encoding="utf-8",
    )

    problems = sync.audit(fake_repo)
    assert str(sync.INDEX_PAGE) in problems

    sync.write(fake_repo)
    assert sync.audit(fake_repo) == {}


@pytest.mark.unit
def test_a_new_chapter_needs_no_edit_anywhere_else(fake_repo: Path):
    """The whole point of the arrangement: add a file, run --write.

    If this ever needed a second edit -- a page copied from another, a row
    added to the index by hand -- the manual would have the drift problem the
    gate was built to remove, at twenty chapters instead of one.
    """
    (fake_repo / sync.MANUAL_DIR / "02_second.md").write_text(
        CHAPTER.replace("A chapter", "Second chapter"), encoding="utf-8"
    )
    assert sync.audit(fake_repo), "a new chapter did not register as missing"

    sync.write(fake_repo)
    assert sync.audit(fake_repo) == {}

    index = (fake_repo / sync.INDEX_PAGE).read_text(encoding="utf-8")
    assert "help_second.html" in index
    assert "Second chapter" in index

    # And the neighbour links are regenerated in both directions, which is the
    # part a per-page generator gets wrong: chapter 1 has to learn it now has
    # a successor.
    first = (fake_repo / sync.HTML_DIR / "help_a_chapter.html").read_text(
        encoding="utf-8"
    )
    assert 'data-testid="help-chapter-next"' in first
    second = (fake_repo / sync.HTML_DIR / "help_second.html").read_text(
        encoding="utf-8"
    )
    assert 'data-testid="help-chapter-prev"' in second


@pytest.mark.unit
def test_a_deleted_chapter_leaves_no_orphan_page(fake_repo: Path):
    """A page nothing generates is still reachable by URL and still claims to
    be part of the manual.

    The import guide's gate needs no equivalent because its two artifacts are
    fixed paths. Here the set of artifacts is itself derived from the
    directory, so a stale member is a state ``--write`` has to be able to
    clear -- otherwise a renamed chapter ships twice.
    """
    (fake_repo / sync.MANUAL_DIR / "01_a_chapter.md").rename(
        fake_repo / sync.MANUAL_DIR / "01_renamed.md"
    )
    problems = sync.audit(fake_repo)
    orphan = str(sync.HTML_DIR / "help_a_chapter.html")
    assert orphan in problems
    assert "no chapter" in problems[orphan]

    sync.write(fake_repo)
    assert not (fake_repo / sync.HTML_DIR / "help_a_chapter.html").exists()
    assert (fake_repo / sync.HTML_DIR / "help_renamed.html").is_file()
    assert sync.audit(fake_repo) == {}


@pytest.mark.unit
def test_gate_fails_when_the_index_marker_is_gone(fake_repo: Path):
    """A renamed or deleted marker must fail loudly, not stop syncing."""
    (fake_repo / sync.INDEX_PAGE).write_text(
        "<body>nothing here</body>\n", encoding="utf-8"
    )
    with pytest.raises(sync.ManualError):
        sync.audit(fake_repo)


@pytest.mark.unit
def test_a_chapter_containing_a_script_close_tag_is_refused(fake_repo: Path):
    """``</script>`` in a chapter would close the block and spill markup."""
    chapter = fake_repo / sync.MANUAL_DIR / "01_a_chapter.md"
    chapter.write_text(
        chapter.read_text(encoding="utf-8") + "\nliteral </script> here\n",
        encoding="utf-8",
    )
    with pytest.raises(sync.ManualError):
        sync.audit(fake_repo)


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation, needle",
    [
        ("## In short\n\nOne sentence.\n\n## Body\n\nx.\n", "one '# ' heading"),
        ("# T\n\n## In short\n\nOne.\n\n#### Deep\n\nx.\n", "heading level jumps"),
        ("# T\n\n## Body\n\nx.\n", "In short"),
        ("# T\n\n## In short\n\nA `code` span.\n\n## B\n\nx.\n", "markdown"),
        ("# T\n\n## In short\n\nOne.\n\nTwo.\n\n## B\n\nx.\n", "one paragraph"),
    ],
    ids=["no-title", "level-skip", "no-summary", "markup-in-summary", "two-paragraphs"],
)
def test_a_malformed_chapter_is_refused_with_a_sentence(
    fake_repo: Path, mutation: str, needle: str
):
    """Each structural rule fails with its own message, not an IndexError.

    #66 2.2's rule applied here: a refusal is a sentence a human can act on,
    never an exception from three frames down.
    """
    (fake_repo / sync.MANUAL_DIR / "01_a_chapter.md").write_text(
        mutation, encoding="utf-8"
    )
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert needle in str(exc.value), str(exc.value)


@pytest.mark.unit
def test_a_badly_named_chapter_is_refused(fake_repo: Path):
    """The filename is the ordering and the URL, so it is not free-form."""
    (fake_repo / sync.MANUAL_DIR / "Weights.md").write_text(
        CHAPTER, encoding="utf-8"
    )
    with pytest.raises(sync.ManualError) as exc:
        sync.audit(fake_repo)
    assert "NN_slug.md" in str(exc.value)


@pytest.mark.unit
def test_main_exit_codes(fake_repo: Path, monkeypatch):
    """0 clean, 1 drifted -- the contract CI reads."""
    monkeypatch.setattr(sync, "audit", lambda _root: {}, raising=True)
    monkeypatch.setattr(sync, "read_chapters", lambda _root: [], raising=True)
    assert sync.main([]) == 0

    monkeypatch.setattr(sync, "audit", lambda _root: {"x": "diff"}, raising=True)
    assert sync.main([]) == 1

    def _raise(_root):
        raise sync.ManualError("malformed")

    monkeypatch.setattr(sync, "audit", _raise, raising=True)
    assert sync.main([]) == 2


# --------------------------------------------------------------------------- #
# extract_section -- the mechanism #430's tour steps come through
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_extract_section_stops_at_the_next_sibling_and_not_at_a_child():
    """A named section has to be extractable without a markdown library.

    This is the hook the first-run tour takes its step text from (#430), which
    is what stops a tour step being written beside the manual rather than
    generated from it. A version that ran to the end of the file, or stopped
    at the first deeper heading, would quote the wrong thing -- so both
    boundaries are asserted here rather than assumed.
    """
    doc = (
        "# Title\n\n"
        "## Wanted\n\n"
        "First paragraph.\n\n"
        "### A child heading\n\n"
        "Still inside Wanted.\n\n"
        "## Next\n\n"
        "Not wanted.\n"
    )
    body = sync.extract_section(doc, "## Wanted")
    assert "First paragraph." in body
    assert "Still inside Wanted." in body
    assert "Not wanted." not in body
    assert "## Next" not in body


@pytest.mark.unit
def test_extract_section_refuses_absent_and_empty_sections():
    """Both failures are a sentence, because both are authoring mistakes."""
    with pytest.raises(sync.ManualError):
        sync.extract_section("# T\n\n## Other\n\nx\n", "## Wanted")
    with pytest.raises(sync.ManualError):
        sync.extract_section("# T\n\n## Wanted\n\n## Next\n\nx\n", "## Wanted")


# --------------------------------------------------------------------------- #
# The real tree
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_the_real_tree_is_in_sync():
    """Standing guard: the shipped pages are the committed chapters."""
    problems = sync.audit(PROJECT_ROOT)
    assert problems == {}, (
        "the manual's generated pages have drifted from docs/manual/. Run "
        "`python scripts/check_manual_sync.py --write`:\n"
        + "\n".join(f"--- {k} ---\n{v}" for k, v in sorted(problems.items()))
    )


@pytest.mark.unit
@pytest.mark.parametrize("path", _chapters(), ids=_chapter_id)
def test_every_chapter_avoids_what_the_renderer_cannot_draw(path: Path):
    """``renderHelpMarkdown`` is a regex renderer, and its limits are real.

    None of these four errors. Each just renders the wrong thing in the
    shipped app:

    * a **table** is not parsed at all, so its pipes appear as literal text
      (and the tree's other renderer, ``parseMarkdown``, parses tables but
      silently drops an empty cell and shifts every later column left);
    * a **blockquote** marker is escaped to ``&gt;`` and shows as a stray
      character at the start of the line;
    * an **image** has nowhere to come from -- a chapter is text embedded in a
      page, with no asset path behind it;
    * an **external link** would be clickable, and this view has no address
      bar, so pressing it navigates the application window out of WIMI.

    Prose and lists carry a manual perfectly well. This is the same guard
    ``test_import_guide_sync.py`` puts around the import guide, for the same
    reason.
    """
    found = unsupported_constructs(path.read_text(encoding="utf-8"))
    assert not found, (
        f"{path.name} uses constructs the help renderer does not support: "
        + "; ".join(f"{name} at line(s) {lines}" for name, lines in found.items())
        + ". See src/web/js/help_page.js for what it does support."
    )


@pytest.mark.unit
@pytest.mark.parametrize("path", _chapters(), ids=_chapter_id)
def test_every_internal_link_in_a_chapter_resolves(path: Path):
    """A dead deep link is the ``PAGE_GATE.md`` sample-selector trap again.

    ``querySelector`` returns ``null``, the browser shows a blank page, and
    nothing anywhere says which chapter was pointing at nothing.
    """
    missing: list[str] = []
    for _number, line in _prose_lines(path.read_text(encoding="utf-8")):
        for target, _fragment in INTERNAL_LINK.findall(line):
            if not (WEB_HTML / target).is_file():
                missing.append(target)
    assert not missing, f"{path.name} links pages that do not exist: {missing}"


@pytest.mark.unit
@pytest.mark.parametrize("path", _chapter_pages(), ids=_chapter_id)
def test_every_chapter_page_links_its_stylesheet_and_renderer(path: Path):
    """The per-page link gotcha, enforced rather than remembered.

    Stylesheets and scripts are loaded by individual pages in this tree. A
    generated chapter page missing ``help.css`` renders the whole manual with
    browser defaults, and one missing ``help_page.js`` renders nothing at all
    but the holding line -- neither of which raises anything.
    """
    source = path.read_text(encoding="utf-8")
    assert "../css/help.css" in source, f"{path.name} does not link help.css"
    assert "../js/help_page.js" in source, (
        f"{path.name} does not link help_page.js, so its markdown is never "
        f"rendered and the page shows only its holding line"
    )
    assert sync.EMBED_OPEN in source, (
        f"{path.name} has no markdown embed, so there is nothing to render"
    )


@pytest.mark.unit
def test_the_index_lists_exactly_the_chapters_on_disk():
    """Self-counting in both directions.

    A chapter missing from the index is unreachable; a row in the index with
    no page behind it is a link to a blank screen. The generator makes both
    impossible, and this is what says so if it stops.
    """
    index = HELP_INDEX.read_text(encoding="utf-8")
    linked = re.findall(r'href="(help_[a-z0-9_]+\.html)"', index)
    expected = [p.name for p in _chapter_pages()]
    assert sorted(linked) == sorted(expected), (
        f"help.html links {sorted(linked)} but the tree holds {sorted(expected)}"
    )
    assert len(linked) == len(_chapters()), (
        f"help.html lists {len(linked)} chapters and docs/manual/ holds "
        f"{len(_chapters())}"
    )
    for target in linked:
        assert (WEB_HTML / target).is_file()


@pytest.mark.unit
def test_the_index_and_its_stylesheet_ship_together():
    """help.html is hand written, so its own ``<link>`` is not generated."""
    index = HELP_INDEX.read_text(encoding="utf-8")
    assert "../css/help.css" in index
    assert "../css/styles.css" in index


@pytest.mark.unit
def test_the_dashboard_offers_a_way_in():
    """A manual nothing links to is ``SHARED_SUBJECTS.md`` again (#428).

    That document is student-facing, 5,794 bytes, and reachable from no page
    in the app -- which is the whole reason this issue exists. A chapter set
    with no affordance would repeat it with more words.
    """
    dashboard = (WEB_HTML / "index.html").read_text(encoding="utf-8")
    assert 'href="help.html"' in dashboard, (
        "the dashboard does not link help.html, so the manual is reachable "
        "only by typing a URL the app has no bar for"
    )
    assert 'data-testid="dashboard-help-link"' in dashboard, (
        "the dashboard's help affordance has no data-testid, so no scenario "
        "can assert it is still there (#430 anchors on these)"
    )
    assert HELP_INDEX.is_file()


# --------------------------------------------------------------------------- #
# The sweeps are not vacuous
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_the_sweep_found_the_chapters():
    """A discovery-based check that discovers nothing passes.

    The floor is below the current count rather than at it, so adding a
    chapter does not edit this number -- the point is to catch a glob that
    stopped matching.
    """
    assert len(_chapters()) >= 2, f"only {len(_chapters())} chapters found"
    assert len(_chapter_pages()) == len(_chapters())


@pytest.mark.unit
def test_each_detector_fires_on_the_thing_it_forbids():
    """Negative control, one per construct, plus a positive control.

    Without this a detector broken by a regex typo would report every chapter
    clean and look exactly like a clean tree -- which is how the original
    ``test_capture.py`` pair passed while asserting something the
    architecture forbids.
    """
    assert "table" in unsupported_constructs(
        "| Marker | Meaning |\n|--------|---------|\n| a | b |\n"
    )
    assert "blockquote" in unsupported_constructs("> quoted\n")
    assert "image" in unsupported_constructs("![alt](shot.png)\n")
    assert "external link" in unsupported_constructs(
        "see [the site](https://example.com)\n"
    )
    assert "external link" in unsupported_constructs(
        "see [the site](HTTP://EXAMPLE.COM)\n"
    ), "the external-link detector is case sensitive"

    # A fenced block is not prose: a chapter showing an import file may well
    # contain a pipe or an angle bracket, and flagging those would make the
    # check noise.
    assert unsupported_constructs("```\n| not | a table |\n> not a quote\n```\n") == {}

    # Positive control: ordinary prose, a list and an internal link trip
    # nothing, or the check is simply failing on everything.
    assert unsupported_constructs(
        "# T\n\nProse with **bold** and `code`.\n\n- a list item\n"
        "\nsee [the first hour](help_the_first_hour.html)\n"
    ) == {}


@pytest.mark.unit
def test_the_renderer_declares_what_the_pages_call():
    """The generated pages call these by name; a rename breaks every chapter.

    ``initHelpChapter`` is the entry point the template relies on running on
    load, and ``renderHelpMarkdown`` is what the chapter guard above is a
    guard *about*. Neither is reachable from a markup check, and a missing
    function leaves the holding line on screen with no console error that
    anything here would see.
    """
    source = RENDERER.read_text(encoding="utf-8")
    for name in (
        "function renderHelpMarkdown(",
        "function initHelpChapter(",
        "function helpApplyHashTarget(",
        "function helpRenderInline(",
        "function helpEscapeHtml(",
        "function helpStripComments(",
    ):
        assert name in source, f"help_page.js no longer defines {name!r}"

    # `helpStripComments` is the whole reason a tour short form (#430) can be
    # a generator-only marker. Defined and never called, every chapter with a
    # block in it draws that block as visible prose -- measured, see the
    # function's own comment. The behaviour is asserted in the real engine by
    # `test_manual_renders_in_the_app.py`; this is what stops the call being
    # dropped while the function stays.
    #
    # THE CALL SITE IS PINNED LITERALLY, AND THE LOOSER VERSION WAS MEASURED TO
    # PASS WITH THE CALL DELETED. `source.count("helpStripComments") >= 2`
    # looks like it checks a definition plus a call; it does not, because the
    # module comment above names the function twice in prose, so the count is
    # already 2 with no call anywhere. Same mutant as the one recorded in
    # `test_efficiency_score_is_disabled.py`.
    assert "var lines = helpStripComments(" in source, (
        "helpStripComments is defined and renderHelpMarkdown no longer calls "
        "it. Every <!-- tour --> block in docs/manual/ would then render as a "
        "visible paragraph between a heading and its first sentence"
    )

    # The hash shim is defensive rather than load-bearing, and the function's
    # own docstring records the measurement: deleting this call leaves the
    # deep-link scenario green, because Chromium retries its own fragment
    # scroll after load and the chapter renders on DOMContentLoaded. This
    # assertion exists so the call cannot be dropped *silently* -- the cover it
    # buys only matters the day rendering becomes asynchronous, which is
    # exactly when nobody will be thinking about it.
    assert source.count("helpApplyHashTarget") >= 2, (
        "helpApplyHashTarget is defined and never called. Read its docstring "
        "before deleting it: it covers the case where rendering stops being "
        "synchronous, which no current test can see"
    )
