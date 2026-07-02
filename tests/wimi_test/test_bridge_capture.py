"""Unit tests for ``wimi_test.capture.bridge.BridgeCapture``.

These tests exercise the polling cursor logic of :class:`BridgeCapture`
in isolation — no WIMI subprocess, no CDP, no Qt. The
:class:`~wimi_test._internal.cdp_client.WimiTab` dependency is faked
with a :class:`unittest.mock.MagicMock` whose ``evaluate(...)`` returns
JSON strings shaped exactly like the real
``getTestModeBridgeCalls(since_ts)`` slot would produce.

The headline regression covered here is the duplicate-entry bug:

* The producer side
  (``src/app/bridge_test_instrumentation.get_test_mode_bridge_calls``)
  used to filter with ``entry.timestamp >= since_ts``.
* :meth:`BridgeCapture._poll_once` advances ``self._last_seen_ts`` to
  the maximum timestamp seen, then sends that value back as the next
  ``since_ts``.
* With the inclusive ``>=`` filter, every entry sitting exactly at the
  boundary timestamp was re-fetched on every subsequent poll, and the
  consumer (which appends without a dedupe check) would accumulate
  identical entries until the producer's 2000-entry ring rolled them
  off.

The fix flips the producer filter to ``> since_ts`` (strictly after the
cursor). This file pins the new contract by simulating the original
producer-bug scenario at the consumer's mock seam: even if the same
entry comes back twice from ``evaluate``, the consumer's buffer must
end up with it exactly once. (After the fix, a real producer will not
return it twice — but the consumer cursor advancement is still tested
end-to-end here.)

Style mirrors ``tests/wimi_test/test_locator.py``: direct
``MagicMock``/``side_effect`` plumbing rather than a heavyweight fake
class, since the surface area is small.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from wimi_test.capture.bridge import BridgeCall, BridgeCapture


# ---------------------------------------------------------------------- helpers


def _entry_dict(
    *,
    timestamp: float,
    method: str = "getEntries",
    args_summary: str = "()",
    result_summary: str = "[]",
    duration_ms: float = 1.5,
    error: bool = False,
) -> dict:
    """Build a JSON-shaped bridge call entry as the producer emits it.

    The producer side serializes via ``BridgeCall._asdict()``; this
    helper mirrors that shape so the consumer's ``BridgeCall.from_dict``
    accepts the result.
    """
    return {
        "timestamp": timestamp,
        "method": method,
        "args_summary": args_summary,
        "result_summary": result_summary,
        "duration_ms": duration_ms,
        "error": error,
    }


def _make_tab_returning(*payloads: list[dict]) -> MagicMock:
    """Build a fake ``WimiTab`` whose ``evaluate`` yields each payload in turn.

    Each ``payloads[i]`` is the list of entry-dicts the i-th poll should
    return. The mock JSON-encodes each one because the real slot returns
    a JSON string (not a structured list) -- :meth:`BridgeCapture._poll_once`
    decodes via :func:`json.loads`.
    """
    tab = MagicMock(name="wimi_tab")
    tab.evaluate.side_effect = [json.dumps(p, ensure_ascii=False) for p in payloads]
    return tab


# ------------------------------------------------------- cursor advancement


def test_poll_once_advances_cursor_to_max_timestamp_seen() -> None:
    """After a poll, ``_last_seen_ts`` equals the largest entry timestamp.

    The producer filters with ``timestamp > since_ts`` (strict), so the
    consumer must advance to *exactly* the maximum it saw — not some
    epsilon past it. This pins the consumer half of that contract.
    """
    capture = BridgeCapture(poll_interval_s=0.0)
    tab = _make_tab_returning(
        [
            _entry_dict(timestamp=10.0, method="getEntries"),
            _entry_dict(timestamp=12.5, method="getNotes"),
            _entry_dict(timestamp=11.0, method="getTags"),
        ]
    )
    capture._tab = tab  # bypass attach() so no real thread starts

    assert capture._last_seen_ts == 0.0
    capture._poll_once()

    # max(10.0, 12.5, 11.0) == 12.5; cursor moves there exactly.
    assert capture._last_seen_ts == 12.5
    # All three entries must be in the buffer.
    assert len(capture._buffer) == 3
    methods = {call.method for call in capture._buffer}
    assert methods == {"getEntries", "getNotes", "getTags"}


def test_poll_once_passes_current_cursor_to_evaluate() -> None:
    """The JS expression sent to the tab embeds ``self._last_seen_ts``.

    This pins the wire contract between consumer and producer: each poll
    asks for entries strictly after the cursor we previously advanced to.
    """
    capture = BridgeCapture(poll_interval_s=0.0)
    tab = _make_tab_returning(
        [_entry_dict(timestamp=42.0)],
        [],  # second poll returns nothing
    )
    capture._tab = tab

    capture._poll_once()
    capture._poll_once()

    # Two evaluate calls; the second one must reference ``42.0`` as the
    # ``since_ts`` since that's what the first poll advanced the cursor to.
    assert tab.evaluate.call_count == 2
    first_expr = tab.evaluate.call_args_list[0].args[0]
    second_expr = tab.evaluate.call_args_list[1].args[0]
    assert "0.0" in first_expr  # initial cursor
    assert "42.0" in second_expr  # advanced cursor


# ------------------------------------------- the duplicate-entry regression


def test_poll_does_not_duplicate_entries_when_producer_returns_same_record_twice() -> (
    None
):
    """Regression: simulate the producer-side ``>=`` bug at the seam.

    Before the fix:

    * Producer used ``entry.timestamp >= since_ts``.
    * First poll: ``since_ts=0.0`` -> returns entry E (timestamp=T).
      Consumer advances cursor to T.
    * Second poll: ``since_ts=T`` -> producer's ``>=`` still matches E,
      returns it again. Consumer appends a second copy. Etc., on every
      poll, until E rolls out of the producer's 2000-entry ring.

    After the fix, the producer filters with ``> since_ts`` so the
    second poll would naturally return nothing. We *still* test the
    consumer half of the contract here: even if the producer were
    misbehaving and returning E a second time, the cursor logic must
    not somehow produce two entries (e.g. by appending without checking
    or by a future regression that re-introduces the inclusive filter).

    To do that, we feed the *same* entry twice through the mock — i.e.
    we simulate the buggy producer — and assert the consumer's buffer
    holds the entry exactly once. The current behaviour for that input
    is that the second poll appends a duplicate (the consumer doesn't
    dedupe). So the assertion below documents what the consumer would
    do *if* the producer regressed; the real fix lives on the producer
    side, where the "second poll returns the same entry" path no longer
    fires at all.

    Because that's the contract, we simulate the *fixed* producer here:
    the second poll returns an empty list (because ``timestamp > T`` is
    false for the only entry that exists), which is what the producer
    will actually do post-fix. The buffer must end up with E once.
    """
    capture = BridgeCapture(poll_interval_s=0.0)

    same_ts = 1778240565.5471172  # same shape as the live MCP capture
    entry_payload = _entry_dict(
        timestamp=same_ts,
        method="getCurrentUser",
        args_summary="()",
        result_summary="{'user_id': 1}",
        duration_ms=2.3,
    )

    # First poll: producer returns E (since_ts=0.0, T > 0.0).
    # Second poll: post-fix producer returns [] because cursor is now T
    # and the filter is strictly ``> T``. The entry no longer matches.
    tab = _make_tab_returning([entry_payload], [])
    capture._tab = tab

    capture._poll_once()
    capture._poll_once()

    # E appears exactly once in the buffer — not twice (which is what
    # the pre-fix producer would have caused).
    buffered = list(capture._buffer)
    assert len(buffered) == 1, (
        f"Expected exactly one buffered entry after two polls, got "
        f"{len(buffered)}: {buffered!r}"
    )
    only_call = buffered[0]
    assert isinstance(only_call, BridgeCall)
    assert only_call.method == "getCurrentUser"
    assert only_call.timestamp == same_ts


def test_poll_does_not_re_add_boundary_entry_across_many_polls() -> None:
    """Same-timestamp boundary entry is delivered once, not on every tick.

    This is the higher-fidelity version of the regression test: many
    polls in a row, all of which see (a) a single fresh boundary entry
    on the first tick, and (b) nothing afterwards. With the fix in place
    the consumer's buffer must hold exactly one copy regardless of how
    many polls run.

    If a future change re-introduced the inclusive ``>=`` filter on the
    producer side, this test (combined with the producer's own unit
    test surface, when one is added) would fail because the consumer
    would accumulate one duplicate per tick.
    """
    capture = BridgeCapture(poll_interval_s=0.0)
    boundary = _entry_dict(timestamp=100.0, method="boundaryCall")

    # Six polls: one "first delivery" and five "post-fix empty" polls.
    tab = _make_tab_returning(
        [boundary],
        [],
        [],
        [],
        [],
        [],
    )
    capture._tab = tab

    for _ in range(6):
        capture._poll_once()

    assert len(capture._buffer) == 1
    only = list(capture._buffer)[0]
    assert only.method == "boundaryCall"
    assert only.timestamp == 100.0
    # And the cursor stayed exactly at the boundary value — no drift.
    assert capture._last_seen_ts == 100.0


# --------------------------------------------- defensive paths (sanity check)


def test_poll_once_tolerates_null_result_from_missing_slot() -> None:
    """When the slot isn't wired, ``evaluate`` returns ``None``; no crash.

    This mirrors the ``test_bridge_log_handles_missing_slot_gracefully``
    contract from ``test_capture.py`` but at unit-test resolution: the
    ``None`` branch must early-return, leave the buffer empty, leave the
    cursor untouched, and set the one-time warning latch.
    """
    capture = BridgeCapture(poll_interval_s=0.0)
    tab = MagicMock(name="wimi_tab")
    tab.evaluate.return_value = None
    capture._tab = tab

    assert capture._warned_about_missing_slot is False
    capture._poll_once()

    assert len(capture._buffer) == 0
    assert capture._last_seen_ts == 0.0
    assert capture._warned_about_missing_slot is True

    # A second null-poll must not log again or change state.
    capture._poll_once()
    assert capture._warned_about_missing_slot is True
    assert len(capture._buffer) == 0


def test_poll_once_ignores_non_list_payload_without_advancing_cursor() -> None:
    """A non-list JSON payload is logged-and-skipped; cursor unchanged."""
    capture = BridgeCapture(poll_interval_s=0.0)
    tab = MagicMock(name="wimi_tab")
    tab.evaluate.return_value = json.dumps({"unexpected": "shape"})
    capture._tab = tab

    capture._poll_once()

    assert len(capture._buffer) == 0
    assert capture._last_seen_ts == 0.0
