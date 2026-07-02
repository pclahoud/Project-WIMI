"""Thin pychrome wrapper for the WIMI test infrastructure.

This module is the single seam between :mod:`wimi_test` and the
:mod:`pychrome` package. Everything else in the library that needs to
talk to Qt's Chrome DevTools Protocol endpoint goes through
:class:`WimiBrowser` / :class:`WimiTab` defined here, never directly
through pychrome.

The wrapper hides three pychrome quirks:

1. **Two-tab disambiguation.** Qt's ``QWebEngineView`` sometimes exposes
   one CDP "page" target and sometimes two (the second is an empty
   bookkeeping target with no scripts and no title). :meth:`WimiBrowser.primary_tab`
   iterates the targets and picks the one that is actually running the
   WIMI HTML — i.e. has loaded scripts AND a ``document.title``
   containing the substring ``"WIMI"``.
2. **`tab.start()` / `tab.stop()` are non-idempotent.** pychrome raises
   ``RuntimeException`` if you call ``start`` twice or ``stop`` on a
   tab that was never started. :meth:`WimiTab.start` and
   :meth:`WimiTab.stop` swallow those.
3. **Noisy ``_recv_loop`` warnings.** When pychrome's internal recv
   thread sees a malformed frame (e.g. during teardown) it dumps a
   ``json.JSONDecodeError`` traceback via ``traceback.print_exc``
   straight to stderr. We cannot intercept that cleanly via
   :mod:`logging` because pychrome doesn't go through ``logging`` for
   the traceback dump. The constants below document the limitation;
   future revisions may monkeypatch ``pychrome.tab._recv_loop`` if the
   noise becomes intolerable. For v1 we accept it.

The :func:`open_session` convenience entry point is what
``WimiTestSession.start()`` (M3.1) will use to obtain a browser+tab
pair.

Reference: ``docs/planning/PYCHROME_MIGRATION.md`` Section 5.1
("Connection layer") and Section 7 (risks — particularly the
``window.api`` async-handshake validation, the noisy
``_recv_loop`` warnings, and the two-tab disambiguation).

This is a leaf module. It imports from :mod:`pychrome`, the standard
library, and :class:`wimi_test.errors.WimiTestError`. It must not
import anything from :mod:`wimi_test.session` or other higher-level
modules — those import *us*.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Tuple

import pychrome

from wimi_test.errors import WimiTestError

__all__ = ["WimiBrowser", "WimiTab", "open_session"]


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Noise suppression
# ---------------------------------------------------------------------------
#
# pychrome's ``_recv_loop`` writes ``json.JSONDecodeError`` tracebacks
# directly via ``traceback.print_exc()`` rather than through the
# :mod:`logging` framework. The filter below is installed against the
# ``pychrome.tab`` logger as a defensive measure — it silences any
# warnings pychrome *does* route through ``logging``. The bulk of the
# noise (the bare tracebacks) cannot be suppressed without monkeypatching
# ``pychrome.tab._recv_loop``, which we deliberately do not do in v1.
# Document and accept; revisit if it drowns out real errors during M2.x.


class _PychromeNoiseFilter(logging.Filter):
    """Drops :mod:`pychrome` log records that match known-noisy patterns.

    Currently this is best-effort: pychrome 0.2.4 does not actually use
    :mod:`logging` for its ``_recv_loop`` ``JSONDecodeError`` chatter
    (it uses :func:`traceback.print_exc` to stderr, which bypasses
    :mod:`logging` entirely). The filter is installed as a placeholder
    so that any future pychrome release that *does* migrate to
    :mod:`logging` is silenced automatically.
    """

    _NOISY_SUBSTRINGS: Tuple[str, ...] = (
        "JSONDecodeError",
        "_recv_loop",
    )

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        msg = record.getMessage()
        for needle in self._NOISY_SUBSTRINGS:
            if needle in msg:
                return False
        return True


logging.getLogger("pychrome.tab").addFilter(_PychromeNoiseFilter())


# ---------------------------------------------------------------------------
# WimiTab
# ---------------------------------------------------------------------------


class WimiTab:
    """Wraps a :class:`pychrome.Tab` and adds WIMI-aware helpers.

    The wrapped tab must already have :meth:`pychrome.Tab.start` called
    on it before being passed in — :meth:`WimiBrowser.primary_tab` is
    responsible for that.

    Attribute delegation: :attr:`Page`, :attr:`Runtime`, :attr:`Network`,
    :attr:`DOM`, :attr:`Input`, and :attr:`Target` are pass-throughs to
    the underlying pychrome ``GenericAttr`` proxy objects, so callers can
    write ``wt.Runtime.evaluate(...)`` exactly as they would on a raw
    :class:`pychrome.Tab`.
    """

    def __init__(self, tab: pychrome.Tab) -> None:
        self._tab: pychrome.Tab = tab

    # -- Domain delegates --------------------------------------------------
    #
    # We expose these as properties (not bare attribute reads) so a unit
    # test can ``patch.object(WimiTab, "Runtime")`` cleanly. pychrome's
    # ``Tab.__getattr__`` builds the proxy lazily on first access; the
    # property simply forwards.

    @property
    def Page(self) -> Any:
        """The pychrome ``Page`` domain proxy."""
        return self._tab.Page

    @property
    def Runtime(self) -> Any:
        """The pychrome ``Runtime`` domain proxy."""
        return self._tab.Runtime

    @property
    def Network(self) -> Any:
        """The pychrome ``Network`` domain proxy."""
        return self._tab.Network

    @property
    def DOM(self) -> Any:
        """The pychrome ``DOM`` domain proxy."""
        return self._tab.DOM

    @property
    def Input(self) -> Any:
        """The pychrome ``Input`` domain proxy."""
        return self._tab.Input

    @property
    def Target(self) -> Any:
        """The pychrome ``Target`` domain proxy.

        Note: Qt's CDP only partially implements ``Target.*`` — see
        ``PYCHROME_MIGRATION.md`` Section 3. ``attachToTarget`` works;
        context creation does not.
        """
        return self._tab.Target

    @property
    def id(self) -> str:
        """The CDP target id for this tab."""
        return self._tab.id

    # -- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Idempotent wrapper around :meth:`pychrome.Tab.start`.

        pychrome's own ``start()`` raises ``RuntimeException`` if the
        tab is already started. We swallow that so callers can
        defensively re-start without caring about prior state.
        """
        try:
            self._tab.start()
        except pychrome.RuntimeException:
            # Already started — exactly the case we want to ignore.
            pass

    def stop(self) -> None:
        """Idempotent wrapper around :meth:`pychrome.Tab.stop`.

        pychrome raises ``RuntimeException`` if the tab was never
        started; we swallow that here.
        """
        try:
            self._tab.stop()
        except pychrome.RuntimeException:
            pass
        except Exception as exc:  # noqa: BLE001 — cleanup must be best-effort
            logger.warning("WimiTab.stop(): unexpected error: %s", exc)

    # -- Convenience wrappers ---------------------------------------------

    def evaluate(
        self,
        expression: str,
        *,
        return_by_value: bool = True,
        await_promise: bool = False,
    ) -> Any:
        """Evaluate ``expression`` in the page's main world.

        Wraps :meth:`Runtime.evaluate` with a sensible response shape:
        on success, returns the JS-side ``value``; on a JS exception,
        raises :class:`WimiTestError` carrying the formatted error text.

        Parameters
        ----------
        expression
            JavaScript source to evaluate. Treated as an *expression*,
            not a statement — wrap multi-statement code in an IIFE.
        return_by_value
            Forwarded to CDP as ``returnByValue``. When ``True`` (the
            default) the return value is JSON-serialised by the page
            and round-tripped back as a Python value. When ``False``
            the caller receives the raw RemoteObject dict.
        await_promise
            Forwarded to CDP as ``awaitPromise``. When ``True``, if the
            expression evaluates to a Promise the call blocks (on the
            CDP side) until the Promise settles and returns the resolved
            value. Required for QWebChannel slot calls, which always
            return Promises in the JS proxy.

        Returns
        -------
        Any
            The evaluated value (when ``return_by_value=True``) or the
            ``result`` RemoteObject dict (when ``return_by_value=False``).

        Raises
        ------
        WimiTestError
            If the evaluation produced an ``exceptionDetails`` block.
        """
        response = self._tab.Runtime.evaluate(
            expression=expression,
            returnByValue=return_by_value,
            awaitPromise=await_promise,
        )

        # Some Qt CDP responses use ``exceptionDetails`` at the top level
        # to flag JS errors. Surface those as WimiTestError so callers
        # don't have to introspect the dict.
        exc = response.get("exceptionDetails") if isinstance(response, dict) else None
        if exc:
            text = exc.get("text") or exc.get("exception", {}).get("description") or "(no detail)"
            raise WimiTestError(f"eval error: {text}")

        result = response.get("result", {}) if isinstance(response, dict) else {}
        if return_by_value:
            return result.get("value")
        return result

    def wait_for_wimi_api(self, timeout_ms: int = 5000, poll_ms: int = 100) -> None:
        """Block until ``window.api`` exists and is an object.

        Polls ``typeof window.api`` via :meth:`Runtime.evaluate`
        every ``poll_ms`` milliseconds until either the value is
        ``"object"`` (the API has been wired up) or ``timeout_ms``
        elapses.

        ``window.api`` is the long-lived public name. WIMI's
        ``src/web/js/api/_loader.js`` builds the API object at
        ``window._wimiApi`` during bootstrap, then promotes it to
        ``window.api`` and ``delete``s ``_wimiApi`` once every domain
        module has loaded — so polling ``_wimiApi`` here would race the
        loader and fail spuriously.

        This is the **hot validation step** flagged in
        ``PYCHROME_MIGRATION.md`` Section 7: if Qt's ``QWebChannel``
        bridge is not reachable from CDP under proper async wait, this
        method will surface the problem at the earliest possible moment.

        Parameters
        ----------
        timeout_ms
            Total time to wait, in milliseconds. Defaults to 5000.
        poll_ms
            Interval between polls, in milliseconds. Defaults to 100.

        Raises
        ------
        WimiTestError
            If ``window.api`` does not become an object before the
            timeout. The error message includes the last observed type
            string (``undefined``, ``function``, etc.) so the failure
            mode is debuggable.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        last_value: Any = "<no probe completed>"

        while True:
            try:
                last_value = self.evaluate("typeof window.api")
            except WimiTestError as exc:
                # An eval failure during polling is surprising but not
                # fatal — record and keep trying until the deadline so
                # transient navigation errors don't cascade.
                last_value = f"<eval failed: {exc.message}>"
            else:
                if last_value == "object":
                    return

            if time.monotonic() >= deadline:
                raise WimiTestError(
                    f"window.api never appeared within {timeout_ms}ms; "
                    f"last value: {last_value!r}"
                )

            time.sleep(poll_ms / 1000.0)

    def set_listener(self, event: str, handler: Callable[..., Any]) -> None:
        """Register ``handler`` for the CDP event named ``event``.

        Pass-through to :meth:`pychrome.Tab.set_listener`. The handler
        is invoked with the event payload as keyword arguments.
        """
        self._tab.set_listener(event, handler)


# ---------------------------------------------------------------------------
# WimiBrowser
# ---------------------------------------------------------------------------


class WimiBrowser:
    """Wraps a :class:`pychrome.Browser` and owns the CDP connection.

    Construction is cheap — no network traffic happens until
    :meth:`primary_tab` is called.
    """

    def __init__(self, port: int) -> None:
        self._port: int = port
        self._client: pychrome.Browser = pychrome.Browser(
            url=f"http://127.0.0.1:{port}"
        )

    def primary_tab(self) -> WimiTab:
        """Return the WIMI tab, starting it if necessary.

        Iterates every page-type tab Qt's CDP exposes and picks the
        first one whose document has scripts loaded AND whose title
        contains ``"WIMI"``. Tabs that are inspected but rejected are
        stopped again so we don't leak websocket connections.

        Raises
        ------
        WimiTestError
            If no tab in the listing matches the WIMI signature.
        """
        candidates = self._client.list_tab()
        rejected: list[pychrome.Tab] = []

        for tab in candidates:
            try:
                tab.start()
            except pychrome.RuntimeException:
                # Already started by an earlier call (Browser caches
                # tabs across instances by URL). Continue probing.
                pass

            try:
                scripts_resp = tab.Runtime.evaluate(
                    expression="document.scripts.length > 0",
                    returnByValue=True,
                )
                has_scripts = bool(
                    scripts_resp.get("result", {}).get("value", False)
                )

                title_resp = tab.Runtime.evaluate(
                    expression="document.title",
                    returnByValue=True,
                )
                title = title_resp.get("result", {}).get("value") or ""

                if has_scripts and "WIMI" in title:
                    return WimiTab(tab)
            except Exception as exc:  # noqa: BLE001 — keep iterating on probe failure
                logger.debug(
                    "WimiBrowser.primary_tab: probe failed for tab %s: %s",
                    getattr(tab, "id", "<unknown>"),
                    exc,
                )

            # Not a match — stop the connection so we don't leak the
            # websocket. Defer collection until after the loop so we
            # don't touch a tab we may yet need.
            rejected.append(tab)

        for tab in rejected:
            try:
                tab.stop()
            except Exception:  # noqa: BLE001
                pass

        raise WimiTestError("No usable WIMI tab found")

    def close(self) -> None:
        """Best-effort teardown of every tracked tab.

        :class:`pychrome.Browser` does not have a single ``close``
        method; the only resource it owns is a cache of started
        :class:`pychrome.Tab` objects (each with its own websocket
        connection and recv thread). We iterate that cache and call
        ``stop`` on every tab, swallowing any errors so cleanup is
        always safe.
        """
        try:
            tabs = list(self._client._tabs.values())  # noqa: SLF001 — internal cache
        except Exception:  # noqa: BLE001
            tabs = []

        for tab in tabs:
            try:
                if getattr(tab, "_started", False) and not getattr(
                    tab, "_stopped", None
                ).is_set():
                    tab.stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "WimiBrowser.close: error stopping tab %s: %s",
                    getattr(tab, "id", "<unknown>"),
                    exc,
                )


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------


def open_session(port: int) -> Tuple[WimiBrowser, WimiTab]:
    """Construct a :class:`WimiBrowser` and resolve its primary tab.

    This is the convenience entry point used by
    ``WimiTestSession.start()`` (task M3.1) — it folds the two-step
    construction into a single call so callers don't need to remember
    the lifecycle.

    Parameters
    ----------
    port
        The CDP port WIMI's debug server is listening on. Typically
        the value returned from :meth:`wimi_test.process.WimiProcess.spawn`.

    Returns
    -------
    Tuple[WimiBrowser, WimiTab]
        A connected browser wrapper and a started, validated tab.
    """
    browser = WimiBrowser(port=port)
    tab = browser.primary_tab()
    return browser, tab
