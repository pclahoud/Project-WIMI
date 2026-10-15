"""Memory figures estimated from a card's review log (#784 Wave 1, decision 11).

AnkiConnect cannot read Anki's stored FSRS memory state, so every figure here
is **derived from the review log** and is an **estimate**. The owner's
decision 11 is to show stability and retrievability *labelled estimated*,
computed with the FSRS-4.5-and-later forgetting curve, and to show the log's
``factor`` as *Ease* rather than as *Difficulty*. This module is pure -- no
clock, no database, no Qt -- so every number it produces has a golden test.

The curve
---------

FSRS-4.5 and FSRS-5 model recall probability after ``t`` days for a card of
stability ``S`` (days) as::

    R(t, S) = (1 + FACTOR * t / S) ** DECAY,   DECAY = -0.5,  FACTOR = 19/81

``FACTOR`` is chosen so that ``R(S, S) = 0.9``: stability is the number of
days until recall falls to 90%. The plugin this replaces used FSRS v4's
constants (``DECAY = -1``, ``FACTOR = 1/9``), which agree only at ``t = S``
and diverge either side of it. FSRS-6 makes the decay a per-user learned
parameter, which AnkiConnect does not expose, so it cannot be reproduced here;
that is one more reason the figures are labelled estimates.

What "stability" is estimated from, and when it is wrong
--------------------------------------------------------

The estimate is the interval Anki scheduled at the card's most recent review
(the log's ``ivl``). With FSRS and a desired retention of 0.9 the scheduled
interval *is* the stability, so the estimate is exact there and approximate
at any other retention -- a student at 0.85 has intervals longer than S. A
negative ``ivl`` is a learning-step interval in **seconds**; ``0`` (a card
reset to new) has no stability, and none is invented.

What "ease" is, and the one thing about it that is unverified
-------------------------------------------------------------

The log's ``factor`` is SM-2's ease in permille (2500 = 250%). The plugin
displayed it as *Difficulty %*; decision 11 relabels it *Ease*, which is what
it is under SM-2. **Whether an FSRS-enabled Anki repurposes that column is not
established here** -- it was not measured against a real FSRS collection while
writing this module, and it should be before the figure is described to a
student as anything more than "the log's ease value".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Optional

#: FSRS-4.5+ forgetting-curve decay.
DECAY = -0.5
#: FSRS-4.5+ factor, ``0.9 ** (1 / DECAY) - 1``, so that R(S, S) = 0.9.
FACTOR = 19 / 81

MS_PER_DAY = 86_400_000
SECONDS_PER_DAY = 86_400


def retrievability(elapsed_days: float, stability_days: float) -> float:
    """Recall probability, 0..1, after ``elapsed_days`` at ``stability_days``.

    A review in the future (clock skew between machines, or a log written by a
    device whose clock was ahead) is clamped to zero elapsed days rather than
    producing a probability above 1.
    """
    if stability_days <= 0:
        raise ValueError(f'stability must be positive, not {stability_days!r}')
    elapsed = max(0.0, float(elapsed_days))
    return (1.0 + FACTOR * elapsed / stability_days) ** DECAY


def stability_from_interval(ivl: Optional[int]) -> Optional[float]:
    """Days of stability implied by a log ``ivl``; ``None`` when there is none.

    Positive is days; negative is a learning step in seconds; zero or missing
    is a card with no scheduled interval.
    """
    if ivl is None or isinstance(ivl, bool) or not isinstance(ivl, (int, float)) or ivl == 0:
        return None
    if ivl > 0:
        return float(ivl)
    return -float(ivl) / SECONDS_PER_DAY


def ease_percent(factor: Optional[int]) -> Optional[float]:
    """The log's ``factor`` (permille) as a percentage; ``None`` when absent.

    A factor of 0 appears on learning and manual entries and carries no ease.
    """
    if factor is None or isinstance(factor, bool) or not isinstance(factor, (int, float)):
        return None
    if factor <= 0:
        return None
    return factor / 10.0


@dataclass(frozen=True)
class MemoryEstimate:
    """Everything derived from one card's log. Every figure may be ``None``."""

    review_count: int
    total_time_ms: int
    latest_review_ms: Optional[int]
    latest_ivl: Optional[int]
    latest_factor: Optional[int]
    stability_days: Optional[float]
    retrievability: Optional[float]
    ease_percent: Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


def estimate(reviews: Iterable[Mapping], now_ms: int) -> MemoryEstimate:
    """Derive one card's figures from its ``getReviewsOfCards`` rows at ``now_ms``.

    Each row carries ``id`` (the review's epoch milliseconds), ``ivl``,
    ``factor`` and ``time`` (milliseconds spent answering). The most recent row
    by ``id`` supplies the interval and factor; ties cannot occur, because the
    review id is the log's primary key. Rows without an integer ``id`` are
    ignored rather than guessed at.
    """
    rows = [r for r in reviews if isinstance(r.get('id'), int) and not isinstance(r.get('id'), bool)]
    total_time = 0
    for row in rows:
        spent = row.get('time')
        if isinstance(spent, int) and not isinstance(spent, bool) and spent > 0:
            total_time += spent
    if not rows:
        return MemoryEstimate(0, 0, None, None, None, None, None, None)

    latest = max(rows, key=lambda r: r['id'])
    ivl = latest.get('ivl')
    factor = latest.get('factor')
    stability = stability_from_interval(ivl)
    recall = None
    if stability is not None:
        recall = retrievability((now_ms - latest['id']) / MS_PER_DAY, stability)
    return MemoryEstimate(
        review_count=len(rows),
        total_time_ms=total_time,
        latest_review_ms=latest['id'],
        latest_ivl=ivl if isinstance(ivl, int) and not isinstance(ivl, bool) else None,
        latest_factor=factor if isinstance(factor, int) and not isinstance(factor, bool) else None,
        stability_days=stability,
        retrievability=recall,
        ease_percent=ease_percent(factor),
    )
