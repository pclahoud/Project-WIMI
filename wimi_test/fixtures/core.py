"""Core pytest fixtures for the WIMI test infrastructure.

Implements the fixture catalogue specified in
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 7. Each fixture is the
thin pytest-shaped wrapper around a piece of library state already
implemented in :mod:`wimi_test.config`, :mod:`wimi_test.session`,
:mod:`wimi_test.db.test_user`, :mod:`wimi_test.db.seeders`, and
:mod:`wimi_test.page` — this module composes them into the
test-author-facing surface (``wimi_session``, ``test_user``,
``seeded_user``, capture handles, etc.).

Two custom CLI flags are added by :func:`pytest_addoption`:

* ``--wimi-headed`` — show the WIMI window during tests (default off so
  CI and local pytest runs are non-interactive).
* ``--wimi-keep-app-data`` — skip the session-end teardown of
  ``app_data_test/`` so a debugger can poke at the leftover files
  after a failing run.

The capture handles (``console_log`` / ``network_log`` / ``bridge_log``)
intentionally reach through ``wimi_session.captures.*`` directly. Per
the task spec (T2.8), task T3.8 is being dispatched **in parallel** and
will populate ``WimiTestSession.captures`` with a real ``CaptureBundle``
(today the property returns ``None``). Once both tasks land, the
capture fixtures resolve cleanly; until T3.8 ships, any test that uses
them would see ``AttributeError`` when accessing ``.console`` on
``None`` — that is the expected pre-T3.8 state and is acceptable.

This module also lives behind a pytest plugin entry point: see the
project-root ``conftest.py``'s ``pytest_plugins`` declaration (or, in a
future packaging refactor, the ``pytest11`` entry point in
``pyproject.toml``). Either route loads :mod:`wimi_test.fixtures` as a
plugin so :func:`pytest_addoption` and the fixtures below are picked up
without per-test imports.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path  # noqa: F401  — re-exported for type clarity in fixture bodies
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

import pytest

from wimi_test.config import TestConfig
from wimi_test.db.test_user import TestUser
from wimi_test.session import WimiTestSession

__all__ = [
    "pytest_addoption",
    "wimi_config",
    "wimi_master_db",
    "test_user",
    "seeded_user",
    "wimi_session",
    "wimi_page",
    "console_log",
    "network_log",
    "bridge_log",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The scenario component of a test user's name must match the same
# character class that ``TestUser`` enforces (``[a-zA-Z0-9_-]+``). Pytest
# nodeids contain ``/``, ``:``, ``[``, ``]`` and other punctuation that
# break that pattern, so :func:`_scenario_from_nodeid` sanitises the
# nodeid before handing it off as a scenario name.
_SCENARIO_SANITISER: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9_-]+")

# Scenario names are interpolated into a SQLite filename, so we cap the
# length at a value comfortably below the typical 255-char filesystem
# limit while still leaving room for the ``test_`` prefix and the run-id
# suffix. 40 chars matches the spec in TEST_INFRASTRUCTURE_TASKS T2.8.
_SCENARIO_MAX_LEN: int = 40


def _scenario_from_nodeid(nodeid: str) -> str:
    """Derive a filesystem-safe scenario name from a pytest nodeid.

    Replaces any run of non-``[a-zA-Z0-9_-]`` characters with a single
    underscore, strips any leading/trailing underscores left over from
    that substitution, and truncates to :data:`_SCENARIO_MAX_LEN` chars.
    Returns ``"unknown"`` if the result is empty (e.g. an empty
    nodeid, which should not happen in practice but is cheap to guard).
    """
    cleaned = _SCENARIO_SANITISER.sub("_", nodeid).strip("_")
    if not cleaned:
        return "unknown"
    return cleaned[:_SCENARIO_MAX_LEN]


def _make_run_id() -> str:
    """Generate a unique run-id matching ``[a-zA-Z0-9_-]+``.

    The shape ``"<pid>_<ms-since-epoch>_<8-hex>"`` gives us three
    independent sources of uniqueness — pid (per-process), millisecond
    timestamp (per-process across time), and a uuid4 hex slice (random,
    collision-resistant for tests that fire in the same millisecond).
    Once :mod:`wimi_test._internal.runid` lands, this helper should
    delegate there; until then this inline form satisfies the same
    contract.
    """
    return f"{os.getpid()}_{int(time.time() * 1000)}_{uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register WIMI-specific CLI flags on the pytest parser.

    Two flags are exposed; both default off so non-WIMI test runs and
    CI invocations do not need to know about this plugin:

    * ``--wimi-headed`` — show the WIMI subprocess window during tests
      (forwarded into ``TestConfig.headed`` via the ``cli_overrides``
      kwarg of :meth:`TestConfig.resolve`).
    * ``--wimi-keep-app-data`` — skip the session-scope teardown that
      removes ``app_data_test/``. Useful for post-mortem inspection of
      the per-user databases after a failing test.
    """
    group = parser.getgroup("wimi", "WIMI test infrastructure")
    group.addoption(
        "--wimi-headed",
        action="store_true",
        default=False,
        help=(
            "Show the WIMI window during tests (default off for CI). "
            "Equivalent to setting WIMI_TEST_HEADED=1."
        ),
    )
    group.addoption(
        "--wimi-keep-app-data",
        action="store_true",
        default=False,
        help=(
            "Do not remove app_data_test/ at session end. Useful for "
            "post-mortem inspection of the per-user databases."
        ),
    )


