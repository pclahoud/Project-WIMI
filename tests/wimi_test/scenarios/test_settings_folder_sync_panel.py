"""Regression: Settings -> Data & Backup, the folder sync panel (#123).

The panel is the only UI for folder sync, and two of its rules are
JS-side decisions that no backend test can see.

1. **The checkbox has no stored value.** Settled 2026-09-21: "Enable
   Cloud Sync" reflects and toggles *the link*. It deliberately carries
   no ``data-field``, because that attribute would route it through
   ``updateUserPreferences`` into ``user_preferences.cloud_sync_enabled``
   -- a user-level column, so it travels inside a ``.wimi`` and a
   profile exported with sync on would arrive on the next machine
   claiming to sync with no folder linked there. This scenario asserts
   the attribute is absent and that the control's state comes from the
   link instead.

2. **The panel never claims a state it cannot observe.** You cannot
   force a sync or know when one finished, so "nothing new" and "the
   other device has not uploaded yet" are indistinguishable from the
   filesystem. There is no tick, and the words that would imply one must
   not appear.

The folder is linked through the **work** slot with a plain path rather
than the native picker, which is why the two are separate slots
(session-import pattern). A scenario cannot drive ``QFileDialog``.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``, ``tmp_path``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

FRESH_DOC = "typeof window.__wimiPrevDoc === 'undefined' && typeof window.api === 'object'"
PANEL_READY = (
    "(() => { const cb = document.getElementById('cloud_sync_enabled');"
    " return !!cb && typeof settingsPage === 'object'"
    "        && typeof settingsPage.renderFolderSyncLink === 'function'; })()"
)


def _poll(page: WimiPage, js: str, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _open_panel(page: WimiPage) -> None:
    page.eval_js("window.__wimiPrevDoc = true")
    page.goto('settings')
    assert _poll(page, FRESH_DOC, True) is True, 'Settings page did not (re)load'
    assert _poll(page, PANEL_READY, True) is True, 'Folder sync control never initialised'
    page.eval_js(
        "document.querySelector('[data-testid=\"settings-nav-data-backup\"]').click()"
    )
    assert page.eval_js(
        "document.querySelector('.settings-panel[data-panel=\"data_backup\"]')"
        ".classList.contains('active')"
    ), 'Data & Backup panel did not activate'


def _await_js(page: WimiPage, expression: str, *, timeout_ms: int = 30000):
    """Run an async api call and poll for its settled result."""
    page.eval_js(
        "window.__syncResult = undefined; window.__syncError = undefined;"
        " Promise.resolve(" + expression + ")"
        "  .then(v => { window.__syncResult = JSON.stringify(v === undefined ? null : v); })"
        "  .catch(e => { window.__syncError = String(e && e.message || e); });"
    )
    elapsed = 0
    while elapsed < timeout_ms:
        err = page.eval_js("window.__syncError || null")
        if err:
            raise AssertionError(f"{expression} failed: {err}")
        done = page.eval_js("window.__syncResult || null")
        if done is not None:
            return json.loads(done)
        page.wait_for_timeout(200)
        elapsed += 200
    raise AssertionError(f"{expression} never settled")


def _observations(page: WimiPage) -> str:
    return page.eval_js(
        "document.getElementById('folder-sync-observations').textContent")


@pytest.mark.slow
@pytest.mark.regression
def test_the_checkbox_is_the_link_and_stores_no_preference(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    """Unlinked means unchecked, and the control writes no preference row."""
    _open_panel(wimi_page)

    assert wimi_page.eval_js(
        "document.getElementById('cloud_sync_enabled').hasAttribute('data-field')"
    ) is False, (
        "the checkbox carries data-field, so it saves into "
        "user_preferences.cloud_sync_enabled -- a column that travels in a "
        ".wimi. Settled 2026-09-21: the link is the state."
    )
    assert wimi_page.eval_js(
        "document.getElementById('cloud_sync_enabled').checked") is False
    assert wimi_page.eval_js(
        "document.getElementById('folder-sync-details').hidden") is True


@pytest.mark.slow
@pytest.mark.regression
def test_linking_a_folder_checks_the_box_and_names_the_pin_setting(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    """The panel's most useful sentence is the client's own wording."""
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    _open_panel(wimi_page)

    _await_js(wimi_page,
              f"api.linkFolderSync({json.dumps(str(folder))}, 'box')")
    _await_js(wimi_page, "settingsPage.renderFolderSyncLink()")

    assert wimi_page.eval_js(
        "document.getElementById('cloud_sync_enabled').checked") is True
    assert wimi_page.eval_js(
        "document.getElementById('folder-sync-details').hidden") is False
    assert wimi_page.eval_js(
        "document.getElementById('folder-sync-folder').textContent") == str(folder)

    hint = wimi_page.eval_js(
        "document.getElementById('folder-sync-pin-hint').textContent")
    assert "Always keep on this device" in hint, (
        f"Box's pin setting is not named in the panel: {hint!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_pushing_reports_a_generation_and_never_claims_it_synced(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    """#123's UI-honesty criterion, at the surface the student reads."""
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    _open_panel(wimi_page)

    _await_js(wimi_page, f"api.linkFolderSync({json.dumps(str(folder))}, 'box')")
    pushed = _await_js(wimi_page, "api.pushFolderSync()")
    assert pushed["generation"] == 1

    status = _await_js(wimi_page, "api.getFolderSyncStatus()")
    assert status["head_generation"] == 1
    wimi_page.eval_js("settingsPage.renderFolderSyncObservations("
                      + json.dumps(status) + ")")

    text = _observations(wimi_page).lower()
    assert "generation 1" in text, f"the generation is not reported: {text!r}"
    for forbidden in ("in sync", "synced", "up to date", "all good"):
        assert forbidden not in text, (
            f"the panel says {forbidden!r}, which implies knowledge the "
            f"filesystem cannot give: {text!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_unticking_unlinks_and_leaves_the_folder_alone(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    """Unticking a checkbox must never be a destructive act."""
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    _open_panel(wimi_page)

    _await_js(wimi_page, f"api.linkFolderSync({json.dumps(str(folder))}, 'box')")
    _await_js(wimi_page, "api.pushFolderSync()")
    before = sorted(p.name for p in (folder / "WIMI").rglob("*"))
    assert before, "nothing was written to the folder, so this proves nothing"

    _await_js(wimi_page, "settingsPage.toggleFolderSync(false)")

    assert wimi_page.eval_js(
        "document.getElementById('cloud_sync_enabled').checked") is False
    assert wimi_page.eval_js(
        "document.getElementById('folder-sync-details').hidden") is True
    assert sorted(p.name for p in (folder / "WIMI").rglob("*")) == before, (
        "unlinking deleted archives out of the student's own folder")


@pytest.mark.slow
@pytest.mark.regression
def test_the_fork_panel_is_hidden_until_there_is_one(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    """A permanent "no conflicts" box is noise that trains people to ignore it."""
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    _open_panel(wimi_page)

    _await_js(wimi_page, f"api.linkFolderSync({json.dumps(str(folder))}, 'box')")
    _await_js(wimi_page, "api.pushFolderSync()")
    _await_js(wimi_page, "settingsPage.refreshFolderSyncStatus()")

    assert wimi_page.eval_js(
        "document.getElementById('folder-sync-fork').hidden") is True
    assert _await_js(wimi_page, "api.getFolderSyncForkReport()") is None, (
        "no fork must be null, which is not the same as a report that "
        "could not compare")


@pytest.mark.slow
@pytest.mark.regression
def test_a_report_that_could_not_compare_never_renders_as_no_differences(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    """The one failure mode in #124 that lies rather than erroring.

    ``compared: false`` means a side could not be read, so every
    ``subjects_only_here`` is empty -- which is indistinguishable from "the
    two copies have identical subjects" unless the panel says otherwise.
    Telling a student the copies agree when nobody looked is precisely the
    false reassurance #124 exists to prevent.

    Driven by handing the renderer a report directly, because provoking an
    unreadable side through a real cloud folder is not something a scenario
    can arrange.
    """
    _open_panel(wimi_page)

    report = {
        "parent_generation": 1,
        "compared": False,
        "notes": ["One side could not be read, so the subject comparison did "
                  "not run. An empty 'only on this side' list below means "
                  "nobody looked, not that the two agree."],
        "sides": [
            {"generation": 2, "parent_generation": 1, "device_id": "dev-a",
             "device_name": "DESKTOP", "created_at": "2026-09-22T00:00:00Z",
             "bytes": 1, "blob_name": "profile-DESKTOP-aaaaaaaa-gen-0002.wimi",
             "entries": 40, "sessions": 1, "exam_contexts": 1, "subjects": 3,
             "encountered_first": "2026-09-01", "encountered_last": "2026-09-20",
             "logged_first": None, "logged_last": None,
             "subjects_only_here": [], "subjects_only_here_count": 0,
             "subjects_only_here_named": []},
            {"generation": 2, "parent_generation": 1, "device_id": "dev-b",
             "device_name": "LAPTOP", "created_at": "2026-09-22T00:00:00Z",
             "bytes": 1, "blob_name": "profile-LAPTOP-bbbbbbbb-gen-0002.wimi",
             "entries": 6, "sessions": 1, "exam_contexts": 1, "subjects": 2,
             "encountered_first": "2026-06-01", "encountered_last": "2026-06-02",
             "logged_first": None, "logged_last": None,
             "subjects_only_here": [], "subjects_only_here_count": 0,
             "subjects_only_here_named": []},
        ],
    }
    wimi_page.eval_js(
        "settingsPage.folderSyncFork = " + json.dumps(report) + ";"
        " document.getElementById('folder-sync-fork').hidden = false;"
        " document.getElementById('folder-sync-fork-sides').innerHTML ="
        "   settingsPage.folderSyncFork.sides"
        "     .map(s => settingsPage.renderForkSide(s, settingsPage.folderSyncFork))"
        "     .join('');")

    text = wimi_page.eval_js(
        "document.getElementById('folder-sync-fork-sides').textContent").lower()
    assert "could not compare" in text, (
        f"an uncompared report must say so: {text!r}")
    assert "no subjects that the other copy lacks" not in text, (
        "the panel claimed the copies agree when nobody looked")

    # The figures that make the choice answerable are still shown.
    assert "40 entries" in text and "6 entries" in text
    assert "2026-09-20" in text and "2026-06-02" in text
