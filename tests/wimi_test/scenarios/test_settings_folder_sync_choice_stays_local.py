"""Regression: a fork choice stays on this computer until the student sends (#148).

The owner's decision, 2026-09-22: resolving a fork writes nothing to the
folder. The choice takes effect here, is remembered, and is shown as a
standing state -- not a toast that scrolls away -- until the student
sends. Three things only a real page can show:

1. after choosing, the panel says a choice is waiting and the Send button
   says so too;
2. the fork's comparison is not offered a second time while it waits
   (asking twice is how a student answers differently the second time);
3. after sending, the waiting state is gone, and the other computer is
   told its copy was not the one kept.

The fork is real: device B is a second app-data directory in the test
process, and the running WIMI publishes without fetching B's work -- #149's
own reproduction.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``, ``tmp_path``.
"""
from __future__ import annotations

import pytest

from _helpers.foldersync_fork import await_js, make_fork, poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PANEL_READY = (
    "(() => typeof settingsPage === 'object'"
    " && typeof settingsPage.renderFolderSyncPending === 'function'"
    " && !!document.getElementById('folder-sync-pending'))()"
)


def _open_panel(page: WimiPage) -> None:
    page.eval_js("window.__wimiPrevDoc = true")
    page.goto('settings')
    assert poll(page, "typeof window.__wimiPrevDoc === 'undefined'", True) is True
    assert poll(page, PANEL_READY, True) is True, 'folder sync panel never initialised'
    page.eval_js(
        "document.querySelector('[data-testid=\"settings-nav-data-backup\"]').click()")


def _js(page: WimiPage, expr: str):
    return page.eval_js(expr)


@pytest.mark.slow
@pytest.mark.regression
def test_a_choice_waits_visibly_until_it_is_sent(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    _open_panel(wimi_page)
    scene = make_fork(wimi_page, wimi_session.user.db, folder, tmp_path / "deviceB")
    try:
        await_js(wimi_page, "settingsPage.renderFolderSyncLink()")
        await_js(wimi_page, "settingsPage.refreshFolderSyncStatus()")
        assert _js(wimi_page, "document.getElementById('folder-sync-fork').hidden") is False, (
            "a real fork was not offered for comparison")
        files_before = sorted(p.name for p in (folder / "WIMI").rglob("*") if p.is_file())

        await_js(wimi_page, "settingsPage.resolveFolderSyncFork('keep_local')")

        # 1. Nothing reached the folder; the waiting state is on screen.
        assert sorted(p.name for p in (folder / "WIMI").rglob("*") if p.is_file()) == files_before, (
            "choosing wrote to the folder -- the owner decided it must not")
        assert _js(wimi_page, "document.getElementById('folder-sync-pending').hidden") is False
        text = _js(wimi_page, "document.getElementById('folder-sync-pending-text').textContent")
        assert "not sent it yet" in text, f"the waiting state does not say so: {text!r}"
        assert _js(wimi_page, "document.getElementById('folder-sync-push').textContent") == (
            "Send your choice")

        # 2. The question is not asked again while the answer waits.
        assert _js(wimi_page, "document.getElementById('folder-sync-fork').hidden") is True, (
            "the comparison was offered again after the student had chosen")

        # 3. Send; the waiting state clears and the other computer is told.
        await_js(wimi_page, "settingsPage.pushFolderSync()")
        assert poll(wimi_page, "document.getElementById('folder-sync-pending').hidden", True) is True
        assert _js(wimi_page, "document.getElementById('folder-sync-push').textContent") == (
            "Send this device's copy")

        theirs = scene["b_sync"].status(scene["b_user_id"])
        assert theirs.base_relation == "superseded", (
            "the computer whose copy was not kept was not told")
        assert theirs.forks and theirs.forks[0]["set_aside"] is True
    finally:
        scene["b_master"].close()
