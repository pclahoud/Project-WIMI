"""Issue #286 - "Today" was computed in UTC, so an evening session was stored
under tomorrow.

    "``getTodayDateString()`` is ``new Date().toISOString().split('T')[0]``.
    ``toISOString()`` is **UTC**. In a negative-offset timezone every load
    after ``24:00 - |offset|`` local therefore yields *tomorrow's* date. [...]
    ``initializeSessionSetup()`` writes that into ``#session-date``, which is a
    **required** field the student is not asked to confirm, and
    ``startSession()`` passes it straight to
    ``createReviewSession(date_encountered=...)``."

Local is not a preference here; it is the only value consistent with what
reads the column back. ``sessions.py`` defaults it with ``date.today()``,
``get_activity_heatmap`` emits days up to ``datetime.now().date()`` and
``_calculate_streak_info`` compares against the same -- all **local**. So a
UTC "tomorrow" is not merely a day out: it is a key absent from the heatmap
and ahead of the streak, and the session counts nowhere.

How this is timezone-independent
--------------------------------
#286 was filed believing the defect was invisible on the box that found it,
and the box was in fact ``America/New_York`` -- i.e. it was invisible for
sixteen hours a day, not invisible by location. A test written against the
host's own zone inherits exactly that: green all afternoon, meaningful only in
the evening, and differently meaningful on every machine.

So the zone is **driven**, through CDP's ``Emulation.setTimezoneOverride``,
which Qt's CDP does implement (measured: ``getTimezoneOffset()`` moved 240 ->
-840 -> 660, and the override survives a ``goto``). The zone is then chosen
from the current UTC hour so that the local day and the UTC day **always**
differ:

* UTC hour < 11  -> ``Pacific/Pago_Pago`` (UTC-11), local date is yesterday
* UTC hour >= 11 -> ``Pacific/Kiritimati`` (UTC+14), local date is tomorrow

Both are DST-free. Whichever is picked, the two dates differ, and
``assert_the_clocks_disagree`` **fails hard** if they do not -- without that
control the assertion below would quietly become a tautology on a UTC host,
which is the shape #121 warns about. Nothing here hardcodes an offset or a
date: the oracle is read out of the page, so the test states "the field holds
the local day", never "the field holds 2026-10-04".
"""
from __future__ import annotations

import datetime as _dt

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

PAGE_READY = (
    "(() => { try { return typeof SessionState !== 'undefined'"
    " && SessionState.isPageReady === true; } catch (e) { return false; } })()"
)

#: The page's own two readings of now. `local` is the definition of a local
#: calendar day, computed independently of the helper under test; `utc` is the
#: expression #286 is about.
CLOCKS = """
(() => {
  const n = new Date();
  const pad = v => String(v).padStart(2, '0');
  return {
    offset_minutes: n.getTimezoneOffset(),
    local: n.getFullYear() + '-' + pad(n.getMonth() + 1) + '-' + pad(n.getDate()),
    utc: n.toISOString().split('T')[0],
    field: document.getElementById('session-date').value
  };
})()
"""


def _zone_where_the_two_days_differ() -> str:
    """A DST-free zone in which the local day is not the UTC day, right now."""
    if _dt.datetime.now(_dt.timezone.utc).hour >= 11:
        return "Pacific/Kiritimati"   # UTC+14: local is tomorrow
    return "Pacific/Pago_Pago"        # UTC-11: local is yesterday


def _open_session_setup(session: WimiTestSession, page: WimiPage) -> tuple[int, str]:
    db = session.user.db
    exam = db.create_exam_context(exam_name="W286 Exam", exam_description="")
    db.create_question_source(source_name="W286 Bank")
    db.conn.commit()

    zone = _zone_where_the_two_days_differ()
    page.goto("dashboard")
    # Before the navigation that computes the default, or the page would read
    # the host's real clock and this would measure nothing.
    page.tab._tab.Emulation.setTimezoneOverride(timezoneId=zone)

    page.goto("session-setup", query={"exam_id": exam.id})
    assert poll(page, PAGE_READY), "session setup never released its gate"
    return exam.id, zone


def _assert_the_clocks_disagree(clocks: dict, zone: str) -> None:
    assert clocks["local"] != clocks["utc"], (
        f"under {zone} the page's local day ({clocks['local']}) and its UTC "
        f"day ({clocks['utc']}) are the same, offset {clocks['offset_minutes']}"
        f" minutes. The timezone override did not take effect, so the "
        f"assertion that follows cannot tell a fixed page from a broken one. "
        f"This is a failure of the instrument, not of the application -- "
        f"check Emulation.setTimezoneOverride against this Qt build before "
        f"touching src/web/js/local_date.js."
    )


def test_the_date_field_defaults_to_the_students_own_day(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange ----------------------------------------------------------
    _exam_id, zone = _open_session_setup(wimi_session, wimi_page)

    # ---- Act --------------------------------------------------------------
    clocks = wimi_page.eval_js(CLOCKS)

    # ---- Assert -----------------------------------------------------------
    _assert_the_clocks_disagree(clocks, zone)
    assert clocks["field"] == clocks["local"], (
        f"#session-date defaulted to {clocks['field']!r} under {zone}; the "
        f"student's own day is {clocks['local']!r}. #286: this field is "
        f"required, is never confirmed, and is passed straight to "
        f"createReviewSession."
    )
    assert clocks["field"] != clocks["utc"], (
        f"#session-date is still the UTC day ({clocks['utc']!r}) -- #286 "
        f"exactly."
    )


def test_the_day_the_page_offered_is_the_day_that_is_stored(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """The half no display fix could recover.

    #286 is a *write*-side defect: the row is created with whatever
    ``#session-date`` holds, so the only assertion that settles it reads the
    column back. The sibling fields are filled through the page's own API
    rather than driven -- the source picker is not what is under test, and the
    one value that matters here (the date) is still the page's own default,
    untouched by this test.
    """
    # ---- Arrange ----------------------------------------------------------
    _exam_id, zone = _open_session_setup(wimi_session, wimi_page)
    clocks = wimi_page.eval_js(CLOCKS)
    _assert_the_clocks_disagree(clocks, zone)

    filled = wimi_page.eval_js("""
    (() => {
      const q = document.getElementById('session-total-questions');
      const i = document.getElementById('session-total-incorrect');
      q.value = '10';
      i.value = '3';
      SessionState.sourceSelect.setValue(String(SessionState.sources[0].id), true);
      validateForm();
      return !document.getElementById('btn-start-session').disabled;
    })()
    """)
    assert filled is True, "the form never became valid, so Start cannot run"

    # ---- Act --------------------------------------------------------------
    mark = wimi_page.mark_bridge_calls()
    wimi_page.eval_js("(() => { startSession(); return true; })()")
    wimi_page.wait_for_bridge_call("createReviewSession", since_ts=mark,
                                   timeout_ms=30000)

    # ---- Assert -----------------------------------------------------------
    row = wimi_session.user.db.fetchone(
        "SELECT date_encountered FROM review_sessions"
        " ORDER BY id DESC LIMIT 1")
    assert row, "no review_sessions row was written"
    stored = str(row["date_encountered"])[:10]
    assert stored == clocks["local"], (
        f"review_sessions.date_encountered holds {stored!r} for a session "
        f"started under {zone}, where the student's day is "
        f"{clocks['local']!r} (UTC's is {clocks['utc']!r}). Stored one day "
        f"out, the row is a key get_activity_heatmap's day range does not "
        f"contain and _calculate_streak_info is behind, so the session "
        f"counts nowhere -- #286."
    )
