"""What went wrong extracting relations, at the granularity the student acts on.

Mirrors ``app/stt/errors.py``, which #59 built for the same shape of problem: a
downloaded model, a subprocess-or-worker that can fail several ways, and a UI
that must not offer a button which cannot work.

The one rule worth repeating from that module
---------------------------------------------
``RETRYABLE`` is not decoration. #174 established that a message may not direct
a press when nothing is pressable, and the guard for it sweeps real copy. A
kind that is not retryable either needs an action outside WIMI or will fail
identically on a second press, and offering "Try again" in those cases is worse
than offering nothing -- it spends the student's attention on a button that
cannot help.

Availability is NOT an error
----------------------------
There is deliberately no ``NOT_AVAILABLE`` kind. Whether this build can extract
at all is :mod:`availability`'s question, answered before anything is
attempted, and its states are reported as a line in Settings rather than raised
at the student (#60, owner's decision). An exception type for "the feature you
were never offered is absent" would invite the entry form to catch and display
it, which is exactly the silence that decision asks for.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class RelationExtractionErrorKind(str, Enum):
    """``str`` mixin so a kind serialises through the bridge as its own name."""

    # -- the model ----------------------------------------------------------
    #: Weights absent where the spec says they should be. Distinct from
    #: MODEL_CORRUPT because the fixes differ: fetch it, versus fetch it again.
    MODEL_MISSING = 'model_missing'
    #: Present, but its digest or size does not match the pin. A truncated
    #: download must say so rather than failing later as a cryptic load error.
    MODEL_CORRUPT = 'model_corrupt'
    MODEL_LOAD_FAILED = 'model_load_failed'

    # -- acquisition --------------------------------------------------------
    DOWNLOAD_FAILED = 'download_failed'
    DOWNLOAD_CANCELLED = 'download_cancelled'

    # -- inference ----------------------------------------------------------
    EXTRACTION_FAILED = 'extraction_failed'
    #: The worker exceeded its wall-clock ceiling and was stopped, so one
    #: wedged pass cannot hold the single worker forever. Mirrors #59's
    #: TRANSCRIPTION_TIMEOUT for the same reason.
    EXTRACTION_TIMEOUT = 'extraction_timeout'
    #: Inference ran out of memory. Its own kind because the honest advice is
    #: specific -- close something, or use the smaller model -- and because an
    #: 8 GB machine is a real target (one of this project's own Macs).
    OUT_OF_MEMORY = 'out_of_memory'

    # -- the job layer ------------------------------------------------------
    #: Polled for a job id the executor never issued or has already handed out.
    #: Mirrors the folder-sync and STT job contracts.
    UNKNOWN_JOB = 'unknown_job'


#: Kinds where offering a retry is honest.
#:
#: ``MODEL_MISSING`` and ``MODEL_CORRUPT`` are **not** here: both need a
#: download, which is a different action from "try that again", and #59 found
#: the same split. ``OUT_OF_MEMORY`` is not here either -- a second identical
#: pass on the same text and the same machine fails the same way, and inviting
#: it wastes another multi-second wait to reach the same place.
RETRYABLE = frozenset({
    RelationExtractionErrorKind.MODEL_LOAD_FAILED,
    RelationExtractionErrorKind.EXTRACTION_FAILED,
    RelationExtractionErrorKind.EXTRACTION_TIMEOUT,
    RelationExtractionErrorKind.DOWNLOAD_FAILED,
})


class RelationExtractionError(Exception):
    """An extraction failure the student may need to be told about.

    Carries ``kind`` so the UI can decide what to offer without parsing a
    message, and ``detail`` for anything a log should keep but a student should
    not read.

    **The second positional argument is the message, not the detail**, and
    that is the opposite of ``SttError(kind, detail='')``. The two classes are
    otherwise near-identical and #59's code is what #60's is written from, so
    the mistake is one copy away: ``to_dict`` deliberately omits the message,
    so ``RelationExtractionError(kind, str(exc))`` reaches the page as a bare
    kind with ``detail: null`` and the only description of the failure left in
    the log. It happened once in the download slot and was caught by a test
    asserting the exception text survives. Pass ``detail=`` explicitly.
    """

    def __init__(
        self,
        kind: RelationExtractionErrorKind,
        message: str,
        detail: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = detail

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE

    def to_dict(self) -> dict:
        """The shape the bridge serialises into a failed response.

        The same three keys as ``SttError.to_dict``, so a page that renders one
        feature's failure can render the other's. The message is deliberately
        absent: copy is chosen from ``kind``, and ``detail`` is for the log.
        """
        return {
            'kind': self.kind.value,
            'detail': self.detail,
            'retryable': self.retryable,
        }

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (f"{type(self).__name__}({self.kind.value!r}, "
                f"{self.message!r}, retryable={self.retryable})")
