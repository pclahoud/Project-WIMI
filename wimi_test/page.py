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
import time
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlencode

from wimi_test._internal.cdp_client import WimiTab
from wimi_test.config import TestConfig
from wimi_test.errors import WimiTestError
from wimi_test.locator import WimiLocator, build_locator
from wimi_test.routes import resolve as resolve_route

__all__ = ["WimiPage"]


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

    def wait_for_bridge_call(
        self,
        method: str,
        *,
        timeout_ms: int = 5000,
    ) -> object:
        """Wait for a named bridge method invocation to complete.

        Used when JS-side code defers a database write through the
        bridge and the test needs to synchronize on its completion
        before asserting on the resulting state.

        Not implemented yet: although the JS-side ``BridgeCapture``
        polls ``getTestModeBridgeCalls`` (the original T3.6 blocker is
        unblocked), the WIMI-side ``@pyqtSlot`` for
        ``get_test_mode_bridge_calls`` is **still pending**. This
        method therefore continues to raise :class:`NotImplementedError`
        until that slot is wired up.

        Raises
        ------
        NotImplementedError
            Always, until the WIMI-side bridge slot for
            ``get_test_mode_bridge_calls`` is wired up.
        """
        # TODO(T3.6 / Phase 3): implement once the WIMI-side
        # @pyqtSlot for get_test_mode_bridge_calls exists. The
        # JS-side BridgeCapture polling is already in place; this
        # method is now blocked on the slot wiring rather than on the
        # capture module.
        raise NotImplementedError(
            "wait_for_bridge_call is blocked on the WIMI-side @pyqtSlot "
            "for get_test_mode_bridge_calls (T3.6 / Phase 3)"
        )
