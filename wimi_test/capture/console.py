"""Layer 2 console capture: pychrome CDP ``Runtime.*`` event subscription.

This module implements the per-test, fine-grained half of the two-layer
console-capture story described in ``docs/planning/TEST_INFRASTRUCTURE.md``
Section 6.1. Layer 1 (the always-on Python ``QWebEnginePage`` subclass in
``src/app/test_mode.py``) catches startup and pre-attach errors. Layer 2 —
this module — owns the primary capture stream while a test is running:
``WimiTestSession.attach()`` subscribes a :class:`ConsoleCapture` to the
primary :class:`~wimi_test._internal.cdp_client.WimiTab` and detaches on
``session.stop()``.

Per-test segmentation is timestamp-based, not buffer-clearing: the same
ring buffer lives for the whole session, and each test's failure report
slices via ``snapshot(since_ts=test_start_ts)``. This keeps the
implementation simple and lets cross-test forensic queries see the full
history.

The :class:`ConsoleEntry` defined here is intentionally a different type
from the one in ``src/app/test_mode.py`` (Layer 1). The two layers run in
different processes (Layer 1 inside the WIMI Qt app, Layer 2 inside the
pytest / MCP driver) and serialize separately; coupling them through a
shared dataclass would force a runtime import across the process boundary
for no real benefit.

Migration note (M2.2): this module previously subscribed to Playwright's
high-level ``page.on("console")`` and ``page.on("pageerror")`` events.
After the pychrome migration we instead subscribe to the raw CDP events
``Runtime.consoleAPICalled`` (for ``console.log/info/warn/error/...``)
and ``Runtime.exceptionThrown`` (for uncaught JS exceptions). The
public :class:`ConsoleEntry` shape is preserved so downstream consumers
(``CaptureBundle``, ``format_console``) are unaffected.

See also:
    - ``docs/planning/PYCHROME_MIGRATION.md`` Section 5.4 for the design
      and the Playwright→pychrome translation.
    - Section 4 of ``TEST_INFRASTRUCTURE.md`` for the public API contract.
    - Section 6.1 for the layering rationale and ``fail_on_console_error``.
"""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime dependency
    from wimi_test._internal.cdp_client import WimiTab

__all__ = ["ConsoleEntry", "ConsoleCapture"]


# Severity ranking. ``log`` is treated as info-equivalent for filtering
# (matches Chromium's behaviour: ``console.log`` and ``console.info`` both
# surface as informational). ``exception`` is reserved for
# ``Runtime.exceptionThrown`` events, which represent uncaught JS
# exceptions and rank above ``error``.
_LEVEL_RANK: dict[str, int] = {
    "debug": 0,
    "info": 1,
    "log": 1,
    "warning": 2,
    "error": 3,
    "exception": 4,
}


# CDP's ``Runtime.consoleAPICalled.type`` is one of a fixed set
# documented in the Chrome DevTools Protocol. Most names line up with our
# level vocabulary one-to-one, but a few CDP-specific types
# (``"trace"``, ``"dir"``, ``"table"``, ``"clear"``, etc.) need to be
# bucketed onto a level we already understand. Anything not in this map
# falls back to ``"log"`` in :meth:`ConsoleCapture._on_console`.
_CDP_TYPE_TO_LEVEL: dict[str, str] = {
    "log": "log",
    "info": "info",
    "warning": "warning",
    "error": "error",
    "debug": "debug",
    # CDP-specific types: bucket them onto the closest level we expose.
    "trace": "debug",
    "dir": "log",
    "dirxml": "log",
    "table": "log",
    "clear": "log",
    "startGroup": "log",
    "startGroupCollapsed": "log",
    "endGroup": "log",
    "assert": "error",
    "profile": "log",
    "profileEnd": "log",
    "count": "log",
    "timeEnd": "log",
}


