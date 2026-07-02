"""Inspection tools for the ``wimi-test`` MCP facade.

Implements the read-only inspection tools described in
``docs/planning/TEST_INFRASTRUCTURE.md`` §6 (capture pipelines) and §8
(tool ↔ library mapping table):

* :func:`get_console_log` — replay buffered console messages emitted by
  the embedded Chromium runtime via
  :class:`wimi_test.capture.console.ConsoleCapture`.
* :func:`get_network_log` — replay buffered network events recorded by
  :class:`wimi_test.capture.network.NetworkCapture`.
* :func:`get_bridge_log` — replay buffered Qt WebChannel bridge calls
  recorded by :class:`wimi_test.capture.bridge.BridgeCapture`. The
  WIMI-side ``@pyqtSlot`` instrumentation that feeds this capture is
  still pending; until that wiring lands the snapshot returns an empty
  list, but the tool itself is fully functional and ready to surface
  events as soon as they start being recorded.
* :func:`dump_dom` — serialise the current page's ``outerHTML`` for ad
  hoc inspection when locator-based assertions fail to match.

Why this split:
    The capture instances are plain in-process Python deques that are
    already thread-safe, so :func:`get_console_log`,
    :func:`get_network_log`, and :func:`get_bridge_log` can read them
    directly from the MCP server thread without going through the
    registry's worker. :func:`dump_dom`, on the other hand, calls into
    Playwright via ``page.eval_js`` — Playwright objects are owned by
    the worker thread, so that call must be marshalled through
    ``_registry.get_executor().run(...)``.

Tool registrations happen at import time via the ``@mcp.tool()``
decorator, so this module is imported by :mod:`wimi_test_mcp.server`
solely for its side effect of registering handlers on the shared
``mcp`` instance — there is nothing here that callers need to invoke
directly.
"""

from __future__ import annotations

from wimi_test_mcp.adapters import exception_to_dict, success
from wimi_test_mcp.server import _registry, mcp

__all__ = ["get_console_log", "get_network_log", "get_bridge_log", "dump_dom"]


@mcp.tool()
def get_console_log(
    level_min: str = "warning", since_ts: float | None = None
) -> dict:
    """Return console log entries from the active session.

    level_min filters by severity: debug < info=log < warning < error < exception.
    since_ts (optional Unix timestamp) returns only entries newer than that.
    """
    try:
        import dataclasses

        session = _registry.get()
        entries = session.captures.console.snapshot(
            level_min=level_min, since_ts=since_ts
        )
        _registry.heartbeat()
        return success(
            {
                "entries": [dataclasses.asdict(e) for e in entries],
                "count": len(entries),
            }
        )
    except Exception as e:
        return exception_to_dict(e)


@mcp.tool()
def get_network_log(
    url_substr: str | None = None, since_ts: float | None = None
) -> dict:
    """Return network event entries from the active session.

    url_substr filters to events whose URL contains the substring.
    since_ts returns only events newer than that.
    """
    try:
        import dataclasses

        session = _registry.get()
        entries = session.captures.network.snapshot(
            url_substr=url_substr, since_ts=since_ts
        )
        _registry.heartbeat()
        return success(
            {
                "entries": [dataclasses.asdict(e) for e in entries],
                "count": len(entries),
            }
        )
    except Exception as e:
        return exception_to_dict(e)


@mcp.tool()
def get_bridge_log(
    method_substr: str | None = None, since_ts: float | None = None
) -> dict:
    """Return bridge call entries from the active session.

    method_substr filters to calls whose method name contains the substring.
    since_ts returns only calls newer than that. Note: the WIMI-side bridge
    slot wiring is deferred; until it lands, this tool returns an empty list.
    """
    try:
        import dataclasses

        session = _registry.get()
        entries = session.captures.bridge.snapshot(
            method_substr=method_substr, since_ts=since_ts
        )
        _registry.heartbeat()
        return success(
            {
                "entries": [dataclasses.asdict(e) for e in entries],
                "count": len(entries),
            }
        )
    except Exception as e:
        return exception_to_dict(e)


@mcp.tool()
def dump_dom() -> dict:
    """Return the current page's outerHTML for inspection. Useful for
    debugging when locators don't match.
    """
    try:
        session = _registry.get()
        executor = _registry.get_executor()
        html = executor.run(
            session.page.eval_js, "document.documentElement.outerHTML"
        )
        _registry.heartbeat()
        return success({"html": html, "size_bytes": len(html) if html else 0})
    except Exception as e:
        return exception_to_dict(e)
