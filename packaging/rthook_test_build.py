"""PyInstaller runtime hook for the TEST build of WIMI (#144). Never in a release.

Marks the bundle as a test build, which is what lets ``app.cli`` accept
``--test-mode`` / ``--debug-port`` in a frozen binary. Release builds do not
include this hook, so nothing at runtime -- no flag, no environment
variable -- can switch test mode on in them.

Included by ``wimi.spec`` / ``wimi_macos.spec`` only when the build runs
with ``WIMI_BUILD_VARIANT=test``, which is what ``build_windows.bat test``
and ``./build_macos.sh test`` set.
"""
import sys

sys._wimi_test_build = True