# Heuristic threshold for distinguishing CDP timestamps (milliseconds
# since epoch) from a stray seconds-since-epoch value. Year 2001 in
# seconds is ~1e9; the same instant in milliseconds is ~1e12. Anything
# above 1e11 is unambiguously milliseconds for any realistic clock; we
# convert to seconds so the buffer stores a uniform time base.
_MS_THRESHOLD: float = 1e11


@dataclass(frozen=True, slots=True)
class ConsoleEntry:
    """A single captured JS console message or page error.

    ``level`` is one of ``"info"``, ``"log"``, ``"warning"``, ``"error"``,
    ``"debug"`` (mapped from CDP's ``Runtime.consoleAPICalled.type``) or
    the synthetic ``"exception"`` level used for
    ``Runtime.exceptionThrown`` events.

    ``location`` mirrors the legacy Playwright location dict shape
    (``{"url": ..., "lineNumber": ..., "columnNumber": ...}``). For
    ``console.*`` events it is built from the topmost ``stackTrace``
    frame when CDP supplies one; for ``Runtime.exceptionThrown`` it is
    built from ``exceptionDetails.{url,lineNumber,columnNumber}``. It is
    ``None`` when no location information is available.
    """

    timestamp: float
    level: str
    text: str
    location: Optional[dict] = field(default=None)


