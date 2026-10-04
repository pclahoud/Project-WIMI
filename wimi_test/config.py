"""Configuration for the WIMI test infrastructure.

`TestConfig` is the single, frozen, dataclass-based configuration object
consumed by every other ``wimi_test.*`` module (process management,
session/page wrapper, capture pipeline, MCP facade). The full field list,
defaults, and rationale live in ``docs/planning/TEST_INFRASTRUCTURE.md``
section 9 (``Configuration``); this module is the executable mirror of
that table.

The default network URL filter behaviour (rejecting ``file://`` and
``qrc://`` prefixes so they are excluded from CDP network capture) is
documented in section 6.2 of the same design doc — those schemes are
noisy and rarely interesting for assertions.

This is a leaf module: it imports nothing from ``wimi_test.*`` and only
uses the standard library (``dataclasses``, ``pathlib``, ``typing``,
``os``, ``re``). Callers compose it with the other modules; it does not
compose anything itself.
"""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional

__all__ = [
    "TestConfig",
    "default_url_filter",
    "warn_if_unresolved",
    "UnresolvedConfigWarning",
]


# Truthy strings recognised by every boolean env-var override below.
_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes"})

# Pattern accepted by ``WIMI_TEST_DEBUG_PORT_RANGE`` (e.g. ``"12000-12100"``).
# Whitespace around the hyphen is tolerated so values like ``"12000 - 12100"``
# pasted from documentation also work.
_PORT_RANGE_PATTERN: re.Pattern[str] = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def default_url_filter(url: str) -> bool:
    """Default predicate for ``TestConfig.network_url_filter``.

    Returns ``True`` for URLs that should be captured by the network
    pipeline and ``False`` for URLs that should be excluded. The default
    drops ``file://`` and ``qrc://`` requests because those schemes are
    used internally by Qt/QtWebEngine for asset loading and produce a
    great deal of noise that is rarely interesting for test assertions.
    HTTP(S) and every other scheme are captured. See
    ``TEST_INFRASTRUCTURE.md`` section 6.2.

    **There is no ``media://`` scheme.** This docstring named one as
    captured until 2026-09-28; the handler was deleted as dead code in
    #140 and nothing ever built such a URL.

    **A WIMI page loads entirely over ``file://``, so on WIMI's own
    pages this predicate rejects everything** — measured at 80 events
    in, 0 out (78 ``file://``, 2 ``qrc://``). That is the filter working,
    not a capture that failed to attach, and the stream carries signal
    only when something fetches remote content (i.e. the browser pane).
    An empty ``get_network_log`` was twice read as a broken capability
    and written up as one (#152, #257). It is not.

    Note the filter runs **on ingest**, inside ``NetworkCapture``'s event
    handlers — not in ``snapshot()``. A rejected event is never buffered,
    so a caller cannot recover ``file://`` traffic afterwards by
    snapshotting differently; construct ``NetworkCapture(url_filter=None)``
    for that, and see the ``set_listener`` overwrite hazard in
    ``capture/network.py`` before attaching a second one to a live tab.
    """
    if url.startswith("file://") or url.startswith("qrc://"):
        return False
    return True


def _parse_bool_env(name: str) -> Optional[bool]:
    """Read a boolean env var; ``None`` if unset, otherwise truthy mapping."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in _TRUTHY


def _parse_int_env(name: str) -> Optional[int]:
    """Read an integer env var; ``None`` if unset; raises ``ValueError`` on bad value."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    return int(raw.strip())


