"""Tests for the no-shouting gate (#733).

Four things, and the last two are the ones that make the gate worth
having rather than merely present:

* it passes on the real tree;
* it CATCHES a planted declaration -- the negative control, without
  which a gate that matched nothing would look identical to a clean
  codebase;
* its comment stripping preserves line numbers. A first draft replaced
  each comment with spaces of equal length, which collapses the newlines
  inside it and shifts every line after, and a probe built that way
  reported most of the codebase as commented out. That bug would make
  the gate silently skip real violations sitting after any multi-line
  comment -- and `src/web/css` is full of them;
* nothing sets `text-transform` from JavaScript, so the gate's stated
  blind spot is empty rather than merely acknowledged.

The script is loaded with ``importlib`` rather than imported, because
``scripts/`` is not a package. Note the gate uses a plain class-free
module for the reason recorded in CLAUDE.md: a ``@dataclass`` inside a
``scripts/`` gate raises ``AttributeError`` at import time under exactly
this loading pattern.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "check_css_no_shouting.py"
CSS_DIR = REPO_ROOT / "src" / "web" / "css"


def _load():
    spec = importlib.util.spec_from_file_location("check_css_no_shouting", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_real_tree_has_no_shouting():
    module = _load()
    violations, file_count = module.find_violations(CSS_DIR)
    assert violations == [], (
        "first-party CSS paints text in capitals, which #733 settled "
        f"against app-wide: {violations!r}")
    # Self-counting: a gate that read no files would also report none.
    assert file_count >= 15, (
        f"only {file_count} stylesheets were read; the gate is looking in "
        f"the wrong place and its clean result means nothing")


def test_it_catches_a_planted_declaration(tmp_path):
    """The negative control."""
    module = _load()
    (tmp_path / "planted.css").write_text(
        ".shouty {\n    color: red;\n    text-transform: uppercase;\n}\n")

    violations, _ = module.find_violations(tmp_path)

    assert len(violations) == 1, f"the gate missed a plain violation: {violations!r}"
    rel, number, line = violations[0]
    assert number == 3, f"wrong line reported: {violations!r}"
    assert "uppercase" in line


def test_a_commented_out_declaration_is_not_a_violation(tmp_path):
    module = _load()
    (tmp_path / "commented.css").write_text(
        "/* we used to do\n   text-transform: uppercase;\n   here */\n"
        ".fine {\n    color: red;\n}\n")

    violations, _ = module.find_violations(tmp_path)

    assert violations == [], (
        f"a declaration inside a comment is not applied: {violations!r}")


def test_comment_stripping_preserves_line_numbers(tmp_path):
    """The bug that would make this gate skip real violations.

    A multi-line comment ABOVE a violation must not shift the reported
    line. Replacing comments with equal-length spaces -- which eats the
    newlines -- is what gets this wrong, and the symptom is a gate that
    quietly reads the wrong lines rather than one that errors.
    """
    module = _load()
    (tmp_path / "shifted.css").write_text(
        "/* one\n * two\n * three\n * four\n */\n"
        ".shouty {\n    text-transform: uppercase;\n}\n")

    violations, _ = module.find_violations(tmp_path)

    assert len(violations) == 1, f"the violation was lost: {violations!r}"
    assert violations[0][1] == 7, (
        "the reported line is wrong, so comment stripping is collapsing "
        f"newlines and every later line is off: {violations!r}")


# `rich_html.js` lists `text-transform` among the CSS properties the
# rich-text sanitiser ALLOWS THROUGH on stored student content (#591).
#
# THAT IS NOT IN SCOPE AND MUST NOT BE SWEPT, which is why it is named here
# rather than left to be rediscovered as a violation. #733 is about WIMI
# shouting in its own chrome. A student who capitalises a heading inside
# their own note is styling their own words, and removing the property from
# that allowlist would silently strip formatting out of notes people have
# already written -- a data-visible change nobody asked for, to enforce a
# rule that was never about them.
_SANITISER_ALLOWLIST = "src/web/js/rich_html.js"


def test_nothing_sets_text_transform_from_javascript():
    """The gate's one real blind spot, asserted empty rather than assumed.

    A page could shout by assigning `style.textTransform`, which no CSS
    check can see. Nothing does today. If something ever needs to, it is
    a decision that reopens #733, not a line to slip past this gate.
    """
    js_dir = REPO_ROOT / "src" / "web" / "js"
    # An ASSIGNMENT, not a mention. Several modules discuss text-transform
    # in prose -- `tour.js` explains that it reads a step's title with
    # `textContent` rather than `innerText` precisely BECAUSE innerText is
    # the text as painted and a transform would reach it. Matching the bare
    # word flagged four such comments, which is a reader with no control
    # (#396's lesson one level over: a sweep's own matcher needs checking).
    pattern = re.compile(
        r"""\.style\s*\.\s*textTransform\s*=          # el.style.textTransform =
          | setProperty\s*\(\s*['"]text-transform['"] # setProperty('text-transform'
          | textTransform\s*:                         # {textTransform: ...}
        """,
        re.X,
    )
    offenders = []
    checked = 0
    for path in sorted(js_dir.rglob("*.js")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if "/lib/" in rel:
            continue  # vendored D3/Fuse, not ours to style-police
        if rel == _SANITISER_ALLOWLIST:
            continue  # see above: the student's own content
        checked += 1
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert checked >= 20, (
        f"only {checked} scripts were read; this sweep is looking in the "
        f"wrong place and its clean result means nothing")
    assert offenders == [], (
        "JavaScript sets text-transform, which the CSS gate cannot see: "
        + "; ".join(offenders))


# ALL-CAPS labels written straight into markup or JS. The CSS gate cannot
# see these, and the stylesheet sweep alone would have left nine of them
# shouting -- which is how this was found: three tests that asserted painted
# capitals were expected to break and did not, because those strings were
# never painted by CSS at all. *A stylesheet sweep measures stylesheets.*
#
# Each exemption is a reason, not a convenience:
_SOURCE_CAPS_EXEMPT = {
    # GPL-3.0 §5(d). The About panel IS the notices document and this is the
    # warranty disclaimer, quoted verbatim; test_about_panel_shows_notices.py
    # pins it. Recasing it would change a legal notice.
    "WITHOUT ANY WARRANTY",
    "LICENSE",        # a filename, in the same notices panel
    "MIT-CMU",        # a licence identifier
    # Real DLL filenames shipped by the MSVC runtime (#195 (c)).
    "MSVCP140", "VCOMP140", "VCRUNTIME140",
    # A question bank's own brand spelling.
    "AMBOSS",
}


def test_no_all_caps_label_is_written_into_markup_or_js():
    """The other half of "no shouting", which CSS cannot enforce."""
    pattern = re.compile(r">([A-Z][A-Z0-9 &/'\-]{3,})<")
    known_words = {
        "WIMI", "MCP", "GPL", "LGPL", "MIT", "URL", "CSV", "JSON", "HTML",
        "CSS", "AI", "ID", "OK", "PDF", "API", "UI", "CPU", "GPU", "DB",
        "SQL", "USMLE", "NBME", "STT", "CDP",
    }
    offenders, files_read = [], 0
    for base in ("src/web/js", "src/web/html"):
        for path in sorted((REPO_ROOT / base).rglob("*")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if path.suffix not in (".js", ".html") or "/lib/" in rel:
                continue
            files_read += 1
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in pattern.finditer(line):
                    text = match.group(1).strip()
                    if not text or text in _SOURCE_CAPS_EXEMPT:
                        continue
                    words = [w for w in re.split(r"[ &/'\-]+", text) if w]
                    if all(w in known_words for w in words):
                        continue
                    offenders.append(f"{rel}:{number}: {text}")

    assert files_read >= 40, (
        f"only {files_read} files were read; this sweep is looking in the "
        f"wrong place and its clean result means nothing")
    assert offenders == [], (
        "these labels shout from the source, where no CSS gate can see "
        "them: " + "; ".join(offenders))


def test_the_source_caps_exemptions_are_all_still_present():
    """An exemption nobody re-checks outlives its reason (the xfail lesson).

    Every entry must still be findable, or it is dead and should go.
    """
    haystack = "\n".join(
        p.read_text(encoding="utf-8")
        for base in ("src/web/js", "src/web/html")
        for p in (REPO_ROOT / base).rglob("*")
        if p.suffix in (".js", ".html") and "/lib/" not in p.as_posix()
    )
    stale = [e for e in _SOURCE_CAPS_EXEMPT if e not in haystack]
    assert stale == [], (
        f"these exemptions no longer match anything and should be removed: "
        f"{sorted(stale)}")


def test_the_sanitiser_exemption_is_still_needed():
    """The pytest.xfail lesson: an exemption nobody re-checks outlives it.

    If `rich_html.js` stops allowing `text-transform` through, the
    carve-out above is dead and should go rather than sit there implying
    a rule.
    """
    source = (REPO_ROOT / _SANITISER_ALLOWLIST).read_text(encoding="utf-8")
    assert "'text-transform'" in source, (
        f"{_SANITISER_ALLOWLIST} no longer allows text-transform through, "
        f"so its exemption in this file is stale and should be removed")
