"""Regression: the dashboard's folder-sync notice fires once per launch (#148).

The owner's decision, 2026-09-22: the student is told about a fork --
or a choice not yet sent, or a copy set aside by the other computer -- by
a notice **once, at startup**. The dashboard reloads on every navigation,
so the "once" lives in the bridge; a page-side flag would fire it on every
visit and teach the student to dismiss it unread.

Also asserted: an ordinary linked profile with nothing to act on gets no
banner at all. "Nothing new" is not something the folder can tell us, and a
banner saying so would be the green tick #123 forbids.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``, ``tmp_path``.
"""
from __future__ import annotations

import pytest

from _helpers.foldersync_fork import await_js, make_fork, poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

NOTICE_HIDDEN = "document.getElementById('sync-notice').hidden"
NOTICE_TEXT = "document.getElementById('sync-notice-text').textContent"


def _dashboard(page: WimiPage) -> None:
    page.eval_js("window.__wimiPrevDoc = true")
    page.goto('dashboard')
    assert poll(page, "typeof window.__wimiPrevDoc === 'undefined'"
                      " && !!document.getElementById('sync-notice')", True) is True


def _settle(page: WimiPage) -> None:
    """Wait for the startup check to have been asked and answered."""
    assert poll(page, "typeof api === 'object' && typeof api.runFolderSyncStartupCheck"
                      " === 'function'", True) is True
    # The check is fire-and-forget from the page; give the one folder look
    # time to land, then read whatever it decided.
    page.wait_for_timeout(1500)


@pytest.mark.slow
@pytest.mark.regression
def test_a_fork_raises_the_notice_once_and_only_once(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    # Seed through the settings page: the dashboard is where the check runs,
    # so it must not have been visited before the fork exists.
    wimi_page.goto('settings')
    assert poll(wimi_page, "typeof api === 'object' && typeof api.pushFolderSync"
                           " === 'function'", True) is True
    scene = make_fork(wimi_page, wimi_session.user.db, folder, tmp_path / "deviceB")
    try:
        _dashboard(wimi_page)
        assert poll(wimi_page, NOTICE_HIDDEN, False, timeout_ms=20000) is False, (
            "a real fork produced no startup notice")
        assert "changed this profile independently" in wimi_page.eval_js(NOTICE_TEXT)

        _dashboard(wimi_page)
        _settle(wimi_page)
        assert wimi_page.eval_js(NOTICE_HIDDEN) is True, (
            "the notice fired again on a second visit -- it is once per launch")
    finally:
        scene["b_master"].close()


@pytest.mark.slow
@pytest.mark.regression
def test_a_linked_profile_with_nothing_to_act_on_gets_no_banner(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    wimi_page.goto('settings')
    assert poll(wimi_page, "typeof api === 'object' && typeof api.pushFolderSync"
                           " === 'function'", True) is True
    await_js(wimi_page, f"api.linkFolderSync({str(folder)!r}, 'generic')")
    await_js(wimi_page, "api.pushFolderSync()")

    _dashboard(wimi_page)
    _settle(wimi_page)
    assert wimi_page.eval_js(NOTICE_HIDDEN) is True, (
        "a banner appeared with nothing to act on: "
        + str(wimi_page.eval_js(NOTICE_TEXT)))
