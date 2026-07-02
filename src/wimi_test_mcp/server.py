"""FastMCP entry point for the ``wimi-test`` server.

This module implements the MCP facade described in
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 8 ("MCP facade structure").
It exposes WIMI test-automation primitives — spawning the app in test
mode, driving the UI through Playwright over CDP, and inspecting
captured artefacts — to MCP clients such as Claude Code.

At-most-one-session constraint
------------------------------

The facade enforces a single live :class:`~wimi_test.session.WimiTestSession`
per server process. Bringing up a WIMI subprocess, attaching Playwright
over CDP, and provisioning a per-test master-DB user is expensive and
strongly thread-affine; multiplexing it would gain nothing and would
violate Playwright's "use one thread for the lifetime of the objects"
contract. Callers must :func:`end_session` (T5.5) before starting a
fresh one. The shared :data:`_registry` raises
:class:`~wimi_test.errors.WimiTestError` if a second start is attempted
while a session is live.

Threading model
---------------

MCP tool handlers run on the FastMCP async dispatcher. Every
Playwright-touching operation — ``session.start``/``session.stop`` and
any seeder run against ``session.user.db`` — is dispatched onto the
single-worker :class:`~wimi_test._internal.async_bridge.SessionThreadExecutor`
owned by the registry, so all such work happens on the same OS thread
that owns the Playwright objects. Tool handlers themselves stay on the
async dispatcher and only do registry calls + JSON serialisation.

Module structure
----------------

The :data:`mcp` :class:`~mcp.server.fastmcp.FastMCP` instance and the
:data:`_registry` :class:`~wimi_test_mcp.registry.SessionRegistry` are
defined at module scope so that tool modules in
``wimi_test_mcp.tools.*`` can import them and register handlers via
``@mcp.tool()`` decorators that close over the shared registry. Those
tool modules land in T5.5 (lifecycle), T5.6 (navigation), T5.7
(interaction), and T5.8 (inspection); see the import block at the
bottom of this file.
"""

from __future__ import annotations

import atexit
import logging

from mcp.server.fastmcp import FastMCP

from wimi_test_mcp.registry import SessionRegistry

__all__ = ["mcp", "_registry", "run"]


_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level FastMCP instance
# ---------------------------------------------------------------------------
#
# Module-level so that tool modules in ``wimi_test_mcp.tools.*`` can do
# ``from wimi_test_mcp.server import mcp`` and register handlers with
# ``@mcp.tool()``. The instructions string is shown to MCP clients on
# connect; it points readers at the design doc rather than restating it.

mcp = FastMCP(
    "wimi-test",
    instructions=(
        "WIMI test automation server. Provides tools to spawn WIMI in test mode, "
        "drive the UI via Playwright/CDP, and inspect captures. At most one active "
        "session per server. See docs/planning/TEST_INFRASTRUCTURE.md §8."
    ),
)


# ---------------------------------------------------------------------------
# Module-level SessionRegistry
# ---------------------------------------------------------------------------
#
# Created on import so it is shared across every tool module. The
# registry owns the single-worker executor that serialises Playwright
# calls; see ``wimi_test_mcp/registry.py`` and TEST_INFRASTRUCTURE.md §8.

_registry = SessionRegistry()


# ---------------------------------------------------------------------------
# Process-exit cleanup
# ---------------------------------------------------------------------------


def _atexit_cleanup() -> None:
    """Best-effort teardown of the active session at process exit.

    Invoked via :mod:`atexit` so a SIGTERM, ``Ctrl+C``, or unhandled
    exception in the MCP runtime does not leak a WIMI subprocess or a
    Playwright worker thread. The registry's :meth:`end` is itself
    idempotent and already swallows individual cleanup failures, but we
    wrap the whole call once more here because :mod:`atexit` handlers
    must never raise — an exception here would be printed by the
    interpreter on shutdown and obscure the real cause.
    """
    try:
        _registry.end()
    except Exception as exc:  # noqa: BLE001 - atexit handlers must not raise
        _logger.warning("wimi-test atexit cleanup raised: %s", exc)


atexit.register(_atexit_cleanup)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Run the wimi-test MCP server over stdio."""
    mcp.run(transport="stdio")


# Tool modules are imported here so their @mcp.tool() registrations
# take effect. The import has side effects (decorator runs against `mcp`)
# so noqa: F401 is required.
from wimi_test_mcp.tools import lifecycle, navigation, interaction, inspection  # noqa: F401


if __name__ == "__main__":
    run()
