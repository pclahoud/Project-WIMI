"""Regression: the entry form's own pickers render stored values as text (#548 stage 3b).

``question_entry.js`` had three shapes of the #324 class left after stage 2:

* **A value inside a JavaScript string inside an ``onclick``.** The subject
  dropdown, the quick-add parent dropdown, the error-type dropdown, the
  error-type hierarchy and the create-tag button all wrote
  ``onclick="f(1, '${WimiEscape.html(name)...}')"``. HTML escaping cannot
  protect that context: the attribute is decoded before its JavaScript is
  parsed, so ``&#39;`` is a quote again and a subject named
  ``x');code;('`` runs ``code`` when the student picks it -- and an
  ordinary ``O'Brien`` was a syntax error that made the option dead.
* **A colour interpolated raw** into ``style``/``data-``/``onclick``.
  ``create_tag_group`` and ``create_hierarchical_tag`` validate nothing, and
  a profile import carries the column as it is.
* **Plain content sinks**: the toast (whose callers put subject, tag and
  group names in it), the image auto-populate prompt (the subject's name),
  and the attach picker's note preview, which parsed a stored note into a
  detached ``<div>`` of this live document -- where an ``<img onerror>``
  still loads.

Everything is seeded through the database rather than typed, because the
subject importer and a profile import can deliver a value that never
passed through the control that would normally create it. Each payload
sets its own flag, so a failure names the value that executed. The
student's text must also come back exactly.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SUBJ_JS = "Brien');window.__qe_subjs=1;('"
TAG_JS = "Rushed');window.__qe_tagjs=1;('"
NEW_JS = "Newtag');window.__qe_newjs=1;('"
COLOR = '#fff"><img src=x onerror=window.__qe_color=1>'
GROUP = 'Habits <img src=x onerror=window.__qe_group=1>'
RENAL = 'Renal <img src=x onerror=window.__qe_prompt=1>'
NOTE = '<p>Beta blockers <b>first</b>.</p><img src=x onerror="window.__qe_note=1">'

FLAGS = ['__qe_subjs', '__qe_tagjs', '__qe_newjs', '__qe_color', '__qe_group',
         '__qe_prompt', '__qe_note']
FIRED = f"{json.dumps(FLAGS)}.filter(k => window[k] === 1)"
RESET = f"{json.dumps(FLAGS)}.forEach(k => {{ delete window[k]; }})"


def _seed(db) -> dict:
    exam = db.create_exam_context(exam_name='QE Exam', exam_description='#548')
    brien = db.create_subject_node(exam.exam_name, SUBJ_JS, 'System')
    renal = db.create_subject_node(exam.exam_name, RENAL, 'System')
    group = db.create_tag_group(exam.exam_name, GROUP, color_hex=COLOR)
    # Two tags, so neither payload masks the other: on the unfixed page the
    # colour's quote ends the tag's start tag early, which leaves the name's
    # onclick as text and nothing to click.
    tag = db.create_hierarchical_tag(exam.exam_name, TAG_JS, group.id, color_hex='#123456')
    db.create_hierarchical_tag(exam.exam_name, 'Slow reading', group.id, color_hex=COLOR)
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=3,
        session_name='QE session', date_encountered=date.today())
    # A finished entry on Renal carrying an image and a note, so the new
    # entry the form opens on is offered both when Renal is picked.
    done = db.create_question_entry(session.id, 'a', 'b', reflection='<p>r</p>',
                                    explanation='<p>e</p>',
                                    primary_subject_ids=[renal.id])
    assert not done.is_draft
    db.add_entry_media(done.id, 'no-such-file', original_filename='ecg.png',
                       mime_type='image/png', file_size_bytes=10,
                       linked_subject_ids=[renal.id])
    db.add_entry_note(done.id, content_html=NOTE, linked_subject_ids=[renal.id])
    db.conn.commit()
    return {'session': session.id, 'brien': brien.id, 'renal': renal.id,
            'tag': tag.id}


def _type(page: WimiPage, selector: str, text: str) -> None:
    page.eval_js(
        f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
        f" el.focus(); el.value = {json.dumps(text)};"
        f" el.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")


def _click_when(page: WimiPage, selector: str, what: str) -> None:
    found = f"!!document.querySelector({json.dumps(selector)})"
    assert poll(page, found, timeout_ms=15000), f'{what} never appeared'
    page.eval_js(RESET)
    page.eval_js(f"document.querySelector({json.dumps(selector)}).click()")
    page.wait_for_timeout(400)   # a broken <img>'s onerror fires async


def _state(page: WimiPage, extra: str = 'null') -> dict:
    return json.loads(page.eval_js(
        f"JSON.stringify({{fired: {FIRED}, extra: ({extra})}})"))


@pytest.mark.slow
@pytest.mark.regression
def test_entry_form_values_are_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    ids = _seed(wimi_session.user.db)
    wimi_page.goto('entry-form', query={'session_id': ids['session']})
    wait_for_form_ready(wimi_page)
    assert poll(wimi_page, "!!document.querySelector('#tag-hierarchy .tag-item')"), (
        'the error-type hierarchy never drew')
    wimi_page.wait_for_timeout(400)
    seen = {}

    # ---- On load: the error-type hierarchy and its colours --------------
    seen['load'] = _state(wimi_page)

    # ---- Subject dropdown: pick the subject whose name is a JS string ---
    _type(wimi_page, '#primary-subject-search', 'Brien')
    _click_when(wimi_page, f"#primary-subject-dropdown [data-id='{ids['brien']}']",
                'the subject option')
    seen['subject dropdown'] = _state(wimi_page, (
        "EntryState.formData.primarySubjects.map(s => s.name)"))

    # ---- Quick-add parent dropdown --------------------------------------
    wimi_page.eval_js("Modal.open('quick-add-subject-modal')")
    _type(wimi_page, '#quick-add-parent-search', 'Brien')
    _click_when(wimi_page, f"#quick-add-parent-dropdown [data-id='{ids['brien']}']",
                'the parent option')
    seen['parent dropdown'] = _state(
        wimi_page, "document.getElementById('quick-add-parent-search').value")
    wimi_page.eval_js("Modal.close('quick-add-subject-modal')")

    # ---- Error-type dropdown, then the hierarchy button -----------------
    _type(wimi_page, '#tag-search', 'Rushed')
    _click_when(wimi_page, f"#tag-dropdown [data-id='{ids['tag']}']", 'the tag option')
    seen['tag dropdown'] = _state(wimi_page, (
        "EntryState.formData.tags.map(t => [t.name, t.color])"))
    _click_when(wimi_page, f"#tag-hierarchy [data-tag-id='{ids['tag']}']",
                'the hierarchy button')
    seen['tag hierarchy'] = _state(wimi_page, "EntryState.formData.tags.length")

    # ---- Create-tag: the typed query, and the toast that names the group
    _type(wimi_page, '#tag-search', NEW_JS)
    _click_when(wimi_page, '#tag-dropdown .dropdown-create-btn', 'the create button')
    assert poll(wimi_page, "!!document.querySelector('.toast--success .toast-message')"), (
        'creating the tag raised no success toast')
    seen['create tag'] = _state(wimi_page, (
        "[EntryState.formData.tags.map(t => t.name),"
        " document.querySelector('.toast--success .toast-message').textContent,"
        " document.querySelectorAll('.toast-container img').length]"))

    # ---- Manage error types modal ---------------------------------------
    wimi_page.eval_js(RESET)
    wimi_page.eval_js("openManageTagsModal()")
    assert poll(wimi_page, "!!document.querySelector('#manage-tags-list .manage-tag-row')")
    wimi_page.wait_for_timeout(400)
    seen['manage modal'] = _state(wimi_page)
    wimi_page.eval_js("closeManageTagsModal()")

    # ---- Picking Renal: the image prompt, then the attach-notes picker --
    wimi_page.eval_js(RESET)
    wimi_page.eval_js(f"selectSubject({ids['renal']}, {json.dumps(RENAL)},"
                      f" {json.dumps(RENAL)}, 'primary')")
    assert poll(wimi_page, "!!document.getElementById('image-autopopulate-prompt')"), (
        'picking Renal never offered its image')
    wimi_page.wait_for_timeout(400)
    seen['image prompt'] = _state(wimi_page, (
        "document.querySelector('#image-autopopulate-prompt .autofill-prompt-text span')"
        ".textContent"))
    assert poll(wimi_page, "_attachCandidates.notes.length > 0"), (
        'the Renal note was never offered as an attach candidate')
    wimi_page.eval_js(RESET)
    wimi_page.eval_js("openAttachExistingPicker('notes')")
    wimi_page.wait_for_timeout(400)
    seen['attach notes'] = _state(wimi_page, (
        "document.querySelector('#attach-existing-list .attach-existing-preview')"
        ".textContent"))

    fired = {k: v['fired'] for k, v in seen.items() if v['fired']}
    assert not fired, f'executed as markup: {fired}\n{json.dumps(seen, indent=1)}'

    # ---- The other half: the student's text arrives exactly -------------
    assert SUBJ_JS in seen['subject dropdown']['extra'], seen['subject dropdown']
    assert seen['parent dropdown']['extra'] == SUBJ_JS, seen['parent dropdown']
    assert [TAG_JS, '#123456'] in seen['tag dropdown']['extra'], seen['tag dropdown']
    assert seen['tag hierarchy']['extra'] == 0, seen['tag hierarchy']   # toggled off again
    names, toast, toast_imgs = seen['create tag']['extra']
    assert NEW_JS in names, seen['create tag']
    assert toast == f'"{NEW_JS}" added to {GROUP}' and toast_imgs == 0, seen['create tag']
    assert seen['image prompt']['extra'] == f'1 image previously used with "{RENAL}"', (
        seen['image prompt'])
    assert seen['attach notes']['extra'] == 'Beta blockers first.', seen['attach notes']
