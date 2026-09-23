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

import socket
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
    bare = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            bare.bind(("127.0.0.1", port_in_time_wait))
    finally:
        bare.close()

    assert WimiProcess._port_is_bindable(port_in_time_wait), (
        "A port in TIME_WAIT with no listener must be considered usable - "
        "the child Chromium sets SO_REUSEADDR and binds it fine. This is "
        "Forgejo issue #80."
    )


@pytest.mark.unit
def test_probe_rejects_live_listener() -> None:
    """SO_REUSEADDR must not weaken the check: a live listener still wins."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    listener.listen(1)
    try:
        assert not WimiProcess._port_is_bindable(port)
    finally:
        listener.close()


@pytest.mark.unit
def test_pick_free_port_skips_a_listener_and_returns_the_next() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
