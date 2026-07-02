"""
WIMI Launcher
Run this script from the project root to start the application
"""

import argparse
import socket
import sys
from pathlib import Path

# Get project root and add src to path
project_root = Path(__file__).parent
src_dir = project_root / 'src'

# Add src to path
sys.path.insert(0, str(src_dir))

# Default CDP debug-port range. Mirrors the default in
# ``wimi_test/config.py``'s ``TestConfig.cdp_port_range``. Kept as a module
# constant so the validation message and the auto-pick loop never drift.
_DEBUG_PORT_RANGE: tuple[int, int] = (12000, 12100)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser.

    All flags are optional. The ``--mcp-server`` flag is intentionally not
    declared here — ``src/app/main.py`` peeks at ``sys.argv`` for it
    before any GUI imports so the MCP server can be launched without
    pulling in PyQt. Likewise we leave any unknown args alone via
    ``parse_known_args`` so the existing ``--mcp-server`` flow is
    undisturbed.
    """
    parser = argparse.ArgumentParser(
        prog="run_wimi",
        description="WIMI launcher (desktop GUI by default).",
        # We use parse_known_args at call sites so unknown flags
        # (e.g. --mcp-server, future Qt flags) survive untouched.
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
            f"(must be in [{_DEBUG_PORT_RANGE[0]}, {_DEBUG_PORT_RANGE[1]}]; "
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
        "--test-mcp-server",
        action="store_true",
        help=(
            "Run as the wimi-test MCP server (placeholder; lands in "
            "Phase 5 / T5.9)."
        ),
    )
    return parser


def _pick_free_port(port_range: tuple[int, int]) -> int:
    """Return the first port in ``port_range`` that we can bind on 127.0.0.1.

    Sockets are opened with ``SO_REUSEADDR`` not set so a successful bind
    is a strong signal the port is genuinely free. Each socket is closed
    immediately after the probe — there is an inherent TOCTOU window
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


def _resolve_test_mode_args(args: argparse.Namespace) -> argparse.Namespace:
    """Validate and finalize test-mode CLI inputs.

    Mutates the namespace in place (``args.debug_port`` may be set to an
    auto-picked value) and returns it for chaining.
    """
    if not args.test_mode:
        return args

    lo, hi = _DEBUG_PORT_RANGE
    if args.debug_port is not None:
        if not (lo <= args.debug_port <= hi):
            raise SystemExit(
                f"error: --debug-port {args.debug_port} is outside the "
                f"allowed range [{lo}, {hi}]."
            )
    else:
        args.debug_port = _pick_free_port(_DEBUG_PORT_RANGE)

    return args


def main() -> int:
    parser = _build_arg_parser()
    # parse_known_args so flags handled elsewhere (notably --mcp-server,
    # which main.py peeks at directly) pass through cleanly.
    args, _unknown = parser.parse_known_args()

    # --test-mcp-server runs the wimi-test MCP server over stdio. Like
    # --mcp-server, it short-circuits before any QApplication startup so
    # PyQt is never imported in this code path. ``src/`` is already on
    # ``sys.path`` (see top of module), so the lazy import resolves to
    # ``src/wimi_test_mcp/server.py``.
    if args.test_mcp_server:
        from wimi_test_mcp.server import run as run_test_mcp_server
        run_test_mcp_server()
        return 0

    args = _resolve_test_mode_args(args)

    # Import after argparse so a bad CLI invocation doesn't drag in PyQt.
    from app.main import main as app_main

    return app_main(args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except NotImplementedError as exc:
        # Match the contract: --test-mcp-server should exit with code 2
        # and a clear stderr message rather than a Python traceback.
        sys.stderr.write(f"error: {exc}\n")
        sys.exit(2)
