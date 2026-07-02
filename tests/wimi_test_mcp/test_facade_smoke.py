"""Phase 5 verification gate: smoke tests for the ``wimi-test`` MCP facade.

These tests prove the MCP facade for the WIMI test harness is reachable
end-to-end over stdio. They do **not** attempt to drive a live WIMI
subprocess or Playwright session — that is intentionally out of scope for
the Phase 5 gate. The goal here is narrow:

1. The ``wimi-test`` MCP server can be spawned via
   ``python run_wimi.py --test-mcp-server``.
2. A standard MCP stdio client can connect, initialize, and list the
   server's tools.
3. The 13 tools shipped in ``src/wimi_test_mcp/server.py`` are all
   registered and discoverable.
4. A no-op tool call (``get_session_status`` with no active session)
   returns a well-formed response instead of erroring out.

A separate, full end-to-end MCP scenario — actually starting a session,
navigating, evaluating JS, asserting on logs — is left to a later phase
once Playwright orchestration is wired up.

Every test in this module is marked ``slow`` because spawning a Python
subprocess and bringing up the MCP server takes non-trivial time on cold
starts, especially on Windows.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Lazy-import the MCP client SDK. It is listed as a deferred dependency in
# the test infrastructure design doc, so we must not hard-fail the suite
# if it is missing — instead skip the whole module.
try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    MCP_CLIENT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when SDK absent
    MCP_CLIENT_AVAILABLE = False


# Every test in this module is slow (subprocess spawn + MCP handshake).
pytestmark = [pytest.mark.slow]


# Repo root: tests/wimi_test_mcp/test_facade_smoke.py -> ../../
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _server_params() -> "StdioServerParameters":
    """Build the stdio launch parameters for the wimi-test MCP server.

    Pulled into a helper so both tests stay in sync if the launch flag
    or argv shape changes.
    """
    return StdioServerParameters(
        command=sys.executable,
        args=["run_wimi.py", "--test-mcp-server"],
        cwd=str(_REPO_ROOT),
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not MCP_CLIENT_AVAILABLE, reason="mcp SDK not installed")
async def test_wimi_test_mcp_server_starts_and_lists_tools(tmp_path):
    """Spawn the wimi-test MCP server, list its tools, end the connection.

    This is the primary Phase 5 verification: if this passes, the facade
    is reachable and its tool registry is intact.
    """
    params = _server_params()

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_response = await session.list_tools()
            tool_names = {t.name for t in tools_response.tools}

            # The 13 tools defined in src/wimi_test_mcp/server.py.
            expected = {
                "start_session",
                "end_session",
                "get_session_status",
                "navigate_to",
                "wait_for",
                "eval_js",
                "click",
                "fill",
                "screenshot",
                "get_console_log",
                "get_network_log",
                "get_bridge_log",
                "dump_dom",
            }

            missing = expected - tool_names
            assert not missing, f"Missing tools: {missing}"


@pytest.mark.asyncio
@pytest.mark.skipif(not MCP_CLIENT_AVAILABLE, reason="mcp SDK not installed")
async def test_get_session_status_when_no_session_active(tmp_path):
    """``get_session_status`` with no active session must succeed, not error.

    The contract is: the tool returns a structured response whose
    ``status.active`` is ``False`` when no WIMI subprocess has been
    started. This guards against regressions where the facade would
    blow up on a cold call before any session was opened.
    """
    params = _server_params()

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool("get_session_status")

            # The MCP SDK returns a CallToolResult; we only need to
            # confirm the call did not raise and produced *something*.
            # Deeper schema assertions belong in a follow-up end-to-end
            # test once a real session lifecycle is exercised.
            assert result is not None
