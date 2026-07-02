"""Bridge call capture for the WIMI test infrastructure (Layer 2).

This module implements :class:`BridgeCapture`, the third capture stream
described in ``docs/planning/PYCHROME_MIGRATION.md`` Section 5.4
("Bridge call capture under pychrome"). Together with
:class:`~wimi_test.capture.console.ConsoleCapture` and
:class:`~wimi_test.capture.network.NetworkCapture` it forms the trio of
capture streams attached to a :class:`~wimi_test.session.WimiTestSession`.

Why a third stream?
-------------------

QWebChannel bridge calls bypass the Chromium network stack entirely, so
they do not show up in :class:`~wimi_test.capture.network.NetworkCapture`
(which is CDP-based). The WIMI side instruments every ``@pyqtSlot`` with
``@instrumented_slot`` (see ``src/app/bridge_test_instrumentation.py``)
to record calls into a per-bridge ring buffer. This module mirrors that
buffer on the test driver side by polling the JS-exposed slot
``window.api.getTestModeBridgeCalls(since_ts)`` at low frequency
(default every 0.5 s) and decoding the JSON it returns.

Pychrome migration (M2.4)
-------------------------

Previously the polling step was implemented via Playwright's
``page.evaluate(js_function, since_ts)``, which lets the caller pass an
arbitrary JS function plus arguments. pychrome's ``Runtime.evaluate``
accepts only a *string expression*, so the polling JS is now built per
tick by formatting ``self._last_seen_ts`` directly into the expression
template (see ``_POLL_JS_TEMPLATE`` below). The actual evaluation goes
through :meth:`wimi_test._internal.cdp_client.WimiTab.evaluate`, which
returns the JS-side ``value`` (or raises
:class:`wimi_test.errors.WimiTestError` on a JS exception).

Missing-slot tolerance
----------------------

When the slot is missing or returns nothing useful the JS expression
returns ``null`` (which arrives back here as ``None``), and we log a
single ``logging.warning`` on the first miss so subsequent polls don't
spam. This keeps the capture stream non-fatal even if the bridge is
not test-mode-aware.

Decoupled type mirror
---------------------

The :class:`BridgeCall` defined here is intentionally a parallel
dataclass — it duplicates (rather than imports) the
:class:`BridgeCall` ``NamedTuple`` from
``src/app/bridge_test_instrumentation.py``. The two ends serialize over
JSON, so coupling them through a shared runtime import would force the
test driver to import ``src/app/`` (and transitively PyQt) just to name
a record type. The shape is identical; the boundary stays clean.

See also:
    - Section 5.4 of ``PYCHROME_MIGRATION.md`` for the polling design
      under pychrome.
    - ``wimi_test/_internal/cdp_client.py`` for the ``WimiTab.evaluate``
      seam this module relies on.
    - ``src/app/bridge_test_instrumentation.py`` for the producer side.
"""

from __future__ import annotations

import collections
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime dependency
    from wimi_test._internal.cdp_client import WimiTab

__all__ = ["BridgeCall", "BridgeCapture"]


_logger = logging.getLogger(__name__)

# Default thread-join timeout on detach. The poll loop checks the stop
# event on every iteration, so 2 seconds is plenty even if a poll is in
# flight when detach is called.
_DETACH_JOIN_TIMEOUT_S: float = 2.0


# ---------------------------------------------------------------------------
# Data type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeCall:
    """A single recorded ``@pyqtSlot`` invocation (mirror type).

    This dataclass mirrors the ``BridgeCall`` ``NamedTuple`` in
    ``src/app/bridge_test_instrumentation.py``. They are deliberately
    *not* the same Python object: the WIMI-side type is what gets
    serialized through ``getTestModeBridgeCalls()`` as JSON, and this
    side reconstructs records from the JSON dict shape.

    Attributes:
        timestamp: ``time.time()`` value at the moment the call started
            (set on the WIMI side, not on the test driver side).
        method: The wrapped slot's ``__name__`` (e.g. ``"getEntries"``).
        args_summary: Short ``repr`` of the positional + keyword args,
            truncated on the WIMI side.
        result_summary: Short ``repr`` of the return value, or for
            exceptions ``"<ExcClass>: <message>"``.
        duration_ms: Wall-clock milliseconds from entry to return /
            exception.
        error: ``True`` if the slot raised, ``False`` if it returned
            normally.
    """

    timestamp: float
    method: str
    args_summary: str
    result_summary: str
    duration_ms: float
    error: bool

    @classmethod
    def from_dict(cls, d: dict) -> "BridgeCall":
        """Construct a :class:`BridgeCall` from the dict shape produced
        by the WIMI-side ``get_test_mode_bridge_calls`` helper.

        That helper serializes via :meth:`NamedTuple._asdict`, so the
        keys exactly match this dataclass's field names. We coerce the
        types defensively in case the JSON decoder returned numbers as
        ``int`` (timestamp / duration are nominally floats but JSON has
        no distinction) and to give the boolean field a clean bool.
        """
        return cls(
            timestamp=float(d["timestamp"]),
            method=str(d["method"]),
            args_summary=str(d["args_summary"]),
            result_summary=str(d["result_summary"]),
            duration_ms=float(d["duration_ms"]),
            error=bool(d["error"]),
        )


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


