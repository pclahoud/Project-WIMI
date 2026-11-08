"""Regression: a filter that matches nothing never reads as "No entries yet" (#702).

``showEmpty()`` decided whether a filter was in force from its own hand-kept
list, which missed three filters that ``loadEntries()`` does send:

* a prefix-only search: ``notes:zzzz`` puts everything in ``fieldFilters``
  and leaves ``searchQuery`` empty;
* a custom date range with only a To date;
* "finished entries only" (``isDraft === false``), which is falsy.

Each of them, matching nothing on an exam full of entries, showed "No entries
yet / Start by creating your first question entry.", the #174 class. Both
functions now read ``filterParams()``.

The prefix search is TYPED into the search box (focus, then
``Input.insertText``), so the debounce and ``parseSearchQuery`` are on the
path. The other two are set on ``entryBrowser.filters`` and loaded through
``loadEntries()``. The date panel's own Apply is #521's subject, and this
test is about what the empty state counts.

The control is the unfiltered page. With no filters it draws the entry, so
the empty state is reached only through a filter.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import centre_of, poll, real_click, real_type
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

EMPTY_TITLE = "document.getElementById('emptyTitle').textContent"
# showEmpty() hides the grid rather than emptying it, so the old cards stay in
# the DOM; the empty state's own display is the signal.
SHOWN = "getComputedStyle(document.getElementById('emptyState')).display !== 'none'"


def _seed(db):
    exam = db.create_exam_context(exam_name="W702 Exam", exam_description="#702")
    subject = db.create_subject_node(exam.exam_name, "Cardiovascular", "System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name="W702 session", date_encountered=date.today())
    db.create_question_entry(session.id, "a", "b", notes="warfarin",
                             primary_subject_ids=[subject.id])
    db.conn.commit()
    return exam


def _open(page: WimiPage) -> None:
    page.goto("entry-browser")
    assert poll(page, "document.querySelectorAll('.entry-card').length === 1",
                timeout_ms=20000), (
        "the control failed: with no filter the browser should draw the entry")


def _title_after(page: WimiPage) -> str:
    assert poll(page, SHOWN, timeout_ms=10000), "the empty state never showed"
    return page.eval_js(EMPTY_TITLE)


@pytest.mark.slow
@pytest.mark.regression
def test_a_prefix_only_search_is_a_filter(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    _seed(wimi_session.user.db)
    _open(wimi_page)
    real_click(wimi_page, centre_of(wimi_page, "#searchInput"))
    real_type(wimi_page, "notes:zzzz")
    title = _title_after(wimi_page)
    assert title == "No entries match your filters", (
        f"#702: a prefix-only search matching nothing reads {title!r}, on an"
        f" exam with an entry")


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("filters", [
    {"dateTo": "2000-01-01"},
    {"isDraft": False, "dateTo": None},
], ids=["to-date-only", "finished-only"])
def test_every_filter_loadEntries_sends_counts(
    wimi_session: WimiTestSession, wimi_page: WimiPage, filters: dict
) -> None:
    db = wimi_session.user.db
    _seed(db)
    if "isDraft" in filters:
        # Make the only entry a draft, so "finished only" matches nothing.
        db.execute("UPDATE question_entries SET is_draft = 1")
        db.conn.commit()
    _open(wimi_page)
    sets = "; ".join(f"entryBrowser.filters.{k} = {json.dumps(v)}"
                     for k, v in filters.items())
    wimi_page.eval_js(f"(() => {{ {sets}; entryBrowser.currentPage = 1;"
                      f" entryBrowser.loadEntries(); }})()")
    title = _title_after(wimi_page)
    assert title == "No entries match your filters", (
        f"#702: with {filters} in force and matching nothing, the empty state"
        f" reads {title!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_an_exam_with_no_entries_and_no_filter_still_reads_no_entries_yet(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    """The negative control for the three tests above.

    Each of them asserts the "match your filters" heading, so a showEmpty()
    that always took the filter branch would pass all three. This is the
    other half: with no filter in force, an exam with nothing logged must
    still say "No entries yet". It also catches a filterParams() that starts
    returning a key by default, which would make every empty exam read as
    filtered.
    """
    db = wimi_session.user.db
    db.create_exam_context(exam_name="W702 Empty", exam_description="#702")
    db.conn.commit()
    wimi_page.goto("entry-browser")
    assert poll(wimi_page, "typeof entryBrowser !== 'undefined'", timeout_ms=20000)
    title = _title_after(wimi_page)
    assert title == "No entries yet", (
        f"#702: an exam with no entries and no filter reads {title!r}")
    assert wimi_page.eval_js("Object.keys(entryBrowser.filterParams()).length") == 0, (
        "filterParams() must be empty when no filter is in force")


@pytest.mark.slow
@pytest.mark.regression
@pytest.mark.parametrize("filters", [
    {"difficultyLevels": [5]},
    {"timeMin": 600},
    {"timeMax": 30},
    {"missingAny": ["difficulty", "time"]},
    {"untagged": True},
    {"tagIds": "BOTH", "tagMode": "all"},
    {"countedSubjectId": "OTHER"},
], ids=["difficulty", "time-min", "time-max", "missing", "untagged",
        "tag-mode-all", "counted-subject"])
def test_every_898_filter_counts(
    wimi_session: WimiTestSession, wimi_page: WimiPage, filters: dict
) -> None:
    """#898's filters, each matching nothing, must read as a filter too.

    The entry is rated 3, timed at 60 s, carries one of two types and sits
    on Cardiovascular, so each filter here is one it fails: rated 5, 600 s
    or more, under 30 s, missing a rating or a time, carrying no type,
    carrying both types, counted under another subject. The unfiltered page
    drawing it is the control (``_open``); ``tag-mode-all`` is the one that
    needs the mode, since the same two types under *any* would match.
    """
    db = wimi_session.user.db
    exam = _seed(db)
    one = db.create_tag(exam.exam_name, "W702 One").id
    two = db.create_tag(exam.exam_name, "W702 Two").id
    other = db.create_subject_node(exam.exam_name, "Renal", "System")
    db.execute("UPDATE question_entries SET perceived_difficulty = 3,"
               " time_spent_seconds = 60")
    entry_id = db.fetchone("SELECT id FROM question_entries")["id"]
    db.execute("INSERT INTO entry_tags (question_entry_id, tag_id) VALUES (?, ?)",
               (entry_id, one))
    db.conn.commit()
    resolved = dict(filters)
    if resolved.get("tagIds") == "BOTH":
        resolved["tagIds"] = [one, two]
    if resolved.get("countedSubjectId") == "OTHER":
        resolved["countedSubjectId"] = other.id
    _open(wimi_page)
    sets = "; ".join(f"entryBrowser.filters.{k} = {json.dumps(v)}"
                     for k, v in resolved.items())
    wimi_page.eval_js(f"(() => {{ {sets}; entryBrowser.currentPage = 1;"
                      f" entryBrowser.loadEntries(); }})()")
    title = _title_after(wimi_page)
    assert title == "No entries match your filters", (
        f"#702/#898: with {filters} in force and matching nothing, the empty"
        f" state reads {title!r}")
