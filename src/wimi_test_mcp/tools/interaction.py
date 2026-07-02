"""Interaction tools for the ``wimi-test`` MCP facade.

Implements the ``click`` / ``fill`` / ``screenshot`` tools described in
``docs/planning/TEST_INFRASTRUCTURE.md`` §8 (tool ↔ library mapping
table). Each tool is a thin shim over the active
:class:`~wimi_test.session.WimiTestSession`: it resolves the session
from the shared :class:`~wimi_test_mcp.registry.SessionRegistry`,
dispatches the underlying Playwright call onto the session's worker
thread (so Playwright's thread-affinity contract is preserved — see
§8 "Threading and the session registry"), refreshes the heartbeat on
success, and funnels the result through
:mod:`wimi_test_mcp.adapters` so the MCP client receives the uniform
``{"ok": ..., ...}`` envelope.

Worker-thread dispatch is mandatory for every Playwright operation:
locator construction (``page.locator(...)``) and any subsequent
locator method (``click``, ``fill``) all touch Playwright objects
that are owned by the executor's single worker thread. The pattern
here is to wrap the entire ``locator(...) -> .method(...)`` chain in
a closure and submit that closure via ``executor.run(...)``, so the
locator never escapes the worker thread.

Screenshots are returned as base64-encoded PNG bytes in the
``screenshot_base64`` field of the response. JSON-RPC (and therefore
MCP) cannot transport raw bytes, so the encoding step is non-optional;
``base64`` is imported lazily inside the screenshot function because
it is only needed there.

Tool registrations happen at import time via the ``@mcp.tool()``
decorator, so this module is imported by :mod:`wimi_test_mcp.server`
solely for its side effect of registering handlers on the shared
``mcp`` instance — there is nothing here that callers need to invoke
directly.
"""

from __future__ import annotations

from wimi_test_mcp.adapters import exception_to_dict, success
from wimi_test_mcp.server import _registry, mcp

__all__ = ["click", "fill", "screenshot"]


@mcp.tool()
def click(
    role: str | None = None,
    name: str | None = None,
    testid: str | None = None,
    css: str | None = None,
    timeout_ms: int | None = None,
) -> dict:
    """Click an element. Exactly one of (role+name) / testid / css.

    Auto-waits for the element to be visible+enabled before clicking.

    The locator is constructed and clicked inside a single closure
    submitted to the session's worker thread, so neither the locator
    nor the click itself ever touches Playwright objects from the
    wrong thread.

    Parameters
    ----------
    role:
        ARIA role (e.g. ``"button"``). Must be paired with ``name``.
    name:
        Accessible name. Used together with ``role``.
    testid:
        ``data-testid`` attribute value.
    css:
        Raw CSS selector. Use sparingly; prefer role+name or testid
        for resilience against markup churn.
    timeout_ms:
        Per-call timeout in milliseconds. ``None`` defers to the
        library default.

    Returns
    -------
    dict
        ``success({"clicked": True}, captures=...)`` on success, or
        an :func:`~wimi_test_mcp.adapters.exception_to_dict` payload
        on failure.
    """
    try:
        session = _registry.get()
        executor = _registry.get_executor()

        def _click() -> None:
            loc = session.page.locator(
                role=role, name=name, testid=testid, css=css
            )
            loc.click(timeout_ms=timeout_ms)

        executor.run(_click)
        _registry.heartbeat()
        since_ts = _registry.consume_capture_window()
        return success(
            {"clicked": True}, captures=session.captures, since_ts=since_ts
        )
    except Exception as e:
        return exception_to_dict(e)


@mcp.tool()
def fill(
    value: str,
    role: str | None = None,
    name: str | None = None,
    testid: str | None = None,
    css: str | None = None,
    timeout_ms: int | None = None,
) -> dict:
    """Fill a text field with the given value. Replaces existing content.

    Auto-waits for the element to be visible+enabled. Like
    :func:`click`, the locator and the fill call run inside a single
    closure on the worker thread.

    Parameters
    ----------
    value:
        Text to enter. Replaces any existing field content.
    role, name, testid, css:
        Locator selectors — exactly one strategy should be specified.
        See :func:`click` for details.
    timeout_ms:
        Per-call timeout in milliseconds. ``None`` defers to the
        library default.

    Returns
    -------
    dict
        ``success({"filled": True}, captures=...)`` on success, or
        an :func:`~wimi_test_mcp.adapters.exception_to_dict` payload
        on failure.
    """
    try:
        session = _registry.get()
        executor = _registry.get_executor()

        def _fill() -> None:
            loc = session.page.locator(
                role=role, name=name, testid=testid, css=css
            )
            loc.fill(value, timeout_ms=timeout_ms)

        executor.run(_fill)
        _registry.heartbeat()
        since_ts = _registry.consume_capture_window()
        return success(
            {"filled": True}, captures=session.captures, since_ts=since_ts
        )
    except Exception as e:
        return exception_to_dict(e)


@mcp.tool()
def screenshot(full_page: bool = False) -> dict:
    """Take a screenshot of the current page.

    Returns base64-encoded PNG bytes in the ``screenshot_base64``
    field — JSON-RPC cannot transport raw bytes, so encoding is
    mandatory. Use ``full_page=True`` for the full scrollable page
    rather than just the viewport.

    The underlying ``WimiPage.screenshot(path: Path | None = None, *,
    full_page: bool = False)`` is invoked with ``path=None`` so it
    returns the PNG bytes in-memory rather than writing to disk; the
    bytes are then base64-encoded for the MCP response. The
    Playwright call runs on the session's worker thread.

    Parameters
    ----------
    full_page:
        If ``True``, capture the entire scrollable page; otherwise
        only the current viewport.

    Returns
    -------
    dict
        ``success({"screenshot_base64": <str>, "size_bytes": <int>},
        captures=...)`` on success, or an
        :func:`~wimi_test_mcp.adapters.exception_to_dict` payload on
        failure. ``screenshot_base64`` is the empty string and
        ``size_bytes`` is ``0`` if the underlying call returned no
        bytes.
    """
    try:
        import base64

        session = _registry.get()
        executor = _registry.get_executor()
        # WimiPage.screenshot signature: (path: Path | None = None, *,
        # full_page: bool = False). Pass None positionally and
        # full_page as a keyword so the bytes are returned in-memory.
        png = executor.run(session.page.screenshot, None, full_page=full_page)
        encoded = base64.b64encode(png).decode("ascii") if png else ""
        _registry.heartbeat()
        since_ts = _registry.consume_capture_window()
        return success(
            {
                "screenshot_base64": encoded,
                "size_bytes": len(png) if png else 0,
            },
            captures=session.captures,
            since_ts=since_ts,
        )
    except Exception as e:
        return exception_to_dict(e)
