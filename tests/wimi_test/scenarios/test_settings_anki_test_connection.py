"""Regression: Settings -> Anki's Test connection, against a real HTTP server.

The button asks the spawned WIMI to call AnkiConnect's ``version`` on the port
in the box, through the bridge's job slots. A fake AnkiConnect on loopback is
the positive control; a port with nothing listening is the negative one, and it
must produce a sentence telling the student what to check, in the error style,
rather than a stuck "Asking..." line.

The port is saved on change, before Test is pressed, and is read back through
the app's own ``getUserPreferences`` -- the test's database connection has a
different device id, so it could not see a device setting the app wrote.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import pytest

from _helpers.anki_settings import (
    closed_port, is_error, open_panel, poll_true, preferences, set_and_change, text_of,
)
from tests._fake_ankiconnect import FakeAnkiConnect
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

STATUS = 'anki-connection-status'


def _press_test(wimi_page: WimiPage) -> None:
    wimi_page.locator(css='#anki-test-connection').click()


@pytest.mark.slow
@pytest.mark.regression
def test_test_connection_reaches_anki_and_names_a_dead_port(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.create_exam_context(exam_name='Step X')
    db.create_question_source(source_name='Bank', exam_context='Step X')

    with FakeAnkiConnect() as anki:
        open_panel(wimi_page, banks=1)

        # ---- Act: point the panel at the fake; the port saves on change
        set_and_change(wimi_page, 'anki-port', str(anki.port))
        assert poll_true(wimi_page, f"document.getElementById('{STATUS}').textContent"
                                    " === 'Saved.'"), text_of(wimi_page, STATUS)
        assert preferences(wimi_page)['ankiconnect_port'] == anki.port

        # ---- Act + Assert: Test connection answers from the fake
        _press_test(wimi_page)
        assert poll_true(wimi_page, f"document.getElementById('{STATUS}')"
                                    ".textContent.startsWith('Connected.')"), \
            text_of(wimi_page, STATUS)
        assert f'port {anki.port}' in text_of(wimi_page, STATUS)
        assert not is_error(wimi_page, STATUS)
        assert 'version' in anki.actions(), anki.actions()
        assert not wimi_page.eval_js("document.getElementById('anki-test-connection').disabled")

    # ---- Act + Assert: nothing listening is a sentence, in the error style
    dead = closed_port()
    set_and_change(wimi_page, 'anki-port', str(dead))
    _press_test(wimi_page)
    assert poll_true(wimi_page, f"document.getElementById('{STATUS}')"
                                ".textContent.startsWith('Nothing answered on port')"), \
        text_of(wimi_page, STATUS)
    assert str(dead) in text_of(wimi_page, STATUS)
    assert is_error(wimi_page, STATUS)


@pytest.mark.slow
@pytest.mark.regression
def test_an_out_of_range_port_is_refused_before_the_bridge(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db.create_exam_context(exam_name='Step X')
    db.create_question_source(source_name='Bank', exam_context='Step X')
    open_panel(wimi_page, banks=1)
    before = preferences(wimi_page)['ankiconnect_port']

    set_and_change(wimi_page, 'anki-port', '80')
    assert poll_true(wimi_page, f"document.getElementById('{STATUS}')"
                                ".textContent.startsWith('Choose a port from 1000')"), \
        text_of(wimi_page, STATUS)
    assert is_error(wimi_page, STATUS)
    assert preferences(wimi_page)['ankiconnect_port'] == before
