"""
WIMI Application Entry Point
Run this file to start the WIMI desktop application

Supports both development mode and frozen (PyInstaller) builds.
Use --mcp-server flag to run the embedded MCP server instead of the GUI.

**This file is the frozen entry point.** ``wimi.spec`` and
``wimi_macos.spec`` both name it as the PyInstaller Analysis script, so
in a shipped binary this module is ``__main__`` and ``run_wimi.py`` is
not in the bundle at all. The ``__main__`` block at the bottom therefore
*is* the release build's command line, and it parses through the shared
``app.cli`` the launcher uses — see #138 for what happened when it did
not.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


def get_application_paths():
    """
    Determine correct paths for both development and frozen (compiled) modes.

    Returns:
        tuple: (project_root, src_dir, is_frozen)
    """
    is_frozen = getattr(sys, 'frozen', False)

    if is_frozen:
        # Running as compiled executable (PyInstaller)
        exe_path = Path(sys.executable)
        if sys.platform == 'darwin' and '.app/Contents/MacOS' in str(exe_path):
            # macOS .app bundle: WIMI.app/Contents/MacOS/WIMI
            # Go up 3 levels to the folder containing WIMI.app
            project_root = exe_path.parents[3]
        else:
            # Windows: dist/WIMI/WIMI.exe → parent is dist/WIMI/
            project_root = exe_path.parent
        src_dir = project_root  # In frozen mode, modules are at root level
    else:
        # Running in development mode
        src_dir = Path(__file__).parent.parent
        project_root = src_dir.parent

    return project_root, src_dir, is_frozen


# Get paths and set up imports
project_root, src_dir, IS_FROZEN = get_application_paths()

# Add src directory to Python path BEFORE any imports (only needed in dev mode)
if not IS_FROZEN and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


def _run_mcp_server():
    """Run the embedded MCP server instead of the GUI."""
    from mcp_server import run
    run()
    return 0


def resolve_startup_profile(master_db, UserDatabase, error_logger=None):
    """Decide which profile (if any) to auto-open at launch.

    Rules, in order:
    1. Housekeeping: purge soft-deleted profiles past the grace period
       (failure must never block launch).
    2. ``profiles.always_ask`` setting == 'true'  -> None (show picker).
    3. Valid + active ``profiles.last_used_id``   -> open it.
    4. Exactly one active profile                 -> open it (zero-friction
       upgrade path for existing single-profile installs, e.g. legacy
       demo_user setups).
    5. Otherwise (0 or 2+ active profiles)        -> None (show picker).

    Args:
        master_db: MasterDatabase instance
        UserDatabase: the UserDatabase class (injected to keep this
            function import-light and unit-testable)

    Returns:
        An open UserDatabase, or None when the profile picker should
        be shown instead.
    """
    # Rule 1: housekeeping — never block launch on failure
    try:
        master_db.permanently_delete_expired_users()
    except Exception as exc:
        print(f"Warning: expired-profile cleanup failed: {exc}")

    def _open_profile(user):
        db_path = master_db.ensure_user_database(user.id)
        # error_logger is load-bearing, not decoration: the database layer
        # guards every log call with `if getattr(self, 'error_logger', None)`,
        # so omitting it silently disables ALL database logging.
        # device_id names the MACHINE and must not travel with the
        # profile, so it comes from master's app_settings (#126). The
        # profile uuid is the opposite: it lives in the user database
        # and travels, and master only keeps a re-derived mirror (#129).
        user_db = UserDatabase(
            db_path=db_path,
            user_id=user.id,
            username=user.username,
            error_logger=error_logger,
            device_id=master_db.get_device_id(),
        )
        master_db.touch_user_last_active(user.id)
        try:
            master_db.record_profile_uuid(user.id, user_db.get_profile_uuid())
        except Exception as exc:
            # An un-mirrored id costs a registry lookup, never the launch.
            print(f"Warning: could not mirror profile id: {exc}")
        return user_db

    # Rule 2: explicit "always ask" preference wins
    always_ask = master_db.get_setting('profiles.always_ask')
    if always_ask is not None and always_ask.setting_value == 'true':
        return None

    # Rule 3: last-used profile, if it still exists and is active
    last_used = master_db.get_setting('profiles.last_used_id')
    if last_used is not None:
        try:
            last_used_id = int(last_used.setting_value)
        except (TypeError, ValueError):
            last_used_id = None
        if last_used_id is not None:
            user = master_db.get_user(user_id=last_used_id)
            if user is not None and user.account_status == 'active':
                return _open_profile(user)
            # Stale reference (deleted/suspended user) — fall through.

    # Rule 4: exactly one active profile -> open it without asking
    active_users = master_db.get_all_users(account_status='active')
    if len(active_users) == 1:
        return _open_profile(active_users[0])

    # Rule 5: zero or multiple profiles -> picker
    return None


def main(args: Optional[argparse.Namespace] = None):
    """Main entry point for the application.

    Args:
        args: Parsed CLI arguments, from ``app.cli.parse_cli_args``.
            Both real entry points pass one — ``run_wimi.py`` in
            development and this module's own ``__main__`` block in a
            frozen build. ``None`` is accepted only for programmatic
            callers (tests, ``python -c "from app.main import main"``)
            and means "no flags"; it used to be the *frozen* path, which
            is exactly why every test-mode flag was silently dropped
            from the shipped binary (#138). Do not restore a code path
            that reaches here with ``None`` from a command line.
    """
    # Before anything can print. On Windows a redirected stdout encodes
    # with the console codepage, and a non-ASCII character then raises
    # UnicodeEncodeError from inside print() — which killed the frozen
    # build during startup (#137). The banner below is the first writer,
    # so this has to come first. Import is local because ``src`` only
    # joins ``sys.path`` at module import time, above.
    from console_encoding import configure_stdio
    configure_stdio()

    # Check for MCP server mode before importing GUI dependencies.
    # ``--mcp-server`` is declared in ``app.cli`` so strict parsing
    # accepts it, but the dispatch stays a ``sys.argv`` peek so a
    # programmatic caller passing ``args=None`` behaves as it always has.
    if getattr(args, 'mcp_server', False) or '--mcp-server' in sys.argv:
        return _run_mcp_server()

    # Test-mode flags from the CLI. Default to "off" for a programmatic
    # caller that passed no namespace at all.
    test_mode_active: bool = bool(getattr(args, 'test_mode', False))
    debug_port: Optional[int] = getattr(args, 'debug_port', None)
    app_data_override: Optional[str] = getattr(args, 'app_data_dir', None)

    # ------------------------------------------------------------------
    # Step 1 (per TEST_INFRASTRUCTURE.md §5):
    # Set Qt environment variables BEFORE importing/constructing
    # ``QApplication``. ``QTWEBENGINE_REMOTE_DEBUGGING`` only takes
    # effect if it is in the environment when QtWebEngine initializes.
    # ------------------------------------------------------------------
    if test_mode_active:
        # Defensive: --test-mode + missing port should never happen
        # because app.cli.resolve_test_mode_args fills it in, but if
        # someone calls main() directly with a hand-built namespace we
        # want a loud error rather than passing None to int().
        if debug_port is None:
            raise RuntimeError(
                "main() invoked with test_mode=True but no debug_port; "
                "app.cli.resolve_test_mode_args is responsible for this."
            )
        os.environ['QTWEBENGINE_REMOTE_DEBUGGING'] = str(debug_port)
        # Quiet the noisy ``qt.webenginecontext.info`` category which
        # otherwise pollutes the test parent process's stdout/stderr.
        os.environ['QT_LOGGING_RULES'] = 'qt.webenginecontext.info=false'
        # Keep the renderer producing frames even when nothing is
        # watching. A driven session spends its life behind the terminal
        # that is driving it, and Chromium notices: Windows native
        # occlusion detection marks the window hidden and backgrounds the
        # renderer. Screenshots go through ``Page.captureScreenshot``,
        # which waits for a compositor frame, so a throttled renderer
        # turns a capture into a stall.
        #
        # Belt and braces rather than a fix for anything observed: the
        # stale-frame problem this looks like it addresses was really a
        # detached page (see ``test_mode.install_on_view``), and these
        # flags did nothing for it.
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = ' '.join(filter(None, [
            os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', ''),
            '--disable-features=CalculateNativeWinOcclusion',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-background-timer-throttling',
        ]))

    # ------------------------------------------------------------------
    # Determine paths. In test mode the default app_data root is
    # ``app_data_test/`` to keep regression-test state out of the user's
    # real ``app_data/`` directory. ``--app-data-dir`` overrides both.
    #
    # Resolved BEFORE the GUI imports because ``set_active`` (below) must
    # run before ``app.bridge`` is imported transitively — see the next
    # comment block.
    # ------------------------------------------------------------------
    if app_data_override is not None:
        app_data_dir = Path(app_data_override)
        if not app_data_dir.is_absolute():
            app_data_dir = (project_root / app_data_dir).resolve()
    elif test_mode_active:
        app_data_dir = project_root / 'app_data_test'
    else:
        app_data_dir = project_root / 'app_data'

    app_data_dir.mkdir(parents=True, exist_ok=True)

    # Activate test_mode state BEFORE importing ``app.main_window`` (which
    # transitively imports ``app.bridge`` and every ``bridge_domains/*``
    # mixin). Each ``@instrumented_slot`` evaluates ``test_mode.is_active()``
    # **at decoration time** (per the design in
    # ``src/app/bridge_test_instrumentation.py`` — "zero per-call overhead
    # in production"). If we activate after the import chain, every slot
    # gets unwrapped and the bridge call buffer stays empty for the
    # lifetime of the process.
    if test_mode_active:
        from app import test_mode
        test_mode.set_active(True, port=debug_port, app_data_dir=app_data_dir)

    # Import GUI modules only when running the GUI. Done after the env
    # var assignments above so ``QtWebEngine``'s static initializers
    # see ``QTWEBENGINE_REMOTE_DEBUGGING``, and after ``set_active`` so
    # ``@instrumented_slot`` sees the right state.
    from database import MasterDatabase, UserDatabase
    from app_logging import ErrorLogger
    from app.main_window import run_application
    from app.plugin_manager import PluginManager
    from app import test_mode

    print("=" * 50)
    print("WIMI - What I Missed It")
    print("   Metacognitive Exam Preparation Tool")
    print("=" * 50)
    if IS_FROZEN:
        print("   [Running in compiled mode]")
    else:
        print("   [Running in development mode]")
    if test_mode_active:
        print(f"   [Test mode active - CDP on port {debug_port}]")
    print()

    print(f"App data directory: {app_data_dir}")

    # Initialize error logger
    logs_dir = project_root / 'logs'
    logs_dir.mkdir(exist_ok=True)

    # Use 'production' mode when frozen, 'development' otherwise
    logger_mode = 'production' if IS_FROZEN else 'development'
    error_logger = ErrorLogger(
        mode=logger_mode,
        log_dir=str(logs_dir)
    )
    print(f"Logs directory: {logs_dir}")

    # Initialize master database
    master_db = MasterDatabase(
        data_dir=app_data_dir,
        error_logger=error_logger
    )
    print(f"Master database: {app_data_dir / 'users.db'}")

    # ------------------------------------------------------------------
    # Startup profile resolution. In test mode we keep ``user_db=None``
    # — tests provision their own users via ``TestUser`` and the bridge
    # / MainWindow already handle a null user_db. Otherwise the 5-rule
    # cascade in ``resolve_startup_profile`` decides between auto-opening
    # a profile and showing the profile picker.
    # ------------------------------------------------------------------
    if test_mode.is_active():
        print("[test-mode] Skipping startup profile resolution.")
        user_db = None
    else:
        user_db = resolve_startup_profile(
            master_db, UserDatabase, error_logger=error_logger
        )
    initial_page = 'index.html' if user_db is not None else 'profile_select.html'
    print()

    # Initialize plugin system
    plugins_dir = app_data_dir / 'plugins'
    plugins_dir.mkdir(exist_ok=True)
    plugin_manager = PluginManager(plugins_dir, user_db, error_logger)
    load_results = plugin_manager.load_all()
    loaded_count = sum(1 for v in load_results.values() if v)
    print(f"Plugins directory: {plugins_dir} ({loaded_count} loaded)")

    # Run the application
    print("Starting WIMI application...")
    if not IS_FROZEN:
        # F5 binding lives in src/app/main_window.py and is intentionally
        # not rebound here — the task scope forbids modifying that file.
        # Disabling the F5 reload-during-test footgun is deferred (see
        # TEST_INFRASTRUCTURE.md §5 "What test mode disables / changes").
        # Likewise the 1280×800 window-size clamp and the
        # ``setTestModeAutoDismiss`` bridge slot are deferred.
        print("   Press F5 to reload the page")
        print("   Press F12 for developer tools")
    print()

    # Disable dev mode features in production builds
    dev_mode = not IS_FROZEN

    if test_mode.is_active():
        # In test mode we replicate ``run_application`` inline so we can
        # interpose between MainWindow construction and the Qt event
        # loop: install the TestModeQWebEnginePage (so JS console
        # buffering starts before the first page load) and emit the
        # machine-readable ready signal once the QWebChannel bridge is
        # registered. ``main_window.py`` is intentionally left untouched.
        return _run_test_mode(
            master_db=master_db,
            user_db=user_db,
            dev_mode=dev_mode,
            app_data_dir=app_data_dir,
            plugin_manager=plugin_manager,
            debug_port=debug_port,
        )

    # Without this MainWindow falls through to `error_logger or
    # ErrorLogger(...)` and mints a SECOND logger with its own file, so
    # database and plugin records land in one file and bridge records in
    # another.
    exit_code = run_application(
        master_db=master_db,
        user_db=user_db,
        dev_mode=dev_mode,
        app_data_dir=app_data_dir,
        plugin_manager=plugin_manager,
        initial_page=initial_page,
        error_logger=error_logger
    )

    return exit_code


def _run_test_mode(
    *,
    master_db,
    user_db,
    dev_mode: bool,
    app_data_dir: Path,
    plugin_manager,
    debug_port: int,
) -> int:
    """Replicate ``run_application``'s flow with test-mode hooks.

    Mirrors the body of ``app.main_window.run_application`` so we can
    install :class:`TestModeQWebEnginePage` before the first URL load and
    emit ``TEST_MODE_READY:port=<N>`` after the QWebChannel bridge is
    in place. Kept structurally close to the original to make future
    drift easy to spot.
    """
    from PyQt6.QtWidgets import QApplication

    from app import APP_VERSION, test_mode
    from app.main_window import MainWindow, _auto_start_mcp_server

    app = QApplication(sys.argv)
    app.setApplicationName('WIMI')
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName('Project WIMI')

    window = MainWindow(
        master_db=master_db,
        user_db=user_db,
        dev_mode=dev_mode,
        app_data_dir=app_data_dir,
        plugin_manager=plugin_manager,
    )

    # Install the buffering page subclass before ``window.show()`` so
    # the ring buffer captures every console message starting with the
    # very first page load. ``MainWindow.__init__`` has already created
    # the channel, registered objects on it, and called ``setUrl`` for
    # ``index.html`` against the original ``WIMIWebPage``. ``setPage``
    # below replaces that page, which detaches the channel and discards
    # the in-flight load request — so we must re-attach the channel and
    # re-issue the navigation against the new page.
    test_page = test_mode.install_on_view(window.web_view)
    # Re-attach the existing QWebChannel to the new page — ``setPage``
    # detached it. Without this the JS bridge never wires up.
    test_page.setWebChannel(window.channel)
    # The original ``WIMIWebPage`` also forwarded download requests; do
    # the same for the test-mode page so file-export flows still work.
    test_page.profile().downloadRequested.connect(window._handle_download)
    # Hold a reference on the window so the page outlives this function.
    window.web_page = test_page
    # Re-issue the initial navigation now that the new page is current.
    window.load_page('index.html')

    window.show()

    _auto_start_mcp_server(window)

    # Bridge readiness: ``MainWindow._setup_web_channel`` has already
    # registered the bridge object with the channel by the time
    # ``__init__`` returns. The QWebChannel object itself is reachable
    # via CDP as soon as the page finishes loading. We emit the ready
    # signal here — Playwright's CDP attach is the gating condition for
    # the test parent process, and that endpoint is up the moment the
    # Qt event loop starts servicing the remote-debugging port.
    test_mode.emit_ready_signal(debug_port)

    return app.exec()


def _entry_point() -> int:
    """Parse this process's command line and run the app.

    **This is the shipped binary's entry point**, not a fallback:
    ``wimi.spec:91`` and ``wimi_macos.spec:91`` freeze
    ``src/app/main.py``, so a frozen WIMI never executes ``run_wimi.py``
    and never saw the parser that used to live there. What stood here
    was ``sys.exit(main())`` — no arguments — so ``--test-mode``,
    ``--debug-port`` and ``--app-data-dir`` were read off a ``None``
    namespace by ``getattr(..., default)`` and dropped without a word:
    the CDP port never opened, and a caller pointing the binary at a
    scratch directory quietly got the real ``app_data/`` instead (#138).

    Parsing goes through ``app.cli``, the same module ``run_wimi.py``
    uses, so the flag surface and the 12000-12100 port validation cannot
    fork between the launcher and the artifact users actually get.
    """
    # Before argparse, which writes usage and errors to the streams.
    from console_encoding import configure_stdio
    configure_stdio()

    from app.cli import parse_cli_args

    args = parse_cli_args()

    if args.test_mcp_server:
        # Development-checkout tooling: ``wimi_test_mcp`` is excluded
        # from frozen builds (it drives WIMI, it does not ship inside
        # it). Say so rather than repeat #138's accept-and-ignore.
        sys.stderr.write(
            "error: --test-mcp-server is only available from the "
            "development checkout: python run_wimi.py --test-mcp-server\n"
        )
        return 2

    return main(args)


if __name__ == '__main__':
    sys.exit(_entry_point())
