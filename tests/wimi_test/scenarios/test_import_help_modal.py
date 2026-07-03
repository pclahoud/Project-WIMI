"""Regression: Import Format Guide modal on the tree editor page.

The help icon (``#btn-import-help``) previously fetched
``subject_tree_import_format.md`` through the ``readDocumentation``
bridge slot, whose dev-mode base path regressed to ``src/`` during the
mixin decomposition (``bridge_domains/`` added a directory level to
``__file__``), so the modal always fell back to its error panel. The
guide is now embedded in the page itself (``#import-help-source``, a
``text/markdown`` script block in ``tree_editor.html``) and rendered
locally by ``parseMarkdown`` — no bridge round-trip, identical
behavior in dev and frozen builds.

This scenario proves the wiring: source block present, modal opens
from the button, markdown actually rendered (not the fallback error
panel).

Loader quirk: probes use ``window.api`` (NOT ``window._wimiApi``)
because ``_loader.js`` aliases then deletes the source handle.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_import_help_modal_renders_embedded_guide(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Open the help modal and assert the embedded guide renders."""
    wimi_page.goto("tree-editor")

    # Page init is async — give it a beat before poking the DOM.
    wimi_page.wait_for_timeout(500)

    # The embedded markdown source block must ship with the page.
    source_len = wimi_page.eval_js(
        "(() => { const s = document.getElementById('import-help-source');"
        " return s ? s.textContent.trim().length : -1; })()"
    )
    assert source_len > 1000, (
        f"#import-help-source missing or near-empty (len={source_len}). "
        "The text/markdown block in tree_editor.html must carry the "
        "import format guide."
    )

    # Open the modal through the real button handler.
    clicked = wimi_page.eval_js(
        "(() => { const b = document.getElementById('btn-import-help');"
        " if (!b) return false; b.click(); return true; })()"
    )
    assert clicked, "#btn-import-help not found on tree_editor.html"

    # Rendering is synchronous now (no bridge fetch), but allow a beat.
    wimi_page.wait_for_timeout(200)

    modal_active = wimi_page.eval_js(
        "document.getElementById('import-help-modal')"
        ".classList.contains('active')"
    )
    assert modal_active, "Import help modal did not open on button click"

    content_probe = wimi_page.eval_js(
        "(() => { const c = document.getElementById('import-help-content');"
        " return { html_len: c.innerHTML.length,"
        "          has_heading: !!c.querySelector('h1, h2'),"
        "          has_code: !!c.querySelector('pre code'),"
        "          fallback: c.innerHTML.includes('Unable to Load Documentation') }; })()"
    )
    assert not content_probe["fallback"], (
        "Modal rendered the fallback error panel — the embedded source "
        "was not parsed. Check showImportHelpModal in import_export.js."
    )
    assert content_probe["has_heading"] and content_probe["has_code"], (
        f"Rendered guide looks wrong: {content_probe!r}. Expected parsed "
        "markdown with headings and code blocks from the embedded source."
    )
