#!/usr/bin/env python
"""Check that every CSS custom property a stylesheet names is defined somewhere.

What this script does
---------------------
Walks every ``*.css``, ``*.js`` and ``*.html`` file under ``src/web/`` (excluding
the vendored ``src/web/js/lib/`` and ``src/web/lib/`` trees), collects the set of
custom properties the project *defines*, then reports every ``var()`` naming a
token that is defined nowhere.

Two findings, one cause
-----------------------
A token defined nowhere is reported in either of the two forms it can appear
in. Same half-landed rename; only the symptom differs.

* ``var(--x)`` — **broken now.** Invalid at computed-value time. The browser
  does not warn, does not log, and does not fall back to the property's
  cascaded value: it discards the declaration. An inherited property (``color``)
  silently drops to the inherited value; everything else drops to its *initial*
  value — ``padding: var(--spacing-md)`` computes to ``0px``.
* ``var(--x, fallback)`` — **dead code, and usually a theme bug.** Perfectly
  valid, so nothing complains anywhere: the fallback simply wins every time and
  the token half never does anything at all. When the fallback is a hardcoded
  colour the declaration cannot follow the palette, so it paints a light-theme
  value in every dark theme while every neighbouring rule moves.

The second form is **not** reported for merely having a fallback.
``var(--space-md, 12px)`` is legitimate and deliberate, and the several hundred
such uses in this tree are silent. It is reported only when the token it names
is defined nowhere in the project, which makes the fallback unconditional *by
construction*. That distinction is the whole reason this half of the check can
exist without being noise: a fallback guarding a token that might be absent in
some context is good practice; a fallback guarding a token that does not exist
is a rename that only half landed.

The failure is silent either way, which is why it has been filed four times:

* #76 — ``--color-danger`` used in ``entry.css``/``tree.css``, defined nowhere
  (the palette's red is ``--color-error``).
* #81 — nine more tokens across 43 declarations, 32 of them the whole spacing
  system of ``aliases.css`` (``--spacing-md`` for the real ``--space-md``), so
  the alias manager rendered with no padding, no margins and no gaps at all.
* #97 — the *other* half of the same rename: ``--color-border`` and
  ``--font-size-base`` used **with** a hardcoded fallback, so six borders were
  pinned to a near-white hairline in every dark theme. #81's audit correctly
  did not flag them, because it only looked at the no-fallback form — which is
  precisely why this second check now exists.
* #102 — the complete remainder of that family: 21 tokens across 31
  declarations, of which 18 tokens / 28 declarations were repointed at the
  palette and three remain allowlisted below as a design question, not a
  rename.

Why #97 in particular took four filings to notice: ``styles.css`` sets
``--border-color: var(--color-gray-200)`` and ``--color-gray-200`` is
``#e2e8f0`` — the exact hex ``entry.css`` hardcoded as its fallback. In the
default light theme the broken declaration and the correct one were the *same
colour*, so the bug was invisible anywhere anybody was looking.

Every undefined token so far has been a near-miss of a token that does exist.
Nothing in the build, the test suite or the browser console noticed any of it.
This script is the thing that notices.

Repoint, do not define
----------------------
When this script flags a token, the fix is almost always to **repoint the use at
the real token**, not to define the missing name. Two reasons, both learned the
hard way:

* ``themes.js`` overrides the palette by writing *inline* custom properties onto
  the root element (``_wimiApplyThemeVariables``), so a theme only reaches names
  its dictionaries list. A second token defined statically in ``styles.css``
  could not be themed at all — that is the #76 reasoning for refusing a
  ``--color-danger`` alongside ``--color-error``.
* The same applies to the spacing scale: the ``density`` preference rewrites
  ``--space-sm``/``-md``/``-lg``/``-xl`` at runtime (``themes.js``,
  ``settings.js``). A static ``--spacing-md: 1rem`` alias would have looked
  correct and then quietly ignored the user's density setting forever.

"Could not be themed at all" is precise about the *default* case and not about
every case. ``_wimiApplyThemeVariables`` clears the **union** of every name any
dictionary lists before applying the chosen theme, so a new token defined in
``styles.css`` *and* listed by the themes that must differ is themed correctly,
and falls through to the ``:root`` value in the ones that do not list it. #110
took that route for the three toast ``-dark`` slabs, having measured it rather
than reasoned about it. It is still the exception: reach for it only when no
existing token says what you mean, and say in the definition what the token
means when the name stops being accurate.

What counts as a definition
---------------------------
* A CSS declaration — ``--token: value`` — anywhere in a ``.css`` file or in an
  inline ``style=`` attribute or ``<style>`` block in an ``.html`` file.
* A key in a ``themes.js`` theme dictionary — ``'--token': '#fff'``. Same
  ``--token:`` shape, so the same pattern catches it.
* A ``setProperty('--token', value)`` call in any scanned ``.js``/``.html``.

What counts as a use
--------------------
Both ``var(--token)`` and ``var(--token, fallback)``, reported separately —
see "Two findings, one cause" above. Neither is reported while ``--token`` is
defined somewhere, so a fallback on a real token is never mentioned.

Allowlists
----------
``KNOWN_UNDEFINED`` (no-fallback form) and ``KNOWN_DEAD_FALLBACK`` (fallback
form) carry tokens that are undefined on purpose or are being fixed elsewhere,
each with a reason. Both are **self-cleaning**: an entry that no longer matches
any undefined use is itself reported as a failure, so a stale exemption cannot
sit there quietly re-hiding the next bug.

They are deliberately two dicts rather than one keyed by token. An exemption
written for the mild form must not silence the severe one: allowlisting
``--color-surface`` because its fallback uses are tracked in #102 should not
also hide the day somebody writes a bare ``var(--color-surface)`` and has the
declaration thrown away.

Usage
-----
Manual run from the project root::

    python scripts/check_css_tokens.py

Exit codes:

* ``0`` — every ``var()`` names a token that is defined somewhere.
* ``1`` — at least one undefined token in either form (each printed with every
  ``file:line`` that uses it), or at least one stale allowlist entry.
* ``2`` — unexpected error (e.g. the scan root is missing).

Limitations
-----------
* Definitions are collected globally, not per-page. ``src/web/css/`` stylesheets
  are linked by individual HTML pages (see CLAUDE.md, "Per-page CSS link
  gotcha"), so a token defined in a stylesheet a given page does not link is
  still counted as defined here. That is a deliberate scope choice: this script
  catches *nowhere*-defined tokens, which is the bug that has actually shipped
  twice. Per-page reachability is a different, much noisier check.
* Runtime-injected plugin CSS (``app_data/plugins/``) is not scanned — it is
  untracked user data, not repo source.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple


# Directories scanned, relative to the project root.
SCAN_ROOT = Path("src") / "web"

# Vendored third-party bundles (D3, Fuse.js, TinyMCE, KaTeX). Deliberately
# tracked in-repo (CLAUDE.md, "Dependencies") but not ours to audit: they
# define and use their own tokens under their own naming conventions.
EXCLUDED_DIRS = (
    Path("src") / "web" / "js" / "lib",
    Path("src") / "web" / "lib",
)

SCANNED_SUFFIXES = (".css", ".js", ".html")


# A custom property being *defined*: `--token:`.
#
# Catches a CSS declaration (`--space-md: 1rem`), a quoted key in a themes.js
# theme dictionary (`'--text-primary': '#f8fafc'`) and an HTML inline style
# (`style="--x: 3"`) with one pattern, since all three are `--name` followed by
# a colon.
#
# The optional quote before the colon is load-bearing, not cosmetic: a JS object
# key closes its quote *between* the name and the colon (`'--text-primary':`),
# so without it every theme dictionary in themes.js is silently skipped. That
# gap is invisible on the real tree — every token those dictionaries list is
# also declared in styles.css — which is exactly why it is covered by a test.
#
# The negative lookbehind keeps `var(--x)` from ever matching: a use is preceded
# by `(` or `,` plus optional space, never by the start of a declaration.
#
# Known, accepted false positive: a JS ternary over two property-name strings
# (`cond ? '--a' : '--b'`) reads as defining `--a`. Over-collecting a definition
# can only cost a missed report, never a false failure, and no such expression
# exists in the tree.
DEFINITION_RE = re.compile(r"""(?<![\w-])(--[A-Za-z0-9_-]+)['"`]?\s*:""")

# `setProperty('--token', ...)` — themes.js and settings.js write the palette
# and the density scale this way, and those are real definitions.
SET_PROPERTY_RE = re.compile(
    r"""setProperty\s*\(\s*['"`](--[A-Za-z0-9_-]+)['"`]"""
)

# A custom property being *used with no fallback*: `var(--token)` exactly.
USE_NO_FALLBACK_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)")