def _parse_port_range_env(name: str) -> Optional[tuple[int, int]]:
    """Parse a ``"<lo>-<hi>"`` env var into a ``(lo, hi)`` tuple.

    Returns ``None`` when the variable is unset. Raises ``ValueError`` if
    the value does not match the expected ``<int>-<int>`` shape.
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    match = _PORT_RANGE_PATTERN.match(raw)
    if not match:
        raise ValueError(
            f"{name} must look like '<lo>-<hi>' (e.g. '12000-12100'); got {raw!r}"
        )
    return int(match.group(1)), int(match.group(2))


def _validate_port_range(value: tuple[int, int]) -> None:
    """Enforce ``lo < hi`` and both endpoints inside the unprivileged range."""
    lo, hi = value
    if not (1024 <= lo <= 65535) or not (1024 <= hi <= 65535):
        raise ValueError(
            f"cdp_port_range endpoints must be in [1024, 65535]; got {value!r}"
        )
    if lo >= hi:
        raise ValueError(
            f"cdp_port_range must satisfy lo < hi; got {value!r}"
        )


def _validate_user_isolation(value: str) -> None:
    """Reject anything outside the two allowed literals for ``test_user_isolation``."""
    if value not in ("session", "test"):
        raise ValueError(
            f"test_user_isolation must be 'session' or 'test'; got {value!r}"
        )


@dataclass(frozen=True)
class TestConfig:
    """Frozen configuration bundle for the WIMI test infrastructure.

    Mirrors the table in ``docs/planning/TEST_INFRASTRUCTURE.md`` section
    9. Construct directly for ad-hoc use, or call :meth:`resolve` to
    layer environment variables and pytest CLI overrides on top of the
    defaults.
    """

    headed: bool = False
    cdp_port_range: tuple[int, int] = (12000, 12100)
    app_data_dir: Path = field(default_factory=lambda: Path("app_data_test"))
    console_buffer_size: int = 10_000
    network_buffer_size: int = 5_000
    bridge_buffer_size: int = 2_000
    fail_on_console_error: bool = False
    fail_on_uncaught_exception: bool = True
    network_url_filter: Callable[[str], bool] = field(
        default_factory=lambda: default_url_filter
    )
    timeout_default_ms: int = 5_000
    timeout_attach_s: int = 30
    allow_eval_js: bool = True
    test_user_isolation: Literal["session", "test"] = "session"
    # Path to a built WIMI executable. ``None`` (the default) spawns
    # ``python run_wimi.py``, which is what every scenario has always
    # done. Set it — or ``WIMI_TEST_BINARY`` — and the whole suite runs
    # against the frozen artifact instead. That was impossible before
    # #137/#138: the binary died on the piped stdout this harness needs
    # and ignored ``--test-mode`` even when it survived, which is why
    # #135's Chromium drift could not be caught by any test.
    wimi_binary: Optional[Path] = None

    #: True only on instances built by :meth:`resolve`. Nothing reads it to
    #: change behaviour -- it exists so a session can tell a config that has
    #: seen the environment from one that has not, and say so (#185).
    #:
    #: A bare ``TestConfig()`` carries pure dataclass defaults, because every
    #: environment variable is read inside ``resolve()``. That made the
    #: *explicit-looking* construction the broken one while omitting ``config=``
    #: entirely worked, which inverts the usual safety gradient: being careful
    #: was the unsafe move. It cost a real investigation -- a probe built with
    #: ``TestConfig()`` silently ignored ``WIMI_TEST_BINARY``, ran the dev
    #: launcher instead of the frozen bundle, and reported a dev path as
    #: evidence of a #138-class frozen-mode defect that did not exist.
    #:
    #: Direct construction stays legal: a unit test wanting hermetic defaults
    #: is a real case, so this warns rather than refuses.
    resolved_from_environment: bool = False

    @classmethod
    def resolve(cls, cli_overrides: Optional[dict] = None) -> "TestConfig":
        """Build a ``TestConfig`` by layering defaults, env vars, and CLI overrides.

        Precedence, lowest to highest:

        1. Dataclass defaults defined on the class itself.
        2. ``WIMI_TEST_*`` environment variables (see module docstring and
           the mapping in ``TEST_INFRASTRUCTURE.md`` section 9).
        3. Entries in ``cli_overrides``, typically supplied by the pytest
           plugin from CLI flags such as ``--wimi-headed``.

        ``network_url_filter`` is intentionally not env-resolvable — it is
        a callable, not a string — and so can only be supplied via
        ``cli_overrides``.

        Raises
        ------
        ValueError
            If any resolved value fails validation (port range bounds or
            the ``test_user_isolation`` literal).
        """
        values: dict = {}

        # --- 2. Environment variables ---------------------------------
        env_headed = _parse_bool_env("WIMI_TEST_HEADED")
        if env_headed is not None:
            values["headed"] = env_headed

        env_app_data = os.environ.get("WIMI_TEST_APP_DATA_DIR")
        if env_app_data is not None:
            values["app_data_dir"] = Path(env_app_data)

        env_port_range = _parse_port_range_env("WIMI_TEST_DEBUG_PORT_RANGE")
        if env_port_range is not None:
            values["cdp_port_range"] = env_port_range

        for env_name, field_name in (
            ("WIMI_TEST_CONSOLE_BUFFER_SIZE", "console_buffer_size"),
            ("WIMI_TEST_NETWORK_BUFFER_SIZE", "network_buffer_size"),
            ("WIMI_TEST_BRIDGE_BUFFER_SIZE", "bridge_buffer_size"),
            ("WIMI_TEST_TIMEOUT_DEFAULT_MS", "timeout_default_ms"),
            ("WIMI_TEST_TIMEOUT_ATTACH_S", "timeout_attach_s"),
        ):
            parsed = _parse_int_env(env_name)
            if parsed is not None:
                values[field_name] = parsed

        for env_name, field_name in (
            ("WIMI_TEST_FAIL_ON_CONSOLE_ERROR", "fail_on_console_error"),
            ("WIMI_TEST_FAIL_ON_UNCAUGHT_EXCEPTION", "fail_on_uncaught_exception"),
            ("WIMI_TEST_ALLOW_EVAL_JS", "allow_eval_js"),
        ):
            parsed_bool = _parse_bool_env(env_name)
            if parsed_bool is not None:
                values[field_name] = parsed_bool

        env_isolation = os.environ.get("WIMI_TEST_USER_ISOLATION")
        if env_isolation is not None:
            values["test_user_isolation"] = env_isolation

        # An empty or whitespace-only value reads as unset rather than as
        # "spawn the empty string" — ``WIMI_TEST_BINARY=`` is how a shell
        # script most naturally turns the switch back off.
        env_binary = os.environ.get("WIMI_TEST_BINARY")
        if env_binary is not None and env_binary.strip():
            values["wimi_binary"] = Path(env_binary.strip())

        # --- 3. CLI overrides (highest priority) ----------------------
        if cli_overrides:
            # Only forward keys that are known fields so a typo surfaces
            # as a TypeError rather than silently dropping the override.
            values.update(cli_overrides)

        # --- Validation ----------------------------------------------
        # Resolve the final port range from values (if set) or the
        # default to validate before constructing the frozen instance.
        port_range = values.get("cdp_port_range", cls.cdp_port_range)
        _validate_port_range(port_range)

        isolation = values.get("test_user_isolation", cls.test_user_isolation)
        _validate_user_isolation(isolation)

        values["resolved_from_environment"] = True
        return cls(**values)


class UnresolvedConfigWarning(UserWarning):
    """A session was handed a ``TestConfig`` that never read the environment."""


def warn_if_unresolved(config: "TestConfig", *, consumer: str) -> None:
    """Warn when a directly-constructed config reaches a live session (#185).

    ``TestConfig()`` is not a lighter ``TestConfig.resolve()``. Every
    environment variable -- ``WIMI_TEST_BINARY`` among them -- is read inside
    ``resolve()``, so a bare construction silently discards all of them and
    the session runs against ``python run_wimi.py`` no matter what the
    environment asked for.

    The failure is maximally deceptive: it does not raise, it does not warn,
    and it yields a *plausible wrong answer* -- a real path to a real binary,
    differing from the expected one in exactly the direction an investigation
    into frozen-mode behaviour would be looking for. One such probe reported a
    dev path as evidence of a #138-class defect that did not exist, and
    invalidated a model-download measurement that had to be redone.

    A warning rather than a refusal, because direct construction is legitimate
    for a unit test wanting hermetic defaults. What is never legitimate is
    handing one to something that spawns a real WIMI.
    """
    if getattr(config, "resolved_from_environment", False):
        return
    warnings.warn(
        f"{consumer} was given a TestConfig built directly, so no environment "
        f"variable was read -- WIMI_TEST_BINARY included. This session will "
        f"spawn `python run_wimi.py` regardless of what the environment asked "
        f"for, and will report dev paths that look like real findings (#185). "
        f"Pass no config at all, or pass TestConfig.resolve(); never "
        f"TestConfig().",
        UnresolvedConfigWarning,
        stacklevel=3,
    )
