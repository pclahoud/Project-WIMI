"""Regression: profile rename / delete / restore on the picker page.

Covers the picker's management modals end to end:

1. Rename the session profile through the rename modal and assert the
   card text updates (display-name-only rename — the username is baked
   into the database filename and stays put).
2. Create a second (non-current) profile, delete it through the delete
   confirmation modal, and assert it moves to the collapsible
   "Recently deleted" section with the 10-day grace countdown.
3. Restore it from that section and assert it is back in the grid.

CDP click quirk
---------------

Per ``memory/feedback_cdp_click_quirks.md``: the cards, kebab menu
items, and modal buttons are dynamically injected, so all interactions
use ``.click()`` from ``eval_js`` rather than ``locator.click()``.
The kebab menu items are wired via event delegation on the grid, so
clicking them programmatically works even while the menu is closed.

Loader quirk: probes use ``window.api`` (NOT ``window._wimiApi``)
because ``_loader.js`` aliases then deletes the source handle.
"""
from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


def _wait_js(
    page: WimiPage,
    expression: str,
    *,
    timeout_s: float = 15.0,
    desc: str = "",
    await_promise: bool = False,
) -> Any:
    """Poll a JS expression until truthy (or raise on timeout)."""
    deadline = time.time() + timeout_s
    last: Any = None
    while time.time() < deadline:
        try:
            last = page.eval_js(expression, await_promise=await_promise)
        except Exception:
            last = None
        if last:
            return last
        time.sleep(0.25)
    raise AssertionError(
        f"Timed out after {timeout_s}s waiting for "
        f"{desc or expression!r}; last observed value: {last!r}"
    )


@pytest.mark.slow
@pytest.mark.regression
def test_profile_rename_delete_restore(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
    wimi_master_db: Any,  # session-scoped: guarantees app_data_test cleanup
) -> None:
    """Rename via modal; delete a non-current profile; restore it."""
    session_user_id = wimi_session.user.user_id
    new_display_name = "Renamed Via Modal"

    wimi_page.goto("profile-select")
    _wait_js(
        wimi_page,
        f"!!document.querySelector('.profile-card[data-user-id=\"{session_user_id}\"]')",
        desc="session profile card rendered",
    )

    # ================== 1. Rename via the modal =======================
    wimi_page.eval_js(
        f"""document.querySelector(
            '.profile-card[data-user-id="{session_user_id}"] [data-action="rename"]'
        ).click()"""
    )
    _wait_js(
        wimi_page,
        "document.getElementById('renameModal').classList.contains('active')",
        desc="rename modal open",
    )
    wimi_page.eval_js(
        f"""
        (() => {{
            document.getElementById('renameInput').value = {json.dumps(new_display_name)};
            document.getElementById('renameSaveBtn').click();
        }})()
        """
    )
    # Save handler awaits renameProfile then reloads the grid.
    _wait_js(
        wimi_page,
        f"""
        (() => {{
            const card = document.querySelector(
                '.profile-card[data-user-id="{session_user_id}"]'
            );
            return !!card && card.querySelector('.profile-card-name')
                ?.textContent === {json.dumps(new_display_name)};
        }})()
        """,
        desc="card shows the new display name",
    )
    modal_still_open = wimi_page.eval_js(
        "document.getElementById('renameModal').classList.contains('active')"
    )
    assert not modal_still_open, "Rename modal did not close after saving."

    # ================== 2. Delete a non-current profile ===============
    username2 = f"mng_{uuid4().hex[:8]}"
    created = wimi_page.eval_js(
        f"""
        window.api.createProfile({{
            username: {json.dumps(username2)},
            display_name: 'Delete Me'
        }})
        """,
        await_promise=True,
    )
    victim_id = created.get("id")
    assert isinstance(victim_id, int), f"createProfile returned {created!r}"

    # Refresh the grid so the new card exists, then open its delete modal.
    wimi_page.eval_js("loadProfiles()", await_promise=True)
    _wait_js(
        wimi_page,
        f"!!document.querySelector('.profile-card[data-user-id=\"{victim_id}\"]')",
        desc="card for the to-be-deleted profile",
    )
    wimi_page.eval_js(
        f"""document.querySelector(
            '.profile-card[data-user-id="{victim_id}"] [data-action="delete"]'
        ).click()"""
    )
    _wait_js(
        wimi_page,
        "document.getElementById('deleteModal').classList.contains('active')",
        desc="delete confirmation modal open",
    )
    wimi_page.eval_js("document.getElementById('deleteConfirmBtn').click()")

    # Card leaves the grid; "Recently deleted" section appears.
    _wait_js(
        wimi_page,
        f"!document.querySelector('.profile-card[data-user-id=\"{victim_id}\"]')",
        desc="deleted profile's card removed from the grid",
    )
    _wait_js(
        wimi_page,
        "!document.getElementById('deletedSection').classList.contains('hidden')",
        desc="'Recently deleted' section visible",
    )

    # Expand the section and check the row + days-remaining countdown.
    wimi_page.eval_js("document.getElementById('deletedToggle').click()")
    days_text = _wait_js(
        wimi_page,
        f"""
        (() => {{
            const row = document.querySelector(
                '.profile-deleted-row[data-user-id="{victim_id}"]'
            );
            return row
                ? row.querySelector('.profile-deleted-days')?.textContent
                : null;
        }})()
        """,
        desc="deleted row with days-remaining label",
    )
    assert days_text == "10 days remaining", (
        f"Fresh soft-delete should report the full 10-day grace period; "
        f"got {days_text!r}"
    )

    # ================== 3. Restore =====================================
    wimi_page.eval_js(
        f"""document.querySelector(
            '.profile-deleted-row[data-user-id="{victim_id}"] [data-action="restore"]'
        ).click()"""
    )
    _wait_js(
        wimi_page,
        f"!!document.querySelector('.profile-card[data-user-id=\"{victim_id}\"]')",
        desc="restored profile's card back in the grid",
    )
    deleted_section_hidden = wimi_page.eval_js(
        "document.getElementById('deletedSection').classList.contains('hidden')"
    )
    assert deleted_section_hidden, (
        "'Recently deleted' section should hide once its only entry is restored."
    )

    # Backend agrees: profile is active again in the registry.
    profiles = wimi_page.eval_js("window.api.listProfiles()", await_promise=True)
    active_ids = {p["id"] for p in profiles.get("profiles") or []}
    assert victim_id in active_ids, (
        f"Restored profile id={victim_id} missing from active list: "
        f"{sorted(active_ids)!r}"
    )
    assert not any(
        d["id"] == victim_id for d in profiles.get("deleted") or []
    ), "Restored profile still listed in the deleted section payload."
