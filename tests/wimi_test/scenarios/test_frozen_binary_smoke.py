"""Regression: a frozen build must be drivable by the harness (#137 + #138).

Bug sources: Forgejo issues #137 and #138 on the private tracker.
Neither is observable on its own, which is why one scenario covers both.

* **#138** — ``wimi.spec:91`` freezes ``src/app/main.py``, whose
  ``__main__`` block called ``main()`` with no arguments while the parser
  lived in ``run_wimi.py``. Frozen, every test-mode flag was read off a
  ``None`` namespace and silently dropped: the CDP port never opened,
  ``--app-data-dir`` was ignored, and a stray ``app_data/`` appeared next
  to the executable.
* **#137** — the harness **pipes stdout**, because that is where
  ``TEST_MODE_READY:port=N`` arrives. On Windows a redirected stream
  encodes with the console codepage, and six non-ASCII ``print()`` calls
  then raised ``UnicodeEncodeError`` from inside ``print`` — killing the
  process during scheme registration, before the window appeared.

Fixing either alone changes nothing you can see: with #137 unfixed the
binary dies before it can honour the flag, and with #138 unfixed there is
no port to attach to even when it lives. This scenario is the compound
test — pipe stdout, read the sentinel, attach CDP, navigate — and it is
the first thing in this project's history to drive the artifact users
actually get.

**It needs a built TEST binary.** Point ``WIMI_TEST_BINARY`` at one
(``build_windows.bat test`` / ``./build_macos.sh test``, then
``dist/WIMI-test/WIMI``); the scenario skips without it, because a 560 MB
PyInstaller build does not belong in an ordinary test run. Setting that
variable also switches *every* other scenario onto the binary, which is
the capability #138 asked for.

A **release** build refuses ``--test-mode`` (#144, owner's decision), so it
cannot be driven here. The two variants come from one spec and differ by
one runtime hook; ``tests/test_release_build_refuses_test_mode.py`` checks
the release side.
"""

from __future__ import annotations

import os

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = pytest.mark.skipif(
    not os.environ.get("WIMI_TEST_BINARY", "").strip(),
    reason=(
        "Set WIMI_TEST_BINARY to a built WIMI TEST executable "
        # Both platforms, because the first person to hit this skip on macOS
        # was sent to a .bat file and a path the .app does not have.
        "to run the frozen smoke test. Build one with `build_windows.bat test` "
        "(-> dist/WIMI-test/WIMI.exe) or `./build_macos.sh test` "
        "(-> dist/WIMI-test/WIMI.app/Contents/MacOS/WIMI)."
    ),
)


def _wait_for_ready_state(page: WimiPage, attempts: int = 40) -> str:
    """Poll ``document.readyState`` — never ``time.sleep`` in a scenario."""
    state = ""
    for _ in range(attempts):
        try:
            state = str(page.eval_js("document.readyState"))
        except Exception:
            state = ""
        if state == "complete":
            return state
        page.wait_for_timeout(250)
    return state


@pytest.mark.slow
@pytest.mark.regression
def test_a_frozen_binary_reaches_ready_and_serves_a_page(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The whole #137 + #138 contract, in the order the harness needs it."""
    # The session fixture has already done the two things that used to be
    # impossible: it spawned the binary with stdout piped and blocked on
    # the ready sentinel (#137 would have killed it first), then attached
    # over CDP on the port ``--debug-port`` asked for (#138 never opened
    # one). Reaching this line is most of the assertion.
    proc = wimi_session.process
    assert proc.is_alive(), "The frozen binary exited before the test body ran."

    binary = os.environ["WIMI_TEST_BINARY"].strip()
    assert proc._build_command(0)[0] == binary, (
        "The session spawned something other than the configured binary; "
        "this scenario would then be re-testing the dev launcher."
    )

    stdout = "\n".join(proc.last_stdout(200))
    assert "TEST_MODE_READY:port=" in stdout, (
        "No ready sentinel on the piped stdout. Before #137 a "
        "UnicodeEncodeError from a non-ASCII print() appeared here "
        f"instead. Last output was:\n{stdout}"
    )
    assert "UnicodeEncodeError" not in stdout, (
        f"A print() crashed the redirected frozen build (#137):\n{stdout}"
    )
    assert "[Running in compiled mode]" in stdout, (
        "The process under test does not report itself as frozen; "
        f"WIMI_TEST_BINARY may point at a script. Output:\n{stdout}"
    )

    # And it is a real, drivable app: navigate and read the DOM back.
    wimi_page.goto("dashboard")
    assert _wait_for_ready_state(wimi_page) == "complete"
    node_count = wimi_page.eval_js("document.querySelectorAll('*').length")
    assert isinstance(node_count, int) and node_count > 20, (
        f"The page rendered {node_count} elements; the frozen bundle may "
        "be missing its web/ assets."
    )