# JS expression template evaluated each poll tick. Defensively guards
# against the slot being missing — see the module docstring for the
# rationale.
#
# Unlike the Playwright version (which accepted a JS function plus an
# argument), pychrome's ``Runtime.evaluate`` only accepts an expression
# string. We therefore build the expression per tick by formatting the
# ``since_ts`` cursor directly into the template. The cursor is a Python
# float (defaulting to ``0.0``) so ``f"{ts}"`` produces a JS-safe number
# literal — no quoting or escaping concerns.
#
# Wrapped in an async IIFE because ``api.getTestModeBridgeCalls`` is
# an async wrapper over a QWebChannel slot (which always returns a
# Promise). The poll caller passes ``await_promise=True`` to
# :meth:`WimiTab.evaluate` so CDP awaits the Promise and we receive the
# resolved JSON string directly. The global is ``window.api`` (the
# long-lived public name set by ``_loader.js``), not ``window._wimiApi``
# (the bootstrap-only name that the loader deletes on completion).
_POLL_JS_TEMPLATE = (
    "(async () => {{ "
    "if (window.api && typeof window.api.getTestModeBridgeCalls === 'function') {{ "
    "  return await window.api.getTestModeBridgeCalls({since_ts}); "
    "}} "
    "return null; "
    "}})()"
)


