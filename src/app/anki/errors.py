"""The AnkiConnect failure taxonomy (#784).

Every way a conversation with the student's AnkiConnect can go wrong is mapped
onto ``AnkiErrorKind`` in exactly one place -- ``client.py`` for the wire,
``jobs.py`` for the job layer -- so the page never sees a raw ``URLError`` and
never has to guess what a message means. Same shape as ``app.stt.errors``.

**Add a member at the end of its section if you genuinely need one**, with a
comment saying what produces it; do not rename or repurpose an existing one,
because the kind string crosses the bridge and the page branches on it.

The distinction that matters most
---------------------------------

``UNAVAILABLE`` and ``ACTION_FAILED`` are different facts and must stay
different. The first means *nothing answered* -- Anki is closed, the add-on is
not installed, the port is wrong -- and a caller holding cached data **keeps
it** and says it is showing what it had. The second means Anki answered and
refused. The plugin this replaces collapsed "nothing answered" into "no cards
found" and wiped its cache (#784, plan finding 1); keeping the two kinds apart
at the source is what makes that mistake hard to repeat.
"""

from __future__ import annotations

from enum import Enum


class AnkiErrorKind(str, Enum):
    """What went wrong, at the granularity a caller needs to act on.

    ``str`` mixin so a kind serialises through the bridge as its own name.
    """

    # -- the wire -------------------------------------------------------------
    #: Nothing answered on the port: connection refused, reset, or timed out.
    #: Anki closed, AnkiConnect not installed, or the wrong port. Cached data
    #: stays valid and is shown as such.
    UNAVAILABLE = 'unavailable'
    #: AnkiConnect answered with a non-null ``error`` -- an unknown action, a
    #: malformed search, a card id it does not have. The text is Anki's.
    ACTION_FAILED = 'action_failed'
    #: Something answered and it was not AnkiConnect speaking version 6: an
    #: HTTP error status, a body that is not JSON, or JSON without the
    #: ``result``/``error`` pair.
    PROTOCOL = 'protocol'
    #: The response was larger than the client agreed to read. Raised before
    #: the remainder is read, so a runaway response cannot exhaust memory.
    TOO_LARGE = 'too_large'

    # -- the search -----------------------------------------------------------
    #: A search template or question id that cannot be turned into a search
    #: that means what the student meant -- no ``{{qid}}`` placeholder, or a
    #: question id with whitespace in it. Refused before anything is sent.
    INVALID_SEARCH = 'invalid_search'

    # -- the job layer --------------------------------------------------------
    #: Polled for a job id the executor has never heard of.
    UNKNOWN_JOB = 'unknown_job'
    #: The profile open when the job finishes is not the one that started it,
    #: so its finish phase -- the one that writes to the database -- is not
    #: run. Writing one profile's card data into another is the outcome this
    #: exists to prevent.
    PROFILE_CHANGED = 'profile_changed'
    #: Anything the taxonomy does not name, with the real message in
    #: ``detail``.
    FAILED = 'failed'


#: Kinds where offering a retry is honest. ``UNAVAILABLE`` is retryable because
#: the usual cause is "Anki is not open yet"; ``ACTION_FAILED`` and
#: ``INVALID_SEARCH`` fail identically on a second press.
RETRYABLE = frozenset({
    AnkiErrorKind.UNAVAILABLE,
    AnkiErrorKind.PROTOCOL,
    AnkiErrorKind.FAILED,
})


class AnkiError(Exception):
    """A failure with a ``kind`` the UI can branch on.

    ``detail`` is for the log and for a developer -- the socket error, the
    HTTP status, AnkiConnect's own error text. Student-facing copy lives with
    the UI, as for ``SttError``.
    """

    def __init__(self, kind: AnkiErrorKind, detail: str = '') -> None:
        self.kind = AnkiErrorKind(kind)
        self.detail = detail
        super().__init__(f'{self.kind.value}: {detail}' if detail else self.kind.value)

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE

    def to_dict(self) -> dict:
        return {
            'kind': self.kind.value,
            'detail': self.detail,
            'retryable': self.retryable,
        }
