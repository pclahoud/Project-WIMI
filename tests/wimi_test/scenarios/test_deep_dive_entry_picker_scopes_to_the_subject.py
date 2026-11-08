"""#848 Wave 2b: the entry picker offers this subject's entries until widened.

Decision 5 (owner, comment 11594): the list starts scoped to the entries
tagged with the subject the dialog was opened from, with a checkbox to widen
it to every entry in the exam. The scope is the entry browser's own subject
filter (#13), read through the same slot. And a draft is a mistake that
happened (#12), so a draft entry is offered, marked *Draft*.

Three entries make the cases: one on this subject, one draft on this subject,
one in the same exam on another subject. The other-subject entry is the one
that must be absent until the box is ticked; it appearing afterwards is the
positive control that it was seeded where the picker could see it. The
mutant that drops the subject filter fails the first assertion.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.deep_dive_quick_note import (
    open_deep_dive, open_dialog, seed_entry, seed_exam, seed_session, text_of,
    wait_cards, wait_picking,
)


@pytest.mark.slow
@pytest.mark.regression
def test_the_picker_offers_the_subjects_entries_and_drafts_until_widened(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed_exam(db, "DDC")
    tagged_session = seed_session(db, world["exam_id"], "DDC block 14", days_ago=2)
    other_session = seed_session(db, world["exam_id"], "DDC asthma set", days_ago=1)
    tagged = seed_entry(db, tagged_session, world["subject_id"], order=1, question_id="3001",
                        user_answer="A", correct_answer="B", reflection="tagged one")
    draft = seed_entry(db, tagged_session, world["subject_id"], order=2, question_id="3002",
                       user_answer="C", correct_answer="D", is_draft=True)
    elsewhere = seed_entry(db, other_session, world["other_id"], order=1, question_id="3003",
                           user_answer="E", correct_answer="F", reflection="other subject")

    open_deep_dive(wimi_page, world)
    open_dialog(wimi_page)
    wimi_page.locator(testid="quick-note-where-entry").click()
    wimi_page.locator(testid="quick-note-choose-entry").click()
    wait_picking(wimi_page)

    # ---- Scoped: this subject's entries, the draft among them ----------
    ids = wait_cards(wimi_page, lambda got: len(got) >= 2)
    assert sorted(ids) == sorted([tagged, draft]), (
        f"the picker should offer this subject's two entries only, offered {ids!r} "
        f"(the other subject's entry is {elsewhere})")
    lede = text_of(wimi_page, "quick-note-picker-lede") or ""
    assert f"Entries tagged {world['subject_name']}" in lede, lede
    assert text_of(wimi_page, f"quick-note-entry-card-{draft}-draft") == "Draft", (
        "a draft entry is offered and marked")
    assert text_of(wimi_page, f"quick-note-entry-card-{tagged}-draft") is None, (
        "only the draft carries the Draft tag")
    sessions = wimi_page.eval_js(
        "Array.from(document.querySelectorAll('[data-testid=\"quick-note-picker-sessions\"] .qn-sess'))"
        ".map(b => b.dataset.testid)")
    assert sessions == ["quick-note-picker-session-all",
                        f"quick-note-picker-session-{tagged_session}"], (
        f"the sessions column lists the sessions holding candidates: {sessions!r}")
    assert "2 entries" in (text_of(wimi_page, "quick-note-picker-session-all") or "")

    # ---- The search narrows by question id, inside the scoped set ------
    wimi_page.locator(testid="quick-note-picker-search").fill("3002")
    assert wait_cards(wimi_page, lambda got: got == [draft]) == [draft], (
        "searching a question id should leave that entry only")
    wimi_page.locator(testid="quick-note-picker-search").fill("3003")
    assert wait_cards(wimi_page, lambda got: got == []) == [], (
        "the other subject's entry is outside the scoped set, so a search cannot find it")
    status = text_of(wimi_page, "quick-note-picker-status") or ""
    assert "matches" in status, f"an empty search result says so: {status!r}"
    wimi_page.locator(testid="quick-note-picker-search").fill("")

    # ---- Widened: every entry in the exam ------------------------------
    wimi_page.locator(testid="quick-note-picker-widen").click()
    ids = wait_cards(wimi_page, lambda got: len(got) == 3)
    assert sorted(ids) == sorted([tagged, draft, elsewhere]), (
        f"ticking Show every entry in this exam should offer all three: {ids!r}")
    assert "Every entry in this exam" in (text_of(wimi_page, "quick-note-picker-lede") or "")
    assert text_of(wimi_page, f"quick-note-picker-session-{other_session}") is not None, (
        "widened, the other subject's session is in the column too")
