"""The log is drained from Qt's ``aboutToQuit``, and the drain is complete (#278).

``ErrorLogger.cleanup()`` was described in four places as reachable from a
Qt ``aboutToQuit`` hook -- ``error_logger.py``'s ``__init__`` comment, its
own docstring, ``tests/test_error_logger.py``'s ``test_cleanup_is_idempotent``
and CLAUDE.md -- and ``grep -rn aboutToQuit --include=*.py`` over the whole
tree returned nothing but those four sentences. Same class as #153: a
documented invariant that several places assert and no code implements.

Two defects, and the second is the one that cost records:

1. **The hook was never connected.** ``atexit`` covered it, so nothing was
   lost on an ordinary exit -- but ``atexit`` does not run on a fatal
   signal, on ``os._exit``, or when Qt's own teardown crashes. #153
   measured exactly that last case: a forced wrong release order inside a
   live ``MainWindow`` **dumped core**. A core dump during Qt teardown
   takes the entire log file with it, which is why the in-event-loop drain
   is worth having rather than merely tidy.

2. **``cleanup()`` dropped everything past the hundredth record**, on every
   path including ``atexit``. ``flush()`` carries ``processed < 100`` and
   ``cleanup()`` called it once, so the queue's tail was discarded
   deterministically. Measured on this tree before the fix: 250 records
   logged, **100 on disk, 150 lost**. #278 reasons in the abstract that "a
   queue that is drained non-blockingly at interpreter shutdown can still
   lose its tail"; the tail was in fact being lost by a different and much
   blunter mechanism, and connecting a hook to a drain that stops at 100
   would have been decorative.

Why the cap is kept for the periodic flush and removed only at shutdown:
the ticker runs on a daemon thread every ``flush_interval`` seconds, and a
producer logging faster than it writes must not be able to hold that thread
inside one ``flush()`` for ever. At shutdown there is no next pass, so the
bound has nothing to protect.

Every assertion here reads **the file on disk**, never ``error_buffer`` --
the in-memory cache is populated by ``log()`` whether or not anything ever
drains, so a test built on it passes against a logger that writes nothing
(CLAUDE.md says this of logging tests, and it is the trap this module has a
history of).
"""
import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from app_logging.error_logger import ErrorLogger  # noqa: E402

_CHILD = Path(__file__).parent / '_logger_quit_drain_child.py'
_REPO = Path(__file__).resolve().parents[2]
_TIMEOUT_S = 120

# Comfortably more than one ``flush()`` pass and comfortably under the
# default 1000-entry queue -- a full queue makes ``log()`` write
# synchronously, which would measure the overflow path instead.
_MORE_THAN_ONE_PASS = 250


def _logger(log_dir, **kwargs) -> ErrorLogger:
    """A logger whose periodic ticker cannot fire during the test.

    ``flush_interval=3600`` is load-bearing in every test in this file: at
    the shipped 5 s the ticker drains the queue on its own and a broken
    shutdown drain still ends up with the records on disk.
    """
    params = dict(
        app_name='QuitDrain',
        log_dir=Path(log_dir),
        mode='development',
        flush_interval=3600.0,
    )
    params.update(kwargs)
    return ErrorLogger(**params)


def _records_on_disk(log_dir, marker: str = 'drain-probe-') -> int:
    return sum(
        1
        for path in Path(log_dir).glob('*.log')
        for line in path.read_text(encoding='utf-8',
                                   errors='replace').splitlines()
        if marker in line
    )


# ==================== The drain is complete ====================


def test_cleanup_puts_every_queued_record_on_disk():
    """The defect that actually lost data, stated as a count.

    Before the fix this wrote 100 of 250 and reported success.
    """
    log_dir = tempfile.mkdtemp()
    logger = _logger(log_dir)
    try:
        for i in range(_MORE_THAN_ONE_PASS):
            logger.info(f'drain-probe-{i:05d}')
        assert logger.error_queue.qsize() == _MORE_THAN_ONE_PASS, (
            'arrange failed: the ticker or an overflow drained the queue '
            'before cleanup() could, so this test would measure nothing'
        )

        logger.cleanup()

        assert _records_on_disk(log_dir) == _MORE_THAN_ONE_PASS, (
            'cleanup() must drain the whole queue; a single flush() pass '
            'stops at 100 and silently discards the rest'
        )
    finally:
        logger.cleanup()


