"""Regression: catching up to a newer copy from the sync folder (#151).

Another computer built on this one's copy and sent it. The owner decided:

1. **Detect unsent work and offer both.** When this computer has changed
   since it last synced, the panel names what changed and offers "Send mine
   first" beside "Use the newer copy anyway". When it has not, it says what
   it checked -- counts and dates -- and offers only the one action.
2. **The dashboard says so, once per launch.** Sitting down at the second
   computer is when a student would otherwise start on a stale copy.

Taking the copy replaces the open profile, which the bridge closes and
reopens around the replace (#148), so the page reloads -- asserted here with
a real profile database, not a stub.

Device B is a second app-data directory in the test process.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``, ``tmp_path``.
"""
from __future__ import annotations

import pytest

from _helpers.foldersync_fork import (
    add_entries_here, await_js, entries_here, make_behind, poll,
)
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PANEL_READY = ("(() => typeof window.__wimiPrevDoc === 'undefined'"
               " && typeof settingsPage === 'object'"
               " && typeof settingsPage.renderFolderSyncCatchup === 'function')()")
HIDDEN = "document.getElementById('folder-sync-catchup').hidden"


def _open_panel(page: WimiPage) -> None:
    page.eval_js("window.__wimiPrevDoc = true")
    page.goto('settings')
    assert poll(page, PANEL_READY, True) is True, 'settings did not (re)load'
    page.eval_js(
        "document.querySelector('[data-testid=\"settings-nav-data-backup\"]').click()")


def _text(page: WimiPage, el_id: str) -> str:
    return page.eval_js(f"document.getElementById('{el_id}').textContent") or ""


@pytest.mark.slow
@pytest.mark.regression
def test_an_unchanged_computer_takes_the_newer_copy(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    _open_panel(wimi_page)
    scene = make_behind(wimi_page, wimi_session, folder, tmp_path / "deviceB")
    try:
        await_js(wimi_page, "settingsPage.renderFolderSyncLink()")
        await_js(wimi_page, "settingsPage.refreshFolderSyncStatus()")

        assert wimi_page.eval_js(HIDDEN) is False, "the newer copy was not offered"
        assert "No changes found on this computer" in _text(wimi_page, "folder-sync-catchup-text")
        assert _text(wimi_page, "folder-sync-take-newer") == "Use the newer copy"
        assert wimi_page.eval_js(
            "document.getElementById('folder-sync-send-first').hidden") is True

        # Taking it reopens the profile under the page, which reloads.
        wimi_page.eval_js("window.__wimiPrevDoc = true; settingsPage.takeNewerFolderSyncCopy()")
        assert poll(wimi_page, PANEL_READY, True, timeout_ms=30000) is True, (
            "the page did not reload after the profile was replaced")

        assert entries_here(wimi_session) == 8, "this computer does not hold the newer copy"
        status = await_js(wimi_page, "api.getFolderSyncStatus()")
        assert status["base_relation"] == "current"
        assert status["pending"] is None, "catching up must need no send"
    finally:
        scene["b_master"].close()


@pytest.mark.slow
@pytest.mark.regression
def test_work_here_is_named_and_send_mine_first_keeps_both(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    _open_panel(wimi_page)
    scene = make_behind(wimi_page, wimi_session, folder, tmp_path / "deviceB")
    try:
        add_entries_here(wimi_session, 2)       # work B does not have
        await_js(wimi_page, "settingsPage.refreshFolderSyncStatus()")

        text = _text(wimi_page, "folder-sync-catchup-text")
        assert "This computer has changed since it last synced" in text, text
        assert "entries: 7 here, 5 when it last synced" in text, text
        assert _text(wimi_page, "folder-sync-take-newer") == "Use the newer copy anyway"
        assert wimi_page.eval_js(
            "document.getElementById('folder-sync-send-first').hidden") is False

        await_js(wimi_page, "settingsPage.pushFolderSync()")
        assert poll(wimi_page, "document.getElementById('folder-sync-fork').hidden",
                    False, timeout_ms=30000) is False, (
            "sending first should have produced two copies to choose between")
        assert wimi_page.eval_js(HIDDEN) is True
        assert entries_here(wimi_session) == 7, "sending first must not replace anything"
    finally:
        scene["b_master"].close()


@pytest.mark.slow
@pytest.mark.regression
def test_the_dashboard_announces_the_newer_copy(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    _open_panel(wimi_page)
    scene = make_behind(wimi_page, wimi_session, folder, tmp_path / "deviceB")
    try:
        wimi_page.eval_js("window.__wimiPrevDoc = true")
        wimi_page.goto('dashboard')
        assert poll(wimi_page, "typeof window.__wimiPrevDoc === 'undefined'"
                               " && !!document.getElementById('sync-notice')", True) is True
        assert poll(wimi_page, "document.getElementById('sync-notice').hidden",
                    False, timeout_ms=20000) is False, "no notice for a newer copy"
        assert "A newer copy of this profile" in _text(wimi_page, "sync-notice-text")
    finally:
        scene["b_master"].close()