class BridgeCapture:
    """Poll-based capture mirror of the WIMI bridge call buffer.

    Construct once per :class:`~wimi_test.session.WimiTestSession`, call
    :meth:`attach` once a :class:`~wimi_test._internal.cdp_client.WimiTab`
    is available, and :meth:`detach` on session teardown. Both lifecycle
    methods are idempotent. The buffer survives detach/attach cycles so
    session-long queries (``snapshot(since_ts=session.start_ts)``) keep
    working.

    Threading: a daemon thread runs the poll loop. ``collections.deque``
    is atomic for ``append`` in CPython, so the producer thread does not
    need to hold a lock. :meth:`snapshot` and :meth:`flush` materialize
    a list copy before filtering, which is also a thread-safe operation
    on a deque in CPython.
    """

    def __init__(
        self,
        *,
        max_calls: int = 2_000,
        poll_interval_s: float = 0.5,
    ) -> None:
        self._buffer: collections.deque[BridgeCall] = collections.deque(
            maxlen=max_calls
        )
        self._poll_interval_s: float = poll_interval_s
        self._tab: Optional["WimiTab"] = None
        self._attached: bool = False
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        # ``since_ts`` cursor for incremental polling. Starts at 0.0 so
        # the first poll fetches everything currently buffered on the
        # WIMI side; subsequent polls advance to the max timestamp seen.
        self._last_seen_ts: float = 0.0
        # One-time warning latch — see module docstring.
        self._warned_about_missing_slot: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def attach(self, tab: "WimiTab") -> None:
        """Start polling ``getTestModeBridgeCalls`` on ``tab``.

        Idempotent: a second call while already attached is a no-op,
        even if a different tab is passed (callers must :meth:`detach`
        first to switch tabs).

        The poll thread is a daemon so it does not block process exit
        if a test forgets to call :meth:`detach`.
        """
        if self._attached:
            return
        self._tab = tab
        self._attached = True
        # Reset the stop event in case this is a re-attach after a prior
        # detach — Event objects need an explicit clear() to be reusable.
        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="wimi-bridge-capture-poll",
            daemon=True,
        )
        self._poll_thread.start()

    def detach(self) -> None:
        """Stop the poll thread and release the tab reference.

        Idempotent. Buffered calls are preserved so a subsequent
        :meth:`snapshot` / :meth:`flush` still returns them.
        """
        if not self._attached:
            return
        self._stop_event.set()
        thread = self._poll_thread
        if thread is not None:
            thread.join(timeout=_DETACH_JOIN_TIMEOUT_S)
        self._poll_thread = None
        self._tab = None
        self._attached = False

    # ------------------------------------------------------------------
    # Poll loop (runs on the daemon thread)
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background loop: poll the bridge slot until stopped.

        Uses :meth:`threading.Event.wait` for the inter-poll delay so
        :meth:`detach` cuts through any in-flight wait promptly. All
        exceptions are caught and logged — the thread must never die
        from a transient page or eval error, otherwise the buffer would
        silently stop growing.
        """
        # First wait — gives the page a moment to install
        # ``window.api`` before we start querying. ``wait`` returns
        # ``True`` if the event was set, in which case we exit early.
        if self._stop_event.wait(timeout=self._poll_interval_s):
            return

        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception:
                # Log and keep going — a bad poll (page navigated,
                # evaluate raced with a reload, etc.) must not kill the
                # capture stream.
                _logger.warning(
                    "BridgeCapture: poll iteration failed; continuing",
                    exc_info=True,
                )
            # Wait before the next tick. ``wait`` returns ``True`` if
            # ``_stop_event`` was set during the wait — exit cleanly.
            if self._stop_event.wait(timeout=self._poll_interval_s):
                return

    def _poll_once(self) -> None:
        """Single poll iteration: evaluate, parse, append.

        Separated from :meth:`_poll_loop` for clarity and so individual
        failures can be tested in isolation.
        """
        tab = self._tab
        if tab is None:
            # Defensive — detach should have set this to None and stopped
            # the thread before we ever reach here, but the loop is
            # racing the detach call so we re-check.
            return

        # Build the polling expression with the current ``since_ts``
        # cursor inlined. See ``_POLL_JS_TEMPLATE`` above for the
        # rationale (pychrome's evaluate takes a string expression, not
        # a function-plus-args pair like Playwright did).
        js = _POLL_JS_TEMPLATE.format(since_ts=self._last_seen_ts)
        # ``await_promise=True``: the JS expression is an async IIFE that
        # awaits the QWebChannel slot Promise. CDP resolves the Promise
        # before returning, so we get the raw JSON string here.
        result = tab.evaluate(js, await_promise=True)

        if result is None:
            # Slot not wired yet — log once and treat as empty.
            if not self._warned_about_missing_slot:
                self._warned_about_missing_slot = True
                _logger.warning(
                    "BridgeCapture: window.api.getTestModeBridgeCalls "
                    "is not exposed; bridge call buffer will stay empty."
                )
            return

        # The slot returns a JSON string. Be tolerant of an already-
        # decoded list in case a future version of the slot returns
        # the structured value directly through QWebChannel, or some
        # pychrome configurations auto-deserialize through CDP's
        # ``returnByValue`` machinery.
        if isinstance(result, str):
            try:
                entries = json.loads(result)
            except json.JSONDecodeError:
                _logger.warning(
                    "BridgeCapture: getTestModeBridgeCalls returned "
                    "non-JSON string; ignoring poll result",
                    exc_info=True,
                )
                return
        else:
            entries = result

        if not isinstance(entries, list):
            _logger.warning(
                "BridgeCapture: getTestModeBridgeCalls returned "
                "unexpected payload type %r; ignoring",
                type(entries).__name__,
            )
            return

        max_ts = self._last_seen_ts
        for entry in entries:
            if not isinstance(entry, dict):
                # Skip malformed entries rather than crash the loop.
                continue
            try:
                call = BridgeCall.from_dict(entry)
            except (KeyError, TypeError, ValueError):
                _logger.warning(
                    "BridgeCapture: failed to decode buffer entry; skipping",
                    exc_info=True,
                )
                continue
            self._buffer.append(call)
            if call.timestamp > max_ts:
                max_ts = call.timestamp

        # Advance the cursor to the maximum timestamp we actually saw
        # in this batch. Contract with the producer
        # (``get_test_mode_bridge_calls``): the producer filters with
        # ``entry.timestamp > since_ts`` (strictly greater), so once we
        # send this ``max_ts`` back as the next ``since_ts`` the producer
        # will skip every entry whose timestamp equals it — i.e. all the
        # entries we just consumed. That asymmetry is what prevents the
        # duplicate-entry bug we used to see, where an entry at the
        # boundary timestamp was returned on every subsequent poll.
        #
        # Lower-bound safety: an entry produced *exactly* at ``max_ts``
        # but appended to the producer ring after our snapshot would be
        # excluded by the next poll, since the producer's filter is
        # strict. In practice ``time.time()`` collisions on the same
        # process are vanishingly rare (sub-microsecond ties), and any
        # genuinely simultaneous slot would have already been included
        # in the same poll batch we just processed. We accept this
        # theoretical edge case in exchange for guaranteed
        # duplicate-free incremental delivery.
        self._last_seen_ts = max_ts

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def snapshot(
        self,
        *,
        method_substr: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> list[BridgeCall]:
        """Return a filtered copy of the buffer (non-draining).

        ``method_substr`` keeps only calls whose ``method`` contains the
        substring (case-sensitive — slot names are camelCase by
        convention so case-sensitive matching is rarely a problem).

        ``since_ts`` keeps only entries whose ``timestamp`` is at or
        after that time — used for per-test segmentation against
        ``WimiTestSession.start_ts`` (Section 6.3).

        Returns a list (not a deque view) so callers can sort, mutate
        or extend without affecting the live buffer.
        """
        # Materialize a list snapshot first — see the class docstring
        # on thread safety. ``list(deque)`` is atomic in CPython.
        entries = list(self._buffer)
        if since_ts is not None:
            entries = [e for e in entries if e.timestamp >= since_ts]
        if method_substr is not None:
            entries = [e for e in entries if method_substr in e.method]
        return entries

    def flush(self) -> list[BridgeCall]:
        """Drain the buffer and return every call it held.

        After this call the buffer is empty; subsequent :meth:`snapshot`
        calls see only entries appended after the flush. Useful at the
        end of a session or when callers want exclusive ownership of
        captured calls.
        """
        drained = list(self._buffer)
        self._buffer.clear()
        return drained
