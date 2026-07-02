"""Monotonic per-process run-id generator for test-user names.

Test users created by `wimi_test.db.test_user.TestUser` embed a run id in
their username (e.g. ``test_<scenario>_<runid>``) so that concurrent test
runs do not collide on the master-database `username` UNIQUE constraint.

The id is composed of the OS process id plus a thread-safe monotonic
counter. The counter is process-local and starts at 0 in every fresh
Python process — that is fine, because pairing it with `os.getpid()`
keeps the value globally unique across the universe of test runs that
are alive at any given moment.

See `docs/planning/TEST_INFRASTRUCTURE.md` Section 3 (module
responsibility matrix) for where this helper is consumed.
"""

from __future__ import annotations

import os
import threading

__all__ = ["next_run_id"]


_counter: int = 0
_lock: threading.Lock = threading.Lock()


def next_run_id() -> str:
    """Return a unique run identifier of the form ``'<pid>_<counter>'``.

    Process ID + monotonic counter ensures uniqueness across rapid
    test runs in the same process and across parallel processes.
    Counter is thread-safe via a module-level Lock.
    """
    global _counter
    with _lock:
        _counter += 1
        counter = _counter
    return f"{os.getpid()}_{counter}"
