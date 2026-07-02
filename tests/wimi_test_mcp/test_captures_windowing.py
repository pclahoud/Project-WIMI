"""Tests for the per-session capture-response windowing in the MCP facade.

Background
----------
``recent()`` historically returned the trailing ``limit`` entries from
each capture stream regardless of age. Because the streams are
append-only since session start, the ~18 console errors fired during
WIMI's landing-page init (the "no user database connected" warnings
emitted before ``loadTestUserDatabase`` runs) permanently occupied
positions 1-18 of the console stream and rode every successful tool
response back to Claude — ~3 KB of stale startup noise per round trip.

The fix introduces a per-session watermark
(``SessionRegistry._last_response_ts``) and threads it through
``recent()`` / ``success()`` so each MCP tool response only carries
activity that arrived between the previous tool response and this one.

These tests cover the four observable contracts of that change:

1. ``recent(bundle, since_ts=...)`` filters stream entries by timestamp.
2. ``success(data, captures=..., since_ts=...)`` forwards the floor.
3. ``SessionRegistry.consume_capture_window`` advances its watermark
   atomically so successive calls produce non-overlapping windows.
4. The first call after ``start()`` falls back to the session-start
   timestamp (so pre-session noise is excluded but the post-start
   landing-page burst still surfaces on the very first response).
5. Calls without a session/since_ts argument preserve the legacy
   ``recent()`` behaviour, guarding backwards compatibility for the
   public ``success()`` signature.
"""

from __future__ import annotations

import time
from typing import Optional

import pytest

from wimi_test.capture.bundle import CaptureBundle
from wimi_test.capture.console import ConsoleCapture, ConsoleEntry
from wimi_test.capture.network import NetworkCapture, NetworkEvent
from wimi_test_mcp.adapters import recent, success
from wimi_test_mcp.registry import SessionRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bundle() -> CaptureBundle:
    """Build a real CaptureBundle backed by un-attached captures.

    We push entries directly into the underlying deques rather than
    going through CDP — the MCP-facade windowing is independent of
    where entries originate, so a real bundle with synthetic entries
    is the most faithful test surface that does not require Playwright.
    """
    return CaptureBundle(
        console=ConsoleCapture(),
        network=NetworkCapture(),
        bridge=None,
    )


def _push_console(
    bundle: CaptureBundle, *, timestamp: float, text: str, level: str = "warning"
) -> None:
    """Append a synthetic ConsoleEntry to the bundle's console buffer."""
    bundle.console._buffer.append(  # type: ignore[attr-defined]
        ConsoleEntry(
            timestamp=timestamp,
            level=level,
            text=text,
            location=None,
        )
    )


def _push_network(
    bundle: CaptureBundle, *, timestamp: float, url: str, request_id: str = "r1"
) -> None:
    """Append a synthetic NetworkEvent to the bundle's network buffer."""
    bundle.network._buffer.append(  # type: ignore[attr-defined]
        NetworkEvent(
            timestamp=timestamp,
            kind="request",
            request_id=request_id,
            url=url,
            method="GET",
            raw={},
        )
    )


# ---------------------------------------------------------------------------
# 1. recent() honours since_ts
# ---------------------------------------------------------------------------


def test_recent_with_since_ts_filters_old_entries() -> None:
    """``recent(bundle, since_ts=150)`` drops entries with timestamp <= 150."""
    bundle = _make_bundle()
    _push_console(bundle, timestamp=100.0, text="early")
    _push_console(bundle, timestamp=200.0, text="late")

    out = recent(bundle, since_ts=150.0)

    assert len(out["console"]) == 1
    assert out["console"][0]["text"] == "late"
    assert out["summary"]["console_count"] == 1


