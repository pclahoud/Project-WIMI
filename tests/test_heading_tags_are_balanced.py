"""Every heading a web file opens, it closes with the same level (#846).

The alias manager's title opened ``<h2 class="modal-title"
id="alias-manager-title">`` and closed ``</h3>``. The browser repairs that
silently, so the title still rendered and nothing a student could see was
wrong. But the dialog's ``aria-labelledby`` points at whatever element the
parser's recovery built, not at the one the source describes. #318 settles
modal titles as ``<h2>``, and every other modal title in the app already
is one.

A mismatch like this is invisible in the running app by design, which is
why this is a source check. It counts opening and closing tags per level in
every first-party page and script, after stripping comments, because prose
in a doc comment (``help_page.js`` mentions the page's ``<h1>``) is not
markup.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"

_JS_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_JS_LINE = re.compile(r"(?<![:'\"\\])//[^\n]*")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _sources():
    return sorted([*(WEB / "js").rglob("*.js"), *(WEB / "html").glob("*.html"),
                   *(WEB / "html" / "wizards").glob("*.html")])


def _markup(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = _HTML_COMMENT.sub("", text)
    if path.suffix == ".js":
        text = _JS_LINE.sub("", _JS_BLOCK.sub("", text))
    return text


def _imbalances(text: str) -> list[str]:
    out = []
    for level in range(1, 7):
        opened = len(re.findall(rf"<h{level}[\s>]", text))
        closed = len(re.findall(rf"</h{level}>", text))
        if opened != closed:
            out.append(f"h{level}: {opened} opened, {closed} closed")
    return out


def test_the_sweep_finds_its_files():
    assert len(_sources()) > 40, "the sweep found too few files to mean anything"


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.relative_to(WEB).as_posix())
def test_every_heading_closes_at_its_own_level(path):
    assert _imbalances(_markup(path)) == [], (
        f"{path.relative_to(ROOT)}: {_imbalances(_markup(path))}. The browser"
        f" repairs a mismatched heading silently, so aria-labelledby and the"
        f" outline point at an element the source does not describe (#846).")


def test_the_check_catches_the_original_mismatch():
    """Negative control: the line #846 fixed must fail this check."""
    assert _imbalances('<h2 class="modal-title" id="t">Manage Aliases</h3>') == [
        "h2: 1 opened, 0 closed", "h3: 0 opened, 1 closed"]
