"""CDP-based network event capture for the WIMI test infrastructure.

Subscribes to Chrome DevTools Protocol ``Network.*`` events through
:class:`wimi_test._internal.cdp_client.WimiTab` (a thin pychrome wrapper)
and buffers ``request``/``response``/``failed`` events in a bounded
ring. The implementation mirrors the contract in
``docs/planning/TEST_INFRASTRUCTURE.md`` §6.2 (network capture) and §4
(``NetworkCapture`` API contract).

Migration note
--------------
This module previously subscribed to events through Playwright's
``CDPSession``. As of the pychrome migration (see
``docs/planning/PYCHROME_MIGRATION.md`` §5.4) it now goes through
``tab.set_listener`` on a :class:`WimiTab`. **The CDP event shapes are
unchanged** — Playwright was just forwarding them. The only API-level
difference is that pychrome dispatches each event's ``params`` as
keyword arguments to the handler rather than a single ``params`` dict,
so the handler signatures here unpack the relevant fields directly.

What is captured
----------------
HTTP/HTTPS, the custom ``media://`` scheme, and any other URL scheme
that QtWebEngine routes through the Chromium network stack. The
``file://`` and ``qrc://`` schemes are commonly noisy and rarely useful
for assertions; this module does *not* filter them itself — the public
default-filter rule lives in :func:`wimi_test.config.default_url_filter`
and is applied at the configuration layer. Pass ``url_filter=None`` (the
default) to capture every URL that reaches CDP.

What is NOT captured
--------------------
**QWebChannel bridge calls do not appear in CDP Network events** — the
QWebChannel transport bypasses the network stack entirely. Bridge call
capture is handled separately by ``wimi_test.capture.bridge`` (task
T3.3 and T3.6 wire that up via an instrumented-slot decorator on the
Python bridge).

Failure events
--------------
``Network.loadingFailed`` payloads do not always include the URL (the
request was already correlated by ``requestId`` in an earlier
``requestWillBeSent``). We always buffer failure events — even when the
URL filter would otherwise reject them — because failures of filtered
URLs are still useful diagnostic signal.

Detach limitations
------------------
pychrome's :class:`pychrome.Tab` does not expose an explicit
``remove_listener`` API: each call to ``set_listener(event, handler)``
overwrites the previously-registered handler for that event name, but
there is no public way to *clear* a listener without registering a new
one. :meth:`NetworkCapture.detach` therefore disables the Network
domain (which stops the events at the source) and clears the cached
tab reference, but the bound-method handlers remain registered until
either the tab itself is torn down or another component overwrites
them. Detaching and immediately reattaching the same capture works
correctly because :meth:`attach` re-registers the same bound methods.
This is a v1 limitation; revisit if it causes leakage in long-lived
sessions.

Threading and lifetime
----------------------
``attach`` / ``detach`` are idempotent. The buffer is a fixed-size
``collections.deque`` and is preserved across detach/reattach cycles so
session-long log slicing (``snapshot(since_ts=...)``) still works.
"""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from wimi_test._internal.cdp_client import WimiTab

__all__ = ["NetworkEvent", "NetworkCapture"]


@dataclass(frozen=True)
class NetworkEvent:
    """One captured CDP network event.

    A request, response, or failure observation correlated by
    ``request_id`` (Chrome's ``requestId``). The same ``request_id`` is
    shared across the request, the corresponding response, and any
    failure event — callers can group by it to reconstruct a full
    transaction.

    Attributes
    ----------
    timestamp:
        Wall-clock seconds (``time.time()``) when the event was
        observed by the capture, not the CDP-reported timestamp.
    kind:
        One of ``"request"``, ``"response"``, ``"failed"``.
    request_id:
        Chrome's request ID. Stable across the request/response/failed
        events of a single transaction.
    url:
        Request or response URL. Empty string for ``failed`` events
        whose CDP payload omits the URL.
    method:
        HTTP method (only on ``request`` events).
    status:
        HTTP status code (only on ``response`` events).
    mime_type:
        Response MIME type (only on ``response`` events).
    error_text:
        CDP ``errorText`` (only on ``failed`` events).
    headers:
        Request or response headers, after the optional ``redact_headers``
        callback. ``None`` for ``failed`` events (CDP does not provide
        headers in the failure payload).
    raw:
        The reconstructed CDP event params dict, kept verbatim for
        debugging. **Not** redacted — do not include this stream in
        user-facing failure reports.
    """

    timestamp: float
    kind: str
    request_id: str
    url: str
    method: Optional[str] = None
    status: Optional[int] = None
    mime_type: Optional[str] = None
    error_text: Optional[str] = None
    headers: Optional[dict] = None
    raw: dict = None  # type: ignore[assignment]


