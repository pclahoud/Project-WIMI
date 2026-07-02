"""Bridge call capture for the WIMI test infrastructure (Layer 2).

This module implements the ``@instrumented_slot`` decorator and the
``get_test_mode_bridge_calls`` helper described in
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 6.3 ("Bridge call
capture"). Together with ``src/app/test_mode.py`` (Layer 1, JS console
buffering) it forms the always-on capture path that lets a test harness
attach late and still see what happened during startup.

When the app is launched without ``--test-mode``, this module's
decorator is a **complete no-op** — applying it to a slot returns the
original function unchanged so there is zero per-call overhead in
production. When test mode is active, every wrapped call is recorded
into a per-bridge-instance bounded ring buffer
(``self._bridge_call_buffer`` — a :class:`collections.deque` with
``maxlen=2000``). The bridge later exposes this buffer to the harness
through a ``getTestModeBridgeCalls(since_ts)`` slot which delegates to
:func:`get_test_mode_bridge_calls`.

Decorator-order requirement
---------------------------

PyQt's :func:`pyqtSlot` decorator inspects the wrapped function's
signature to build its meta-object entry. To preserve that introspection,
``@instrumented_slot`` uses :func:`functools.wraps` and **must be the
inner decorator**::

    from PyQt6.QtCore import pyqtSlot
    from app.bridge_test_instrumentation import instrumented_slot

    class SomeBridgeMixin:
        @pyqtSlot(str, result=str)        # OUTER — closer to the class
        @instrumented_slot                # INNER — closer to the function
        def someMethod(self, arg: str) -> str:
            ...

Reversing the order ( ``@instrumented_slot`` outside ``@pyqtSlot``)
breaks PyQt's signature introspection and the slot will not be exposed
to QWebChannel. A CI check (``scripts/check_instrumented_slots.py``,
T3.4) walks ``src/app/bridge_domains/*.py`` and enforces the pairing.

PyQt-free at import time
------------------------

This module deliberately does **not** import any PyQt symbols. It must
be importable in plain-Python contexts (tests, CI scripts, the AST check
runner) where PyQt may not be installed. PyQt only enters the picture at
the call sites where ``@pyqtSlot`` and ``@instrumented_slot`` are
stacked on the bridge mixin methods themselves.
"""

from __future__ import annotations

import collections
import functools
import json
import logging
import time
from typing import NamedTuple

from app import test_mode

