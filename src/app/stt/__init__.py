"""Speech to text: record on the main thread, transcribe on a worker (#59).

The package is deliberately **empty of re-exports**. Import the submodule you
need (``from app.stt.errors import SttErrorKind``), never ``from app.stt import
...``. Two reasons, both learned elsewhere in this codebase:

* ``recorder.py`` imports ``PyQt6.QtMultimedia``. Re-exporting it here would
  make every import of anything in this package pull in Qt, including on the
  worker thread and in unit tests that have no ``QApplication`` -- and the
  worker is contractually forbidden to touch a Qt object at all (§3.4).
* The modules land from several directions. A facade in this file is a file
  every one of them has to edit, which is a merge conflict for no benefit.

Layout:

* ``errors.py``    -- the failure taxonomy and the order the checks run in.
* ``recorder.py``  -- microphone to WAV, on the Qt main thread (T7).
* ``runtime.py``   -- where the binary and the model live, and how to run them (T6).
* ``jobs.py``      -- the single-worker executor the bridge polls (T6).
* ``priming.py``   -- subject terms to a whisper.cpp ``--prompt`` string (T10).
* ``model_spec.py``/``download.py`` -- the pinned weights, fetched on first run (T21).

Plan: ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md``.
"""
