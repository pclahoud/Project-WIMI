"""Sync<->async bridge for the `wimi-test` MCP facade.

Per `docs/planning/TEST_INFRASTRUCTURE.md` Section 8 (Threading), three
threads coexist in the test-infrastructure process:

1. **MCP server thread** -- FastMCP's asyncio event loop. Tool handlers
   are ``async def`` and may not block the loop.
2. **Playwright/test-orchestration thread** -- a single dedicated worker
   thread owned by ``SessionRegistry``. Playwright's *sync* API has hard
   thread affinity: every ``Page``, ``Browser``, and ``BrowserContext``
   object must be touched only from the OS thread that created it. All
   Playwright calls -- and, by extension, every `wimi_test.session`
   operation that funnels into Playwright -- run here.
3. **WIMI Qt UI thread** -- inside the WIMI subprocess; we only reach it
   over CDP and never synchronize on it directly.

The synchronization rule is therefore narrow but absolute: **only the
registry's worker thread touches Playwright objects; MCP async handlers
never call Playwright directly**. This module is the one place where
that bridging lives, so the rule has exactly one enforcement point.

`SessionThreadExecutor` wraps a single-worker
``concurrent.futures.ThreadPoolExecutor``. Callers either:

* call :meth:`SessionThreadExecutor.run` from synchronous code (e.g.
  pytest fixtures during teardown) and block until the worker returns,
  or
* ``await`` :meth:`SessionThreadExecutor.run_async` from an asyncio
  handler (e.g. an MCP tool) and yield control to the event loop while
  the worker thread executes.

Pytest itself is single-threaded and does not need this bridge; it
exists for the MCP facade. See Section 8 for the full rationale.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Callable, TypeVar

__all__ = ["SessionThreadExecutor", "make_session_executor"]


T = TypeVar("T")


class SessionThreadExecutor:
    """Single-worker executor that owns the Playwright thread.

    All Playwright (and other thread-affine) calls for a given test
    session must go through one instance of this class. ``max_workers=1``
    guarantees that every submitted callable runs on the same OS thread,
    which is the contract Playwright's sync API requires.

    Usable as a context manager; ``__exit__`` shuts the executor down.
    """

    def __init__(self) -> None:
        self._executor: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="wimi-test-session",
            )
        )
        self._shutdown: bool = False

    def run(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run ``func`` on the worker thread and block until it returns.

        Synchronous form; suitable for non-async callers (pytest setup
        and teardown, CLI helpers). Re-raises any exception raised by
        ``func`` in the calling thread.
        """
        future = self._executor.submit(func, *args, **kwargs)
        return future.result()

    async def run_async(
        self,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Run ``func`` on the worker thread and ``await`` its result.

        Async form for MCP tool handlers. Yields control to the asyncio
        event loop while the worker thread executes ``func``, so other
        coroutines (and incoming JSON-RPC requests) keep making progress.
        Exceptions from ``func`` propagate out of the ``await``.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: func(*args, **kwargs),
        )

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the executor. Idempotent.

        Calling more than once is a no-op so that both explicit teardown
        and the context-manager ``__exit__`` can be wired without fear
        of double-shutdown errors.
        """
        if self._shutdown:
            return
        self._executor.shutdown(wait=wait)
        self._shutdown = True

    def __enter__(self) -> SessionThreadExecutor:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.shutdown()


def make_session_executor() -> SessionThreadExecutor:
    """Construct a fresh single-worker executor for a test session."""
    return SessionThreadExecutor()