def test_recent_without_since_ts_returns_all_within_limit() -> None:
    """No ``since_ts`` keeps the legacy behaviour: trailing ``limit`` tail."""
    bundle = _make_bundle()
    _push_console(bundle, timestamp=100.0, text="early")
    _push_console(bundle, timestamp=200.0, text="late")

    out = recent(bundle)

    assert len(out["console"]) == 2
    assert {e["text"] for e in out["console"]} == {"early", "late"}


# ---------------------------------------------------------------------------
# 2. success() forwards since_ts to recent()
# ---------------------------------------------------------------------------


def test_success_uses_since_ts_when_provided() -> None:
    """``success(data, captures=..., since_ts=T)`` filters captures at T.

    Documents the chosen integration: tools call
    ``_registry.consume_capture_window()`` to obtain the floor and pass
    it as the ``since_ts`` keyword to ``success()``. The watermark
    itself lives on the registry, not on the bundle (see
    ``SessionRegistry._last_response_ts``).
    """
    bundle = _make_bundle()
    _push_console(bundle, timestamp=50.0, text="before-cutoff")
    _push_console(bundle, timestamp=300.0, text="after-cutoff")

    payload = success({"ok": 1}, captures=bundle, since_ts=200.0)

    captures = payload["captures"]
    assert captures is not None
    texts = [e["text"] for e in captures["console"]]
    assert texts == ["after-cutoff"]


# ---------------------------------------------------------------------------
# 3. consume_capture_window advances the watermark
# ---------------------------------------------------------------------------


def test_consume_capture_window_advances_watermark_after_call() -> None:
    """First ``consume_capture_window()`` returns the start floor and bumps
    the watermark to "now" so the next call sees only post-now activity.
    """
    registry = SessionRegistry()
    # Simulate a successful start without spinning up Playwright.
    fake_start = time.time() - 10.0
    registry._session_start_ts = fake_start
    registry._last_response_ts = None

    first_cutoff = registry.consume_capture_window()
    # First call: floor at session start so the first response still
    # surfaces post-start activity.
    assert first_cutoff == fake_start
    # Watermark is now "now" so the next call sees only entries newer
    # than this point.
    assert registry._last_response_ts is not None
    assert registry._last_response_ts >= fake_start

    advanced_to = registry._last_response_ts
    time.sleep(0.01)  # ensure a non-zero gap
    second_cutoff = registry.consume_capture_window()
    # Second call returns the watermark set by the first call.
    assert second_cutoff == advanced_to
    # And bumps it forward again.
    assert registry._last_response_ts is not None
    assert registry._last_response_ts >= advanced_to


def test_first_call_after_session_start_uses_session_start_ts() -> None:
    """No prior watermark -> floor at session start, not None.

    Design choice: the very first MCP tool response after
    ``start_session`` includes captures with timestamp greater than the
    session-start timestamp. This excludes pre-session noise (residue
    from a prior session in the same process) while still surfacing the
    landing-page init burst that happens immediately after start.

    An alternate design would pass ``None`` (no filter) on the first
    call to surface the entire session history; we explicitly chose the
    session-start floor so the first response is no noisier than later
    ones once a previous session leaked entries.
    """
    registry = SessionRegistry()
    registry._session_start_ts = 12345.0
    registry._last_response_ts = None

    cutoff = registry.consume_capture_window()

    assert cutoff == 12345.0


def test_consume_capture_window_with_no_session_returns_none() -> None:
    """Defensive: no active session and no prior response -> ``None``.

    This path is unreachable from live tool handlers (which always have
    an active session by the time they reach ``success``), but the
    contract of ``consume_capture_window`` is preserved so a stray
    invocation does not crash with a stale-watermark error.
    """
    registry = SessionRegistry()

    cutoff = registry.consume_capture_window()

    assert cutoff is None


# ---------------------------------------------------------------------------
# 4. End-to-end: two tool calls produce non-overlapping windows
# ---------------------------------------------------------------------------


