"""Regression: replacing a profile asks what to do with its images (#150).

A ``.wimi`` exported with *Include media* unticked carries no images. The
replace path used to rename the target's media directory aside, copy the
archive's media in (none), and delete the renamed original on success --
so importing such an archive deleted every image the profile had and put
nothing back. The database backup was kept; the media backup was not.

The owner's decision was **a checkbox at import time**. This drives the
real modal against a real archive, because the part worth guarding is not
``replace_profile`` (unit-tested in ``tests/app/test_bridge_profile_transfer.py``)
but the surface: ticked by default, and a hint that says what unticking
would actually destroy, for this profile and this archive.

The import is deliberately **not** executed here -- the choice is what is
under test, and the picker cannot replace the profile it has open anyway.

#497: which hint fires depends on whether the archive HOLDS image files,
not on the export's *Include media* choice. That box is ticked by default,
so a profile with no images exports as ``included: true, file_count: 0`` --
and the hint used to treat that as an archive with images, printing the
weaker warning for an import that deletes every image and puts none back.
The second test below exported exactly that shape and asserted the weaker
hint, so it pinned the defect; it now puts an image in the archive, and the
third test is the default-export case on its own.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``, ``tmp_path``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.foldersync_fork import await_js, poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

MODAL_READY = ("(() => typeof window.__wimiPrevDoc === 'undefined'"
               " && typeof openImportPreviewModal === 'function')()")

HINT = "document.getElementById('importReplaceKeepMediaHint').textContent"
KEEP_BOX = "document.getElementById('importReplaceKeepMedia')"
WARNED = ("document.getElementById('importReplaceKeepMediaHint')"
          ".classList.contains('profile-import-mode-hint--warning')")


def _profile_with_images(session: WimiTestSession, count: int, username: str):
    """A second profile on this computer, holding ``count`` image files.

    Written straight to disk under the media directory naming convention
    (``media/user_{id}_{username}``) -- what is being measured is the files
    a replace would delete, not what any row references.
    """
    from database.master_db import MasterDatabase

    master = MasterDatabase(data_dir=session.config.app_data_dir, error_logger=None)
    try:
        # The harness reuses one app_data directory across runs, so this has
        # to be idempotent rather than assume a clean master.
        user = master.get_user_by_username(username)
        if user is None:
            user = master.create_user(username=username, display_name="Replace Me")
        master.ensure_user_database(user.id)
        media_dir = master.data_dir / "media" / f"user_{user.id}_{user.username}"
        media_dir.mkdir(parents=True, exist_ok=True)
        for stale in media_dir.iterdir():
            if stale.is_file():
                stale.unlink()
        for i in range(count):
            (media_dir / f"cccccccc-0000-0000-0000-{i:012d}.png").write_bytes(
                b"image-bytes"
            )
        return user.id, media_dir
    finally:
        master.close()


MEDIA_LINE = "document.getElementById('importMediaInfo').textContent"


def _give_open_profile_an_image(session: WimiTestSession):
    """One image file in the open profile's media folder, so an export with
    *Include media* ticked really carries something."""
    media_dir = (session.config.app_data_dir / "media"
                 / f"user_{session.user.user_id}_{session.user.username}")
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "dddddddd-0000-0000-0000-000000000001.png").write_bytes(b"image-bytes")
    return media_dir


def _archive_of_open_profile(page: WimiPage, session: WimiTestSession,
                             dest, *, include_media: bool) -> str:
    """Export the open profile through the bridge, as the UI would.

    ``_loader.js`` renames the API object to ``window.api`` and deletes
    ``window._wimiApi`` once the modules are in, so a scenario reaches it
    by the former name only.
    """
    await_js(page, "window.api.exportProfile(" + json.dumps({
        "user_id": session.user.user_id,
        "include_media": include_media,
        "dest_path": str(dest),
    }) + ")")
    assert dest.exists(), "the export produced no archive"
    return str(dest)


def _open_preview(page: WimiPage, archive_path: str, target_user_id: int) -> None:
    """Open the import modal on an archive and choose a replace target."""
    page.eval_js(
        "window.dispatchEvent(new CustomEvent('wimi:profile-import-requested',"
        " { detail: { path: " + json.dumps(archive_path) + " } }))"
    )
    assert poll(page, "!document.getElementById('importModal').classList"
                      ".contains('hidden')", True, timeout_ms=30000) is True, (
        "the import preview modal never opened"
    )
    page.eval_js("document.getElementById('importModeReplace').checked = true;"
                 "document.getElementById('importReplaceTarget').value = "
                 + json.dumps(str(target_user_id)) + ";"
                 "updateImportControls();")


@pytest.mark.slow
@pytest.mark.regression
def test_a_media_less_archive_offers_to_keep_the_images_and_says_what_is_at_stake(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    target_id, media_dir = _profile_with_images(wimi_session, 3, "replace_three")

    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('profile-select')
    assert poll(wimi_page, MODAL_READY, True) is True, "the picker never finished loading"

    archive = _archive_of_open_profile(
        wimi_page, wimi_session, tmp_path / "no_media.wimi", include_media=False
    )
    _open_preview(wimi_page, archive, target_id)

    # Ticked by default: the answer that cannot lose anything.
    assert wimi_page.eval_js(KEEP_BOX + ".checked") is True, (
        "keeping the images must be the default (#150)"
    )
    hint = wimi_page.eval_js(HINT)
    assert "3 images" in hint, f"the hint does not say what is at stake: {hint!r}"
    assert wimi_page.eval_js(WARNED) is False, "keeping images is not a warning"

    # Unticking is the destructive choice, and has to read like one.
    wimi_page.eval_js(KEEP_BOX + ".checked = false; updateImportControls();")
    hint = wimi_page.eval_js(HINT)
    assert "Deletes all 3 images" in hint, f"unticking understates what it does: {hint!r}"
    assert "no images to put back" in hint, (
        "the archive carrying no media is the whole reason this is dangerous"
    )
    assert wimi_page.eval_js(WARNED) is True, "the destructive choice is styled as a hint"

    # Nothing was imported, so nothing was deleted.
    assert len(list(media_dir.iterdir())) == 3


@pytest.mark.slow
@pytest.mark.regression
def test_an_archive_with_media_describes_the_choice_differently(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    """With media in the archive, unticking removes only what it lacks.

    Same checkbox, different consequence -- if the hint were static it
    would be wrong in one of these two tests.
    """
    target_id, _ = _profile_with_images(wimi_session, 1, "replace_one")
    _give_open_profile_an_image(wimi_session)

    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('profile-select')
    assert poll(wimi_page, MODAL_READY, True) is True, "the picker never finished loading"

    archive = _archive_of_open_profile(
        wimi_page, wimi_session, tmp_path / "with_media.wimi", include_media=True
    )
    _open_preview(wimi_page, archive, target_id)

    assert wimi_page.eval_js(KEEP_BOX + ".checked") is True
    assert "adds the archive's" in wimi_page.eval_js(HINT)

    wimi_page.eval_js(KEEP_BOX + ".checked = false; updateImportControls();")
    hint = wimi_page.eval_js(HINT)
    assert "1 image" in hint, f"singular count not handled: {hint!r}"
    assert "does not contain" in hint, (
        "with media in the archive, unticking deletes only the images the "
        f"archive lacks -- the hint must not claim otherwise: {hint!r}"
    )

    assert "Includes 1 media file" in wimi_page.eval_js(MEDIA_LINE)


@pytest.mark.slow
@pytest.mark.regression
def test_the_default_export_of_a_profile_with_no_images_gets_the_strong_warning(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    """#497: *Include media* ticked (the default) and nothing to include.

    The archive's manifest says ``included: true`` with ``file_count: 0``.
    Replacing a profile that has images with it, unticked, deletes all of
    them and puts none back -- so it must read exactly like the archive
    exported without media in the first test, not like the one with media.
    """
    target_id, media_dir = _profile_with_images(wimi_session, 2, "replace_two")

    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('profile-select')
    assert poll(wimi_page, MODAL_READY, True) is True, "the picker never finished loading"

    archive = _archive_of_open_profile(
        wimi_page, wimi_session, tmp_path / "default_export.wimi", include_media=True
    )
    _open_preview(wimi_page, archive, target_id)

    # Positive control: this really is the #497 shape, not a media-less export.
    media = json.loads(wimi_page.eval_js("JSON.stringify(ImportState.preview.media)"))
    assert media.get("included") is True and media.get("file_count") == 0, media

    assert "Includes 0" not in wimi_page.eval_js(MEDIA_LINE), (
        "the media line claims the archive includes files when it holds none")
    assert wimi_page.eval_js(KEEP_BOX + ".checked") is True, (
        "keeping the images must stay the default (#150)")
    wimi_page.eval_js(KEEP_BOX + ".checked = false; updateImportControls();")
    hint = wimi_page.eval_js(HINT)
    assert "Deletes all 2 images" in hint and "no images to put back" in hint, (
        f"an archive holding no images got the weaker warning: {hint!r}")
    assert wimi_page.eval_js(WARNED) is True
    assert len(list(media_dir.iterdir())) == 2
