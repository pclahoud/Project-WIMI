"""Child process for ``test_logger_drains_on_quit.py`` (#278).

Run as ``python _logger_quit_drain_child.py <arm> <log_dir> <n>`` where
``arm`` is ``hook`` or ``nohook``.

What it measures, and why it has to be a subprocess: the whole question is
whether the queue reaches disk **inside the Qt event loop** rather than at
interpreter shutdown. ``atexit`` already drains, so any check made after
this process exits cannot tell the two apart. So the child reads the log
file back itself, immediately after ``app.exec()`` returns and before it
returns from ``main()`` -- a moment when ``atexit`` has provably not run --
and prints the count for the parent to assert on.

``QCoreApplication``, not ``QApplication``: ``aboutToQuit`` is declared on
``QCoreApplication`` and that is the signal under test, so using the core
class costs nothing and means the child needs no platform plugin. CLAUDE.md
records that ``QT_QPA_PLATFORM=offscreen`` behaves differently on all three
platforms; a test about a logger should not have to care.
"""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / 'src'
sys.path.insert(0, str(_SRC))

from PyQt6.QtCore import QCoreApplication, QTimer  # noqa: E402

from app_logging.error_logger import ErrorLogger  # noqa: E402


def main() -> int:
    arm, log_dir, count = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])

    # flush_interval far beyond the run, so the ONLY thing that can put
    # these records on disk is a shutdown drain. Without this the periodic
    # ticker writes them and both arms pass.
    #
    # Logger before the application, which is production's order and the
    # reason the periodic flush is a daemon thread rather than a QTimer
    # (CLAUDE.md, Logging invariant 4).
    logger = ErrorLogger(
        app_name='QuitDrainChild',
        log_dir=log_dir,
        mode='development',
        flush_interval=3600.0,
    )

    app = QCoreApplication(sys.argv)

    if arm == 'hook':
        logger.install_shutdown_hook(app)
    elif arm != 'nohook':
        sys.stderr.write(f'unknown arm: {arm}\n')
        return 2

    # INFO, deliberately. ERROR and above self-flush inside log() (and
    # WARNING and above deduplicate within 300 s), so either would measure
    # something other than the shutdown drain.
    for i in range(count):
        logger.info(f'quit-drain-record-{i:05d}')

    QTimer.singleShot(0, app.quit)
    app.exec()

    # On disk, not the in-memory buffer -- and before this process exits,
    # so atexit has not had a chance to make both arms look identical.
    on_disk = 0
    for path in sorted(log_dir.glob('*.log')):
        on_disk += sum(
            1 for line in path.read_text(encoding='utf-8',
                                         errors='replace').splitlines()
            if 'quit-drain-record-' in line
        )

    print(f'ON_DISK_AFTER_EXEC={on_disk}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
