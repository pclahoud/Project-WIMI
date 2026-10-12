"""A chapter's fenced code block survives the real renderer intact (#433, #428).

Why this is its own scenario
---------------------------
Chapter 3 ships a copy-pasteable prompt, and a prompt is only worth shipping if
it arrives unaltered: a student selects it, copies it and pastes it into a chat
assistant, so a dropped line changes what they ask for without anybody being
able to see that it happened. Until that chapter there was no fenced block
anywhere in `docs/manual/`, so nothing had run one through
`renderHelpMarkdown`.

`tests/test_manual_chapters.py` cannot cover it: that reads markdown and asserts
chapters avoid what the renderer does not support, while a fence *is* supported
and the question is whether what comes out is identical to what went in. The
failure mode is the usual one here -- nothing errors, a page appears, and the
text on it is wrong.

Three things it checks, each with a way of going wrong that looks like success
-----------------------------------------------------------------------------
* **One `<pre>` per fence.** An unbalanced fence makes the renderer read to the
  end of the file, so the rest of the chapter becomes code -- and the page still
  looks like a page.
* **Exact text.** Escaping happens inside a fence and inline markup does not, so
  a prompt carrying `**` or a backtick must come out carrying them. If inline
  rendering ever reached inside a fence the prompt would silently lose
  characters a student is meant to paste.
* **The chapter after the fence.** Rendered `h2` elements against the source's
  `## ` headings is what notices a fence that consumed the remainder, which is
  the likeliest way to break this and the hardest to see by looking.

Self-counting: the chapter is discovered by having a fence rather than named, so
a second chapter with a prompt in it is covered the day it lands, and the
positive control is that at least one chapter has one.

Verified able to fail, two ways, 2026-10-07: a line inserted inside the fence
without regenerating the page, and `help_page.js`'s closing-fence pattern
changed from ``` to ~~~ so a fence can never close. Both land on the exact-text
assertion -- which is why the `h2` count stays as a backstop rather than being
the headline check.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

MANUAL_DIR = Path(__file__).resolve().parents[3] / "docs" / "manual"

FENCE = "```"

#: Exists only after `help_page.js` has rendered. `#help-chapter-body` ships in
#: the markup holding a placeholder, so it is not a signal.
RENDERED = "#help-chapter-body h2[id]"

CHAPTER_SHAPE = """
(() => {
  const body = document.getElementById('help-chapter-body');
  if (!body) return JSON.stringify({ found: false });
  return JSON.stringify({
    found: true,
    holding: body.querySelectorAll('.help-body-holding').length,
    error: body.querySelectorAll('.help-body-error').length,
    h2: body.querySelectorAll('h2[id]').length,
    pre: body.querySelectorAll('pre').length,
    blocks: Array.from(body.querySelectorAll('pre')).map(p => p.textContent),
    fence_markers: (body.innerText.match(/```/g) || []).length
  });
})()
"""


def _fenced_blocks(markdown: str) -> list[str]:
    """The body of each fenced block, exactly as the source holds it."""
    blocks: list[str] = []
    current: list[str] | None = None
    for line in markdown.split("\n"):
        if line.startswith(FENCE):
            if current is None:
                current = []
            else:
                blocks.append("\n".join(current))
                current = None
            continue
        if current is not None:
            current.append(line)
    assert current is None, "a fence is never closed"
    return blocks


def _section_headings(markdown: str) -> int:
    """``## `` headings outside a fence -- what the page should render as h2."""
    count = 0
    in_fence = False
    for line in markdown.split("\n"):
        if line.startswith(FENCE):
            in_fence = not in_fence
            continue
        if not in_fence and re.match(r"^## +\S", line):
            count += 1
    return count


def _chapter_with_a_fence() -> tuple[Path, list[str]]:
    """The first chapter carrying a fenced block, with its blocks."""
    for path in sorted(MANUAL_DIR.glob("*.md")):
        blocks = _fenced_blocks(path.read_text(encoding="utf-8"))
        if blocks:
            return path, blocks
    pytest.fail(
        f"no chapter under {MANUAL_DIR} carries a fenced code block, so this "
        f"scenario asserts nothing. It is not a precaution: chapter 3 ships a "
        f"prompt a student copies out of the page"
    )


def test_a_chapters_code_block_arrives_unaltered(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """Copy-pasteable means byte-identical, measured in the real engine."""
    # ---- Arrange ----------------------------------------------------------
    path, blocks = _chapter_with_a_fence()
    slug = path.name.split("_", 1)[1].removesuffix(".md")
    markdown = path.read_text(encoding="utf-8")

    wimi_page.goto("help")
    wimi_page.locator(testid=f"help-chapter-link-{slug}").click()

    # ---- Act --------------------------------------------------------------
    wimi_page.locator(css=RENDERED).expect_visible()
    shape = json.loads(wimi_page.eval_js(CHAPTER_SHAPE))

    # ---- Assert -----------------------------------------------------------
    assert shape["found"] and not shape["holding"] and not shape["error"], (
        f"{path.name} did not render at all -- a SyntaxError in help_page.js "
        f"looks exactly like this. Shape: {shape}"
    )
    assert shape["pre"] == len(blocks), (
        f"{path.name} holds {len(blocks)} fenced block(s) and the page rendered "
        f"{shape['pre']} <pre> element(s). Fewer means a fence ran on and "
        f"swallowed prose; more means prose was read as code"
    )
    for index, (expected, actual) in enumerate(zip(blocks, shape["blocks"])):
        assert actual == expected, (
            f"{path.name} block {index} came back altered. A student copies "
            f"this text out of the page and pastes it into a chat assistant, so "
            f"a changed character changes what they ask for.\n"
            f"--- expected ---\n{expected}\n--- rendered ---\n{actual}"
        )
    assert shape["fence_markers"] == 0, (
        f"{path.name} shows literal fence markers in its text, so the fence was "
        f"not parsed and the prompt is rendered as prose"
    )
    assert shape["h2"] == _section_headings(markdown), (
        f"{path.name} has {_section_headings(markdown)} '## ' heading(s) and the "
        f"page rendered {shape['h2']} h2 element(s). An unbalanced fence reads "
        f"to the end of the file, so the chapter after the block disappears "
        f"into the code block with nothing raised anywhere"
    )
