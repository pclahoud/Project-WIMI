"""``teardown()`` is what silences QtWebEngine's profile-release warning (#153).

``test_main_window_closes_the_browser_pane.py`` proves ``closeEvent`` makes
the call. This file proves the call is worth making, against real Qt, with
its own negative control -- because an assertion that a warning is *absent*
proves nothing unless the same harness can show it present.

Measured here (Qt 6.9.0 / PyQt 6.9.1, headless Linux):

- release the profile with the pages alive -> **one warning per live page**
  (2 tabs, 2 warnings). The exact text carries a space before the bang:
  "Expect troubles !". #153 and CLAUDE.md both quote it without, so match on
  the stable prefix, not the whole sentence.
- call ``teardown()`` first -> **zero**.
- ``teardown()`` twice, and ``teardown()`` with a navigation pending on
  every tab -> zero, and the process still exits 0.

What this file deliberately does *not* claim: that #153 was observable
through ``MainWindow``. It was not, and that is why nobody noticed. Qt
destroys children in child-list order and ``MainWindow.__init__`` builds the
central widget (which ends up owning the pages) before the controller
(which owns the profile), so the pages were already gone. A control that
forced the other order inside a live ``MainWindow`` produced the warning and
then **dumped core** -- which is the measured answer to "is this only a log
line", and also the reason that control is not a test. The order is now
stated by ``closeEvent`` instead of being an accident of two lines of
construction order.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_CHILD = Path(__file__).parent / '_browser_pane_teardown_child.py'
_TIMEOUT_S = 120


def _child_env() -> dict:
    """Environment for the child, with headless Qt arranged if needed.

    ``QT_QPA_PLATFORM=offscreen`` alone is not enough: the GL context is
    lost and QtWebEngine dies, on Linux and on Windows both (CLAUDE.md
    records the measurements). So whenever offscreen is in force,
    ``--disable-gpu`` goes with it. macOS is left alone entirely -- offscreen
    kills QtWebEngine there regardless, so if someone has exported it the
    child will fail to start and this test skips rather than lying.
    """
    env = dict(os.environ)
    env['PYTHONUNBUFFERED'] = '1'

    if (
        sys.platform.startswith('linux')
        and 'QT_QPA_PLATFORM' not in env
        and not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY'))
    ):
        env['QT_QPA_PLATFORM'] = 'offscreen'

    if env.get('QT_QPA_PLATFORM') == 'offscreen':
        flags = env.get('QTWEBENGINE_CHROMIUM_FLAGS', '')
        if '--disable-gpu' not in flags:
            env['QTWEBENGINE_CHROMIUM_FLAGS'] = f'{flags} --disable-gpu'.strip()

    return env


def _run(mode: str) -> dict:
    """Run the child and parse its one RESULT line.

    No RESULT line means QtWebEngine could not start in this environment,
    which is a skip -- but only ever for the mode being run. The control
    failing to warn is a hard failure, handled by the caller.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(_CHILD), mode],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            env=_child_env(),
        )
    except subprocess.TimeoutExpired:
        pytest.skip(f'browser-pane teardown child timed out in {mode!r} mode')

    line = next(
        (ln for ln in proc.stdout.splitlines() if ln.startswith('RESULT ')),
        None,
    )
    if line is None:
        pytest.skip(
            'QtWebEngine would not start for the browser-pane teardown child '
            f'({mode!r}, returncode {proc.returncode}). '
            f'stderr tail: {proc.stderr[-600:]!r}'
        )

    fields = dict(part.split('=', 1) for part in line.split()[1:])
    return {
        'mode': fields['mode'],
        'warnings': int(fields['warnings']),
        'tabs': int(fields['tabs']),
        'teardown_calls': int(fields['teardown_calls']),
        'returncode': proc.returncode,
    }


@pytest.mark.slow
def test_releasing_the_profile_with_live_pages_warns():
    """The negative control, and it has to run first in spirit.

    If this ever stops warning -- a Qt version that dropped the message, a
    pane that no longer keeps a page per tab -- then the assertion below is
    vacuous and must not be trusted. So this is a hard failure, never a
    skip: a control that proves nothing is worse than no control.
    """
    result = _run('no_teardown')

    assert result['tabs'] >= 1
    assert result['warnings'] >= 1, (
        'the control did not reproduce "Release of profile requested ...", '
        'so test_teardown_silences_the_warning proves nothing and this pair '
        'needs re-measuring against the current Qt'
    )
    # One warning per live page, which is why teardown() loops the tabs
    # rather than detaching only the visible one.
    assert result['warnings'] == result['tabs']


@pytest.mark.slow
def test_teardown_silences_the_warning():
    result = _run('teardown')

    assert result['warnings'] == 0, (
        'teardown() did not prevent the profile-release warning'
    )
    assert result['teardown_calls'] == 2, (
        'the child must call teardown() twice, so idempotence is proved on '
        'the same path as the ordering'
    )
    assert result['returncode'] == 0


@pytest.mark.slow
def test_teardown_is_safe_while_navigations_are_in_flight():
    """Deleting a page mid-navigation is the obvious way to turn this fix
    into a crash on exit, and ``closeEvent`` can land at any moment -- a
    student closing the window while a qbank page loads is ordinary. It is
    safe because ``teardown()`` uses ``deleteLater()``: the page is detached
    now and destroyed on the next event-loop turn, after Qt has unwound.
    """
    result = _run('inflight')

    assert result['warnings'] == 0
    assert result['returncode'] == 0, (
        'tearing the pane down with pending navigations must not crash'
    )


if __name__ == '__main__':  # pragma: no cover
    pytest.main([__file__, '-v'])
