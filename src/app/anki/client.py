"""A database-free client for the student's own AnkiConnect (#784 Wave 1).

This module is the **whole** of what runs on the Anki worker thread
(``jobs.py``), so it imports nothing from Qt and nothing from ``database`` --
``tests/app/test_anki_jobs.py`` asserts that statically, as the speech jobs'
tests do for theirs. Everything else about talking to Anki lives here so that
the rules below are stated once.

Four rules, each a decision rather than a default
-------------------------------------------------

1. **Loopback only, and by address.** The host is ``127.0.0.1`` and is not a
   parameter (owner, #784 decision 4). It is the address and not the name
   ``localhost`` because on macOS ``localhost`` may resolve to ``::1`` first,
   and AnkiConnect listens on IPv4 by default -- a connection refused there is
   indistinguishable from "Anki is closed".
2. **No proxy, ever.** The opener is built with ``ProxyHandler({})``. A bare
   ``urlopen`` honours ``HTTP_PROXY`` from the environment, and with no
   ``NO_PROXY`` entry for the address it sends the request -- the student's
   search terms and card ids -- to the proxy instead of to this machine.
   That is the no-network rule (#433) broken by an environment variable the
   student may not know is set. ``test_an_environment_proxy_is_ignored``
   carries the control that shows a default opener does exactly that.
3. **Bounded reads.** Every response is read with a ceiling and refused as
   ``TOO_LARGE`` past it, before the remainder is read. The owner chose to
   cache every field without a cap (#784 decision 3); that is a storage
   decision, and a ceiling on one HTTP response is a different one, there so a
   misbehaving listener on the port cannot exhaust memory.
4. **The question id cannot change the search.** ``build_search`` escapes
   Anki's search metacharacters in the id and refuses an id containing
   whitespace, which Anki's syntax cannot express inside an unquoted term. The
   plugin substituted the id raw, so an id containing a space, a quote or
   ``OR`` changed which cards matched.

Nothing here knows what a WIMI entry, exam or question bank is. The caller
decides what to ask for; this module says what Anki answered.
"""

from __future__ import annotations

import base64
import binascii
import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .errors import AnkiError, AnkiErrorKind

#: AnkiConnect's API version this client speaks. Every request carries it,
#: including each action inside ``multi`` -- an inner action without one is
#: treated by AnkiConnect as version 4, whose response shape differs (the
#: plugin's unused ``_anki_multi`` had exactly that latent bug).
API_VERSION = 6

#: Fixed by decision; see rule 1.
HOST = '127.0.0.1'

#: AnkiConnect's own default port.
DEFAULT_PORT = 8765

#: Seconds for the ``version`` ping, which answers instantly when Anki is
#: open. Kept short so a Settings page asking "is Anki there?" says no quickly.
PING_TIMEOUT_S = 2.0

#: Seconds for every other request. ``getReviewsOfCards`` over many cards is
#: the slowest call the feature makes.
REQUEST_TIMEOUT_S = 10.0

#: Rule 3's ceiling on any one response body, in bytes.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

#: The placeholder a search template must contain.
QID_PLACEHOLDER = '{{qid}}'

#: Characters Anki's search syntax treats specially, each escaped with a
#: backslash so the id matches literally. Backslash first, so the escapes
#: added for the others are not themselves escaped.
_SEARCH_METACHARACTERS = ('\\', '"', '*', '_', ':', '(', ')')

#: ``transport(url, body, timeout, max_bytes) -> response bytes``.
Transport = Callable[[str, bytes, float, int], bytes]


# ----------------------------------------------------------------- searching

def escape_search_term(value: str) -> str:
    """``value`` as a literal inside one Anki search term.

    Raises ``AnkiError(INVALID_SEARCH)`` for an empty value or one containing
    whitespace: outside quotes a space ends the term, and the term is the
    template's, so quoting the id alone would not keep it inside the term the
    template wrote (``tag:#A::{{qid}}`` with ``"1 2"`` substituted is
    ``tag:#A::"1 2"``, which Anki reads as two terms).
    """
    text = (value or '').strip()
    if not text:
        raise AnkiError(AnkiErrorKind.INVALID_SEARCH, 'the question id is empty')
    if any(ch.isspace() for ch in text):
        raise AnkiError(
            AnkiErrorKind.INVALID_SEARCH,
            f'the question id {text!r} contains a space, which an Anki search '
            'term cannot hold',
        )
    for ch in _SEARCH_METACHARACTERS:
        text = text.replace(ch, '\\' + ch)
    # A leading '-' negates a term; escaped, it is a literal hyphen.
    if text.startswith('-'):
        text = '\\' + text
    return text


