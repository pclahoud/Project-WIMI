"""MCP navigation tools: ``navigate_to``, ``wait_for``, and ``eval_js``.

This module implements the navigation slice of the MCP tool surface
described in ``docs/planning/TEST_INFRASTRUCTURE.md`` Section 8 ("MCP
facade structure"). It exposes three handlers registered with the shared
:data:`wimi_test_mcp.server.mcp` instance:

- :func:`navigate_to` — drive the active session to a logical route
  name registered in :mod:`wimi_test.routes` and (by default) wait for
  the ``window._wimiApi`` QWebChannel bridge to attach.
- :func:`wait_for` — block until a single locator (selected by exactly
  one of role+name / test-id / CSS) becomes visible.
- :func:`eval_js` — evaluate a JavaScript expression in the page
  context. Gated by :attr:`wimi_test.config.TestConfig.allow_eval_js`
  (default ``True`` in local test mode); a stricter config can disable
  it so MCP-driven sessions cannot run arbitrary JS — see Section 9
  of the design doc.

Worker-thread dispatch
----------------------

Every Playwright-touching operation in this module is dispatched onto
the registry's :class:`~wimi_test._internal.async_bridge.SessionThreadExecutor`
via ``_registry.get_executor().run(...)``. Playwright's sync API has a
hard "use one thread for the lifetime of the objects" contract, and the
FastMCP runtime invokes tool handlers on its own dispatcher pool, so we
must hop onto the executor's single worker thread (the same one that
ran ``session.start()``) before touching any Playwright object. The
handlers themselves stay on the dispatcher and only do registry calls,
``executor.run(...)`` hops, and JSON serialisation through
:func:`~wimi_test_mcp.adapters.success` /
:func:`~wimi_test_mcp.adapters.exception_to_dict`.

The other invariant every handler upholds is calling
:meth:`~wimi_test_mcp.registry.SessionRegistry.heartbeat` after a
successful operation so the registry's idle-timeout clock keeps moving
with active use. Failures skip the heartbeat — by definition the call
did not consume the session.
"""

from __future__ import annotations

from wimi_test_mcp.adapters import exception_to_dict, success
from wimi_test_mcp.server import _registry, mcp

__all__ = ["navigate_to", "wait_for", "eval_js"]


@mcp.tool()
def navigate_to(route: str) -> dict:
    """Navigate the active session to a logical route name.

    Logical route names (e.g. ``"dashboard"``, ``"entry-form"``,
    ``"tree-editor"``) are resolved by :func:`wimi_test.routes.resolve`
    against the session's app root. The underlying
    :meth:`wimi_test.page.WimiPage.goto` waits for the QWebChannel
    bridge (``window._wimiApi``) to be defined before returning, so
    follow-up tool calls can drive the UI without racing the
    ``src/web/js/api/_loader.js`` handshake.

    The actual ``page.goto`` call is dispatched onto the registry's
    worker thread to satisfy Playwright's thread-affinity contract.

    Parameters
    ----------
    route:
        Logical route name registered in :mod:`wimi_test.routes`.

    Returns
    -------
    dict
        On success, the standard ``success`` envelope with
        ``data={"route": <route>}`` and recent capture activity
        attached. On failure, an ``exception_to_dict`` envelope.
    """
    try:
        session = _registry.get()
        session_executor = _registry.get_executor()
        session_executor.run(session.page.goto, route)
        _registry.heartbeat()
        since_ts = _registry.consume_capture_window()
        return success(
            {"route": route}, captures=session.captures, since_ts=since_ts
        )
    except Exception as e:  # noqa: BLE001 - tool boundary serialises everything
        return exception_to_dict(e)