# A custom property being *used with a fallback*: `var(--token, …)`.
#
# Matching stops at the comma, so it is indifferent to what the fallback is --
# a hex, a keyword, or another whole `var()`. Nesting therefore costs nothing:
# `var(--a, var(--b, #ccc))` yields `--a` here and `--b` on the next match,
# which is what you want, because both names are equally capable of being dead.
#
# This pattern alone says nothing about whether a use is a bug. Only its
# intersection with "defined nowhere" does -- see the module docstring.
USE_WITH_FALLBACK_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*,")


# --------------------------------------------------------------------------- #
# Known-undefined allowlist
# --------------------------------------------------------------------------- #

# Tokens that are allowed to be undefined, each mapped to the reason.
#
# Add an entry ONLY for a token that is undefined on purpose or is already being
# fixed elsewhere — never to quiet a real finding. Entries are self-cleaning:
# `main()` fails on any entry that no longer matches an undefined use, so the
# next person to run the script is told to delete it rather than inheriting a
# silent hole.
KNOWN_UNDEFINED: dict[str, str] = {
    # Empty by design. #81's two `settings.css` exemptions were retired when #90
    # landed those renames in the same batch — the self-cleaning check reported
    # them stale on the merged tree, which is exactly what it is for.
}


# Tokens allowed to be undefined *when used with a fallback*, each mapped to the
# reason. Same rules and same self-cleaning behaviour as `KNOWN_UNDEFINED`, and
# deliberately a separate dict — see "Allowlists" in the module docstring.
KNOWN_DEAD_FALLBACK: dict[str, str] = {
    # Empty by design. The last three entries were #102's remainder —
    # `--color-success-dark` / `--color-warning-dark` / `--color-error-dark`,
    # the solid toast backgrounds — parked here because the fix was a design
    # decision rather than a rename. #110 answered it: the three are now real
    # tokens defined at `:root` in styles.css and overridden in the two theme
    # dictionaries that invert `--color-white`, so the fallbacks are gone and
    # these lines went with them in the same commit.
    #
    # Note that this is a *defined* token, not a repoint, which is the one
    # thing "Repoint, do not define" above tells you not to reach for. It is
    # allowed here because there is no existing token that says what it says:
    # `--color-success` is the wrong colour on a solid slab (white-on-green
    # falls to ~2:1), and #76's objection — that a static token cannot be
    # themed — does not apply once the name is listed in a theme dictionary.
    # `_wimiApplyThemeVariables` clears the union of every themed name before
    # applying, so listing it in the two themes that must differ is enough and
    # the other four fall through to `:root`. Do not read this as the rule
    # relaxing; read it as the exception #110 argued for and measured.
}



# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #

def iter_scanned_files(project_root: Path) -> list[Path]:
    """Return every file under ``src/web/`` this script audits, sorted.

    Filters to :data:`SCANNED_SUFFIXES` and drops anything inside
    :data:`EXCLUDED_DIRS`.
    """
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


def _is_within(path: Path, parent: Path) -> bool:
    """Return True if `path` is inside `parent`."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def find_definitions(source: str) -> set[str]:
    """Return every custom property `source` defines.

    Covers CSS declarations, quoted theme-dictionary keys and inline HTML
    styles (all the ``--token:`` shape) plus ``setProperty('--token', …)``.
    """
    names = set(DEFINITION_RE.findall(source))
    names.update(SET_PROPERTY_RE.findall(source))
    return names


def find_uses(source: str) -> list[tuple[str, int]]:
    """Return ``(token, line_number)`` for every no-fallback ``var(--token)``.

    ``var(--token, fallback)`` is not matched here; :func:`find_fallback_uses`
    collects that form separately, because the two have different severities
    and different remedies.
    """
    return _scan(source, USE_NO_FALLBACK_RE)


def find_fallback_uses(source: str) -> list[tuple[str, int]]:
    """Return ``(token, line_number)`` for every ``var(--token, fallback)``.

    A use collected here is only a finding once the token turns out to be
    defined nowhere; on its own, a fallback is good practice.
    """
    return _scan(source, USE_WITH_FALLBACK_RE)


def _scan(source: str, pattern: "re.Pattern[str]") -> list[tuple[str, int]]:
    """Return ``(token, line_number)`` for every match of ``pattern``."""
    uses: list[tuple[str, int]] = []
    for match in pattern.finditer(source):
        line_no = source.count("\n", 0, match.start()) + 1
        uses.append((match.group(1), line_no))
    return uses


class AuditResult(NamedTuple):
    """Everything one scan of the tree found.

    ``undefined`` and ``dead_fallback`` each map a token that is defined
    nowhere to the sorted ``path:line`` locations that use it — in the
    no-fallback and the fallback form respectively. A token can appear in both.
    """

    undefined: dict[str, list[str]]
    dead_fallback: dict[str, list[str]]
    files_scanned: int
    definition_count: int
    use_count: int
    fallback_use_count: int


def audit(project_root: Path) -> AuditResult:
    """Scan the project and return the undefined-token report."""
    files = iter_scanned_files(project_root)

    defined: set[str] = set()
    sources: list[tuple[Path, str]] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"WARN: could not read {path}: {exc}", file=sys.stderr)
            continue
        sources.append((path, source))
        defined.update(find_definitions(source))

    # Two passes: every definition anywhere counts, so uses can only be judged
    # once the whole project has been read.
    bare: dict[str, list[str]] = defaultdict(list)
    fallback: dict[str, list[str]] = defaultdict(list)
    use_count = fallback_use_count = 0

    for path, source in sources:
        rel = path.relative_to(project_root)
        for token, line_no in find_uses(source):
            use_count += 1
            if token not in defined:
                bare[token].append(f"{rel}:{line_no}")
        for token, line_no in find_fallback_uses(source):
            fallback_use_count += 1
            if token not in defined:
                fallback[token].append(f"{rel}:{line_no}")

    return AuditResult(
        undefined=_sorted_locations(bare),
        dead_fallback=_sorted_locations(fallback),
        files_scanned=len(sources),
        definition_count=len(defined),
        use_count=use_count,
        fallback_use_count=fallback_use_count,
    )


def _sorted_locations(found: dict[str, list[str]]) -> dict[str, list[str]]:
    """Sort each token's locations by path, then numerically by line."""
    return {
        token: sorted(locations, key=_location_sort_key)
        for token, locations in found.items()
    }


