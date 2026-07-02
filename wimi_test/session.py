"""End-to-end test session orchestrator (pychrome edition).

:class:`WimiTestSession` is the *hub* of the WIMI test infrastructure: the
single object that knows about all four moving parts at once — the WIMI
subprocess, the pychrome/CDP attachment, the capture pipeline, and the
per-test database user. See ``docs/planning/PYCHROME_MIGRATION.md``
Sections 5.1 ("Connection layer") and 6 ("Session integration") for the
high-level shape of this module post-migration; see
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 4 for the broader
``WimiTestSession`` API contract that this implementation preserves.

Every other ``wimi_test.*`` module is intentionally narrow:
:mod:`wimi_test.process` knows about subprocesses but nothing about
CDP, :mod:`wimi_test.page` knows about a CDP tab but nothing about
subprocesses, etc. ``session.py`` is the glue.

Public API: this rewrite is **wire-compatible** with the previous
implementation. ``start()`` / ``stop()``, the ``page`` / ``user`` /
``captures`` / ``start_ts`` accessors, and the context manager protocol
all retain their previous signatures and contracts so neither
``tests/wimi_test/scenarios/*`` nor the ``wimi-test`` MCP facade needs
to change. The only intentional rename is the previously-private escape
hatch: where the old code held a raw page handle, this version holds a
:class:`WimiTab` in ``self._tab`` and exposes it via the public
:attr:`tab` property for scenarios that need raw CDP access.

Lifecycle::

    session = WimiTestSession(scenario="smoke")
    session.start()
    try:
        session.page.goto("dashboard")
        session.page.screenshot(path="dash.png")
    finally:
        session.stop()  # always safe — handles partial-start failures

Or as a context manager::

    with WimiTestSession(scenario="smoke") as session:
        session.page.goto("dashboard")

Captures (T3.8) are wired in :meth:`start`: a :class:`ConsoleCapture`,
:class:`NetworkCapture`, and :class:`BridgeCapture` are attached to the
live :class:`WimiTab` before ``start_ts`` is stamped, then composed into
a :class:`~wimi_test.capture.bundle.CaptureBundle` exposed via
:attr:`captures`. Detach happens in reverse order on :meth:`stop`,
each step independently best-effort so capture cleanup never blocks
subprocess termination.

Threading: this class is not thread-safe and not intended to be. Pytest
runs single-threaded, and the MCP facade serialises all CDP work on a
single dedicated worker thread (see
:mod:`wimi_test._internal.async_bridge`). Callers must own one
:class:`WimiTestSession` per CDP worker thread.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from wimi_test._internal.cdp_client import WimiBrowser, WimiTab, open_session
from wimi_test.capture.bridge import BridgeCapture
from wimi_test.capture.bundle import CaptureBundle
from wimi_test.capture.console import ConsoleCapture
from wimi_test.capture.network import NetworkCapture
from wimi_test.config import TestConfig
from wimi_test.db.test_user import TestUser
from wimi_test.errors import WimiTestError
from wimi_test.page import WimiPage
from wimi_test.process import WimiProcess

__all__ = ["WimiTestSession"]


_logger = logging.getLogger(__name__)


class WimiTestSession:
    """End-to-end test session: spawn -> attach -> (capture) -> teardown.

    See ``docs/planning/PYCHROME_MIGRATION.md`` §5.1 + §6 for the CDP
    integration shape and ``docs/planning/TEST_INFRASTRUCTURE.md``
    Section 4 for the full API contract this implementation preserves.

    A session owns four pieces of state, brought up in order by
    :meth:`start` and torn down in reverse by :meth:`stop`:

    1. A :class:`~wimi_test.db.test_user.TestUser` (created against a
       :class:`MasterDatabase` rooted at ``config.app_data_dir``).
    2. A :class:`~wimi_test.process.WimiProcess` (the WIMI subprocess
       launched with ``--test-mode``).
    3. A pychrome connection over CDP to the spawned process — a
       :class:`WimiBrowser` plus its primary :class:`WimiTab` — and a
       :class:`~wimi_test.page.WimiPage` wrapping the tab.
    4. A :class:`~wimi_test.capture.bundle.CaptureBundle` aggregating
       console / network / bridge events, attached after the tab is
       live and exposed via :attr:`captures` (T3.8).
    """

    def __init__(
        self,
        *,
        scenario: str,
        config: Optional[TestConfig] = None,
    ) -> None:
        """Prepare a session; no subprocess is spawned until :meth:`start`.

        Parameters
        ----------
        scenario:
            Short, filesystem-safe scenario name (matches
            ``[a-zA-Z0-9_-]+``). Used as the middle segment of the test
            user's name (``test_<scenario>_<run_id>``).
        config:
            Optional :class:`TestConfig`. Defaults to
            :meth:`TestConfig.resolve` (env-var layered defaults) when
            ``None``.
        """
        self.scenario: str = scenario
        self.config: TestConfig = config if config is not None else TestConfig.resolve()

        # TODO(T5.1): replace inline run-id with
        # ``wimi_test._internal.runid.next_run_id()`` once that module
        # lands. The shape "<pid>_<ms-since-epoch>" matches the character
        # class accepted by TestUser (``[a-zA-Z0-9_-]+``) and is unique
        # within a process (pid) and across processes (timestamp).
        self._run_id: str = f"{os.getpid()}_{int(time.time() * 1000)}"

        # Lifecycle state. None values reflect "not yet brought up" or
        # "torn down". The single boolean ``_started`` is the source of
        # truth for the public ``page`` / ``user`` accessors.
        self._proc: Optional[WimiProcess] = None
        self._browser: Optional[WimiBrowser] = None
        self._tab: Optional[WimiTab] = None
        self._page: Optional[WimiPage] = None
        self._user: Optional[TestUser] = None
        self._master_db: Optional[Any] = None  # database.master_db.MasterDatabase
        # Capture pipeline (T3.8). The bundle holds the three capture
        # streams; all three attach to ``self._tab`` directly under the
        # pychrome model (no separate CDP session object — the tab itself
        # is the raw CDP handle). The bundle stays ``None`` for an
        # unstarted or torn-down session so the not-started guard on the
        # public ``captures`` property is the single source of truth.
        self._captures: Optional[CaptureBundle] = None
        self._started: bool = False
        self._start_ts: Optional[float] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Bring up the full session: master DB -> user -> process -> tab.

        Steps run in dependency order:

        1. Construct ``MasterDatabase(data_dir=config.app_data_dir)``.
        2. Construct :class:`TestUser` (creates the user row immediately).
        3. Spawn the WIMI subprocess and wait for the
           ``TEST_MODE_READY:port=N`` ready signal.
        4. Connect over CDP via :func:`open_session` — picks the primary
           WIMI tab and starts it. Replaces the previous multi-step
           connect / context-pick / first-page lookup with a single call.
        5. Wrap the tab in :class:`WimiPage` rooted at the project root.
        6. Attach :class:`ConsoleCapture` / :class:`NetworkCapture` /
           :class:`BridgeCapture` to the live tab and compose them into
           a :class:`CaptureBundle` exposed via :attr:`captures`. All
           three captures take a :class:`WimiTab` directly — the pychrome
           rewrite removed the separate CDP-session object that the
           previous network capture used to require.
        7. Stamp ``start_ts`` and flip ``_started``.

        Idempotency: calling :meth:`start` on an already-started session
        raises :class:`WimiTestError`. If any step *after* the first
        fails, :meth:`stop` is invoked to roll back the partial state and
        the original exception is re-raised so callers see the root
        cause, not a cleanup error.

        Raises
        ------
        WimiTestError
            If the session is already started, or if no usable WIMI tab
            is exposed by the spawned process's CDP endpoint (raised
            from :meth:`WimiBrowser.primary_tab` via :func:`open_session`).
        """
        if self._started:
            raise WimiTestError("Session already started")

        try:
            # 1. Master DB. Lazy-imported so simply importing
            # ``wimi_test`` doesn't pull in the WIMI database stack —
            # tooling that introspects this package without WIMI on the
            # PYTHONPATH should still work.
            from database.master_db import MasterDatabase

            self._master_db = MasterDatabase(data_dir=self.config.app_data_dir)

            # 2. Test user. Creating the user row happens inside
            # ``TestUser.__init__`` so any collision surfaces here.
            self._user = TestUser(
                self._master_db,
                scenario=self.scenario,
                run_id=self._run_id,
            )

            # 3. WIMI subprocess. ``spawn`` returns the picked CDP port;
            # ``wait_for_ready`` blocks until the bridge is up.
            self._proc = WimiProcess(self.config)
            port = self._proc.spawn()
            self._proc.wait_for_ready()

            # 4. CDP connection via pychrome. ``open_session`` constructs
            # a :class:`WimiBrowser`, picks the primary WIMI tab (skipping
            # the empty bookkeeping target Qt sometimes exposes), starts
            # the tab, and returns the pair. This single call replaces
            # the previous multi-step CDP connect / context-pick /
            # first-page lookup chain.
            #
            # If no usable WIMI tab is found, ``open_session`` raises
            # :class:`WimiTestError` with the discriminator ("no scripts"
            # vs. "title doesn't contain WIMI") preserved by the wrapper.
            self._browser, self._tab = open_session(port)

            # 5. WIMI-aware page wrapper. ``Path(__file__)`` is
            # ``<repo>/wimi_test/session.py`` so ``parent.parent`` is the
            # repo root holding ``src/web/html/`` etc.
            self._page = WimiPage(
                self._tab,
                app_root=Path(__file__).resolve().parent.parent,
                config=self.config,
            )

            # 6. Wire the capture pipeline (per TEST_INFRASTRUCTURE.md
            # §6). All three captures attach to the live tab BEFORE
            # ``_start_ts`` is stamped so the failure-report hook can
            # slice each buffer via ``since_ts=session.start_ts`` and
            # reliably include everything the test could have caused.
            #
            # Under pychrome there is no separate CDP-session object:
            # ``WimiTab`` *is* the raw CDP handle, so all three captures
            # take the tab directly. This collapses what was a three-step
            # attach (page-level + per-tab CDP session for network) in
            # the previous implementation.
            console = ConsoleCapture(
                max_messages=self.config.console_buffer_size,
            )
            console.attach(self._tab)

            network = NetworkCapture(
                max_events=self.config.network_buffer_size,
                url_filter=self.config.network_url_filter,
            )
            network.attach(self._tab)

            bridge = BridgeCapture(
                max_calls=self.config.bridge_buffer_size,
            )
            bridge.attach(self._tab)

            self._captures = CaptureBundle(
                console=console,
                network=network,
                bridge=bridge,
            )

            # 7. Stamp the session start time *last* so partial-start
            # failures don't leave a stale timestamp readable via the
            # public property. Stamping AFTER the captures attach means
            # ``since_ts=session.start_ts`` slices include every event
            # observed from the test's perspective onward.
            #
            # NOTE: ``bridge.user_db`` is **not** wired here. The
            # registry calls :meth:`attach_user_db` separately, *after*
            # the seeder has populated the per-user .db file with the
            # Phase 2/4 schema and any fixture data. Wiring the bridge
            # before the seeder would race the page-load auto-fired
            # bridge calls (themes, exams, analytics, ...) against a
            # half-migrated DB, producing spurious "no such table"
            # errors that mask real test failures.
            self._start_ts = time.time()
            self._started = True
        except BaseException:
            # Roll back any partial state. ``stop`` is always-safe and
            # handles every combination of "set / not set" for the
            # private attributes. We still drop the user on cleanup
            # because a half-started session has no useful state to
            # preserve.
            try:
                self.stop()
            except Exception as cleanup_exc:  # noqa: BLE001
                _logger.warning(
                    "WimiTestSession.start(): cleanup after failed start "
                    "raised: %s",
                    cleanup_exc,
                )
            raise

    def attach_user_db(self) -> None:
        """Switch the WIMI bridge from "no user" to the test user's DB.

        Production goes through ``MainWindow.set_user_database`` (driven
        by the user-login UI flow); test mode uses a dedicated bridge
        slot (``loadTestUserDatabase``) so we don't have to drive the
        login UI from a not-yet-logged-in state.

        Called by the registry **after** any seeder has populated the
        per-user database file. Doing it after seeding is load-bearing:
        the page auto-fires bridge calls (themes, exams, analytics, ...)
        as soon as ``window.api`` is ready, and those calls run on
        whatever schema is on disk at the time. Wiring the bridge before
        the seeder runs the Phase 2/4 migrations would have those calls
        hit "no such table: exam_contexts" / "no such table:
        question_entries" and surface noisy red-herring errors during
        every test.

        Idempotent: a second call resets the bridge to the same user.
        Must be called after :meth:`start` (which leaves the page
        loaded but with ``bridge.user_db = None``).

        NOTE: this only sets ``bridge.user_db``. The media manager and
        scheme handler that ``MainWindow.set_user_database`` also wires
        aren't reachable from the bridge — scenarios that touch media
        uploads will need a follow-up.

        Raises
        ------
        WimiTestError
            If ``window.api`` doesn't appear within the configured
            default timeout, or if the slot returns ``success=false``.
        RuntimeError
            If called before :meth:`start`.
        """
        if not self._started:
            raise RuntimeError(
                "attach_user_db() called before start(); start the "
                "session first."
            )
        # ``TEST_MODE_READY`` fires before the initial page load
        # finishes, so ``window.api`` may not exist yet; wait for
        # ``src/web/js/api/_loader.js`` to finish promoting it.
        self._tab.wait_for_wimi_api(
            timeout_ms=self.config.timeout_default_ms,
        )
        self._page.eval_js(
            f"window.api.loadTestUserDatabase({self._user.user_id})",
            await_promise=True,
        )

    def stop(self, *, drop_user: bool = True) -> None:
        """Tear down the session in reverse of :meth:`start`. Always safe.

        This method is the primary defence against leaking subprocesses
        or test-user rows. It is wrapped step-by-step so a failure in
        one cleanup step does not block the others — the worst case is
        a logged warning per failed step.

        Order:

        1. Detach captures (bridge -> network -> console).
        2. Stop the :class:`WimiTab` (idempotent; closes the tab's
           websocket recv thread).
        3. Close the :class:`WimiBrowser` (idempotent; iterates any
           remaining cached pychrome ``Tab`` objects and stops them —
           pychrome itself has no top-level ``close`` method, so the
           wrapper does the work).
        4. Terminate the WIMI subprocess.
        5. Drop the :class:`TestUser` (optional via ``drop_user``).
        6. Discard the master-DB reference.

        Parameters
        ----------
        drop_user:
            When ``True`` (default) the underlying :class:`TestUser` is
            dropped (row deleted, ``.db`` file removed). Pass ``False``
            to keep the user around, e.g. for post-mortem inspection
            after a debugging session.
        """
        # Fast path: nothing to do and nothing left to clean up.
        if (
            not self._started
            and self._proc is None
            and self._browser is None
            and self._tab is None
            and self._user is None
            and self._master_db is None
            and self._captures is None
        ):
            return

        # 1. Capture pipeline. Detach in reverse attach order so the
        # bridge poll thread stops first, then the CDP network listener,
        # then the console listener. Each detach is wrapped individually
        # — capture cleanup must never block subprocess termination, so
        # one failed detach should not skip the next one. Buffered
        # events on each capture are preserved (per the capture
        # modules' detach contracts) so any post-stop snapshot reads
        # still work.
        if self._captures is not None:
            try:
                if self._captures.bridge is not None:
                    self._captures.bridge.detach()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                _logger.warning(
                    "WimiTestSession.stop(): BridgeCapture detach raised: %s",
                    exc,
                )
            try:
                self._captures.network.detach()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                _logger.warning(
                    "WimiTestSession.stop(): NetworkCapture detach raised: %s",
                    exc,
                )
            try:
                self._captures.console.detach()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                _logger.warning(
                    "WimiTestSession.stop(): ConsoleCapture detach raised: %s",
                    exc,
                )
            self._captures = None

        # 2. CDP tab. ``WimiTab.stop`` is idempotent — it swallows
        # ``pychrome.RuntimeException`` for the "never started" case and
        # logs anything else. Closing the tab tears down the websocket
        # recv thread and unblocks any handlers waiting on it.
        if self._tab is not None:
            try:
                self._tab.stop()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                _logger.warning(
                    "WimiTestSession.stop(): WimiTab.stop() raised: %s",
                    exc,
                )
            finally:
                self._tab = None

        # 3. CDP browser. ``WimiBrowser.close`` walks pychrome's internal
        # tab cache and stops any tab that is still running, swallowing
        # errors per its own best-effort contract. There is no
        # ``Target.disposeBrowserContext`` equivalent under Qt's CDP —
        # the only thing the browser owns are tab websockets, which the
        # close walks. After this returns the only resource left is the
        # WIMI subprocess itself, terminated next.
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                _logger.warning(
                    "WimiTestSession.stop(): WimiBrowser.close() raised: %s",
                    exc,
                )
            finally:
                self._browser = None

        # Drop the page wrapper reference too. The wrapper holds the tab
        # we just nulled, so keeping it around buys nothing.
        self._page = None

        # 4. WIMI subprocess. ``terminate`` is itself idempotent and
        # never raises, but we still wrap it for symmetry and so a
        # truly unexpected error gets logged here rather than from
        # deep inside the process module.
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                _logger.warning(
                    "WimiTestSession.stop(): subprocess terminate raised: %s",
                    exc,
                )
            finally:
                self._proc = None

        # 5. Test user. Optional per ``drop_user`` so debug flows can
        # keep the user around after stop().
        if drop_user and self._user is not None:
            try:
                self._user.drop()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                _logger.warning(
                    "WimiTestSession.stop(): TestUser.drop() raised: %s",
                    exc,
                )
            finally:
                self._user = None
        elif not drop_user:
            # Keep the user reference so the caller can still poke at it
            # via the ``user`` property — but only if we were started.
            # Otherwise the half-built user is best discarded.
            pass

        # 6. Discard the master DB reference. ``MasterDatabase`` does
        # not require an explicit close; dropping the reference lets
        # the connection close itself when garbage-collected.
        self._master_db = None

        self._started = False
        # ``_start_ts`` is intentionally preserved so post-stop
        # introspection ("when did this session start?") still works.
        # The not-started guard on the property already returns ``None``
        # for the never-started case.

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def page(self) -> WimiPage:
        """The :class:`WimiPage` wrapping the attached CDP tab.

        Raises
        ------
        WimiTestError
            If the session has not been started.
        """
        if not self._started or self._page is None:
            raise WimiTestError("Session not started")
        return self._page

    @property
    def tab(self) -> WimiTab:
        """The underlying :class:`WimiTab` for raw CDP access.

        Escape hatch for scenarios that need direct CDP domain access
        (e.g. ``session.tab.Network.setExtraHTTPHeaders(...)``). Most
        callers should reach for :attr:`page` instead — :class:`WimiPage`
        wraps this tab with WIMI-aware navigation, locator policy, and
        bridge-readiness waits. Replaces the previous ``pw_page``
        accessor (raw page handle) one-for-one.

        Raises
        ------
        WimiTestError
            If the session has not been started.
        """
        if not self._started or self._tab is None:
            raise WimiTestError("Session not started")
        return self._tab

    @property
    def process(self) -> WimiProcess:
        """The :class:`WimiProcess` owning the WIMI subprocess.

        Useful for tests that want to assert against the subprocess's
        captured stdout (``session.process.last_stdout(...)``) or to
        force-terminate independently of :meth:`stop`. The session still
        owns lifecycle — callers should not call ``spawn`` themselves.

        Raises
        ------
        WimiTestError
            If the session has not been started.
        """
        if not self._started or self._proc is None:
            raise WimiTestError("Session not started")
        return self._proc

    @property
    def user(self) -> TestUser:
        """The :class:`TestUser` owning the per-session WIMI account.

        Raises
        ------
        WimiTestError
            If the session has not been started.
        """
        if not self._started or self._user is None:
            raise WimiTestError("Session not started")
        return self._user

    @property
    def captures(self) -> CaptureBundle:
        """The session's capture bundle (console + network + bridge).

        Always non-``None`` for a started session. Aggregates the three
        diagnostic streams attached on :meth:`start`:

        * ``ConsoleCapture`` — Runtime.consoleAPICalled +
          Runtime.exceptionThrown listeners on the WIMI tab.
        * ``NetworkCapture`` — Network.* listeners on the WIMI tab.
        * ``BridgeCapture`` — instrumented ``@pyqtSlot`` calls polled
          from ``window.api.getTestModeBridgeCalls``.

        Used by failure reports (via ``session.captures.flush_all()``
        or ``session.captures.snapshot(since_ts=session.start_ts)``) and
        by the per-test capture fixtures.

        Raises
        ------
        WimiTestError
            If the session has not been started.
        """
        if not self._started or self._captures is None:
            raise WimiTestError("Session not started; captures unavailable")
        return self._captures

    @property
    def start_ts(self) -> Optional[float]:
        """Wall-clock timestamp of :meth:`start`, or ``None`` if unstarted.

        Used by capture snapshots' ``since_ts`` filter — the
        ``screenshot_on_failure`` hook slices each capture buffer to
        events newer than ``session.start_ts`` for per-test segmentation.
        Stamped after the captures attach so every event reachable from
        the test's perspective is included in such a slice.
        """
        return self._start_ts

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "WimiTestSession":
        """Start the session and return ``self``."""
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        """Stop the session, dropping the user (always-safe)."""
        self.stop()
