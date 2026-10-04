"""The three capture streams flow from a real WIMI subprocess.

These tests are the closing gate for Phase 3 of
``docs/planning/TEST_INFRASTRUCTURE.md`` -- specifically Section 6 (the
three capture streams: console, network, and bridge). After T3.1 - T3.9
landed the Layer-2 captures, the bundle, the session wiring, and the
autouse failure-report hook, this file proves end-to-end that each
stream actually flows from a real WIMI subprocess back into the test
driver's deques.

The three scenarios mirror the three streams:

1. :func:`test_console_log_captures_messages` -- inject a JS
   ``console.warn`` via :meth:`WimiPage.eval_js` and assert the message
   surfaces in :meth:`ConsoleCapture.snapshot`. Proves the
   ``Runtime.consoleAPICalled`` subscription set up by
   :meth:`WimiTestSession.start` is live and that the level filter
   (``level_min="warning"``) keeps the entry.
2. :func:`test_network_log_captures_navigation` -- navigate to the
   dashboard and assert the ``Network.*`` CDP events reach
   :meth:`NetworkCapture.snapshot`. It attaches its **own** unfiltered
   capture to do so, because the session's capture applies
   :func:`~wimi_test.config.default_url_filter` and a local WIMI page
   emits nothing that survives it -- see that test's docstring.
3. :func:`test_bridge_log_captures_a_real_call_and_survives_the_slot_vanishing`
   -- assert a dispatched ``@pyqtSlot`` reaches
   :meth:`BridgeCapture.snapshot`, then delete the slot out from under
   the poll thread and assert it logs-and-continues rather than dying.

All three tests are :pytest:mark:`slow` because each spawns a real WIMI
subprocess (~3-8 s startup on a warm disk). They use the fixtures from
:mod:`wimi_test.fixtures.core`:

* ``wimi_session`` -- the started :class:`WimiTestSession`.
* ``wimi_page`` -- the wrapped :class:`WimiPage` (tests 2 and 3).
* ``console_log`` / ``network_log`` / ``bridge_log`` -- thin views over
  ``wimi_session.captures.{console, network, bridge}``.

History (#152, #257)
--------------------
Tests 2 and 3 were both **permanently red on Linux, macOS and Windows**,
and were filed as one bug under #152 because the issue quoted a single
traceback for both. They were two unrelated defects, and neither was in
the code under test:

* Test 3 reached for ``wimi_session.page.pw_page``, the Playwright
  handle renamed to :attr:`WimiPage.tab` by the pychrome migration
  (``PYCHROME_MIGRATION.md`` Section 6). That rename was recorded as
  safe because nothing in ``tests/wimi_test/scenarios/*`` reached into
  it -- which was true, and this file is not in that directory.
* Test 2 asserted that "the bridge handshake and any ``media://``
  requests still survive" the default URL filter. **Neither can.**
  QWebChannel bridge calls never appear in CDP ``Network`` events (the
  transport bypasses the network stack -- ``capture/network.py`` says so
  in its own module docstring), and ``wimi-media://`` was deleted as
  dead code in #140. So the test asserted a non-empty buffer that the
  architecture cannot fill, and read as "``get_network_log`` is broken"
  for as long as it was red.

Test 3's stated premise was stale too: it pinned a *defensive* contract
("the ``getTestModeBridgeCalls`` slot wiring is deferred, so tolerate
its absence") and promised to "gain a positive assertion once that
follow-up lands". The follow-up landed -- the slot is live in
``src/app/bridge_domains/utility.py`` and exposed by
``src/web/js/api/utility.js`` -- so the test had stopped exercising the
branch it named and would have passed trivially. The missing-slot branch
keeps its unit test against a fake tab
(``test_bridge_capture.py::test_poll_once_tolerates_null_result_from_missing_slot``);
what had no test anywhere was the stream's *positive* path against a
live WIMI, which is what the whole capture exists for.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from wimi_test.capture.bridge import BridgeCapture, BridgeCall
from wimi_test.capture.console import ConsoleCapture, ConsoleEntry
from wimi_test.capture.network import NetworkCapture, NetworkEvent
from wimi_test.config import default_url_filter
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


# ---------------------------------------------------------------------------
# Test 1: console capture
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_console_log_captures_messages(
    wimi_session: WimiTestSession,
    console_log: ConsoleCapture,
) -> None:
    """Inject a ``console.warn`` and assert it appears in the snapshot.

    The ``wimi_session`` fixture has already attached
    :class:`ConsoleCapture` to the live tab (see
    :meth:`WimiTestSession.start` step 6). ``console_log`` is the same
    capture instance, exposed as a fixture for ergonomic access.

    We use :meth:`WimiPage.eval_js` rather than driving any real UI
    code because the test is about the *capture pipeline*, not about
    any particular page. ``console.warn`` is chosen because the default
    ``level_min="warning"`` filter on :meth:`ConsoleCapture.snapshot`
    keeps warning-and-above entries -- using ``console.log`` here would
    require a stricter ``level_min`` argument to surface and would
    also conflate the level-filter contract with the capture contract.
    """
    # Sentinel string is unique enough that we can't accidentally
    # match a stray console.warn from app startup.
    sentinel = "hi from capture test"

    wimi_session.page.eval_js(f"console.warn({sentinel!r})")

    # CDP dispatches ``Runtime.consoleAPICalled`` off the same socket
    # the evaluate went out on, so by the time ``eval_js`` returns the
    # listener has appended. No extra wait is needed in practice, but if
    # CI shows flakiness here the escape hatch is a short
    # ``wimi_session.page.wait_for_timeout(50)`` before the snapshot.
    entries: list[ConsoleEntry] = console_log.snapshot(level_min="warning")

    matches = [e for e in entries if sentinel in e.text]
    assert matches, (
        f"Expected at least one console entry containing {sentinel!r}; "
        f"snapshot held {len(entries)} entry/entries with levels "
        f"{[e.level for e in entries]!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: network capture
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_network_log_captures_navigation(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
    network_log: NetworkCapture,
) -> None:
    """A navigation reaches CDP, and nothing in it reaches the network.

    Two facts, one measurement, because they are the same story: the
    reason ``session.captures.network`` is empty after a page load is
    the URL filter doing its job, not a subscription that failed to
    attach.

    Measured on this navigation (Linux, 2026-09-28): **80 events** --
    40 ``requestWillBeSent`` plus 40 ``responseReceived`` -- of which
    **78 are ``file://`` and 2 are ``qrc://``**, so **zero** survive
    :func:`~wimi_test.config.default_url_filter`. The session's capture
    is constructed with that filter
    (``session.py`` step 6, from :attr:`TestConfig.network_url_filter`),
    and the filter runs **on ingest** rather than in
    :meth:`NetworkCapture.snapshot`, so a rejected event is not
    recoverable later by snapshotting differently. Hence this test
    attaches its own unfiltered capture instead of reading
    ``network_log``.

    The second assertion is the valuable one and it is not a
    limitation: **a dashboard load must make no remote request.** Every
    frontend dependency is vendored in-repo (D3, Fuse.js, TinyMCE,
    KaTeX -- see CLAUDE.md *Dependencies*), media reaches the page as
    base64 data URLs rather than over a scheme (#140), and bridge
    traffic is QWebChannel, not HTTP. So any URL surviving the filter
    means WIMI started fetching something off-machine, which for a
    local-first tool is worth a red test.

    What this test does **not** assert, and why the version it replaces
    was unfixable: the old docstring claimed "the bridge handshake and
    any ``media://`` requests still survive" the filter. Bridge calls
    never appear in CDP Network events at all, and ``wimi-media://`` was
    deleted in #140 -- see this module's docstring.
    """
    tab = wimi_session.page.tab

    # ``WimiTab.set_listener`` is a pass-through to pychrome, which keys
    # handlers by event name and so **overwrites** rather than chains
    # (``capture/network.py``, "Detach limitations"). Attaching a second
    # capture therefore silently unsubscribes the session's one, so
    # detach it explicitly first -- an intentional handover reads as one,
    # a race does not -- and restore it afterwards so the failure-report
    # hook still has the stream it expects.
    network_log.detach()
    probe = NetworkCapture(url_filter=None)
    probe.attach(tab)
    try:
        # Navigate via the wrapper so we go through the full route
        # resolver plus bridge-readiness wait.
        wimi_page.goto("dashboard")
        events: list[NetworkEvent] = probe.snapshot()
    finally:
        probe.detach()
        network_log.attach(tab)

    assert events, (
        "Expected CDP Network events from a dashboard load; got an empty "
        "buffer with the URL filter disabled, so the subscription itself "
        "did not attach. Check Network.enable() and the set_listener "
        "registrations in NetworkCapture.attach()."
    )

    # ``e.url`` is skipped when empty rather than passed to the filter:
    # ``loadingFailed`` payloads often omit the URL (the ``requestId``
    # already correlates back to the request), the capture buffers them
    # unconditionally, and ``default_url_filter("")`` is ``True`` -- so a
    # single failed request would otherwise be reported here as a remote
    # fetch to the empty string.
    remote = sorted({e.url for e in events if e.url and default_url_filter(e.url)})
    assert not remote, (
        "A dashboard load made a request that is not file:// or qrc://, "
        "i.e. WIMI reached off-machine during a plain page load. Every "
        f"frontend dependency is vendored in-repo, so this is news: {remote}"
    )


# ---------------------------------------------------------------------------
# Test 3: bridge capture
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_bridge_log_captures_a_real_call_and_survives_the_slot_vanishing(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
    bridge_log: BridgeCapture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A dispatched slot reaches the buffer; losing the slot does not kill it.

    Both halves against a live WIMI, because the fake-tab unit tests in
    ``test_bridge_capture.py`` already pin the cursor arithmetic and the
    ``None``-tolerance branch, and what they cannot reach is whether the
    poll thread can read WIMI's real ring buffer at all.

    That is not a formality. :class:`BridgeCapture` is a *second,
    independent* consumer of ``getTestModeBridgeCalls`` -- it runs on a
    daemon thread with its own cursor, deliberately not sharing
    :meth:`WimiPage.wait_for_bridge_call`'s JS
    (``capture/bridge.py`` says so, and ``test_bridge_call_sync.py``
    covers only that other consumer). So the stream behind
    ``get_bridge_log`` and behind every failure report's bridge section
    had no end-to-end test until this one.

    Measured (Linux, 2026-09-28): a dashboard load yields **29 calls
    across 14 distinct slots** -- ``getUserPreferences``,
    ``getAnalyticsOverview``, ``loadTestUserDatabase``, ... -- with the
    first visible **~200 ms** after navigation, well inside the 0.5 s
    default poll interval.

    The second half deletes ``window.api.getTestModeBridgeCalls`` from
    the page. That genuinely reproduces the missing-slot condition the
    previous version of this test only *claimed* to cover: it was
    written while the slot was unwired, promised to become a positive
    test "once that follow-up lands", and the follow-up landed -- so it
    had been asserting nothing for as long as it was named for a branch
    it could no longer enter. The delete is safe to leave in place: the
    test performs no further navigation, and nothing after it reads the
    slot.

    It asserts the warning fires **exactly once** rather than only that
    the thread survived, because thread-survival alone is nearly
    untestable here: :meth:`BridgeCapture._poll_loop` wraps every
    ``_poll_once`` in ``except Exception``, so a regression *inside*
    ``_poll_once`` leaves the thread alive and the buffer empty either
    way -- indistinguishable from correct behaviour on both of the
    signals the old test read.

    The once-only latch is what separates them, and the measured case is
    not the obvious one. Deleting the ``if result is None`` guard does
    **not** raise: ``None`` falls through to the payload-type check
    below it, which logs *"returned unexpected payload type 'NoneType'"*
    -- naming the slot, and **unlatched**, so it fires on every tick.
    Verified: that mutation yields 3 warnings across ~3 polls instead of
    1. A mutation that also removes the loop's catch-all does kill the
    thread, which the ``is_alive`` assertion below catches. Two
    different regressions, two different assertions, both verified to
    fail this test.
    """
    # ---- A dispatched slot reaches the buffer -------------------------
    wimi_page.goto("dashboard")

    # Poll rather than sleeping a fixed span: the capture's own loop
    # ticks every ``poll_interval_s`` (0.5 s) and the dashboard's bridge
    # fan-out is not instantaneous, so a single fixed wait is either
    # flaky or slow. Ceiling is generous because a cold page load on a
    # loaded CI box is the slow case.
    deadline = time.time() + 15.0
    calls: list[BridgeCall] = []
    while time.time() < deadline:
        calls = bridge_log.snapshot()
        if calls:
            break
        wimi_page.wait_for_timeout(200)

    assert calls, (
        "BridgeCapture recorded no slot call 15 s after a dashboard load, "
        "which fires getUserPreferences, getAnalyticsOverview and a dozen "
        "others. Either the poll thread is not running, or "
        "window.api.getTestModeBridgeCalls is unreachable from the CDP "
        "world (TEST_INFRASTRUCTURE.md 12a)."
    )
    for call in calls:
        assert isinstance(call, BridgeCall), (
            f"Every snapshot entry must be a BridgeCall; "
            f"got {type(call).__name__}"
        )

    # ---- Losing the slot logs once and keeps the thread alive ---------
    # The once-only latch may already be spent: the poll thread starts
    # half a second after ``attach``, which can beat ``window.api`` onto
    # the page, and that first miss is indistinguishable from the one
    # being provoked here. Reset it so the count below means what it
    # says rather than depending on startup timing.
    bridge_log._warned_about_missing_slot = False
    caplog.clear()

    # Same JS world as the capture's own poll: both go through CDP
    # ``Runtime.evaluate`` on this tab. (The disjoint-worlds hazard in
    # TEST_INFRASTRUCTURE.md 12a is about Qt's ``runJavaScript``, which
    # is the other side of the bridge and not in play here.)
    with caplog.at_level(logging.WARNING, logger="wimi_test.capture.bridge"):
        wimi_page.eval_js("delete window.api.getTestModeBridgeCalls")
        assert wimi_page.eval_js(
            "typeof window.api.getTestModeBridgeCalls"
        ) == "undefined", (
            "the slot is still present, so the tolerance path is not being tested"
        )

        # Two poll intervals, so the loop is guaranteed to have taken the
        # missing-slot branch more than once -- which is the point: the
        # latch must still hold the warning count at one.
        wimi_page.wait_for_timeout(1500)

    misses = [
        r for r in caplog.records if "getTestModeBridgeCalls" in r.getMessage()
    ]
    assert len(misses) == 1, (
        f"Expected exactly one missing-slot warning across ~3 polls (the "
        f"once-only latch in BridgeCapture); got {len(misses)}. More than "
        f"one means either the latch stopped latching, or the ``result is "
        f"None`` guard is gone and the unlatched payload-type warning "
        f"downstream is firing every tick instead. Zero means the poll is "
        f"raising before it gets there, into _poll_loop's catch-all. "
        f"Records seen: {[r.getMessage() for r in caplog.records]}"
    )

    after: list[BridgeCall] = bridge_log.snapshot()
    assert isinstance(after, list), (
        f"BridgeCapture.snapshot() must return a list even with the slot "
        f"gone; got {type(after).__name__}"
    )

    # The contract is log-and-continue, not exit: a poll thread killed by
    # a transient exception would silently miss every later bridge call.
    poll_thread: Any = getattr(bridge_log, "_poll_thread", None)
    assert poll_thread is not None, (
        "BridgeCapture._poll_thread is gone; the missing-slot path must "
        "not tear the capture down"
    )
    assert poll_thread.is_alive(), (
        "BridgeCapture poll thread died after the slot was removed; "
        "the missing-slot path should log-and-continue, not exit."
    )
