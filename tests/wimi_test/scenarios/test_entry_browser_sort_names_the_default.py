"""Regression: the entry browser's sort control names the order in force.

Forgejo issue #476 -- "The entry browser's sort control shows its
placeholder on a fresh profile while the list is really sorted
newest-first, because the stored default is not one of its options".

Why it failed: the shipped default for ``entry_review_default_sort_field``
is ``'answered_incorrectly_date'`` (the dataclass, the m001 schema default
and ``SettingsPage.DEFAULTS`` all agree on it). The entry browser copied it
into ``filters.sortBy`` and handed it to a ``CustomSelect`` whose four
options are ``date_desc``/``date_asc``/``difficulty_desc``/``difficulty_asc``,
so the control fell through to its ``Sort by...`` placeholder, while the
backend's ``sort_mapping.get(sort_by, sort_mapping['date_desc'])`` quietly
sorted newest-first. Settings -> Entry Browser -> Default Sort Field had the
same mismatch (it renders blank, selectedIndex -1); that half is #504's
and is deliberately not covered here.

What the fix changes: the stored value is left alone (no migration, no
change to the default). Where the entry browser reads the preference it maps
``answered_incorrectly_date`` onto ``date_desc`` -- the order the backend
already applies for it -- so the control names the sort in force.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

LEGACY_DEFAULT = 'answered_incorrectly_date'

CARD_COUNT = "document.querySelectorAll('#entryGrid [data-entry-id]').length"
SORT_PROBE = """
(() => { const el = document.querySelector('#sortSelectContainer .custom-select');
  const shown = el && el.querySelector('.custom-select-value');
  const opts = el ? Array.from(el.querySelectorAll('.custom-select-option'))
                      .map(o => o.dataset.value) : [];
  const first = document.querySelector('#entryGrid [data-entry-id] .entry-date');
  return JSON.stringify({
    value: el ? el.dataset.value : null,
    options: opts,
    text: shown ? shown.textContent.trim() : null,
    placeholder: shown ? shown.classList.contains('placeholder') : null,
    firstCardDate: first ? first.textContent.trim() : null,
  }); })()
"""

def _poll(wimi_page: WimiPage, js: str, want, *, timeout_ms: int = 15000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = wimi_page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            last = None
        if last == want:
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


def _seed(db) -> None:
    """Two sessions a week apart, one entry each, so order is observable."""
    db._ensure_phase2_schema()
    exam = db.create_exam_context(exam_name="Sort Exam", exam_description="")
    for name, when in (("Older", date.today() - timedelta(days=7)),
                       ("Newer", date.today())):
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=10, total_incorrect=1,
            session_name=name, date_encountered=when,
        )
        db.create_question_entry(
            review_session_id=session.id, user_answer="A", correct_answer="B",
            reflection=f"{name} reflection", explanation=f"{name} explanation",
        )


@pytest.mark.slow
@pytest.mark.regression
def test_sort_control_names_the_shipped_default(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    _seed(db)
    stored = db.get_preferences().entry_review_default_sort_field
    # Precondition: without the legacy value stored, nothing below can fail.
    assert stored == LEGACY_DEFAULT, (
        f"fresh profile stores {stored!r}; this test needs the shipped "
        f"default {LEGACY_DEFAULT!r} to exercise #476")

    wimi_page.goto('entry-browser')
    assert _poll(wimi_page, CARD_COUNT, 2) == 2, "the two seeded cards never rendered"
    probe = json.loads(wimi_page.eval_js(SORT_PROBE))

    assert probe['value'] in probe['options'], (
        f"sort control holds {probe['value']!r}, which is none of its options "
        f"{probe['options']}; it reads {probe['text']!r}")
    assert not probe['placeholder'] and probe['text'] == 'Date (Newest)', (
        f"sort control reads {probe['text']!r} (placeholder={probe['placeholder']}) "
        f"while the list is sorted newest-first")
    newest = wimi_page.eval_js(
        "entryBrowser.formatDate(%s)" % json.dumps(date.today().isoformat()))
    assert probe['firstCardDate'] == newest, (
        f"first card is dated {probe['firstCardDate']!r}, expected today's "
        f"{newest!r}: the control says newest-first, so the list must be")