class ConsoleCapture:
    """Always-on capture of JS console messages and uncaught page errors.

    Ring-buffered (``collections.deque(maxlen=...)``) so a runaway
    ``console.log`` loop in the page under test cannot exhaust memory.
    Severity-classified via :class:`ConsoleEntry.level` and sliceable by
    timestamp through :meth:`snapshot`.

    Lifecycle: instantiate once per :class:`~wimi_test.session.WimiTestSession`,
    call :meth:`attach` after the :class:`WimiTab` is available, and
    :meth:`detach` on session teardown. Both are idempotent.
    """

    def __init__(self, *, max_messages: int = 10_000) -> None:
        self._buffer: collections.deque[ConsoleEntry] = collections.deque(
            maxlen=max_messages
        )
        self._tab: Optional["WimiTab"] = None
        self._attached: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def attach(self, tab: "WimiTab") -> None:
        """Subscribe to ``Runtime.consoleAPICalled`` / ``Runtime.exceptionThrown``.

        Idempotent: a second call while already attached is a no-op,
        even if a different tab is passed (callers must :meth:`detach`
        first to switch tabs).

        Enables the ``Runtime`` CDP domain before registering listeners
        — events will not fire otherwise. ``Runtime.enable`` is
        tolerated as a no-op on a tab that already has it enabled, but
        some pychrome / Qt CDP combinations surface a benign error in
        that case; we swallow it so the attach flow is robust.
        """
        if self._attached:
            return

        try:
            tab.Runtime.enable()
        except Exception:  # noqa: BLE001 — Runtime.enable is best-effort
            # If Runtime is already enabled (or a transient CDP error
            # occurs), continue: the listeners will still be wired and
            # subsequent events will reach us. Diagnostics for a truly
            # broken tab will surface elsewhere.
            pass

        tab.set_listener("Runtime.consoleAPICalled", self._on_console)
        tab.set_listener("Runtime.exceptionThrown", self._on_pageerror)

        self._tab = tab
        self._attached = True

    def detach(self) -> None:
        """Disable the ``Runtime`` domain and forget the tab. Buffer is preserved.

        Idempotent. Calls ``Runtime.disable`` (best-effort) so the page
        stops emitting events to a tab we are no longer servicing.

        **Known limitation:** pychrome 0.2.4 does not expose a
        ``remove_listener`` counterpart to :meth:`WimiTab.set_listener`;
        the handler refs registered in :meth:`attach` remain installed
        on the underlying ``pychrome.Tab``. In practice this is benign
        because (a) the tab is normally torn down shortly after
        :meth:`detach` (session teardown) and (b) a subsequent
        :meth:`attach` on the same tab will overwrite the listener slot
        for these specific event names. Document and accept; revisit
        only if a future pychrome release adds proper unregistration.
        """
        if not self._attached:
            return

        tab = self._tab
        if tab is not None:
            try:
                tab.Runtime.disable()
            except Exception:  # noqa: BLE001 — disable is best-effort
                # Already disabled, tab already torn down, or transient
                # CDP error during shutdown — none of these should
                # block detach.
                pass

        self._tab = None
        self._attached = False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    #
    # pychrome dispatches CDP event payloads to listeners as keyword
    # arguments matching the field names in the protocol. Both handlers
    # below accept ``**kwargs`` so an extra/unknown field in a future
    # CDP revision does not raise ``TypeError`` at the dispatch site.
    # The whole body is wrapped in try/except so a malformed event
    # cannot crash pychrome's recv thread.

    def _on_console(
        self,
        type=None,
        args=None,
        executionContextId=None,
        timestamp=None,
        stackTrace=None,
        **kwargs,
    ) -> None:
        """Handler for ``Runtime.consoleAPICalled``.

        Translates the CDP payload to a :class:`ConsoleEntry`. The
        ``args`` array (a list of CDP ``RemoteObject`` dicts) is
        flattened to a single text string by :meth:`_stringify_arg`.
        """
        try:
            level = _CDP_TYPE_TO_LEVEL.get(type or "", "log")
            text = self._format_args(args or [])
            ts = self._coerce_timestamp(timestamp)
            location = self._location_from_stack_trace(stackTrace)

            self._buffer.append(
                ConsoleEntry(
                    timestamp=ts,
                    level=level,
                    text=text,
                    location=location,
                )
            )
        except Exception:  # noqa: BLE001 — listener must never raise
            # A malformed event must not propagate into pychrome's recv
            # loop (which would dump a traceback to stderr and could
            # destabilise the session). Drop the offending event.
            return

    def _on_pageerror(
        self,
        timestamp=None,
        exceptionDetails=None,
        **kwargs,
    ) -> None:
        """Handler for ``Runtime.exceptionThrown``.

        Translates the CDP payload to a :class:`ConsoleEntry` tagged
        with the synthetic ``"exception"`` level so callers can
        distinguish thrown exceptions from ``console.error`` calls.
        """
        try:
            details = exceptionDetails or {}

            head = (details.get("text") or "").strip()
            exception_obj = details.get("exception") or {}
            tail = (exception_obj.get("description") or "").strip()
            if head and tail:
                text = f"{head}: {tail}"
            else:
                text = head or tail

            url = details.get("url")
            line = details.get("lineNumber")
            col = details.get("columnNumber")
            if url is not None or line is not None or col is not None:
                location: Optional[dict] = {
                    "url": url,
                    "lineNumber": line,
                    "columnNumber": col,
                }
            else:
                location = None

            ts = self._coerce_timestamp(timestamp)

            self._buffer.append(
                ConsoleEntry(
                    timestamp=ts,
                    level="exception",
                    text=text,
                    location=location,
                )
            )
        except Exception:  # noqa: BLE001 — listener must never raise
            return

    # ------------------------------------------------------------------
    # Payload helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _stringify_arg(arg: object) -> str:
        """Render a single CDP ``RemoteObject`` to a human-readable string.

        CDP ``RemoteObject`` dicts have ``type`` (``"string"``,
        ``"number"``, ``"object"``, ...) and either a ``value`` (for
        primitive types where CDP returns the value by-value) or a
        ``description`` (for objects, functions, errors, etc.). We
        prefer ``value`` for primitives and fall back to
        ``description`` otherwise so the rendered text matches what a
        user would see in DevTools.
        """
        if not isinstance(arg, dict):
            # Defensive: the protocol only ever sends dicts here, but a
            # mocked test or an unknown CDP extension might not.
            return repr(arg)

        arg_type = arg.get("type")
        if arg_type == "string":
            value = arg.get("value", "")
            return value if isinstance(value, str) else repr(value)
        if arg_type in ("number", "boolean"):
            return repr(arg.get("value"))
        if arg_type == "undefined":
            return "undefined"
        if arg_type == "symbol":
            return arg.get("description") or "Symbol()"

        # Objects, functions, errors, bigints, regexps: ``description``
        # is the DevTools-rendered preview. Fall back to ``value`` and
        # finally to ``repr`` so we never emit an empty string for a
        # non-empty arg.
        description = arg.get("description")
        if isinstance(description, str) and description:
            return description
        if "value" in arg:
            return repr(arg.get("value"))
        return repr(arg)

    @classmethod
    def _format_args(cls, args: list) -> str:
        """Join a list of CDP ``RemoteObject`` args with spaces.

        Mirrors how the browser's own console concatenates
        ``console.log("a", 1, obj)`` into a single line.
        """
        return " ".join(cls._stringify_arg(a) for a in args)

    @staticmethod
    def _coerce_timestamp(ts: object) -> float:
        """Normalise CDP timestamps (ms since epoch) to seconds.

        CDP reports ``Runtime.Timestamp`` as milliseconds since the Unix
        epoch. The buffer stores seconds since the Unix epoch (matching
        ``time.time()``) so :meth:`snapshot` can compare against
        ``WimiTestSession.start_ts`` directly. Values that are missing
        or look like seconds-since-epoch are passed through; only
        clearly-millisecond values are divided by 1000.
        """
        if isinstance(ts, (int, float)):
            value = float(ts)
            if value > _MS_THRESHOLD:
                return value / 1000.0
            if value > 0.0:
                return value
        return time.time()

    @staticmethod
    def _location_from_stack_trace(stack_trace: object) -> Optional[dict]:
        """Pull a Playwright-shaped location dict from a CDP stackTrace.

        ``stackTrace.callFrames`` is a list of frames ordered
        innermost-first; we use the topmost frame so the location
        identifies where ``console.*`` was called.
        """
        if not isinstance(stack_trace, dict):
            return None
        frames = stack_trace.get("callFrames")
        if not isinstance(frames, list) or not frames:
            return None
        top = frames[0]
        if not isinstance(top, dict):
            return None
        return {
            "url": top.get("url"),
            "lineNumber": top.get("lineNumber"),
            "columnNumber": top.get("columnNumber"),
        }

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def snapshot(
        self,
        *,
        level_min: str = "warning",
        since_ts: Optional[float] = None,
    ) -> list[ConsoleEntry]:
        """Return a filtered copy of the buffer.

        ``level_min`` filters by severity using the ranking
        ``debug < info == log < warning < error < exception``. Entries
        whose rank is greater than or equal to the rank of ``level_min``
        are kept.

        ``since_ts`` (if given) keeps only entries whose ``timestamp``
        is at or after that time — used for per-test segmentation
        against ``WimiTestSession.start_ts`` (Section 6.1).

        Returns a list (not a deque view) so callers can sort, mutate
        or extend without affecting the live buffer.

        Raises ``ValueError`` if ``level_min`` is not a known level.
        """
        try:
            min_rank = _LEVEL_RANK[level_min]
        except KeyError as exc:
            raise ValueError(
                f"Unknown level_min {level_min!r}; "
                f"expected one of {sorted(_LEVEL_RANK)}"
            ) from exc

        result: list[ConsoleEntry] = []
        for entry in self._buffer:
            if since_ts is not None and entry.timestamp < since_ts:
                continue
            entry_rank = _LEVEL_RANK.get(entry.level, min_rank)
            if entry_rank < min_rank:
                continue
            result.append(entry)
        return result

    def flush(self) -> list[ConsoleEntry]:
        """Drain the entire buffer and return its contents as a list.

        After this call the buffer is empty; subsequent :meth:`snapshot`
        calls see only entries appended after the flush. Useful at the
        end of a session or when callers want exclusive ownership of
        captured messages.
        """
        drained = list(self._buffer)
        self._buffer.clear()
        return drained
