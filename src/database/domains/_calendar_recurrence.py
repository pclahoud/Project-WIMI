"""Weekly recurrence for planned sessions (#778, owner decision 2).

Pure functions over local calendar dates; no database, no clock. A series
row holds one RRULE string and its ``planned_date`` is the series start.
Occurrences are **expanded on read** by :func:`expand_weekly` and never
stored, so the table holds one row per series and analytics stay untouched.

The supported subset of RFC 5545 RRULE is deliberately small:

    FREQ=WEEKLY[;INTERVAL=n][;BYDAY=MO,TU,...][;UNTIL=YYYYMMDD | ;COUNT=n]

``FREQ`` must be ``WEEKLY``; anything else is refused by :func:`parse_rrule`
with a sentence, never a traceback, so a bad rule from the page never
reaches the table. ``BYDAY`` defaults to the start date's weekday. ``COUNT``
counts occurrences from the start date; ``UNTIL`` is inclusive and a DATE
(no time), matching ``planned_date``. Both absent means open-ended, and
the caller bounds the expansion with a range, which every caller has.

The iCal exporter re-emits the parsed rule rather than the stored string,
so a rule that parses here is one that exports cleanly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator, List, Optional, Tuple

_WEEKDAYS: Tuple[str, ...] = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


class RecurrenceRuleError(ValueError):
    """A recurrence rule outside the supported subset, with a sentence."""


@dataclass(frozen=True)
class WeeklyRule:
    interval: int = 1
    by_day: Tuple[int, ...] = ()          # 0 = Monday ... 6 = Sunday, sorted
    until: Optional[date] = None          # inclusive
    count: Optional[int] = None

    def to_rrule(self, start: date) -> str:
        """Canonical RRULE text for storage and export."""
        days = self.by_day or (start.weekday(),)
        parts = ["FREQ=WEEKLY"]
        if self.interval != 1:
            parts.append(f"INTERVAL={self.interval}")
        parts.append("BYDAY=" + ",".join(_WEEKDAYS[d] for d in days))
        if self.until is not None:
            parts.append("UNTIL=" + self.until.strftime("%Y%m%d"))
        if self.count is not None:
            parts.append(f"COUNT={self.count}")
        return ";".join(parts)


def parse_rrule(text: str) -> WeeklyRule:
    """Parse the supported RRULE subset or raise :class:`RecurrenceRuleError`."""
    if not isinstance(text, str) or not text.strip():
        raise RecurrenceRuleError("a recurrence rule must be text like FREQ=WEEKLY;BYDAY=TU")
    seen = {}
    for part in text.strip().rstrip(";").split(";"):
        if "=" not in part:
            raise RecurrenceRuleError(f"recurrence rule part {part!r} is not NAME=VALUE")
        name, value = part.split("=", 1)
        name = name.strip().upper()
        if name in seen:
            raise RecurrenceRuleError(f"recurrence rule names {name} twice")
        seen[name] = value.strip()
    if seen.get("FREQ", "").upper() != "WEEKLY":
        raise RecurrenceRuleError("only FREQ=WEEKLY is supported")
    unknown = set(seen) - {"FREQ", "INTERVAL", "BYDAY", "UNTIL", "COUNT"}
    if unknown:
        raise RecurrenceRuleError(
            f"recurrence rule uses unsupported part(s): {', '.join(sorted(unknown))}")
    interval = 1
    if "INTERVAL" in seen:
        try:
            interval = int(seen["INTERVAL"])
        except ValueError:
            raise RecurrenceRuleError("INTERVAL must be a whole number") from None
        if not 1 <= interval <= 52:
            raise RecurrenceRuleError("INTERVAL must be between 1 and 52 weeks")
    by_day: Tuple[int, ...] = ()
    if "BYDAY" in seen:
        days = []
        for token in seen["BYDAY"].split(","):
            token = token.strip().upper()
            if token not in _WEEKDAYS:
                raise RecurrenceRuleError(f"BYDAY value {token!r} is not one of {', '.join(_WEEKDAYS)}")
            days.append(_WEEKDAYS.index(token))
        if not days:
            raise RecurrenceRuleError("BYDAY names no day")
        by_day = tuple(sorted(set(days)))
    if "UNTIL" in seen and "COUNT" in seen:
        raise RecurrenceRuleError("a rule may carry UNTIL or COUNT, not both")
    until = None
    if "UNTIL" in seen:
        raw = seen["UNTIL"]
        if len(raw) != 8 or not raw.isdigit():
            raise RecurrenceRuleError("UNTIL must be a date written YYYYMMDD")
        try:
            until = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
        except ValueError:
            raise RecurrenceRuleError(f"UNTIL {raw!r} is not a real date") from None
    count = None
    if "COUNT" in seen:
        try:
            count = int(seen["COUNT"])
        except ValueError:
            raise RecurrenceRuleError("COUNT must be a whole number") from None
        if not 1 <= count <= 520:
            raise RecurrenceRuleError("COUNT must be between 1 and 520 occurrences")
    return WeeklyRule(interval=interval, by_day=by_day, until=until, count=count)


def _iter_occurrences(start: date, rule: WeeklyRule) -> Iterator[date]:
    """Every occurrence date from ``start`` onward, in order, honouring
    BYDAY, INTERVAL, UNTIL and COUNT. Unbounded when neither UNTIL nor
    COUNT is set; callers bound it with a range."""
    days = rule.by_day or (start.weekday(),)
    week_anchor = start - timedelta(days=start.weekday())   # Monday of the start week
    produced = 0
    week = 0
    while True:
        monday = week_anchor + timedelta(weeks=week * rule.interval)
        for d in days:
            occurrence = monday + timedelta(days=d)
            if occurrence < start:
                continue
            if rule.until is not None and occurrence > rule.until:
                return
            yield occurrence
            produced += 1
            if rule.count is not None and produced >= rule.count:
                return
        week += 1
        if week > 10_000:   # defensive: 52 * 192 years; a range bound always stops sooner
            return


def expand_weekly(start: date, rule: WeeklyRule, range_start: date, range_end: date) -> List[date]:
    """Occurrence dates of a series that fall inside ``[range_start, range_end]``
    (inclusive). COUNT is counted from the series start, not from the range,
    so the fifth of five occurrences is the same date whichever month is
    being drawn."""
    if range_end < range_start:
        raise ValueError("range_end is before range_start")
    out: List[date] = []
    for occurrence in _iter_occurrences(start, rule):
        if occurrence > range_end:
            break
        if occurrence >= range_start:
            out.append(occurrence)
    return out
