"""Settings -> MCP Server favours no assistant (owner, 2026-10-14).

The panel used to say "AI assistants like Claude", head its connection help
"Connect Claude Code", and emit one vendor's command-line invocation. MCP is
an open protocol with many clients, so the panel now names the protocol, not
a product, and offers the de facto `mcpServers` shape over each transport the
server speaks plus a stdio launch. These are static checks on the markup, the
script and the chapter; the rendered blocks are a scenario.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SETTINGS = (REPO / "src/web/html/settings.html").read_text(encoding="utf-8")
SCRIPT = (REPO / "src/web/js/settings.js").read_text(encoding="utf-8")
CHAPTER = (REPO / "docs/manual/80_settings.md").read_text(encoding="utf-8")
BRIDGE = (REPO / "src/app/bridge_domains/mcp_server.py").read_text(encoding="utf-8")

#: Product names a vendor-neutral panel must not carry. "Claude" also covers
#: "Claude Code"; the list is what the panel and chapter used to say.
VENDORS = ("Claude", "ChatGPT", "OpenAI", "Gemini", "Copilot", "Cursor", "Anthropic")


def _panel() -> str:
    m = re.search(r'<div class="settings-panel" data-panel="mcp_server">.*?'
                  r'(?=<!-- =+\s*Panel \d+: Profile)', SETTINGS, re.S)
    assert m, "the MCP panel is missing or the Profile panel's banner moved"
    return m.group(0)


def _mcp_block_of(source: str) -> str:
    start = source.index("_populateMcpInstructions(status) {")
    end = source.index("_copyToClipboard(text, btn) {")
    return source[start:end]


def _chapter_section() -> str:
    start = CHAPTER.index("## MCP Server")
    end = CHAPTER.index("\n## ", start + 1)
    return CHAPTER[start:end]


@pytest.mark.unit
def test_the_panel_names_no_product():
    panel = _panel()
    found = [v for v in VENDORS if v in panel]
    assert not found, f"the MCP panel names {found}; it should name the protocol only"
    assert "Model Context Protocol" in panel


@pytest.mark.unit
def test_the_instructions_script_runs_no_vendor_cli():
    block = _mcp_block_of(SCRIPT)
    assert "claude mcp" not in block, "one vendor's command line is back in the panel"
    found = [v for v in VENDORS if v in block]
    assert not found, found


@pytest.mark.unit
def test_the_panel_offers_both_transports_and_stdio():
    panel = _panel()
    for needle in ('id="mcpHttpUrlValue"', 'id="mcpUrlValue"',
                   'id="mcpConfigHttp"', 'id="mcpConfigJson"', 'id="mcpConfigStdio"',
                   'id="mcpCopyHttpBtn"', 'id="mcpCopyJsonBtn"', 'id="mcpCopyStdioBtn"'):
        assert needle in panel, needle
    block = _mcp_block_of(SCRIPT)
    for key in ("http_url", "sse_url", "stdio_command", "stdio_cwd"):
        assert key in block, f"the script never reads {key} from the bridge payload"


@pytest.mark.unit
def test_the_bridge_payload_carries_every_route():
    for key in ("'sse_url'", "'http_url'", "'stdio_command'", "'stdio_cwd'"):
        assert key in BRIDGE, key
    assert "streamable_http_app()" in BRIDGE and "sse_app().routes" in BRIDGE, (
        "both transports must be served from the one uvicorn app")


@pytest.mark.unit
def test_the_chapter_matches():
    section = _chapter_section()
    found = [v for v in VENDORS if v in section]
    assert not found, found
    assert "Model Context Protocol" in section
    assert "three copy-ready configuration blocks" in section
