"""Failure-attachment hook for the WIMI test infrastructure.

Implements the autouse pytest hook described in
``docs/planning/TEST_INFRASTRUCTURE.md`` §6.4 ("Failure attachment"): on
every test-call failure, attach a screenshot of the WIMI page plus the
formatted console / network / bridge capture streams to the pytest
report so the human looking at a failed run gets every diagnostic the
session collected, in one place.

Discovery
---------
This module is loaded as part of the ``wimi_test.fixtures`` pytest
plugin (registered via ``pytest_plugins = ["wimi_test.fixtures"]`` from
the project-root ``conftest.py``). Pytest discovers hook implementations
by *name*, so the :func:`pytest_runtest_makereport` function below is
picked up automatically once
:mod:`wimi_test.fixtures.__init__` re-exports it. There is no
``@pytest.fixture(autouse=True)`` decorator in this file — it is a hook,
not a fixture, despite the §6.4 prose calling it "autouse".

Two attachment paths
--------------------
1. **pytest-html present.** Each capture is wrapped in a
   ``pytest_html.extras.image`` / ``pytest_html.extras.text`` payload
   and appended to ``rep.extras``. The HTML report renders the
   screenshot inline and the three log streams as collapsible blocks
   under the failure entry.
2. **pytest-html absent.** We fall through to writing four files under
   ``pytest_artifacts/<sanitized-nodeid>/`` (``screenshot.png``,
   ``console.txt``, ``network.txt``, ``bridge.txt``). The directory is
   created lazily so non-failing runs leave the workspace clean.

Both paths slice every capture stream to ``since_ts=session.start_ts``
so a failed test only carries its *own* events into the report, not
the cumulative session log. This matches the per-test segmentation
contract documented on
:attr:`wimi_test.session.WimiTestSession.start_ts`.

Failure-of-the-failure-hook
---------------------------
Reporting must never crash pytest's reporting. The hook body is wrapped
in a top-level ``try/except Exception`` that demotes any internal error
to a single ``logger.warning`` line. A page that already crashed (so
:meth:`WimiPage.screenshot` raises) likewise falls through to a warning
without breaking the rest of the attachment.

See also
--------
- ``TEST_INFRASTRUCTURE.md`` §4 — :class:`WimiTestSession` API contract.
- ``TEST_INFRASTRUCTURE.md`` §6 — capture pipeline overview.
- ``wimi_test.capture.bundle`` — the ``format_*`` helpers consumed here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pytest

from wimi_test.capture.bundle import format_bridge, format_console, format_network
from wimi_test.session import WimiTestSession

if TYPE_CHECKING:  # pragma: no cover - typing only
    from _pytest.nodes import Item

__all__: list[str] = []
# Pytest discovers ``pytest_runtest_makereport`` by name regardless of
# ``__all__``; we keep the list empty so ``from wimi_test.fixtures.capture
# import *`` only pulls intentional public symbols (which is "none" — the
# hook is consumed by pytest, not by tests).


_logger = logging.getLogger(__name__)

# Maximum length of the directory name derived from a test nodeid. 80 is
# generous enough for "tests/<package>/<file>::<class>::<test_name>"
# while still well under typical filesystem path-segment limits.
_MAX_NODEID_DIR_LEN = 80

# Root for file-write fallback artifacts. Relative to the pytest
# invocation directory, matching how pytest itself resolves
# ``pytest_artifacts`` in §6.4 of the design doc.
_ARTIFACTS_ROOT = Path("pytest_artifacts")


def _get_wimi_session(item: "Item") -> Optional[WimiTestSession]:
    """Return the first :class:`WimiTestSession` found in ``item.funcargs``.

    The hook walks the test function's resolved fixture arguments
    looking for a session instance. Tests that do not depend on
    ``wimi_session`` (e.g. pure unit tests over a database mixin)
    return ``None`` here and the hook short-circuits.

    Multiple sessions per test are unsupported; the first one wins. In
    practice ``wimi_session`` is function-scoped and there is exactly
    one per test, so this never matters — but documenting the choice
    keeps future contributors from being surprised.
    """
    funcargs = getattr(item, "funcargs", None)
    if not funcargs:
        return None
    for value in funcargs.values():
        if isinstance(value, WimiTestSession):
            return value
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Attach captures + screenshot to every failed test-call report.

    Pytest fires ``pytest_runtest_makereport`` three times per test
    (``setup``, ``call``, ``teardown``). We only act on the ``call``
    phase because:

    * ``setup`` failures usually mean the session never started (so
      there is nothing to screenshot);
    * ``teardown`` failures fire *after* the session was torn down
      (``session.captures`` is then unavailable by contract).

    We use ``hookwrapper=True`` so we can read the resolved
    :class:`pytest.TestReport` via ``outcome.get_result()`` after every
    other plugin has had a chance to mutate it. The yield always
    happens — we do nothing on the way *down* — so cooperating plugins
    are unaffected.

    Any exception raised inside this hook is caught and demoted to a
    single warning. A failure to attach diagnostics must never mask the
    underlying test failure.
    """
    outcome = yield
    try:
        rep = outcome.get_result()
        if rep.when != "call" or not rep.failed:
            return

        session = _get_wimi_session(item)
        if session is None:
            return

        # Slice every capture stream to events newer than the session
        # start. Falling back to ``0`` for an unstarted session means
        # ``snapshot()`` yields the entire buffer rather than nothing,
        # which is the more useful failure mode if a test somehow
        # failed before the session timestamp landed.
        since_ts = session.start_ts or 0.0

        # Screenshot. Wrapped tightly because a page that crashed mid-
        # navigation can leave the CDP channel in a state where
        # ``page.screenshot()`` raises or hangs — we still want the
        # log streams. ``timeout_ms=10000`` bounds the RPC; without
        # it a stalled CDP response hangs the entire test runner
        # until pytest-timeout fires, masking the real failure.
        png: Optional[bytes]
        try:
            png = session.page.screenshot(timeout_ms=10000)
        except Exception as exc:  # noqa: BLE001 — diagnostic best-effort
            _logger.warning(
                "pytest_runtest_makereport: screenshot capture raised: %s",
                exc,
            )
            png = None

        # Capture snapshots. Pull a single bundle dict so the three
        # streams come from the same instant; a per-stream snapshot
        # would risk drift if the page is still emitting events.
        try:
            bundle = session.captures.snapshot(since_ts=since_ts)
        except Exception as exc:  # noqa: BLE001 — diagnostic best-effort
            _logger.warning(
                "pytest_runtest_makereport: captures snapshot raised: %s",
                exc,
            )
            bundle = {"console": [], "network": [], "bridge": []}

        console_text = format_console(bundle.get("console", []))
        network_text = format_network(bundle.get("network", []))
        bridge_text = format_bridge(bundle.get("bridge", []))

        # Attachment path A: pytest-html, when available. Lazy-import so
        # the wimi_test plugin has no hard dependency on pytest-html —
        # CI runs that don't generate an HTML report still load this
        # module without ImportError.
        try:
            from pytest_html import extras as html_extras  # type: ignore[import-not-found]
        except ImportError:
            html_extras = None  # type: ignore[assignment]

        if html_extras is not None:
            extras = list(getattr(rep, "extras", None) or [])
            if png is not None:
                extras.append(html_extras.image(png, "screenshot"))
            extras.append(html_extras.text(console_text, "console"))
            extras.append(html_extras.text(network_text, "network"))
            extras.append(html_extras.text(bridge_text, "bridge"))
            rep.extras = extras
            return

        # Attachment path B: file-write fallback. Sanitize the nodeid
        # into a single directory-safe segment, then write four files.
        # The directory is created lazily so passing tests never touch
        # the filesystem here.
        sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", item.nodeid)[
            :_MAX_NODEID_DIR_LEN
        ]
        artifacts_dir = _ARTIFACTS_ROOT / sanitized
        try:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001 — diagnostic best-effort
            _logger.warning(
                "pytest_runtest_makereport: could not create %s: %s",
                artifacts_dir,
                exc,
            )
            return

        if png is not None:
            try:
                (artifacts_dir / "screenshot.png").write_bytes(png)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "pytest_runtest_makereport: screenshot write raised: %s",
                    exc,
                )

        for filename, contents in (
            ("console.txt", console_text),
            ("network.txt", network_text),
            ("bridge.txt", bridge_text),
        ):
            try:
                (artifacts_dir / filename).write_text(contents, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "pytest_runtest_makereport: %s write raised: %s",
                    filename,
                    exc,
                )
    except Exception as exc:  # noqa: BLE001 — never break pytest reporting
        _logger.warning(
            "pytest_runtest_makereport: failure-attachment hook raised: %s",
            exc,
        )
