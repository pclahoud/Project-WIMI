#!/usr/bin/env python
"""Check that the subject-tree import guide's three copies are one document.

What this script does
---------------------
``docs/examples/subject_tree_import_format.md`` is the **single source**. Two
artifacts are generated from it and committed alongside it:

1. The ``<script type="text/markdown" id="import-help-source">`` block in
   ``src/web/html/tree_editor.html`` — the text the ❓ *Import Format Help*
   button renders. It must be the markdown file, verbatim.
2. ``docs/examples/subject_tree_import.schema.json`` — the JSON Schema, which
   is the fenced ``json`` block under the guide's ``## JSON Schema`` heading.

Run with no arguments to **check** (the CI gate). Run with ``--write`` to
**regenerate** both artifacts from the markdown.

Why the embed exists at all
---------------------------
The guide has to render in a PyInstaller build, where ``docs/`` is not shipped
and there is no filesystem read to fall back on. Embedding the text in the page
is what makes the modal identical in dev and frozen builds. That constraint is
real and is not what this script questions — what it removes is the *hand*
synchronisation, which was a code comment asking politely.

It had already failed. #61 taught the guide that ``root_nodes`` and
``subjects`` are both accepted and #62 taught it that sibling order is kept;
both landed in the HTML embed and neither reached ``docs/``, so the repo's copy
of the guide spent two commits describing an importer that no longer existed.
Every issue in the #63 / #64 / #69 cluster edits this guide, which is how a
two-line drift becomes a permanent one.

Why generate rather than diff
-----------------------------
A pure diff gate tells you the copies disagree and leaves you to reconcile them
by hand — which is the same manual step, just later and under time pressure.
Generating means there is only ever one thing to edit, and the gate's failure
message is a command that fixes it.

No allowlist, by design
-----------------------
``check_css_tokens.py`` carries a self-cleaning ``KNOWN_UNDEFINED`` because a
CSS token can be legitimately undefined for a while. Nothing here can be
legitimately out of sync: the artifacts are generated, so a difference is
always a missing ``--write``. There is therefore no exemption mechanism, which
is the strongest form of the self-cleaning property — an exemption that cannot
exist cannot go stale and re-hide the next drift.

Usage
-----
From the project root::

    python scripts/check_import_guide_sync.py            # check
    python scripts/check_import_guide_sync.py --write    # regenerate

Exit codes:

* ``0`` — the artifacts match the source (or, with ``--write``, now do).
* ``1`` — at least one artifact is out of sync (each reported with the first
  differing line).
* ``2`` — the source or a landmark inside it is missing or malformed.

Limitations
-----------
This script compares text. It does not parse the guide's JSON examples or check
them against the schema — ``tests/test_import_guide_sync.py`` does that, so the
gate itself stays stdlib-only, like the other ``scripts/`` gates.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# Paths and landmarks
# --------------------------------------------------------------------------- #

SOURCE = Path("docs") / "examples" / "subject_tree_import_format.md"
EMBED_HOST = Path("src") / "web" / "html" / "tree_editor.html"
SCHEMA_FILE = Path("docs") / "examples" / "subject_tree_import.schema.json"

# The opening tag of the embed. Matched literally — an attribute reordered by a
# future edit should fail loudly here rather than silently stop syncing.
EMBED_OPEN = '<script type="text/markdown" id="import-help-source">'
EMBED_CLOSE = "</script>"

# Indentation of the closing tag inside tree_editor.html, so a regenerated
# embed leaves the surrounding HTML formatted the way it was written.
EMBED_CLOSE_INDENT = "    "

# The heading the schema lives under, and the fence that opens it.
SCHEMA_HEADING = "## JSON Schema"
JSON_FENCE_OPEN = "```json\n"
FENCE_CLOSE = "\n```"


class GuideError(Exception):
    """A landmark this script needs is missing or malformed."""


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

def read_source(project_root: Path) -> str:
    """Return the guide's markdown, with trailing newlines normalised away.

    Trailing blank lines are stripped here so both generated artifacts are a
    deterministic function of the text and not of how an editor saved it.
    """
    path = project_root / SOURCE
    if not path.is_file():
        raise GuideError(f"source guide not found at {SOURCE}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise GuideError(f"{SOURCE} is empty")
    if EMBED_CLOSE in text:
        # An embedded `</script>` would close the script block early and spill
        # the rest of the guide into the page as markup.
        raise GuideError(
            f"{SOURCE} contains the literal text {EMBED_CLOSE!r}, which cannot "
            f"be embedded in an HTML script block"
        )
    return text.rstrip("\n")


def extract_embed(html: str) -> str:
    """Return the current embed body from ``tree_editor.html``.

    The body is everything between the opening tag and the closing
    ``</script>``, with the newline after the opening tag and the indentation
    before the closing tag removed — i.e. what should equal the markdown.
    """
    start = html.find(EMBED_OPEN)
    if start == -1:
        raise GuideError(
            f"{EMBED_HOST} has no {EMBED_OPEN!r} block — the import help modal "
            f"renders that block, so it cannot simply have moved"
        )
    body_start = start + len(EMBED_OPEN)
    end = html.find(EMBED_CLOSE, body_start)
    if end == -1:
        raise GuideError(f"{EMBED_HOST}: the import help block is never closed")
    body = html[body_start:end]
    if body.startswith("\n"):
        body = body[1:]
    return body.rstrip(" \t").rstrip("\n")


def extract_schema(markdown: str) -> str:
    """Return the JSON Schema fence's contents from the guide.

    The schema is the first ``json`` fence after the ``## JSON Schema``
    heading. Locating it by heading rather than by position keeps the guide
    free to grow more JSON examples above and below it.
    """
    heading = markdown.find(f"\n{SCHEMA_HEADING}\n")
    if heading == -1:
        raise GuideError(
            f"{SOURCE} has no {SCHEMA_HEADING!r} heading, so there is no schema "
            f"to publish"
        )
    fence = markdown.find(JSON_FENCE_OPEN, heading)
    if fence == -1:
        raise GuideError(
            f"{SOURCE}: no ```json block follows the {SCHEMA_HEADING!r} heading"
        )
    body_start = fence + len(JSON_FENCE_OPEN)
    end = markdown.find(FENCE_CLOSE, body_start)
    if end == -1:
        raise GuideError(f"{SOURCE}: the schema's ```json block is never closed")
    return markdown[body_start:end]


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def render_embed(html: str, markdown: str) -> str:
    """Return ``tree_editor.html`` with its embed replaced by ``markdown``."""
    start = html.find(EMBED_OPEN)
    if start == -1:
        raise GuideError(f"{EMBED_HOST} has no {EMBED_OPEN!r} block")
    body_start = start + len(EMBED_OPEN)
    end = html.find(EMBED_CLOSE, body_start)
    if end == -1:
        raise GuideError(f"{EMBED_HOST}: the import help block is never closed")
    return (
        html[:body_start]
        + "\n"
        + markdown
        + "\n"
        + EMBED_CLOSE_INDENT
        + html[end:]
    )


def render_schema_file(markdown: str) -> str:
    """Return the contents the published schema file should have."""
    return extract_schema(markdown) + "\n"


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #

def first_difference(expected: str, actual: str, label: str) -> str:
    """Return a short unified diff, or the empty string when they match."""
    if expected == actual:
        return ""
    diff = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=f"{label} (expected, from {SOURCE})",
        tofile=f"{label} (actual)",
        lineterm="",
        n=1,
    )
    lines = list(diff)
    head = lines[:30]
    if len(lines) > len(head):
        head.append(f"... and {len(lines) - len(head)} more diff lines")
    return "\n".join(head)


def audit(project_root: Path) -> dict[str, str]:
    """Return ``{artifact label: diff}`` for every artifact out of sync."""
    markdown = read_source(project_root)

    problems: dict[str, str] = {}

    html_path = project_root / EMBED_HOST
    if not html_path.is_file():
        raise GuideError(f"{EMBED_HOST} not found")
    html = html_path.read_text(encoding="utf-8")
    diff = first_difference(markdown, extract_embed(html), str(EMBED_HOST))
    if diff:
        problems[str(EMBED_HOST)] = diff

    expected_schema = render_schema_file(markdown)
    schema_path = project_root / SCHEMA_FILE
    actual_schema = (
        schema_path.read_text(encoding="utf-8") if schema_path.is_file() else ""
    )
    diff = first_difference(expected_schema, actual_schema, str(SCHEMA_FILE))
    if diff:
        problems[str(SCHEMA_FILE)] = diff

    return problems


def write(project_root: Path) -> list[str]:
    """Regenerate both artifacts. Returns the paths actually rewritten."""
    markdown = read_source(project_root)
    written: list[str] = []

    html_path = project_root / EMBED_HOST
    html = html_path.read_text(encoding="utf-8")
    updated = render_embed(html, markdown)
    if updated != html:
        html_path.write_text(updated, encoding="utf-8")
        written.append(str(EMBED_HOST))

    schema_path = project_root / SCHEMA_FILE
    expected_schema = render_schema_file(markdown)
    current = schema_path.read_text(encoding="utf-8") if schema_path.is_file() else None
    if current != expected_schema:
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(expected_schema, encoding="utf-8")
        written.append(str(SCHEMA_FILE))

    return written


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    """Check, or with ``--write`` regenerate, the guide's generated copies."""
    parser = argparse.ArgumentParser(
        description=(
            "Check (or regenerate) the copies of the subject-tree import guide "
            "generated from docs/examples/subject_tree_import_format.md."
        )
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate the HTML embed and the published JSON Schema",
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
                print("Already in sync — nothing to rewrite.")
            return 0

        problems = audit(project_root)
    except GuideError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:  # pragma: no cover — filesystem failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not problems:
        print(
            f"Import guide is in sync: {EMBED_HOST} and {SCHEMA_FILE} both "
            f"match {SOURCE}."
        )
        return 0

    print(
        f"FAIL: {len(problems)} generated copy/copies of the import guide are "
        f"out of sync with {SOURCE}.",
        file=sys.stderr,
    )
    for label in sorted(problems):
        print(f"\n--- {label} ---", file=sys.stderr)
        print(problems[label], file=sys.stderr)
    print(
        "\nFix: python scripts/check_import_guide_sync.py --write\n"
        "     (edit the markdown, never the generated copies)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
