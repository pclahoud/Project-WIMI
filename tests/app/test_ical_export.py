"""The iCalendar builder (#778, owner decision 11: UTC instants).

Qt-free, stdlib-only, deterministic for a fixed `now` and `zone`, so the
golden test asserts exact bytes. Every RFC 5545 rule the module claims has
a test: CRLF, 75-octet folding that never splits a UTF-8 sequence, TEXT
escaping, UTC DTSTAMP, all-day versus timed shapes, RRULE with EXDATE, and
the DST fallback that enumerates a timed series as separate events.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app import APP_VERSION
from app.ical_export import IcsEvent, build_ics, escape_text, fold_line, parse_ics

NOW = datetime(2026, 10, 12, 14, 0, 0, tzinfo=timezone.utc)
MINUS_FOUR = timezone(timedelta(hours=-4))


def _lines(data: bytes) -> list[str]:
    text = data.decode("utf-8")
    assert text.endswith("\r\n")
    return text[:-2].split("\r\n")


@pytest.mark.unit
def test_golden_bytes_two_events():
    events = [
        IcsEvent(uid="9f1c2b6a7d3e4e1a9b8c0f5a6d7e8c90@wimi", summary="WIMI session: Step 1 ; Cardiology, Part 2",
                 day=date(2026, 10, 15), start_time=time(9, 0), duration_minutes=60, categories=["Step 1"]),
        IcsEvent(uid="3a0e5f8d1c2b4d6e8f9ab1c2d3e4f5a6@wimi", summary="WIMI session: Pädiatrie", day=date(2026, 10, 18),
                 description="Goal: 20 entries this week. Übungsaufgaben zur Neonatologie und "
                             "Wachstumsstörungen, dann Wiederholung der Impfpläne."),
    ]
    out = build_ics(events, now=NOW, zone=MINUS_FOUR, app_version="0.2.0-beta")
    expected = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Project WIMI//WIMI 0.2.0-beta//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:9f1c2b6a7d3e4e1a9b8c0f5a6d7e8c90@wimi\r\n"
        "DTSTAMP:20261012T140000Z\r\n"
        "DTSTART:20261015T130000Z\r\n"
        "DURATION:PT60M\r\n"
        "SUMMARY:WIMI session: Step 1 \\; Cardiology\\, Part 2\r\n"
        "CATEGORIES:Step 1\r\n"
        "SEQUENCE:0\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:3a0e5f8d1c2b4d6e8f9ab1c2d3e4f5a6@wimi\r\n"
        "DTSTAMP:20261012T140000Z\r\n"
        "DTSTART;VALUE=DATE:20261018\r\n"
        "DTEND;VALUE=DATE:20261019\r\n"
        "SUMMARY:WIMI session: Pädiatrie\r\n"
        "DESCRIPTION:Goal: 20 entries this week. Übungsaufgaben zur Neonatologie un\r\n"
        " d Wachstumsstörungen\\, dann Wiederholung der Impfpläne.\r\n"
        "SEQUENCE:0\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode("utf-8")
    assert out == expected


@pytest.mark.unit
def test_every_physical_line_is_within_75_octets_and_decodes_alone():
    long_desc = "ü" * 200 + " end"
    out = build_ics([IcsEvent(uid="u@wimi", summary="s", day=date(2026, 1, 1), description=long_desc)],
                    now=NOW, zone=MINUS_FOUR)
    for line in _lines(out):
        assert len(line.encode("utf-8")) <= 75, line
        line.encode("utf-8").decode("utf-8")   # never a split multibyte sequence
    # Unfolding gives the text back exactly.
    (ev,) = parse_ics(out)
    assert ev["DESCRIPTION"] == [long_desc]


@pytest.mark.unit
def test_no_bare_lf_anywhere():
    out = build_ics([IcsEvent(uid="u@wimi", summary="a\nb", day=date(2026, 1, 1))], now=NOW, zone=MINUS_FOUR)
    assert b"\n" not in out.replace(b"\r\n", b"")


@pytest.mark.unit
def test_text_escaping_and_control_characters():
    assert escape_text("a\\b;c,d\ne\rf\x07g") == "a\\\\b\\;c\\,d\\nefg"
    assert escape_text("a\\b") == "a\\\\b"
    assert escape_text("x;y,z") == "x\\;y\\,z"
    assert escape_text("line1\nline2\r") == "line1\\nline2"
    assert escape_text("bell\x07here") == "bellhere"


@pytest.mark.unit
def test_fold_line_short_lines_are_untouched_and_continuations_start_with_a_space():
    assert fold_line("SUMMARY:short") == ["SUMMARY:short"]
    parts = fold_line("X:" + "a" * 200)
    assert parts[0] == "X:" + "a" * 73
    assert all(p.startswith(" ") and len(p.encode()) <= 75 for p in parts[1:])
    assert "".join([parts[0]] + [p[1:] for p in parts[1:]]) == "X:" + "a" * 200


@pytest.mark.unit
def test_timed_events_are_utc_instants_from_the_given_zone():
    ev = IcsEvent(uid="u@wimi", summary="s", day=date(2026, 10, 15), start_time=time(23, 30), duration_minutes=30)
    (parsed,) = parse_ics(build_ics([ev], now=NOW, zone=MINUS_FOUR))
    assert parsed["DTSTART"] == ["20261016T033000Z"]       # 23:30 at UTC-4 is 03:30 next day
    assert parsed["DURATION"] == ["PT30M"]
    (parsed_plus,) = parse_ics(build_ics([ev], now=NOW, zone=timezone(timedelta(hours=9))))
    assert parsed_plus["DTSTART"] == ["20261015T143000Z"]


@pytest.mark.unit
def test_dtstamp_is_the_injected_now_in_utc():
    local_now = datetime(2026, 10, 12, 10, 0, tzinfo=MINUS_FOUR)
    (parsed,) = parse_ics(build_ics([IcsEvent(uid="u@wimi", summary="s", day=date(2026, 1, 1))], now=local_now, zone=MINUS_FOUR))
    assert parsed["DTSTAMP"] == ["20261012T140000Z"]
    with pytest.raises(ValueError):
        build_ics([], now=datetime(2026, 10, 12, 10, 0), zone=MINUS_FOUR)


@pytest.mark.unit
def test_prodid_carries_the_imported_app_version():
    out = build_ics([], now=NOW, zone=MINUS_FOUR)
    assert f"PRODID:-//Project WIMI//WIMI {APP_VERSION}//EN".encode() in out


@pytest.mark.unit
def test_all_day_series_is_one_rrule_event_with_exdates():
    ev = IcsEvent(uid="s@wimi", summary="Weekly", day=date(2026, 10, 13),
                  rrule="FREQ=WEEKLY;BYDAY=TU;COUNT=4", exdates=[date(2026, 10, 20)],
                  occurrences=[date(2026, 10, 13), date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3)])
    events = parse_ics(build_ics([ev], now=NOW, zone=MINUS_FOUR))
    assert len(events) == 1
    assert events[0]["RRULE"] == ["FREQ=WEEKLY;BYDAY=TU;COUNT=4"]
    assert events[0]["EXDATE"] == ["20261020"] and events[0]["_params"]["EXDATE"] == "VALUE=DATE"


@pytest.mark.unit
def test_timed_series_with_one_utc_offset_keeps_the_rule():
    ev = IcsEvent(uid="s@wimi", summary="Weekly", day=date(2026, 10, 13), start_time=time(9, 0), duration_minutes=45,
                  rrule="FREQ=WEEKLY;BYDAY=TU;COUNT=3", exdates=[date(2026, 10, 20)],
                  occurrences=[date(2026, 10, 13), date(2026, 10, 20), date(2026, 10, 27)])
    events = parse_ics(build_ics([ev], now=NOW, zone=MINUS_FOUR))
    assert len(events) == 1
    assert events[0]["DTSTART"] == ["20261013T130000Z"]
    assert events[0]["EXDATE"] == ["20261020T130000Z"]


def _dst_zone():
    """A zone whose offset changes on 2026-11-01 (US autumn change), built by
    hand so the test needs no tzdata: UTC-4 before, UTC-5 after."""
    from datetime import tzinfo as _tz

    class Z(_tz):
        def utcoffset(self, dt):
            return timedelta(hours=-4) if dt.replace(tzinfo=None) < datetime(2026, 11, 1, 2) else timedelta(hours=-5)

        def dst(self, dt):
            return timedelta(0)

        def tzname(self, dt):
            return "Z"
    return Z()


@pytest.mark.unit
def test_timed_series_across_a_dst_change_is_enumerated_not_ruled():
    occ = [date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3), date(2026, 11, 10)]
    ev = IcsEvent(uid="s@wimi", summary="Weekly", day=date(2026, 10, 20), start_time=time(9, 0), duration_minutes=45,
                  rrule="FREQ=WEEKLY;BYDAY=TU;COUNT=4", exdates=[date(2026, 10, 27)], occurrences=occ)
    events = parse_ics(build_ics([ev], now=NOW, zone=_dst_zone()))
    assert [e["UID"][0] for e in events] == ["s@wimi-20261020", "s@wimi-20261103", "s@wimi-20261110"]
    assert [e["DTSTART"][0] for e in events] == ["20261020T130000Z", "20261103T140000Z", "20261110T140000Z"]
    assert all("RRULE" not in e for e in events)


@pytest.mark.unit
def test_never_organizer_or_attendee():
    out = build_ics([IcsEvent(uid="u@wimi", summary="s", day=date(2026, 1, 1), description="mail me at x@y.z")],
                    now=NOW, zone=MINUS_FOUR)
    assert b"ORGANIZER" not in out and b"ATTENDEE" not in out


@pytest.mark.unit
def test_round_trip_through_the_reader():
    events = [
        IcsEvent(uid="a@wimi", summary="A; one, two", day=date(2026, 3, 1)),
        IcsEvent(uid="b@wimi", summary="B", day=date(2026, 3, 2), start_time=time(7, 15), duration_minutes=90,
                 description="d\\e", categories=["Exam, X"]),
    ]
    parsed = parse_ics(build_ics(events, now=NOW, zone=MINUS_FOUR))
    assert [p["UID"][0] for p in parsed] == ["a@wimi", "b@wimi"]
    assert parsed[0]["SUMMARY"] == ["A; one, two"]
    assert parsed[1]["DESCRIPTION"] == ["d\\e"] and parsed[1]["CATEGORIES"] == ["Exam, X"]
