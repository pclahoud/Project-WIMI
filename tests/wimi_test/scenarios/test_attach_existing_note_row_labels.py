"""The + Add existing picker names where each note lives (#848 Wave 2a).

Four labels, from ``attachment_count`` (which ``get_notes_by_subjects``
attaches since Wave 2a) and the presence of ``question_entry_id``:

* a note on no entry, attached nowhere   -> ``not on any entry``
* a note on its own, attached to one entry -> ``on 1 entry``
* a note born on another entry, held only there -> ``from entry #N``
* a note held by two entries -> ``on 2 entries``

Nothing read these words until PR #864's round-3 review. The control is that
all four rows are drawn: a picker that opened empty, or missed a note, fails
on the row lookup before any label is compared.
"""
from __future__ import annotations

import json

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

from _helpers.quick_note import open_form, seed_entry, seed_free_note
from _helpers.w114_form_ready import poll

BUTTON_READY = (
    "(() => { const b = document.querySelector("
    "'[data-testid=\"entry-form-notes-attach-existing-button\"]');"
    " return !!b && !b.disabled; })()"
)
PICKER_OPEN = (
    "(() => { const m = document.getElementById('attach-existing-modal');"
    " return !!m && m.classList.contains('active'); })()"
)


def _labels(page: WimiPage, ids: list[int]) -> dict:
    return json.loads(page.eval_js(
        "JSON.stringify(Object.fromEntries(" + json.dumps(ids) + ".map(id => {"
        " const r = document.querySelector(`[data-testid=\"attach-existing-item-notes-${id}\"]`);"
        " const m = r && r.querySelector('.attach-existing-meta');"
        " return [id, m ? m.textContent.trim() : null]; })))"))


@pytest.mark.slow
@pytest.mark.regression
def test_each_picker_row_says_where_the_note_lives(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    world = seed_entry(db, name="QNL")
    s = world["subject_id"]
    b = db.create_question_entry(review_session_id=world["session_id"], user_answer="c",
                                 correct_answer="d", primary_subject_ids=[s])
    c = db.create_question_entry(review_session_id=world["session_id"], user_answer="e",
                                 correct_answer="f", primary_subject_ids=[s])
    nowhere = seed_free_note(db, "<p>QNL nowhere</p>", subject_ids=[s])
    own_on_c = seed_free_note(db, "<p>QNL own on c</p>", subject_ids=[s])
    db.attach_existing_note_to_entry(own_on_c, c.id)
    on_b = db.add_entry_note(b.id, content_html="<p>QNL on b</p>", linked_subject_ids=[s]).id
    on_two = db.add_entry_note(b.id, content_html="<p>QNL on b and c</p>",
                               linked_subject_ids=[s]).id
    db.attach_existing_note_to_entry(on_two, c.id)
    db.conn.commit()

    open_form(wimi_page, world["session_id"], world["entry_id"])
    assert poll(wimi_page, BUTTON_READY, timeout_ms=20000), (
        "the + Add existing notes button never enabled for an entry tagged with the subject")
    wimi_page.locator(testid="entry-form-notes-attach-existing-button").click()
    assert poll(wimi_page, PICKER_OPEN, timeout_ms=5000), "the picker did not open"

    ids = [nowhere, own_on_c, on_b, on_two]
    labels = None
    for _ in range(50):
        labels = _labels(wimi_page, ids)
        if all(v is not None for v in labels.values()):
            break
        wimi_page.wait_for_timeout(100)
    assert all(v is not None for v in labels.values()), f"rows missing from the picker: {labels!r}"

    assert labels == {
        str(nowhere): "not on any entry",
        str(own_on_c): "on 1 entry",
        str(on_b): f"from entry #{b.id}",
        str(on_two): "on 2 entries",
    }, labels
