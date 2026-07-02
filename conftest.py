"""
Root conftest.py - Pytest configuration for WIMI tests

This file ensures the src directory is in the Python path
so that imports work correctly during testing.

It also registers the ``wimi_test.fixtures`` package as a pytest plugin
so the WIMI test infrastructure fixtures (``wimi_session``,
``test_user``, ``seeded_user``, capture handles, etc.) are available to
every test without explicit imports. See
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 7 for the full fixture
catalogue. Once the project grows a ``pyproject.toml`` this can move to
a ``[project.entry-points.pytest11]`` table; the project-root
``conftest.py`` route is the documented fallback for projects without
one.
"""
import os
import sys
from pathlib import Path

# CI headless-Qt bootstrap.
#
# When CI=true is set (GitHub Actions, GitLab CI, etc. all set this), force
# ``QT_QPA_PLATFORM=offscreen`` unless the runner has already chosen a
# platform plugin explicitly. This must happen *at import time*, before
# ``pytest_plugins = ["wimi_test.fixtures"]`` below loads the WIMI test
# infrastructure: those fixtures spawn WIMI subprocesses that inherit the
# parent process environment, and the offscreen platform is what lets
# QtWebEngine render without a real display. See
# ``docs/testing/CI_SETUP.md`` for the full rationale and the Ubuntu
# system-package list that must be installed alongside this flag.
if os.environ.get("CI", "").lower() in ("true", "1") and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Get project root
project_root = Path(__file__).parent

# Add the src directory to the Python path (like run_wimi.py does)
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Also add project root for 'src.module' style imports
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load the WIMI test infrastructure plugin (fixtures, CLI flags, hooks).
# Must be a top-level assignment in the project-root conftest.py so
# pytest discovers it before collection begins.
pytest_plugins = ["wimi_test.fixtures"]
