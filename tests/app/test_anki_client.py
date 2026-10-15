"""The AnkiConnect client against a real socket and a fake AnkiConnect (#784 Wave 1).

Everything here goes over HTTP to ``tests/_fake_ankiconnect.py`` on
``127.0.0.1`` -- no Anki, no network. The tests that are about a rule rather
than an action carry a control showing the rule is what makes them pass:
the proxy test shows a default opener *is* diverted, and the closed-port test
shows the port really is closed.
"""

from __future__ import annotations

import base64
import json
import socket
import urllib.request

import pytest

from app.anki import client as client_module
from app.anki.client import (
    AnkiConnectClient,
    build_search,
    escape_search_term,
    validate_template,
)
from app.anki.errors import AnkiError, AnkiErrorKind
from tests._fake_ankiconnect import FakeAnkiConnect


@pytest.fixture
def anki():
    with FakeAnkiConnect() as fake:
        yield fake


def _closed_port() -> int:
    """A port nothing listens on: bind, read the number, close."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ searching

class TestSearch:
    def test_the_qid_is_substituted_everywhere(self):
        assert build_search('tag:A::{{qid}} OR tag:B::{{qid}}', '123') == \
            'tag:A::123 OR tag:B::123'

    @pytest.mark.parametrize('qid, escaped', [
        ('a"b', 'a\\"b'),
        ('a*b', 'a\\*b'),
        ('a_b', 'a\\_b'),
        ('a:b', 'a\\:b'),
        ('(ab)', '\\(ab\\)'),
        ('a\\b', 'a\\\\b'),
        ('-12', '\\-12'),
        ('OR', 'OR'),  # alone, with no space, it is just text inside the term
    ])
    def test_metacharacters_match_literally(self, qid, escaped):
        assert escape_search_term(qid) == escaped

    def test_backslash_is_escaped_once_not_twice(self):
        # Backslash first: the escapes added for '"' are not themselves escaped.
        assert escape_search_term('\\"') == '\\\\\\"'

    @pytest.mark.parametrize('qid', ['12 34', '12\t34', ' ', ''])
    def test_a_qid_the_syntax_cannot_hold_is_refused(self, qid):
        with pytest.raises(AnkiError) as exc:
            escape_search_term(qid)
        assert exc.value.kind is AnkiErrorKind.INVALID_SEARCH

    def test_surrounding_whitespace_is_not_part_of_the_qid(self):
        assert escape_search_term('  42 ') == '42'

    def test_a_template_without_the_placeholder_is_refused(self):
        with pytest.raises(AnkiError) as exc:
            validate_template('deck:Step2')
        assert exc.value.kind is AnkiErrorKind.INVALID_SEARCH
        assert '{{qid}}' in exc.value.detail


# ------------------------------------------------------------------- the wire

class TestActions:
    def test_every_request_is_version_6(self, anki):
        client = AnkiConnectClient(anki.port)
        client.version()
        client.find_cards('x')
        assert all(r['version'] == 6 for r in anki.requests)

    def test_ping(self, anki):
        assert AnkiConnectClient(anki.port).version() == 6

    def test_find_cards_sends_the_search_unchanged(self, anki):
        query = build_search('tag:Bank::{{qid}}', 'q_1')
        anki.searches[query] = [11, 12]
        assert AnkiConnectClient(anki.port).find_cards(query) == [11, 12]
        assert anki.requests[-1]['params'] == {'query': 'tag:Bank::q\\_1'}

    def test_cards_info_and_empty_input_sends_nothing(self, anki):
        anki.add_card(11, note_id=5, interval=3)
        client = AnkiConnectClient(anki.port)
        assert client.cards_info([]) == []
        assert anki.requests == []
        assert client.cards_info([11])[0]['interval'] == 3

    def test_reviews_are_keyed_by_int_and_every_card_is_present(self, anki):
        anki.reviews[11] = [{'id': 1, 'ivl': 1, 'factor': 2500, 'time': 900}]
        result = AnkiConnectClient(anki.port).reviews_of_cards([11, 12])
        assert set(result) == {11, 12}
        assert result[12] == []
        assert result[11][0]['time'] == 900

    def test_media_round_trips_and_absent_is_none(self, anki):
        anki.media['a.png'] = b'\x89PNG data'
        client = AnkiConnectClient(anki.port)
        assert client.retrieve_media_file('a.png') == b'\x89PNG data'
        assert client.retrieve_media_file('missing.png') is None

    def test_suspend_and_unsuspend(self, anki):
        anki.add_card(11, note_id=5)
        client = AnkiConnectClient(anki.port)
        client.suspend([11])
        assert anki.cards[11]['queue'] == -1
        client.unsuspend([11])
        assert anki.cards[11]['queue'] == 0

    def test_an_empty_suspension_is_refused_before_sending(self, anki):
        with pytest.raises(ValueError):
            AnkiConnectClient(anki.port).suspend([])
        assert anki.requests == []

    def test_card_ids_must_be_integers(self, anki):
        with pytest.raises(ValueError):
            AnkiConnectClient(anki.port).cards_info(['11'])
        with pytest.raises(ValueError):
            AnkiConnectClient(anki.port).suspend([True])

    def test_multi_versions_every_inner_action(self, anki):
        anki.searches['s'] = [1]
        results = AnkiConnectClient(anki.port).multi([
            {'action': 'version'},
            {'action': 'findCards', 'params': {'query': 's'}},
        ])
        assert results == [6, [1]]
        inner = anki.requests[0]['params']['actions']
        assert [a['version'] for a in inner] == [6, 6]

    def test_an_inner_failure_names_its_action(self, anki):
        anki.fail_actions['findCards'] = 'bad search'
        with pytest.raises(AnkiError) as exc:
            AnkiConnectClient(anki.port).multi([
                {'action': 'version'},
                {'action': 'findCards', 'params': {'query': 's'}},
            ])
        assert exc.value.kind is AnkiErrorKind.ACTION_FAILED
        assert 'findCards' in exc.value.detail and 'bad search' in exc.value.detail


# --------------------------------------------------------------- the failures

class TestFailures:
    def test_nothing_listening_is_unavailable(self):
        port = _closed_port()
        with pytest.raises(AnkiError) as exc:
            AnkiConnectClient(port).version()
        assert exc.value.kind is AnkiErrorKind.UNAVAILABLE
        assert exc.value.retryable

    def test_a_slow_answer_is_unavailable_not_a_hang(self, anki):
        anki.delay_s = 1.0
        with pytest.raises(AnkiError) as exc:
            AnkiConnectClient(anki.port, timeout=0.2).find_cards('x')
        assert exc.value.kind is AnkiErrorKind.UNAVAILABLE

    def test_the_ping_uses_the_short_timeout(self, anki, monkeypatch):
        seen = []

        def transport(url, body, timeout, max_bytes):
            seen.append(timeout)
            return json.dumps({'result': 6, 'error': None}).encode()

        AnkiConnectClient(anki.port, transport=transport, timeout=30).version()
        assert seen == [client_module.PING_TIMEOUT_S]

    def test_an_anki_error_is_action_failed_with_ankis_text(self, anki):
        anki.fail_actions['findCards'] = 'invalid search'
        with pytest.raises(AnkiError) as exc:
            AnkiConnectClient(anki.port).find_cards('x')
        assert exc.value.kind is AnkiErrorKind.ACTION_FAILED
        assert 'invalid search' in exc.value.detail
        assert not exc.value.retryable

    @pytest.mark.parametrize('raw', [
        b'not json',
        b'{"result": 6}',             # no error key
        b'[1, 2]',                    # not an envelope
        b'\xff\xfe',                  # not UTF-8
    ])
    def test_something_that_is_not_ankiconnect_is_protocol(self, anki, raw):
        anki.raw_response = raw
        with pytest.raises(AnkiError) as exc:
            AnkiConnectClient(anki.port).version()
        assert exc.value.kind is AnkiErrorKind.PROTOCOL

    def test_a_wrongly_typed_result_is_protocol(self, anki):
        anki.raw_response = b'{"result": "six", "error": null}'
        with pytest.raises(AnkiError) as exc:
            AnkiConnectClient(anki.port).version()
        assert exc.value.kind is AnkiErrorKind.PROTOCOL

    def test_an_oversized_response_is_refused(self, anki):
        anki.raw_response = json.dumps(
            {'result': base64.b64encode(b'x' * 4000).decode(), 'error': None}
        ).encode()
        with pytest.raises(AnkiError) as exc:
            AnkiConnectClient(anki.port, max_response_bytes=1000).retrieve_media_file('a')
        assert exc.value.kind is AnkiErrorKind.TOO_LARGE

    def test_invalid_base64_media_is_protocol(self, anki):
        anki.raw_response = b'{"result": "%%%not base64", "error": null}'
        with pytest.raises(AnkiError) as exc:
            AnkiConnectClient(anki.port).retrieve_media_file('a')
        assert exc.value.kind is AnkiErrorKind.PROTOCOL

    @pytest.mark.parametrize('port', [0, 65536, -1, '8765', True, 8765.0])
    def test_a_port_must_be_a_real_port(self, port):
        with pytest.raises(ValueError):
            AnkiConnectClient(port)


# --------------------------------------------------------------- the rules

class TestRules:
    def test_the_host_is_loopback_by_address(self, anki):
        assert AnkiConnectClient(anki.port).url == f'http://127.0.0.1:{anki.port}'

    def test_an_environment_proxy_is_ignored(self, anki, monkeypatch):
        """Rule 2, with the control that shows the rule is load-bearing."""
        dead_proxy = f'http://127.0.0.1:{_closed_port()}'
        for name in ('HTTP_PROXY', 'http_proxy'):
            monkeypatch.setenv(name, dead_proxy)
        for name in ('NO_PROXY', 'no_proxy'):
            monkeypatch.delenv(name, raising=False)

        # Control: a default opener sends the request to the proxy, which is
        # closed, so it fails. If this ever passes, the environment is not
        # exercising the rule and the assertion below proves nothing.
        request = urllib.request.Request(
            f'http://127.0.0.1:{anki.port}',
            data=b'{"action": "version", "version": 6}', method='POST',
        )
        with pytest.raises(OSError):
            urllib.request.build_opener().open(request, timeout=2).read()
        assert anki.requests == [], 'the control reached the fake directly'

        assert AnkiConnectClient(anki.port).version() == 6
        assert len(anki.requests) == 1
