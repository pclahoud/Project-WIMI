"""Unit tests for ``WimiProcess._pick_free_port`` (Forgejo issue #80).

The harness used to probe candidate CDP ports with a bare ``bind()``::

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        continue

A bare ``bind()`` fails on a port whose previous connection is still in
``TIME_WAIT`` (~60s on Linux) even though nothing is listening there and
the child Chromium -- which sets ``SO_REUSEADDR`` itself -- would bind it
without complaint. Each scenario spawns a WIMI, attaches over CDP and
kills it within a few seconds, so a narrow ``WIMI_TEST_DEBUG_PORT_RANGE``
was consumed far faster than TIME_WAIT drained. The range then reported
itself permanently full: ``ss -ltnp`` showed no listener, yet every
remaining scenario errored at setup with ``ProcessSpawnError``.

These tests do not spawn WIMI. They exercise the port picker directly
against real loopback sockets, so they stay in the fast bucket.
"""

from __future__ import annotations

import inspect
import socket
import sys
from typing import Iterator

import pytest

from wimi_test import process as process_module
from wimi_test.config import TestConfig as HarnessConfig
from wimi_test.errors import ProcessSpawnError
from wimi_test.process import WimiProcess


def _reserve_port() -> int:
    """Ask the OS for a currently-free loopback port and release it.

    Using an OS-assigned port keeps these tests off the 12000-12100 band
    that real sessions (and concurrent agents) use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _make_process(lo: int, hi: int) -> WimiProcess:
    return WimiProcess(HarnessConfig(cdp_port_range=(lo, hi)))


@pytest.fixture
def port_in_time_wait() -> Iterator[int]:
    """Yield a loopback port left holding a ``TIME_WAIT`` connection.

    Reproduces what a finished CDP session leaves behind: the *server*
    closes the accepted connection first, so the TIME_WAIT is anchored on
    the server's port -- the one the next spawn wants to reuse.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    listener.listen(1)

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    accepted, _ = listener.accept()

    # Server side closes first -> the (port, client_port) pair enters
    # TIME_WAIT anchored on `port`.
    accepted.close()
    client.close()
    listener.close()

    yield port


@pytest.mark.unit
def test_probe_accepts_port_in_time_wait(port_in_time_wait: int) -> None:
    """The #80 regression: TIME_WAIT must not disqualify a port.

    A bare ``bind()`` is asserted to fail on the same port first, so this
    test fails loudly if the OS ever stops producing the condition rather
    than passing vacuously.
    """
    # The precondition is Linux's behaviour and is NOT Windows' (#217).
    # Measured on Windows 10 Pro 19045: a bare bind to a TIME_WAIT port
    # SUCCEEDS there, so this `pytest.raises` was the whole of that machine's
    # "DID NOT RAISE" failure -- the OS never produces the condition the test
    # is guarding against. The behaviour it protects (#80) is not reachable
    # there for the same reason, so the assertion below is what still matters
    # and the precondition is skipped rather than inverted: there is no
    # Windows equivalent statement to make.
    if sys.platform != "win32":
        bare = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError):
                bare.bind(("127.0.0.1", port_in_time_wait))
        finally:
            bare.close()

    assert WimiProcess._port_is_bindable(port_in_time_wait), (
        "A port in TIME_WAIT with no listener must be considered usable - "
        "the child Chromium binds it fine. This is Forgejo issue #80."
    )
    # This message used to say "the child Chromium sets SO_REUSEADDR and binds
    # it fine". Measured on Windows (#217): it does NOT set SO_REUSEADDR -- a
    # SO_REUSEADDR probe over a live CDP port is refused with errno 13, the
    # same result a bare incumbent gives. The reason a TIME_WAIT port is usable
    # is not that Chromium opted into anything; it is that nothing is listening
    # on it. The claim was load-bearing in the wrong direction, because it is
    # what made #217 look production-reachable.


@pytest.mark.unit
@pytest.mark.parametrize("incumbent_reuseaddr", [True, False],
                         ids=["listener-SO_REUSEADDR", "listener-bare"])
