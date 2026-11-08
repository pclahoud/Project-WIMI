"""Regression: a fork side's entry count renders as text, never markup (#548).

``renderForkSide`` interpolated ``side.entries`` raw. That figure comes from
the sync-folder manifest's ``stats``, which ``parse_manifest`` keeps
uncoerced and ``summarise_side`` lets override the int-coerced
``row_counts`` -- so anyone who can write a manifest into the linked folder
(the other device, or a collaborator on a shared folder) put markup into
Settings -> Cloud sync. No ``.wimi`` install is involved, so #593's schema
check is not in the path.

The fix is in two places and this file tests the rendered one: the count is
escaped where it is drawn. The Python half (a count that is not an integer is
reported as absent) is ``test_a_count_that_is_not_an_integer_is_absent``.
Driven by handing the renderer a report directly, as
``test_settings_folder_sync_panel.py`` does, because a scenario cannot arrange
a hostile manifest in a real cloud folder.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

PAYLOAD = '<img src=x data-testid="fork-injected" onerror="window.__forkSideRan=1">'

FRESH_DOC = "typeof window.__wimiPrevDoc === 'undefined' && typeof window.api === 'object'"
PANEL_READY = ("typeof settingsPage === 'object'"
               " && typeof settingsPage.renderForkSide === 'function'"
               " && !!document.getElementById('folder-sync-fork-sides')")


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


def _side(name: str, entries) -> dict:
    return {"generation": 2, "parent_generation": 1, "device_id": f"dev-{name}",
            "device_name": name, "created_at": "2026-10-16T00:00:00Z",
            "bytes": 1, "blob_name": f"profile-{name}-aaaaaaaa-gen-0002.wimi",
            "entries": entries, "sessions": 1, "exam_contexts": 1, "subjects": 1,
            "encountered_first": None, "encountered_last": None,
            "logged_first": None, "logged_last": None,
            "subjects_only_here": [], "subjects_only_here_count": 0,
            "subjects_only_here_named": []}


@pytest.mark.slow
@pytest.mark.regression
def test_a_count_carrying_markup_renders_as_its_own_text(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    wimi_page.eval_js("window.__wimiPrevDoc = true")
    wimi_page.goto('settings')
    assert _poll(wimi_page, FRESH_DOC, True) is True, 'Settings page did not (re)load'
    assert _poll(wimi_page, PANEL_READY, True) is True, 'fork renderer never initialised'

    report = {"parent_generation": 1, "compared": True, "notes": [],
              "sides": [_side("HONEST", 40), _side("HOSTILE", PAYLOAD)]}
    wimi_page.eval_js(
        "window.__forkSideRan = undefined;"
        " const r = " + json.dumps(report) + ";"
        " document.getElementById('folder-sync-fork-sides').innerHTML ="
        "   r.sides.map(s => settingsPage.renderForkSide(s, r)).join('');")
    # An onerror for src=x fires on the next tasks; give it the chance.
    wimi_page.wait_for_timeout(500)

    mount = "document.getElementById('folder-sync-fork-sides')"
    # Positive control: the honest side drew, so the renderer ran.
    text = wimi_page.eval_js(mount + ".textContent")
    assert "40 entries" in text, f"the renderer drew nothing usable: {text!r}"

    assert wimi_page.eval_js(
        mount + ".querySelector('[data-testid=\"fork-injected\"]') === null"
    ), "the manifest's count became an element in the fork panel"
    assert wimi_page.eval_js("window.__forkSideRan === undefined"), (
        "the injected handler ran")
    assert PAYLOAD + " entries" in text, (
        f"the count should read back as its own text: {text!r}")
