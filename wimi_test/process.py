"""WIMI subprocess lifecycle manager.

`WimiProcess` owns one and only one concern: launching ``python
run_wimi.py --test-mode ...`` as a child process, watching its stdout for
the ``TEST_MODE_READY:port=N`` sentinel, and ensuring the child is killed
on teardown — even when something else in the test goes wrong.

This module is deliberately OS-only. It has *no* knowledge of the DOM,
the WIMI database, Playwright, or CDP semantics beyond the integer port
number. Higher layers (``wimi_test.session``, ``wimi_test.page``) wrap
the port into a Playwright connection; the polling fallback here is the
single concession to "is the CDP endpoint up?" and uses
``urllib.request`` only — no third-party HTTP client.

Design references:

* ``docs/planning/TEST_INFRASTRUCTURE.md`` Section 3 (Module
  responsibility matrix) — defines this module's narrow remit.
* ``docs/planning/TEST_INFRASTRUCTURE.md`` Section 5 (``--test-mode``
  Launch Flag) — defines the CLI surface this module spawns and the
  ``TEST_MODE_READY:port=N`` ready-signal contract on stdout.

Stdlib only. The only ``wimi_test.*`` imports are
:class:`~wimi_test.config.TestConfig` and the two relevant exception
classes from :mod:`wimi_test.errors`.
"""

from __future__ import annotations

import collections
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from wimi_test.config import TestConfig
from wimi_test.errors import AttachTimeout, ProcessSpawnError

__all__ = ["WimiProcess"]

logger = logging.getLogger(__name__)

# How many trailing stdout lines we keep for crash diagnostics.
_STDOUT_BUFFER_LIMIT = 200

# Sentinel printed by ``src/app/main.py`` once the QWebChannel bridge is
# ready. The trailing ``=`` is intentional — see
# ``TEST_INFRASTRUCTURE.md`` Section 5 step 8.
_READY_SIGNAL_PREFIX = "TEST_MODE_READY:port="

# How often we poll the ``/json/version`` fallback once we cross the 75%
# mark of the ready timeout. 0.5s is a balance between snappy detection
# and not hammering the embedded HTTP server.
_FALLBACK_POLL_INTERVAL_S = 0.5

# urllib timeout for the polling fallback. Independent of the overall
# attach timeout — each individual probe should fail fast.
_FALLBACK_HTTP_TIMEOUT_S = 1.0


