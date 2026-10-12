"""Regression: the import preview says the archive is a profile already here (#498).

Importing a ``.wimi`` whose profile is already installed makes a second,
independent copy. ``install_profile_as_new`` always knew -- it built the
sentence below -- but only after the copy existed, as a toast, and the
preview carried no profile-identity field at all. What the preview did say was
the username collision, which is a different question.

The open profile's own export is the simplest archive that is "already
here", so the scenario exports it and opens the preview on it.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``, ``tmp_path``.
"""
from __future__ import annotations

import json

import pytest

from _helpers.foldersync_fork import await_js, poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PICKER_READY = ("(() => typeof window.__wimiPrevDoc === 'undefined'"
                " && typeof openImportPreviewModal === 'function')()")
NOTE = "document.getElementById('importAlreadyInstalled')"


@pytest.mark.slow
@pytest.mark.regression
def test_the_preview_names_the_copy_already_on_this_computer(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('profile-select')
    assert poll(wimi_page, PICKER_READY, True) is True, "the picker never finished loading"

    archive = tmp_path / "here.wimi"
    await_js(wimi_page, "window.api.exportProfile(" + json.dumps({
        "user_id": wimi_session.user.user_id, "include_media": False,
        "dest_path": str(archive)}) + ")")

    # Hidden before any preview: the note is not a standing message.
    assert wimi_page.eval_js(NOTE + ".classList.contains('hidden')") is True

    wimi_page.eval_js(
        "window.dispatchEvent(new CustomEvent('wimi:profile-import-requested',"
        " { detail: { path: " + json.dumps(str(archive)) + " } }))")
    assert poll(wimi_page, "!document.getElementById('importModal').classList"
                           ".contains('hidden')", True, timeout_ms=30000) is True

    assert wimi_page.eval_js(NOTE + ".classList.contains('hidden')") is False, (
        "the preview did not say this profile is already on this computer")
    text = wimi_page.eval_js(NOTE + ".textContent")
    assert wimi_session.user.username in text, text
    assert "second, independent copy" in text, text
    # Visible in the modal, i.e. before Import is pressed, not after.
    assert wimi_page.eval_js(
        "document.getElementById('importConfirmBtn').disabled === false"), (
        "positive control: Import is still available, so the note arrived first")
