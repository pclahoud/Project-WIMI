"""
WIMI Launcher — the development entry point.

Run this script from the project root to start the application.

This file is deliberately thin. The command line itself lives in
``src/app/cli.py`` (#138): ``wimi.spec`` and ``wimi_macos.spec`` both
freeze ``src/app/main.py``, so ``run_wimi.py`` is not in the bundle and a
parser defined *here* could never be reached by the shipped binary.
While it was, the frozen build accepted ``--test-mode``, ``--debug-port``
and ``--app-data-dir`` and silently ignored all three. Add a flag to
``app/cli.py``, never to one entry point.

``--test-mcp-server`` is the exception and stays here on purpose: the
``wimi_test_mcp`` facade is development-checkout tooling (``.mcp.json``
launches it) and is excluded from frozen builds, so the frozen entry
point rejects the flag with a message instead of pretending.
"""

import sys
from pathlib import Path

# Get project root and add src to path
project_root = Path(__file__).parent
src_dir = project_root / 'src'

# Add src to path
sys.path.insert(0, str(src_dir))

# Imports below need ``src`` on the path, hence their position.
from app.cli import parse_cli_args  # noqa: E402
from console_encoding import configure_stdio  # noqa: E402


def main() -> int:
    # First, before anything can print: on Windows a redirected stdout
    # encodes with the console codepage and a non-ASCII character raises
    # UnicodeEncodeError from inside print() (#137). Also makes the
    # --test-mcp-server stdio transport below UTF-8 rather than cp1252.
    configure_stdio()

    args = parse_cli_args()

    # --test-mcp-server runs the wimi-test MCP server over stdio. Like
    # --mcp-server, it short-circuits before any QApplication startup so
    # PyQt is never imported in this code path. ``src/`` is already on
    # ``sys.path`` (see top of module), so the lazy import resolves to
    # ``src/wimi_test_mcp/server.py``.
    if args.test_mcp_server:
        from wimi_test_mcp.server import run as run_test_mcp_server
        run_test_mcp_server()
        return 0

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