def _location_sort_key(location: str) -> tuple[str, int]:
    """Sort ``path:line`` strings by path, then numerically by line."""
    file_part, _, line_part = location.rpartition(":")
    try:
        return (file_part, int(line_part))
    except ValueError:
        return (location, 0)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def _split(found: dict[str, list[str]], allowlist: dict[str, str]) -> tuple[dict, dict, list]:
    """Partition a finding into (reported, allowlisted, stale allowlist entries)."""
    reported = {t: locs for t, locs in found.items() if t not in allowlist}
    allowed = {t: locs for t, locs in found.items() if t in allowlist}
    stale = sorted(set(allowlist) - set(found))
    return reported, allowed, stale


def _print_allowed(allowed: dict, allowlist: dict[str, str], heading: str) -> None:
    """List the allowlisted tokens and why each is tolerated."""
    if not allowed:
        return
    print()
    print(heading)
    for token in sorted(allowed):
        print(f"  {token} — {len(allowed[token])} use(s) — {allowlist[token]}")


def _print_reported(reported: dict, heading: str) -> None:
    """Print every offending token with every file:line that uses it."""
    if not reported:
        return
    print()
    print(heading)
    print()
    for token in sorted(reported):
        print(f"  {token} — {len(reported[token])} declaration(s):")
        for location in reported[token]:
            print(f"      {location}")
        print()