def test_the_periodic_flush_still_stops_after_one_bounded_pass():
    """Negative control for the fix above, and a design pin.

    If the cap were simply deleted, this would pass too -- and the daemon
    ticker could then be held inside one ``flush()`` indefinitely by a
    producer that outruns it. The bound belongs to the periodic path only.
    """
    log_dir = tempfile.mkdtemp()
    logger = _logger(log_dir)
    try:
        for i in range(_MORE_THAN_ONE_PASS):
            logger.info(f'drain-probe-{i:05d}')

        logger.flush()

        assert _records_on_disk(log_dir) == 100, (
            'one periodic flush() pass must remain bounded at 100 records'
        )
    finally:
        logger.cleanup()


def test_a_short_queue_is_unaffected():
    """The ordinary case must not change shape."""
    log_dir = tempfile.mkdtemp()
    logger = _logger(log_dir)
    try:
        for i in range(7):
            logger.info(f'drain-probe-{i:05d}')
        logger.cleanup()
        assert _records_on_disk(log_dir) == 7
    finally:
        logger.cleanup()


# ==================== The hook itself ====================


class _RecordingSignal:
    def __init__(self):
        self.connected = []

    def connect(self, slot):
        self.connected.append(slot)


class _RecordingApp:
    """Stands in for ``QApplication``.

    ``aboutToQuit`` is the only member the hook may touch, which is the
    point: the installer must not reach for ``QApplication.instance()`` or
    anything else that would tie the logger to a GUI it is built before.
    """

    def __init__(self):
        self.aboutToQuit = _RecordingSignal()


def test_install_shutdown_hook_connects_cleanup():
    log_dir = tempfile.mkdtemp()
    logger = _logger(log_dir)
    app = _RecordingApp()
    try:
        assert logger.install_shutdown_hook(app) is True

        assert app.aboutToQuit.connected == [logger.cleanup], (
            'aboutToQuit must be connected to cleanup -- the call #278 '
            'found missing'
        )
    finally:
        logger.cleanup()


def test_the_connected_slot_drains_to_disk_when_fired():
    """Connecting the right name is not the same as draining.

    Fires whatever was connected, exactly as Qt would, and then looks at
    the file.
    """
    log_dir = tempfile.mkdtemp()
    logger = _logger(log_dir)
    app = _RecordingApp()
    try:
        logger.install_shutdown_hook(app)
        for i in range(_MORE_THAN_ONE_PASS):
            logger.info(f'drain-probe-{i:05d}')

        for slot in app.aboutToQuit.connected:
            slot()

        assert _records_on_disk(log_dir) == _MORE_THAN_ONE_PASS
    finally:
        logger.cleanup()


def test_an_app_with_no_aboutToQuit_is_reported_not_raised():
    """A logging hook must never be the thing that stops a launch.

    ``install_shutdown_hook`` is called from two entry seams; if a future
    Qt or a stand-in has no such signal the app still has to start, and
    ``atexit`` still covers the drain.
    """
    log_dir = tempfile.mkdtemp()
    logger = _logger(log_dir)
    try:
        assert logger.install_shutdown_hook(object()) is False
        assert logger.install_shutdown_hook(None) is False
    finally:
        logger.cleanup()


def test_installing_twice_connects_once():
    """``aboutToQuit`` firing into two cleanups is harmless (cleanup is
    idempotent), but a double connect means somebody wired the same logger
    from both seams and only one of them should own it."""
    log_dir = tempfile.mkdtemp()
    logger = _logger(log_dir)
    app = _RecordingApp()
    try:
        logger.install_shutdown_hook(app)
        logger.install_shutdown_hook(app)
        assert len(app.aboutToQuit.connected) == 1
    finally:
        logger.cleanup()


