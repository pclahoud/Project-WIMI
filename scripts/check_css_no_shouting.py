#!/usr/bin/env python3
"""CI gate: no first-party CSS paints student-facing text in capitals (#733).

The owner's decision, 2026-10-10: *"no shouting appwide"*. #346 did the
tree editor's details panel; #733 settled that the rule is the app's, not
that panel's, and this gate is what keeps it.

WHY THIS IS A DECLARATION-LEVEL GATE RATHER THAN A RENDERED SWEEP
-----------------------------------------------------------------

#346 needed a rendered sweep to FIND the problem, and said so: three of
the fifteen uppercased nodes in that panel were unreachable by reading
classes -- bare ``<label>`` elements behind parent-plus-element
selectors, and a ``<span>`` that inherited a transform from the ``<h3>``
it sat in and so uppercased a digit.

Enforcement is the opposite problem. Inheritance has to come FROM a
declaration, and a parent-plus-element selector IS a declaration, so a
check that no declaration exists is complete in a way a per-page render
could never be -- a rendered sweep can only see the pages somebody
remembered to drive, and this app has pages reachable only with seeded
data. Finding needs the render; preventing needs the declaration.

NO ALLOWLIST, BY DESIGN
-----------------------

Same property as ``check_css_empty_selector.py``: a match is always a
violation and never a legitimate state, so there is nothing to exempt and
no exemption that can go stale. If a genuine exception ever appears, it is
a decision for the owner and reopens #733 -- not a line added here.

WHAT IT DOES NOT COVER, STATED SO NOBODY READS IT AS MORE THAN IT IS
--------------------------------------------------------------------

* **A string typed in capitals.** ``<span>ERROR</span>`` is text, not
  styling, and this gate cannot and should not object to it. The error
  viewer's level badge is the live example: it renders ``${error.level}``,
  whose value arrives already upper-cased from the logger, so removing its
  transform changed nothing on screen.
* **``text-transform`` set from JavaScript**, e.g. ``el.style.textTransform``.
  Nothing in ``src/web/js`` does this today; the companion test asserts
  that, so the absence is checked rather than assumed.
* **``font-variant: small-caps``**, which is a different effect and was
  not part of the decision.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = REPO_ROOT / "src" / "web" / "css"

# `text-transform: uppercase`, tolerant of whitespace and `!important`.
# Deliberately NOT matching `capitalize` or `lowercase`: the decision was
# about shouting, and `capitalize` is used on one weight label where it
# title-cases a stored lower-case enum value.
SHOUT = re.compile(r"text-transform\s*:\s*uppercase", re.I)

COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _strip_comments(css: str) -> str:
    """Blank comments while PRESERVING line numbers.

    Replacing a comment with spaces of equal length collapses the newlines
    inside it and shifts every line number after it -- which is how a
    first draft of this check reported two thirds of the codebase as
    commented out. Keep the newlines.
    """
    def blank(m: "re.Match[str]") -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    return COMMENT.sub(blank, css)


def find_violations(css_dir: Path):
    """[(relative_path, line_number, line_text)], and the file count read."""
    violations = []
    files = sorted(css_dir.glob("*.css"))
    for path in files:
        text = _strip_comments(path.read_text(encoding="utf-8"))
        for number, line in enumerate(text.splitlines(), start=1):
            if SHOUT.search(line):
                # as_posix(): a reported location is a repo-relative
                # identifier, not a path to open, and it must not differ
                # by platform (#621 -- backslashes made two tests
                # unpassable on Windows and nobody noticed for days).
                #
                # The fallback is not defensive padding: the tests point
                # this function at a tmp_path outside the repo, and
                # `relative_to` RAISES there rather than degrading.
                try:
                    rel = path.relative_to(REPO_ROOT).as_posix()
                except ValueError:
                    rel = path.as_posix()
                violations.append((rel, number, line.strip()))
    return violations, len(files)


def main() -> int:
    if not CSS_DIR.is_dir():
        print(f"FAIL: no stylesheet directory at {CSS_DIR}")
        return 1

    violations, file_count = find_violations(CSS_DIR)

    print(f"Scanned {file_count} stylesheet(s) under "
          f"{CSS_DIR.relative_to(REPO_ROOT).as_posix()}.")

    if not violations:
        print("OK: nothing is painted in capitals (0 allowlisted)")
        return 0

    print(f"\nFAIL: {len(violations)} rule(s) paint text in capitals. The "
          f"owner settled this app-wide on 2026-10-10 (#733, after #346).\n")
    for rel, number, line in violations:
        print(f"  {rel}:{number}: {line}")
    print(
        "\nRemove the declaration, and the `letter-spacing` beside it if that "
        "\ntracking was only there to make capitals legible. If the text "
        "\nshould genuinely read in capitals, write it that way in the markup "
        "\nor the JavaScript -- styling is not the place to say it, because "
        "\nChromium applies `text-transform` to the ACCESSIBLE NAME too, so "
        "\nthe shouting reaches a screen reader as well as the screen."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
