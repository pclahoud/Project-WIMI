"""Regression: profile picker create -> select -> dashboard flow.

Covers the launch-time profile picker (``profile_select.html``) end to
end: the page renders the card grid from ``listProfiles``, the inline
"+ New profile" form creates a profile via ``createProfile``, and
clicking the new card runs ``selectProfile`` (which swaps
``bridge.user_db`` and emits ``userDatabaseLoaded`` so ``MainWindow``
rewires media/plugins) before navigating to the dashboard.

The final assertions prove the swap really happened: the bridge reports
a connected user DB (``checkConnection``) and the dashboard header
profile chip renders the new profile's display name (``landing.js``
populates it from ``getCurrentProfile``).

CDP click quirk
---------------

Per ``memory/feedback_cdp_click_quirks.md``: dynamically-injected
controls (the rendered profile cards and the inline create form) are
driven with ``.click()`` from ``eval_js`` rather than
``locator.click()`` — CDP's ``Input.dispatchMouseEvent`` can drop
events on targets whose layout was synthesised after the initial
render.

Loader quirk
------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` -> ``window.api`` then
deletes the source handle.
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
    """Poll a JS expression until it is truthy (or raise on timeout).

    Evaluation errors are swallowed while polling — a navigation in
    flight destroys the JS context and makes ``eval_js`` raise until the
    next document is up, which is an expected transient here.
    """
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
def test_profile_picker_create_and_select(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
    wimi_master_db: Any,  # session-scoped: guarantees app_data_test cleanup
) -> None:
    """Create a profile via the picker form, open it, land on the dashboard.

    Arrange: navigate to the picker (the session's own test user renders
    as the "currently open" card). Act: create a fresh profile through
    the inline form, then click its card. Assert: the app navigates to
    the dashboard, the bridge reports ``user_db_connected`` and the
    header profile chip shows the new display name.
    """
    username = f"picker_{uuid4().hex[:8]}"
    display_name = "Picker Regression"

    # ---- Arrange: picker page with the grid rendered -----------------
    wimi_page.goto("profile-select")
    _wait_js(
        wimi_page,
        "!!document.getElementById('createCardOpen')",
        desc="profile grid + create card rendered",
    )

    # ---- Act 1: create a profile through the inline form -------------
    wimi_page.eval_js("document.getElementById('createCardOpen').click()")
    filled = wimi_page.eval_js(
        f"""
        (() => {{
            const u = document.getElementById('createUsername');
            const d = document.getElementById('createDisplayName');
            if (!u || !d) return false;
            u.value = {json.dumps(username)};
            d.value = {json.dumps(display_name)};
            document.getElementById('createSubmitBtn').click();
            return true;
        }})()
        """
    )
    assert filled, "Create form inputs were not present after opening the form."

    # Grid refreshes after createProfile resolves — wait for the card.
    _wait_js(
        wimi_page,
        f"""
        [...document.querySelectorAll(
            '[data-testid="profile-card"] .profile-card-username'
        )].some(el => el.textContent === '@{username}')
        """,
        desc=f"card for @{username} in the grid",
    )

    # No create-form error should be showing.
    create_error = wimi_page.eval_js(
        "(() => { const el = document.getElementById('createError');"
        " return el && !el.classList.contains('hidden')"
        " ? el.textContent : null; })()"
    )
    assert not create_error, f"createProfile surfaced an error: {create_error!r}"

    # ---- Act 2: click the new card -> selectProfile -> dashboard -----
    clicked = wimi_page.eval_js(
        f"""
        (() => {{
            const card = [...document.querySelectorAll(
                '.profile-card[data-user-id]'
            )].find(c =>
                c.querySelector('.profile-card-username')?.textContent
                    === '@{username}'
            );
            if (!card) return false;
            card.querySelector('[data-action="select"]').click();
            return true;
        }})()
        """
    )
    assert clicked, f"Could not find/click the card for @{username}."

    # selectProfile awaits the bridge then sets location.href='index.html'.
    _wait_js(
        wimi_page,
        "window.location.href.includes('index.html')"
        " && typeof window.api === 'object'",
        desc="dashboard loaded with window.api ready",
        timeout_s=20.0,
    )

    # ---- Assert: bridge reports the swapped-in user DB ----------------
    conn = _wait_js(
        wimi_page,
        "window.api.checkConnection()",
        desc="checkConnection response",
        await_promise=True,
    )
    assert conn.get("user_db_connected") is True, (
        f"selectProfile did not leave a connected user DB: {conn!r}. "
        f"The userDatabaseLoaded -> MainWindow.set_user_database wiring "
        f"may be broken."
    )
    assert conn.get("master_db_connected") is True, f"master DB lost: {conn!r}"

    # ---- Assert: header profile chip shows the new profile -----------
    chip_name = _wait_js(
        wimi_page,
        "(() => { const el = document.getElementById('profileChipName');"
        " return el ? el.textContent : null; })()",
        desc="dashboard profile chip populated",
    )
    assert chip_name == display_name, (
        f"Dashboard profile chip shows {chip_name!r}, expected "
        f"{display_name!r} — getCurrentProfile is not reflecting the "
        f"newly selected profile."
    )
