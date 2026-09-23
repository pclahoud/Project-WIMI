"""Regression: a container hidden while empty must appear when it gains content.

Forgejo issues #134, #136 and #141.

QtWebEngine 6.10 / Chromium 134 stops re-invalidating ``:empty``. A container
styled ``:empty { display: none }`` that gains its first child **keeps** that
``display: none``: the computed style is never recalculated, the element
renders at zero pixels, and layout genuinely excludes it. The fix (#141) was
to replace every first-party ``:empty`` with ``:not(:has(*))``, which
invalidates correctly on both engines; ``scripts/check_css_empty_selector.py``
keeps it that way.

**Read this before trusting a green run.**

1. *This scenario passes on Chromium 130 whether or not the fix is present.*
   The pinned stack re-invalidates ``:empty`` correctly, so on 6.9 the buggy
   CSS and the fixed CSS behave identically. A pass here guards the *markup
   and JS* against regression; it is **not** proof that the CSS fix works.

   **No environment with a regressed engine is maintained any more.** One was
   held on the Windows machine and released on 2026-09-21, once the owner
   settled that the Qt pin is not moving: keeping it alive to verify a fix for
   a bug that cannot occur on the shipped engine was cost without a consumer,
   and #141 had itself warned that such an environment would otherwise be
   "preserved indefinitely by inertia".

   **So this scenario has never been run against an engine where it could
   fail.** If you are the person moving the Qt pin: run this first on the new
   engine, and before trusting it, revert one rule in ``entry.css`` to
   ``:empty`` and confirm these tests actually **fail**. If they pass with the
   bug reintroduced, the scenario is decoration and the real check is manual —
   measure ``offsetHeight`` after adding the first chip.

2. *It must start from a container that was ``:empty`` at first style
   resolution.* Once a container resolves non-empty it stays correct for the
   life of the page, so opening an entry that already has chips or notes
   measures the immunised state and passes against completely broken code.
   Everything below therefore loads a **fresh, empty** entry form.

3. *It asserts pixels, not DOM presence.* When this bug bit, the element, its
   children and live TinyMCE instances were all present and correct — only the
   height was zero. ``assert container.querySelector('.chip')`` would have
   passed throughout. Assert ``offsetHeight``.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# Returns null until the entry form has finished loading, so callers poll.
READY = """
(() => {
  if (typeof EntryState === 'undefined') return null;
  if (EntryState.isLoading) return null;
  if (!document.getElementById('btn-add-note')) return null;
  return JSON.stringify({ready: true});
})()
"""


def _measure(selector: str) -> str:
    """Computed display, child count and rendered height of one container."""
    return f"""
