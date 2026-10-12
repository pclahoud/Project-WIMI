"""Regression: a folder's warnings are shown before the link is recorded (#412).

Before #412, linking a folder whose generated paths exceed Box's 255-character
limit showed one thing -- "Cloud sync folder set." -- and recorded the link;
the warning ``preflight()`` computed was discarded (measured on
Windows machine B). The owner's decision: show such warnings in the link
dialog, before anything is recorded.

Driven the way a student does it: the folder picker is the one stub (a native
dialog CDP cannot reach), then real clicks and a real Escape. Asserted:

* with warnings, a dialog lists them, focus is inside it, and the link is NOT
  yet recorded;
* Escape declines, records nothing, and does not trigger the page's own Escape
  shortcut (which discards unsaved settings);
* "Use this folder anyway" records the link with the chosen client;
* a folder with no warnings links at once, with no dialog.
"""
from __future__ import annotations

import json

import pytest

from _helpers import a11y
from _helpers.page_gate import ax_mentions, ax_snapshot, ax_summary, wait_for_release
from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

MODAL = '[data-testid="folder-sync-warning-modal"]'


def _deep_folder(tmp_path):
    folder = tmp_path / "boxdeep"
    while len(str(folder)) < 205:
        folder = folder / ("b" * 30)
    folder.mkdir(parents=True)
    return folder


def _open(page: WimiPage) -> None:
    page.goto("settings")
    assert poll(page, "!!document.querySelector('#folder-sync-provider option[value=box]')"), (
        "the folder-sync provider list never loaded")
    wait_for_release(page)


def _start_link(page: WimiPage, folder, provider: str) -> None:
    page.eval_js("""(() => {
        window.__toasts = [];
        const real = settingsPage.showToast.bind(settingsPage);
        settingsPage.showToast = (m, t) => { window.__toasts.push([t, m]); return real(m, t); };
        window.__cancelled = 0;
        const realCancel = settingsPage.cancelChanges.bind(settingsPage);
        settingsPage.cancelChanges = () => { window.__cancelled += 1; return realCancel(); };
        api.pickFolderSyncFolder = async () => ({folder: %s});
        document.getElementById('folder-sync-provider').value = %s;
        window.__linkDone = undefined;
        settingsPage.chooseFolderSyncFolder().then(v => { window.__linkDone = v; });
        return true;
    })()""" % (json.dumps(str(folder)), json.dumps(provider)))


def _link(page: WimiPage) -> dict:
    return json.loads(page.eval_js(
        "(async () => JSON.stringify(await api.getFolderSyncLink()))()", await_promise=True))


@pytest.mark.slow
@pytest.mark.regression
def test_warnings_are_shown_before_the_link_and_escape_records_nothing(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = _deep_folder(tmp_path)
    _open(wimi_page)
    a11y.enable(wimi_page)
    before = ax_snapshot(wimi_page)
    assert ax_mentions(before, "Reset what Save covers"), (
        f"positive control: the page's own controls should be exposed before the "
        f"dialog opens. {ax_summary(before)}")
    _start_link(wimi_page, folder, "box")

    assert poll(wimi_page, "!!document.querySelector('%s')" % MODAL, timeout_ms=20000), (
        "no warnings dialog appeared for a folder over Box's path budget")
    listed = wimi_page.eval_js(
        "document.querySelector('[data-testid=\"folder-sync-warnings\"]').innerText")
    assert "255-character limit" in listed, listed
    assert _link(wimi_page)["linked"] is False, "the link was recorded before the student chose"

    # The boundary itself (#319). aria-modal does nothing on QtWebEngine 6.9.2
    # (measured four ways in modal_dialog.js's header), so a correct role and
    # focus inside the dialog both pass with the whole page still exposed.
    # What makes it modal here is modal_dialog.js writing aria-hidden along
    # the path to <body>; hiddenCount() is the instrument for that, and the
    # AX tree is polled because it trails a DOM change (#350).
    after = before
    for _ in range(40):
        after = ax_snapshot(wimi_page)
        if after["exposed"] * 2 < before["exposed"]:
            break
        wimi_page.wait_for_timeout(50)
    assert after["exposed"] * 2 < before["exposed"], (
        f"opening the dialog left most of the page exposed "
        f"({before['exposed']} -> {after['exposed']}): the page behind it is still "
        f"reachable by a screen reader. after: {ax_summary(after)}")
    assert not ax_mentions(after, "Reset what Save covers"), (
        f"a control behind the dialog is still exposed. {ax_summary(after)}")
    assert wimi_page.eval_js("window.ModalDialog.hiddenCount()") > 0, (
        "the tree shrank but modal_dialog.js holds no aria-hidden, so it was not "
        "the helper that drew the boundary")

    node = a11y.ax_node(wimi_page, MODAL + " [data-modal-surface]")
    assert node["role"] == "dialog" and node["name"] == "Check this folder before you use it", (
        a11y.describe(node))
    assert poll(wimi_page, "document.querySelector('%s').contains(document.activeElement)" % MODAL), (
        "focus did not move into the dialog")

    a11y.real_key(wimi_page, "Escape", settle_ms=200)
    assert poll(wimi_page, "window.__linkDone === false"), "Escape did not decline"
    assert not wimi_page.eval_js("!!document.querySelector('%s')" % MODAL)
    assert _link(wimi_page)["linked"] is False, "declining still recorded a link"
    assert wimi_page.eval_js("window.__cancelled") == 0, (
        "Escape in the dialog also fired the page's discard-unsaved-changes shortcut")
    assert poll(wimi_page, "window.ModalDialog.hiddenCount() === 0"), (
        "closing the dialog left the page aria-hidden")


@pytest.mark.slow
@pytest.mark.regression
def test_use_anyway_records_the_link_with_the_chosen_client(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = _deep_folder(tmp_path)
    _open(wimi_page)
    _start_link(wimi_page, folder, "box")
    assert poll(wimi_page, "!!document.querySelector('%s')" % MODAL, timeout_ms=20000)

    real_click(wimi_page, centre_of(wimi_page, '[data-testid="folder-sync-warning-accept"]'))
    assert poll(wimi_page, "window.__linkDone === true", timeout_ms=20000), (
        "Use this folder anyway did not complete the link")
    link = _link(wimi_page)
    assert link["linked"] is True and link["provider_id"] == "box", link
    assert link["folder"] == str(folder)
    toasts = wimi_page.eval_js("JSON.stringify(window.__toasts)")
    assert "Cloud sync folder set." in toasts, toasts


@pytest.mark.slow
@pytest.mark.regression
def test_a_folder_without_warnings_links_without_a_dialog(
    wimi_session: WimiTestSession, wimi_page: WimiPage, tmp_path,
) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    _open(wimi_page)
    _start_link(wimi_page, folder, "generic")
    assert poll(wimi_page, "window.__linkDone === true", timeout_ms=20000)
    assert not wimi_page.eval_js("!!document.querySelector('%s')" % MODAL), (
        "a dialog appeared for a folder with nothing to warn about")
    assert _link(wimi_page)["linked"] is True
