"""The in-app MCP server answers both transports on one port, and the status
payload names every way in.

MCP clients disagree about transport: the original SSE pair, Streamable HTTP
(the 2025-03-26 revision), or launching the server as a process over stdio.
Settings -> MCP Server shows all three so it favours no one client. This test
starts the real server through the bridge slot, connects over SSE and over
Streamable HTTP with the reference client, and requires the two tool lists to
be identical and non-trivial. A control asserts that the SSE path is not
served by a server built from the Streamable HTTP app alone, so the route
merge in `_run_mcp_sse_server` is what the pass depends on.
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys

import pytest

from app.bridge import DatabaseBridge
from database.master_db import MasterDatabase

pytestmark = pytest.mark.unit


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


async def _tool_names_sse(url: str) -> list[str]:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return sorted(t.name for t in (await session.list_tools()).tools)


async def _tool_names_http(url: str) -> list[str]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return sorted(t.name for t in (await session.list_tools()).tools)


@pytest.fixture
def running_server(tmp_path):
    master = MasterDatabase(data_dir=tmp_path / "data", error_logger=None)
    bridge = DatabaseBridge(master_db=master, user_db=None)
    port = _free_port()
    started = json.loads(bridge.startMcpServer(json.dumps({'port': port})))
    assert started['success'], started
    try:
        yield bridge, started['data']
    finally:
        json.loads(bridge.stopMcpServer())
        master.close()


def test_the_status_payload_names_every_way_in(running_server):
    bridge, data = running_server
    port = data['port']
    assert data['sse_url'] == f'http://127.0.0.1:{port}/sse' == data['url']
    assert data['http_url'] == f'http://127.0.0.1:{port}/mcp'
    assert data['stdio_command'][0] == sys.executable
    assert data['stdio_command'][-1] == '--mcp-server'
    assert data['stdio_cwd']
    status = json.loads(bridge.getMcpServerStatus())['data']
    assert status['running'] is True
    for key in ('url', 'sse_url', 'http_url', 'stdio_command', 'stdio_cwd'):
        assert status[key] == data[key], key


def test_both_transports_serve_the_same_tools(running_server):
    _, data = running_server
    via_sse = asyncio.run(_tool_names_sse(data['sse_url']))
    via_http = asyncio.run(_tool_names_http(data['http_url']))
    assert via_sse == via_http
    assert len(via_sse) >= 20, via_sse
    assert 'list_entries' in via_sse and 'get_analytics_overview' in via_sse


def test_the_server_can_be_stopped_and_started_again_in_one_process(tmp_path):
    """FastMCP's Streamable HTTP session manager runs once per instance, and
    FastMCP caches it on the module singleton, so a second start in one
    process failed with "can only be called once per instance" until the
    bridge dropped the cached manager. Save, Reset and a port change all
    restart the server, so this is the common path, not a corner."""
    master = MasterDatabase(data_dir=tmp_path / "data", error_logger=None)
    bridge = DatabaseBridge(master_db=master, user_db=None)
    try:
        for attempt in range(2):
            port = _free_port()
            started = json.loads(bridge.startMcpServer(json.dumps({'port': port})))
            assert started['success'], (attempt, started)
            assert asyncio.run(_tool_names_http(started['data']['http_url']))
            assert json.loads(bridge.stopMcpServer())['data']['running'] is False
    finally:
        json.loads(bridge.stopMcpServer())
        master.close()


def test_the_streamable_http_app_alone_does_not_serve_sse():
    """Control: the SSE route is only there because the server adds it.
    Without the route merge, the pass above would be impossible, so this
    pins that the merge is doing the work rather than FastMCP's default."""
    from mcp_server import mcp
    app = mcp.streamable_http_app()
    paths = {getattr(r, 'path', None) for r in app.router.routes}
    assert '/sse' not in paths and '/mcp' in paths, paths
