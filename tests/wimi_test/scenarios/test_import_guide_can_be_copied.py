"""Regression: the Import Format Guide can be copied in one press (#452).

The manual's "Building your subject tree from a published outline" chapter
tells a student to hand this guide to an AI assistant, which made the guide
load-bearing on a documented path. Before this button that step meant
selecting more than a thousand lines by hand inside a scrolling modal.

**Why the bridge call is the assertion.** CDP cannot read the system
clipboard, so "the text reached the clipboard" is not observable from here.
What *is* observable is that WIMI asked Qt to put it there: `copyToClipboard`
is an `@instrumented_slot`, and its buffer entry is appended **after** the
Python side returns, so a match means the copy completed rather than that JS
merely dispatched it. That is the strongest available claim and the test says
so rather than implying it checked the clipboard.

**Why the argument is checked, not just the call.** A button that copied the
empty string, or the rendered HTML instead of the markdown source, would fire
the same slot. The student is pasting this into a language model, so the
source is what has to travel.

**The status span is checked two ways on purpose** (#121's rule). `innerText`
answers "is a student shown an outcome"; the accessibility tree answers "is it
announced". The `aria-live` attribute answers neither — it is exactly what
stays correct when the node has been removed from the tree.
"""
from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _wait_for(
    wimi_page: WimiPage,
    js_expression: str,
    *,
    timeout_ms: int = 5000,
    poll_step_ms: int = 100,
) -> Any:
    """Poll ``js_expression`` until truthy; return the last value seen."""
    waited = 0
    value = None
    while waited < timeout_ms:
        value = wimi_page.eval_js(js_expression)
        if value:
            return value
        wimi_page.wait_for_timeout(poll_step_ms)
        waited += poll_step_ms
    return value


def _open_the_guide(wimi_page: WimiPage) -> None:
    wimi_page.goto("tree-editor")
    _wait_for(
        wimi_page,
        "(() => { const s = document.getElementById('import-help-source');"
        " return !!s && s.textContent.trim().length > 1000; })()",
    )
    clicked = wimi_page.eval_js(
        "(() => { const b = document.getElementById('btn-import-help');"
        " if (!b) return false; b.click(); return true; })()"
    )
    assert clicked, "#btn-import-help not found on tree_editor.html"
    assert _wait_for(
        wimi_page,
        "document.getElementById('import-help-modal').classList.contains('active')",
    ), "Import help modal did not open"


@pytest.mark.slow
@pytest.mark.regression
def test_one_press_copies_the_guides_markdown_source(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Press Copy and assert WIMI handed Qt the guide's own markdown."""
    _open_the_guide(wimi_page)

    # Negative control. Without this, "the status says something afterwards"
    # would pass against a span that always said it.
    before = wimi_page.eval_js(
        "(() => { const s ="
        " document.getElementById('import-help-copy-status');"
        " return s ? s.textContent.trim() : 'MISSING'; })()"
    )
    assert before == "", (
        f"the status span should start empty, found {before!r}. An always-on "
        "message makes every assertion below vacuous."
    )

    source_len = wimi_page.eval_js(
        "document.getElementById('import-help-source').textContent.length"
    )

    cursor = wimi_page.mark_bridge_calls()
    pressed = wimi_page.eval_js(
        "(() => { const b = document.getElementById('btn-copy-import-format');"
        " if (!b) return false; b.click(); return true; })()"
    )
    assert pressed, (
        "#btn-copy-import-format not found. The Copy button is what makes the "
        "manual's documented first step possible (#452)."
    )

    record = wimi_page.wait_for_bridge_call("copyToClipboard", since_ts=cursor)
    assert record, (
        "copyToClipboard was never recorded. The button's primary path is the "
        "Qt bridge, because the Clipboard API may be refused outright on the "
        "file:// protocol every WIMI page is served over."
    )

    # What was handed over has to be the guide, not an empty string and not
    # the rendered HTML.
    #
    # The instrumentation records `args_summary` -- a `repr` TRUNCATED to about
    # 200 characters with "..." appended -- and no raw argument, which is right
    # for a buffer that would otherwise hold 46 KB per press. So this checks
    # the opening of what was copied plus the truncation marker, and that pair
    # is the honest claim: the right document, and longer than 200 characters.
    # It is not a check of all 45,988.
    summary = record.get("args_summary") or ""
    assert summary, (
        "copyToClipboard was recorded with no args_summary, so there is "
        "nothing to check the copied text against."
    )
    assert "Subject tree import format" in summary, (
        f"copyToClipboard did not receive the guide. args_summary={summary!r}. "
        "An empty string or the wrong text fires the same slot."
    )
    assert "<div" not in summary and "<p>" not in summary, (
        f"the rendered HTML was copied instead of the markdown source: "
        f"{summary!r}. A language model should be given the format as written."
    )
    assert summary.rstrip().endswith("..."), (
        f"args_summary was not truncated, so the copied text was under ~200 "
        f"characters when the guide is {source_len}: {summary!r}"
    )

    # Painted.
    #
    # POLLED, not read once, and the reason is worth keeping: a recorded bridge
    # call means the **Python** slot returned, not that the JS continuation
    # after `await api.copyToClipboard(...)` has run. The status is set in that
    # continuation, so there is a real gap between the two. Reading once passed
    # this file in isolation and failed it inside a 26-scenario selection --
    # the pass-alone/fail-in-suite shape, and it was the test's
    # synchronisation rather than the product every time (#117's lesson).
    shown = _wait_for(
        wimi_page,
        "document.getElementById('import-help-copy-status').innerText.trim()",
    )
    assert shown, "the copy reported no outcome to the student"

    # Announced. A separate instrument, because the accessibility tree is the
    # only thing that answers this -- the `aria-live` attribute is exactly what
    # stays correct when the node has been removed from the tree.
    #
    # Polled for the same reason as above. #371 records six scenarios reading
    # this tree after a fixed wait, which is a race; a snapshot taken one frame
    # early is indistinguishable from a span that is never exposed.
    wimi_page.tab.Accessibility.enable()
    wanted = shown.split(".")[0]

    def _exposed() -> bool:
        tree = wimi_page.tab.Accessibility.getFullAXTree()
        return any(
            wanted in ((node.get("name") or {}).get("value", "") or "")
            for node in tree.get("nodes", [])
        )

    announced = False
    for _ in range(50):
        if _exposed():
            announced = True
            break
        wimi_page.wait_for_timeout(100)

    assert announced, (
        f"the outcome is painted ({shown!r}) but absent from the accessibility "
        "tree after 5s. Toasts in this app are not announced at all (#417), "
        "which is the whole reason this span exists."
    )