class WimiProcess:
    """Manages the lifecycle of one WIMI subprocess for testing.

    Typical use is via the context manager protocol::

        with WimiProcess(config) as proc:
            port = proc._picked_port  # already spawned + ready
            ...

    Direct use is fine too::

        proc = WimiProcess(config)
        port = proc.spawn()
        proc.wait_for_ready()
        try:
            ...
        finally:
            proc.terminate()

    Thread safety: ``spawn`` is not safe to call concurrently with itself.
    ``terminate`` and ``last_stdout`` are safe to call from any thread.
    The reader thread runs as a daemon and only mutates the bounded
    stdout buffer (under :attr:`_stdout_lock`) and the ready event.
    """

    def __init__(self, config: TestConfig) -> None:
        self._config: TestConfig = config

        # Process handle — None before spawn, None again after terminate.
        self._proc: Optional[subprocess.Popen[str]] = None

        # Port we ended up using. Set in spawn() and never cleared.
        self._picked_port: Optional[int] = None

        # Reader thread + buffer for diagnostics.
        self._reader_thread: Optional[threading.Thread] = None
        self._stdout_lock: threading.Lock = threading.Lock()
        self._stdout_buffer: collections.deque[str] = collections.deque(
            maxlen=_STDOUT_BUFFER_LIMIT
        )

        # Set by the reader thread when it sees the ready sentinel.
        self._ready_event: threading.Event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def spawn(self) -> int:
        """Launch the WIMI subprocess and start the stdout reader thread.

        Returns
        -------
        int
            The CDP debug port that was selected.

        Raises
        ------
        ProcessSpawnError
            If no port in ``config.cdp_port_range`` could be bound.
        """
        port = self._pick_free_port()
        cmd = self._build_command(port)
        cwd = self._project_root()

        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        # Force UTF-8 stdout/stderr in the child so emoji prints (e.g. the
        # camera glyph in media_scheme_handler.register_media_scheme) don't
        # crash with UnicodeEncodeError on Windows, where piped stdout
        # defaults to cp1252. ``errors='replace'`` is a belt-and-suspenders
        # guard against any other un-encodable character.
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # ``stderr=STDOUT`` so the reader thread sees a single merged
        # stream — useful when WIMI dies with a Python traceback on
        # stderr but no stdout output. ``text=True`` gives us str lines;
        # ``bufsize=1`` enables line-buffered reads. ``encoding='utf-8'``
        # matches PYTHONIOENCODING so the parent decodes the same way the
        # child encodes.
        # stdin=DEVNULL: when the parent is the wimi-test MCP server,
        # its own stdin is the MCP stdio transport that Claude Code is
        # actively reading from. If we let the WIMI child inherit that
        # pipe, the two readers race for protocol messages and Qt's
        # bootstrap can stall before printing a single byte. DEVNULL
        # breaks the inheritance and is safe — WIMI never reads stdin.
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            env=env,
        )

        self._picked_port = port

        # Reader thread is daemon=True so an unhandled exception in the
        # main test thread doesn't leave it dangling forever.
        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            name=f"WimiProcess-stdout-{port}",
            daemon=True,
        )
        self._reader_thread.start()

        return port

    def wait_for_ready(self, timeout_s: Optional[int] = None) -> None:
        """Block until the subprocess prints the ready sentinel.

        Implements a polling fallback: once we cross 75% of the timeout
        without seeing the sentinel, we start probing
        ``http://127.0.0.1:<port>/json/version``. A 200 response there
        is taken as evidence the Qt CDP server is up — the print may
        have been swallowed by buffering or a stdout race.

        Parameters
        ----------
        timeout_s
            Override for ``config.timeout_attach_s``. ``None`` uses the
            configured default.

        Raises
        ------
        ProcessSpawnError
            If the subprocess exits before becoming ready.
        AttachTimeout
            If neither the sentinel nor the HTTP fallback succeed within
            the timeout.
        """
        if self._proc is None or self._picked_port is None:
            raise RuntimeError("wait_for_ready() called before spawn()")

        timeout = (
            timeout_s if timeout_s is not None else self._config.timeout_attach_s
        )
        start = time.monotonic()
        deadline = start + timeout
        # Cross-over point at which we begin the HTTP fallback poll loop.
        fallback_start = start + (timeout * 0.75)

        # Phase 1: pure event wait until we cross the fallback threshold.
        # We use short waits so we can also notice early process exit.
        while True:
            now = time.monotonic()
            if self._ready_event.is_set():
                return

            # Did the process die under us?
            rc = self._proc.poll()
            if rc is not None:
                raise ProcessSpawnError(
                    message="WIMI exited before becoming ready",
                    exit_code=rc,
                    last_stdout=self.last_stdout(),
                )

            if now >= deadline:
                break

            # In phase 1 (before fallback_start) we just wait on the
            # event. In phase 2 we also probe the HTTP endpoint.
            if now < fallback_start:
                # Wait up to whichever comes first: ready event,
                # fallback start, or deadline.
                wait_for = min(fallback_start, deadline) - now
                if wait_for > 0 and self._ready_event.wait(timeout=wait_for):
                    return
                # Loop continues — re-check process state and time.
                continue

            # Phase 2: combined event-wait + HTTP probe. We deliberately
            # do NOT spin here; we sleep for the poll interval inside
            # the event.wait so a late ready signal still wins.
            wait_for = min(_FALLBACK_POLL_INTERVAL_S, deadline - now)
            if wait_for > 0 and self._ready_event.wait(timeout=wait_for):
                return

            if self._probe_cdp_endpoint(self._picked_port):
                logger.warning(
                    "WIMI ready signal not seen on stdout, but CDP "
                    "endpoint at port %d is responsive; proceeding "
                    "(stdout buffering race?)",
                    self._picked_port,
                )
                # Treat the endpoint coming up as ready so subsequent
                # callers don't re-wait.
                self._ready_event.set()
                return

        # Final fallback probe at the deadline boundary — gives one more
        # chance in case the endpoint became ready between the last poll
        # and the timeout.
        if self._probe_cdp_endpoint(self._picked_port):
            logger.warning(
                "WIMI ready signal not seen, but CDP endpoint at port "
                "%d became responsive at the deadline; proceeding.",
                self._picked_port,
            )
            self._ready_event.set()
            return

        elapsed = time.monotonic() - start
        raise AttachTimeout(
            message=(
                f"Timed out waiting for WIMI ready signal on port "
                f"{self._picked_port} after {elapsed:.1f}s"
            ),
            port=self._picked_port,
            elapsed_s=elapsed,
            last_stdout=self.last_stdout(),
        )

    def terminate(self, grace_s: int = 5) -> None:
        """Kill the subprocess if it is still running. Idempotent.

        On Windows we send ``CTRL_BREAK_EVENT`` (the only signal that
        works for a child started with ``CREATE_NEW_PROCESS_GROUP``). On
        POSIX we send SIGTERM. If the child is still alive after
        ``grace_s`` seconds, we escalate to ``kill()``.

        Any secondary failures during cleanup are logged at WARNING and
        swallowed — terminate() must not raise.
        """
        proc = self._proc
        if proc is None:
            return

        try:
            # Already exited? Just clean state.
            if proc.poll() is not None:
                return

            # Try graceful shutdown first.
            try:
                if sys.platform == "win32":
                    # CTRL_BREAK_EVENT works because spawn() used
                    # CREATE_NEW_PROCESS_GROUP. CTRL_C_EVENT does not
                    # work for child processes on Windows.
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
            except (OSError, ValueError) as exc:
                logger.warning(
                    "WimiProcess.terminate(): graceful signal failed: %s",
                    exc,
                )

            try:
                proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "WimiProcess.terminate(): grace period (%ds) "
                    "expired; escalating to kill()",
                    grace_s,
                )
                try:
                    proc.kill()
                    proc.wait(timeout=grace_s)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    logger.warning(
                        "WimiProcess.terminate(): kill() failed or "
                        "still timing out: %s",
                        exc,
                    )
        except Exception as exc:  # noqa: BLE001 — must not propagate
            logger.warning(
                "WimiProcess.terminate(): unexpected error during "
                "cleanup: %s",
                exc,
            )
        finally:
            # Closing stdout signals EOF to the reader thread so it
            # exits the read loop cleanly. The thread is a daemon so
            # we don't actually need to join, but doing so on a short
            # timeout makes test output more predictable.
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "WimiProcess.terminate(): error closing stdout: %s",
                    exc,
                )

            reader = self._reader_thread
            if reader is not None and reader.is_alive():
                reader.join(timeout=1.0)

            self._proc = None
            self._reader_thread = None

    def is_alive(self) -> bool:
        """``True`` iff the subprocess exists and has not yet exited."""
        return self._proc is not None and self._proc.poll() is None

    def last_stdout(self, n: int = 100) -> list[str]:
        """Return up to the last ``n`` stdout lines as a snapshot list.

        Thread-safe: takes the buffer lock for the copy. The returned
        list is a stable snapshot — subsequent stdout writes will not
        mutate it.
        """
        if n <= 0:
            return []
        with self._stdout_lock:
            # ``deque`` slicing is not supported, but list() then slice
            # gives us a snapshot in one O(n) pass.
            snapshot = list(self._stdout_buffer)
        if n >= len(snapshot):
            return snapshot
        return snapshot[-n:]

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "WimiProcess":
        self.spawn()
        try:
            self.wait_for_ready()
        except BaseException:
            # If wait_for_ready raises, make sure we don't leak the
            # subprocess. Re-raise after cleanup.
            self.terminate()
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        self.terminate()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _pick_free_port(self) -> int:
        """Scan ``config.cdp_port_range`` for the first bindable port.

        Raises
        ------
        ProcessSpawnError
            If every port in the range is in use.
        """
        lo, hi = self._config.cdp_port_range
        for port in range(lo, hi + 1):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            else:
                return port
            finally:
                sock.close()

        raise ProcessSpawnError(
            message="No free port in CDP range",
            exit_code=-1,
            last_stdout=[],
        )

    def _build_command(self, port: int) -> list[str]:
        """Build the argv used to launch the WIMI subprocess."""
        return [
            sys.executable,
            "run_wimi.py",
            "--test-mode",
            "--debug-port",
            str(port),
            "--app-data-dir",
            str(self._config.app_data_dir),
        ]

    @staticmethod
    def _project_root() -> Path:
        """Resolve the repository root from this file's location.

        ``wimi_test/process.py`` → ``<repo>/wimi_test/process.py`` so
        ``parent.parent`` is the repo root that holds ``run_wimi.py``.
        """
        return Path(__file__).resolve().parent.parent

    def _read_stdout(self) -> None:
        """Background reader: appends lines and watches for ready signal.

        Runs on a daemon thread. Exits cleanly on EOF (which happens when
        the subprocess closes stdout, e.g. on exit, or when terminate()
        explicitly closes the pipe).
        """
        proc = self._proc
        if proc is None or proc.stdout is None:
            return

        try:
            for line in proc.stdout:
                # Strip the trailing newline for nicer storage; the raw
                # line is rarely useful for diagnostics.
                stripped = line.rstrip("\r\n")
                with self._stdout_lock:
                    self._stdout_buffer.append(stripped)

                # Match anywhere in the line: main.py writes the sentinel
                # on its own line, but a defensive substring check is
                # cheap and tolerates stray prefixes from logging.
                if _READY_SIGNAL_PREFIX in stripped and not self._ready_event.is_set():
                    self._ready_event.set()
        except (OSError, ValueError):
            # Pipe closed underneath us during terminate(). Normal.
            return
        except Exception as exc:  # noqa: BLE001 — daemon thread must not raise
            logger.warning(
                "WimiProcess stdout reader exited with error: %s", exc
            )

    @staticmethod
    def _probe_cdp_endpoint(port: int) -> bool:
        """Return ``True`` iff ``http://127.0.0.1:<port>/json/version`` returns 200.

        Used as a fallback when the stdout ready signal is delayed or
        missed entirely. Any HTTP error, connection error, or timeout
        is treated as "not ready" — we do not raise.
        """
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            with urllib.request.urlopen(  # noqa: S310 — local CDP probe
                url, timeout=_FALLBACK_HTTP_TIMEOUT_S
            ) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, ConnectionError, OSError, TimeoutError):
            return False
        except Exception:  # noqa: BLE001 — fallback must never raise
            return False
