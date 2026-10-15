"""Shared helpers for the Settings -> Anki scenarios (#784 Wave 3).

The panel saves each control on change and builds its template and field lists
after its own reads finish, so every helper here polls for an outcome rather
than sleeping. Buttons are pressed with a hit-tested click, because the page is
gated (``inert``) until it is ready and ``el.click()`` would pass against a
gated page.
"""
from __future__ import annotations

import json
import socket

from wimi_test.page import WimiPage

FRESH_DOC = "typeof window.__wimiPrevDoc === 'undefined' && typeof window.api === 'object'"


def poll(wimi_page: WimiPage, js: str, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def poll_true(wimi_page: WimiPage, js: str, *, timeout_ms: int = 15000) -> bool:
    return poll(wimi_page, f"!!({js})", True, timeout_ms=timeout_ms) is True


def open_panel(wimi_page: WimiPage, *, banks: int) -> None:
    """Navigate to Settings, open the Anki panel and wait for its first exam's
    bank blocks, so nothing is pressed before the panel's own reads finish."""
    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('settings')
    assert poll(wimi_page, FRESH_DOC, True) is True, 'Settings page did not (re)load'
    assert poll_true(wimi_page, "!document.querySelector('[data-page-gated]').inert"), \
        'Settings page never released its gate'
    wimi_page.locator(css='.settings-nav-item[data-panel="anki_integration"]').click()
    assert poll_true(wimi_page,
                     "document.getElementById('anki-settings').classList.contains('active')"), \
        'Anki panel did not activate'
    count = "document.querySelectorAll('#anki-template-list .anki-bank').length"
    assert poll(wimi_page, count, banks) == banks, 'Bank blocks never rendered'


def set_and_change(wimi_page: WimiPage, element_id: str, value: str) -> None:
    wimi_page.eval_js(
        "(() => { const el = document.getElementById(" + json.dumps(element_id) + ");"
        " el.value = " + json.dumps(value) + ";"
        " el.dispatchEvent(new Event('change', {bubbles: true})); })()"
    )


def text_of(wimi_page: WimiPage, element_id: str) -> str:
    return wimi_page.eval_js(
        f"document.getElementById({json.dumps(element_id)}).textContent") or ''


def is_error(wimi_page: WimiPage, element_id: str) -> bool:
    return bool(wimi_page.eval_js(
        f"document.getElementById({json.dumps(element_id)}).classList.contains('is-error')"))


def preferences(wimi_page: WimiPage) -> dict:
    """The merged settings as the app itself reads them -- device settings are
    keyed on the app's device id, which the test's own connection lacks."""
    return json.loads(wimi_page.eval_js(
        "(async () => JSON.stringify(await api.getUserPreferences()))()", await_promise=True))


def closed_port() -> int:
    """A loopback port with nothing listening: bound, read and released."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
