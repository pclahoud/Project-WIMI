"""Test-mode state and console-buffering ``QWebEnginePage`` subclass.

This module is the always-on "Layer 1" capture for the WIMI test
infrastructure. When the app is launched with ``--test-mode``, ``main.py``
flips ``IS_ACTIVE`` to ``True`` (via :func:`set_active`), installs a
:class:`TestModeQWebEnginePage` on every ``QWebEngineView``, and emits a
machine-readable ready signal to stdout once the QWebChannel bridge is
up. The subclass mirrors every JavaScript ``console.*`` call into a
bounded ring buffer so that a test harness attaching later via CDP still
sees errors that fired during startup, plugin load, or before the test
client connected.

A best-effort :mod:`atexit` hook also dumps the combined buffer to
``<APP_DATA_DIR>/last_crash_console.json`` when the process exits with
an active exception, giving post-mortem visibility into hard crashes
that never reached the per-test capture pipeline.

See ``docs/planning/TEST_INFRASTRUCTURE.md`` Section 5 (``--test-mode``
launch flag, order of operations in ``main.py``) and Section 6.1, "Layer 1
— Python QWebEnginePage subclass (always-on safety net)" for the design
rationale and the contract this module implements.

Module-level state (``IS_ACTIVE``, ``DEBUG_PORT``, ``APP_DATA_DIR``) must
only be mutated through :func:`set_active`; direct assignment is
considered private API.
"""

from __future__ import annotations

import atexit
import collections
import json
import sys
import time
import weakref
from pathlib import Path
from typing import NamedTuple, Optional

from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView

__all__ = [
    "IS_ACTIVE",
    "DEBUG_PORT",
    "APP_DATA_DIR",
    "ConsoleEntry",
    "TestModeQWebEnginePage",
    "set_active",
    "is_active",
    "install_on_view",
    "emit_ready_signal",
    "get_console_buffer",
]


# ---------------------------------------------------------------------------
# Module-level state — mutate only through ``set_active``.
# ---------------------------------------------------------------------------

IS_ACTIVE: bool = False
DEBUG_PORT: Optional[int] = None
APP_DATA_DIR: Optional[Path] = None

# Maximum number of console messages buffered per page instance. 10k is
# generous enough to capture verbose plugin startup chatter without
# unbounded memory growth.
_CONSOLE_BUFFER_MAXLEN: int = 10_000

# WeakSet of every ``TestModeQWebEnginePage`` ever constructed. Used by the
# atexit crash-dump hook to gather the combined buffer across views without
# preventing pages from being garbage-collected when their view goes away.
_known_pages: "weakref.WeakSet[TestModeQWebEnginePage]" = weakref.WeakSet()

# Guard so the atexit hook is registered at most once even if
# ``set_active(True, ...)`` is called repeatedly (defensive — main.py should
# only call it once, but this keeps the contract robust).
_atexit_registered: bool = False

# Guard so the ready signal is emitted at most once. The contract in §5
# says "after bridgeReady" — but if a caller wires it up twice, we don't
# want duplicate lines confusing the parent process.
_ready_signal_emitted: bool = False


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class ConsoleEntry(NamedTuple):
    """A single buffered JavaScript console message.

    Attributes:
        timestamp: ``time.time()`` value at the moment the message arrived.
        level_name: Translated Qt log level — one of ``"info"``,
            ``"warning"``, or ``"error"``.
        message: The console message body as JS produced it.
        line: Source line number reported by Qt (``0`` if unknown).
        source: URL of the source file; typically a ``qrc://``,
            ``file://``, or ``media://`` URL while the app is running.
    """

    timestamp: float
    level_name: str
    message: str
    line: int
    source: str


# Mapping from Qt's enum to a stable lowercase string. Qt6's enum lives at
# ``QWebEnginePage.JavaScriptConsoleMessageLevel`` and has three members.
_LEVEL_NAME_BY_ENUM = {
    QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: "info",
    QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "warning",
    QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: "error",
}


# ---------------------------------------------------------------------------
# QWebEnginePage subclass
# ---------------------------------------------------------------------------


