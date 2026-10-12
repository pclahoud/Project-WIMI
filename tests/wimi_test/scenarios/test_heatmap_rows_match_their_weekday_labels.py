"""Issue #529 - the heatmap row labelled "Mon" must hold Mondays.

``heatmap_chart.js`` draws day ``i`` of the payload at row ``i % 7`` and
writes the labels Mon / Wed / Fri beside rows 1 / 3 / 5. The backend began
the payload on a Monday, so every label sat beside the next day's row:
the "Mon" row held Tuesdays, every day, for every student.

This reads the rendered page only: which row each label sits beside (from
its ``y``), which row each square sits in (from its ``y``), and each
square's own date from its ``data-testid``. The weekday of that date is
computed in UTC on both ends, so the oracle cannot depend on the zone the
page runs in or on the date the suite runs on -- the assertion is the same
on every day of the week.
"""
from __future__ import annotations

from datetime import date

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

READ = """
(() => {
  const root = document.querySelector('#activityHeatmap');
  const cells = [...root.querySelectorAll('rect.heatmap-cell')];
  const step = cells.length > 1
    ? Math.min(...cells.map(c => Number(c.getAttribute('y'))).filter(y => y > 0))
    : 0;
  const rowOfCell = c => Math.round(Number(c.getAttribute('y')) / step);
  const weekdayOf = s => {
    const [y, m, d] = s.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d)).getUTCDay();   // Sunday = 0
  };
  const names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const rows = {};
  for (const c of cells) {
    const date = c.getAttribute('data-testid').replace('analytics-heatmap-cell-', '');
    (rows[rowOfCell(c)] ||= new Set()).add(names[weekdayOf(date)]);
  }
  // The labels are positioned in the svg's own frame; the cells inside a
  // translated <g>. Compare each label's row by its index in the label set
  // the chart draws (data-testid analytics-heatmap-day-<row>) AND by its text.
  const labels = [...root.querySelectorAll('.day-labels text')].map(t => ({
    row: Number(t.getAttribute('data-testid').replace('analytics-heatmap-day-', '')),
    text: t.textContent,
  }));
  return {
    cells: cells.length,
    step,
    labels,
    rows: Object.fromEntries(Object.entries(rows).map(([r, s]) => [r, [...s]])),
    first: cells.length ? cells[0].getAttribute('data-testid') : null,
  };
})()
"""


def _seed(db) -> int:
    exam = db.create_exam_context(exam_name='W529 Exam', exam_description='')
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=1, total_incorrect=1,
        session_name='W529', date_encountered=date.today(),
    )
    db.create_question_entry(
        review_session_id=session.id, user_answer='A', correct_answer='B',
    )
    db.conn.commit()
    return exam.id


def test_each_labelled_row_holds_the_weekday_it_names(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    exam_id = _seed(wimi_session.user.db)
    wimi_page.goto('analytics', query={'exam': exam_id})
    assert poll(
        wimi_page,
        "document.querySelectorAll('#activityHeatmap rect.heatmap-cell').length > 100",
    ), 'the activity heatmap never rendered'

    got = wimi_page.eval_js(READ)

    # Positive controls: the chart drew a full grid and its three labels, so
    # an empty read cannot pass the assertion below.
    assert got['step'] > 0 and len(got['rows']) == 7, got
    assert [(lab['row'], lab['text']) for lab in got['labels']] == [
        (1, 'Mon'), (3, 'Wed'), (5, 'Fri'),
    ], got['labels']

    for lab in got['labels']:
        held = got['rows'][str(lab['row'])]
        assert held == [lab['text']], (
            f'the row labelled "{lab["text"]}" holds {held}; every square in '
            f'it should be a {lab["text"]}. First square: {got["first"]}. '
            f'#529: the payload started on a Monday while the chart assumes '
            f'Sunday, so each label sat one row off.'
        )
    # And row 0, which the chart leaves unlabelled, is Sunday.
    assert got['rows']['0'] == ['Sun'], got['rows']