def test_probe_rejects_live_listener(incumbent_reuseaddr: bool) -> None:
    """A live listener wins, whichever option the INCUMBENT set (#217).

    The option on the listener is the variable, and it is the one nobody
    controlled. This test originally set `SO_REUSEADDR` on its listener and
    nothing else, and it failed on Windows for a reason that took a 2x2 to
    see: there the rule is **mutual consent**, so a second `SO_REUSEADDR`
    bind succeeds only when the incumbent also set `SO_REUSEADDR`. Measured
    on Windows 10 Pro 19045:

        listener bare           listener SO_REUSEADDR
          REUSEADDR -> refused    REUSEADDR -> BOUND    <- the defect
          EXCLUSIVE -> refused    EXCLUSIVE -> refused

    Parametrised over both, because a probe written against a bare listener
    passes on Windows while the defect is live -- an independent probe did
    exactly that and appeared to refute the whole issue. One case is a
    control for the other.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if incumbent_reuseaddr:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    listener.listen(1)
    try:
        assert not WimiProcess._port_is_bindable(port), (
            f"a live listener bound with "
            f"{'SO_REUSEADDR' if incumbent_reuseaddr else 'no option'} was "
            f"reported as a free port"
        )
    finally:
        listener.close()


@pytest.mark.unit
def test_the_probe_uses_the_option_its_platform_needs() -> None:
    """The platform split is asserted, not left to a comment (#217).

    #217's own conclusion: *"whatever lands should make the platform split
    explicit in the code, not implicit in a docstring"*. The previous shape
    was a correct sentence about Linux above a branchless function that also
    ran on Windows, so this checks the branch exists and points the right way
    on whichever platform is running it.
    """
    source = inspect.getsource(WimiProcess._port_is_bindable)

    assert 'sys.platform == "win32"' in source, (
        "the platform branch is gone; SO_REUSEADDR alone is wrong on Windows"
    )
    assert "SO_EXCLUSIVEADDRUSE" in source
    assert "SO_REUSEADDR" in source, "Linux still needs it for #80"

    if sys.platform == "win32":
        assert hasattr(socket, "SO_EXCLUSIVEADDRUSE"), (
            "win32 branch names an option this interpreter does not have"
        )
    else:
        assert not hasattr(socket, "SO_EXCLUSIVEADDRUSE"), (
            "SO_EXCLUSIVEADDRUSE exists off win32; the branch may be wrong"
        )


@pytest.mark.unit
@pytest.mark.parametrize("incumbent_reuseaddr", [True, False],
                         ids=["listener-SO_REUSEADDR", "listener-bare"])
def test_pick_free_port_skips_a_listener_and_returns_the_next(
        incumbent_reuseaddr: bool) -> None:
    """The defect one level up: the picker hands out the occupied port.

    Parametrised for the same reason as the probe test -- on Windows only the
    `SO_REUSEADDR` incumbent reproduced it, and that is the case that reaches
    `--debug-port`.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if incumbent_reuseaddr:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    busy = int(listener.getsockname()[1])
    listener.listen(1)
    try:
        picked = _make_process(busy, busy + 2)._pick_free_port()
        assert picked != busy
        assert busy < picked <= busy + 2
    finally:
        listener.close()


@pytest.mark.unit
def test_pick_free_port_retries_before_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exhausted scan retries instead of failing the rest of the session."""
    monkeypatch.setattr(process_module, "_PORT_SCAN_TIMEOUT_S", 5.0)
    monkeypatch.setattr(process_module, "_PORT_SCAN_RETRY_INTERVAL_S", 0.01)

    port = _reserve_port()
    calls = {"n": 0}

    def flaky(candidate: int) -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    monkeypatch.setattr(WimiProcess, "_port_is_bindable", staticmethod(flaky))

    assert _make_process(port, port)._pick_free_port() == port
    assert calls["n"] == 4, "expected three failed scans then a success"


@pytest.mark.unit
def test_pick_free_port_raises_when_range_stays_occupied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process_module, "_PORT_SCAN_TIMEOUT_S", 0.05)
    monkeypatch.setattr(process_module, "_PORT_SCAN_RETRY_INTERVAL_S", 0.01)
    monkeypatch.setattr(
        WimiProcess, "_port_is_bindable", staticmethod(lambda candidate: False)
    )

    port = _reserve_port()
    with pytest.raises(ProcessSpawnError) as excinfo:
        _make_process(port, port)._pick_free_port()

    # The message must still name the range so a narrow-range failure is
    # diagnosable from the pytest output alone.
    assert "No free port in CDP range" in str(excinfo.value)
    assert str(port) in str(excinfo.value)
