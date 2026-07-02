"""MCP-facing serializers for `CaptureBundle` and library exceptions.

This module is the leaf adapter layer described in
``docs/planning/TEST_INFRASTRUCTURE.md`` §8. It exists to keep the
``wimi_test_mcp`` server tools as 1-call shims: each tool resolves a
session, performs its action via the underlying ``wimi_test`` library,
then funnels the result through the helpers here to produce a
JSON-friendly response payload that FastMCP can return verbatim.

Responsibilities
----------------
- Convert a :class:`~wimi_test.capture.bundle.CaptureBundle` snapshot
  into a dict with summary counts (``capture_bundle_to_dict``).
- Provide a "recent activity" tail of each capture stream so successful
  tool responses can show Claude the last N entries without flooding
  the channel (``recent``).
- Translate any :class:`~wimi_test.errors.WimiTestError` (or unexpected
  exception) into a structured ``{"ok": False, "error": {...}}`` payload
  the server tools can return without leaking tracebacks
  (``exception_to_dict``).
- Wrap a successful tool result with attached recent captures
  (``success``).

Constraints
-----------
This module is pure and side-effect free: no I/O, no mutation, no
imports from anywhere except the stdlib, ``wimi_test.capture.bundle``
and ``wimi_test.errors``. That keeps it cheap to import from FastMCP
tool modules and trivial to unit-test in isolation.
"""

from __future__ import annotations

from typing import Optional

from wimi_test.capture.bundle import CaptureBundle
from wimi_test.errors import (
    AssertionFailureWithCapture,
    AttachTimeout,
    LocatorAmbiguous,
    ProcessSpawnError,
    WimiTestError,
)

__all__ = [
    "capture_bundle_to_dict",
    "recent",
    "exception_to_dict",
    "success",
]


def capture_bundle_to_dict(
    bundle: CaptureBundle,
    *,
    since_ts: Optional[float] = None,
) -> dict:
    """Serialize a full :class:`CaptureBundle` snapshot for an MCP response.

    Wraps :meth:`CaptureBundle.snapshot` and decorates the result with
    the ``since_ts`` filter (echoed back so callers can correlate) and
    a ``summary`` block of per-stream entry counts. The counts let
    Claude tell at a glance whether each stream has data without having
    to enumerate the (potentially large) entry lists.

    Parameters
    ----------
    bundle:
        The capture bundle to read. Must be non-``None`` — callers that
        may not have an active session should use :func:`recent`
        instead, which tolerates ``None``.
    since_ts:
        Optional epoch-seconds floor; entries older than this are
        dropped. Forwarded to :meth:`CaptureBundle.snapshot`.

    Returns
    -------
    dict
        Shape::

            {
                "since_ts": <float | None>,
                "console": [<entry dict>, ...],
                "network": [<event dict>, ...],
                "bridge":  [<call dict>, ...],
                "summary": {
                    "console_count": <int>,
                    "network_count": <int>,
                    "bridge_count": <int>,
                },
            }
    """
    snapshot = bundle.snapshot(since_ts=since_ts)
    console_entries = snapshot["console"]
    network_entries = snapshot["network"]
    bridge_entries = snapshot["bridge"]
    return {
        "since_ts": since_ts,
        "console": console_entries,
        "network": network_entries,
        "bridge": bridge_entries,
        "summary": {
            "console_count": len(console_entries),
            "network_count": len(network_entries),
            "bridge_count": len(bridge_entries),
        },
    }


def recent(
    bundle: Optional[CaptureBundle],
    *,
    limit: int = 20,
    since_ts: Optional[float] = None,
) -> dict:
    """Return the last ``limit`` entries from each capture stream.

    Used by every successful tool response so Claude sees what just
    happened without re-querying. The output mirrors
    :func:`capture_bundle_to_dict` minus the ``since_ts`` echo.

    A ``bundle`` of ``None`` is tolerated — that's the case before a
    session has been started — and yields an "empty bundle" payload
    with all three stream lists empty and zeroed counts. This means
    tool implementations can blindly call ``recent(session.captures)``
    even on the failure path where ``session`` was never assigned.

    Parameters
    ----------
    bundle:
        The capture bundle, or ``None`` if no session is active.
    limit:
        Maximum number of trailing entries to include from each stream.
        Defaults to 20, which is enough for a typical Claude turn but
        small enough to keep responses cheap.
    since_ts:
        Optional epoch-seconds floor; entries with ``timestamp <=
        since_ts`` are dropped *before* the trailing-``limit`` slice.
        Forwarded to :meth:`CaptureBundle.snapshot`. The MCP server
        threads its per-session response watermark through this
        parameter so each tool response only carries activity that
        occurred since the previous response — see
        :meth:`SessionRegistry.consume_capture_window`.

    Returns
    -------
    dict
        Shape::

            {
                "console": [<entry dict>, ...],   # last `limit`
                "network": [<event dict>, ...],   # last `limit`
                "bridge":  [<call dict>, ...],    # last `limit`
                "summary": {
                    "console_count": <int>,
                    "network_count": <int>,
                    "bridge_count": <int>,
                },
            }
    """
    if bundle is None:
        return {
            "console": [],
            "network": [],
            "bridge": [],
            "summary": {
                "console_count": 0,
                "network_count": 0,
                "bridge_count": 0,
            },
        }
    snapshot = bundle.snapshot(since_ts=since_ts)
    console_entries = snapshot["console"][-limit:]
    network_entries = snapshot["network"][-limit:]
    bridge_entries = snapshot["bridge"][-limit:]
    return {
        "console": console_entries,
        "network": network_entries,
        "bridge": bridge_entries,
        "summary": {
            "console_count": len(console_entries),
            "network_count": len(network_entries),
            "bridge_count": len(bridge_entries),
        },
    }