def _print_stale(stale: list, allowlist: dict[str, str], name: str) -> None:
    """Report allowlist entries that no longer match anything."""
    if not stale:
        return
    print(f"Stale {name} entries (token is no longer undefined —")
    print("delete it from scripts/check_css_tokens.py):")
    for token in stale:
        print(f"  {token} — {allowlist[token]}")
    print()


def main() -> int:
    """Scan ``src/web/``, print a summary, and fail on undefined tokens.

    Returns ``0`` when clean, ``1`` on undefined tokens in either form or a
    stale allowlist entry, ``2`` on unexpected error.
    """
    try:
        project_root = Path(__file__).parent.parent

        if not (project_root / SCAN_ROOT).is_dir():
            print(
                f"ERROR: scan root not found at {project_root / SCAN_ROOT}",
                file=sys.stderr,
            )
            return 2

        result = audit(project_root)

        if result.files_scanned == 0:
            print(f"ERROR: no files to scan under {SCAN_ROOT}", file=sys.stderr)
            return 2

        bare_reported, bare_allowed, bare_stale = _split(
            result.undefined, KNOWN_UNDEFINED
        )
        fb_reported, fb_allowed, fb_stale = _split(
            result.dead_fallback, KNOWN_DEAD_FALLBACK
        )

        print(
            f"Scanned {result.files_scanned} files under {SCAN_ROOT}, "
            f"found {result.definition_count} defined custom properties, "
            f"{result.use_count} no-fallback var() uses "
            f"and {result.fallback_use_count} var() uses with a fallback."
        )

        _print_allowed(bare_allowed, KNOWN_UNDEFINED, "Known-undefined (allowlisted):")
        _print_allowed(
            fb_allowed, KNOWN_DEAD_FALLBACK, "Known dead fallbacks (allowlisted):"
        )

        reported = bool(bare_reported) or bool(fb_reported)
        stale = bool(bare_stale) or bool(fb_stale)

        if not reported and not stale:
            allowed_total = len(bare_allowed) + len(fb_allowed)
            print(
                f"OK: every var() names a defined token "
                f"({allowed_total} allowlisted)"
            )
            return 0

        _print_reported(
            bare_reported, "Undefined custom properties used with no fallback:"
        )
        _print_reported(
            fb_reported,
            "Undefined custom properties used with a dead fallback (the fallback\n"
            "always wins, so the token half is dead code — repoint it or inline it):",
        )

        _print_stale(bare_stale, KNOWN_UNDEFINED, "KNOWN_UNDEFINED")
        _print_stale(fb_stale, KNOWN_DEAD_FALLBACK, "KNOWN_DEAD_FALLBACK")

        parts = []
        if bare_reported:
            parts.append(
                f"{len(bare_reported)} undefined token(s) with no fallback across "
                f"{sum(len(v) for v in bare_reported.values())} declaration(s)"
            )
        if fb_reported:
            parts.append(
                f"{len(fb_reported)} dead-fallback token(s) across "
                f"{sum(len(v) for v in fb_reported.values())} declaration(s)"
            )
        if bare_stale or fb_stale:
            parts.append(f"{len(bare_stale) + len(fb_stale)} stale allowlist entr(y/ies)")
        print("FAIL: " + ", ".join(parts))
        return 1

    except Exception as exc:  # pragma: no cover — defensive top-level catch
        print(f"ERROR: unexpected failure in check_css_tokens: {exc!r}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
