"""Regression: Reset what Save covers stops a running MCP server (#707).

``resetToDefaults()`` posted ``DEFAULTS`` (``mcp_server_enabled: false``),
redrew the form and cleared the dirty flag, and never called the one function
that starts or stops the server. So the box read unticked while the server
kept listening until the next launch, when the stored ``false`` finally
stopped it from starting. Save went through ``_applyMcpServerState``; Reset
did not. Both now go through ``_reconcileMcpServer``.

The page asks ``confirm()`` first, and QtWebEngine raises a real modal dialog
for it that nothing in the harness answers, so the scenario replaces
``window.confirm`` on the loaded page, as the question-bank reset scenario does.

The positive control is the arrange: the server must report running before
Reset is pressed, or a stopped server afterwards proves nothing.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PORT = 8123   # not 8000: a developer's wimi-db server may hold that one

READY = ("(() => { try { return settingsPage.isPageReady === true; }"
         " catch (e) { return false; } })()")


def _poll(page: WimiPage, read, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if last == want:
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _server_running(page: WimiPage):
    return page.eval_js("(async () => (await api.getMcpServerStatus()).running)()",
                        await_promise=True)


@pytest.mark.slow
@pytest.mark.regression
def test_reset_stops_a_server_the_stored_setting_had_running(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    # The stored state a student reaches by ticking the box and pressing Save.
    db.update_settings(mcp_server_enabled=True, mcp_server_port=PORT)
    assert db.get_device_settings().mcp_server_enabled is True, "arrange did not stick"

    wimi_page.goto("settings")
    assert _poll(wimi_page, lambda: wimi_page.eval_js(READY), True) is True

    # Test mode attaches the profile after launch, so the launch-time
    # auto-start never saw the setting; start it the way the launch would.
    started = wimi_page.eval_js(
        f"(async () => await api.startMcpServer({PORT}))()", await_promise=True)
    assert started.get("running") is True, f"the server did not start: {started!r}"
    assert _poll(wimi_page, lambda: _server_running(wimi_page), True) is True, (
        "positive control: the server must be running before Reset is pressed")
    assert wimi_page.eval_js("document.getElementById('mcp_server_enabled').checked") is True

    wimi_page.eval_js("window.confirm = () => true")
    wimi_page.eval_js("document.getElementById('resetDefaultsBtn').click()")

    assert _poll(wimi_page, lambda: db.get_device_settings().mcp_server_enabled, False) is False, (
        "the reset never reached the database")
    assert _poll(wimi_page, lambda: _server_running(wimi_page), False) is False, (
        "#707: the box is unticked but the MCP server is still listening")
    assert wimi_page.eval_js("document.getElementById('mcp_server_enabled').checked") is False
    status_text = wimi_page.eval_js("document.getElementById('mcpStatusText').textContent")
    assert "Running" not in status_text, f"the status line still claims a running server: {status_text!r}"
