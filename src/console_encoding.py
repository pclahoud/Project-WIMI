"""Process-wide stdio encoding guard for every WIMI entry point (#137).

Why this module exists
----------------------
``print()`` writes through ``sys.stdout``'s text encoder, and on Windows
that encoder is the *console codepage* — cp1252 on most installs —
whenever the stream is not a real console. A pipe, or ``WIMI.exe >
log.txt``, is enough. Any character outside that codepage then raises
``UnicodeEncodeError`` from inside ``print()``; at startup that kills the
process before the window ever appears. The frozen build crashed exactly
this way on ``register_media_scheme``'s camera glyph (that handler was
later deleted as dead code, #140), and the harness
pipes stdout by design (it reads ``TEST_MODE_READY:port=N`` from it), so
"redirected" is the normal case for automation rather than an exotic one.

The environment cannot fix it: ``PYTHONIOENCODING`` is honoured by an
ordinary interpreter and **ignored by the PyInstaller runtime** (measured
on Windows with a control — see #137 comment #1689). So the guard has to
live in code, at the top of every entry point, which is what
:func:`configure_stdio` is for.

Three things here are load-bearing, not defensive noise
-------------------------------------------------------
* **``sys.stdout`` can be ``None``.** ``wimi_macos.spec`` sets
  ``console=False`` because a macOS ``.app`` must not be a console app,
  and a windowed PyInstaller build has no standard streams at all. An
  unguarded ``sys.stdout.reconfigure(...)`` raises ``AttributeError``
  there and crashes the build on the very line added to prevent a crash.
  ``wimi.spec`` says ``console=True,  # Set to False for release builds``,
  so Windows can reach the same state.
* **``sys.stdout`` need not be a ``TextIOWrapper``.** pytest's capture
  object, a ``StringIO``, an IDE console shim: none have ``reconfigure``.
  Skipping them is the correct outcome, not a failure.
* **``errors`` must be passed whenever ``encoding`` is.**
  ``io.TextIOWrapper.reconfigure`` resets ``errors`` to ``'strict'`` when
  it is given an encoding and no errors handler — so passing encoding
  alone to ``sys.stderr`` would *remove* the ``'backslashreplace'`` that
  already keeps tracebacks from raising.

The two streams therefore get different handlers on purpose.
``sys.stdout`` defaults to ``'strict'``, which is the crash; ``'replace'``
degrades a future non-encodable character to ``?`` instead. ``sys.stderr``
already defaults to ``'backslashreplace'`` and so never raises — we keep
that, because a traceback that silently swaps characters for ``?`` is
worse than one that escapes them.

This module imports nothing but :mod:`sys`, so any layer may use it: it
is reached from ``src/app/main.py`` (the frozen entry point),
``run_wimi.py`` (the dev launcher) and
``src/database/migrations/__main__.py`` (the migration CLI).
"""

from __future__ import annotations

import sys

__all__ = ["configure_stdio", "STDOUT_ERRORS", "STDERR_ERRORS"]

# See the module docstring: these differ deliberately.
STDOUT_ERRORS = "replace"
STDERR_ERRORS = "backslashreplace"


def configure_stdio(encoding: str = "utf-8") -> tuple[str, ...]:
    """Force ``sys.stdout`` / ``sys.stderr`` to ``encoding``. Never raises.

    Call it as the first statement of an entry point, before anything can
    print. Safe to call more than once.

    Returns
    -------
    tuple[str, ...]
        The names of the streams that were actually reconfigured
        (``("stdout", "stderr")`` in the ordinary case, ``()`` in a
        windowed build with no streams). Returned so callers and tests
        can tell "skipped" from "done"; nothing in the app branches on it.
    """
    reconfigured: list[str] = []

    for name, errors in (("stdout", STDOUT_ERRORS), ("stderr", STDERR_ERRORS)):
        stream = getattr(sys, name, None)
        if stream is None:
            # Windowed build (``console=False``): there is no stream to
            # encode to, and ``print()`` is already a no-op.
            continue

        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            # Not a TextIOWrapper — pytest capture, StringIO, IDE shim.
            continue

        try:
            reconfigure(encoding=encoding, errors=errors)
        except Exception:  # noqa: BLE001 - see below
            # A detached, closed or otherwise hostile stream must never
            # turn a diagnostic convenience into a startup failure. This
            # function exists to stop a crash; it may not cause one.
            continue

        reconfigured.append(name)

    return tuple(reconfigured)
