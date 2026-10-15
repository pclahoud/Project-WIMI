#!/usr/bin/env python
"""Check that the in-app manual's generated pages are the markdown chapters.

What this script does
---------------------
``docs/manual/NN_slug.md`` is the **single source** for every chapter of the
student manual (issue #428). Two kinds of artifact are generated from those
files and committed alongside them:

1. One page per chapter, ``src/web/html/help_<slug>.html``. The whole file is
   generated: the chapter's markdown is embedded verbatim in a
   ``<script type="text/markdown" id="help-chapter-source">`` block, with the
   title, the chapter number and the previous/next links written into the
   surrounding markup.
2. The chapter list inside ``src/web/html/help.html``, between the
   ``GENERATED CHAPTER LIST`` markers. ``help.html`` is otherwise hand
   written, the way ``tree_editor.html`` is.

Run with no arguments to **check** (the CI gate). Run with ``--write`` to
**regenerate** every artifact from the markdown.

Why the embed exists at all
---------------------------
The same reason ``check_import_guide_sync.py`` gives, and it is the measured
one: a PyInstaller build ships no ``docs/``, and pages load from ``file://``
where Chromium treats each origin as opaque, so there is no ``fetch()`` to
fall back on either. Embedding the text in the page is what makes a chapter
identical in development and in a frozen build.

Why one page per chapter
------------------------
``docs/examples/subject_tree_import_format.md`` is 45,813 bytes and is
embedded whole in ``tree_editor.html``. That works at one document. Twenty
chapters at that density is most of a megabyte of markdown in one HTML file,
re-rendered on every open. Per-chapter pages keep each open proportional to
the chapter, make chapter-to-chapter navigation a plain link, and let a deep
link from the app name a place (``help_weights.html#rescaling``) rather than
a position in one enormous document.

Why generate rather than diff
-----------------------------
A diff gate tells you two copies disagree and leaves the reconciliation to a
human, which is the same manual step moved later. Generating means there is
only one thing to edit and the gate's failure message is the command that
fixes it.

No allowlist, by design
-----------------------
Nothing here can be legitimately out of sync: every artifact is generated, so
a difference is always a missing ``--write``. There is therefore no exemption
mechanism, which is the strongest form of the self-cleaning property -- an
exemption that cannot exist cannot go stale and re-hide the next drift. The
same reasoning, in the same words, as the import guide's gate.

The named-section hook (#430)
-----------------------------
``extract_section`` returns the body of a named ``##`` section of a chapter.
It is what produces each chapter's one-line summary for the index, so it is
load-bearing here rather than speculative.

The tour's short forms (#430)
-----------------------------
A third artifact: ``src/web/js/tour_steps.js``, the step text for the
first-run tour, collected out of the chapters and grouped by page.

**Why a marker and not a named section.** #430's own measurement is that a
manual section runs 239 to 1,713 characters and an overlay panel cannot carry
one, so a step needs an *authored* short form rather than a slice of prose. A
short form is a compression of a rule, so a second copy of that rule exists by
nature; what stops the two drifting is that it lives two lines from the
section it compresses, and that this gate regenerates the artifact from it.

The marker is an HTML comment, which is **invisible only because
``help_page.js`` strips one**. That was measured rather than assumed: before
``helpStripComments`` existed, a comment planted in chapter 1 reached a real
QtWebEngine as an ordinary visible paragraph between a heading and its first
sentence (``innertext_has_marker: true``, 15 paragraphs where the chapter has
14), because nothing in the renderer matched it and the paragraph branch
escaped its angle brackets. The alternative -- a dedicated ``##`` section the
page generator leaves out -- was rejected because it would end the property
``render_page`` is built on and ``test_manual_code_block_renders.py`` leans
on: that the embed *is* the chapter, verbatim.

Shape, and every part of it is checked::

    <!-- tour
    page: tree-editor
    anchor: the weight beside a subject's name in the tree
    text: A weight is a share of the whole exam at any depth, never a share of
      the subject above it.
    -->

``page`` is one of ``TOUR_PAGES``; ``anchor`` says in words what the step
points at, because the ``data-testid`` anchoring is #430's own work; ``text``
is the short form.

A step whose target depends on the page's state is a **fork** (#620), written
as two more keys that always come together::

    anchor: dashboard-create-first-exam
    fork: has-exams
    fork-anchor: exam-card

When the page's ``has-exams`` predicate is true the runner points at
``fork-anchor``, otherwise at ``anchor``, with one shared text. ``fork`` must
name an entry in ``TOUR_FORKS`` on the step's own page, so a typo fails here
rather than silently at runtime. Both anchors of a fork are identifiers, which
is what the runner resolves (``data-tour-anchor``, then ``data-testid``). The
generated step carries ``fork`` and ``fork_anchor`` only when the block has
them, so a chapter without a fork generates exactly what it did before. The chapter, its title, the enclosing section and a deep
link into it are **derived**, so a step cannot name the wrong chapter and a
section renamed in the markdown moves its own link.

Several blocks on one page may share an ``anchor``: they are **slides** of
one tour step, shown in the order they are written, each keeping its own
section link (#682). They must sit in one chapter and none may fork.

Usage
-----
From the project root::

    python scripts/check_manual_sync.py            # check
    python scripts/check_manual_sync.py --write    # regenerate

Exit codes:

* ``0`` -- every artifact matches the chapters (or, with ``--write``, now
  does).
* ``1`` -- at least one artifact is out of sync, or a generated page exists
  that no chapter claims.
* ``2`` -- a chapter is missing, malformed, or missing a landmark this script
  needs.

Limitations
-----------
This script compares text. Whether a chapter's markdown stays inside what the
help page's renderer actually supports is ``tests/test_manual_chapters.py``'s
job, so the gate itself stays stdlib-only like the other ``scripts/`` gates.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# Paths and landmarks
# --------------------------------------------------------------------------- #

MANUAL_DIR = Path("docs") / "manual"
HTML_DIR = Path("src") / "web" / "html"
INDEX_PAGE = HTML_DIR / "help.html"

# The tour's step text (#430). A .js file assigning a global, not JSON under
# docs/, for the same measured reason the chapters are embedded rather than
# fetched: a PyInstaller build ships no docs/, and a file:// page in Chromium
# has an opaque origin so it cannot fetch a sibling. This is the only form the
# tour can actually consume.
TOUR_ARTIFACT = Path("src") / "web" / "js" / "tour_steps.js"
TOUR_GLOBAL = "window.WIMI_TOUR_STEPS"

# Orientation steps (#682, owner 2026-10-10: "both kinds of step").
#
# A step in a CHAPTER teaches a RULE and its text is generated from the
# section it sits under, so the chapter and the tip cannot disagree. A step in
# THIS file only names a control -- "this is the date filter" -- and has no
# section to be generated from.
#
# **The kind is derived from which source the block sits in**, exactly as
# `chapter`, `section`, `link` and `chapter_title` are derived from where a
# block sits. There is no `kind:` field and no second opener: a field can be
# omitted or mistyped, and a file cannot.
#
# WHY A SUBDIRECTORY RATHER THAN `docs/manual/tour_orientation.md`. Both
# enumerations here use non-recursive `iterdir()` -- `read_chapters` and the
# orphan-page sweep -- and a directory has no `.md` suffix, so this path is
# invisible to chapter discovery with no change to either. A SIBLING would be
# picked up by `read_chapters` and refused by `CHAPTER_NAME`, and relaxing
# that check to let it through would cost the thing the check is for: today
# `3_weights.md` or `30-weights.md` fails loudly, and with a skip a typo'd
# chapter becomes a silently ignored file that generates nothing.
#
# The file is OPTIONAL. Absent means no orientation steps, which is the state
# this landed in.
ORIENTATION_SOURCE = MANUAL_DIR / "tour" / "orientation.md"

# ``NN_slug.md``. The number orders the chapters and nothing else -- the
# number a reader sees is the chapter's position in that order, so inserting
# a chapter later does not leave a visible gap, and no URL carries a number
# that could go stale.
CHAPTER_NAME = re.compile(r"^(\d{2})_([a-z0-9]+(?:_[a-z0-9]+)*)\.md$")

# Which generated pages this script owns. ``help.html`` has no underscore and
# is deliberately outside the pattern: it is hand written apart from one
# block.
CHAPTER_PAGE = re.compile(r"^help_([a-z0-9_]+)\.html$")

EMBED_OPEN = '<script type="text/markdown" id="help-chapter-source">'
EMBED_CLOSE = "</script>"

INDEX_OPEN = "<!-- GENERATED CHAPTER LIST - do not edit by hand (#428). -->"
INDEX_CLOSE = "<!-- END GENERATED CHAPTER LIST -->"
INDEX_INDENT = "            "

# The section whose body becomes the chapter's summary on the index page.
SUMMARY_HEADING = "## In short"

# A summary is escaped into the index, not rendered, so inline markdown there
# would appear literally. Refused with a sentence rather than shipped wrong.
SUMMARY_MARKUP = re.compile(r"`|\*\*|\[[^\]]*\]\(")

# --------------------------------------------------------------------------- #
# The tour's short forms (#430)
# --------------------------------------------------------------------------- #

#: The pages that have a tour, in the order a student meets them. These are the
#: logical route names from ``wimi_test/routes.py``; they are restated here
#: rather than imported because every ``scripts/`` gate is stdlib-only, and
#: ``tests/test_manual_tour_steps.py`` asserts the two lists agree.
TOUR_PAGES = (
    "dashboard",
    "exam-wizard",
    "tree-editor",
    "session-setup",
    "entry-form",
    "entry-browser",
    "analytics",
    "calendar",
    "settings",
)

TOUR_OPEN = "<!-- tour"
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
TOUR_KEYS = ("page", "anchor", "text")

#: Optional keys, accepted only as a pair (#620's step fork, #430).
TOUR_FORK_KEYS = ("fork", "fork-anchor")

#: The predicates a fork may name, each with the one page that defines it. The
#: runner asks the page for the predicate's value; the page computes it once,
#: where it already decides the same thing (the dashboard records the value it
#: hands applyHeroState), so the step and the screen cannot disagree (#313).
TOUR_FORKS = {
    "has-exams": "dashboard",
}

#: What the runner resolves: a data-tour-anchor or data-testid value.
TOUR_IDENTIFIER = re.compile(r"^[a-z0-9-]+$")

#: A step is one or two sentences. The floor catches a block whose ``text:``
#: never got written; the ceiling is the whole point of this pass -- #430
#: measured manual sections at 239-1,713 characters and a panel that size
#: covers the thing it points at on the 1130x689 viewport this project
#: measures against. Neither bound is a style preference.
TOUR_TEXT_MIN = 60
TOUR_TEXT_MAX = 340

#: The floor for an ORIENTATION step (#682). The rule-step floor of 60 cannot
#: apply here, and the reason is in the error it raises: "under the floor it is
#: a label rather than a rule". **An orientation step IS a label** -- "Narrow
#: the list to a date range." is 32 characters and correct -- so inheriting 60
#: would refuse exactly what the owner's decision asks for.
#:
#: What survives of the floor's purpose is the constants comment above: catch a
#: block whose ``text:`` never got written. 15 does that and nothing more.
#:
#: **It is chosen to be permissive, not measured.** No corpus of orientation
#: text exists yet; the first real one -- #682's sweep of every meaningful
#: control -- is what should set this. Revisit it then rather than defending
#: the number.
ORIENTATION_TEXT_MIN = 15
TOUR_ANCHOR_MAX = 90

#: A line inside a tour block that would open a markdown block, or that carries
#: a construct ``tests/test_manual_chapters.py`` forbids. The renderer strips
#: the block, so none of these would ever be *drawn* -- but the chapter sweeps
#: read the raw markdown, so such a line makes an unrelated test fail for an
#: unrelated-looking reason. Refused here, where the message can say why.
TOUR_BLOCK_LINE = re.compile(r"^\s*(?:[-*] +\S|\d+\. +\S|#{1,6} +|```|-{3,}\s*$|>)")

#: Inline markdown in a step. #430 renders the artifact as data; nothing turns
#: a backtick or a link into markup there, so it would reach a student
#: literally. Same rule, same reason, as ``SUMMARY_MARKUP``.
TOUR_MARKUP = re.compile(r"`|\*\*|\[[^\]]*\]\(|<[a-zA-Z/!]")


class ManualError(Exception):
    """A chapter is malformed, or a landmark this script needs is missing."""


class Chapter:
    """One chapter: its source, its generated page, and what the index needs.

    Deliberately a plain class rather than a ``dataclass``. Every test of a
    ``scripts/`` gate imports it by path with ``spec_from_file_location``,
    which leaves the module out of ``sys.modules`` -- and ``dataclass`` reads
    ``sys.modules[cls.__module__].__dict__`` while deciding whether a field is
    ``KW_ONLY``, so the decorator raises ``AttributeError`` at import time.
    That is a collection error in a file that has not run a line yet, which is
    an expensive way to find out; a plain class costs nothing and cannot.
    """

    __slots__ = (
        "order", "slug", "title", "summary", "markdown", "source", "page",
        "tour",
    )

    def __init__(
        self,
        order: str,        # the two-digit filename prefix, for sorting only
        slug: str,         # ``weights`` -> ``help_weights.html``
        title: str,        # the text of the source's single level-1 heading
        summary: str,      # the body of its ``## In short`` section
        markdown: str,     # the whole file, trailing newlines normalised away
        source: Path,      # relative to the project root
        page: Path,        # relative to the project root
        tour: list,        # the tour steps authored in it, in document order
    ) -> None:
        self.order = order
        self.slug = slug
        self.title = title
        self.summary = summary
        self.markdown = markdown
        self.source = source
        self.page = page
        self.tour = tour


# --------------------------------------------------------------------------- #
# Reading and validating the source
# --------------------------------------------------------------------------- #

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


def headings(markdown: str) -> list[tuple[int, int, str]]:
    """``(level, line number, text)`` for every ATX heading outside a fence."""
    out: list[tuple[int, int, str]] = []
    for number, line in _prose_lines(markdown):
        match = re.match(r"^(#{1,6}) +(.*\S)\s*$", line)
        if match:
            out.append((len(match.group(1)), number, match.group(2)))
    return out


def extract_section(markdown: str, heading: str) -> str:
    """Return the body of the named section, or raise ``ManualError``.

    The body is everything between ``heading`` and the next heading of the
    same level or higher, with surrounding blank lines removed. Locating a
    section by its heading rather than by position is what lets a chapter
    grow around it -- and it is the hook #430's tour steps come through, so
    it is deliberately a general function and not an inlined search for one
    string.
    """
    level = len(heading) - len(heading.lstrip("#"))
    lines = markdown.split("\n")
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break
    if start is None:
        raise ManualError(f"no {heading!r} section")

    end = len(lines)
    for index in range(start, len(lines)):
        match = re.match(r"^(#{1,6}) +\S", lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break

    body = "\n".join(lines[start:end]).strip("\n")
    if not body.strip():
        raise ManualError(f"the {heading!r} section is empty")
    return body


def slugify(text: str) -> str:
    """The heading id ``help_page.js`` gives this heading.

    A deliberate transcription of ``helpSlugify`` rather than an independent
    scheme: the id is what a deep link names, so a second convention here
    would produce links that resolve to nothing. The scenario sweep asserts
    every generated link resolves in the real engine, which is what makes this
    a mirror rather than a hope.
    """
    out = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return out.strip("-")


def heading_sections(markdown: str) -> list[tuple[int, str, str]]:
    """``(line number, heading text, id)`` for every heading that renders.

    The chapter's single ``# `` title is skipped, because ``renderHelpMarkdown``
    drops it (the page's markup carries the h1) and therefore never spends an
    id on it. The duplicate suffix is ``uniqueId``'s, for the same reason
    ``slugify`` is a mirror.
    """
    used: dict[str, bool] = {}
    out: list[tuple[int, str, str]] = []
    for level, number, text in headings(markdown):
        if level == 1:
            continue
        base = slugify(text) or "section"
        candidate = base
        counter = 2
        while used.get(candidate):
            candidate = f"{base}-{counter}"
            counter += 1
        used[candidate] = True
        out.append((number, text, candidate))
    return out


def _tour_blocks(markdown: str, label: str) -> list[tuple[int, list[str]]]:
    """``(line number of the opener, body lines)`` for every tour block.

    Also the one place an unterminated HTML comment is caught, in any chapter,
    tour block or not. That matters now that ``help_page.js`` strips comments:
    an unclosed ``<!--`` swallows every line after it with no error anywhere,
    which is the symptomless class this gate exists for.
    """
    lines = markdown.split("\n")
    blocks: list[tuple[int, list[str]]] = []
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if in_fence:
            index += 1
            continue

        stripped = line.strip()
        if stripped == TOUR_OPEN:
            opener = index + 1  # one-based, the number a reader sees
            if index > 0 and lines[index - 1].strip() != "":
                raise ManualError(
                    f"{label}:{opener}: a tour block needs a blank line "
                    f"before it. The renderer blanks a comment's lines rather "
                    f"than removing them, so a block butted against prose or a "
                    f"bullet changes what the chapter renders"
                )
            body: list[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != COMMENT_CLOSE:
                if COMMENT_CLOSE in lines[index]:
                    raise ManualError(
                        f"{label}:{index + 1}: a tour block's closing "
                        f"{COMMENT_CLOSE!r} is on a line with other text. Put "
                        f"it on a line of its own"
                    )
                if COMMENT_OPEN in lines[index]:
                    raise ManualError(
                        f"{label}:{index + 1}: a tour block is never closed -- "
                        f"a second {COMMENT_OPEN!r} appears inside it"
                    )
                body.append(lines[index])
                index += 1
            if index >= len(lines):
                raise ManualError(
                    f"{label}: the tour block opened at line {opener} is never "
                    f"closed with {COMMENT_CLOSE!r}. help_page.js would blank "
                    f"every line after it and the chapter would render as "
                    f"nothing"
                )
            if index + 1 < len(lines) and lines[index + 1].strip() != "":
                raise ManualError(
                    f"{label}:{index + 2}: a tour block needs a blank line "
                    f"after it, for the same reason it needs one before"
                )
            blocks.append((opener, body))
            index += 1
            continue

        if COMMENT_OPEN in line:
            # Some other HTML comment. Allowed, but it has to close, and on
            # this line or a later one -- see the docstring.
            rest = "\n".join(lines[index:])
            after = rest.split(COMMENT_OPEN, 1)[1]
            if COMMENT_CLOSE not in after:
                raise ManualError(
                    f"{label}:{index + 1}: an HTML comment is never closed. "
                    f"help_page.js strips comments, so everything after this "
                    f"line would render as nothing, with no error anywhere"
                )
        index += 1
    return blocks


def _parse_tour_block(
    body: list[str], line_number: int, label: str,
    text_min: int = TOUR_TEXT_MIN,
) -> dict[str, str]:
    """Turn one block's lines into ``{page, anchor, text}`` or raise.

    ``text_min`` is the floor on ``text:``. It is a parameter because an
    orientation step is a label and a rule step is not -- see
    ``ORIENTATION_TEXT_MIN``. Everything else is checked identically for both
    kinds, deliberately: one parser, so a block cannot be valid in a chapter
    and invalid in the orientation file for a reason nobody can see.
    """
    fields: dict[str, str] = {}
    order: list[str] = []
    for offset, raw in enumerate(body):
        if not raw.strip():
            raise ManualError(
                f"{label}:{line_number + offset + 1}: a tour block has a blank "
                f"line in it. Keys and their continuations are contiguous, so "
                f"a blank line means a key has been lost"
            )
        if TOUR_BLOCK_LINE.match(raw) or "|" in raw:
            raise ManualError(
                f"{label}:{line_number + offset + 1}: {raw.strip()!r} would "
                f"read as a list item, heading, rule, table or quote to the "
                f"chapter sweeps, which read the markdown rather than the "
                f"rendered page. Write a tour block as plain sentences"
            )
        # A field name is flush left and a continuation is indented. That is
        # not tidiness: without it a wrapped sentence beginning "subject: the
        # name of..." would be read as a field, and the block would be
        # refused for a reason a reader cannot see.
        match = re.match(r"^([\w-]+): ?(.*)$", raw)
        if match and match.group(1) in TOUR_KEYS + TOUR_FORK_KEYS:
            key = match.group(1)
            if key in fields:
                raise ManualError(
                    f"{label}:{line_number + offset + 1}: {key!r} is given "
                    f"twice in one tour block"
                )
            fields[key] = match.group(2).strip()
            order.append(key)
            continue
        if match and match.group(1) not in TOUR_KEYS + TOUR_FORK_KEYS:
            raise ManualError(
                f"{label}:{line_number + offset + 1}: {match.group(1)!r} is "
                f"not a tour field. The fields are "
                f"{', '.join(TOUR_KEYS)}, plus {' and '.join(TOUR_FORK_KEYS)} "
                f"together for a fork; everything else about a step is "
                f"derived from where the block sits"
            )
        if not order:
            raise ManualError(
                f"{label}:{line_number + offset + 1}: a tour block opens with "
                f"{raw.strip()!r} rather than a field. The first line is "
                f"'page: <one of {', '.join(TOUR_PAGES)}>'"
            )
        if raw[:1] not in (" ", "\t"):
            raise ManualError(
                f"{label}:{line_number + offset + 1}: {raw.strip()!r} is "
                f"flush left but is not a field, so it reads as the wrapped "
                f"remainder of {order[-1]!r}. Indent a continuation line"
            )
        fields[order[-1]] = f"{fields[order[-1]]} {raw.strip()}".strip()

    missing = [key for key in TOUR_KEYS if not fields.get(key)]
    if missing:
        raise ManualError(
            f"{label}:{line_number}: a tour block is missing "
            f"{', '.join(repr(m) for m in missing)}. All of "
            f"{', '.join(TOUR_KEYS)} are required"
        )

    if fields["page"] not in TOUR_PAGES:
        raise ManualError(
            f"{label}:{line_number}: {fields['page']!r} is not a page with a "
            f"tour. The pages are {', '.join(TOUR_PAGES)} -- a name not on "
            f"that list would create a ninth page that nothing ever shows"
        )
    for key in ("anchor", "text"):
        found = TOUR_MARKUP.search(fields[key])
        if found is not None:
            raise ManualError(
                f"{label}:{line_number}: a tour block's {key!r} uses markup "
                f"({found.group(0)!r}). #430 renders a step as text, so write "
                f"it as plain prose -- the chapter beside it is where emphasis "
                f"and links belong"
            )
    if not (text_min <= len(fields["text"]) <= TOUR_TEXT_MAX):
        raise ManualError(
            f"{label}:{line_number}: a step's text is {len(fields['text'])} "
            f"characters; the range is {text_min}-{TOUR_TEXT_MAX}. Under the "
            f"floor the text never got written; over the ceiling the panel "
            f"covers the thing it points at"
        )
    if len(fields["anchor"]) > TOUR_ANCHOR_MAX:
        raise ManualError(
            f"{label}:{line_number}: a step's anchor is "
            f"{len(fields['anchor'])} characters; the ceiling is "
            f"{TOUR_ANCHOR_MAX}. An anchor names one thing on screen"
        )
    if not fields["text"].endswith((".", "?")):
        raise ManualError(
            f"{label}:{line_number}: a step's text does not end in a full "
            f"stop. A truncated short form reads as a complete one"
        )
    _check_fork(fields, line_number, label)
    return fields


def _check_fork(fields: dict[str, str], line_number: int, label: str) -> None:
    """A fork is both keys or neither, names a known predicate on its own page,
    and forks between two identifiers (#620, #430)."""
    present = [k for k in TOUR_FORK_KEYS if k in fields]
    if not present:
        return
    if len(present) != len(TOUR_FORK_KEYS):
        missing = [k for k in TOUR_FORK_KEYS if k not in fields]
        raise ManualError(
            f"{label}:{line_number}: a fork needs {' and '.join(TOUR_FORK_KEYS)} "
            f"together; {', '.join(repr(m) for m in missing)} is missing"
        )
    fork = fields["fork"]
    if TOUR_FORKS.get(fork) != fields["page"]:
        known = ", ".join(f"{name} ({page})" for name, page in TOUR_FORKS.items())
        raise ManualError(
            f"{label}:{line_number}: {fork!r} is not a fork predicate on the "
            f"{fields['page']} page. The predicates are: {known}. A name the "
            f"page does not define would never be true"
        )
    for key in ("anchor", "fork-anchor"):
        if not TOUR_IDENTIFIER.match(fields[key]):
            raise ManualError(
                f"{label}:{line_number}: a forked step's {key!r} is "
                f"{fields[key]!r}, which is not an anchor identifier "
                f"(lowercase letters, digits and hyphens: a data-tour-anchor "
                f"or data-testid value). The runner cannot resolve prose"
            )


def read_tour_steps(markdown: str, slug: str, title: str, label: str) -> list[dict]:
    """Every tour step in one chapter, in the order it appears.

    The chapter, its title, the enclosing section and the deep link are
    derived here rather than written in the block, so a step cannot name a
    chapter it is not in and a renamed section carries its own link with it.
    """
    sections = heading_sections(markdown)
    steps: list[dict] = []
    for line_number, body in _tour_blocks(markdown, label):
        fields = _parse_tour_block(body, line_number, label)
        enclosing = [s for s in sections if s[0] < line_number]
        if not enclosing:
            raise ManualError(
                f"{label}:{line_number}: a tour block sits above the "
                f"chapter's first section, so there is no section for its "
                f"link to name. Put it under the heading it compresses"
            )
        _, section_text, section_id = enclosing[-1]
        steps.append({
            "page": fields["page"],
            "anchor": fields["anchor"],
            "text": fields["text"],
            "chapter": slug,
            "chapter_title": title,
            "section": section_text,
            "link": f"help_{slug}.html#{section_id}",
        })
        # Only when present, so a chapter with no fork generates exactly what
        # it did before the keys existed.
        if "fork" in fields:
            steps[-1]["fork"] = fields["fork"]
            steps[-1]["fork_anchor"] = fields["fork-anchor"]
    return steps


def _read_chapter(project_root: Path, path: Path) -> Chapter:
    """Validate one chapter file and return what generation needs from it."""
    name_match = CHAPTER_NAME.match(path.name)
    if name_match is None:
        raise ManualError(
            f"{MANUAL_DIR / path.name}: a chapter file is named "
            f"NN_slug.md (two digits, underscore, lowercase slug). The number "
            f"orders the chapters; the slug becomes help_<slug>.html"
        )
    order, slug = name_match.group(1), name_match.group(2)

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ManualError(f"{MANUAL_DIR / path.name} is empty")
    if EMBED_CLOSE in text:
        # An embedded `</script>` would close the block early and spill the
        # rest of the chapter into the page as markup.
        raise ManualError(
            f"{MANUAL_DIR / path.name} contains the literal text "
            f"{EMBED_CLOSE!r}, which cannot be embedded in an HTML script "
            f"block"
        )
    markdown = text.rstrip("\n")

    found = headings(markdown)
    tops = [h for h in found if h[0] == 1]
    if len(tops) != 1:
        raise ManualError(
            f"{MANUAL_DIR / path.name}: expected exactly one '# ' heading "
            f"(the chapter title), found {len(tops)}"
        )
    if found[0][0] != 1:
        raise ManualError(
            f"{MANUAL_DIR / path.name}: the first heading is h{found[0][0]} at "
            f"line {found[0][1]}; a chapter opens with its '# ' title"
        )
    title = tops[0][2]

    # The rendered body is injected under the page's markup h1, so a chapter
    # whose levels skip produces an out-of-order outline that no markup sweep
    # can see (#317's lesson, one layer down).
    previous = found[0][0]
    for level, number, text_ in found:
        if level > previous + 1:
            raise ManualError(
                f"{MANUAL_DIR / path.name}:{number}: heading level jumps from "
                f"h{previous} to h{level} ({text_!r}). The chapter renders "
                f"into the page's outline, so a skipped level is a real "
                f"outline defect"
            )
        previous = level

    try:
        summary = extract_section(markdown, SUMMARY_HEADING)
    except ManualError as exc:
        raise ManualError(
            f"{MANUAL_DIR / path.name}: {exc}. Every chapter carries a "
            f"'{SUMMARY_HEADING}' section; its body is the sentence the index "
            f"page shows, and it is also the worked example of the "
            f"named-section extraction the first-run tour needs (#430)"
        ) from exc
    if "\n\n" in summary:
        raise ManualError(
            f"{MANUAL_DIR / path.name}: the '{SUMMARY_HEADING}' section is "
            f"more than one paragraph. The index shows it whole, so it has to "
            f"be short enough to read in a list"
        )
    found_markup = SUMMARY_MARKUP.search(summary)
    if found_markup is not None:
        raise ManualError(
            f"{MANUAL_DIR / path.name}: the '{SUMMARY_HEADING}' section uses "
            f"markdown ({found_markup.group(0)!r}). The index escapes that "
            f"text rather than rendering it -- a second renderer here is a "
            f"second thing to drift -- so write the summary as plain prose"
        )

    return Chapter(
        order=order,
        slug=slug,
        title=title,
        summary=" ".join(summary.split()),
        markdown=markdown,
        source=MANUAL_DIR / path.name,
        page=HTML_DIR / f"help_{slug}.html",
        tour=read_tour_steps(
            markdown, slug, title, (MANUAL_DIR / path.name).as_posix()
        ),
    )


def read_chapters(project_root: Path) -> list[Chapter]:
    """Every chapter, in reading order. Raises on anything malformed."""
    directory = project_root / MANUAL_DIR
    if not directory.is_dir():
        raise ManualError(f"no chapters directory at {MANUAL_DIR}")

    files = sorted(p for p in directory.iterdir() if p.suffix == ".md")
    if not files:
        raise ManualError(f"{MANUAL_DIR} holds no .md chapters")

    chapters = [_read_chapter(project_root, path) for path in files]

    by_order: dict[str, Chapter] = {}
    by_slug: dict[str, Chapter] = {}
    for chapter in chapters:
        clash = by_order.get(chapter.order)
        if clash is not None:
            raise ManualError(
                f"{chapter.source} and {clash.source} share the chapter "
                f"number {chapter.order}, so their reading order depends on "
                f"their slugs"
            )
        by_order[chapter.order] = chapter
        clash = by_slug.get(chapter.slug)
        if clash is not None:
            raise ManualError(
                f"{chapter.source} and {clash.source} share the slug "
                f"{chapter.slug!r}, so they generate the same page"
            )
        by_slug[chapter.slug] = chapter

    return chapters


# --------------------------------------------------------------------------- #
# Rendering the generated artifacts
# --------------------------------------------------------------------------- #

def escape(text: str) -> str:
    """HTML-escape text going into generated markup."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title_attr} - WIMI manual</title>
    <link rel="stylesheet" href="../css/styles.css">
    <link rel="stylesheet" href="../css/help.css">
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script src="../js/api/_bridge.js"></script>
    <script src="../js/api/_loader.js"></script>
    <script src="../js/themes.js"></script>
    <script src="../js/event_bus.js"></script>
    <script src="../js/plugin_loader.js"></script>
</head>
<!--
  GENERATED PAGE - DO NOT EDIT BY HAND (issue #428).

  The single source is {source}. Edit that file, then run:

      python scripts/check_manual_sync.py --write

  to regenerate this page and the chapter list in help.html. The same script
  with no arguments is a CI gate.

  This page is deliberately NOT page-gated (#114/#127). A gate exists to stop
  a page accepting input it cannot keep; a chapter has no form state to lose
  and waits on no bridge call, so `inert` here would buy nothing and cost the
  whole subtree its place in the accessibility tree while the markdown
  rendered. entry_detail.html is the other ungated page, for the same kind of
  reason. If a future chapter page grows something that can be typed into,
  read docs/guides/PAGE_GATE.md before adding one.
-->
<body>
    <div class="help-page">
        <header class="help-header">
            <a href="help.html" class="help-back-link" data-testid="help-chapter-back">
                <span class="help-back-arrow" aria-hidden="true">&#8592;</span>
                <span>WIMI manual</span>
            </a>
        </header>
        <main class="help-main">
            <article class="help-article">
                <p class="help-eyebrow">Chapter {number}</p>
                <h1 class="help-title" data-testid="help-chapter-title">{title_html}</h1>
                <div class="help-body" id="help-chapter-body" data-testid="help-chapter-body">
                    <p class="help-body-holding">Opening this chapter&hellip;</p>
                </div>
            </article>
{nav}
        </main>
    </div>
    {embed_open}
{markdown}
    </script>
    <script src="../js/help_page.js"></script>
</body>
</html>
"""


def render_nav(chapters: list[Chapter], index: int) -> str:
    """The previous/next block for one chapter, or '' when there is neither.

    A missing neighbour is omitted rather than drawn disabled: an affordance
    that cannot be pressed is #174's rule in another shape, and a one-chapter
    manual gets no navigation block at all.
    """
    previous = chapters[index - 1] if index > 0 else None
    following = chapters[index + 1] if index + 1 < len(chapters) else None
    if previous is None and following is None:
        return ""

    rows = [
        '            <nav class="help-chapter-nav" aria-label="Chapters"'
        ' data-testid="help-chapter-nav">'
    ]
    if previous is not None:
        rows.append(
            '                <a class="help-chapter-nav-link'
            ' help-chapter-nav-link--prev"'
            f' href="help_{previous.slug}.html"'
            ' data-testid="help-chapter-prev">'
        )
        rows.append(
            '                    <span class="help-chapter-nav-label">'
            "Previous</span>"
        )
        rows.append(
            '                    <span class="help-chapter-nav-title">'
            f"{escape(previous.title)}</span>"
        )
        rows.append("                </a>")
    if following is not None:
        rows.append(
            '                <a class="help-chapter-nav-link'
            ' help-chapter-nav-link--next"'
            f' href="help_{following.slug}.html"'
            ' data-testid="help-chapter-next">'
        )
        rows.append(
            '                    <span class="help-chapter-nav-label">'
            "Next</span>"
        )
        rows.append(
            '                    <span class="help-chapter-nav-title">'
            f"{escape(following.title)}</span>"
        )
        rows.append("                </a>")
    rows.append("            </nav>")
    return "\n".join(rows)


def render_page(chapters: list[Chapter], index: int) -> str:
    """Return the whole contents a chapter's generated page should have."""
    chapter = chapters[index]
    return PAGE_TEMPLATE.format(
        title_attr=escape(chapter.title),
        title_html=escape(chapter.title),
        source=chapter.source.as_posix(),
        number=index + 1,
        nav=render_nav(chapters, index),
        embed_open=EMBED_OPEN,
        markdown=chapter.markdown,
    )


def render_index_block(chapters: list[Chapter]) -> str:
    """Return the chapter list that belongs between help.html's markers."""
    rows: list[str] = [
        f'{INDEX_INDENT}<ol class="help-chapter-list"'
        ' data-testid="help-chapter-list">'
    ]
    for index, chapter in enumerate(chapters, start=1):
        rows.extend(
            [
                f'{INDEX_INDENT}    <li class="help-chapter-item">',
                f'{INDEX_INDENT}        <a class="help-chapter-link"'
                f' href="help_{chapter.slug}.html"'
                f' data-testid="help-chapter-link-{chapter.slug}">',
                f'{INDEX_INDENT}            '
                f'<span class="help-chapter-item-number"'
                f' aria-hidden="true">{index}</span>',
                f'{INDEX_INDENT}            '
                f'<span class="help-chapter-item-text">',
                f'{INDEX_INDENT}                '
                f'<span class="help-chapter-item-title">'
                f"{escape(chapter.title)}</span>",
                f'{INDEX_INDENT}                '
                f'<span class="help-chapter-item-summary">'
                f"{escape(chapter.summary)}</span>",
                f"{INDEX_INDENT}            </span>",
                f"{INDEX_INDENT}        </a>",
                f"{INDEX_INDENT}    </li>",
            ]
        )
    rows.append(f"{INDEX_INDENT}</ol>")
    return "\n".join(rows)


TOUR_TEMPLATE = """/* GENERATED FILE - DO NOT EDIT BY HAND (issues #430, #428).
 *
 * The first-run tour's step text, collected out of the manual's chapters by
 * `scripts/check_manual_sync.py`. The single source for every string below is
 * a `<!-- tour ... -->` block in `docs/manual/NN_slug.md`, sitting beside the
 * section whose rule it compresses. To change a step, edit that block and run:
 *
 *     python scripts/check_manual_sync.py --write
 *
 * The same script with no arguments is a CI gate, so this file cannot drift
 * from the chapters. There is no allowlist: a difference is always a missing
 * --write and never a legitimate state.
 *
 * Why the step text is authored rather than sliced out of a chapter: #430
 * measured manual sections at 239-1,713 characters, and on the 1130x689
 * viewport this project measures against, a panel that size covers the thing
 * it is pointing at. So a step carries an authored short form -- the rule's
 * substance in one or two sentences, never a label a student clicks past.
 *
 * Each step carries:
 *
 *   page           one of %(pages)s
 *   anchor         what the step points at, in words. The data-testid
 *                  anchoring is #430's own work; this is the brief for it.
 *   text           the short form.
 *   chapter        the chapter slug, so the page is help_<chapter>.html
 *   chapter_title  that chapter's title
 *   section        the heading the block sits under
 *   link           a deep link to that section, for the step's "read more"
 *
 * Everything but page, anchor and text is DERIVED from where the block sits,
 * so a step cannot name a chapter it is not in, and a section renamed in the
 * markdown moves its own link with it.
 *
 * Steps are grouped by page and run in chapter order within a page. A page
 * with no steps is absent rather than empty: #430 reads this as
 * `(%(global)s || {})[page] || []`, and an empty array drawn as a tour is the
 * two-empty-boxes-and-a-gap mistake in another file.
 *
 * %(count)d step(s) across %(page_count)d page(s).
 */
%(global)s = %(data)s;
"""


def read_orientation(project_root: Path) -> list[dict]:
    """Every orientation step, in file order. ``[]`` when the file is absent.

    Reuses ``_tour_blocks`` and ``_parse_tour_block`` rather than parsing
    again: one parser for both kinds, so a block cannot be valid in a chapter
    and invalid here for a reason nobody can see.

    What it does NOT do is derive ``section``, ``link``, ``chapter`` or
    ``chapter_title``. There is no section to derive them from, which is the
    whole difference between the two kinds, and `tour.js` already draws *Read
    more* only `if (step.link)` -- so a step with none renders without a
    change to the runner.
    """
    source = project_root / ORIENTATION_SOURCE
    if not source.is_file():
        return []

    label = ORIENTATION_SOURCE.as_posix()
    markdown = source.read_text(encoding="utf-8")
    steps: list[dict] = []
    for line_number, body in _tour_blocks(markdown, label):
        fields = _parse_tour_block(
            body, line_number, label, text_min=ORIENTATION_TEXT_MIN)
        # A fork pairs an anchor with a registered runtime predicate, which is
        # a chapter-level idea and has no orientation case. Refused rather
        # than quietly accepted, because accepting it would emit a step whose
        # fork nothing has ever exercised.
        if "fork" in fields or "fork-anchor" in fields:
            raise ManualError(
                f"{label}:{line_number}: a fork belongs to a chapter step. "
                f"An orientation block takes {', '.join(TOUR_KEYS)} and "
                f"nothing else"
            )
        steps.append({
            "page": fields["page"],
            "anchor": fields["anchor"],
            "text": fields["text"],
        })
    return steps


def _refuse_orientation_on_a_rule_anchor(
    chapters: list[Chapter], orientation: list[dict]
) -> None:
    """An orientation step may not share an anchor with a chapter's step.

    If a control has a rule, the rule owns it: the chapter's text is generated
    and cannot drift from the manual, and an orientation block on the same
    anchor is either saying the same thing twice or contradicting it. Which of
    those it is cannot be told apart mechanically, so neither is allowed.

    The error names the chapter, because the fix is usually to improve the
    rule step's text rather than to drop the orientation block -- the
    collision is a signal that the chapter already covers the control and
    says it badly.
    """
    owned: dict[tuple[str, str], str] = {}
    for chapter in chapters:
        for step in chapter.tour:
            owned[(step["page"], step["anchor"].lower())] = (
                chapter.source.as_posix())
    for step in orientation:
        where = owned.get((step["page"], step["anchor"].lower()))
        if where is not None:
            raise ManualError(
                f"{ORIENTATION_SOURCE.as_posix()}: an orientation block "
                f"points at {step['anchor']!r} on {step['page']!r}, which "
                f"{where} already has a step for. If a control has a rule, "
                f"the rule owns it -- fix that chapter's wording rather than "
                f"naming the control twice"
            )


def render_tour_artifact(
    chapters: list[Chapter], orientation: list[dict] | None = None
) -> str:
    """Return the whole contents ``src/web/js/tour_steps.js`` should have.

    ``orientation`` is ``read_orientation``'s output (#682) and defaults to
    none, so every existing caller and test keeps its behaviour. Orientation
    steps are appended per page AFTER the chapters' own, which is deliberate:
    a rule comes before the label of the thing it is a rule about, and the
    runtime sort reorders them by screen position anyway.
    """
    orientation = list(orientation or ())
    _refuse_orientation_on_a_rule_anchor(chapters, orientation)
    by_page: dict[str, list[dict]] = {}
    # (page, anchor) -> (chapter source, whether that step forks)
    seen: dict[tuple[str, str], tuple[str, bool]] = {}
    for chapter in chapters:
        source = chapter.source.as_posix()
        for step in chapter.tour:
            key = (step["page"], step["anchor"].lower())
            clash = seen.get(key)
            # Steps sharing an anchor are ONE tour step shown as slides, in
            # the order their blocks appear (#682, owner 2026-10-10: the
            # question bank pane is explained by several slides on the entry
            # form's button). The runner keys a step by page and anchor, so
            # the slides share one identity and are recorded seen together.
            # Two things stay refused, each because nobody would choose its
            # result: slides spread over two chapters, whose order would be
            # the chapters' filename order; and a fork on a shared anchor,
            # where a predicate could move one slide off the others.
            if clash is not None:
                where, forked = clash
                if where != source:
                    raise ManualError(
                        f"{source}: two tour steps on {step['page']!r} both "
                        f"point at {step['anchor']!r} (the other is in "
                        f"{where}). Steps on one anchor are slides of one "
                        f"step, in the order they are written, so they must "
                        f"be written in one chapter"
                    )
                if forked or step.get("fork"):
                    raise ManualError(
                        f"{source}: two tour steps on {step['page']!r} both "
                        f"point at {step['anchor']!r} and one of them forks. "
                        f"Slides of one step share one target, so none of "
                        f"them may fork"
                    )
            else:
                seen[key] = (source, bool(step.get("fork")))
            by_page.setdefault(step["page"], []).append(step)

    for step in orientation:
        by_page.setdefault(step["page"], []).append(step)

    ordered = {page: by_page[page] for page in TOUR_PAGES if page in by_page}
    # ensure_ascii, deliberately: this file is loaded by a <script src> from a
    # file:// page, where the document's charset is the only thing that would
    # decide how a raw en dash is decoded. An escape cannot be mis-decoded.
    data = json.dumps(ordered, indent=2, ensure_ascii=True, sort_keys=False)
    return TOUR_TEMPLATE % {
        "pages": ", ".join(TOUR_PAGES),
        "global": TOUR_GLOBAL,
        "data": data,
        "count": sum(len(steps) for steps in ordered.values()),
        "page_count": len(ordered),
    }


def extract_index_block(html: str) -> str:
    """Return the current chapter list from ``help.html``."""
    start = html.find(INDEX_OPEN)
    if start == -1:
        raise ManualError(
            f"{INDEX_PAGE} has no {INDEX_OPEN!r} marker -- the chapter list is "
            f"generated into that block, so it cannot simply have moved"
        )
    body_start = start + len(INDEX_OPEN)
    end = html.find(INDEX_CLOSE, body_start)
    if end == -1:
        raise ManualError(
            f"{INDEX_PAGE}: the generated chapter list is never closed with "
            f"{INDEX_CLOSE!r}"
        )
    return html[body_start:end].strip("\n").rstrip(" \t")


def render_index(html: str, chapters: list[Chapter]) -> str:
    """Return ``help.html`` with its chapter list replaced."""
    start = html.find(INDEX_OPEN)
    if start == -1:
        raise ManualError(f"{INDEX_PAGE} has no {INDEX_OPEN!r} marker")
    body_start = start + len(INDEX_OPEN)
    end = html.find(INDEX_CLOSE, body_start)
    if end == -1:
        raise ManualError(f"{INDEX_PAGE}: the chapter list is never closed")
    return (
        html[:body_start]
        + "\n"
        + render_index_block(chapters)
        + "\n"
        + INDEX_INDENT
        + html[end:]
    )


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #

def first_difference(expected: str, actual: str, label: str, source: str) -> str:
    """Return a short unified diff, or the empty string when they match."""
    if expected == actual:
        return ""
    diff = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=f"{label} (expected, from {source})",
        tofile=f"{label} (actual)",
        lineterm="",
        n=1,
    )
    lines = list(diff)
    head = lines[:30]
    if len(lines) > len(head):
        head.append(f"... and {len(lines) - len(head)} more diff lines")
    return "\n".join(head)


def orphan_pages(project_root: Path, chapters: list[Chapter]) -> list[Path]:
    """Generated chapter pages that no chapter in ``docs/manual`` claims.

    A deleted or renamed chapter leaves its page behind, still linked from
    nowhere but still reachable by URL and still saying it is part of the
    manual. The import guide's gate has no equivalent because its artifacts
    are two fixed paths; here the set of artifacts is itself derived, so a
    stale one is a state ``--write`` has to be able to clear.
    """
    claimed = {chapter.page.name for chapter in chapters}
    directory = project_root / HTML_DIR
    return sorted(
        HTML_DIR / path.name
        for path in directory.iterdir()
        if CHAPTER_PAGE.match(path.name) and path.name not in claimed
    )


def audit(project_root: Path) -> dict[str, str]:
    """Return ``{artifact label: problem}`` for everything out of sync."""
    chapters = read_chapters(project_root)
    problems: dict[str, str] = {}

    for index, chapter in enumerate(chapters):
        path = project_root / chapter.page
        actual = path.read_text(encoding="utf-8") if path.is_file() else ""
        diff = first_difference(
            render_page(chapters, index),
            actual,
            str(chapter.page),
            chapter.source.as_posix(),
        )
        if diff:
            problems[str(chapter.page)] = diff

    index_path = project_root / INDEX_PAGE
    if not index_path.is_file():
        raise ManualError(f"{INDEX_PAGE} not found")
    html = index_path.read_text(encoding="utf-8")
    diff = first_difference(
        render_index_block(chapters),
        extract_index_block(html),
        str(INDEX_PAGE),
        MANUAL_DIR.as_posix(),
    )
    if diff:
        problems[str(INDEX_PAGE)] = diff

    tour_path = project_root / TOUR_ARTIFACT
    actual_tour = tour_path.read_text(encoding="utf-8") if tour_path.is_file() else ""
    diff = first_difference(
        render_tour_artifact(chapters, read_orientation(project_root)),
        actual_tour,
        str(TOUR_ARTIFACT),
        MANUAL_DIR.as_posix(),
    )
    if diff:
        problems[str(TOUR_ARTIFACT)] = diff

    for orphan in orphan_pages(project_root, chapters):
        problems[str(orphan)] = (
            f"{orphan} is a generated chapter page, but no chapter in "
            f"{MANUAL_DIR.as_posix()} generates it. --write deletes it."
        )

    return problems


def write(project_root: Path) -> list[str]:
    """Regenerate every artifact. Returns what was actually changed."""
    chapters = read_chapters(project_root)
    written: list[str] = []

    for index, chapter in enumerate(chapters):
        path = project_root / chapter.page
        expected = render_page(chapters, index)
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != expected:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
            written.append(str(chapter.page))

    index_path = project_root / INDEX_PAGE
    html = index_path.read_text(encoding="utf-8")
    updated = render_index(html, chapters)
    if updated != html:
        index_path.write_text(updated, encoding="utf-8")
        written.append(str(INDEX_PAGE))

    tour_path = project_root / TOUR_ARTIFACT
    expected_tour = render_tour_artifact(
        chapters, read_orientation(project_root))
    current_tour = (
        tour_path.read_text(encoding="utf-8") if tour_path.is_file() else None
    )
    if current_tour != expected_tour:
        tour_path.parent.mkdir(parents=True, exist_ok=True)
        tour_path.write_text(expected_tour, encoding="utf-8")
        written.append(str(TOUR_ARTIFACT))

    for orphan in orphan_pages(project_root, chapters):
        (project_root / orphan).unlink()
        written.append(f"{orphan} (removed - no chapter generates it)")

    return written


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    """Check, or with ``--write`` regenerate, the manual's generated pages."""
    parser = argparse.ArgumentParser(
        description=(
            "Check (or regenerate) the help pages generated from the "
            "markdown chapters in docs/manual/."
        )
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate every chapter page and help.html's chapter list",
    )
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parent.parent

    try:
        if args.write:
            written = write(project_root)
            if written:
                for path in written:
                    print(f"Rewrote {path}")
            else:
                print("Already in sync - nothing to rewrite.")
            return 0

        problems = audit(project_root)
    except ManualError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:  # pragma: no cover - filesystem failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not problems:
        chapters = read_chapters(project_root)
        steps = sum(len(chapter.tour) for chapter in chapters)
        print(
            f"Manual is in sync: {len(chapters)} chapter(s) in "
            f"{MANUAL_DIR.as_posix()}, their pages, {INDEX_PAGE} and "
            f"{TOUR_ARTIFACT} ({steps} tour step(s)) all match."
        )
        return 0

    print(
        f"FAIL: {len(problems)} generated manual artifact(s) are out of sync "
        f"with {MANUAL_DIR.as_posix()}.",
        file=sys.stderr,
    )
    for label in sorted(problems):
        print(f"\n--- {label} ---", file=sys.stderr)
        print(problems[label], file=sys.stderr)
    print(
        "\nFix: python scripts/check_manual_sync.py --write\n"
        "     (edit the markdown in docs/manual/, never the generated pages)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
