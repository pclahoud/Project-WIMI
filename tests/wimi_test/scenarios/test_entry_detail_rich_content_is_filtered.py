"""Regression: the entry page keeps the student's formatting and runs nothing (#589).

Owner's decision on #589 (2026-10-08): reflections, explanations and notes keep
their formatting on the entry page, and the markup is filtered by an
allowlist -- ``WimiRichHtml`` in ``rich_html.js``, no new dependency. The
renderer used to ``innerHTML`` the stored string, so an ``<img onerror>`` in
each field ran there (measured by #548's sweep), the note's twice because
``isEmpty`` also parsed it through a live ``<div>``.

Two halves, and both are needed:

* **Nothing runs.** Every stored field carries a different attack -- an
  ``onerror`` image, a ``javascript:`` link, an ``svg onload``, an iframe
  ``srcdoc``, an attribute break-out, a ``details ontoggle`` and a CSS
  ``url()``, the CSS escapes and full-window layer of #591 -- seeded through
  the database, because an import delivers HTML
  the editor never saw.
* **The formatting survives.** A filter that strips everything would pass the
  first half. So the second test writes formatted content THROUGH THE REAL
  EDITOR -- TinyMCE's own ``setContent``/``getContent`` round trip on the
  entry form, i.e. exactly the string the editor stores -- and checks that
  bold, lists, a quote, a heading, a table, a link, a pasted image and a
  maths formula all reach the entry page, and that no style declaration the
  editor's colour, alignment, list and table controls wrote is lost (#591).
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.page_gate import wait_for_release
from _helpers.w114_form_ready import poll, wait_for_form_ready
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

ATTACKS = {
    'reflection': (
        '<p>Keep <b>this</b></p>'
        '<img src=x onerror="window.__rich=(window.__rich||[]).concat(\'img\')">'
        '<a href="javascript:window.__rich=(window.__rich||[]).concat(\'js\')">jslink</a>'
        '<svg onload="window.__rich=(window.__rich||[]).concat(\'svg\')"></svg>'),
    'explanation': (
        '<p title=\'x" onmouseover="window.__rich=1\'>breakout</p>'
        '<iframe srcdoc="<script>parent.__rich=(parent.__rich||[]).concat(\'iframe\')</script>"></iframe>'
        '<details open ontoggle="window.__rich=(window.__rich||[]).concat(\'details\')">toggled</details>'
        '<div style="background:url(https://example.invalid/x.png)">styled</div>'
        # #591: CSS escapes the old style regex let through (measured: the
        # parser read both as url()), and a layer over the whole window.
        '<div style="background:\\75 rl(https://example.invalid/e.png)">escaped</div>'
        '<div style="background-image:\\75\\72\\6c(https://example.invalid/f.png)">escfull</div>'
        '<div style="position:fixed;inset:0;z-index:9999;opacity:0">overlay</div>'
        '<p style="margin-top:-400px;transform:scale(9)">lifted</p>'),
    'notes': (
        '<p>A note</p>'
        '<img src=x onerror="window.__rich=(window.__rich||[]).concat(\'note\')">'
        # Passes SAFE_IMG (a well-formed data URL) and then fails to decode,
        # so only the attribute allowlist stops its onerror. Every other
        # payload is stopped earlier, which hid that layer from the tests.
        '<img src="data:image/png;base64,QUJD"'
        ' onerror="window.__rich=(window.__rich||[]).concat(\'attr\')">'),
}

#: A 1x1 transparent PNG, as a pasted image is stored (paste_data_images).
PNG = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlE'
       'QVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')

FORMATTED = (
    '<h2>Heading</h2>'
    '<p><strong>Bold</strong> <em>italic</em> <u>under</u></p>'
    '<ul><li>one</li><li>two</li></ul><ol><li>first</li></ol>'
    '<blockquote><p>quoted</p></blockquote>'
    '<p style="text-align: center;"><span style="color: #e03e2d; background-color: #fbeeb8;">'
    'coloured</span></p>'
    '<ol style="list-style-type: lower-alpha;"><li>alpha</li></ol>'
    '<table style="border-collapse: collapse; width: 100%; border-width: 1px;'
    ' border-style: solid; border-color: #ced4da; height: 40px;" border="1"><tbody>'
    '<tr><td style="background-color: #ecf0f1; vertical-align: top; width: 50%;'
    ' text-align: right; padding: 4px; border-color: #3598db;">a</td><td>b</td></tr>'
    '<tr><td>c</td><td>d</td></tr></tbody></table>'
    '<p><a href="https://example.org/page">a link</a></p>'
    '<p><span class="math-tex" data-formula="a^2+b^2=c^2">a^2+b^2=c^2</span></p>'
    f'<p><img src="{PNG}" alt="pasted"></p>'
)

STATE = """
(() => {
  const q = s => document.querySelector(s);
  const all = s => document.querySelectorAll(s).length;
  const root = q('.entry-detail, main') || document.body;
  return JSON.stringify({
    fired: window.__rich || null,
    reflection: (q('#reflection-content') || {}).textContent || '',
    explanation: (q('#explanation-content') || {}).textContent || '',
    notes: (q('#notes-content') || {}).textContent || '',
    dangerous: all('#reflection-content *[onerror], #explanation-content *[onmouseover],'
                   + ' #reflection-content svg, #explanation-content iframe,'
                   + ' #explanation-content details, #notes-content *[onerror],'
                   + ' a[href^="javascript"]'),
    styled_url: Array.from(document.querySelectorAll('#explanation-content [style]'))
        .some(e => /url\\(/i.test(e.getAttribute('style'))),
    // Judged on what the engine computed, not on the attribute text (#591).
    escaped_out: Array.from(document.querySelectorAll('#explanation-content *'))
        .filter(e => {
          const cs = getComputedStyle(e);
          return cs.backgroundImage !== 'none' || cs.position !== 'static'
              || cs.opacity !== '1' || cs.transform !== 'none'
              || parseFloat(cs.marginTop) < 0;
        }).map(e => e.textContent.slice(0, 20)),
    imgs_without_data: Array.from(document.querySelectorAll(
        '#reflection-content img, #explanation-content img, #notes-content img'))
        .filter(i => !i.src.startsWith('data:image/')).length,
  });
})()
"""

FORMAT_STATE = """
(() => {
  const c = document.querySelector('#explanation-content');
  const n = s => c.querySelectorAll(s).length;
  const a = c.querySelector('a');
  const img = c.querySelector('img');
  return JSON.stringify({
    h2: n('h2'), strong: n('strong'), em: n('em'), u: n('u'),
    ul_li: n('ul > li'), ol_li: n('ol > li'), blockquote: n('blockquote'),
    td: n('table td'), table_style: (c.querySelector('table') || {getAttribute: () => ''})
        .getAttribute('style') || '',
    href: a ? a.getAttribute('href') : null, rel: a ? a.getAttribute('rel') : null,
    target: a ? a.getAttribute('target') : null,
    katex: n('.math-tex .katex'), img_data: img ? img.src.startsWith('data:image/png') : false,
  });
})()
"""

#: Every style declaration the editor stored, and which of them the entry page
#: lost. Both sides are read through the CSS parser, so `border: 1px solid`
#: and its longhands compare equal. KaTeX's own output is not stored text.
#: An ``initial`` value is a shorthand resetting a longhand to its default
#: (``border`` resets ``border-image-*``); not copying it changes nothing.
LOST_STYLES = """
((stored) => {
  const decls = els => els.flatMap(e => Array.from(e.style)
      .filter(p => e.style.getPropertyValue(p) !== 'initial')
      .map(p => p + ': ' + e.style.getPropertyValue(p)));
  const want = decls(Array.from(new DOMParser().parseFromString(stored, 'text/html')
      .body.querySelectorAll('[style]')));
  const c = document.querySelector('#explanation-content');
  const have = new Set(decls(Array.from(c.querySelectorAll('[style]'))
      .filter(e => !e.closest('.katex'))));
  return JSON.stringify({want: want.length, lost: want.filter(d => !have.has(d))});
})(%s)
"""


def _seed(db, **fields) -> int:
    exam = db.create_exam_context(exam_name='Rich Exam', exam_description='#589')
    subject = db.create_subject_node(exam.exam_name, 'Cardiovascular', 'System')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='Rich session', date_encountered=date.today())
    entry = db.create_question_entry(session.id, 'a', 'b',
                                     primary_subject_ids=[subject.id], **fields)
    db.conn.commit()
    return entry.id, session.id


def _open_detail(page: WimiPage, entry_id: int) -> None:
    page.goto('entry-detail', query={'id': entry_id})
    assert poll(page, "!!document.querySelector('#explanation-content')"
                      " && document.querySelector('#explanation-content').childNodes.length > 0",
                timeout_ms=20000), 'the entry page never rendered its content'
    page.wait_for_timeout(400)   # an onerror / ontoggle fires asynchronously


@pytest.mark.slow
@pytest.mark.regression
def test_nothing_stored_runs_on_the_entry_page(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    entry_id, _ = _seed(wimi_session.user.db, **ATTACKS)
    _open_detail(wimi_page, entry_id)
    state = json.loads(wimi_page.eval_js(STATE))

    assert state['fired'] is None, f'stored HTML ran on the entry page: {state["fired"]}'
    assert state['dangerous'] == 0, state
    assert not state['styled_url'], 'a style reaching outside the page survived'
    assert state['imgs_without_data'] == 0, 'an image that fetches survived'
    assert state['escaped_out'] == [], (
        f'a stored style fetches, floats, hides or moves an element: {state["escaped_out"]}')
    # The words are kept: a filter that dropped everything would fail here.
    assert 'Keep this' in state['reflection'] and 'jslink' in state['reflection']
    assert 'breakout' in state['explanation'] and 'toggled' in state['explanation']
    assert 'styled' in state['explanation'] and 'escfull' in state['explanation']
    assert 'overlay' in state['explanation'] and 'lifted' in state['explanation']
    assert 'A note' in state['notes']


@pytest.mark.slow
@pytest.mark.regression
def test_formatting_written_by_the_editor_survives(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    _, session_id = _seed(db, reflection='<p>x</p>')

    # What the editor itself stores for this content.
    wimi_page.goto('entry-form', query={'session_id': session_id})
    wait_for_release(wimi_page)
    wait_for_form_ready(wimi_page)
    stored = wimi_page.eval_js(
        '(() => { const e = EntryState.explanationEditor; e.setContent(%s);'
        ' return e.getContent().html; })()' % json.dumps(FORMATTED))
    assert '<table' in stored and 'math-tex' in stored and 'data:image/png' in stored, (
        f'the editor did not keep the sample, so this would test nothing: {stored[:300]}')

    entry_id = db.create_question_entry(session_id, 'a', 'b', explanation=stored).id
    db.conn.commit()
    _open_detail(wimi_page, entry_id)
    f = json.loads(wimi_page.eval_js(FORMAT_STATE))

    assert f['h2'] == 1 and f['strong'] >= 1 and f['em'] >= 1 and f['u'] >= 1, f
    assert f['ul_li'] == 2 and f['ol_li'] == 2 and f['blockquote'] == 1, f
    assert f['td'] == 4 and 'border-collapse' in f['table_style'], f
    assert f['href'] == 'https://example.org/page', f
    assert f['rel'] == 'noopener noreferrer' and f['target'] == '_blank', f
    assert f['katex'] >= 1, 'the maths formula did not render'
    # The editor's own colour, alignment, list and table controls (#591): no
    # declaration it wrote is lost. A missing property flattens a student's
    # table silently, so this compares every one rather than a sample.
    styles = json.loads(wimi_page.eval_js(LOST_STYLES % json.dumps(stored)))
    assert styles['want'] >= 15, f'the sample carries too few styles to test: {styles}'
    assert styles['lost'] == [], f'stored formatting was dropped: {styles["lost"]}'
    assert f['img_data'], 'the pasted image was dropped'
