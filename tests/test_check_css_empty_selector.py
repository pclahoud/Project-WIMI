"""Tests for ``scripts/check_css_empty_selector.py`` — the #141 gate.

The gate itself is run against the real tree by
:func:`test_real_tree_has_no_empty_selectors`, which is the assertion that
matters. The rest test the parts that decide whether it can be trusted:
comment stripping (so documenting the ban does not trip it) and the vendored
exclusions (so TinyMCE's own rules do not).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "check_css_empty_selector.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_css_empty_selector", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_css_empty_selector"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load()


@pytest.mark.unit
def test_real_tree_has_no_empty_selectors(gate):
    """The assertion the gate exists for."""
    hits = gate.find_uses(PROJECT_ROOT)
    assert hits == [], (
        "`:empty` reappeared in first-party CSS. It does not re-invalidate on "
        "QtWebEngine 6.10 — the element renders at zero pixels with no error. "
        f"Use `:not(:has(*))`. Found: {[(str(p), n) for p, n, _ in hits]}"
    )


@pytest.mark.unit
def test_detects_a_real_use(gate, tmp_path):
    css = tmp_path / "src" / "web" / "css"
    css.mkdir(parents=True)
    (css / "x.css").write_text(".thing:empty { display: none; }\n", encoding="utf-8")
    hits = gate.find_uses(tmp_path)
    assert len(hits) == 1
    assert hits[0][1] == 1


@pytest.mark.unit
def test_ignores_uses_inside_comments(gate, tmp_path):
    """A gate that punishes documenting itself gets its docs deleted.

    ``styles.css`` carries a comment explaining why `:empty` is banned; an
    earlier version of this check fired on that comment.
    """
    css = tmp_path / "src" / "web" / "css"
    css.mkdir(parents=True)
    (css / "x.css").write_text(
        "/* Do not use :empty here -- see #141.\n"
        "   It does not re-invalidate on 6.10. */\n"
        ".thing:not(:has(*)) { display: none; }\n",
        encoding="utf-8",
    )
    assert gate.find_uses(tmp_path) == []


@pytest.mark.unit
def test_comment_stripping_preserves_line_numbers(gate, tmp_path):
    """The reported line must point at the offending line, not drift."""
    css = tmp_path / "src" / "web" / "css"
    css.mkdir(parents=True)
    (css / "x.css").write_text(
        "/* a\n   multi-line\n   comment */\n"
        ".thing:empty { display: none; }\n",
        encoding="utf-8",
    )
    hits = gate.find_uses(tmp_path)
    assert len(hits) == 1
    assert hits[0][1] == 4, "line number drifted after comment stripping"
    assert ":empty" in hits[0][2], "reported text should be the original line"


@pytest.mark.unit
def test_detects_uses_in_html_style_blocks(gate, tmp_path):
    html = tmp_path / "src" / "web" / "html"
    html.mkdir(parents=True)
    (html / "p.html").write_text(
        "<style>\n.x:empty { display:none; }\n</style>\n", encoding="utf-8")
    hits = gate.find_uses(tmp_path)
    assert len(hits) == 1 and hits[0][1] == 2


@pytest.mark.unit
def test_ignores_html_comments(gate, tmp_path):
    html = tmp_path / "src" / "web" / "html"
    html.mkdir(parents=True)
    (html / "p.html").write_text(
        "<!-- :empty is banned, see #141 -->\n<div></div>\n", encoding="utf-8")
    assert gate.find_uses(tmp_path) == []


@pytest.mark.unit
def test_vendored_libraries_are_excluded(gate, tmp_path):
    """TinyMCE ships its own `:empty` rules and they are not ours to audit."""
    for rel in (Path("src/web/lib/tinymce"), Path("src/web/js/lib")):
        d = tmp_path / rel
        d.mkdir(parents=True)
        (d / "v.css").write_text(".vendor:empty { display: none; }\n",
                                 encoding="utf-8")
    assert gate.find_uses(tmp_path) == []


@pytest.mark.unit
def test_has_no_allowlist(gate):
    """Deliberate: every first-party use was removed in the same commit.

    An exemption list with no entries is a place for the next exception to
    hide. If `:empty` is ever genuinely needed, reopen #141.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "KNOWN_" not in source and "ALLOWLIST" not in source
