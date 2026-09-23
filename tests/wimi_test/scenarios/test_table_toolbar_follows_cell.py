"""Regression: the rich editor's table toolbar stays next to the selected cell.

Forgejo issue #20 -- "Rich editor: the table cell toolbar is stuck at the
bottom-left for large tables (over ~5x5)":

    For tables larger than roughly 5 by 5, the cell toolbar appears at
    the bottom-left of the editor and is only visible once the user has
    scrolled to the bottom of the table.

Root cause: TinyMCE's ``table`` plugin registers its cell toolbar as a
context toolbar anchored to the ``<table>`` element
(``scope: 'node', position: 'node'``). While the whole table fits inside
the editor's visible area the positioner puts the toolbar just above or
below the table and everything looks right. Once the table is taller
than that area neither the table's top nor its bottom edge is on screen,
so the positioner falls back to an *inset* placement measured against the
editor's own bounds -- the toolbar is pinned to the far edge of the
editor instead of to the cell the caret is in.

Measured on ``373e060`` with a 20x6 table in the reflection editor
(iframe 371 px tall, table 821 px): with the caret in a cell at viewport
267.5-308.5 the toolbar rendered at 564-612, i.e. ``tox-pop--inset
tox-pop--bottom`` at the bottom edge of the editor, ~256 px below the
cell. The fix empties ``table_toolbar`` (which stops the plugin
registering) and re-registers the same items with
``position: 'selection'`` in ``RichEditor``'s ``setup`` callback, so the
anchor is the caret and the toolbar cannot be placed away from it.

The assertion is the vertical gap between the toolbar and the selected
cell, plus a check that the toolbar stays inside the editor: both are
what "appears next to the selected cell" means in geometry.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

ROWS, COLS = 20, 6

# The reflection editor, once TinyMCE has finished initialising it.
READY_PROBE = (
    "(() => { const e = (typeof EntryState !== 'undefined') && EntryState.reflectionEditor;"
    " return JSON.stringify({ready: !!(e && e.isInitialized)}); })()"
)

# Fill the editor with a table taller than its visible area, then scroll
# the editor's own document so the table's top edge is off screen -- the
# state in which the plugin's table-anchored toolbar loses the cell.
BUILD_JS = """
(() => {
  const re = EntryState.reflectionEditor, ed = re.editor;
  let html = '<table border="1" style="border-collapse:collapse;width:100%%"><tbody>';
  for (let r = 0; r < %(rows)d; r++) {
    html += '<tr>';
    for (let c = 0; c < %(cols)d; c++) html += '<td id="c' + r + '_' + c + '">r' + r + '</td>';
    html += '</tr>';
  }
  ed.setContent('<p>lead</p>' + html + '</tbody></table><p>tail</p>');
  document.getElementById(re.editorId + '_ifr').scrollIntoView({block: 'center'});
  ed.getWin().scrollTo(0, Math.round(ed.getDoc().documentElement.scrollHeight / 2));
  return JSON.stringify({rows: ed.getBody().querySelectorAll('tr').length});
})()
"""

# The topmost cell of column 0 that is wholly inside the editor's visible
# area, in *page* coordinates so CDP can click it for real.
TARGET_CELL_JS = """
(() => {
  const re = EntryState.reflectionEditor, ed = re.editor;
  const fr = document.getElementById(re.editorId + '_ifr').getBoundingClientRect();
  const cells = Array.from(ed.getBody().querySelectorAll('tr > td:first-child'));
  const hit = cells.find(td => {
    const r = td.getBoundingClientRect();
    return r.top >= 4 && r.bottom <= fr.height - 4;
  });
  if (!hit) return JSON.stringify({found: false});
  const r = hit.getBoundingClientRect();
  return JSON.stringify({found: true, id: hit.id,
                         x: fr.left + r.left + 8, y: fr.top + r.top + 8});
})()
"""

# Toolbar geometry against the selected cell and the editor frame, all in
# page coordinates. ``.tox-pop`` is the context-toolbar popup; it lives in
# the *host* document, so the scenario can measure it directly.
GEOMETRY_JS = """
(() => {
  const re = EntryState.reflectionEditor, ed = re.editor;
  const fr = document.getElementById(re.editorId + '_ifr').getBoundingClientRect();
  const cell = ed.getBody().querySelector('#%(cell)s').getBoundingClientRect();
  const pop = document.querySelector('.tox-pop');
  if (!pop) return JSON.stringify({shown: false});
  const p = pop.getBoundingClientRect();
  if (p.height === 0) return JSON.stringify({shown: false});
  return JSON.stringify({
    shown: true, cls: pop.className,
    buttons: pop.querySelectorAll('button').length,
    gap: Math.max(0, p.top - (fr.top + cell.bottom), (fr.top + cell.top) - p.bottom),
    popTop: p.top, popBottom: p.bottom,
    frameTop: fr.top, frameBottom: fr.bottom,
  });
})()
"""


def _poll(page: WimiPage, probe: str, done, *, timeout_ms: int = 20000) -> dict:
    elapsed, last = 0, {}
    while elapsed < timeout_ms:
        try:
            last = json.loads(page.eval_js(probe))
        except Exception:  # document torn down mid-navigation
            last = {}
        if done(last):
            return last
        page.wait_for_timeout(100)
        elapsed += 100
    return last


def _click(page: WimiPage, x: float, y: float) -> None:
    """A real mouse click. Synthetic DOM events skip TinyMCE's own
    selection bookkeeping, which is what decides where the toolbar goes."""
    for phase in ('mousePressed', 'mouseReleased'):
        page.tab.Input.dispatchMouseEvent(
            type=phase, x=x, y=y, button='left', buttons=1, clickCount=1)


def _seed(db) -> tuple[int, int]:
    exam = db.create_exam_context(exam_name='Table Toolbar Exam', exam_description='')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=1,
        session_name='Table toolbar session', date_encountered=date.today(),
    )
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer='a', correct_answer='b',
    )
    db.conn.commit()
    return session.id, entry.id


@pytest.mark.slow
@pytest.mark.regression
def test_table_toolbar_appears_next_to_the_selected_cell(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    # ---- Arrange -----------------------------------------------------
    session_id, entry_id = _seed(wimi_session.user.db)
    wimi_page.goto('entry-form', query={'session_id': session_id, 'entry': entry_id})
    assert _poll(wimi_page, READY_PROBE, lambda s: s.get('ready')).get('ready'), (
        'the reflection editor never finished TinyMCE init'
    )

    built = json.loads(wimi_page.eval_js(BUILD_JS % {'rows': ROWS, 'cols': COLS}))
    assert built.get('rows') == ROWS, f'table was not built: {built!r}'
    wimi_page.wait_for_timeout(300)

    # ---- Act ---------------------------------------------------------
    target = json.loads(wimi_page.eval_js(TARGET_CELL_JS))
    assert target.get('found'), (
        f'no cell of the {ROWS}x{COLS} table was fully visible to click: {target!r}'
    )
    _click(wimi_page, target['x'], target['y'])
    geometry = _poll(wimi_page, GEOMETRY_JS % {'cell': target['id']},
                     lambda s: s.get('shown'))

    # ---- Assert ------------------------------------------------------
    assert geometry.get('shown'), (
        f'no table context toolbar appeared for cell {target["id"]}: {geometry!r}'
    )
    assert geometry['buttons'] >= 8, (
        f'the table toolbar lost its buttons: {geometry!r}'
    )
    # #20: the toolbar was pinned to the editor's bottom edge, ~256 px
    # from the cell, because it anchored to the whole <table>. Anchored
    # to the selection it sits directly above or below the cell, so the
    # gap is 0; 60 px leaves room for the popup's own arrow and margin.
    assert geometry['gap'] <= 60, (
        f'the table toolbar is {geometry["gap"]:.0f} px away from the selected '
        f'cell instead of next to it -- it anchored to the table, not the '
        f'caret: {geometry!r}'
    )
    # ...and "at least stays within view": inside the editor's frame.
    assert geometry['popTop'] >= geometry['frameTop'] - 8, (
        f'the table toolbar sits above the editor: {geometry!r}'
    )
    assert geometry['popBottom'] <= geometry['frameBottom'] + 8, (
        f'the table toolbar sits below the editor: {geometry!r}'
    )
