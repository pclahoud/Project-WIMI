"""Settings -> MCP Server, once the server runs, shows both addresses and
three copy-ready blocks that an MCP client of any vendor can use.

The blocks are read back from the rendered page and parsed, so a block that
is drawn but not valid JSON, or that names a route the bridge did not offer,
fails here rather than on a student's clipboard. The stdio block's command
must be this process's interpreter and end in --mcp-server, which is what the
bridge derives for a checkout; a frozen build derives the executable instead
(not measured here, #760).
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PORT = 8124

READY = ("(() => { try { return settingsPage.isPageReady === true; }"
         " catch (e) { return false; } })()")


def _poll(page: WimiPage, read, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_the_panel_shows_two_addresses_and_three_parseable_blocks(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_page.goto("settings")
    assert _poll(wimi_page, lambda: wimi_page.eval_js(READY), True) is True

    started = wimi_page.eval_js(f"(async () => await api.startMcpServer({PORT}))()", await_promise=True)
    assert started.get("running") is True, started
    # The panel redraws from getMcpServerStatus; drive the same path Save would.
    wimi_page.eval_js(f"(async () => settingsPage._updateMcpStatusUI(await api.getMcpServerStatus()))()",
                      await_promise=True)
    try:
        assert _poll(wimi_page, lambda: wimi_page.eval_js(
            "getComputedStyle(document.getElementById('mcpConnectInstructions')).display"), "block") == "block"

        http_url = wimi_page.eval_js("document.getElementById('mcpHttpUrlValue').textContent")
        sse_url = wimi_page.eval_js("document.getElementById('mcpUrlValue').textContent")
        assert http_url == f"http://127.0.0.1:{PORT}/mcp"
        assert sse_url == f"http://127.0.0.1:{PORT}/sse"

        blocks = {}
        for block_id in ("mcpConfigHttp", "mcpConfigJson", "mcpConfigStdio"):
            hidden = wimi_page.eval_js(
                f"document.getElementById('{block_id}').closest('.mcp-config-block').hidden")
            assert hidden is False, f"{block_id} is hidden although the bridge offered its route"
            text = wimi_page.eval_js(f"document.getElementById('{block_id}').textContent")
            blocks[block_id] = json.loads(text)["mcpServers"]["wimi-db"]

        assert blocks["mcpConfigHttp"] == {"type": "http", "url": http_url}
        assert blocks["mcpConfigJson"] == {"type": "sse", "url": sse_url}
        stdio = blocks["mcpConfigStdio"]
        assert stdio["args"][-1] == "--mcp-server"
        assert stdio["command"].rstrip("3").endswith("python") or "python" in stdio["command"].lower(), stdio
        assert stdio["cwd"], "the stdio block names no working directory"

        page_text = wimi_page.eval_js(
            "document.querySelector('.settings-panel[data-panel=\"mcp_server\"]').innerText")
        for vendor in ("Claude", "ChatGPT", "Cursor", "Gemini", "Copilot"):
            assert vendor not in page_text, f"the rendered panel names {vendor}"
        for button in ("settings-mcp-server-copy-http", "settings-mcp-server-copy-json",
                       "settings-mcp-server-copy-stdio"):
            assert wimi_page.eval_js(
                f"!!document.querySelector('[data-testid=\"{button}\"]')"), button
    finally:
        wimi_page.eval_js("(async () => await api.stopMcpServer())()", await_promise=True)