def test_two_successive_tool_calls_window_correctly() -> None:
    """Simulate two MCP tool calls; verify second response only carries
    entries that arrived between the first and second responses.

    Reproduces the exact bug scenario: 18 startup-noise entries get
    surfaced once on the first response, but never re-attached on the
    second response.
    """
    registry = SessionRegistry()
    bundle = _make_bundle()

    # Use a timestamp clearly in the past so the synthetic startup
    # entries' timestamps are < ``time.time()`` at the moment
    # ``consume_capture_window`` snapshots the watermark — otherwise the
    # entries' timestamps could race the wall-clock advance and slip
    # past the second filter. This is purely a test-fixture concern;
    # in real usage every entry's timestamp is set by the capture
    # listener before the next tool handler runs.
    session_start = time.time() - 100.0
    registry._session_start_ts = session_start
    registry._last_response_ts = None

    # Simulate startup noise: 18 console errors that fired immediately
    # after session start.
    for i in range(18):
        _push_console(
            bundle, timestamp=session_start + 0.01 * i, text=f"startup-{i}"
        )

    # First tool call: should include the 18 startup entries.
    first_cutoff = registry.consume_capture_window()
    first_response = success(
        {"action": "navigate"}, captures=bundle, since_ts=first_cutoff
    )
    first_console = first_response["captures"]["console"]
    first_texts = {e["text"] for e in first_console}
    assert first_texts == {f"startup-{i}" for i in range(18)}

    # Between-calls activity: one new console entry timestamped after
    # the watermark the first response just set.
    between_ts = registry._last_response_ts + 0.001
    _push_console(bundle, timestamp=between_ts, text="user-action")

    # Second tool call: should ONLY see "user-action", not any of the
    # 18 startup entries.
    second_cutoff = registry.consume_capture_window()
    second_response = success(
        {"action": "click"}, captures=bundle, since_ts=second_cutoff
    )
    second_console = second_response["captures"]["console"]
    second_texts = [e["text"] for e in second_console]
    assert second_texts == ["user-action"], (
        "Second response leaked stale startup noise: " f"{second_texts!r}"
    )


# ---------------------------------------------------------------------------
# 5. Backwards compatibility of success()
# ---------------------------------------------------------------------------


def test_success_no_since_ts_falls_back_to_legacy_recent() -> None:
    """Legacy callers that pass only ``captures=`` still work.

    The fix must not break the public signature; existing code calling
    ``success(data, captures=bundle)`` without the new ``since_ts``
    keyword should produce the same trailing-tail behaviour as before.
    """
    bundle = _make_bundle()
    _push_console(bundle, timestamp=10.0, text="old")
    _push_console(bundle, timestamp=20.0, text="new")

    payload = success({"ok": 1}, captures=bundle)

    captures = payload["captures"]
    assert captures is not None
    texts = {e["text"] for e in captures["console"]}
    # No filter -> both entries surface (within limit=20).
    assert texts == {"old", "new"}


def test_success_no_captures_returns_none_captures_field() -> None:
    """``success`` without a bundle keeps ``captures=None`` in the payload.

    This is the lifecycle-tools path (``end_session``,
    ``start_session``) that never attaches a bundle.
    """
    payload = success({"handle": "h1"})

    assert payload == {"ok": True, "data": {"handle": "h1"}, "captures": None}


# ---------------------------------------------------------------------------
# 6. Network stream is windowed too (not just console)
# ---------------------------------------------------------------------------


def test_recent_filters_network_stream_by_since_ts() -> None:
    """``since_ts`` applies uniformly across all three streams."""
    bundle = _make_bundle()
    _push_network(
        bundle, timestamp=50.0, url="qrc:///old.js", request_id="r1"
    )
    _push_network(
        bundle, timestamp=200.0, url="qrc:///new.js", request_id="r2"
    )

    out = recent(bundle, since_ts=100.0)

    urls = [e["url"] for e in out["network"]]
    assert urls == ["qrc:///new.js"]
    assert out["summary"]["network_count"] == 1
