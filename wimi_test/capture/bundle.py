"""Composition layer that bundles the three capture streams.

This module implements :class:`CaptureBundle`, the single object passed
around when a caller wants "all the diagnostic streams attached to this
session" — the failure-attachment hook in
``docs/planning/TEST_INFRASTRUCTURE.md`` §6.4 and the MCP facade adapter
described in §4 are the two primary consumers.

A ``CaptureBundle`` does not own any subscriptions or buffers itself; it
holds references to a :class:`~wimi_test.capture.console.ConsoleCapture`,
a :class:`~wimi_test.capture.network.NetworkCapture`, and (after T3.6)
a ``BridgeCapture``. ``WimiTestSession`` constructs all three captures,
calls ``attach()`` on each, then wraps them in a bundle and exposes the
bundle via ``session.captures``. Lifecycle (attach / detach) stays with
the session — the bundle is a pure read-side façade.

The bundle exists for two reasons:

1. **Uniform serialization for failure reports and MCP responses.**
   :meth:`CaptureBundle.snapshot` and :meth:`CaptureBundle.to_dict` walk
   every stream and return a JSON-friendly dict
   (``{"console": [...], "network": [...], "bridge": [...]}``). The
   pytest-html ``extras`` attachment and the MCP ``adapters.py`` shim
   (``capture_bundle_to_dict``) consume the same shape.
2. **Stream-specific access when callers need filtering knobs.** The
   underlying captures expose stream-shaped filters
   (``ConsoleCapture.snapshot(level_min=...)``,
   ``NetworkCapture.snapshot(url_substr=...)``); ``CaptureBundle``
   exposes the raw captures via read-only properties so a test author
   can reach in for a domain-specific query without giving up the
   bundle's ``flush_all`` /  ``to_dict`` convenience.

T3.6 status
-----------
This module accepts a bridge capture but treats it as optional —
callers without one construct the bundle with ``bridge=None`` and the
``"bridge"`` key in serialized output is the empty list. The
:class:`BridgeCall` on the test-driver side is a frozen
``@dataclass``, so the bridge stream is converted via
:func:`dataclasses.asdict` like the other two streams.

See also
--------
- ``TEST_INFRASTRUCTURE.md`` §4 — public API contracts.
- ``TEST_INFRASTRUCTURE.md`` §6.4 — failure attachment, which is the
  consumer that drove the ``format_console`` / ``format_network`` /
  ``format_bridge`` helpers.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from wimi_test.capture.console import ConsoleCapture
from wimi_test.capture.network import NetworkCapture

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime dependency
    from wimi_test.capture.bridge import BridgeCapture

__all__ = [
    "CaptureBundle",
    "format_console",
    "format_network",
    "format_bridge",
]


class CaptureBundle:
    """Composition of console, network, and (optional) bridge captures.

    Holds references — not ownership. The owning
    :class:`~wimi_test.session.WimiTestSession` instantiates each
    capture, attaches them, and wraps them in a bundle. Detach happens
    on the session, never here.

    Parameters
    ----------
    console:
        Required. The session-wide console capture stream.
    network:
        Required. The session-wide CDP network capture stream.
    bridge:
        Optional. The bridge-call capture stream. ``None`` until T3.6
        lands ``wimi_test.capture.bridge``; serialized output uses an
        empty list for the ``"bridge"`` key when ``None``.
    """

    def __init__(
        self,
        *,
        console: ConsoleCapture,
        network: NetworkCapture,
        bridge: "BridgeCapture | None" = None,
    ) -> None:
        self._console = console
        self._network = network
        self._bridge = bridge

    # ------------------------------------------------------------------
    # Stream accessors (read-only properties)
    # ------------------------------------------------------------------
    @property
    def console(self) -> ConsoleCapture:
        """The underlying :class:`ConsoleCapture` for stream-specific reads."""
        return self._console

    @property
    def network(self) -> NetworkCapture:
        """The underlying :class:`NetworkCapture` for stream-specific reads."""
        return self._network

    @property
    def bridge(self) -> "BridgeCapture | None":
        """The underlying ``BridgeCapture`` or ``None`` if not yet wired."""
        return self._bridge

    # ------------------------------------------------------------------
    # Combined read API
    # ------------------------------------------------------------------
    def snapshot(self, *, since_ts: float | None = None) -> dict:
        """Return a JSON-serializable snapshot of all three streams.

        The shape is::

            {
                "console": [<ConsoleEntry as dict>, ...],
                "network": [<NetworkEvent as dict>, ...],
                "bridge":  [<BridgeCall as dict>, ...],
            }

        ``since_ts`` is forwarded to every underlying ``snapshot()``
        method; entries older than ``since_ts`` are dropped, matching
        per-test segmentation against ``WimiTestSession.start_ts``
        (see §6.1). When ``bridge`` is ``None``, the ``"bridge"`` key
        maps to ``[]``.

        ``ConsoleEntry``, ``NetworkEvent``, and the test-driver-side
        ``BridgeCall`` are all dataclasses, so we use
        :func:`dataclasses.asdict` to coerce each. The producer-side
        ``BridgeCall`` in ``src/app/bridge_test_instrumentation.py`` is
        still a ``NamedTuple`` and serializes via ``_asdict()`` over the
        wire — this side reconstructs into the dataclass mirror via
        ``BridgeCall.from_dict`` (see ``wimi_test/capture/bridge.py``).
        """
        console_entries = [
            dataclasses.asdict(entry)
            for entry in self._console.snapshot(since_ts=since_ts)
        ]
        network_entries = [
            dataclasses.asdict(event)
            for event in self._network.snapshot(since_ts=since_ts)
        ]
        if self._bridge is None:
            bridge_entries: list[dict] = []
        else:
            bridge_entries = [
                dataclasses.asdict(call)
                for call in self._bridge.snapshot(since_ts=since_ts)
            ]
        return {
            "console": console_entries,
            "network": network_entries,
            "bridge": bridge_entries,
        }

    def flush_all(self) -> dict:
        """Drain every attached stream and return their full contents.

        Same shape as :meth:`snapshot`, but no ``since_ts`` filter — the
        flush pulls everything currently buffered. After this call, each
        underlying capture's buffer is empty; subsequent
        :meth:`snapshot` calls only see entries that arrived afterward.

        Detaching the underlying captures is **not** done here — that
        is :class:`~wimi_test.session.WimiTestSession.stop`'s job.
        """
        console_entries = [
            dataclasses.asdict(entry) for entry in self._console.flush()
        ]
        network_entries = [
            dataclasses.asdict(event) for event in self._network.flush()
        ]
        if self._bridge is None:
            bridge_entries: list[dict] = []
        else:
            bridge_entries = [
                dataclasses.asdict(call) for call in self._bridge.flush()
            ]
        return {
            "console": console_entries,
            "network": network_entries,
            "bridge": bridge_entries,
        }

    def to_dict(self, *, since_ts: float | None = None) -> dict:
        """Alias for :meth:`snapshot` with a name that reads better at the
        failure-report boundary (``capture_bundle_to_dict``, the MCP
        adapter, etc.). Always equivalent to ``snapshot(since_ts=...)``.
        """
        return self.snapshot(since_ts=since_ts)


# ----------------------------------------------------------------------
# Failure-report formatters
# ----------------------------------------------------------------------
# These helpers turn the dict-of-lists shape produced by
# ``CaptureBundle.snapshot()`` into compact, human-readable text. They
# are pure functions — they import nothing from ``CaptureBundle`` —
# because the failure-attachment hook (``fixtures/capture.py``) needs to
# call them after pulling a snapshot, and the MCP adapter wants the
# formatted text without re-deriving it.
#
# Each formatter accepts a list of dicts (already coerced from the
# capture module's dataclass / NamedTuple) and returns a single string,
# one entry per line, with the most useful fields surfaced. Missing
# fields fall back gracefully so a partially-filled entry never raises.


def _safe(value: object, fallback: str = "?") -> str:
    """Return ``str(value)`` or ``fallback`` if value is ``None``/empty."""
    if value is None:
        return fallback
    text = str(value)
    return text if text else fallback


def format_console(entries: list[dict]) -> str:
    """Format console entries for inclusion in a pytest-html ``extras``.

    Each entry becomes one line:
    ``"[<level>] <text> (<source.url>:<source.lineNumber>)"``. The
    location parenthetical is omitted when the entry has no
    ``location`` (e.g. ``pageerror`` records).
    """
    lines: list[str] = []
    for entry in entries:
        level = _safe(entry.get("level"), "?")
        text = _safe(entry.get("text"), "")
        location = entry.get("location")
        if isinstance(location, dict) and (location.get("url") or location.get("lineNumber") is not None):
            url = _safe(location.get("url"), "?")
            line_no = location.get("lineNumber")
            line_part = str(line_no) if line_no is not None else "?"
            lines.append(f"[{level}] {text} ({url}:{line_part})")
        else:
            lines.append(f"[{level}] {text}")
    return "\n".join(lines)


def format_network(entries: list[dict]) -> str:
    """Format network events, grouping by ``request_id`` when possible.

    Within each group, events are emitted in their original order and
    rendered as ``"<kind> <method or status> <url>"``. ``method`` is
    used on ``request`` events; ``status`` on ``response`` events;
    ``failed`` events fall back to ``error_text``. Events with no
    ``request_id`` are emitted ungrouped at the end.
    """
    grouped: dict[str, list[dict]] = {}
    ordered_keys: list[str] = []
    ungrouped: list[dict] = []
    for event in entries:
        request_id = event.get("request_id") or ""
        if not request_id:
            ungrouped.append(event)
            continue
        if request_id not in grouped:
            grouped[request_id] = []
            ordered_keys.append(request_id)
        grouped[request_id].append(event)

    lines: list[str] = []
    for key in ordered_keys:
        for event in grouped[key]:
            lines.append(_format_network_line(event))
    for event in ungrouped:
        lines.append(_format_network_line(event))
    return "\n".join(lines)


def _format_network_line(event: dict) -> str:
    kind = _safe(event.get("kind"), "?")
    url = _safe(event.get("url"), "")
    if kind == "request":
        descriptor = _safe(event.get("method"), "?")
    elif kind == "response":
        status = event.get("status")
        descriptor = str(status) if status is not None else "?"
    elif kind == "failed":
        descriptor = _safe(event.get("error_text"), "failed")
    else:
        descriptor = "?"
    return f"{kind} {descriptor} {url}".rstrip()


def format_bridge(entries: list[dict]) -> str:
    """Format bridge calls, one line per call.

    Shape: ``"<method>(<args_summary>) -> <result_summary> (<duration_ms>ms)"``.
    ``args`` and ``result`` come straight from the dict; if they are
    not strings already, ``repr`` is used so callers see something
    inspectable. Truncation of long values is the caller's concern —
    the formatter's job is faithful, line-per-call rendering.
    """
    lines: list[str] = []
    for entry in entries:
        method = _safe(entry.get("method"), "?")
        args_summary = _stringify_summary(entry.get("args"))
        result_summary = _stringify_summary(entry.get("result"))
        duration = entry.get("duration_ms")
        duration_part = f"{duration}ms" if duration is not None else "?ms"
        lines.append(
            f"{method}({args_summary}) -> {result_summary} ({duration_part})"
        )
    return "\n".join(lines)


def _stringify_summary(value: object) -> str:
    """Render a ``BridgeCall`` arg/result for one-line display."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return repr(value)
