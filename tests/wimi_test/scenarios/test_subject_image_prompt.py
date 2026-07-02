"""Regression: "related images for this subject" prompt on the entry form.

When a user types a primary subject on the question entry form, the page
calls ``api.getMediaBySubject`` to look for media already linked to that
subject and (if any are found) renders an autopopulation prompt with
``data-testid="entry-form-image-autopopulate-prompt"``.

Bug history
-----------

Shipped 2026-01-24 in commit ``e1e2671``. The call site in
``src/web/js/question_entry.js`` (``checkSubjectImages``) was passing
**four** arguments to ``api.getMediaBySubject`` but the wrapper in
``src/web/js/api/media.js`` accepts only three
(``subjectNodeId, limit, dimensionId``). The extra
``EntryState.session.exam_context_id`` in slot 1 shifted every other
argument one position left — the bridge ended up querying
``subject_node_id = exam_context_id`` (~1), ``limit = subjectId``,
``dimension_id = 5``. The DB method ``get_media_by_subject`` is
user-scoped via ``self.user_id`` and does NOT accept an exam-context
id; the first arg was purely wrong. Result: the prompt almost never
fired because ``subject_node_id`` matched the wrong row, ``limit`` was
massively inflated, and ``dimension_id=5`` filtered out everything that
wasn't in dimension 5.

The fix drops the spurious first argument so the call site matches the
wrapper.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because
``_loader.js`` aliases ``window._wimiApi`` → ``window.api`` then
deletes the source handle. See ``test_weight_no_silent_rebalance.py``
and the rest of ``tests/wimi_test/scenarios/`` for the same convention.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_subject_image_prompt_renders_after_tagging_primary_subject(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Tag a subject that already has media → prompt renders.

    Arrange
    -------
    1. Create an exam context.
    2. Create one subject ``S`` under it.
    3. Create a review session for the exam context.
    4. Create an entry in that session tagged with ``S`` as a primary
       subject. ``add_entry_media`` defaults ``linked_subject_ids`` to
       the entry's primary subjects, so the attached media record will
       carry ``linked_subject_ids = [S.id]``.
    5. Attach a media row to that entry — this is the seed the prompt
       is supposed to surface.

    Act
    ---
    1. Navigate to the entry form for the same session (creates a fresh
       entry slot that does not yet have any media).
    2. From JS, drive ``selectSubject(S.id, ...)``. The typeahead's
       on-select handler is what calls ``checkSubjectImages`` — calling
       ``selectSubject`` directly exercises the same code path as a
       real user picking an option from the autocomplete dropdown,
       without depending on the typeahead's dropdown render timing.

    Assert
    ------
    ``[data-testid="entry-form-image-autopopulate-prompt"]`` becomes
    visible in the DOM within a few hundred ms (the bridge round-trip
    plus prompt mount).
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Subject Image Prompt Regression",
        exam_description=(
            "Regression for getMediaBySubject param-shift bug "
            "(question_entry.js checkSubjectImages)."
        ),
    )

    subject = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name="SIP Cardiology",
        level_type="System",
        weight_source="user_defined",
    )

    # Seed an entry tagged with the subject + attach a media row so the
    # subject has a "library" of associated images to surface. Two
    # sessions so the seed entry lives separately from the entry slot
    # the test interacts with — keeps the assertion clean.
    seed_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name="SIP seed session",
        date_encountered=date.today(),
    )
    seed_entry = db.create_question_entry(
        review_session_id=seed_session.id,
        user_answer="A",
        correct_answer="B",
        reflection="seed reflection",
        explanation="seed explanation",
        primary_subject_ids=[subject.id],
    )
    # add_entry_media defaults linked_subject_ids to the entry's primary
    # subjects; we pass it explicitly to make the test self-documenting.
    db.add_entry_media(
        entry_id=seed_entry.id,
        file_uuid="11111111-1111-1111-1111-111111111111",
        original_filename="seed_image.png",
        mime_type="image/png",
        file_size_bytes=1024,
        linked_subject_ids=[subject.id],
    )

    # Fresh session + slot for the test interaction. The page's init()
    # will land us on entry slot 1 of this session, which has no media
    # yet — so the EntryState.formData.media.length === 0 early-return
    # in checkSubjectImages does NOT fire.
    interactive_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=1,
        total_incorrect=1,
        session_name="SIP interactive session",
        date_encountered=date.today(),
    )

    # ---- Act ---------------------------------------------------------
    wimi_page.goto(
        "entry-form",
        query={"session_id": interactive_session.id},
    )

    # Bridge surface readiness probe — the wrapper we just fixed must
    # be present, and EntryState.session must have been loaded by
    # initializeEntryPage() (the early-return at line 660 of
    # question_entry.js short-circuits without it).
    api_ready = wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getMediaBySubject === 'function' "
        "&& typeof selectSubject === 'function')()"
    )
    assert api_ready, (
        "window.api.getMediaBySubject and/or the page-scope "
        "selectSubject() helper is not available. Check that "
        "src/web/js/api/media.js loaded via _loader.js and that "
        "src/web/js/question_entry.js is included by question_entry.html."
    )

    # initializeEntryPage() is async — give it a beat to fetch the
    # session and render the empty form before we drive the typeahead.
    wimi_page.wait_for_timeout(500)

    session_loaded = wimi_page.eval_js(
        "(() => !!(EntryState && EntryState.session "
        "&& EntryState.session.exam_context_id))()"
    )
    assert session_loaded, (
        "EntryState.session was not populated after navigating to "
        "the entry form. The exam_context_id guard at the top of "
        "checkSubjectImages would short-circuit the test."
    )

    # Drive selectSubject directly — same handler the typeahead's
    # dropdown click invokes. addSubjectChip (used elsewhere) is the
    # programmatic-add path and does NOT call checkSubjectImages.
    select_result: Any = wimi_page.eval_js(
        f"""
        (() => {{
            try {{
                selectSubject(
                    {subject.id},
                    'SIP Cardiology',
                    'SIP Cardiology',
                    'primary'
                );
                return {{ok: true}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """
    )
    assert select_result.get("ok"), (
        f"selectSubject raised: {select_result!r}"
    )

    # The prompt mount is async: selectSubject fires checkSubjectImages
    # which awaits the bridge round-trip then calls
    # showImageAutoPopulationPrompt. 1500 ms is comfortably above the
    # observed local round-trip while staying tight enough to fail
    # fast on a regression.
    deadline_ms = 1500
    poll_step_ms = 100
    elapsed = 0
    prompt_present = False
    while elapsed < deadline_ms:
        prompt_present = bool(wimi_page.eval_js(
            "!!document.querySelector("
            "'[data-testid=\"entry-form-image-autopopulate-prompt\"]')"
        ))
        if prompt_present:
            break
        wimi_page.wait_for_timeout(poll_step_ms)
        elapsed += poll_step_ms

    assert prompt_present, (
        "Image autopopulation prompt did not render within "
        f"{deadline_ms}ms after tagging a primary subject that has an "
        "associated media row. Likely regression of the "
        "getMediaBySubject param-shift bug — verify that "
        "question_entry.js:checkSubjectImages calls "
        "api.getMediaBySubject(subjectId, 5, dimensionId) with three "
        "args (no leading exam_context_id)."
    )
