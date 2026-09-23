#!/usr/bin/env python3
"""Fail if any first-party stylesheet uses the ``:empty`` pseudo-class.

Why this exists (#141)
----------------------
QtWebEngine 6.10 / Chromium 134 **stops re-invalidating ``:empty``**. An
element that gains its first child keeps the style it had while empty: the
computed ``display`` is never recalculated, the element renders at **zero
pixels**, and layout genuinely excludes it. ``getBoundingClientRect()``
returns zeros and the page does not grow.

The failure is silent and looks like a dead button. When it bit, the DOM node,
its children and live TinyMCE instances were all present and correct — only
the pixels were missing — so every test asserting DOM presence passed against
broken code. It cost:

* **#134** — "+ Add Note" appeared to do nothing, and the entry later held one
  empty note per invisible click.
* **#136** — selecting an error type or a subject rendered the chip at zero
  pixels, and the multi-parent context pill had no hit area at all, so every
  multi-parent subject silently took its canonical parent.

Four rules were live; three were already dead. None of it was reachable by any
test, because on the pinned stack (Chromium 130) the behaviour is correct.

The replacement
---------------
``:not(:has(*))`` — verified to invalidate correctly on **both** Chromium 130
and 134, in both directions. It is a drop-in wherever the container's children
are elements, which is true of every site this project had.

**It is not a universal substitute.** ``:empty`` is false for an element
containing *anything*, including a text node; ``:not(:has(*))`` only asks
whether there are element children. A container holding bare text is
"not empty" to the first and "has no elements" to the second. Two rules were
deleted rather than converted for exactly this reason — see #141.

Scope
-----
Vendored libraries under ``src/web/lib`` and ``src/web/js/lib`` are excluded:
TinyMCE ships ``:empty`` rules of its own and they are not ours to audit.

There is deliberately **no allowlist**. Every first-party use was removed in
the same commit that added this check, so an exemption list would have no
entries and nothing to go stale. If a genuine need for ``:empty`` ever
appears, the honest move is to reopen #141 with the case, not to add a
quiet exception here.

Usage
-----
::

    python scripts/check_css_empty_selector.py

Exit codes:

* ``0`` — no first-party ``:empty`` uses.
* ``1`` — at least one, listed with file and line.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOT = Path("src") / "web"

# Same exclusions as scripts/check_css_tokens.py, for the same reason.
EXCLUDED_DIRS = (
    Path("src") / "web" / "js" / "lib",
    Path("src") / "web" / "lib",
)

SCANNED_SUFFIXES = (".css", ".html")

# `:empty` as a pseudo-class, not as a substring of something longer and not
# inside `:not(:empty)`-style text we might add later. A bare occurrence is
# what we ban, so match the token and let the report show context.
EMPTY_RE = re.compile(r":empty\b")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def iter_scanned_files(project_root: Path) -> list[Path]:
    root = project_root / SCAN_ROOT
    if not root.is_dir():
        return []
    excluded = [project_root / d for d in EXCLUDED_DIRS]
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        if any(_is_within(path, ex) for ex in excluded):
            continue
        files.append(path)
    return sorted(files)


# CSS `/* ... */` and HTML `<!-- ... -->`, both able to span lines.
COMMENT_RE = re.compile(r"/\*.*?\*/|<!--.*?-->", re.DOTALL)


def strip_comments(text: str) -> str:
    """Blank out comment bodies, preserving newlines so line numbers hold.

    Without this the check fires on prose *about* `:empty` — including the
    comment in ``styles.css`` explaining why the token is banned. A gate that
    punishes documenting itself gets its documentation deleted, which is the
    opposite of what it is for.
    """
    def _blank(match: re.Match) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return COMMENT_RE.sub(_blank, text)


def find_uses(project_root: Path) -> list[tuple[Path, int, str]]:
    """Return ``(path, line_number, line_text)`` for every ``:empty`` use.

    Comments are stripped first; the reported line is the original text, so
    the message still shows what was written.
    """
    hits: list[tuple[Path, int, str]] = []
    for path in iter_scanned_files(project_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        original = text.splitlines()
        for lineno, line in enumerate(strip_comments(text).splitlines(), start=1):
            if EMPTY_RE.search(line):
                shown = original[lineno - 1].strip() if lineno <= len(original) else line
                hits.append((path, lineno, shown))
    return hits


def main() -> int:
    files = iter_scanned_files(PROJECT_ROOT)
    hits = find_uses(PROJECT_ROOT)

    if not hits:
        print(
            f"Scanned {len(files)} first-party files under {SCAN_ROOT}.\n"
            "OK: no `:empty` selectors."
        )
        return 0

    print(
        f"FAIL: `:empty` is not usable in this project (#141). "
        f"{len(hits)} use(s) found:\n",
        file=sys.stderr,
    )
    for path, lineno, line in hits:
        rel = path.relative_to(PROJECT_ROOT)
        print(f"  {rel}:{lineno}\n      {line}", file=sys.stderr)

    print(
        "\nQtWebEngine 6.10 / Chromium 134 does not re-invalidate `:empty`: an\n"
        "element that gains its first child keeps the style it had while empty\n"
        "and renders at ZERO PIXELS, with no error. It cost #134 and #136, and\n"
        "no test caught either because the pinned engine behaves correctly.\n"
        "\n"
        "Use `:not(:has(*))`, which invalidates correctly on both engines.\n"
        "\n"
        "Careful: the two are NOT equivalent. `:empty` is false for an element\n"
        "containing anything at all, including a text node; `:not(:has(*))`\n"
        "only asks about element children. If your container can hold bare\n"
        "text, neither selector is right and the state belongs in a class set\n"
        "by the code that populates it.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
