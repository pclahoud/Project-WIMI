"""Lifecycle tools for the ``wimi-test`` MCP facade.

Implements the ``start_session`` / ``end_session`` / ``get_session_status``
tools described in ``docs/planning/TEST_INFRASTRUCTURE.md`` §8 (tool ↔
library mapping table). Each tool is a thin shim over the shared
:class:`~wimi_test_mcp.registry.SessionRegistry`: it dispatches the
underlying library call, refreshes the heartbeat where appropriate, and
funnels the result through :mod:`wimi_test_mcp.adapters` so the MCP
client receives a uniform ``{"ok": ..., ...}`` envelope rather than a
raw exception.

Tool registrations happen at import time via the ``@mcp.tool()``
decorator, so this module is imported by :mod:`wimi_test_mcp.server`
solely for its side effect of registering handlers on the shared
``mcp`` instance — there is nothing here that callers need to invoke
directly.
"""

from __future__ import annotations

from wimi_test_mcp.adapters import exception_to_dict, success
from wimi_test_mcp.server import _registry, mcp

__all__ = ["start_session", "end_session", "get_session_status"]


@mcp.tool()
def start_session(scenario: str, seed: str | None = None) -> dict:
    """Start a new test session. Returns a handle string for the session.

    Only one session can be active at a time. Call end_session() before
    starting another. If `seed` is given, the named seeder (e.g., 'minimal',
    'usmle_step1_outline') is applied to the new test user's database
    before the session is returned.
    """
    try:
        handle = _registry.start(scenario=scenario, seed=seed)
        _registry.heartbeat()
        return success({"handle": handle, "status": _registry.status()})
    except Exception as e:
        return exception_to_dict(e)


@mcp.tool()
def end_session() -> dict:
    """End the active test session. Idempotent: returns ok=True if no
    session is active.
    """
    try:
        _registry.end()
        return success({"status": _registry.status()})
    except Exception as e:
        return exception_to_dict(e)


@mcp.tool()
def get_session_status() -> dict:
    """Return the current session status: active, handle, scenario, idle_s."""
    try:
        return success({"status": _registry.status()})
    except Exception as e:
        return exception_to_dict(e)