class TestModeQWebEnginePage(QWebEnginePage):
    """``QWebEnginePage`` subclass that buffers every JS console message.

    Each instance owns its own bounded :class:`collections.deque`; the
    crash-dump hook walks every live instance via ``_known_pages`` to
    produce a combined dump. The override always calls ``super()`` after
    appending so Qt's default behavior (forwarding to its log handler) is
    preserved — useful for surfacing errors in dev mode and the F12 dev
    tools console pane alike.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # Per-instance buffer — fresh deque, not shared at the class level.
        self._console_buffer: "collections.deque[ConsoleEntry]" = collections.deque(
            maxlen=_CONSOLE_BUFFER_MAXLEN
        )
        _known_pages.add(self)

    def javaScriptConsoleMessage(  # type: ignore[override]
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line: int,
        source: str,
    ) -> None:
        # Translate Qt's enum into a stable string. Unknown levels (future
        # Qt additions) fall back to ``"info"`` rather than crashing the
        # capture path.
        level_name = _LEVEL_NAME_BY_ENUM.get(level, "info")
        entry = ConsoleEntry(
            timestamp=time.time(),
            level_name=level_name,
            message=message,
            line=line,
            source=source,
        )
        self._console_buffer.append(entry)
        # Preserve default Qt behavior — forward to the parent so things
        # like the dev-tools console and Qt logging keep working.
        super().javaScriptConsoleMessage(level, message, line, source)


# ---------------------------------------------------------------------------
# State setters / accessors
# ---------------------------------------------------------------------------


def set_active(
    active: bool,
    *,
    port: Optional[int] = None,
    app_data_dir: Optional[Path] = None,
) -> None:
    """Set test-mode state coherently.

    When ``active`` is ``True``, both ``port`` and ``app_data_dir`` must be
    provided so dependent subsystems (CDP attach, crash-dump path) have a
    complete picture. When ``active`` is ``False``, the other arguments are
    ignored and module state is reset.

    Also registers the atexit crash-dump hook on the first activation.

    Raises:
        ValueError: If ``active`` is ``True`` but ``port`` or
            ``app_data_dir`` is missing.
    """
    global IS_ACTIVE, DEBUG_PORT, APP_DATA_DIR, _atexit_registered

    if active:
        if port is None or app_data_dir is None:
            raise ValueError(
                "set_active(True, ...) requires both `port` and "
                "`app_data_dir` to be provided"
            )
        IS_ACTIVE = True
        DEBUG_PORT = int(port)
        APP_DATA_DIR = Path(app_data_dir)
        if not _atexit_registered:
            atexit.register(_dump_crash_console_on_exit)
            _atexit_registered = True
    else:
        IS_ACTIVE = False
        DEBUG_PORT = None
        APP_DATA_DIR = None


def is_active() -> bool:
    """Return whether test mode is currently active."""
    return IS_ACTIVE


# ---------------------------------------------------------------------------
# View installation
# ---------------------------------------------------------------------------


def install_on_view(view: QWebEngineView) -> TestModeQWebEnginePage:
    """Replace ``view``'s page with a fresh :class:`TestModeQWebEnginePage`.

    The new page inherits the existing page's ``QWebEngineProfile`` so
    cookies, cache, and the ``media://`` scheme registration carry over.
    Returns the newly installed page so callers can hold a reference to
    its buffer (for example, to expose it via a bridge slot).

    Only meaningful while ``IS_ACTIVE`` is ``True``; calling this when
    test mode is inactive almost certainly indicates a logic error.

    Raises:
        RuntimeError: If called while ``IS_ACTIVE`` is ``False``.
    """
    if not IS_ACTIVE:
        raise RuntimeError(
            "install_on_view() called while test mode is inactive; "
            "call set_active(True, ...) first"
        )
    profile = view.page().profile()
    new_page = TestModeQWebEnginePage(profile, view)
    view.setPage(new_page)
    return new_page


# ---------------------------------------------------------------------------
# Ready signal
# ---------------------------------------------------------------------------


def emit_ready_signal(port: int) -> None:
    """Emit the ``TEST_MODE_READY:port=N`` line on stdout and flush.

    The wimi-test process manager waits for this exact line to know the
    QWebChannel bridge is ready and CDP is accepting connections.
    Idempotent: subsequent calls are no-ops.
    """
    global _ready_signal_emitted
    if _ready_signal_emitted:
        return
    sys.stdout.write(f"TEST_MODE_READY:port={port}\n")
    sys.stdout.flush()
    _ready_signal_emitted = True


# ---------------------------------------------------------------------------
# Buffer access
# ---------------------------------------------------------------------------


def get_console_buffer(page: TestModeQWebEnginePage) -> list[ConsoleEntry]:
    """Return a snapshot copy of ``page``'s console buffer.

    Returns a freshly materialized list rather than the live deque so
    callers can safely iterate without worrying about concurrent
    mutation from the Qt thread.
    """
    return list(page._console_buffer)


# ---------------------------------------------------------------------------
# Crash-dump hook
# ---------------------------------------------------------------------------


def _dump_crash_console_on_exit() -> None:
    """Atexit hook: dump combined console buffer on non-zero exit.

    Wrapped in a broad try/except — this runs during interpreter shutdown
    and must never raise. We treat "process exiting with an active
    exception" as the failure case (``sys.exc_info()`` returns a non-None
    tuple). Normal exits don't write a crash file.
    """
    try:
        if not IS_ACTIVE or APP_DATA_DIR is None:
            return

        exc_type, _exc_val, _exc_tb = sys.exc_info()
        if exc_type is None:
            # Clean exit — no crash dump needed.
            return

        # Aggregate every live page's buffer. Iterate over a list copy
        # because WeakSet iteration is not safe if pages disappear mid-loop.
        combined: list[ConsoleEntry] = []
        for page in list(_known_pages):
            try:
                combined.extend(page._console_buffer)
            except Exception:
                # A page may already be in a partially-finalized state.
                continue

        # Sort by timestamp so multi-view dumps read chronologically.
        combined.sort(key=lambda entry: entry.timestamp)

        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        target = APP_DATA_DIR / "last_crash_console.json"
        with target.open("w", encoding="utf-8") as fh:
            json.dump(
                [entry._asdict() for entry in combined],
                fh,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        # Never let cleanup raise — it would mask the original exception
        # that triggered shutdown and obscure the actual bug.
        pass