def validate_template(template: str) -> str:
    """The template, stripped, or ``AnkiError(INVALID_SEARCH)`` with a reason.

    A template without the placeholder would find the same cards for every
    question in the bank -- a search that is valid to Anki and wrong for every
    entry it is attached to -- so it is refused rather than accepted.
    """
    text = (template or '').strip()
    if not text:
        raise AnkiError(AnkiErrorKind.INVALID_SEARCH, 'the search template is empty')
    if QID_PLACEHOLDER not in text:
        raise AnkiError(
            AnkiErrorKind.INVALID_SEARCH,
            f'the search template has no {QID_PLACEHOLDER}, so it would find '
            'the same cards for every question',
        )
    return text


def build_search(template: str, question_id: str) -> str:
    """``template`` with every ``{{qid}}`` replaced by the escaped id."""
    return validate_template(template).replace(
        QID_PLACEHOLDER, escape_search_term(question_id)
    )


# ----------------------------------------------------------------- transport

def _urllib_transport(url: str, body: bytes, timeout: float, max_bytes: int) -> bytes:
    """The real transport: one POST, no proxy, a bounded read."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        url, data=body, method='POST',
        headers={'Content-Type': 'application/json'},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise AnkiError(AnkiErrorKind.PROTOCOL, f'HTTP {exc.code} from {url}') from exc
    except urllib.error.URLError as exc:
        raise AnkiError(AnkiErrorKind.UNAVAILABLE, str(exc.reason)) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise AnkiError(AnkiErrorKind.UNAVAILABLE, f'timed out after {timeout} s') from exc
    except OSError as exc:  # reset mid-read, refused after accept
        raise AnkiError(AnkiErrorKind.UNAVAILABLE, str(exc)) from exc
    if len(data) > max_bytes:
        raise AnkiError(
            AnkiErrorKind.TOO_LARGE,
            f'the response exceeded {max_bytes} bytes',
        )
    return data


# -------------------------------------------------------------------- client

class AnkiConnectClient:
    """One conversation partner: AnkiConnect on this machine's ``port``.

    Stateless apart from its configuration, so a job may build one per run.
    ``transport`` is injectable so unit tests need no socket; the suite's
    integration tests use the real one against ``tests/_fake_ankiconnect.py``.
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        *,
        transport: Optional[Transport] = None,
        timeout: float = REQUEST_TIMEOUT_S,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f'port must be an integer from 1 to 65535, not {port!r}')
        self.port = port
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self._transport: Transport = transport or _urllib_transport

    @property
    def url(self) -> str:
        return f'http://{HOST}:{self.port}'

    # ------------------------------------------------------------ the wire

    def invoke(self, action: str, params: Optional[dict] = None, *,
               timeout: Optional[float] = None) -> Any:
        """Call one action and return its ``result``, or raise ``AnkiError``."""
        payload: Dict[str, Any] = {'action': action, 'version': API_VERSION}
        if params is not None:
            payload['params'] = params
        raw = self._transport(
            self.url,
            json.dumps(payload).encode('utf-8'),
            self.timeout if timeout is None else timeout,
            self.max_response_bytes,
        )
        return _unwrap(_decode(raw), action)

    def multi(self, actions: Sequence[dict]) -> List[Any]:
        """Run several actions in one request; one result per action, in order.

        Each element of ``actions`` is ``{'action': ..., 'params': {...}}``.
        An inner failure raises ``ACTION_FAILED`` naming the action, rather
        than returning a list in which one element is silently an error.
        """
        inner = []
        for item in actions:
            entry = {'action': item['action'], 'version': API_VERSION}
            if item.get('params') is not None:
                entry['params'] = item['params']
            inner.append(entry)
        results = self.invoke('multi', {'actions': inner})
        if not isinstance(results, list) or len(results) != len(inner):
            raise AnkiError(
                AnkiErrorKind.PROTOCOL,
                f'multi returned {type(results).__name__} for {len(inner)} actions',
            )
        return [_unwrap(result, entry['action']) for result, entry in zip(results, inner)]

    # ------------------------------------------------------------ actions

    def version(self) -> int:
        """AnkiConnect's API version: the ping. Short timeout (``PING_TIMEOUT_S``)."""
        result = self.invoke('version', timeout=min(self.timeout, PING_TIMEOUT_S))
        if isinstance(result, bool) or not isinstance(result, int):
            raise AnkiError(AnkiErrorKind.PROTOCOL, f'version was {result!r}')
        return result

    def find_cards(self, query: str) -> List[int]:
        return _int_list(self.invoke('findCards', {'query': query}), 'findCards')

    def cards_info(self, card_ids: Iterable[int]) -> List[dict]:
        ids = _ids(card_ids)
        if not ids:
            return []
        result = self.invoke('cardsInfo', {'cards': ids})
        if not isinstance(result, list) or not all(isinstance(c, dict) for c in result):
            raise AnkiError(AnkiErrorKind.PROTOCOL, 'cardsInfo did not return a list of cards')
        return result

    def reviews_of_cards(self, card_ids: Iterable[int]) -> Dict[int, List[dict]]:
        """Every review of each card, keyed by card id (``getReviewsOfCards``).

        AnkiConnect keys its answer by the card id as a **string**; this turns
        the keys back into ints so a caller cannot look up ``1234`` and miss
        ``"1234"``. A card with no reviews maps to an empty list.
        """
        ids = _ids(card_ids)
        if not ids:
            return {}
        result = self.invoke('getReviewsOfCards', {'cards': ids})
        if not isinstance(result, dict):
            raise AnkiError(AnkiErrorKind.PROTOCOL, 'getReviewsOfCards did not return an object')
        out: Dict[int, List[dict]] = {card_id: [] for card_id in ids}
        for key, reviews in result.items():
            try:
                card_id = int(key)
            except (TypeError, ValueError):
                raise AnkiError(AnkiErrorKind.PROTOCOL, f'review key {key!r} is not a card id')
            if not isinstance(reviews, list):
                raise AnkiError(AnkiErrorKind.PROTOCOL, f'reviews for {key} are not a list')
            out[card_id] = reviews
        return out

    def retrieve_media_file(self, filename: str) -> Optional[bytes]:
        """The bytes of one file from Anki's media folder, or ``None`` if absent.

        AnkiConnect answers ``false`` for a file it does not have; that is a
        fact about the collection, not a failure, so it is ``None`` here.
        """
        result = self.invoke('retrieveMediaFile', {'filename': filename})
        if result is False or result is None:
            return None
        if not isinstance(result, str):
            raise AnkiError(AnkiErrorKind.PROTOCOL, 'retrieveMediaFile did not return base64')
        try:
            return base64.b64decode(result, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AnkiError(AnkiErrorKind.PROTOCOL, 'retrieveMediaFile returned invalid base64') from exc

    def suspend(self, card_ids: Iterable[int]) -> None:
        self._suspension('suspend', card_ids)

    def unsuspend(self, card_ids: Iterable[int]) -> None:
        self._suspension('unsuspend', card_ids)

    def _suspension(self, action: str, card_ids: Iterable[int]) -> None:
        ids = _ids(card_ids)
        if not ids:
            # The plugin built ``IN ()`` from an empty list; refuse instead.
            raise ValueError(f'{action} needs at least one card id')
        self.invoke(action, {'cards': ids})


# ------------------------------------------------------------------ helpers

def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnkiError(AnkiErrorKind.PROTOCOL, 'the response was not JSON') from exc


def _unwrap(envelope: Any, action: str) -> Any:
    """``result`` from a version-6 envelope, or the ``error`` raised."""
    if not isinstance(envelope, dict) or 'result' not in envelope or 'error' not in envelope:
        raise AnkiError(
            AnkiErrorKind.PROTOCOL,
            f'{action}: the response is not an AnkiConnect version {API_VERSION} envelope',
        )
    if envelope['error'] is not None:
        raise AnkiError(AnkiErrorKind.ACTION_FAILED, f'{action}: {envelope["error"]}')
    return envelope['result']


def _ids(card_ids: Iterable[int]) -> List[int]:
    ids = []
    for card_id in card_ids:
        if isinstance(card_id, bool) or not isinstance(card_id, int):
            raise ValueError(f'card ids are integers, not {card_id!r}')
        ids.append(card_id)
    return ids


def _int_list(result: Any, action: str) -> List[int]:
    if not isinstance(result, list) or not all(
        isinstance(x, int) and not isinstance(x, bool) for x in result
    ):
        raise AnkiError(AnkiErrorKind.PROTOCOL, f'{action} did not return a list of ids')
    return result
