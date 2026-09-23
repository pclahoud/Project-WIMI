"""WIMI-aware wrapper over a pychrome ``Tab`` (via :class:`WimiTab`).

This module implements :class:`WimiPage`, the test-side handle that knows
how to navigate WIMI's logical route names (``"dashboard"``,
``"entry-form"``, ...) and how to wait for the QWebChannel bridge to be
ready before tests interact with the UI. See
:doc:`docs/planning/PYCHROME_MIGRATION.md` Section 5.2 ("Page wrapper")
for the detailed design.

The **public API is preserved** from the previous Playwright-based
implementation -- ``goto``, ``locator``, ``screenshot``, ``eval_js``,
and ``wait_for_bridge_call`` keep their signatures and contracts so the
rest of the library and the ``wimi-test`` MCP tools do not need to
change. The only internals that change are the underlying CDP client:
Playwright is gone, replaced by :class:`wimi_test._internal.cdp_client.WimiTab`,
which speaks the Chrome DevTools Protocol directly via :mod:`pychrome`.

The escape-hatch property has been **renamed**: the previous ``pw_page``
property (Playwright handle) is now ``tab`` (the underlying
:class:`WimiTab`). ``pw_page`` was an undocumented escape hatch that
nothing in ``tests/wimi_test/scenarios/*`` or the MCP tool layer reaches
into, so the rename is safe per ``PYCHROME_MIGRATION.md`` Section 6.

The wrapper remains intentionally thin: route resolution is delegated
to :mod:`wimi_test.routes`, locator construction to
:mod:`wimi_test.locator`, configuration to :mod:`wimi_test.config`, and
the underlying browser automation to :mod:`pychrome` (through the
:class:`WimiTab` seam in :mod:`wimi_test._internal.cdp_client`). No
import of :mod:`playwright` appears anywhere in this module or the
modules it depends on at runtime.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlencode

from wimi_test._internal.cdp_client import WimiTab
from wimi_test.config import TestConfig
from wimi_test.errors import (
    BridgeCallsUnavailable,
    BridgeCallTimeout,
    WimiTestError,
)
from wimi_test.locator import WimiLocator, build_locator
from wimi_test.routes import resolve as resolve_route

__all__ = ["WimiPage"]


# JS expression used to read WIMI's bridge-call ring buffer. Mirrors the
# template in :mod:`wimi_test.capture.bridge` on purpose rather than
# importing it: the two are independent consumers of the same slot and
# the capture module must stay free to change its polling shape (it runs
# on a daemon thread with its own cursor) without silently changing what
# a scenario's ``wait_for_bridge_call`` observes.
#
# Wrapped in an async IIFE because ``api.getTestModeBridgeCalls`` is an
# async wrapper over a QWebChannel slot, which always returns a Promise;
# callers pass ``await_promise=True`` so CDP resolves it for us. Returns
# ``null`` -- not ``'[]'`` -- when the slot is absent, so the caller can
# tell "not instrumented" from "instrumented, nothing recorded".
#
# The global probed is ``window.api`` (the long-lived public name set by
# ``_loader.js``), not ``window._wimiApi`` (the bootstrap-only name the
# loader deletes on completion).
#
# Worlds note (TEST_INFRASTRUCTURE.md 12a): this is safe to evaluate
# over CDP even though the buffer lives on the Qt side. Nothing here
# reads a global written by ``QWebEnginePage.runJavaScript`` -- it calls
# a QWebChannel slot proxy installed by the page's own scripts, and the
# buffer itself is marshalled back as a JSON string over the channel.
_BRIDGE_CALLS_JS_TEMPLATE = (
    "(async () => {{ "
    "if (window.api && typeof window.api.getTestModeBridgeCalls === 'function') {{ "
    "  return await window.api.getTestModeBridgeCalls({since_ts}); "
    "}} "
    "return null; "
    "}})()"
)


class WimiPage:
    """WIMI-aware wrapper over a :class:`WimiTab`.

    Adds three pieces of WIMI-specific knowledge on top of the bare CDP
    tab:

    1. **Logical routes.** :meth:`goto` accepts a route name registered
       in :data:`wimi_test.routes.ROUTES` rather than a raw URL.
    2. **Bridge readiness.** :meth:`goto` waits for ``window.api``
       to be defined so tests don't race against the QWebChannel
       handshake performed by ``src/web/js/api/_loader.js``. (The
       loader builds the API at ``window._wimiApi`` during bootstrap
       and promotes it to ``window.api`` on completion.)
    3. **Locator policy.** :meth:`locator` funnels through
       :func:`~wimi_test.locator.build_locator`, which enforces the
       role+name -> testid -> CSS preference order documented in
       ``docs/testing/UI_AUDIT.md``.
    """

    def __init__(
        self,
        tab: WimiTab,
        *,
        app_root: Path,
        config: TestConfig | None = None,
    ) -> None:
        """Store the wrapped tab, repository root, and resolved config.

        Parameters
        ----------
        tab:
            The underlying CDP tab wrapper. Replaces the Playwright
            ``Page`` handle from the previous implementation.
        app_root:
            The WIMI repository root, forwarded to
            :func:`wimi_test.routes.resolve` to locate HTML files under
            ``<app_root>/src/web/html/``.
        config:
            The test configuration. Defaults to
            :meth:`TestConfig.resolve` (which layers env vars over the
            dataclass defaults) when ``None``.
        """
        self._tab: WimiTab = tab
        self._app_root: Path = app_root
        self._config: TestConfig = config if config is not None else TestConfig.resolve()

    @property
    def tab(self) -> WimiTab:
        """The wrapped :class:`WimiTab`. Exposed as an escape hatch.

        Tests should prefer the wrapper methods, but a few advanced
        cases (e.g. driving a CDP domain not yet covered here, or
        registering a raw event listener) need direct access to the
        underlying tab. Renamed from the previous ``pw_page`` property
        as part of the pychrome migration.
        """
        return self._tab

    def goto(
        self,
        route: str,
        *,
        query: Optional[Mapping[str, object]] = None,
        wait_for_bridge: bool = True,
    ) -> None:
        """Navigate to a logical route, optionally awaiting bridge readiness.

        The route name is resolved through
        :func:`wimi_test.routes.resolve` against ``self._app_root`` and
        navigated via ``Page.navigate``. When ``wait_for_bridge`` is
        ``True`` (the default) this method then blocks until
        ``typeof window.api === "object"``, which is the signal
        published by ``src/web/js/api/_loader.js`` once the QWebChannel
        handshake has completed and every API module is attached. The
        wait uses :attr:`TestConfig.timeout_default_ms` so it converges
        with the rest of the library.

        ``Page.navigate`` returns immediately; it does not block until
        load complete. The :meth:`WimiTab.wait_for_wimi_api` step is
        what gates "page is interactable". When ``wait_for_bridge=False``
        the caller may need to add their own settle wait before
        interacting with the page.

        The bridge readiness probe targets ``window.api`` (the long-lived
        public name set by ``_loader.js``) — see
        :meth:`WimiTab.wait_for_wimi_api` for the rationale.

        Parameters
        ----------
        route:
            Logical route name, e.g. ``"dashboard"`` or ``"entry-form"``.
        query:
            Optional mapping of query parameters appended to the URL as
            ``?k1=v1&k2=v2``. Required by routes whose page-side JS
            short-circuits without one (e.g. ``question_entry.html``
            redirects to ``index.html`` if no ``session_id`` is present).
            Values go through :func:`urllib.parse.urlencode`, which
            handles escaping for arbitrary scalars.
        wait_for_bridge:
            When ``True`` (default), wait for ``window.api`` to be
            defined after navigation. Set to ``False`` for the rare
            case where the test wants to inspect the page *before* the
            bridge attaches (e.g. error pages, very fast assertions).

        Raises
        ------
        ValueError
            If ``route`` is not a registered route (propagated from
            :func:`wimi_test.routes.resolve`).
        WimiTestError
            If ``wait_for_bridge`` is ``True`` and ``window.api``
            does not become an object within
            :attr:`TestConfig.timeout_default_ms` (propagated from
            :meth:`WimiTab.wait_for_wimi_api`).
        """
        url = resolve_route(route, self._app_root)
        if query:
            url = f"{url}?{urlencode(query)}"
        self._tab.Page.navigate(url=url)
        if wait_for_bridge:
            # WimiTab.wait_for_wimi_api already raises WimiTestError on
            # timeout with the last-observed type baked into the message.
            self._tab.wait_for_wimi_api(timeout_ms=self._config.timeout_default_ms)

    def wait_for_timeout(self, ms: int) -> None:
        """Block for ``ms`` milliseconds. Test-time settle wait.

        Mirrors Playwright's ``page.wait_for_timeout(ms)`` so existing
        scenarios that used the Playwright API in their pre-pychrome
        form keep reading the same way. Internally this is just
        :func:`time.sleep` — the only reason to wrap it is to keep
        callers from importing :mod:`time` everywhere and to give us
        a single place to add instrumentation later (e.g. logging
        long sleeps as a code smell).

        Prefer :meth:`wait_for_bridge_call` or an explicit locator
        :meth:`expect_visible` over a fixed sleep wherever possible —
        a sleep that's too short is flaky, a sleep that's too long
        wastes CI time. This method exists for the residual cases
        where a real signal isn't yet plumbed through.
        """
        time.sleep(ms / 1000.0)

    def locator(
        self,
        *,
        role: str | None = None,
        name: str | None = None,
        testid: str | None = None,
        css: str | None = None,
    ) -> WimiLocator:
        """Construct a :class:`WimiLocator` from exactly one strategy.

        Delegates to :func:`wimi_test.locator.build_locator`, which
        enforces the rule that the caller must supply *exactly one* of
        ``(role+name)`` / ``testid`` / ``css``. The factory accepts any
        object that exposes ``Runtime.evaluate`` and
        ``Input.dispatchMouseEvent``; :class:`WimiTab` satisfies that
        duck type via its property delegates.

        Raises
        ------
        ValueError
            If zero or multiple strategies are supplied, or if ``role``
            and ``name`` are not paired (propagated from
            :func:`build_locator`).
        """
        return build_locator(
            self._tab,
            role=role,
            name=name,
            testid=testid,
            css=css,
        )

    def screenshot(
        self,
        path: Path | None = None,
        *,
        full_page: bool = False,
        timeout_ms: int | None = None,
    ) -> bytes:
        """Capture a PNG screenshot of the page.

        Returns the screenshot's raw PNG bytes. When ``path`` is given,
        the bytes are also written to disk at that location; this
        matches the previous Playwright contract.

        The CDP ``Page.captureScreenshot`` command returns
        ``{"data": "<base64 PNG>"}``; we decode the ``data`` field to
        bytes and (optionally) persist them.

        Parameters
        ----------
        path:
            Optional filesystem path. When supplied, the PNG is also
            written there in addition to being returned.
        full_page:
            Accepted for API compatibility but currently treated as a
            viewport-only capture. CDP's ``captureScreenshot`` does not
            natively offer a "full page" mode the way Playwright does;
            implementing it requires resizing the viewport (or
            stitching multiple captures) before invoking the command.
            # TODO(post-v1): full_page support requires DOM.getBoxModel
            # + multi-capture stitching; see PYCHROME_MIGRATION.md §5.2.
        timeout_ms:
            Bounded wait on the CDP RPC. Forwarded to pychrome as
            ``_timeout`` (in seconds). When ``None`` (default), pychrome
            uses its method-call default. Failure-attachment paths
            should pass a tight value (e.g. 10s) so a stalled CDP
            response doesn't hang the test runner indefinitely.
        """
        # If this ever hangs rather than returning, suspect the target
        # before suspecting the command. ``captureScreenshot`` waits on a
        # compositor frame, and a ``QWebEnginePage`` with no view
        # attached never produces one -- it is listed by Qt's CDP
        # endpoint like any other page and answers every other command
        # normally, so the session looks healthy right up until you ask
        # it for pixels. :meth:`WimiBrowser.primary_tab` now refuses a
        # target that reports ``document.visibilityState !== "visible"``
        # for exactly this reason.
        kwargs = {"format": "png"}
        if timeout_ms is not None:
            kwargs["_timeout"] = timeout_ms / 1000.0
        response = self._tab.Page.captureScreenshot(**kwargs)
        # CDP responses have shape {"data": "<base64 PNG>"}; tolerate a
        # missing key by falling through to an empty bytes payload so
        # the failure surfaces at the call site rather than as a
        # KeyError deep inside this method.
        encoded = response.get("data", "") if isinstance(response, dict) else ""
        png_bytes = base64.b64decode(encoded)
        if path is not None:
            Path(path).write_bytes(png_bytes)
        return png_bytes

    def eval_js(self, expression: str, *, await_promise: bool = False) -> object:
        """Evaluate ``expression`` as JS in the page's main world.

        This escape hatch is gated by
        :attr:`TestConfig.allow_eval_js`. The default is ``True`` (test
        infra is local-only and opt-in, see
        ``TEST_INFRASTRUCTURE.md`` Section 9), but a stricter config
        can disable it so MCP-driven sessions cannot run arbitrary JS.

        Parameters
        ----------
        expression
            JS source. Treated as an expression; multi-statement code
            should be wrapped in an IIFE.
        await_promise
            When ``True``, forwarded as ``awaitPromise`` to CDP. If
            ``expression`` evaluates to a Promise, CDP awaits it and
            returns the resolved value. Required when the expression
            calls a QWebChannel slot proxy (which always returns a
            Promise).

        Returns
        -------
        object
            Whatever :meth:`WimiTab.evaluate` returns for
            ``expression`` -- the JSON round-tripped value when the
            evaluation succeeds.

        Raises
        ------
        WimiTestError
            If :attr:`TestConfig.allow_eval_js` is ``False``, **or** if
            the JS evaluation produced an ``exceptionDetails`` block
            (propagated from :meth:`WimiTab.evaluate`).
        """
        if not self._config.allow_eval_js:
            raise WimiTestError(
                "eval_js is disabled by TestConfig.allow_eval_js=False"
            )
        # WimiTab.evaluate already raises WimiTestError on
        # exceptionDetails, so we just forward the result.
        return self._tab.evaluate(expression, await_promise=await_promise)

    # ------------------------------------------------------------------
    # Bridge-call synchronization
    # ------------------------------------------------------------------

    def mark_bridge_calls(self) -> float:
        """Return a cursor to hand to :meth:`wait_for_bridge_call`.

        Capture this **before** triggering the action, then pass it as
        ``since_ts``::

            mark = page.mark_bridge_calls()
            save_button.click()
            page.wait_for_bridge_call("createQuestionEntry", since_ts=mark)

        Doing it in that order is what makes the wait un-racy: a call
        that completes between the click and the wait is still matched,
        because the cursor predates the click. Taking the cursor inside
        :meth:`wait_for_bridge_call` (what happens when ``since_ts`` is
        omitted) leaves a window in which a very fast call can be missed.

        The cursor is simply :func:`time.time` on the driver side. WIMI
        stamps each buffered call with its own :func:`time.time`, and
        the driver and the app under test are the same process tree on
        the same host reading the same system clock, so the two are
        directly comparable. ``tests/wimi_test/scenarios`` never runs
        against a remote WIMI; if that ever changes, this is the seam
        to change with it.
        """
        return time.time()

    def get_bridge_calls(self, *, since_ts: float = 0.0) -> list[dict]:
        """Fetch buffered WIMI-side bridge calls recorded after ``since_ts``.

        Returns the raw dict shape produced by
        ``app.bridge_test_instrumentation.get_test_mode_bridge_calls``
        (``timestamp`` / ``method`` / ``args_summary`` /
        ``result_summary`` / ``duration_ms`` / ``error``), oldest first.

        This is a *direct* read of the WIMI-side ring buffer through the
        ``getTestModeBridgeCalls`` slot, not a read of
        :class:`~wimi_test.capture.bridge.BridgeCapture`'s mirror. The
        two are independent consumers of the same buffer -- the producer
        filters by the ``since_ts`` each caller passes and never drains
        anything -- so polling here does not disturb the capture stream
        feeding failure reports.

        Raises
        ------
        BridgeCallsUnavailable
            If ``window.api.getTestModeBridgeCalls`` is not exposed on
            the page (the JS probe returns ``null``).
        WimiTestError
            If the evaluation itself fails, or the slot returns
            something other than a JSON list.
        """
        js = _BRIDGE_CALLS_JS_TEMPLATE.format(since_ts=float(since_ts))
        result = self._tab.evaluate(js, await_promise=True)

        if result is None:
            raise BridgeCallsUnavailable(
                "window.api.getTestModeBridgeCalls is not exposed on this "
                "page, so no bridge call can ever be observed. WIMI records "
                "slot calls only when it was launched with --test-mode "
                "(@instrumented_slot checks test_mode.is_active() at "
                "decoration time), and the slot only appears once "
                "window.api is built by src/web/js/api/_loader.js."
            )

        if isinstance(result, str):
            try:
                entries = json.loads(result)
            except json.JSONDecodeError as exc:
                raise WimiTestError(
                    "getTestModeBridgeCalls returned a non-JSON string: "
                    f"{result[:200]!r}"
                ) from exc
        else:
            # Tolerated for the same reason BridgeCapture tolerates it:
            # a returnByValue round trip could hand back the decoded list.
            entries = result

        if not isinstance(entries, list):
            raise WimiTestError(
                "getTestModeBridgeCalls returned an unexpected payload "
                f"type {type(entries).__name__!r}; expected a JSON list."
            )
        return [e for e in entries if isinstance(e, dict)]

    def wait_for_bridge_call(
        self,
        method: str,
        *,
        timeout_ms: int = 5000,
        since_ts: float | None = None,
        poll_interval_ms: int = 50,
    ) -> dict:
        """Wait until WIMI records a completed call to the slot ``method``.

        Used when JS-side code defers a database write through the
        bridge and the test needs to synchronize on its completion
        before asserting on the resulting state. It replaces the fixed
        ``wait_for_timeout`` that scenarios used to sit behind such a
        write: a sleep guesses how long the round trip takes and cannot
        tell "slow" from "never happened", while this observes the call
        itself.

        What counts as "recorded" is precise: ``@instrumented_slot``
        appends its buffer entry **after** the wrapped slot returns, so
        a match means the Python side of the call has finished, not
        merely that JS dispatched it. A slot that raised is recorded too
        (with ``error: True``) and matches -- the call *did* happen, and
        a caller that cares can inspect the returned record.

        Parameters
        ----------
        method:
            Exact slot name as PyQt sees it, e.g.
            ``"createQuestionEntry"`` (not the ``api.*`` JS wrapper
            name, though for WIMI they are spelled the same).
        timeout_ms:
            Budget for the whole wait.
        since_ts:
            Only calls recorded strictly after this cursor match. Pass
            the value of a :meth:`mark_bridge_calls` taken *before* the
            triggering action. When omitted, the cursor is taken now,
            which is only safe when the action has not been dispatched
            yet (e.g. a wait armed before a later step) -- otherwise a
            fast call can land in the gap and never be seen.
        poll_interval_ms:
            Gap between polls of the WIMI-side buffer.

        Returns
        -------
        dict
            The matched call record. Keys are ``timestamp``,
            ``method``, ``args_summary``, ``result_summary``,
            ``duration_ms`` and ``error``.

        Raises
        ------
        BridgeCallTimeout
            If no matching call is recorded within ``timeout_ms``. The
            message lists the slot names that *were* recorded in the
            same window, which is what tells a reader whether the action
            fired at all.
        BridgeCallsUnavailable
            If the WIMI-side instrumentation is not reachable. This is
            deliberately **not** a timeout: a helper that cannot see any
            call must say so rather than report the awaited one as
            missing.
        """
        cursor = self.mark_bridge_calls() if since_ts is None else float(since_ts)
        deadline = time.time() + (timeout_ms / 1000.0)
        observed: list[str] = []
        seen_ts: float = cursor

        while True:
            # ``get_bridge_calls`` raises BridgeCallsUnavailable, which
            # we let through untouched -- see the docstring.
            for entry in self.get_bridge_calls(since_ts=seen_ts):
                name = entry.get("method")
                try:
                    ts = float(entry.get("timestamp", 0.0))
                except (TypeError, ValueError):
                    ts = 0.0
                if ts > seen_ts:
                    seen_ts = ts
                if name == method:
                    return entry
                if isinstance(name, str):
                    observed.append(name)

            if time.time() >= deadline:
                break
            # Sleep no longer than the remaining budget so the wait
            # never overshoots ``timeout_ms`` by a whole poll interval.
            time.sleep(min(poll_interval_ms / 1000.0, max(deadline - time.time(), 0.0)))

        if observed:
            # Preserve order of first appearance while de-duplicating, so
            # a chatty page does not bury the signal under repeats.
            unique: list[str] = []
            for name in observed:
                if name not in unique:
                    unique.append(name)
            seen = ", ".join(unique[:15])
            if len(unique) > 15:
                seen += f", ... (+{len(unique) - 15} more)"
            detail = (
                f"{len(observed)} other bridge call(s) were recorded in the "
                f"same window: {seen}. The page was alive and talking to the "
                f"bridge, so the action that should have issued {method!r} "
                f"either never ran or was rejected before reaching the bridge."
            )
        else:
            detail = (
                "No bridge calls at all were recorded in that window. Either "
                "the page is idle (the triggering action never ran) or it "
                "never finished loading."
            )

        raise BridgeCallTimeout(
            f"Bridge call {method!r} was never recorded within {timeout_ms} ms. "
            + detail,
            method=method,
            timeout_ms=timeout_ms,
            observed=observed,
        )
