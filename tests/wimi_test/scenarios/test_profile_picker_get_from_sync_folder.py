"""Regression: the profile picker gets a profile from a sync folder (#151).

A computer that has never had the profile has no profile open, which is why
this lives in the picker. The owner decided the install also **links** the
profile to the folder it came from, and it records the installed generation
as the profile's base -- without that its first send would claim no history
(#149).

A profile already on this computer is **not** installed again: a second
copy sharing a profile id must never be linked (#124's keep-both rule). The
picker offers the copy that is here instead.

The native folder dialog cannot be driven from a scenario, so the folder is
handed to the modal's state directly -- the same split the Settings panel
uses between ``pickFolderSyncFolder`` and the work.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``, ``tmp_path``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.foldersync_fork import _add_entries, await_js, poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PICKER_READY = ("(() => typeof window.__wimiPrevDoc === 'undefined'"
                " && typeof scanSyncInstallFolder === 'function'"
                " && !document.getElementById('syncInstallBtn').classList.contains('hidden'))()")


def _publish_from_another_computer(tmp_path, folder):
    """A profile that exists only on 'device X' and in the folder."""
    from app.foldersync import ProfileFolderSync
    from database.master_db import MasterDatabase
    from database.user_db import UserDatabase

    master = MasterDatabase(data_dir=tmp_path / "deviceX", error_logger=None)
    user = master.create_user(username="elsewhere", display_name="Elsewhere")
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    try:
        _add_entries(db, 4)
        sync_id = db.get_profile_uuid()
    finally:
        db.close()
    master.record_profile_uuid(user.id, sync_id)
    sync = ProfileFolderSync(master, timeout_s=10.0)
    sync.link(user.id, folder, "generic")
    pushed = sync.push(user.id)
    master.close()
    return sync_id, pushed


def _scan(page: WimiPage, folder) -> None:
    page.eval_js("SyncInstallState.folder = " + json.dumps(str(folder))
                 + "; SyncInstallState.providerId = 'generic';")
    await_js(page, "openSyncInstallModal()")
    await_js(page, "scanSyncInstallFolder()")


@pytest.mark.slow
@pytest.mark.regression
def test_a_profile_from_the_folder_is_installed_linked_and_based(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    from app.foldersync.state import SyncState
    from database.master_db import MasterDatabase

    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    sync_id, pushed = _publish_from_another_computer(tmp_path, folder)

    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('profile-select')
    assert poll(wimi_page, PICKER_READY, True) is True, "the picker offered no sync-folder install"

    _scan(wimi_page, folder)
    assert wimi_page.eval_js(
        "document.querySelectorAll('[data-testid=\"profile-sync-install-go\"]').length") == 1

    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"profile-sync-install-go\"]').click()")
    assert poll(wimi_page, "!!document.querySelector('[data-testid=\"profile-sync-install-done\"]')",
                True, timeout_ms=30000) is True, (
        wimi_page.eval_js("document.getElementById('syncInstallError').textContent"))

    master = MasterDatabase(data_dir=wimi_session.config.app_data_dir, error_logger=None)
    try:
        installed = master.find_users_by_profile_uuid(sync_id)
    finally:
        master.close()
    assert len(installed) == 1, "the profile was not installed exactly once"
    link = SyncState(wimi_session.config.app_data_dir).get_link(installed[0].id)
    assert link is not None, "the install was not linked (owner's decision: auto-link)"
    assert link.base_sha256 == pushed.sha256, "the installed generation is not its base (#149)"

    # Looking again: it is here now, so it is offered to open, not install.
    _scan(wimi_page, folder)
    assert wimi_page.eval_js(
        "document.querySelectorAll('[data-testid=\"profile-sync-install-go\"]').length") == 0
    assert wimi_page.eval_js(
        "!!document.querySelector('[data-testid=\"profile-sync-install-open-existing\"]')") is True
