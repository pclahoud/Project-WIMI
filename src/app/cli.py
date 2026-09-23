"""The one command-line surface for WIMI (#138).

WIMI has two entry points and they must accept exactly the same flags:

* ``run_wimi.py`` at the repository root — what a developer runs, and
  what ``wimi_test.process.WimiProcess`` spawns.
* ``src/app/main.py`` — what ``wimi.spec`` / ``wimi_macos.spec`` name as
  the PyInstaller Analysis entry, so in a frozen build *this* file is
  ``__main__`` and ``run_wimi.py`` is not even in the bundle.

Before #138 the parser lived in ``run_wimi.py`` alone and ``main.py``'s
``__main__`` block called ``main()`` with no arguments. Frozen,
``--test-mode``, ``--debug-port`` and ``--app-data-dir`` were therefore
read off a ``None`` namespace by ``getattr(..., default)`` and silently
dropped: the debug port never opened, and a caller pointing the binary at
a scratch directory quietly got the default instead. A shipped binary
that accepts a flag and ignores it is worse than one that rejects it.

The fix is this module, not a second parser. Both entry points call
:func:`parse_cli_args`, so the flag definitions, the 12000-12100 debug
port validation and the free-port auto-pick cannot fork between the
launcher and the artifact users actually get.

Unknown flags are an **error**, by :func:`argparse.ArgumentParser.parse_args`
rather than ``parse_known_args``. That is the same reasoning one level
down: a typo in ``--app-data-dirr`` used to be swallowed and the run
silently used the real ``app_data/``. ``--mcp-server`` is declared here
for that reason too — it is dispatched by a ``sys.argv`` peek inside
``app.main.main`` before any GUI import, but it still has to be a flag
the parser knows about or strict parsing would reject it.

This module deliberately imports nothing from ``app`` and nothing from
PyQt, so a bad command line fails before the GUI stack is dragged in.

Release builds refuse test mode (#144)
--------------------------------------
``--test-mode`` starts a Chromium remote debugger, and Qt adds
``--remote-allow-origins=*`` to it. The owner decided (2026-09-22) that a
**release** build never accepts it, and that testing uses a separate
**test build** instead. Both are made from the same spec; the test build
adds one PyInstaller runtime hook (``packaging/rthook_test_build.py``) that
sets ``sys._wimi_test_build``. A release bundle has no such hook, so no
environment variable, flag or argument can enable test mode in it -- only
rebuilding it can. A development run (not frozen) is never gated: the
harness spawns ``run_wimi.py`` and must keep working.

The gate lives here, not in an entry point, for #138's reason: one
parser, so the launcher and the artifact cannot disagree about which
flags exist.
"""

from __future__ import annotations

import argparse
import socket
import sys
from typing import Optional, Sequence

__all__ = [
    "DEBUG_PORT_RANGE",
    "TEST_BUILD_MARKER",
    "test_mode_allowed",
    "build_arg_parser",
    "pick_free_port",
    "resolve_test_mode_args",
    "parse_cli_args",
]


# Default CDP debug-port range. Mirrors the default in
# ``wimi_test/config.py``'s ``TestConfig.cdp_port_range``. Kept as a module
# constant so the validation message and the auto-pick loop never drift.
DEBUG_PORT_RANGE: tuple[int, int] = (12000, 12100)

#: Set on ``sys`` by the test build's runtime hook, and by nothing else.
TEST_BUILD_MARKER = "_wimi_test_build"

#: Flags that start or configure the remote debugger. ``--app-data-dir`` is
#: not one of them: pointing a release binary at another data folder opens
#: nothing, and is useful for support.
_DEBUGGER_FLAGS = ("--test-mode", "--debug-port")


def test_mode_allowed() -> bool:
    """May this process start test mode? (#144)

    A development run always may. A frozen build only if it is a test
    build -- that is, only if the test build's runtime hook ran.
    """
    if not getattr(sys, "frozen", False):
        return True
    return bool(getattr(sys, TEST_BUILD_MARKER, False))


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the one WIMI CLI parser.

    ``prog`` is left to argparse, which derives it from ``sys.argv[0]``:
    usage text then reads ``run_wimi.py`` from the checkout and ``WIMI``
    from the frozen binary, which is what each caller actually types.
    """
    parser = argparse.ArgumentParser(
        description="WIMI - What I Missed It (desktop GUI by default).",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help=(
            "Enable test mode: CDP remote debugging, isolated app_data, "
            "no demo user, ready signal on stdout."
        ),
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=None,
        help=(
            "CDP port to use when --test-mode is set "
            f"(must be in [{DEBUG_PORT_RANGE[0]}, {DEBUG_PORT_RANGE[1]}]; "
            "default: auto-pick a free port from the range)."
        ),
    )
    parser.add_argument(
        "--app-data-dir",
        type=str,
        default=None,
        help=(
            "Override the app_data directory. In test mode the default is "
            "'app_data_test/' instead of 'app_data/'."
        ),
    )
    parser.add_argument(
        "--mcp-server",
        action="store_true",
        help=(
            "Run the embedded MCP server instead of the GUI. Dispatched by "
            "a sys.argv peek in app.main before any GUI import; declared "
            "here so strict parsing accepts it."
        ),
    )
    parser.add_argument(
        "--test-mcp-server",
        action="store_true",
        help=(
            "Run as the wimi-test MCP server over stdio. Development "
            "checkout only - the facade is not bundled into frozen builds."
        ),
    )
    return parser


def pick_free_port(port_range: tuple[int, int] = DEBUG_PORT_RANGE) -> int:
    """Return the first port in ``port_range`` that we can bind on 127.0.0.1.

    Sockets are opened with ``SO_REUSEADDR`` not set so a successful bind
    is a strong signal the port is genuinely free. Each socket is closed
    immediately after the probe - there is an inherent TOCTOU window
    between this probe and Qt's bind, but in practice the range is wide
    enough that collisions are rare.
    """
    lo, hi = port_range
    for port in range(lo, hi + 1):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        finally:
            s.close()
        return port
    raise RuntimeError(
        f"No free port available in range [{lo}, {hi}] for --test-mode CDP."
    )


def resolve_test_mode_args(args: argparse.Namespace) -> argparse.Namespace:
    """Validate and finalize test-mode CLI inputs.

    Mutates the namespace in place (``args.debug_port`` may be set to an
    auto-picked value) and returns it for chaining.
    """
    if not args.test_mode:
        return args

    lo, hi = DEBUG_PORT_RANGE
    if args.debug_port is not None:
        if not (lo <= args.debug_port <= hi):
            raise SystemExit(
                f"error: --debug-port {args.debug_port} is outside the "
                f"allowed range [{lo}, {hi}]."
            )
    else:
        args.debug_port = pick_free_port(DEBUG_PORT_RANGE)

    return args


def parse_cli_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse ``argv`` (default ``sys.argv[1:]``) into a resolved namespace.

    The single call every entry point makes. Raises ``SystemExit`` on an
    unknown flag, on ``--help``, and on a ``--debug-port`` outside the
    allowed range.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if (args.test_mode or args.debug_port is not None) and not test_mode_allowed():
        # parser.error: usage plus "error: ..." on stderr, exit status 2 --
        # the same shape as any other refused flag.
        parser.error(
            f"{' / '.join(_DEBUGGER_FLAGS)} are not available in a release build. "
            "Test mode starts a remote debugger, so it only exists in a test "
            "build: build_windows.bat test, or ./build_macos.sh test (#144)."
        )
    return resolve_test_mode_args(args)
