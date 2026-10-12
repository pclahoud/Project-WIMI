"""PyInstaller runtime hook for the RELATIONS build of WIMI (#60).

Marks the bundle as one that carries the relation-extraction runtime
(``torch`` / ``transformers`` / ``gliner2``). WIMI ships two artifacts per
platform (owner's decision, 2026-10-04) and the default one does not have the
runtime at all.

Why a marker rather than probing for torch
------------------------------------------
``importlib.util.find_spec('torch')`` answers "can I import torch", which
conflates two states the application must treat differently:

* **the default artifact** -- the runtime is absent *by design*. The feature is
  simply not there: a line in Settings, silence everywhere else (#60, open
  question 2). Nothing is wrong and nothing should be reported.
* **the relations artifact with a broken runtime** -- the runtime was bundled
  and will not load. That is a packaging bug in the artifact the user
  deliberately chose the larger download for, and it should say so rather than
  quietly presenting itself as the build that never had the feature.

A probe cannot tell those apart; this flag can. It records what the build
*intended*, which only the build knows.

Included by ``wimi.spec`` / ``wimi_macos.spec`` only when the build runs with
``WIMI_BUILD_RELATIONS=1``, which is what ``build_windows.bat relations`` and
``./build_macos.sh relations`` set. The flag is orthogonal to
``WIMI_BUILD_VARIANT``, so a test build with the runtime carries this hook and
``rthook_test_build.py`` both.

Nothing at runtime can set this, exactly as with #144's test-build marker --
not an environment variable, not a flag. A default artifact is a default
artifact.

The MSVC runtime preload lives here too (#367)
---------------------------------------------
``app.main.main()`` preloads the newest ``msvcp140.dll`` before it imports Qt,
and in a checkout that is early enough. **In a frozen build it is not.**
PyInstaller's own ``pyi_rth_pyqt6`` runtime hook calls
``create_embedded_qt_conf``, which imports ``PyQt6.QtCore`` -- loading Qt's
14.26 ``MSVCP140.dll`` before ``main.py`` runs at all. Measured in the first
frozen relations build on Windows machine B: the preload in ``main()`` reported
``already_loaded: msvcp140.dll 14.26.28720.3 from
_internal\\PyQt6\\Qt6\\bin\\MSVCP140.dll``, and ``import torch`` then failed
with WinError 1114 on the bundle's own ``c10.dll``.

Custom runtime hooks run BEFORE PyInstaller's (``analyze_runtime_hooks``:
"First hooks in the list are executed first. Put their graph nodes at the
head"), so this hook is the earliest Python that runs in the bundle, and it
is already the one that exists only in the relations build. The preload must
come AFTER the marker below, because ``should_preload`` reads it.
"""
import sys

sys._wimi_relations_build = True

try:
    from app.msvc_runtime import preload_newest

    preload_newest()
except Exception:  # noqa: BLE001 -- a runtime hook must never stop startup
    pass