@mcp.tool()
def wait_for(
    role: str | None = None,
    name: str | None = None,
    testid: str | None = None,
    css: str | None = None,
    timeout_ms: int = 5000,
) -> dict:
    """Wait for an element selected by one strategy to become visible.

    Exactly one of the strategy groups must be supplied:
    ``(role, name)`` together, ``testid`` alone, or ``css`` alone. The
    locator is built via :meth:`wimi_test.page.WimiPage.locator`, which
    delegates to :func:`wimi_test.locator.build_locator` and enforces
    the role+name -> testid -> CSS preference order from
    ``docs/testing/UI_AUDIT.md``. Visibility is checked through
    :meth:`wimi_test.locator.WimiLocator.expect_visible` with
    ``timeout_ms`` forwarded verbatim.

    The locator construction and visibility wait both run on the
    registry's worker thread so Playwright never sees off-thread access.

    Parameters
    ----------
    role, name:
        ARIA role + accessible name pair. Must be supplied together.
    testid:
        Value of the ``data-testid`` attribute.
    css:
        Raw CSS selector. Use only when role/testid are not feasible.
    timeout_ms:
        Maximum milliseconds to wait for visibility. Defaults to 5000.

    Returns
    -------
    dict
        On success, ``success`` envelope with ``data={"matched": True}``
        and recent capture activity attached. On timeout or other
        failure, an ``exception_to_dict`` envelope (commonly wrapping a
        Playwright ``TimeoutError`` or
        :class:`~wimi_test.errors.LocatorAmbiguous`).
    """
    try:
        session = _registry.get()
        executor = _registry.get_executor()

        def _wait() -> None:
            loc = session.page.locator(
                role=role,
                name=name,
                testid=testid,
                css=css,
            )
            loc.expect_visible(timeout_ms=timeout_ms)

        executor.run(_wait)
        _registry.heartbeat()
        since_ts = _registry.consume_capture_window()
        return success(
            {"matched": True}, captures=session.captures, since_ts=since_ts
        )
    except Exception as e:  # noqa: BLE001 - tool boundary serialises everything
        return exception_to_dict(e)


@mcp.tool()
def eval_js(expression: str, await_promise: bool = False) -> dict:
    """Evaluate a JavaScript expression in the active page context.

    Thin wrapper over :meth:`wimi_test.page.WimiPage.eval_js`, which is
    itself gated by :attr:`wimi_test.config.TestConfig.allow_eval_js`.
    The default in local test mode is ``True`` (see
    ``TEST_INFRASTRUCTURE.md`` Section 9), but a stricter config can
    disable it to forbid arbitrary JS execution from MCP clients —
    in that case this tool returns an
    :class:`~wimi_test.errors.WimiTestError` envelope.

    Be cautious with mutating expressions: they run with the same
    privilege as the page itself, including the QWebChannel bridge.
    Read-only expressions (DOM queries, ``window.api`` introspection)
    are the intended use case.

    Parameters
    ----------
    expression:
        JavaScript source to evaluate.
    await_promise:
        When ``True``, forwarded as ``awaitPromise`` to CDP. If
        ``expression`` evaluates to a Promise, CDP awaits the
        resolution and returns the resolved value rather than the
        Promise itself. Required when calling QWebChannel slot proxies
        (``window.api._bridge.<slot>(...)``) or any async IIFE; without
        it, FastMCP receives an unresolved Promise and ships an empty
        ``{}`` value back. Defaults to ``False`` to preserve the
        synchronous-evaluation contract for read-only expressions.

    Returns
    -------
    dict
        On success, ``success`` envelope with
        ``data={"result": <evaluated value>}``. The value must be
        JSON-serialisable for FastMCP to ship it. On failure, an
        ``exception_to_dict`` envelope.
    """
    try:
        session = _registry.get()
        executor = _registry.get_executor()
        result = executor.run(
            session.page.eval_js, expression, await_promise=await_promise
        )
        _registry.heartbeat()
        since_ts = _registry.consume_capture_window()
        return success(
            {"result": result}, captures=session.captures, since_ts=since_ts
        )
    except Exception as e:  # noqa: BLE001 - tool boundary serialises everything
        return exception_to_dict(e)
