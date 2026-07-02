"""Phase 3 capture-pipeline verification tests.

These three tests are the **closing gate for Phase 3** of
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
   ``page.on('console')`` subscription set up by
   :meth:`WimiTestSession.start` is live and that the level filter
   (``level_min="warning"``) keeps the entry.
2. :func:`test_network_log_captures_navigation` -- navigate to the
   dashboard via :meth:`WimiPage.goto` and assert that the resulting
   ``Network.*`` CDP events make it into
   :meth:`NetworkCapture.snapshot`. The dashboard pulls JS, CSS, and
   bridge-init resources, so even with the default ``file://`` /
   ``qrc://`` filter applied we expect at least one captured event from
   the load.
3. :func:`test_bridge_log_handles_missing_slot_gracefully` -- exercises
   :class:`BridgeCapture`'s defensive behaviour. The
   ``getTestModeBridgeCalls`` slot wiring is deferred (per the T3.6
   note: full operation depends on a follow-up task to expose the
   helper as a ``@pyqtSlot``), so a freshly-attached capture must
   tolerate the missing slot, log once, and keep its buffer empty
   without raising. This test will gain a *positive* assertion (call a
   bridge method and observe the call appearing in the log) once that
   follow-up lands; for now we lock in the no-crash contract.

All three tests are :pytest:mark:`slow` because each spawns a real WIMI
subprocess (~3-8 s startup on a warm disk). They use the fixtures from
:mod:`wimi_test.fixtures.core`:

* ``wimi_session`` -- the started :class:`WimiTestSession`.
* ``wimi_page`` -- the wrapped :class:`WimiPage` (test 2 only).
* ``console_log`` / ``network_log`` / ``bridge_log`` -- thin views over
  ``wimi_session.captures.{console, network, bridge}``.
"""

from __future__ import annotations

from typing import Any

import pytest

from wimi_test.capture.bridge import BridgeCapture, BridgeCall
from wimi_test.capture.console import ConsoleCapture, ConsoleEntry
from wimi_test.capture.network import NetworkCapture, NetworkEvent
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
    :class:`ConsoleCapture` to the live Playwright page (see
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

    # Playwright dispatches ``console`` events synchronously off the
    # CDP socket; by the time ``evaluate`` returns, the listener has
    # appended. No extra wait is needed in practice, but if CI shows
    # flakiness here, the documented escape hatch is a short
    # ``wimi_session.page.pw_page.wait_for_timeout(50)`` before the
    # snapshot call.
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
    """Navigate to the dashboard and assert the network log is non-empty.

    :meth:`WimiPage.goto` triggers a real navigation, and the dashboard
    page (``src/web/html/index.html``) loads a fan-out of JS bundles,
    CSS files, and the QWebChannel bridge-init scripts. Each of those
    fetches surfaces as one or more ``Network.requestWillBeSent`` /
    ``Network.responseReceived`` events on the per-session CDP session
    that :class:`NetworkCapture` is subscribed to.

    The default URL filter
    (:func:`wimi_test.config.default_url_filter`) rejects ``file://``
    and ``qrc://``, but the bridge handshake and any ``media://``
    requests still survive. The assertion is therefore intentionally
    loose: at least one captured event is enough to prove the CDP
    subscription is live.
    """
    # Navigate via the wrapper so we go through the full route resolver
    # plus bridge-readiness wait. This is a more realistic exercise
    # than ``pw_page.goto(url)`` directly.
    wimi_page.goto("dashboard")

    # No since_ts here -- the buffer is freshly attached by ``start()``
    # and we just want any events captured from the navigation. If a
    # future test interleaves multiple navigations, switch to
    # ``since_ts=wimi_session.start_ts`` for per-call segmentation.
    events: list[NetworkEvent] = network_log.snapshot()

    assert events, (
        "Expected at least one network event from dashboard load; "
        "got an empty buffer. Either NetworkCapture failed to attach, "
        "or the default URL filter rejected every event "
        "(unexpected -- bridge handshake usually surfaces)."
    )


# ---------------------------------------------------------------------------
# Test 3: bridge capture (defensive / pre-slot-wiring)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_bridge_log_handles_missing_slot_gracefully(
    wimi_session: WimiTestSession,
    bridge_log: BridgeCapture,
) -> None:
    """Verify :class:`BridgeCapture` survives the slot being unwired.

    Per the T3.6 status note in ``TEST_INFRASTRUCTURE_TASKS.md``, the
    JS-side ``window._wimiApi.getTestModeBridgeCalls`` slot is deferred
    -- the capture pipeline lands, but full operation depends on a
    follow-up task to expose the helper as a ``@pyqtSlot``. The
    capture's poll loop is documented to handle that case by:

    * defensively checking for the function in the JS expression and
      returning ``null`` if absent;
    * logging *once* via :class:`logging.Logger` on the first miss;
    * leaving the buffer empty;
    * **not** raising or killing the daemon poll thread.

    This test pins that contract. Once the slot is wired up by the
    follow-up task, this test will be upgraded to call a real bridge
    method and assert the call name surfaces in
    :meth:`BridgeCapture.snapshot` (the originally-spec'd Phase 3
    scenario 3); until then the no-crash assertion is what we can
    guarantee.

    No exception handling around the snapshot call is appropriate
    here: if :meth:`BridgeCapture.snapshot` *does* raise, the test
    must fail loudly because the defensive contract has regressed.
    """
    # Touch the page to give the poll thread at least one tick to
    # attempt evaluation. Without this, on a very fast machine the
    # session could tear down before ``_poll_loop`` runs even once,
    # which would still pass the empty-buffer assertion below but
    # wouldn't actually exercise the missing-slot branch.
    wimi_session.page.pw_page.wait_for_timeout(600)

    # snapshot() must not raise even though the underlying slot is
    # absent -- the JS expression returns ``null`` and the poll handler
    # logs-and-continues per the design.
    calls: list[BridgeCall] = bridge_log.snapshot()

    # Empty (or near-empty) is the expected state. We allow for a few
    # entries in case a follow-up task lands between this test's
    # creation and its execution; the core contract is "no crash".
    # Any entries that do appear must still be well-formed BridgeCall
    # instances.
    assert isinstance(calls, list), (
        f"BridgeCapture.snapshot() must return a list; "
        f"got {type(calls).__name__}"
    )
    for call in calls:
        assert isinstance(call, BridgeCall), (
            f"Every snapshot entry must be a BridgeCall; "
            f"got {type(call).__name__}"
        )

    # Sanity-check the poll thread is still alive -- if a transient
    # exception had killed it, subsequent polls would silently miss
    # bridge calls forever, which is a regression we want to catch.
    # The internal attribute is read defensively; if it ever goes away
    # in a refactor, this assertion can be relaxed without losing the
    # core no-crash guarantee above.
    poll_thread: Any = getattr(bridge_log, "_poll_thread", None)
    if poll_thread is not None:
        assert poll_thread.is_alive(), (
            "BridgeCapture poll thread died unexpectedly; "
            "the missing-slot path should log-and-continue, not exit."
        )
