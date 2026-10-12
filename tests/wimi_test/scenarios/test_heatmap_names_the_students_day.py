"""Issue #471 - the activity heatmap named every square one day early west
of Greenwich.

``heatmap_chart.js`` built each square's tooltip with
``new Date(d.date).toLocaleDateString(...)``. ``d.date`` is a bare
``'YYYY-MM-DD'``, which ECMAScript parses as **UTC midnight**, and the
formatter then renders it in the **local** zone -- so in any negative offset
the label names the previous day. The same parse placed the month labels and
the Weekly Goal card's Recent History labels.

The payload is correct (#286: computed in Python, local on both sides). Only
the rendered name was wrong, so the oracle here is the payload's own string,
formatted *without* going through the local zone -- never a date written
into the test.

Why the zone is fixed rather than chosen by the hour
-----------------------------------------------------
The #286 technique picks Pago_Pago or Kiritimati from the current UTC hour so
that local and UTC *today* always differ. That is the right lever for a
"what is today" defect and the wrong one here: this is a parse of a
date-only string, which goes wrong in **every negative-offset zone at every
hour** and in **no positive-offset zone at any hour**. Under Kiritimati the
unfixed page is correct, so an hour-chosen zone would make this test a
tautology for half of every day. So:

* ``Pacific/Pago_Pago`` (UTC-11, DST-free) is the zone that can fail, and
  ``assert_naive_parse_is_wrong_here`` **fails hard** if, in the page, the
  naive parse does not actually name the previous day -- otherwise a broken
  override would silently turn the assertion into a tautology (#121).
* ``Pacific/Kiritimati`` (UTC+14) is run too, as the other side: the fix
  must not move a correct label in the zone where the old code was right.

The override is applied before the navigation that renders, because it
survives a ``goto`` and the page reads the zone when it draws.
"""
from __future__ import annotations

import pytest

from _helpers.w114_form_ready import poll
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

pytestmark = [pytest.mark.slow, pytest.mark.regression]

#: Formats a 'YYYY-MM-DD' exactly as the chart does, but pinned to UTC on
#: both ends, so the answer cannot depend on the zone under test.
ORACLE_JS = """
const nameOf = (s) => {
  const [y, m, d] = s.slice(0, 10).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US',
    {weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
};
"""

READ = ORACLE_JS + """
(() => {
  const cells = [...document.querySelectorAll('#activityHeatmap rect.heatmap-cell')];
  const wrong = [];
  for (const c of cells) {
    const date = c.getAttribute('data-testid').replace('analytics-heatmap-cell-', '');
    const title = c.querySelector('title').textContent;
    if (!title.endsWith(' on ' + nameOf(date))) wrong.push({date, title});
  }
  return {
    zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    cells: cells.length,
    wrong: wrong.slice(0, 5),
    wrongCount: wrong.length,
    sample: cells.length ? cells[cells.length - 1].querySelector('title').textContent : null,
    naiveShifts: new Date('2026-03-01').getDate() !== 1,
  };
})()
"""

#: Month labels, drawn by the real chart class into a scratch node from a
#: synthetic window. The live window is computed from the host's today, and a
#: month label only moves when a 1st-of-month is the last square of its
#: column -- which today's window may not contain -- so the window here is
#: built so that 2026-08-01 is exactly that square. The label must head the
#: column that square is in.
MONTHS = """
(() => {
  const host = document.createElement('div');
  host.id = 'w471MonthProbe';
  document.body.appendChild(host);
  const days = [];
  const start = Date.UTC(2026, 6, 26);           // 2026-07-26: Aug 1 is index 6
  for (let i = 0; i < 28; i++) {
    const t = new Date(start + i * 86400000);
    days.push({date: t.toISOString().slice(0, 10), count: 0, level: 0});
  }
  new ActivityHeatmap('w471MonthProbe', {cellSize: 12, cellGap: 3}).render({days});
  const out = [...host.querySelectorAll('.month-labels text')]
    .map(t => ({month: t.textContent, x: Number(t.getAttribute('x'))}));
  host.remove();
  return {aug1Index: days.findIndex(d => d.date === '2026-08-01'), labels: out};
})()
"""