def exception_to_dict(exc: Exception) -> dict:
    """Translate an exception into a structured MCP error payload.

    Tool handlers in ``wimi_test_mcp`` catch exceptions at the tool
    boundary and pass them through this helper so the response is
    always JSON-shaped, never a traceback. Each known
    :class:`~wimi_test.errors.WimiTestError` subclass contributes its
    type-specific structured fields under ``error.fields``; unknown
    exceptions get a generic ``{"unexpected": True}`` marker so the
    consumer can distinguish "a library-level error happened" from
    "something went wrong nobody anticipated".

    Parameters
    ----------
    exc:
        The exception to serialize. Anything is accepted; the function
        does not re-raise.

    Returns
    -------
    dict
        Shape::

            {
                "ok": False,
                "error": {
                    "type": "<exception class name>",
                    "message": "<str(exc)>",
                    "fields": { ... type-specific extras ... },
                },
            }
    """
    if isinstance(exc, ProcessSpawnError):
        fields: dict = {
            "exit_code": exc.exit_code,
            "last_stdout": exc.last_stdout,
        }
    elif isinstance(exc, AttachTimeout):
        fields = {
            "port": exc.port,
            "elapsed_s": exc.elapsed_s,
            "last_stdout": exc.last_stdout,
        }
    elif isinstance(exc, LocatorAmbiguous):
        fields = {
            "strategy": exc.strategy,
            "matches": exc.matches,
        }
    elif isinstance(exc, AssertionFailureWithCapture):
        fields = {
            "captures_attached": exc.captures is not None,
        }
    elif isinstance(exc, WimiTestError):
        # Known library error with no extra structured fields. Keeping
        # this branch explicit (rather than folding into the catch-all)
        # signals "we recognise this as a library error" via the
        # absence of the ``unexpected`` marker.
        fields = {}
    else:
        fields = {"unexpected": True}
    return {
        "ok": False,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "fields": fields,
        },
    }


def success(
    data: dict,
    captures: Optional[CaptureBundle] = None,
    *,
    since_ts: Optional[float] = None,
) -> dict:
    """Wrap a successful tool result with attached recent capture activity.

    The standard shape every successful MCP tool returns. ``data`` is
    whatever the tool wants to surface (e.g. a screenshot's base64
    payload, a fetched DOM string); ``captures`` is the active
    session's bundle, used to attach a tail of recent stream activity
    so Claude can see the side-effects of the call.

    Parameters
    ----------
    data:
        Tool-specific payload. Passed through verbatim.
    captures:
        The active session's :class:`CaptureBundle`, or ``None`` if the
        tool has no associated session (e.g. ``end_session``). When
        ``None``, the ``"captures"`` key in the response is ``None``
        rather than an empty bundle dict — distinct from "session
        active but no events", which yields the empty-counts shape via
        :func:`recent`.
    since_ts:
        Optional epoch-seconds floor for the captures payload, forwarded
        to :func:`recent`. Tool handlers obtain this from
        :meth:`SessionRegistry.consume_capture_window` so the response
        only carries entries that arrived since the previous successful
        tool response — preventing startup-noise re-attachment on every
        round trip. ``None`` (the default) preserves legacy behaviour:
        the trailing-``limit`` tail of every stream, regardless of age.

    Returns
    -------
    dict
        Shape::

            {
                "ok": True,
                "data": <data dict>,
                "captures": <recent(captures) dict | None>,
            }
    """
    return {
        "ok": True,
        "data": data,
        "captures": (
            recent(captures, since_ts=since_ts)
            if captures is not None
            else None
        ),
    }
