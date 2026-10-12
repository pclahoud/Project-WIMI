"""Regression: session setup treats session and source names as text (#548).

Two sinks on this page carried a student's text past escaping:

* **A previous session's Delete button** had
  ``onclick="confirmDeleteSession(id, '${WimiEscape.html(name).replace(/'/g, "\\'")}')"``
  -- a JavaScript string inside an HTML attribute, where HTML escaping is
  undone by the attribute parser before the script reads it. A session name
  holding ``'`` closed the string and the rest ran as code on the press. The
  button now carries the session id and a listener looks the name up.
* **The toast** built its body with ``innerHTML``, and adding or renaming a
  question source passes the source's name in the message.

The session name is seeded through the database because the session
importer and a profile import deliver names that never passed through this
page's form.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

SESSION_NAME = "S'+(window.__sd_code=1)+' <img src=x onerror=\"window.__sd_img=1\">"
# The handler records WHERE it ran: the same name is also drawn by the
# source picker (custom-select.js), which is outside this file's fix, so a
# bare "did it fire" flag could not tell the toast from the picker.
SOURCE_NAME = ('Bank <img src=x onerror="window.__src_where = (window.__src_where || [])'
               '.concat(this.closest(\'.toast\') ? \'toast\' : \'elsewhere\')">')

PRESS_DELETE = """
(() => {
  const card = document.querySelector('[data-testid="session-card-%d"]');
  const btn = card && [...card.querySelectorAll('button')].find(b => b.textContent.trim() === 'Delete');
  if (!btn) return 'no button';
  btn.click();
  return 'pressed';
})()
"""

TOAST = """
(() => {
  const t = [...document.querySelectorAll('.toast')]
    .find(x => (x.textContent || '').includes('has been added'));
  if (!t) return null;
  return JSON.stringify({
    fired_in_toast: (window.__src_where || []).includes('toast'),
    imgs: t.querySelectorAll('img').length,
    title: t.querySelector('.toast-title').textContent,
    message: t.querySelector('.toast-message').textContent,
  });
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_session_and_source_names_are_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    exam = db.create_exam_context(exam_name='Names Exam', exam_description='#548')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=2, total_incorrect=1,
        session_name=SESSION_NAME, date_encountered=date.today())
    db.conn.commit()

    wimi_page.goto('session-setup', query={'exam_id': exam.id})
    assert poll(wimi_page, "!!document.querySelector('[data-testid=\"session-card-%d\"]')"
                " && !document.querySelector('[data-page-gated][inert]')" % session.id,
                timeout_ms=20000), 'the previous-session card never drew'

    # --- Delete: the name reaches the confirmation modal as the name -----
    assert wimi_page.eval_js(PRESS_DELETE % session.id) == 'pressed'
    wimi_page.wait_for_timeout(300)
    state = json.loads(wimi_page.eval_js(
        "JSON.stringify({code: window.__sd_code === 1, img: window.__sd_img === 1,"
        " shown: document.getElementById('delete-session-name').textContent})"))
    assert not state['code'], 'the session name ran as code in the Delete handler (#548)'
    assert not state['img'], state
    assert state['shown'] == SESSION_NAME, (
        f'the delete modal must name the session exactly: {state["shown"]!r}')
    wimi_page.eval_js("Modal.close('delete-session-modal')")

    # --- Add a source: the toast names it as text -------------------------
    wimi_page.eval_js('openAddSourceModal()')
    wimi_page.eval_js("document.getElementById('new-source-name').value = %s" % json.dumps(SOURCE_NAME))
    wimi_page.eval_js("document.getElementById('add-source-save').click()")
    assert poll(wimi_page, '(%s) !== null' % TOAST.strip(), timeout_ms=10000), (
        'no "has been added" toast appeared')
    wimi_page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    toast = json.loads(wimi_page.eval_js(TOAST))
    assert not toast['fired_in_toast'], 'the source name executed as markup in the toast (#548)'
    assert toast['imgs'] == 0, toast
    assert toast['title'] == 'Source Added', toast
    assert toast['message'] == f'"{SOURCE_NAME}" has been added.', toast
