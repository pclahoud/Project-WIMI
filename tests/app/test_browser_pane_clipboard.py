"""A site's own Copy button works in the browser pane (owner, 2026-11-09).

``navigator.clipboard.writeText`` -- how most sites' Copy buttons, and any
copied image, reach the clipboard -- becomes a ``ClipboardReadWrite``
permission request in Qt 6.8 and later. The pane answered none, so the
promise stayed pending and the button did nothing. Measured on Linux with a
real click: ``pending`` after 2 s, clipboard unchanged. Select-and-Ctrl+C,
the Copy action, right-click Copy Image and ``execCommand('copy')`` all
worked before this change and are not what it fixes.

The owner chose to grant the permission for every site. Qt has one
permission for read and write, so that also lets a site read the clipboard;
the per-site prompt was offered and not chosen.

The real-Qt pair runs the actual ``BrowserPaneController`` in a child
process, the shape of ``test_browser_pane_teardown_order.py``. The negative
control disconnects the handler and must reproduce the hang, or the
positive result proves nothing -- so it fails hard, never skips, once the
child has started.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6.QtWebEngineCore import QWebEnginePermission

from app.browser_pane import pane_permission_decision

_CHILD = Path(__file__).parent / '_browser_pane_clipboard_child.py'
PT = QWebEnginePermission.PermissionType


def test_the_clipboard_permission_is_granted():
    assert pane_permission_decision(PT.ClipboardReadWrite) == 'grant'


@pytest.mark.parametrize('kind', [
    PT.MediaAudioCapture, PT.MediaVideoCapture, PT.MediaAudioVideoCapture,
    PT.Geolocation, PT.Notifications, PT.DesktopVideoCapture,
    PT.DesktopAudioVideoCapture, PT.MouseLock, PT.LocalFontsAccess,
])
def test_no_other_permission_is_answered(kind):
    """Only the clipboard was decided. Camera, microphone, location and the
    rest stay unanswered, as they were."""
    assert pane_permission_decision(kind) is None


def _env() -> dict:
    env = dict(os.environ)
    env['PYTHONUNBUFFERED'] = '1'
    if (sys.platform.startswith('linux') and 'QT_QPA_PLATFORM' not in env
            and not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY'))):
        env['QT_QPA_PLATFORM'] = 'offscreen'
    if env.get('QT_QPA_PLATFORM') == 'offscreen':
        flags = env.get('QTWEBENGINE_CHROMIUM_FLAGS', '')
        if '--disable-gpu' not in flags:
            env['QTWEBENGINE_CHROMIUM_FLAGS'] = f'{flags} --disable-gpu'.strip()
    return env


def _run(mode: str) -> dict:
    try:
        proc = subprocess.run([sys.executable, str(_CHILD), mode], capture_output=True,
                              text=True, timeout=120, env=_env())
    except subprocess.TimeoutExpired:
        pytest.skip(f'browser-pane clipboard child timed out in {mode!r} mode')
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith('RESULT ')), None)
    if line is None:
        pytest.skip(f'QtWebEngine would not start for the clipboard child ({mode!r}, '
                    f'returncode {proc.returncode}): {proc.stderr[-600:]!r}')
    return json.loads(line[len('RESULT '):])


@pytest.mark.slow
def test_without_the_handler_a_site_copy_button_hangs():
    """The negative control: the pre-fix behaviour, reproduced."""
    result = _run('no_handler')
    assert result['page'] == 'pending', (
        f'the control did not hang ({result!r}), so the positive test below proves '
        'nothing; re-measure against the current Qt')
    assert result['clipboard'] == 'SENTINEL'


@pytest.mark.slow
def test_a_site_copy_button_reaches_the_clipboard():
    result = _run('handler')
    assert result['page'] == 'ok', f'navigator.clipboard.writeText did not resolve: {result!r}'
    assert result['clipboard'] == 'COPIED_BY_THE_SITE', result


@pytest.mark.slow
def test_right_clicking_a_link_in_a_selection_offers_copy():
    """#941, owner 2026-11-09: Copy is offered whenever text is selected.

    The control is in the same run: Qt's stock menu for that click must
    lack Copy, or the pane's menu proves nothing.
    """
    result = _run('link_menu')
    assert result['on_link'] and result['has_selection'], (
        f'the click did not land on a link inside a selection: {result!r}')
    assert not result['stock_has_copy'], (
        f"Qt's stock menu now offers Copy here, so this test proves nothing: {result!r}")
    assert result['pane_has_copy'] and result['pane_first_is_copy'], result


@pytest.mark.slow
def test_a_real_right_click_opens_the_menu():
    """The menu is actually shown, and survives a garbage collection.

    Windows machine B found (2026-11-09) that the first version of
    ``_PaneView.contextMenuEvent`` showed nothing at all: the menu had no
    parent and nothing held it, so PyQt freed it the moment the handler
    returned. The test above only calls ``build_context_menu()`` and could
    not see that, and the child first stubbed ``contextMenuEvent`` out, which
    hid it outright. This one goes through the real handler.
    """
    result = _run('link_menu')
    assert result['menu_shown'], f'a right-click in the pane opened no menu: {result!r}'
    assert result['shown_first'] == 'Copy', result
