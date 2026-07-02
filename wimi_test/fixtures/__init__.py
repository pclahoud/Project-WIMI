"""Pytest fixture package for the WIMI test infrastructure.

Implements the pytest fixture catalogue described in
``docs/planning/TEST_INFRASTRUCTURE.md`` Section 7. The package is
registered as a pytest plugin (entry-point or ``pytest_plugins``
re-export from the project-root ``conftest.py``) so importing tests do
not need to import these fixtures explicitly — pytest discovers them
automatically once the plugin is loaded.

The actual fixture implementations live in :mod:`wimi_test.fixtures.core`;
this module re-exports the public fixture names for convenience so
callers that *do* want explicit imports (e.g. to silence linters that
flag implicit fixture use) can write ``from wimi_test.fixtures import
wimi_session``.

See also Section 4 (``WimiTestSession`` API contract) and Section 3
(module responsibility matrix) of the same design document for the
upstream pieces these fixtures glue together.
"""

from wimi_test.fixtures.core import (
    bridge_log,
    console_log,
    network_log,
    pytest_addoption,  # noqa: F401 — pytest hook, must be visible on the plugin module
    seeded_user,
    test_user,
    wimi_config,
    wimi_master_db,
    wimi_page,
    wimi_session,
)

# Re-export the failure-attachment hook at the package level so pytest
# discovers it as part of this plugin module. Pytest looks up hook
# implementations on the *plugin module itself* (this ``__init__``) by
# name; a hook defined in the ``capture`` submodule would otherwise be
# invisible. See ``wimi_test/fixtures/capture.py`` and
# ``docs/planning/TEST_INFRASTRUCTURE.md`` §6.4 for the hook contract.
from wimi_test.fixtures.capture import pytest_runtest_makereport  # noqa: F401

__all__ = [
    "wimi_config",
    "wimi_master_db",
    "test_user",
    "seeded_user",
    "wimi_session",
    "wimi_page",
    "console_log",
    "network_log",
    "bridge_log",
]
