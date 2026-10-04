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
"""
import sys

sys._wimi_relations_build = True
