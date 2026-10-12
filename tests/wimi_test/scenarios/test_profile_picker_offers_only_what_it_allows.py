"""Regression: the profile picker does not offer routes it then blocks (#502).

Two affordances pointed at something the page refuses:

* **Delete on the open profile's card.** ``deleteProfile`` refuses the
  currently open profile, so the kebab's Delete led through a confirmation
  promising a ten-day grace period to an error in the modal. The item is now
  absent from that card -- and only that card.
* **A standing replace hint.** "The currently open profile cannot be replaced
  -- switch to another profile first" was computed from *any* target being
  the open one, which is true whenever a profile is open, and stayed up after
  a legal target was chosen. The open profile's option is already disabled and
  labelled "— currently open", so the hint is gone.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``, ``tmp_path``.
"""
from __future__ import annotations

import json
import uuid

import pytest

from _helpers.foldersync_fork import await_js, poll
from wimi_test.db.test_user import TestUser
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PICKER_READY = ("(() => typeof window.__wimiPrevDoc === 'undefined'"
                " && typeof openImportPreviewModal === 'function'"
                " && document.querySelectorAll('[data-testid=\"profile-card\"]').length > 1)()")


def _delete_offered(page: WimiPage, user_id: int) -> bool:
    return page.eval_js(
        "!!document.querySelector('[data-testid=\"profile-card\"][data-user-id=\"%d\"] "
        "[data-testid=\"profile-delete\"]')" % user_id)


@pytest.mark.slow
@pytest.mark.regression
def test_the_picker_offers_only_what_it_allows(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    other = TestUser(wimi_session._master_db, scenario="picker502",
                     run_id=uuid.uuid4().hex[:8])
    try:
        wimi_page.eval_js("window.__wimiPrevDoc = true")
        wimi_page.goto('profile-select')
        assert poll(wimi_page, PICKER_READY, True) is True, "the picker never listed both profiles"

        # Positive control: Delete is still offered on a profile that can be deleted.
        assert _delete_offered(wimi_page, other.user_id), (
            "Delete vanished from a profile that is not open")
        assert not _delete_offered(wimi_page, wimi_session.user.user_id), (
            "Delete is offered on the open profile, which deleteProfile refuses")

        archive = tmp_path / "open.wimi"
        await_js(wimi_page, "window.api.exportProfile(" + json.dumps({
            "user_id": wimi_session.user.user_id, "include_media": False,
            "dest_path": str(archive)}) + ")")
        wimi_page.eval_js(
            "window.dispatchEvent(new CustomEvent('wimi:profile-import-requested',"
            " { detail: { path: " + json.dumps(str(archive)) + " } }))")
        assert poll(wimi_page, "!document.getElementById('importModal').classList"
                               ".contains('hidden')", True, timeout_ms=30000) is True
        wimi_page.eval_js("document.getElementById('importModeReplace').checked = true;"
                          "updateImportControls();")

        options = json.loads(wimi_page.eval_js("""JSON.stringify(
            [...document.querySelectorAll('#importReplaceTarget option')]
              .filter(o => o.value).map(o => ({id: +o.value, disabled: o.disabled, text: o.textContent})))"""))
        current = [o for o in options if o["id"] == wimi_session.user.user_id]
        assert current and current[0]["disabled"] and "currently open" in current[0]["text"], (
            f"the open profile's option must still carry the reason itself: {options}")

        visible_text = wimi_page.eval_js(
            "document.getElementById('importReplaceOptions').innerText")
        assert "cannot be replaced" not in visible_text, (
            f"the standing 'cannot be replaced' hint is still shown: {visible_text!r}")
    finally:
        other.drop()