#: The Weekly Goal card's Recent History labels, rendered by the real class
#: from a synthetic history. `_renderHistory` skips index 0 (this week).
GOAL_HISTORY = """
(() => {
  const host = document.createElement('div');
  host.id = 'w471GoalProbe';
  document.body.appendChild(host);
  const w = new GoalWidget('w471GoalProbe', {});
  w.goalHistory = ['2026-10-05', '2026-09-28', '2026-03-02'].map(d => (
    {week_start: d, target: 10, achieved: 5, completion_pct: 50, completed: false}));
  const html = w._renderHistory();
  host.remove();
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  return [...tmp.querySelectorAll('.history-date')].map(e => e.textContent);
})()
"""


def _seed(db) -> int:
    from datetime import date
    exam = db.create_exam_context(exam_name='W471 Exam', exam_description='')
    subject = db.create_subject_node(
        exam_context=exam.exam_name, name='W471 Topic', level_type='Topic',
        exam_weight_low=10, exam_weight_high=10,
    )
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=5, total_incorrect=1,
        session_name='W471', date_encountered=date.today(),
    )
    db.create_question_entry(
        review_session_id=session.id, user_answer='A', correct_answer='B',
        perceived_difficulty=3, reflection='r', explanation='e',
        primary_subject_ids=[subject.id],
    )
    db.conn.commit()
    return exam.id


def _open(session: WimiTestSession, page: WimiPage, zone: str) -> int:
    exam_id = _seed(session.user.db)
    page.goto('dashboard')
    page.tab._tab.Emulation.setTimezoneOverride(timezoneId=zone)
    page.goto('analytics', query={'exam': exam_id})
    assert poll(page, "document.querySelectorAll('#activityHeatmap rect.heatmap-cell').length > 100"), (
        'the activity heatmap never rendered'
    )
    return exam_id


@pytest.mark.parametrize('zone, west', [
    pytest.param('Pacific/Pago_Pago', True, id='west-UTC-11'),
    pytest.param('Pacific/Kiritimati', False, id='east-UTC+14'),
])
def test_each_square_is_named_for_its_own_day(
    wimi_session: WimiTestSession, wimi_page: WimiPage, zone: str, west: bool,
) -> None:
    _open(wimi_session, wimi_page, zone)

    got = wimi_page.eval_js(READ)

    assert got['zone'] == zone, f'the timezone override did not take: {got!r}'
    assert got['naiveShifts'] is west, (
        f'under {zone} the naive parse new Date("2026-03-01") '
        f'{"does not" if west else "does"} name another day, so this zone '
        f'cannot tell a fixed chart from a broken one. This is a failure of '
        f'the instrument, not of the application: {got!r}'
    )
    assert got['wrongCount'] == 0, (
        f'{got["wrongCount"]} of {got["cells"]} squares are named for a day '
        f'other than their own under {zone}, e.g. {got["wrong"]}. #471: '
        f'"YYYY-MM-DD" parsed as UTC midnight and formatted in local time.'
    )


def test_month_labels_head_the_column_their_month_starts_in(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    _open(wimi_session, wimi_page, 'Pacific/Pago_Pago')

    got = wimi_page.eval_js(MONTHS)

    assert got['aug1Index'] == 6, got   # the fixture's own precondition
    aug = [lab for lab in got['labels'] if lab['month'] == 'Aug']
    # Day labels take 30 px; Aug 1 is in column 0, so its label sits at 30.
    assert aug and aug[0]['x'] == 30, (
        f'under UTC-11 the "Aug" label is at {aug} where 2026-08-01 heads '
        f'column 0 (x=30): {got}. #471: 2026-08-01 parsed as UTC midnight is '
        f'still July locally, so August was found one square -- here one '
        f'column -- late.'
    )


def test_goal_history_labels_name_the_week_that_started(
    wimi_session: WimiTestSession, wimi_page: WimiPage,
) -> None:
    _open(wimi_session, wimi_page, 'Pacific/Pago_Pago')

    labels = wimi_page.eval_js(GOAL_HISTORY)

    assert labels == ['Sep 28', 'Mar 2'], (
        f'the Weekly Goal card\'s Recent History labels read {labels} under '
        f'UTC-11 for weeks starting 2026-09-28 and 2026-03-02. #471: the same '
        f'date-only parse names the Sunday before each Monday.'
    )