class NetworkCapture:
    """Buffered CDP ``Network.*`` event subscription.

    Construct once per session, call :meth:`attach` with a
    :class:`WimiTab`, and read with :meth:`snapshot` (filtered,
    non-draining) or :meth:`flush` (drains the buffer). See module
    docstring and ``TEST_INFRASTRUCTURE.md`` §6.2 / ``PYCHROME_MIGRATION.md``
    §5.4 for the design rationale.
    """

    def __init__(
        self,
        *,
        max_events: int = 5_000,
        url_filter: Optional[Callable[[str], bool]] = None,
        redact_headers: Optional[Callable[[dict], dict]] = None,
    ) -> None:
        self._buffer: collections.deque[NetworkEvent] = collections.deque(
            maxlen=max_events
        )
        self._url_filter: Optional[Callable[[str], bool]] = url_filter
        self._redact_headers: Optional[Callable[[dict], dict]] = redact_headers
        self._tab: Optional["WimiTab"] = None
        self._attached: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def attach(self, tab: "WimiTab") -> None:
        """Enable the CDP Network domain and subscribe to relevant events.

        Idempotent: a second call while already attached is a no-op so
        callers do not need to track lifecycle themselves.
        """
        if self._attached:
            return
        self._tab = tab
        try:
            tab.Network.enable()
        except Exception:
            # Network domain may already be enabled by an earlier
            # capture or by another component sharing the tab. The
            # ``set_listener`` calls below still take effect, so this
            # is safe to ignore.
            pass
        tab.set_listener("Network.requestWillBeSent", self._on_request)
        tab.set_listener("Network.responseReceived", self._on_response)
        tab.set_listener("Network.loadingFailed", self._on_failed)
        self._attached = True

    def detach(self) -> None:
        """Disable the CDP Network domain and drop our tab reference.

        Buffered events are preserved so a subsequent
        :meth:`snapshot` / :meth:`flush` still returns them. Idempotent.

        See the module docstring for why we cannot fully unregister the
        listeners — pychrome has no ``remove_listener`` in v1.
        """
        if not self._attached:
            return
        tab = self._tab
        if tab is not None:
            try:
                tab.Network.disable()
            except Exception:
                # The tab may already be closing (page closed, websocket
                # gone, subprocess exited). Silencing is correct here —
                # detach is best-effort cleanup.
                pass
        self._tab = None
        self._attached = False

    # ------------------------------------------------------------------
    # CDP event handlers (bound methods so a future remove_listener can
    # match by identity, and so reattach replays the same registrations)
    # ------------------------------------------------------------------
    def _on_request(self, requestId: str = "", request: Optional[dict] = None, **kwargs) -> None:
        request = request or {}
        url: str = request.get("url", "") or ""
        if self._url_filter is not None and not self._url_filter(url):
            return
        headers = request.get("headers") or {}
        if self._redact_headers is not None:
            headers = self._redact_headers(headers)
        # Reconstruct the original ``params`` dict for the ``raw`` field
        # so consumers see the same shape as before the pychrome
        # migration.
        raw = {"requestId": requestId, "request": request, **kwargs}
        self._buffer.append(
            NetworkEvent(
                timestamp=time.time(),
                kind="request",
                request_id=requestId or "",
                url=url,
                method=request.get("method"),
                headers=headers,
                raw=raw,
            )
        )

    def _on_response(self, requestId: str = "", response: Optional[dict] = None, **kwargs) -> None:
        response = response or {}
        url: str = response.get("url", "") or ""
        if self._url_filter is not None and not self._url_filter(url):
            return
        headers = response.get("headers") or {}
        if self._redact_headers is not None:
            headers = self._redact_headers(headers)
        raw = {"requestId": requestId, "response": response, **kwargs}
        self._buffer.append(
            NetworkEvent(
                timestamp=time.time(),
                kind="response",
                request_id=requestId or "",
                url=url,
                status=response.get("status"),
                mime_type=response.get("mimeType"),
                headers=headers,
                raw=raw,
            )
        )

    def _on_failed(self, requestId: str = "", errorText: Optional[str] = None, **kwargs) -> None:
        # Failure payloads do not always carry the URL — the requestId
        # already correlates back to the earlier requestWillBeSent. We
        # always buffer failures, **including** ones that the URL filter
        # would normally reject, because failures of filtered URLs are
        # still useful diagnostic signal.
        raw = {"requestId": requestId, "errorText": errorText, **kwargs}
        self._buffer.append(
            NetworkEvent(
                timestamp=time.time(),
                kind="failed",
                request_id=requestId or "",
                url="",
                error_text=errorText,
                raw=raw,
            )
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------
    def snapshot(
        self,
        *,
        url_substr: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> list[NetworkEvent]:
        """Return a filtered snapshot of the buffer (non-draining).

        ``url_substr`` keeps only events whose ``url`` contains the
        substring (case-sensitive). ``since_ts`` keeps only events with
        ``timestamp >= since_ts``, used by per-test segmentation
        (``WimiTestSession.start_ts``).
        """
        events = list(self._buffer)
        if since_ts is not None:
            events = [e for e in events if e.timestamp >= since_ts]
        if url_substr is not None:
            events = [e for e in events if url_substr in e.url]
        return events

    def flush(self) -> list[NetworkEvent]:
        """Drain the buffer and return every event it held."""
        events = list(self._buffer)
        self._buffer.clear()
        return events