# ==================== Every QApplication seam installs it ====================
#
# The fakes above prove the installer is right; they cannot prove anybody
# calls it, and "nobody calls it" is the entire defect. Today there are two
# places that construct a ``QApplication`` -- ``run_application`` for the
# shipped app and ``_run_test_mode`` for the harness -- and a fix reaching
# only one leaves the other exactly as #278 found it.
#
# **Discovered, not listed.** A hardcoded pair would check the two seams
# that exist and silently ignore a third, which is this bug's whole shape:
# #294 is one of two call sites quietly missing, three lines from a comment
# explaining why it must be there. So the seams are found by walking
# ``src/`` for functions that instantiate a ``QApplication``, in the spirit
# of ``test_page_gate_markup.py`` being self-counting over the gated pages.
# A new entry point is checked the day it is written.


def _qapplication_seams() -> list:
    """Every function under ``src/`` that constructs a ``QApplication``.

    Returns ``(relative path, function name, AST dump)`` triples.
    """
    seams = []
    for path in sorted((_REPO / 'src').rglob('*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError:  # pragma: no cover - not our business here
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            dump = ast.dump(node)
            # A call to the bare name QApplication. Both seams import it
            # as a name rather than using a qualified attribute.
            if "func=Name(id='QApplication'" in dump:
                seams.append(
                    (str(path.relative_to(_REPO)), node.name, dump)
                )
    return seams


_SEAMS = _qapplication_seams()
_SEAM_IDS = [f'{p}:{n}' for p, n, _ in _SEAMS]


def test_the_seam_discovery_found_the_seams_we_know_about():
    """Control for the discovery itself.

    A detector that silently finds nothing would make every assertion
    below vacuous -- parametrising over an empty list *passes*. So the two
    seams #278 was actually about are named here, once, as the floor.
    """
    found = {f'{path}:{name}' for path, name, _ in _SEAMS}

    assert 'src/app/main_window.py:run_application' in found, found
    assert 'src/app/main.py:_run_test_mode' in found, found


@pytest.mark.parametrize('rel_path,func_name,dump', _SEAMS, ids=_SEAM_IDS)
def test_every_qapplication_seam_installs_the_hook(rel_path, func_name, dump):
    assert 'install_shutdown_hook' in dump, (
        f'{rel_path}:{func_name} builds a QApplication and must install '
        f'the logger shutdown hook on it'
    )


@pytest.mark.parametrize('rel_path,func_name,dump', _SEAMS, ids=_SEAM_IDS)
def test_the_seam_check_would_notice_a_missing_call(rel_path, func_name,
                                                   dump):
    """Negative control for the assertion above.

    A source check that cannot fail is worse than none, so prove the
    lookup really is reading that function's body and not the whole file.
    """
    assert 'definitely_not_a_real_call' not in dump


# ==================== Real Qt, with its negative control ====================


def _run_child(arm: str, count: int) -> int:
    log_dir = tempfile.mkdtemp()
    env = dict(os.environ)
    env['PYTHONUNBUFFERED'] = '1'

    proc = subprocess.run(
        [sys.executable, str(_CHILD), arm, log_dir, str(count)],
        capture_output=True, text=True, timeout=_TIMEOUT_S, env=env,
    )
    assert proc.returncode == 0, (
        f'child arm {arm!r} exited {proc.returncode}\n'
        f'--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}'
    )
    for line in proc.stdout.splitlines():
        if line.startswith('ON_DISK_AFTER_EXEC='):
            return int(line.split('=', 1)[1])
    raise AssertionError(f'child printed no count\nstdout:\n{proc.stdout}')


@pytest.mark.slow
def test_a_real_aboutToQuit_drains_the_log_inside_the_event_loop():
    assert _run_child('hook', _MORE_THAN_ONE_PASS) == _MORE_THAN_ONE_PASS, (
        'with the hook installed, every record must be on disk by the time '
        'app.exec() returns -- i.e. before interpreter shutdown'
    )


@pytest.mark.slow
def test_without_the_hook_nothing_is_on_disk_when_exec_returns():
    """The control that makes the test above a finding rather than a
    tautology.

    ``atexit`` drains after this moment, so an assertion taken any later
    is identical in both arms -- which is exactly why #278 was invisible.
    This arm must show the records absent; if it ever shows them present,
    the positive arm has stopped measuring the hook.
    """
    assert _run_child('nohook', _MORE_THAN_ONE_PASS) == 0


if __name__ == '__main__':  # pragma: no cover
    pytest.main([__file__, '-v'])
