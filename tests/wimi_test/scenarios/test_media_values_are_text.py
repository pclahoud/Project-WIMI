"""Regression: the entry form's image surfaces render stored values as text (#548 stage 3b).

``media_upload.js`` and ``image_browser.js`` built their markup with
``innerHTML`` and interpolated four student values raw:

* the image's file name (``user_filename`` / ``original_filename``) -- the
  name of a file the student dropped in, or typed into Rename -- into the
  thumbnail's ``alt``/``title`` and caption, the subject-assignment
  preview, and the Browse Existing Images card;
* a linked subject's name into the thumbnail's subject chips and the
  assignment modal's checkbox list;
* a dimension's name into the thumbnail's dimension select and the
  assignment modal's group headers;
* the exam names a reused image belongs to, on the browser card.

Each is seeded through the database, because a profile import or the
subject importer can deliver any of them without passing through the
control that would normally type them. The handlers are distinct per
payload, so a failure names the value that executed.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# A quote breaks out of a double-quoted attribute; a tag runs in content.
FILE = 'scan" onerror="window.__mu_attr=1" x="<img src=x onerror=window.__mu_file=1>.png'
SUBJ = 'Cardio <img src=x onerror=window.__mu_subj=1>'
DIM = 'Systems </select><img src=x onerror=window.__mu_dim=1>'
EXAM = 'Boards <img src=x onerror=window.__mu_exam=1>'

FLAGS = "['__mu_attr','__mu_file','__mu_subj','__mu_dim','__mu_exam']"
FIRED = f"{FLAGS}.filter(k => window[k] === 1)"
RESET = f"{FLAGS}.forEach(k => {{ delete window[k]; }})"

THUMB = """
(() => {
  const t = document.querySelector('.media-thumbnail');
  if (!t || !t.querySelector('.dimension-select')) return null;
  return JSON.stringify({
    fired: %s,
    imgs: t.querySelectorAll('img').length,
    alt: t.querySelector('.thumbnail-image-container img').getAttribute('alt'),
    title: t.querySelector('.thumbnail-name').getAttribute('title'),
    caption: t.querySelector('.thumbnail-name').textContent.trim(),
    chip: t.querySelector('.thumbnail-subject-chip').getAttribute('title'),
    options: Array.from(t.querySelectorAll('.dimension-select option'))
                  .map(o => o.textContent),
  });
})()
""" % FIRED

MODAL = """
(() => {
  const list = document.querySelector('.media-subject-checkbox');
  if (!list) return null;
  const preview = EntryState.mediaUpload.subjectPreview;
  const modalList = EntryState.mediaUpload.subjectList;
  return JSON.stringify({
    fired: %s,
    preview_imgs: preview.querySelectorAll('img').length,
    preview_alt: preview.querySelector('img').getAttribute('alt'),
    preview_text: preview.querySelector('span').textContent.trim(),
    list_imgs: modalList.querySelectorAll('img').length,
    header: modalList.querySelector('.media-subject-dimension-header').textContent,
    name: modalList.querySelector('.media-subject-name').textContent,
  });
})()
""" % FIRED

BROWSER = """
(() => {
  const card = document.querySelector('.image-browser-card');
  if (!card) return null;
  const exam = card.querySelector('.image-browser-exam');
  return JSON.stringify({
    fired: %s,
    imgs: card.querySelectorAll('img').length,
    alt: card.querySelector('img').getAttribute('alt'),
    name_title: card.querySelector('.image-browser-name').getAttribute('title'),
    name_text: card.querySelector('.image-browser-name').textContent,
    exam_title: exam && exam.getAttribute('title'),
    exam_text: exam && exam.textContent,
  });
})()
""" % FIRED


def _seed(db) -> int:
    exam = db.create_exam_context(exam_name=EXAM, exam_description='#548')
    dim_id = db.create_dimension(exam.id, DIM, 1)
    subject = db.create_subject_node(exam.exam_name, SUBJ, 'System', dimension_id=dim_id)
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=1,
        session_name='Media session', date_encountered=date.today())
    entry = db.create_question_entry(session.id, 'a', 'b', reflection='<p>r</p>',
                                     primary_subject_ids=[subject.id])
    assert entry.is_draft
    db.add_entry_media(entry.id, 'no-such-file-uuid', original_filename=FILE,
                       mime_type='image/png', file_size_bytes=10,
                       linked_subject_ids=[subject.id])
    db.conn.commit()
    return session.id


def _read(page: WimiPage, probe: str, what: str) -> dict:
    assert poll(page, '(%s) !== null' % probe.strip(), timeout_ms=20000), (
        f'{what} never drew')
    page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    return json.loads(page.eval_js(probe))


@pytest.mark.slow
@pytest.mark.regression
def test_media_values_are_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    session_id = _seed(wimi_session.user.db)
    wimi_page.goto('entry-form', query={'session_id': session_id})
    wait_for_form_ready(wimi_page)

    # Every surface is read before anything is asserted, so a failure
    # reports all three rather than stopping at the first.
    thumb = _read(wimi_page, THUMB, 'the thumbnail (with its dimension select)')

    wimi_page.eval_js(RESET)
    wimi_page.eval_js("document.querySelector('.media-thumbnail .thumb-subjects').click()")
    modal = _read(wimi_page, MODAL, 'the subject assignment modal')
    wimi_page.eval_js("EntryState.mediaUpload.closeSubjectAssignmentModal()")

    wimi_page.eval_js(RESET)
    wimi_page.eval_js("EntryState.mediaUpload.openImageBrowser()")
    card = _read(wimi_page, BROWSER, 'the image browser card')

    fired = {'thumbnail': thumb['fired'], 'assignment modal': modal['fired'],
             'image browser': card['fired']}
    assert not any(fired.values()), f'executed as markup: {fired}'

    # ---- Thumbnail grid: the thumbnail is its only <img> -----------------
    assert thumb['imgs'] == 1, thumb
    assert thumb['alt'] == FILE and thumb['title'] == FILE, thumb
    # The caption is the component's own truncation of the name, as text.
    assert thumb['caption'] == 'scan" on....png', thumb
    assert thumb['chip'] == SUBJ, thumb
    assert DIM in thumb['options'], thumb

    # ---- Subject assignment modal ---------------------------------------
    assert modal['preview_imgs'] == 1 and modal['list_imgs'] == 0, modal
    assert modal['preview_alt'] == FILE and modal['preview_text'] == FILE, modal
    assert modal['name'] == SUBJ, modal
    # The group header reads 'General', not DIM: the entry form hands the
    # component subjects without a dimension_id (populateFormWithEntry and
    # addSubjectChip both keep only id/name/path), so the per-dimension
    # grouping -- and DIM reaching this header -- is unreachable from here.
    # The header is escaped regardless; this pins what the page shows today.
    assert modal['header'] == 'General', modal

    # ---- Browse Existing Images -----------------------------------------
    assert card['imgs'] == 1, card
    assert card['alt'] == FILE and card['name_title'] == FILE, card
    assert card['name_text'] == FILE[:17] + '...', card
    assert card['exam_title'] == EXAM and card['exam_text'] == EXAM, card
