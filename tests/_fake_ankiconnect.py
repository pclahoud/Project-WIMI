"""A fake AnkiConnect for the suite (#784).

A real HTTP server on ``127.0.0.1`` and an ephemeral port, speaking
AnkiConnect's version-6 envelope for the actions WIMI uses. It exists so every
layer -- the client, the jobs, the bridge, and scenarios driving a spawned
WIMI -- can be tested with no Anki installed and no network, and so a test can
make Anki slow, absent, wrong or refusing on purpose.

The collection is plain data the test writes into: ``searches`` maps a search
string to card ids (so a test asserts the *exact* search WIMI built),
``cards`` maps a card id to its ``cardsInfo`` dict, ``reviews`` a card id to
its review rows, ``media`` a filename to bytes. ``requests`` records every
action received, in order, inner ``multi`` actions included.

Knobs: ``delay_s`` sleeps before every answer; ``fail_actions`` maps an action
to the error text AnkiConnect should return for it; ``raw_response`` replaces
the whole body with bytes of the test's choosing (malformed JSON, a wrong
envelope).

Usage::

    with FakeAnkiConnect() as anki:
        anki.searches['tag:q::1'] = [101]
        client = AnkiConnectClient(anki.port)
"""

from __future__ import annotations

import base64
import http.server
import json
import threading
import time
from typing import Any, Dict, List, Optional

API_VERSION = 6


class FakeAnkiConnect:
    def __init__(self) -> None:
        self.searches: Dict[str, List[int]] = {}
        self.cards: Dict[int, dict] = {}
        self.reviews: Dict[int, List[dict]] = {}
        self.media: Dict[str, bytes] = {}
        self.requests: List[dict] = []
        self.delay_s: float = 0.0
        self.fail_actions: Dict[str, str] = {}
        self.raw_response: Optional[bytes] = None
        self.version: int = API_VERSION
        self._lock = threading.Lock()
        self._httpd: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- lifecycle

    @property
    def port(self) -> int:
        assert self._httpd is not None, 'start the fake first'
        return self._httpd.server_address[1]

    def start(self) -> 'FakeAnkiConnect':
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_POST(self):  # noqa: N802 - stdlib naming
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length)
                reply = fake._answer(body)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(reply)))
                self.end_headers()
                try:
                    self.wfile.write(reply)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client timed out and went away

            def log_message(self, *args):
                pass

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._httpd = Server(('127.0.0.1', 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._httpd = None
        self._thread = None

    def __enter__(self) -> 'FakeAnkiConnect':
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -------------------------------------------------------------- collection

    def add_card(self, card_id: int, *, note_id: int, queue: int = 0, **fields: Any) -> dict:
        """A ``cardsInfo``-shaped card with sensible defaults; returns it."""
        card = {
            'cardId': card_id, 'note': note_id, 'deckName': 'Default',
            'modelName': 'Basic', 'interval': 0, 'due': 0, 'reps': 0,
            'lapses': 0, 'queue': queue, 'type': 0, 'ord': 0,
            'fields': {}, 'question': '', 'answer': '',
        }
        card.update(fields)
        self.cards[card_id] = card
        return card

    def actions(self) -> List[str]:
        with self._lock:
            return [r.get('action') for r in self.requests]

    # ------------------------------------------------------------------ server

    def _answer(self, body: bytes) -> bytes:
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.raw_response is not None:
            return self.raw_response
        try:
            request = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._envelope(None, 'request was not JSON')
        return json.dumps(self._dispatch(request)).encode('utf-8')

    def _dispatch(self, request: dict) -> dict:
        with self._lock:
            self.requests.append(request)
        action = request.get('action')
        if request.get('version') != API_VERSION:
            # Real AnkiConnect answers older versions in an older shape; WIMI
            # must never send one, so the fake makes it an error to notice.
            return {'result': None, 'error': f'fake speaks only version {API_VERSION}'}
        if action in self.fail_actions:
            return {'result': None, 'error': self.fail_actions[action]}
        params = request.get('params') or {}
        handler = getattr(self, f'_do_{action}', None)
        if handler is None:
            return {'result': None, 'error': 'unsupported action'}
        try:
            return {'result': handler(params), 'error': None}
        except Exception as exc:  # noqa: BLE001 - surfaced as AnkiConnect would
            return {'result': None, 'error': str(exc)}

    @staticmethod
    def _envelope(result: Any, error: Optional[str]) -> bytes:
        return json.dumps({'result': result, 'error': error}).encode('utf-8')

    def _do_version(self, params):
        return self.version

    def _do_findCards(self, params):  # noqa: N802 - AnkiConnect naming
        return list(self.searches.get(params['query'], []))

    def _do_cardsInfo(self, params):  # noqa: N802
        return [self.cards[c] if c in self.cards else {} for c in params['cards']]

    def _do_getReviewsOfCards(self, params):  # noqa: N802
        return {str(c): list(self.reviews.get(c, [])) for c in params['cards']}

    def _do_retrieveMediaFile(self, params):  # noqa: N802
        data = self.media.get(params['filename'])
        return False if data is None else base64.b64encode(data).decode('ascii')

    def _do_suspend(self, params):
        for card_id in params['cards']:
            if card_id in self.cards:
                self.cards[card_id]['queue'] = -1
        return True

    def _do_unsuspend(self, params):
        # Anki restores the queue from the card's type (relearning goes back
        # to learning), not to 0 -- the #800 review's note 3.
        for card_id in params['cards']:
            if card_id in self.cards:
                card_type = self.cards[card_id].get('type', 0)
                self.cards[card_id]['queue'] = 1 if card_type == 3 else card_type
        return True

    def _do_multi(self, params):
        return [self._dispatch(inner) for inner in params['actions']]