# ---------------------------------------------------------------------------
# Configuration & master DB (session scope)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def wimi_config(request: pytest.FixtureRequest) -> TestConfig:
    """Resolved :class:`TestConfig` (CLI flags layered on env defaults).

    Session-scoped because :class:`TestConfig` is frozen and immutable
    once constructed; resolving once per session is both cheaper and
    semantically correct. Only ``--wimi-headed`` is forwarded as an
    override here — ``--wimi-keep-app-data`` is consumed by the
    :func:`wimi_master_db` teardown directly because it is not a
    ``TestConfig`` field.
    """
    overrides: dict[str, Any] = {}
    if request.config.getoption("--wimi-headed"):
        overrides["headed"] = True
    return TestConfig.resolve(cli_overrides=overrides)


@pytest.fixture(scope="session")
def wimi_master_db(
    wimi_config: TestConfig,
    request: pytest.FixtureRequest,
) -> Iterator[Any]:
    """Session-scoped :class:`MasterDatabase` rooted at the test app dir.

    Yields a fully-initialised master DB so other fixtures (and the
    occasional cross-user test) can create test users against a single
    shared registry. The teardown step removes ``app_data_test/`` once
    the session finishes, unless ``--wimi-keep-app-data`` was passed.

    The :class:`MasterDatabase` import is *lazy* (inside the function
    body) so simply importing this module does not pull in the WIMI
    database stack — keeping the plugin importable in tooling that
    introspects pytest plugins without ``src/`` on ``sys.path``.
    """
    # Lazy import: see docstring. ``database.master_db`` requires
    # ``src/`` on the path, which the project-root ``conftest.py``
    # arranges before pytest collection runs.
    from database.master_db import MasterDatabase

    master = MasterDatabase(data_dir=wimi_config.app_data_dir)
    try:
        yield master
    finally:
        # Drop the app_data_test/ tree unless the user explicitly asked
        # to keep it for debugging. ``ignore_errors=True`` swallows
        # PermissionError on Windows when SQLite -wal/-shm files are
        # still memory-mapped — best-effort is the right semantic here.
        if not request.config.getoption("--wimi-keep-app-data"):
            shutil.rmtree(wimi_config.app_data_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Per-test user (function scope)
# ---------------------------------------------------------------------------


@pytest.fixture
def test_user(
    wimi_master_db: Any,
    request: pytest.FixtureRequest,
) -> Iterator[TestUser]:
    """Fresh :class:`TestUser` for the current test, dropped on teardown.

    The username is derived from the test's nodeid (sanitised) plus a
    pid+timestamp+uuid run-id, so parallel pytest workers and rapid
    repeated runs cannot collide. ``user.drop()`` is idempotent, so
    tests are free to call it themselves for early teardown without
    breaking the fixture's own cleanup.
    """
    scenario = _scenario_from_nodeid(request.node.nodeid)
    run_id = _make_run_id()
    user = TestUser(wimi_master_db, scenario=scenario, run_id=run_id)
    try:
        yield user
    finally:
        user.drop()


@pytest.fixture
def seeded_user(test_user: TestUser) -> Callable[..., TestUser]:
    """Factory: ``seeded_user("minimal")`` returns a seeded :class:`TestUser`.

    Cleanup is delegated to the underlying :func:`test_user` fixture, so
    the seeder factory itself does not need to register a finaliser.
    Extra keyword arguments are forwarded to the seeder verbatim, so
    parameterised seeders (e.g.
    ``seeded_user("polyhierarchy_fixture", dvt_in_pregnancy=True)``)
    work without changes here.
    """

    def _factory(seed_name: str, **seeder_kwargs: Any) -> TestUser:
        # Lazy import keeps the plugin importable in environments
        # where the seeders module's transitive deps (e.g. the
        # USMLE outline file) are unavailable.
        from wimi_test.db.seeders import get_seeder

        seeder = get_seeder(seed_name)
        seeder(test_user.db, **seeder_kwargs)
        return test_user

    return _factory


# ---------------------------------------------------------------------------
# Live WIMI session (function scope)
# ---------------------------------------------------------------------------


@pytest.fixture
def wimi_session(
    wimi_config: TestConfig,
    request: pytest.FixtureRequest,
) -> Iterator[WimiTestSession]:
    """Started :class:`WimiTestSession` for the current test.

    The session creates its *own* :class:`TestUser` internally (see
    :meth:`WimiTestSession.start`), so this fixture is intentionally
    *not* layered on top of the :func:`test_user` fixture — composing
    them would create two test users per test (one orphaned). Tests
    that need just a database with no UI should use ``test_user``;
    tests that need a UI session should use ``wimi_session`` and reach
    the per-session user via ``wimi_session.user``.

    The context-manager form guarantees ``stop()`` runs even if the
    test body raises (Playwright shutdown, subprocess termination, and
    user drop are each wrapped in best-effort try/except inside
    :meth:`WimiTestSession.stop`).
    """
    scenario = _scenario_from_nodeid(request.node.nodeid)
    with WimiTestSession(scenario=scenario, config=wimi_config) as session:
        # Wire the bridge's user_db handle. WimiTestSession.start() no
        # longer does this itself (it was moved out so the MCP registry
        # could run a seeder *before* the bridge was attached). Pytest
        # fixtures don't go through the registry, so the test body
        # would otherwise hit "No user database connected" on every
        # bridge call. Tests that need pre-attach seeding do it via
        # ``session.user.db._ensure_phaseN_schema()`` and direct
        # ``UserDatabase`` writes BEFORE the first ``wimi_page.goto``,
        # which is the same code path the registry's seeder hook uses.
        session.attach_user_db()
        yield session


@pytest.fixture
def wimi_page(wimi_session: WimiTestSession) -> Any:
    """Convenience handle to ``wimi_session.page`` (cleanup delegated)."""
    return wimi_session.page


# ---------------------------------------------------------------------------
# Capture handles (function scope, post-T3.8)
# ---------------------------------------------------------------------------
#
# These three fixtures unwrap the ``CaptureBundle`` exposed on
# ``WimiTestSession.captures`` once T3.8 lands (it is ``None`` until
# then; tests that depend on these fixtures will surface AttributeError
# attribute-access errors pre-T3.8, which is the documented expectation
# in TEST_INFRASTRUCTURE_TASKS.md T2.8).


@pytest.fixture
def console_log(wimi_session: WimiTestSession) -> Any:
    """Live ``ConsoleCapture`` view owned by the session (no own cleanup)."""
    return wimi_session.captures.console


@pytest.fixture
def network_log(wimi_session: WimiTestSession) -> Any:
    """Live ``NetworkCapture`` view owned by the session (no own cleanup)."""
    return wimi_session.captures.network


@pytest.fixture
def bridge_log(wimi_session: WimiTestSession) -> Any:
    """Live ``BridgeCapture`` view owned by the session (no own cleanup)."""
    return wimi_session.captures.bridge


# ---------------------------------------------------------------------------
# Re-exports for static analysers
# ---------------------------------------------------------------------------
#
# Pytest itself discovers fixtures by attribute name once the plugin is
# loaded, so the explicit ``__all__`` above is mainly for IDEs and
# linters that read the public surface from ``__all__`` rather than via
# pytest's collection machinery. The :class:`Optional` import above is
# kept available for downstream subclasses; the rest of the optional
# imports are intentionally narrow per the task contract.

# Silence unused-import warnings for names re-exported via ``__all__``
# for the benefit of tooling that does not understand that pattern.
_ = Optional  # type: ignore[assignment]
