"""At-most-one-active-session manager for the ``wimi-test`` MCP facade.

Implements the ``SessionRegistry`` described in
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 8 ("Threading and the
session registry"). The MCP facade is intentionally constrained to one
live :class:`~wimi_test.session.WimiTestSession` at a time: spinning up a
WIMI subprocess, attaching Playwright over CDP, and creating a per-test
master-DB user is too expensive (and too thread-affine) to multiplex.

The registry owns three pieces of mutable state behind a single
:class:`threading.Lock`:

* the active :class:`WimiTestSession` (or ``None``),
* the dedicated single-worker
  :class:`~wimi_test._internal.async_bridge.SessionThreadExecutor` that
  serialises every Playwright call, and
* a heartbeat timestamp used to expire idle sessions on the next tool
  invocation.

All Playwright-touching work — ``session.start()``, ``session.stop()``,
and any seeder run against ``session.user.db`` — is dispatched onto the
executor so it always runs on the OS thread that owns the Playwright
objects (Section 8). MCP tool handlers must call :meth:`heartbeat` on
every invocation to keep the idle timer fresh; the next call after the
timeout elapses ends the session and reports the timeout to the caller.

This module deliberately knows nothing about MCP tool plumbing: it
exposes plain Python methods that the FastMCP tool layer wraps. Keeping
the registry transport-agnostic makes it straightforward to unit-test
without spinning up the MCP server.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from wimi_test._internal.async_bridge import (
    SessionThreadExecutor,
    make_session_executor,
)
from wimi_test._internal.runid import next_run_id
from wimi_test.errors import WimiTestError
from wimi_test.session import WimiTestSession

__all__ = ["SessionRegistry"]


_logger = logging.getLogger(__name__)


class SessionRegistry:
    """Single-active-session manager for the ``wimi-test`` MCP facade.

    Enforces the "one live session at a time" invariant from
    ``docs/planning/TEST_INFRASTRUCTURE.md`` Section 8 and dispatches
    every thread-affine operation (start, stop, seed) onto a dedicated
    single-worker executor so Playwright's thread-affinity contract is
    never violated.

    The registry is itself thread-safe: a single :class:`threading.Lock`
    guards all mutations of the active-session triple
    (``_session`` / ``_executor`` / ``_handle``) and of the idle
    heartbeat. Read-mostly accessors (:meth:`get`, :meth:`get_executor`,
    :meth:`status`) take the lock for consistency even though most reads
    are of single attributes — the locking cost is negligible compared
    to the surrounding Playwright work and it makes the module easy to
    reason about.
    """

    def __init__(self, *, idle_timeout_s: int = 600) -> None:
        """Construct an empty registry.

        Parameters
        ----------
        idle_timeout_s:
            Number of seconds without a :meth:`heartbeat` before the
            next tool call ends the session. Defaults to 600 (10
            minutes). The check is lazy: nothing closes the session in
            the background — the timeout fires the next time
            :meth:`get` or :meth:`get_executor` is called.
        """
        self._session: Optional[WimiTestSession] = None
        self._executor: Optional[SessionThreadExecutor] = None
        self._handle: Optional[str] = None
        self._last_activity: float = 0.0
        self._idle_timeout_s: int = idle_timeout_s
        self._lock: threading.Lock = threading.Lock()
        # Watermark: epoch-seconds floor for the *next* MCP-response
        # captures payload. Bumped to "now" each time a tool finishes
        # serializing a successful response so subsequent responses only
        # carry activity that occurred between two consecutive tool
        # calls. ``None`` means "no prior response yet" — first tool call
        # after :meth:`start` falls back to including all captures (or
        # since session-start, see :meth:`consume_capture_window`).
        # Watermark management lives here rather than on
        # :class:`CaptureBundle` because the bundle is also consumed by
        # failure reports and pytest-html attachments where windowing by
        # MCP-response cadence would be wrong; keeping the watermark on
        # the registry confines the policy to the MCP-response layer.
        self._last_response_ts: Optional[float] = None
        # Session start timestamp captured on a successful :meth:`start`;
        # used as the floor for the first tool-response's captures so
        # pre-session noise (e.g. earlier sessions in the same process)
        # is never re-included. Reset to ``None`` on :meth:`end`.
        self._session_start_ts: Optional[float] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, *, scenario: str, seed: Optional[str] = None) -> str:
        """Bring up a session and return its stable string handle.

        Constructs a fresh :class:`WimiTestSession` and a dedicated
        :class:`SessionThreadExecutor`, then runs ``session.start()`` on
        the executor (synchronously). If ``seed`` is supplied, the
        named seeder is looked up via
        :func:`wimi_test.db.seeders.get_seeder` and invoked against
        ``session.user.db`` on the same executor so the seeding work
        happens on the Playwright-affine thread.

        Raises
        ------
        WimiTestError
            If a session is already active. Callers must
            :meth:`end` first.

        Notes
        -----
        Defensive cleanup: if any step after construction fails — the
        ``session.start()`` call, the seeder lookup, or the seeder run
        itself — the partial session is stopped and the executor shut
        down before the original exception propagates. This guarantees
        that a failed :meth:`start` never leaves the registry in a
        half-initialised state.
        """
        with self._lock:
            if self._session is not None:
                raise WimiTestError(
                    "Another session is already active. "
                    "Call end_session() first."
                )

            session = WimiTestSession(scenario=scenario)
            executor = make_session_executor()

            try:
                executor.run(session.start)

                if seed is not None:
                    # Lazy import: seeders pull in the WIMI database
                    # stack, which we'd rather not require for callers
                    # who never seed.
                    from wimi_test.db.seeders import get_seeder

                    seeder = get_seeder(seed)
                    executor.run(seeder, session.user.db)

                # Wire ``bridge.user_db`` AFTER the seeder so the WIMI
                # side sees the fully-migrated DB on its first query.
                # If we did this before seeding, the page-load auto-fired
                # bridge calls would race the migrations and return
                # spurious "no such table" errors that mask real
                # failures. See ``WimiTestSession.attach_user_db`` for
                # the full rationale.
                executor.run(session.attach_user_db)

                handle = next_run_id()
                self._session = session
                self._executor = executor
                self._handle = handle
                now = time.time()
                self._last_activity = now
                # Record the session start so the first tool-response's
                # captures payload is floored at "now" rather than the
                # epoch — avoids re-surfacing residue from a prior
                # session in the same process. Watermark stays ``None``
                # until the first :meth:`consume_capture_window` advances
                # it.
                self._session_start_ts = now
                self._last_response_ts = None
                return handle
            except BaseException:
                # Partial-init rollback. Stop the session (always-safe;
                # handles any combination of "started"/"not started")
                # and shut down the executor so we don't leak a worker
                # thread. Each step is wrapped so a failure in cleanup
                # does not mask the original exception.
                try:
                    executor.run(session.stop)
                except Exception as cleanup_exc:  # noqa: BLE001
                    _logger.warning(
                        "SessionRegistry.start(): cleanup session.stop() "
                        "raised: %s",
                        cleanup_exc,
                    )
                try:
                    executor.shutdown(wait=True)
                except Exception as cleanup_exc:  # noqa: BLE001
                    _logger.warning(
                        "SessionRegistry.start(): cleanup executor.shutdown() "
                        "raised: %s",
                        cleanup_exc,
                    )
                raise

    def end(self) -> None:
        """Tear down the active session, if any. Idempotent.

        Stops the session on the executor (so Playwright cleanup runs
        on the right thread), then shuts the executor down. Each step
        is independently wrapped so a single failed cleanup never
        skips the next one — the worst case is a logged warning per
        failed step and a registry left in the cleared state.
        """
        with self._lock:
            if self._session is None:
                return

            session = self._session
            executor = self._executor

            if executor is not None:
                try:
                    executor.run(session.stop)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "SessionRegistry.end(): session.stop() raised: %s",
                        exc,
                    )
                try:
                    executor.shutdown(wait=True)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "SessionRegistry.end(): executor.shutdown() raised: %s",
                        exc,
                    )
            else:
                # No executor (shouldn't happen in normal flow, but
                # defensive): stop directly so the user/process still
                # gets cleaned up.
                try:
                    session.stop()
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "SessionRegistry.end(): session.stop() (no executor) "
                        "raised: %s",
                        exc,
                    )

            self._session = None
            self._executor = None
            self._handle = None
            self._last_activity = 0.0
            self._last_response_ts = None
            self._session_start_ts = None

    # ------------------------------------------------------------------
    # Accessors (with lazy idle-timeout enforcement)
    # ------------------------------------------------------------------

    def get(self) -> WimiTestSession:
        """Return the active session, expiring it on idle timeout.

        Raises
        ------
        WimiTestError
            If no session is active, or if the idle timeout elapsed
            (in which case the session is closed before the error
            is raised).
        """
        with self._lock:
            if (
                self._session is not None
                and time.time() - self._last_activity > self._idle_timeout_s
            ):
                # Drop the lock before calling end() — end() takes the
                # same lock. The standard pattern is to invoke end()
                # outside the lock and then re-raise.
                pass
            else:
                if self._session is None:
                    raise WimiTestError(
                        "No active session. Call start_session() first."
                    )
                return self._session

        # Idle: close the session (acquires the lock again) and signal
        # the timeout to the caller.
        self.end()
        raise WimiTestError("Session timed out and was closed")

    def get_executor(self) -> SessionThreadExecutor:
        """Return the active session's executor, expiring on idle timeout.

        Raises
        ------
        WimiTestError
            If no session is active, or if the idle timeout elapsed.
        """
        with self._lock:
            if (
                self._session is not None
                and time.time() - self._last_activity > self._idle_timeout_s
            ):
                pass
            else:
                if self._session is None or self._executor is None:
                    raise WimiTestError(
                        "No active session. Call start_session() first."
                    )
                return self._executor

        self.end()
        raise WimiTestError("Session timed out and was closed")

    # ------------------------------------------------------------------
    # Capture-response windowing
    # ------------------------------------------------------------------

    def consume_capture_window(self) -> Optional[float]:
        """Return the ``since_ts`` floor for the next MCP-response captures.

        Atomically reads the current watermark and advances it to "now"
        so the *next* call sees only entries with ``timestamp > now``.
        Net effect: each successful tool response carries only the
        activity that occurred between the previous tool call and this
        one — typically 0-5 entries instead of the full session history.

        First call after :meth:`start` (no prior watermark) falls back
        to ``self._session_start_ts``, so pre-session-start noise from
        an earlier session in the same process is excluded but
        post-start activity (the landing-page init burst) is still
        surfaced on the first response.

        Returns
        -------
        Optional[float]
            The epoch-seconds floor to forward to
            :meth:`CaptureBundle.snapshot` / :func:`recent`. ``None``
            only if there is no active session and no prior session has
            ever started — that path is unreachable from the live tool
            handlers (which always have an active session by the time
            they reach :func:`success`), but is preserved as a safe
            fallback meaning "no filter".
        """
        with self._lock:
            cutoff = self._last_response_ts
            if cutoff is None:
                cutoff = self._session_start_ts
            self._last_response_ts = time.time()
            return cutoff

    # ------------------------------------------------------------------
    # Heartbeat / status
    # ------------------------------------------------------------------

    def heartbeat(self) -> None:
        """Reset the idle timer. Called by every tool invocation.

        Tools should call this at the top of every handler so that
        active use of the session keeps it alive. The idle timeout is
        only ever checked lazily by :meth:`get` / :meth:`get_executor`,
        so a stale heartbeat does not actively close the session — it
        just makes the *next* accessor call decide to.
        """
        with self._lock:
            self._last_activity = time.time()

    def status(self) -> dict:
        """Return a read-only snapshot of the registry's state.

        Keys
        ----
        ``active``:
            ``True`` iff a session is currently registered.
        ``handle``:
            The stable handle returned by :meth:`start`, or ``None``.
        ``scenario``:
            The active session's scenario name, or ``None``.
        ``idle_s``:
            Seconds since the last heartbeat, or ``None`` if there is
            no active session.
        """
        with self._lock:
            if self._session is None:
                return {
                    "active": False,
                    "handle": None,
                    "scenario": None,
                    "idle_s": None,
                }
            return {
                "active": True,
                "handle": self._handle,
                "scenario": self._session.scenario,
                "idle_s": time.time() - self._last_activity,
            }
