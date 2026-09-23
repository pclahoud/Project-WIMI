"""Guard: the rich editor's table context menu acts on the table.

Forgejo issue #21 -- "Rich editor: the table right-click context menu
shows but its items do nothing":

    Right-clicking inside a table opens the context menu, but choosing
    any item performs no action.

The report predates the flat-layout rework and **did not reproduce** when
it was re-checked on ``373e060``: a real right-click inside a table opens
TinyMCE's menu, hovering ``Row`` opens the submenu, and ``Insert row
after`` adds a row (4 -> 5). The starting point in the report -- "a menu
whose items name commands from an unloaded plugin renders but is inert"
-- does not apply either: ``RichEditor`` loads the ``table`` plugin, and
the plugin ships both the menu items and the ``mceTableInsertRowAfter``
command that backs them.

So this file is a guard, not a reproduction. It drives the whole path the
user drives -- right-click, submenu, leaf item -- with real CDP mouse
events rather than ``execCommand``, because the reported failure was
specifically that the *menu* did nothing while the commands themselves
worked. It would go red if the table plugin were dropped from the plugin
list, if ``contextmenu`` were narrowed so the table entries disappeared,
or if the menu stopped routing its items to the editor.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

ROWS, COLS = 4, 4

READY_PROBE = (
    "(() => { const e = (typeof EntryState !== 'undefined') && EntryState.reflectionEditor;"
    " return JSON.stringify({ready: !!(e && e.isInitialized)}); })()"
)

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
  ed.getWin().scrollTo(0, 0);
  return JSON.stringify({rows: ed.getBody().querySelectorAll('tr').length});
})()
"""

# A cell's centre in page coordinates, so CDP can aim real mouse events
# at it through the editor's iframe.
CELL_POINT_JS = """
(() => {
  const re = EntryState.reflectionEditor, ed = re.editor;
  const fr = document.getElementById(re.editorId + '_ifr').getBoundingClientRect();
  const r = ed.getBody().querySelector('#%(cell)s').getBoundingClientRect();
  return JSON.stringify({x: fr.left + r.left + r.width / 2,
                         y: fr.top + r.top + r.height / 2});
})()
"""

# Menu items live in the host document (TinyMCE's aux sink), not in the
# editor iframe, so the scenario can measure and click them directly.
MENU_ITEM_JS = """
(() => {
  const items = Array.from(document.querySelectorAll('.tox-menu .tox-collection__item'));
  const hit = items.find(el => el.textContent.trim() === %(label)s);
  if (!hit) return JSON.stringify({found: false,
                                   seen: items.map(el => el.textContent.trim())});
  const r = hit.getBoundingClientRect();
  return JSON.stringify({found: true, x: r.left + r.width / 2, y: r.top + r.height / 2});
})()
"""

ROW_COUNT_JS = (
    "(() => { const ed = EntryState.reflectionEditor.editor;"
    " return JSON.stringify({rows: ed.getBody().querySelectorAll('tr').length}); })()"
)


def _poll(page: WimiPage, probe: str, done, *, timeout_ms: int = 15000) -> dict:
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


def _click(page: WimiPage, x: float, y: float, *, button: str = 'left') -> None:
    for phase in ('mousePressed', 'mouseReleased'):
        page.tab.Input.dispatchMouseEvent(
            type=phase, x=x, y=y, button=button,
            buttons=(2 if button == 'right' else 1), clickCount=1)


def _menu_item(page: WimiPage, label: str) -> dict:
    return _poll(page, MENU_ITEM_JS % {'label': json.dumps(label)},
                 lambda s: s.get('found'), timeout_ms=8000)


def _seed(db) -> tuple[int, int]:
    exam = db.create_exam_context(exam_name='Table Menu Exam', exam_description='')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=1,
        session_name='Table menu session', date_encountered=date.today(),
    )
    entry = db.create_question_entry(
        review_session_id=session.id, user_answer='a', correct_answer='b',
    )
    db.conn.commit()
    return session.id, entry.id


@pytest.mark.slow
@pytest.mark.regression
def test_table_context_menu_inserts_a_row(
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

    # ---- Act: click a cell, right-click it, walk Row > Insert row after
    point = json.loads(wimi_page.eval_js(CELL_POINT_JS % {'cell': 'c1_1'}))
    _click(wimi_page, point['x'], point['y'])
    wimi_page.wait_for_timeout(300)
    _click(wimi_page, point['x'], point['y'], button='right')

    row_entry = _menu_item(wimi_page, 'Row')
    assert row_entry.get('found'), (
        f'right-click gave no table entries in the context menu: {row_entry!r}'
    )
    _click(wimi_page, row_entry['x'], row_entry['y'])

    insert_after = _menu_item(wimi_page, 'Insert row after')
    assert insert_after.get('found'), (
        f'the Row submenu never offered "Insert row after": {insert_after!r}'
    )
    _click(wimi_page, insert_after['x'], insert_after['y'])

    # ---- Assert: the menu item mutated the table ----------------------
    # #21 said the menu opened and then did nothing. The only proof that
    # it did something is the table itself, so assert on the row count
    # rather than on the menu closing.
    final = _poll(wimi_page, ROW_COUNT_JS, lambda s: s.get('rows') == ROWS + 1)
    assert final.get('rows') == ROWS + 1, (
        f'"Insert row after" left the table at {final.get("rows")} rows; the '
        f'context menu item did not act on the table'
    )
