"""Exception hierarchy for the WIMI test library.

Defines the structured error types raised across `wimi_test.*` modules
(process management, locator resolution, capture pipeline, assertions).
Every library exception derives from `WimiTestError`, so callers — pytest
fixtures and the `wimi-test` MCP facade alike — can catch one base class
and translate the failure into a structured response without seeing raw
tracebacks.

See `docs/planning/TEST_INFRASTRUCTURE.md` Section 3 (Module
responsibility matrix) for where each exception is raised and consumed.

This module is a leaf: it imports nothing from `wimi_test.*` and uses the
stdlib only. The `CaptureBundle` reference on
`AssertionFailureWithCapture` is a forward string annotation pointing at
`wimi_test.capture.bundle`, which is implemented in a later phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # Forward-only import so the bundle module can land in a later task
    # without creating a circular dependency at runtime.
    from wimi_test.capture.bundle import CaptureBundle

__all__ = [
    "WimiTestError",
    "ProcessSpawnError",
    "AttachTimeout",
    "LocatorAmbiguous",
    "AssertionFailureWithCapture",
]


class WimiTestError(Exception):
    """Base class for every exception raised by the `wimi_test` library."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message: str = message


class ProcessSpawnError(WimiTestError):
    """Raised when launching the WIMI subprocess fails or it exits early.

    Carries the observed `exit_code` and `last_stdout` (the trailing ~100
    lines captured before exit) so failure reports can show what the
    child process printed before dying.
    """

    def __init__(
        self,
        message: str,
        *,
        exit_code: int,
        last_stdout: list[str],
    ) -> None:
        super().__init__(message)
        self.exit_code: int = exit_code
        self.last_stdout: list[str] = last_stdout


class AttachTimeout(WimiTestError):
    """Raised when CDP attachment to the WIMI subprocess times out.

    `port` is the CDP debug port we were waiting on; `elapsed_s` is how
    long we waited before giving up. `last_stdout` carries the trailing
    stdout lines captured up to the timeout so the failure report can
    show what the child process did or didn't print.
    """

    def __init__(
        self,
        message: str,
        *,
        port: int,
        elapsed_s: float,
        last_stdout: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.port: int = port
        self.elapsed_s: float = elapsed_s
        self.last_stdout: list[str] = list(last_stdout) if last_stdout else []


class LocatorAmbiguous(WimiTestError):
    """Raised when a locator that requires uniqueness matches more than one element.

    `strategy` names the resolution strategy used (e.g. ``"role+name"``,
    ``"testid"``, ``"css"``); `matches` holds short human-readable
    descriptions of every matched element so the test author can
    disambiguate.
    """

    def __init__(
        self,
        message: str,
        *,
        strategy: str,
        matches: list[str],
    ) -> None:
        super().__init__(message)
        self.strategy: str = strategy
        self.matches: list[str] = matches


class AssertionFailureWithCapture(WimiTestError, AssertionError):
    """Assertion failure that carries a `CaptureBundle` for the failure report.

    Inherits from both `WimiTestError` (so the library's catch-all still
    catches it) and `AssertionError` (so pytest treats it as a normal
    failed assertion). The optional `captures` reference is filled in by
    DB-side and UI-side assertion helpers once the capture pipeline
    (Phase 3) is wired up; before then it is `None`.
    """

    def __init__(
        self,
        message: str,
        *,
        captures: "Optional[CaptureBundle]" = None,
    ) -> None:
        super().__init__(message)
        self.captures: "Optional[CaptureBundle]" = captures

    def __str__(self) -> str:
        suffix = " [captures attached]" if self.captures is not None else " [no captures attached]"
        return f"{self.message}{suffix}"