(() => {{
  const c = document.querySelector('{selector}');
  if (!c) return JSON.stringify({{missing: true}});
  const kid = c.firstElementChild;
  return JSON.stringify({{
    display: getComputedStyle(c).display,
    children: c.children.length,
    containerH: c.offsetHeight,
    childH: kid ? kid.offsetHeight : null,
  }});
}})()
"""


def _poll(page: WimiPage, js: str, *, timeout_ms: int = 20000):
    elapsed = 0
    while elapsed < timeout_ms:
        try:
            result = page.eval_js(js)
        except Exception:  # context torn down mid-navigation
            result = None
        if result is not None:
            return json.loads(result)
        page.wait_for_timeout(200)
        elapsed += 200
    return None


def _assert_hidden_while_empty(state: dict, name: str) -> None:
    assert state and not state.get("missing"), f"{name}: container not found"
    assert state["children"] == 0, (
        f"{name}: expected an empty container at load, found "
        f"{state['children']} child(ren). This scenario is only meaningful "
        f"from a container that was empty at first style resolution."
    )
    assert state["containerH"] == 0, (
        f"{name}: expected zero height while empty, got {state['containerH']}")


def _assert_visible_with_content(state: dict, name: str) -> None:
    assert state["children"] >= 1, f"{name}: no child was added"
    assert state["display"] != "none", (
        f"{name}: container still computes display:none after gaining a child "
        f"({state}). This is the #141 invalidation failure.")
    assert state["containerH"] > 0, (
        f"{name}: container has a child but renders at zero pixels ({state}). "
        f"DOM presence is not enough — this is exactly what #134 and #136 "
        f"looked like.")
    assert state["childH"] > 0, (
        f"{name}: the child itself renders at zero pixels ({state})")


def _seed(db) -> int:
    """One session with a subject and a tag available, and no entry content."""
    exam = db.create_exam_context(exam_name="Empty Container Regression",
                                  exam_description="")
    parent = db.create_subject_node(
        exam_context=exam.exam_name, name="Cardiovascular", level_type="System")
    db.create_subject_node(
        exam_context=exam.exam_name, name="Hypertension",
        level_type="Topic", parent_id=parent.id)
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=10, total_incorrect=1,
        session_name="Empty container session", date_encountered=date.today())
    db.create_question_entry(
        review_session_id=session.id, user_answer="B", correct_answer="D",
        reflection="<p>r</p>", explanation="<p>e</p>")
    db.conn.commit()
    return session.id


@pytest.mark.slow
@pytest.mark.regression
def test_notes_container_appears_when_a_note_is_added(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#134: '+ Add Note' must put a visible editor on screen."""
    session_id = _seed(wimi_session.user.db)
    wimi_page.goto("entry-form", query={"session_id": session_id})
    assert _poll(wimi_page, READY), "entry form never finished loading"

    sel = "#notes-list-container"
    _assert_hidden_while_empty(_poll(wimi_page, _measure(sel)), "notes")

    wimi_page.locator(testid="entry-form-notes-add-button").click()
    wimi_page.wait_for_timeout(600)

    _assert_visible_with_content(_poll(wimi_page, _measure(sel)), "notes")


@pytest.mark.slow
@pytest.mark.regression
def test_tag_chip_appears_when_an_error_type_is_selected(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#136: selecting an error type must show its chip."""
    session_id = _seed(wimi_session.user.db)
    wimi_page.goto("entry-form", query={"session_id": session_id})
    assert _poll(wimi_page, READY), "entry form never finished loading"

    sel = "#tags-chips"
    _assert_hidden_while_empty(_poll(wimi_page, _measure(sel)), "tag chips")

    wimi_page.locator(css="#tag-search").fill("Know")
    wimi_page.wait_for_timeout(900)
    picked = wimi_page.eval_js(
        "(() => { const d = document.getElementById('tag-dropdown');"
        " if (!d) return 'no-dropdown';"
        " const o = d.querySelector('.tag-option');"
        " if (!o) return 'no-option'; o.click(); return 'clicked'; })()")
    assert picked == "clicked", f"could not select an error type ({picked!r})"
    wimi_page.wait_for_timeout(600)

    _assert_visible_with_content(_poll(wimi_page, _measure(sel)), "tag chips")


@pytest.mark.slow
@pytest.mark.regression
def test_subject_chip_appears_when_a_subject_is_selected(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    """#136: selecting a primary subject must show its chip.

    The same rule governs the secondary field and the Tag context pill, which
    renders inside this container — on 6.10 the pill was 0x0 and therefore
    unclickable, so every multi-parent subject silently took its canonical
    parent context.
    """
    session_id = _seed(wimi_session.user.db)
    wimi_page.goto("entry-form", query={"session_id": session_id})
    assert _poll(wimi_page, READY), "entry form never finished loading"

    sel = "#primary-subjects-chips"
    _assert_hidden_while_empty(_poll(wimi_page, _measure(sel)), "subject chips")

    wimi_page.locator(css="#primary-subject-search").fill("Hyper")
    wimi_page.wait_for_timeout(900)
    picked = wimi_page.eval_js(
        "(() => { const d = document.getElementById('primary-subject-dropdown');"
        " if (!d) return 'no-dropdown';"
        " const o = d.querySelector('.subject-option');"
        " if (!o) return 'no-option'; o.click(); return 'clicked'; })()")
    assert picked == "clicked", f"could not select a subject ({picked!r})"
    wimi_page.wait_for_timeout(800)

    _assert_visible_with_content(_poll(wimi_page, _measure(sel)), "subject chips")
