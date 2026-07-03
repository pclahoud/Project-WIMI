"""Regression: profile export -> preview -> import-as-new roundtrip.

Drives the Task-4 transfer bridge surface end to end through the JS
wrappers, using the path-taking work slots (``exportProfile`` /
``readProfileArchive`` / ``executeProfileImport``) directly — the
dialog slots (``openProfileExportDialog`` / ``openProfileImportDialog``)
are deliberately skipped because a native file dialog would hang a
headless run. This is exactly the dialog-slot/work-slot split the
bridge was designed around.

Flow: seed the session profile with an exam context -> export it to a
temp ``.wimi`` (no media) -> read the archive back and assert the
preview payload (schema verdict ``ok``, username collision against the
still-present source profile, manifest stats) -> import in ``create``
mode -> assert the master registry lists BOTH profiles.

Loader quirk: probes use ``window.api`` (NOT ``window._wimiApi``)
because ``_loader.js`` aliases then deletes the source handle.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_profile_export_import_roundtrip(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
    tmp_path: Path,
    wimi_master_db: Any,  # session-scoped: guarantees app_data_test cleanup
) -> None:
    """Export the seeded session profile and re-import it as a new one."""
    # ---- Arrange: seed the session profile ---------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    db.create_exam_context(
        exam_name="Transfer Regression Exam",
        exam_description="Seeded so the archive manifest has non-trivial stats",
    )
    db.conn.commit()

    source_username = wimi_session.user.username
    source_user_id = wimi_session.user.user_id

    # Any page with the bridge up works; the picker is the natural home
    # for transfer flows and runs fine with a user attached.
    wimi_page.goto("profile-select")

    dest = tmp_path / "transfer_regression.wimi"
    dest_js = json.dumps(str(dest))

    # ---- Act 1: export via the path-taking work slot (no dialog) -----
    export_result = wimi_page.eval_js(
        f"""
        window.api.exportProfile({{
            user_id: {source_user_id},
            include_media: false,
            dest_path: {dest_js}
        }})
        """,
        await_promise=True,
    )
    assert export_result.get("archive_path"), (
        f"exportProfile returned no archive_path: {export_result!r}"
    )
    assert dest.exists(), f"Export did not write {dest}"
    assert export_result.get("stats", {}).get("exam_contexts") == 1, (
        f"Export manifest stats did not pick up the seeded exam context: "
        f"{export_result!r}"
    )

    # ---- Act 2: read the archive back (import preview payload) -------
    preview = wimi_page.eval_js(
        f"window.api.readProfileArchive({dest_js})",
        await_promise=True,
    )
    schema = preview.get("schema") or {}
    assert schema.get("verdict") == "ok", (
        f"Round-trip archive should preflight 'ok' (same app, same "
        f"schema); got {schema!r}"
    )
    media = preview.get("media") or {}
    assert media.get("included") is False, f"media unexpectedly included: {media!r}"
    stats = (preview.get("manifest") or {}).get("stats") or {}
    assert stats.get("exam_contexts") == 1, f"manifest stats wrong: {stats!r}"

    collision = preview.get("collision") or {}
    assert collision.get("username_exists") is True, (
        f"The source profile still exists, so the preview must report a "
        f"username collision; got {collision!r}"
    )
    suggested = collision.get("suggested_username")
    assert suggested and suggested != source_username, (
        f"suggested_username must be a free variant of {source_username!r}; "
        f"got {suggested!r}"
    )

    # The preview's replace_targets must flag the currently open profile.
    targets = {t["user_id"]: t for t in preview.get("replace_targets") or []}
    assert source_user_id in targets, (
        f"replace_targets missing the source profile: {targets!r}"
    )
    assert targets[source_user_id]["is_current"] is True, (
        f"replace_targets did not mark the open profile as current: "
        f"{targets[source_user_id]!r}"
    )

    # ---- Act 3: import as a new profile -------------------------------
    import_result = wimi_page.eval_js(
        f"""
        window.api.executeProfileImport({{
            archive_path: {dest_js},
            mode: 'create'
        }})
        """,
        await_promise=True,
    )
    new_user_id = import_result.get("user_id")
    assert isinstance(new_user_id, int) and new_user_id != source_user_id, (
        f"Import did not create a distinct profile: {import_result!r}"
    )
    assert import_result.get("username") == suggested, (
        f"Import username {import_result.get('username')!r} does not match "
        f"the previewed suggestion {suggested!r} — preview and install "
        f"collision logic have drifted apart."
    )
    assert import_result.get("schema_verdict") == "ok", (
        f"Unexpected import schema verdict: {import_result!r}"
    )

    # ---- Assert: master registry lists BOTH profiles -----------------
    profiles = wimi_page.eval_js(
        "window.api.listProfiles()",
        await_promise=True,
    )
    usernames = {p["username"] for p in profiles.get("profiles") or []}
    assert source_username in usernames, (
        f"Source profile vanished after import: {sorted(usernames)!r}"
    )
    assert suggested in usernames, (
        f"Imported profile @{suggested} not listed: {sorted(usernames)!r}"
    )
    assert profiles.get("current_user_id") == source_user_id, (
        f"Import-as-new must not switch the active profile; got "
        f"current_user_id={profiles.get('current_user_id')!r}"
    )