__all__ = [
    "BridgeCall",
    "instrumented_slot",
    "get_test_mode_bridge_calls",
    "INSTRUMENTED_SLOT_MARKER",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Marker attribute set on wrapper functions produced by ``instrumented_slot``.
# ``scripts/check_instrumented_slots.py`` (T3.4) uses this attribute (and/or
# the AST-visible ``@instrumented_slot`` decorator name) to verify every
# ``@pyqtSlot`` in ``src/app/bridge_domains/*.py`` is paired with an
# instrumentation decorator.
INSTRUMENTED_SLOT_MARKER: str = "_wimi_instrumented_slot"

# Maximum number of bridge calls retained per bridge instance. The buffer
# is per-instance (created lazily on the bridge object as
# ``_bridge_call_buffer``), bounded so a long-lived test session can't
# leak memory. 2000 entries comfortably exceeds the burst rate during a
# single page load while staying small in absolute terms.
_BRIDGE_CALL_BUFFER_MAXLEN: int = 2000

# Default truncation length for both ``args_summary`` and
# ``result_summary``. Kept short so the buffer remains compact and
# JSON-serialization stays fast even for chatty slots.
_DEFAULT_SUMMARY_MAX_LEN: int = 200

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data type
# ---------------------------------------------------------------------------


class BridgeCall(NamedTuple):
    """A single recorded ``@pyqtSlot`` invocation.

    Attributes:
        timestamp: ``time.time()`` value at the moment the call started.
        method: The wrapped slot's ``__name__`` (e.g. ``"getEntries"``).
        args_summary: Short ``repr`` of the positional + keyword args,
            truncated to roughly 200 characters with ``"..."`` appended
            when truncation occurred.
        result_summary: Short ``repr`` of the return value, or for
            exceptions ``"<ExcClass>: <message>"``. Same truncation
            rules as ``args_summary``.
        duration_ms: Wall-clock milliseconds from entry to return /
            exception, computed as ``(time.time() - t0) * 1000``.
        error: ``True`` if the slot raised, ``False`` if it returned
            normally.
    """

    timestamp: float
    method: str
    args_summary: str
    result_summary: str
    duration_ms: float
    error: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize(value: object, max_len: int = _DEFAULT_SUMMARY_MAX_LEN) -> str:
    """Render ``value`` as a short, safe string for buffer storage.

    Exceptions get a ``"<ClassName>: <message>"`` rendering so the
    summary is still readable even when ``repr(exc)`` would be noisy.
    Everything else goes through :func:`repr`. The result is truncated
    to ``max_len`` characters with ``"..."`` appended when truncation
    occurred, so callers can see at a glance that more data existed.

    The function never raises: a misbehaving ``__repr__`` falls back to
    a placeholder string so logging can't break the slot path.
    """
    try:
        if isinstance(value, BaseException):
            text = f"{type(value).__name__}: {value}"
        else:
            text = repr(value)
    except Exception as exc:  # pragma: no cover — defensive
        text = f"<unrepresentable {type(value).__name__}: {exc!r}>"

    if len(text) > max_len:
        # Reserve three chars for the ellipsis so the total stays under
        # ``max_len + 3`` — predictable for downstream JSON budgets.
        return text[:max_len] + "..."
    return text


def _log_bridge_call(
    self: object,
    method_name: str,
    args: tuple,
    kwargs: dict,
    result: object,
    duration_ms: float,
    error: bool,
) -> None:
    """Append a :class:`BridgeCall` to ``self._bridge_call_buffer``.

    The buffer is created lazily on first use so bridge ``__init__``
    code doesn't need to know about test mode. Every step is wrapped in
    a broad ``try/except`` because a logging failure must never propagate
    out of an instrumented slot — the slot's own behavior is more
    important than the capture record.
    """
    try:
        buffer = getattr(self, "_bridge_call_buffer", None)
        if buffer is None:
            buffer = collections.deque(maxlen=_BRIDGE_CALL_BUFFER_MAXLEN)
            # Stash on the instance — subsequent calls reuse the same deque.
            self._bridge_call_buffer = buffer  # type: ignore[attr-defined]

        # Combine args + kwargs into a single summary so the JSON shape
        # stays a flat string. ``kwargs`` is rare on PyQt slots but we
        # support it for completeness.
        if kwargs:
            args_repr = _summarize((args, kwargs))
        else:
            args_repr = _summarize(args)

        entry = BridgeCall(
            timestamp=time.time(),
            method=method_name,
            args_summary=args_repr,
            result_summary=_summarize(result),
            duration_ms=duration_ms,
            error=error,
        )
        buffer.append(entry)
    except Exception:  # pragma: no cover — defensive
        # Never let capture failures leak into the slot's behavior.
        _logger.warning(
            "bridge_test_instrumentation: failed to record call to %r",
            method_name,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# The decorator
# ---------------------------------------------------------------------------


def instrumented_slot(wrapped):
    """Decorator that records bridge slot calls when test mode is active.

    Behavior:

    * If ``test_mode.is_active()`` is ``False`` at decoration time
      (i.e. the normal production path), this is a **complete no-op**
      and returns ``wrapped`` unchanged. There is zero per-call overhead
      and the function object PyQt sees is exactly the original.
    * Otherwise it returns a :func:`functools.wraps`-preserving wrapper
      that records each invocation into ``self._bridge_call_buffer``
      via :func:`_log_bridge_call`, then returns the original result
      (or re-raises, after logging the exception as ``error=True``).

    **Decorator order requirement:** ``@pyqtSlot`` must be the *outer*
    decorator (closer to the class) and ``@instrumented_slot`` must be
    the *inner* decorator (closer to the function)::

        @pyqtSlot(str, result=str)
        @instrumented_slot
        def someMethod(self, arg: str) -> str:
            ...

    Reversing the order breaks PyQt's signature introspection — see the
    module docstring for the rationale.

    The wrapper sets the :data:`INSTRUMENTED_SLOT_MARKER` attribute
    (``_wimi_instrumented_slot = True``) so the CI check in
    ``scripts/check_instrumented_slots.py`` (T3.4) can verify pairing
    via either AST inspection of the decorator name or runtime
    introspection of the marker.
    """
    if not test_mode.is_active():
        # Production path: hand back the original function untouched.
        # No closure, no overhead, and PyQt's introspection sees the
        # exact same signature it would without this module installed.
        return wrapped

    method_name = getattr(wrapped, "__name__", "<anonymous_slot>")

    @functools.wraps(wrapped)
    def wrapper(self, *args, **kwargs):
        t0 = time.time()
        try:
            result = wrapped(self, *args, **kwargs)
        except Exception as exc:
            duration_ms = (time.time() - t0) * 1000.0
            _log_bridge_call(
                self,
                method_name,
                args,
                kwargs,
                result=exc,
                duration_ms=duration_ms,
                error=True,
            )
            raise
        duration_ms = (time.time() - t0) * 1000.0
        _log_bridge_call(
            self,
            method_name,
            args,
            kwargs,
            result=result,
            duration_ms=duration_ms,
            error=False,
        )
        return result

    # CI marker — see ``scripts/check_instrumented_slots.py`` (T3.4).
    setattr(wrapper, INSTRUMENTED_SLOT_MARKER, True)
    return wrapper


# ---------------------------------------------------------------------------
# Bridge-side accessor (wired into the bridge in a later task)
# ---------------------------------------------------------------------------


def get_test_mode_bridge_calls(self: object, since_ts: float = 0.0) -> str:
    """Return buffered bridge calls as a JSON string.

    Intended to be wired into the bridge as a ``@pyqtSlot`` in a later
    task (T3.5*); kept here as a free function so this module stays
    PyQt-free at import time. The bridge mixin will register it via
    something like::

        @pyqtSlot(float, result=str)
        def getTestModeBridgeCalls(self, since_ts: float = 0.0) -> str:
            return get_test_mode_bridge_calls(self, since_ts)

    Behavior:

    * If test mode is inactive, returns ``'[]'`` immediately —
      regardless of whether any stale buffer happens to exist on the
      instance from a previous session.
    * If ``self._bridge_call_buffer`` does not exist yet, returns
      ``'[]'``.
    * Otherwise filters entries to ``entry.timestamp > since_ts``
      (strictly greater than the cursor), serializes each via
      :meth:`NamedTuple._asdict`, and returns the list as a JSON string.

    The ``since_ts`` parameter lets the harness poll incrementally
    without re-fetching the entire buffer each tick. The filter is
    **strictly greater than** ``since_ts`` rather than ``>=`` so that a
    consumer which advances its cursor to ``max(timestamp_seen)`` does
    not re-fetch the boundary entry on the next poll. The first poll
    typically uses ``since_ts=0.0`` and gets every buffered entry, so
    no record is dropped at the lower bound; subsequent polls receive
    only entries strictly after the previously-observed maximum.
    """
    if not test_mode.is_active():
        return "[]"

    buffer = getattr(self, "_bridge_call_buffer", None)
    if buffer is None:
        return "[]"

    # Materialize a list snapshot first — the deque could mutate while we
    # iterate if a slot fires on another thread (PyQt slots are normally
    # main-thread-only, but defensive snapshotting is cheap).
    snapshot = list(buffer)
    selected = [
        entry._asdict() for entry in snapshot if entry.timestamp > since_ts
    ]
    return json.dumps(selected, ensure_ascii=False)
