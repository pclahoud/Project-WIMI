"""Regression: the question entry form is flat, and its dropdowns escape.

Guards the two properties of the layout rework
(``docs/planning/ENTRY_FORM_FLAT_LAYOUT.md``) that would otherwise rot
silently, because nothing else in the suite measures either one.

1. **Flat.** Every field renders on load with no clicks. The form used to
   be six mutually-exclusive accordion sections -- ``toggleSection``
   collapsed every other section when one opened -- so filling an entry
   meant a sequence of open/close gestures and you could never see the
   answer you gave while writing about why you gave it. A future change
   that reintroduces any collapse would still pass every other scenario
   in the suite, because they all drive one field at a time.

2. **The dropdown escapes its column.** ``.subject-dropdown`` is
   absolutely positioned with ``left/right: 0``, so anchored to its input
   inside a facts row it would be ~376px at the width this form has with
   the browser pane open. Options render the subject's full path under
   its name, and with a real content outline the path is frequently the
   only thing distinguishing two same-named results -- so a narrow list
   wraps or clips exactly the text that disambiguates. A full-width,
   zero-height ``.fact-dropdown-anchor`` after the row fixes it.

   The single number that proves the anchor still works is the dropdown's
   width against its input's. If someone re-parents the dropdown back
   into the value cell, every other assertion in this file still passes.

3. **The auto-fill prompt still mounts.** It hangs off a host element and
   had no ``data-testid`` before this rework, which made it the one piece
   of the form that could vanish without any test noticing.

Loader quirk
------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` -> ``window.api`` then deletes
the source handle.
"""
from __future__ import annotations

from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


# Every field the form must show without a click. Ids rather than
# testids: these are what the page's own JS resolves, so a rename breaks
# the page and this list together.
_ALWAYS_VISIBLE_FIELDS: list[str] = [
    "question-id",
    "difficulty-rating",
    "user-answer",
    "correct-answer",
    "time-spent",
    "time-unit",
    "primary-subject-search",
    "secondary-subject-search",
    "tag-search",
    "reflection-editor",
    "explanation-editor",
    "media-upload-container",
    "btn-add-note",
    "btn-quick-add-subject",
]


def _open_entry_form(wimi_session: WimiTestSession, wimi_page: WimiPage) -> None:
    """Seed a minimal exam + session and land on the entry form."""
    db = wimi_session.user.db
    exam_name = "Flat Layout Exam"
    db.create_exam_context(
        exam_name=exam_name,
        exam_description="Regression scenario for the flat entry form",
    )
    # Two same-named leaves under different parents: the case where the
    # dropdown's path text is the only thing telling results apart, and
    # therefore the case the anchor's width exists to serve.
    for parent_name in ("Cardiovascular System", "Respiratory System"):
        parent = db.create_subject_node(
            exam_context=exam_name,
            name=parent_name,
            level_type="System",
            parent_id=None,
            sort_order=1,
        )
        db.create_subject_node(
            exam_context=exam_name,
            name="thromboembolic disorders",
            level_type="Topic",
            parent_id=parent.id,
            sort_order=1,
        )

    review_session = db.create_review_session(
        exam_context_id=db.get_exam_context_by_name(exam_name).id,
        total_questions=1,
        total_incorrect=1,
        session_name="Flat layout scenario",
        date_encountered=date.today(),
    )
    wimi_page.goto("entry-form", query={"session_id": review_session.id})
    _wait_until_ready(wimi_page)


def _wait_until_ready(wimi_page: WimiPage, deadline_ms: int = 5000) -> None:
    """Block until the page has finished its own async start-up.

    ``goto`` returns once the QWebChannel bridge exists, which is well
    before initializeEntryPage() has loaded the subject list and mounted
    the MediaUpload component. Asserting on layout before then measures a
    half-built page: the subject index is empty so the dropdown never
    opens, and #media-upload-container is still an empty div with no
    rect.
    """
    step_ms, elapsed = 100, 0
    while elapsed < deadline_ms:
        # EntryState is a top-level `const`, so it is a global *binding*
        # but not a property of window -- window.EntryState is undefined.
        ready = wimi_page.eval_js(
            "(() => {"
            "  const subjects = typeof EntryState !== 'undefined'"
            "    && EntryState.subjects;"
            "  const media = document.getElementById('media-upload-container');"
            "  return !!(subjects && subjects.length"
            "            && media && media.children.length);"
            "})()"
        )
        if ready:
            return
        wimi_page.wait_for_timeout(step_ms)
        elapsed += step_ms
    raise AssertionError(
        f"Entry form did not finish initialising within {deadline_ms}ms "
        "(EntryState.subjects populated and MediaUpload mounted)."
    )


