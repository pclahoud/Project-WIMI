"""Unit tests for ``WimiPage.wait_for_bridge_call`` and its cursor helpers.

No WIMI subprocess, no CDP, no Qt: the
:class:`~wimi_test._internal.cdp_client.WimiTab` dependency is replaced
by :class:`_FakeBridgeTab`, which reimplements the *producer* contract
from ``src/app/bridge_test_instrumentation.get_test_mode_bridge_calls``
— parse the ``since_ts`` inlined into the polling expression, return
every buffered entry whose ``timestamp`` is **strictly** greater, as a
JSON string. Faking at that seam rather than at ``get_bridge_calls``
means the cursor arithmetic under test is the real thing.

The point of this file is the negative cases. A synchronization helper
that can only be observed succeeding is indistinguishable from one that
matches anything, so the tests that matter here are:

* :func:`test_timeout_when_call_never_happens` — the wait *fails*, on
  time, when the awaited slot is never recorded.
* :func:`test_timeout_message_lists_what_did_happen` — and the failure
  says which calls *were* seen, which is what separates "the action
  never fired" from "the action fired and was slow".
* :func:`test_call_before_the_cursor_is_not_matched` — a call recorded
  before the mark does not satisfy a wait armed after it, so a stale
  buffer entry can never make the wait pass vacuously.
* :func:`test_missing_slot_raises_unavailable_not_timeout` — an
  uninstrumented WIMI is reported as uninstrumented rather than as "your
  call never happened", the failure mode that would otherwise make this
  helper worse than the sleep it replaces.
"""

from __future__ import annotations

import json
import re
import time

import pytest

from wimi_test.config import TestConfig
from wimi_test.errors import (
    BridgeCallsUnavailable,
    BridgeCallTimeout,
    WimiTestError,
)
from wimi_test.page import WimiPage

# ---------------------------------------------------------------------- helpers

_SINCE_RE = re.compile(r"getTestModeBridgeCalls\(([-0-9.eE+]+)\)")


def _entry(
    *,
    timestamp: float,
    method: str,
    args_summary: str = "()",
    result_summary: str = "'{}'",
    duration_ms: float = 1.0,
    error: bool = False,
) -> dict:
    """One buffer entry in the exact shape ``BridgeCall._asdict()`` emits."""
    return {
        "timestamp": timestamp,
        "method": method,
        "args_summary": args_summary,
        "result_summary": result_summary,
        "duration_ms": duration_ms,
        "error": error,
    }


class _FakeBridgeTab:
    """Stand-in for :class:`WimiTab` that mimics the WIMI-side slot.

    ``entries`` is the ring buffer; append to it between polls to
    simulate a call landing mid-wait. ``available=False`` simulates a
    WIMI with no instrumentation, where the JS probe's guard falls
    through and the expression evaluates to ``None``.
    """

    def __init__(self, entries: list[dict] | None = None, *, available: bool = True):
        self.entries: list[dict] = list(entries or [])
        self.available: bool = available
        self.polls: list[float] = []
        # Optional hook fired before each poll returns, so a test can
        # mutate the buffer as a function of how many polls have run.
        self.on_poll = None
        # When set, returned verbatim instead of the JSON list — used to
        # exercise the malformed-payload guard.
        self.raw_override: object | None = None

    def evaluate(self, expression: str, *, await_promise: bool = False) -> object:
        assert await_promise, "the bridge-call probe must await its Promise"
        match = _SINCE_RE.search(expression)
        assert match, f"expression did not carry a since_ts cursor: {expression}"
        since_ts = float(match.group(1))
        self.polls.append(since_ts)
        if self.on_poll is not None:
            self.on_poll(self)
        if not self.available:
            return None
        if self.raw_override is not None:
            return self.raw_override
        selected = [e for e in self.entries if e["timestamp"] > since_ts]
        return json.dumps(selected)


def _page(tab: _FakeBridgeTab) -> WimiPage:
    return WimiPage(tab, app_root=".", config=TestConfig.resolve())  # type: ignore[arg-type]


# ---------------------------------------------------------------------- tests


def test_matches_a_call_that_lands_mid_wait() -> None:
    """The happy path: the wait returns the record once the call lands."""
    tab = _FakeBridgeTab()
    mark = time.time()

    def land_on_third_poll(t: _FakeBridgeTab) -> None:
        if len(t.polls) == 3:
            t.entries.append(_entry(timestamp=time.time(), method="createQuestionEntry"))

    tab.on_poll = land_on_third_poll

    record = _page(tab).wait_for_bridge_call(
        "createQuestionEntry", timeout_ms=2000, since_ts=mark, poll_interval_ms=5
    )

    assert record["method"] == "createQuestionEntry"
    assert record["error"] is False
    assert len(tab.polls) >= 3


def test_timeout_when_call_never_happens() -> None:
    """The wait must *fail*, within its budget, when the call never fires.

    This is the test that keeps the helper honest: without it, a
    predicate that silently matched nothing would look identical to one
    that works.
    """
    tab = _FakeBridgeTab()
    started = time.time()

    with pytest.raises(BridgeCallTimeout) as excinfo:
        _page(tab).wait_for_bridge_call(
            "createQuestionEntry",
            timeout_ms=300,
            since_ts=time.time(),
            poll_interval_ms=10,
        )

    elapsed_ms = (time.time() - started) * 1000.0
    assert 250 <= elapsed_ms < 3000, f"timeout budget not respected: {elapsed_ms:.0f} ms"
    assert excinfo.value.method == "createQuestionEntry"
    assert excinfo.value.timeout_ms == 300
    assert excinfo.value.observed == []
    assert "No bridge calls at all were recorded" in str(excinfo.value)


