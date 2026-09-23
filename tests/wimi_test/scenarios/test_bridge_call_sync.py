"""The harness can observe a real bridge call, and knows when one never came.

Bug source: Forgejo issues #99 and #105 on the private tracker,
the fourth and fifth instances of the class umbrella'd as #86 — a
scenario sitting behind a fixed ``wait_for_timeout`` (or a bounded poll
with a fixed ceiling) while a bridge round trip completes, then blaming
the *result* when what actually went wrong was the *call*.

``WimiPage.wait_for_bridge_call`` replaces that guess: it reads WIMI's
own ``@instrumented_slot`` ring buffer through the
``getTestModeBridgeCalls`` slot and waits for the named call to be
recorded. ``tests/wimi_test/test_page_bridge_wait.py`` pins the cursor
arithmetic against a fake tab. This scenario pins the half a fake cannot
reach: that the buffer is genuinely readable from a *scenario's* CDP
world against a live WIMI.

That is not a formality. ``TEST_INFRASTRUCTURE.md`` §12a documents that
Qt's ``runJavaScript`` world and CDP's ``eval_js`` world are disjoint
with no error on either side, and the buffer being asserted on here
lives in Python, on the Qt side. It is reachable only because the probe
calls a QWebChannel slot proxy installed by the page's own scripts
rather than reading a Qt-written global — a distinction that is
invisible until something silently returns nothing.

So the scenario asserts both directions, and the negative one is the
load-bearing half: a helper that cannot be shown failing is
indistinguishable from one that matches anything.
"""

from __future__ import annotations

import time

import pytest

from wimi_test.errors import BridgeCallTimeout
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


# A slot name no bridge mixin defines, so nothing can satisfy a wait on
# it. Spelled obviously-fake so a future grep for a real slot never
# lands here.
_NEVER_CALLED_SLOT = "thisSlotDoesNotExistAnywhereInWimi"


@pytest.mark.slow
@pytest.mark.regression
def test_wait_for_bridge_call_observes_a_real_call_and_times_out_without_one(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """A dispatched slot is observed; an undispatched one fails, saying so."""
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db.create_exam_context(
        exam_name="Bridge Call Sync Probe",
        exam_description="Gives getAllExamContexts something to return",
    )
    wimi_page.goto("dashboard")

    # ---- Act / Assert: a call that does happen -----------------------
    # Mark *before* dispatching, which is the contract the helper's
    # docstring states: a cursor taken after the trigger can miss a call
    # that completed in the gap.
    mark = wimi_page.mark_bridge_calls()
    # ``eval_js`` deliberately does not await the promise — the point is
    # that the wait, not the evaluation, is what synchronizes.
    wimi_page.eval_js("window.api.getAllExamContexts(true); true")

    record = wimi_page.wait_for_bridge_call(
        "getAllExamContexts", since_ts=mark, timeout_ms=10000
    )

    assert record["method"] == "getAllExamContexts", (
        f"wait_for_bridge_call returned a record for {record['method']!r} "
        "when asked for 'getAllExamContexts'."
    )
    assert record["timestamp"] > mark, (
        "The matched call predates the cursor, so the wait is not "
        "filtering by since_ts — a stale buffer entry would satisfy it."
    )
    assert record["error"] is False, (
        f"getAllExamContexts raised on the WIMI side: {record['result_summary']!r}"
    )

    # ---- Act / Assert: a call that does not happen -------------------
    # The failure must arrive on time rather than hanging, and must name
    # the calls that *were* seen — that is what distinguishes "the click
    # did nothing" from "the write was slow", the misdiagnosis #99 and
    # #105 were both filed under.
    mark2 = wimi_page.mark_bridge_calls()
    wimi_page.eval_js("window.api.getAllExamContexts(true); true")

    started = time.time()
    with pytest.raises(BridgeCallTimeout) as excinfo:
        wimi_page.wait_for_bridge_call(
            _NEVER_CALLED_SLOT, since_ts=mark2, timeout_ms=1500
        )
    elapsed_ms = (time.time() - started) * 1000.0

    assert elapsed_ms < 8000, (
        f"The timeout path took {elapsed_ms:.0f} ms against a 1500 ms budget; "
        "a wait that overruns its ceiling is the problem it was meant to fix."
    )
    assert excinfo.value.method == _NEVER_CALLED_SLOT
    assert "getAllExamContexts" in excinfo.value.observed, (
        "The timeout did not report the call that did happen, so the "
        f"buffer read back empty: observed={excinfo.value.observed!r}. If "
        "this is the only failing assertion here, suspect the slot's "
        "reachability from the CDP world (TEST_INFRASTRUCTURE.md 12a) "
        "before suspecting the wait."
    )
    assert _NEVER_CALLED_SLOT in str(excinfo.value)
