"""Regression: the port probe refuses the debug port a live WIMI is holding (#217).

Every other test of `_port_is_bindable` uses a listener the test created. This
one uses **the listener that actually matters**: the CDP socket of a running
WIMI, opened by the child Chromium on the port `_pick_free_port` handed it.

Why that distinction is the whole point of this file
---------------------------------------------------

#217's severity turned on a question nobody could answer from a synthetic
listener. On Windows the rule is **mutual consent** -- a second `SO_REUSEADDR`
bind succeeds only when the *incumbent* also set `SO_REUSEADDR` -- measured on
Windows 10 Pro 19045:

    listener bare           listener SO_REUSEADDR
      REUSEADDR -> refused    REUSEADDR -> BOUND     <- the defect
      EXCLUSIVE -> refused    EXCLUSIVE -> refused

So whether the defect was ever reachable in production depended on whether
Chromium's CDP listener sets `SO_REUSEADDR`. `process.py`'s docstring asserted
it did -- *"the child Chromium, which sets SO_REUSEADDR itself"* -- and that
was documentation, never instrumented, and it is exactly the kind of claim that
turned out to be wrong about Windows in the first place.

**Answered, 2026-09-27: Chromium does NOT set it.** A `SO_REUSEADDR` probe over
a live WIMI CDP port on Windows is refused with errno 13 -- identical to what a
*bare* incumbent gives -- so on Windows #217 was **test-only**: the failing
tests manufactured a listener shape the harness never meets. The fix is still
right, because it makes the probe correct against both incumbent shapes rather
than correct by luck about a Chromium behaviour nothing pins. This test stays so
a change in that behaviour is caught by a test rather than by a confusing CDP
attach failure.

This test replaces the argument with an observation, and it does so on whatever
platform runs it. It cannot fail on Linux for the reason it would fail on
Windows, and that asymmetry is deliberate rather than a weakness:

* **On Linux** `SO_REUSEADDR` refuses a live listener regardless of the
  incumbent's options, so this passes whatever Chromium does. It is a
  regression guard: it is what fails if someone ever "simplifies" the probe
  back to a bare `bind()` or drops the platform branch.
* **On Windows** it is the measurement. With the fix in place
  `SO_EXCLUSIVEADDRUSE` refuses both incumbent shapes, so it passes; run it
  against the *old* probe and it fails if and only if Chromium sets
  `SO_REUSEADDR` -- which answers #217's open severity question by running,
  rather than by reading Chromium's source.

Marked `slow` and `regression` because it spawns a real WIMI. That is the cost
of testing the real listener, and there is no cheaper way to get one.
"""

from __future__ import annotations

import socket
import sys

import pytest

from wimi_test.process import WimiProcess
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_the_probe_refuses_the_port_a_live_wimi_is_using(
    wimi_session: WimiTestSession,
) -> None:
    port = wimi_session.process._picked_port
    assert port is not None, "the harness did not record a debug port"

    # The session is up and attached, so the CDP socket is listening right now.
    assert wimi_session.process.is_alive(), "WIMI is not running"

    assert not WimiProcess._port_is_bindable(port), (
        f"the probe reported port {port} as free while a live WIMI is serving "
        f"CDP on it. _pick_free_port would hand this port to another spawn, "
        f"and the failure would surface as a confusing CDP attach error "
        f"attributed to anything but port selection (#217)."
    )


@pytest.mark.slow
@pytest.mark.regression
def test_whether_chromiums_cdp_listener_sets_so_reuseaddr(
    wimi_session: WimiTestSession,
) -> None:
    """Records what the incumbent listener actually permits. Never fails.

    This is the instrument, not an assertion. `process.py` claimed Chromium
    sets `SO_REUSEADDR`; on Windows that claim is what decides whether #217 was
    production-reachable or test-only, and it had never been measured. An
    assertion either way would be asserting a property of Chromium that WIMI
    does not control and that differs by platform -- so this reports instead,
    and the report is the deliverable.

    Read the printed line, not a pass/fail. On Linux `BOUND` is impossible
    whatever Chromium does, so a Linux run says only "consistent with either";
    a Windows run is the one that answers it.
    """
    port = wimi_session.process._picked_port
    assert port is not None

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
        outcome = "BOUND"
    except OSError as exc:
        outcome = f"refused (errno {exc.errno} {exc.strerror})"
    finally:
        probe.close()

    if sys.platform == "win32":
        verdict = (
            "Chromium's CDP listener SET SO_REUSEADDR -> #217 was reachable "
            "in production"
            if outcome == "BOUND"
            else "Chromium's CDP listener did NOT set SO_REUSEADDR -> on "
                 "Windows #217 was test-only"
        )
    else:
        verdict = (
            "Linux refuses a live listener whatever the incumbent set, so "
            "this is consistent with either answer; run on Windows to decide"
        )

    print(
        f"\n[#217] SO_REUSEADDR bind over a live WIMI CDP port "
        f"({sys.platform}, port {port}): {outcome}\n"
        f"[#217] {verdict}"
    )
