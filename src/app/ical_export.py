"""One-way iCalendar export of planned and past study sessions (#778).

Qt-free and stdlib-only: ``requirements-prod.txt`` is pinned and
``check_build_env.py`` refuses drift, and ``zoneinfo`` has no data on Windows
without ``tzdata``, so there is no ``TZID`` anywhere in the output.

Owner decision 11 (2026-10-12): **timed events are UTC instants** (``...Z``),
converted from the plan's local date and ``HH:MM`` through the zone the
caller supplies (the bridge passes the OS local zone; tests pass a fixed
offset so the bytes are exact). An untimed plan is an all-day event
(``VALUE=DATE``, exclusive ``DTEND``), which needs no zone at all.

RFC 5545 rules this module implements, each pinned by a test:

- CRLF line endings; folding at 75 **octets**, backing off so a multibyte
  UTF-8 sequence is never split; the continuation space counts toward the
  next line's 75.
- TEXT escaping of ``\\``, ``;``, ``,`` and newlines; other control
  characters are dropped.
- ``DTSTAMP`` is UTC and injected by the caller, so a test can assert bytes.
- ``PRODID`` carries ``APP_VERSION`` imported, never retyped.
- A weekly series exports as one ``VEVENT`` with ``RRULE`` plus ``EXDATE``
  for skipped dates, **except** a timed series whose occurrences do not all
  share one UTC offset (a DST change inside the series): then each
  occurrence is its own event, because a UTC ``RRULE`` would drift the
  wall-clock time by an hour on one side of the change.
- Never ``ORGANIZER`` or ``ATTENDEE``: no e-mail address ever enters the
  output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Iterable, List, Optional, Sequence

from app import APP_VERSION

MAX_OCTETS = 75
CRLF = "\r\n"


@dataclass(frozen=True)
class IcsEvent:
    """One exportable thing. ``start_time`` None means all-day. ``rrule`` is
    the canonical weekly rule text from ``_calendar_recurrence`` or None.
    ``occurrences`` lists the dates a timed series expands to, supplied by
    the caller so this module needs no recurrence logic of its own; it is
    only read when ``rrule`` is set and ``start_time`` is set."""
    uid: str
    summary: str
    day: date
    start_time: Optional[time] = None
    duration_minutes: Optional[int] = None
    description: Optional[str] = None
    categories: Sequence[str] = ()
    rrule: Optional[str] = None
    exdates: Sequence[date] = ()
    occurrences: Sequence[date] = ()
    last_modified: Optional[datetime] = None
    sequence: int = 0


def escape_text(value: str) -> str:
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == ";":
            out.append("\\;")
        elif ch == ",":
            out.append("\\,")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            continue
        elif ord(ch) < 0x20 or ch == "\x7f":
            continue
        else:
            out.append(ch)
    return "".join(out)


def fold_line(line: str) -> List[str]:
    """Split one content line into physical lines of at most 75 octets each,
    never inside a UTF-8 sequence. Continuation lines start with a space,
    which counts toward their 75."""
    data = line.encode("utf-8")
    if len(data) <= MAX_OCTETS:
        return [line]
    parts: List[str] = []
    first = True
    while data:
        budget = MAX_OCTETS if first else MAX_OCTETS - 1
        if len(data) <= budget:
            chunk, data = data, b""
        else:
            cut = budget
            while cut > 0 and (data[cut] & 0xC0) == 0x80:
                cut -= 1
            chunk, data = data[:cut], data[cut:]
        parts.append(("" if first else " ") + chunk.decode("utf-8"))
        first = False
    return parts


def _utc(day: date, at: time, zone: tzinfo) -> datetime:
    return datetime.combine(day, at).replace(tzinfo=zone).astimezone(timezone.utc)


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fmt_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _offsets_agree(days: Iterable[date], at: time, zone: tzinfo) -> bool:
    offsets = {datetime.combine(d, at).replace(tzinfo=zone).utcoffset() for d in days}
    return len(offsets) <= 1


def _event_lines(ev: IcsEvent, *, now: datetime, zone: tzinfo, uid: Optional[str] = None,
                 day: Optional[date] = None, rrule: Optional[str] = None,
                 exdates: Sequence[date] = ()) -> List[str]:
    day = day or ev.day
    lines = ["BEGIN:VEVENT", f"UID:{uid or ev.uid}", f"DTSTAMP:{_fmt_utc(now)}"]
    if ev.start_time is None:
        lines.append(f"DTSTART;VALUE=DATE:{_fmt_date(day)}")
        lines.append(f"DTEND;VALUE=DATE:{_fmt_date(day + timedelta(days=1))}")
    else:
        start = _utc(day, ev.start_time, zone)
        lines.append(f"DTSTART:{_fmt_utc(start)}")
        if ev.duration_minutes:
            lines.append(f"DURATION:PT{int(ev.duration_minutes)}M")
    if rrule:
        lines.append(f"RRULE:{rrule}")
        for ex in exdates:
            if ev.start_time is None:
                lines.append(f"EXDATE;VALUE=DATE:{_fmt_date(ex)}")
            else:
                lines.append(f"EXDATE:{_fmt_utc(_utc(ex, ev.start_time, zone))}")
    lines.append(f"SUMMARY:{escape_text(ev.summary)}")
    if ev.description:
        lines.append(f"DESCRIPTION:{escape_text(ev.description)}")
    if ev.categories:
        lines.append("CATEGORIES:" + ",".join(escape_text(c) for c in ev.categories))
    if ev.last_modified is not None:
        lines.append(f"LAST-MODIFIED:{_fmt_utc(ev.last_modified)}")
    lines.append(f"SEQUENCE:{int(ev.sequence)}")
    lines.append("END:VEVENT")
    return lines


def build_ics(events: Sequence[IcsEvent], *, now: datetime, zone: Optional[tzinfo] = None,
              app_version: str = APP_VERSION) -> bytes:
    """The whole VCALENDAR as bytes, CRLF-terminated, folded, escaped.

    ``now`` must be timezone-aware (it becomes ``DTSTAMP``); ``zone`` is the
    local zone the plans' wall-clock times are read in, defaulting to the
    operating system's. Deterministic for fixed ``now`` and ``zone``.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    zone = zone or datetime.now().astimezone().tzinfo
    content: List[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//Project WIMI//WIMI {app_version}//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for ev in events:
        if ev.rrule and ev.start_time is not None and not _offsets_agree(ev.occurrences, ev.start_time, zone):
            # A DST change inside a timed series: one plain event per
            # occurrence, so no UTC rule drifts the wall-clock hour.
            skipped = set(ev.exdates)
            for occ in ev.occurrences:
                if occ in skipped:
                    continue
                content.extend(_event_lines(ev, now=now, zone=zone,
                                            uid=f"{ev.uid}-{_fmt_date(occ)}", day=occ))
        else:
            content.extend(_event_lines(ev, now=now, zone=zone, rrule=ev.rrule, exdates=ev.exdates))
    content.append("END:VCALENDAR")
    physical: List[str] = []
    for line in content:
        physical.extend(fold_line(line))
    return (CRLF.join(physical) + CRLF).encode("utf-8")


def parse_ics(data: bytes) -> List[dict]:
    """A small reader for tests and for round-trip checks: unfolds, splits
    ``NAME;PARAMS:VALUE``, unescapes TEXT, returns one dict per VEVENT with
    ``params`` kept under ``_params``."""
    text = data.decode("utf-8")
    assert "\n" not in text.replace("\r\n", ""), "a bare LF is not a valid line ending"
    raw_lines = text.split("\r\n")
    unfolded: List[str] = []
    for line in raw_lines:
        if line[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    events: List[dict] = []
    current: Optional[dict] = None
    for line in unfolded:
        if not line:
            continue
        name_part, _, value = line.partition(":")
        name, _, params = name_part.partition(";")
        if name == "BEGIN" and value == "VEVENT":
            current = {"_params": {}}
        elif name == "END" and value == "VEVENT":
            events.append(current)
            current = None
        elif current is not None:
            if name in ("SUMMARY", "DESCRIPTION", "CATEGORIES"):
                value = (value.replace("\\n", "\n").replace("\\,", ",")
                         .replace("\\;", ";").replace("\\\\", "\\"))
            current.setdefault(name, []).append(value)
            if params:
                current["_params"][name] = params
    return events