@pytest.mark.slow
@pytest.mark.regression
def test_every_field_is_visible_without_clicking(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """No accordion, and no field hidden behind something to open."""
    _open_entry_form(wimi_session, wimi_page)

    accordions = wimi_page.eval_js(
        "document.querySelectorAll('.entry-section').length"
    )
    assert accordions == 0, (
        f"Found {accordions} .entry-section elements. The accordion was "
        "removed in the flat-layout rework; reintroducing it means fields "
        "are hidden behind a click again."
    )

    ids = ",".join(f"'{f}'" for f in _ALWAYS_VISIBLE_FIELDS)
    hidden = wimi_page.eval_js(
        "(() => {"
        f"  const ids = [{ids}];"
        "   return ids.filter(id => {"
        "     const el = document.getElementById(id);"
        "     if (!el) return true;"
        "     const r = el.getBoundingClientRect();"
        "     return r.width === 0 || r.height === 0;"
        "   });"
        "})()"
    )
    assert hidden == [], (
        f"These fields are missing or have a zero rect on load: {hidden}. "
        "Every field must be visible without a click -- that is the whole "
        "point of the flat layout."
    )


@pytest.mark.slow
@pytest.mark.regression
def test_subject_dropdown_is_wider_than_its_input(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The dropdown sizes against the facts block, not the value column."""
    _open_entry_form(wimi_session, wimi_page)

    # Narrow the form to roughly what it gets with the browser pane open.
    # This is a container width, not a viewport resize, which is exactly
    # what the anchor has to cope with: the dropdown is sized by its
    # positioned ancestor, not by a media query.
    wimi_page.eval_js(
        "document.querySelector('.entry-content').style.maxWidth = '600px'"
    )

    wimi_page.eval_js(
        "(() => {"
        "  const i = document.getElementById('primary-subject-search');"
        "  i.value = 'thromboembolic';"
        "  i.dispatchEvent(new Event('input', {bubbles: true}));"
        "})()"
    )

    # The dropdown renders after a debounce plus a fuzzy-search pass.
    deadline_ms, step_ms, elapsed = 2000, 100, 0
    visible = False
    while elapsed < deadline_ms:
        visible = bool(wimi_page.eval_js(
            "document.getElementById('primary-subject-dropdown')"
            ".classList.contains('visible')"
        ))
        if visible:
            break
        wimi_page.wait_for_timeout(step_ms)
        elapsed += step_ms

    assert visible, (
        f"Subject dropdown did not open within {deadline_ms}ms of typing. "
        "Check initSubjectSearchField still resolves "
        "#primary-subject-dropdown by id -- the rework re-parented the "
        "dropdown into .fact-dropdown-anchor and relies on that lookup."
    )

    metrics = wimi_page.eval_js(
        "(() => {"
        "  const i = document.getElementById('primary-subject-search');"
        "  const d = document.getElementById('primary-subject-dropdown');"
        "  const f = document.querySelector('.entry-facts');"
        "  return {"
        "    input: Math.round(i.getBoundingClientRect().width),"
        "    dropdown: Math.round(d.getBoundingClientRect().width),"
        "    facts: Math.round(f.getBoundingClientRect().width),"
        "    inAnchor: !!d.closest('.fact-dropdown-anchor')"
        "  };"
        "})()"
    )

    assert metrics["inAnchor"], (
        "#primary-subject-dropdown is no longer inside a "
        ".fact-dropdown-anchor. Re-parenting it back into the value cell "
        "silently narrows it to the input's width."
    )
    # A meaningful margin, not a stray pixel: the anchor buys back the
    # ~9.25rem label column plus the row's padding.
    assert metrics["dropdown"] > metrics["input"] + 100, (
        f"Dropdown is {metrics['dropdown']}px against a "
        f"{metrics['input']}px input -- it is no longer escaping the "
        "value column. Subject paths are what disambiguate same-named "
        "results, and they need the full block width to stay readable."
    )
    assert metrics["dropdown"] >= metrics["facts"] - 10, (
        f"Dropdown ({metrics['dropdown']}px) is much narrower than the "
        f"facts block ({metrics['facts']}px); the anchor should span it."
    )


@pytest.mark.slow
@pytest.mark.regression
def test_autofill_prompt_mounts(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The auto-fill prompt has a host that survived the flatten.

    It used to mount into ``#question-id.closest('.form-group')``. The
    field no longer lives in a .form-group, so without #entry-prompt-host
    the prompt would silently never appear -- and before this scenario
    nothing would have caught that.
    """
    _open_entry_form(wimi_session, wimi_page)

    host = wimi_page.eval_js(
        "(() => {"
        "  const h = document.getElementById('entry-prompt-host');"
        "  if (!h) return null;"
        "  return {inForm: !!h.closest('#entry-form')};"
        "})()"
    )
    assert host is not None, (
        "#entry-prompt-host is gone. showAutofillPrompt() mounts into it; "
        "without it the prompt never renders and nothing else fails."
    )
    assert host["inForm"], "#entry-prompt-host must sit inside the form."

    # Prove the prompt actually lands in the host rather than nowhere.
    mounted = wimi_page.eval_js(
        "(() => {"
        "  showAutofillPrompt({id: 1}, 2);"
        "  const p = document.querySelector("
        "    '[data-testid=\"entry-form-autofill-prompt\"]');"
        "  return !!p && !!p.closest('#entry-prompt-host');"
        "})()"
    )
    assert mounted, (
        "showAutofillPrompt() did not render into #entry-prompt-host. "
        "Check the host lookup in question_entry.js."
    )