def test_timeout_message_lists_what_did_happen() -> None:
    """A busy page's other calls are named in the failure.

    "These calls happened and yours was not among them" is the whole
    diagnostic value over a fixed sleep — it says the page was alive and
    the *action* was the thing that did not run.
    """
    tab = _FakeBridgeTab()
    mark = time.time()
    tab.entries.extend(
        [
            _entry(timestamp=mark + 0.01, method="getReviewSession"),
            _entry(timestamp=mark + 0.02, method="getTagHierarchy"),
            _entry(timestamp=mark + 0.03, method="getTagHierarchy"),
        ]
    )

    with pytest.raises(BridgeCallTimeout) as excinfo:
        _page(tab).wait_for_bridge_call(
            "createQuestionEntry", timeout_ms=200, since_ts=mark, poll_interval_ms=10
        )

    message = str(excinfo.value)
    assert "getReviewSession" in message
    assert "getTagHierarchy" in message
    assert "createQuestionEntry" in message
    # Repeats are collapsed in the rendered list but all observations
    # are retained on the exception for a caller that wants counts.
    assert message.count("getTagHierarchy") == 1
    assert excinfo.value.observed.count("getTagHierarchy") == 2


def test_call_before_the_cursor_is_not_matched() -> None:
    """A stale buffer entry cannot satisfy a wait armed after it.

    The entry-form page calls ``createQuestionEntry`` on autosave as
    well as on the Save button, so "there is one in the buffer" is not
    the same question as "the click I just made produced one".
    """
    mark = time.time()
    tab = _FakeBridgeTab([_entry(timestamp=mark - 5.0, method="createQuestionEntry")])

    with pytest.raises(BridgeCallTimeout):
        _page(tab).wait_for_bridge_call(
            "createQuestionEntry", timeout_ms=150, since_ts=mark, poll_interval_ms=10
        )


def test_missing_slot_raises_unavailable_not_timeout() -> None:
    """An uninstrumented WIMI is reported as such, immediately.

    Reporting it as a timeout would blame the code under test for the
    harness's own blindness, and would burn the full budget doing it.
    """
    tab = _FakeBridgeTab(available=False)
    started = time.time()

    with pytest.raises(BridgeCallsUnavailable) as excinfo:
        _page(tab).wait_for_bridge_call(
            "createQuestionEntry", timeout_ms=5000, since_ts=time.time()
        )

    assert (time.time() - started) < 2.0, "should fail fast, not wait out the budget"
    assert "--test-mode" in str(excinfo.value)
    # A BridgeCallTimeout would be the wrong diagnosis, so make sure the
    # two types stay distinguishable by a caller that catches either.
    assert not isinstance(excinfo.value, BridgeCallTimeout)


def test_errored_slot_call_still_counts_as_having_happened() -> None:
    """``error: True`` matches — the call happened, it just failed.

    The helper's job is synchronization, not success assertion; a test
    that wants the outcome reads ``result_summary`` off the record.
    """
    mark = time.time()
    tab = _FakeBridgeTab(
        [
            _entry(
                timestamp=mark + 0.01,
                method="createQuestionEntry",
                result_summary="DatabaseIntegrityError: NOT NULL constraint",
                error=True,
            )
        ]
    )

    record = _page(tab).wait_for_bridge_call(
        "createQuestionEntry", timeout_ms=500, since_ts=mark, poll_interval_ms=5
    )

    assert record["error"] is True
    assert "NOT NULL" in record["result_summary"]


def test_non_json_payload_is_reported_not_swallowed() -> None:
    """A garbled slot response fails loudly rather than polling forever."""
    tab = _FakeBridgeTab()
    tab.raw_override = "<html>not json</html>"

    with pytest.raises(WimiTestError) as excinfo:
        _page(tab).get_bridge_calls()

    assert "non-JSON" in str(excinfo.value)


def test_cursor_advances_so_polls_do_not_refetch() -> None:
    """Each poll asks only for what it has not already seen.

    The producer filters ``timestamp > since_ts``; the wait advances its
    cursor to the newest entry it consumed. Without that, a long wait on
    a chatty page re-downloads the whole window every 50 ms.
    """
    mark = time.time()
    tab = _FakeBridgeTab([_entry(timestamp=mark + 0.01, method="getEntries")])

    with pytest.raises(BridgeCallTimeout):
        _page(tab).wait_for_bridge_call(
            "createQuestionEntry", timeout_ms=200, since_ts=mark, poll_interval_ms=10
        )

    assert tab.polls[0] == pytest.approx(mark)
    assert tab.polls[-1] == pytest.approx(mark + 0.01)
    # Consumed once, not once per poll.
    assert tab.polls.count(mark) == 1


def test_mark_bridge_calls_is_a_usable_cursor() -> None:
    """The mark is comparable with the timestamps WIMI stamps.

    Both sides call :func:`time.time` on the same host; this pins that
    assumption so a future change of clock source fails here rather than
    as an unexplained flake in a scenario.
    """
    page = _page(_FakeBridgeTab())
    before = time.time()
    mark = page.mark_bridge_calls()
    after = time.time()

    assert before <= mark <= after
