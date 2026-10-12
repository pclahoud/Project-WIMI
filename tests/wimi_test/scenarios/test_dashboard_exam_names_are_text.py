"""Regression: the dashboard treats an exam's name as text everywhere (#548).

Two sinks on the landing page carried ``exam.exam_name`` past the escaping
the card title already had:

* **The Delete Permanently button's inline handler.** It was
  ``onclick="confirmHardDeleteExam(id, '${WimiEscape.html(name).replace(/'/g, "\\'")}')"``
  -- a JavaScript string inside an HTML attribute. HTML escaping turns ``'``
  into ``&#39;``, the attribute parser turns it straight back, and the
  ``.replace`` never sees a quote to escape, so a name holding ``'`` closed
  the string and the rest ran as code when the button was pressed. The
  button now carries only the id and gets a listener.
* **The toast.** ``Toast.show`` built its body with ``innerHTML`` from
  ``title`` and ``message``, and suspending an exam passes the name in the
  message, so ``<img onerror>`` in a name executed on Suspend.

Seeded through the database, because an exam name reaches this page from a
profile import or another computer's folder-sync copy as well as from the
wizard.
"""
from __future__ import annotations

import json

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# A name that closes the inline handler's string, and markup besides.
DELETE_NAME = "Q'+(window.__hd_code=1)+' <img src=x onerror=\"window.__hd_img=1\">"
SUSPEND_NAME = 'Cardio <img src=x onerror="window.__toast_img=1">'

PRESS_DELETE = """
(() => {
  window.__confirm_msgs = [];
  window.confirm = (m) => { window.__confirm_msgs.push(String(m)); return false; };
  const btn = document.querySelector('[data-testid="dashboard-exam-%d-delete-btn"]');
  if (!btn) return 'no button';
  btn.click();
  return 'pressed';
})()
"""

TOAST = """
(() => {
  const toasts = [...document.querySelectorAll('.toast')];
  const t = toasts.find(x => (x.textContent || '').includes('suspended'));
  if (!t) return null;
  return JSON.stringify({
    img_fired: window.__toast_img === 1,
    imgs: t.querySelectorAll('img').length,
    title: t.querySelector('.toast-title').textContent,
    message: t.querySelector('.toast-message').textContent,
  });
})()
"""


@pytest.mark.slow
@pytest.mark.regression
def test_exam_names_are_shown_not_executed(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    suspended = db.create_exam_context(exam_name=DELETE_NAME, exam_description='#548')
    active = db.create_exam_context(exam_name=SUSPEND_NAME, exam_description='#548')
    db.conn.execute('UPDATE exam_contexts SET is_active = 0 WHERE id = ?', (suspended.id,))
    db.conn.commit()

    wimi_page.goto('dashboard')
    assert poll(wimi_page, "!!document.querySelector('[data-testid=\"dashboard-exam-%d-delete-btn\"]')"
                % suspended.id, timeout_ms=20000), 'the suspended exam card never drew'

    # --- Delete Permanently: the name must reach confirm() as the name ----
    assert wimi_page.eval_js(PRESS_DELETE % suspended.id) == 'pressed'
    wimi_page.wait_for_timeout(300)
    state = json.loads(wimi_page.eval_js(
        "JSON.stringify({code: window.__hd_code === 1, img: window.__hd_img === 1,"
        " msgs: window.__confirm_msgs})"))
    assert not state['code'], 'the exam name ran as code in the Delete handler (#548)'
    assert not state['img'], state
    assert len(state['msgs']) == 1, f'Delete Permanently asked {len(state["msgs"])} times: {state}'
    assert f'"{DELETE_NAME}"' in state['msgs'][0], (
        f'the confirmation must name the exam exactly: {state["msgs"][0]!r}')

    # --- Suspend: the toast names the exam as text -----------------------
    wimi_page.eval_js('confirmSuspendExam(%d)' % active.id)
    assert poll(wimi_page, "document.getElementById('delete-exam-name').textContent.length > 0",
                timeout_ms=5000), 'the suspend modal never opened'
    wimi_page.eval_js("document.getElementById('delete-confirm').click()")
    assert poll(wimi_page, '(%s) !== null' % TOAST.strip(), timeout_ms=10000), (
        'no "suspended" toast appeared')
    wimi_page.wait_for_timeout(300)   # a broken <img>'s onerror fires async
    toast = json.loads(wimi_page.eval_js(TOAST))
    assert not toast['img_fired'], 'the exam name executed as markup in the toast (#548)'
    assert toast['imgs'] == 0, toast
    assert toast['title'] == 'Exam Suspended', toast
    assert toast['message'] == f'"{SUSPEND_NAME}" has been suspended.', toast
