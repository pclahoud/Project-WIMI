"""Regression: the difficulty and time card's error-type picker, its per-type
rows and its Every entry scatter (#898 Wave 3).

Seeded by hand. Sixteen mistakes on one exam, fifteen of them timed, so the
median is 50 s; five error types, ``A`` and ``B`` in a group, ``C``, ``D``
and one named ``<b>x</b>`` at the top level. Every expected figure is read
from ``get_difficulty_time_quadrants`` with the same selection, so the test
asserts that the page draws what the method counted -- and the fixture makes
each figure it compares non-zero, so agreement cannot be agreement on zero.

What is asserted:

* **One type** gives "N of M" in each quadrant, and a real click on a
  quadrant lands the entry browser on exactly N (the link keeps the
  selection).
* **Three types, Match any** draws one row per picked type with the
  method's per-type counts; **Match all** collapses them to one number.
* **No error type** lands the browser on entries that carry no type.
* **The scatter**: one ``.dt-dot`` per drawn mistake (entries minus not
  placed); the coloured dots are exactly the matches; the ringed dots are
  exactly those with two or more picked types; a fifth pick turns every
  match one colour. **Control**: with nothing picked no dot is drawn in the
  non-matching grey, so the grey count under a selection is not a colour
  every dot always has.
* **A type named ``<b>x</b>``** reads as text, never as markup, in the
  picker, in the rows and in the hover box.
* **Only the newest request draws**: the first picker request is held back
  by a wrapped bridge call until after a second has drawn; when it lands it
  must not overwrite the second. The held call is checked to have resolved,
  so the test cannot pass by the slow response never arriving.

No positions are asserted (offscreen and native viewports differ, CLAUDE.md).
The hover is driven by dispatching ``mouseenter`` on the dot, which is what
the card listens for; what it checks is the box's text, not hit testing.

Fails on master ``49eced4``, where the toolbar slot is empty: the first wait
for ``[data-testid="analytics-difficulty-time-picker-button"]`` times out.

Markers / fixtures: ``@pytest.mark.slow``, ``@pytest.mark.regression``,
``wimi_session``, ``wimi_page``.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from _helpers.w114_form_ready import centre_of, poll, real_click
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

T = "analytics-difficulty-time"
CARD = f'[data-testid="{T}"]'
BUTTON = f'[data-testid="{T}-picker-button"]'
POPOVER = f'[data-testid="{T}-picker"]'
DRAWN = ("typeof dashboard !== 'undefined' && dashboard.isReady === true"
         " && !window.__w898_old_document"
         f" && !!document.querySelector('{BUTTON}')"
         f" && !!document.querySelector('{CARD}')"
         f" && !!document.querySelector('{CARD}').dataset.state")
BROWSER_SETTLED = (
    "typeof entryBrowser !== 'undefined' && entryBrowser.isPageReady"
    " && entryBrowser.totalEntries >= 0"
    " && document.getElementById('loadingState').style.display === 'none'")
QUADRANTS = ["hard_fast", "hard_slow", "easy_fast", "easy_slow"]
EVIL = "<b>x</b>"


def _seed(db, name: str) -> dict:
    exam = db.create_exam_context(exam_name=name, exam_description="#898 W3")
    subject = db.create_subject_node(exam.exam_name, f"{name} Subject", "System")
    session = db.create_review_session(
        exam_context_id=exam.id, total_questions=40, total_incorrect=40,
        session_name=f"{name} session", date_encountered=date.today())
    group = db.create_tag_group(exam.exam_name, f"{name} Group")
    tags = {
        "A": db.create_hierarchical_tag(exam.exam_name, f"{name} A", group.id).id,
        "B": db.create_hierarchical_tag(exam.exam_name, f"{name} B", group.id).id,
        "C": db.create_tag(exam.exam_name, f"{name} C").id,
        "D": db.create_tag(exam.exam_name, f"{name} D").id,
        "E": db.create_tag(exam.exam_name, EVIL).id,
    }
    rows = [
        (5, 20, "A"), (4, 30, "AB"),                    # hard and fast
        (4, 100, "B"), (5, 120, "ABC"), (4, 90, "C"),   # hard and slow
        (5, 900, "BE"),                                 # hard and slow
        (1, 10, "A"), (2, 25, ""), (2, 15, "D"),        # easy and fast
        (2, 40, "E"), (1, 45, "AB"),                    # easy and fast
        (1, 200, "AC"),                                 # easy and slow
        (3, 50, "A"), (3, 60, ""),                      # middle
        (None, 70, "A"), (4, None, ""),                 # not placed
    ]
    ids = []
    for i, (d, t, carried) in enumerate(rows):
        entry = db.create_question_entry(
            session.id, "A", "B", question_id=f"Q{i + 1}",
            perceived_difficulty=d, time_spent_seconds=t,
            reflection="r", explanation="e", primary_subject_ids=[subject.id],
            tag_ids=[tags[c] for c in carried])
        ids.append(entry.id)
    db.conn.commit()
    return {"exam": exam.id, "tags": tags, "entries": ids}


def _open(page: WimiPage, exam: int) -> None:
    page.eval_js("window.__w898_old_document = true")
    page.goto("analytics", query={"exam": exam})
    assert poll(page, DRAWN, timeout_ms=30000), "the card or its picker never drew"


def _expected(db, exam: int, tag_ids=(), untagged=False, match="any") -> dict:
    return db.get_difficulty_time_quadrants(
        exam, tag_ids=list(tag_ids), untagged=untagged, match=match)


def _pick(page: WimiPage, keys: list, mode: str) -> None:
    """Open the picker by a real click, tick ``keys`` by real clicks, Done."""
    real_click(page, centre_of(page, BUTTON))
    assert poll(page, f"!document.querySelector('{POPOVER}').hidden", timeout_ms=5000), \
        "the picker did not open"
    for key in keys:
        real_click(page, centre_of(page, f'[data-testid="{T}-picker-option-{key}"] input'))
    real_click(page, centre_of(page, f'[data-testid="{T}-picker-done"]'))
    assert poll(page, f"document.querySelector('{POPOVER}').hidden", timeout_ms=5000)
    _wait_selection(page, mode)


def _wait_selection(page: WimiPage, mode: str) -> None:
    assert poll(page, f"document.querySelector('{CARD}').dataset.selection === '{mode}'"
                      " && dashboard.difficultyTimeCard.debounceTimer === null",
                timeout_ms=10000), f"the card never drew the {mode} selection"


def _texts(page: WimiPage) -> dict:
    return json.loads(page.eval_js("""(() => {
        const card = document.querySelector('%s');
        const t = id => {
            const n = card.querySelector('[data-testid="%s-' + id + '"]');
            return n ? n.textContent.replace(/\\s+/g, ' ').trim() : null;
        };
        const out = {};
        ['hard_fast', 'hard_slow', 'easy_fast', 'easy_slow'].forEach(b => {
            out[b] = {
                count: t('count-' + b),
                rows: Array.from(card.querySelectorAll('[data-testid="%s-rows-' + b + '"] .dt-type'))
                    .map(li => li.children[0].textContent + '=' + li.children[1].textContent),
            };
        });
        out.middle = t('line-middle');
        out.accounting = t('accounting');
        out.bold = card.querySelectorAll('b').length;
        return JSON.stringify(out);
    })()""" % (CARD, T, T)))


@pytest.mark.slow
@pytest.mark.regression
def test_one_type_three_types_and_the_quadrant_link(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    ids = _seed(db, "W898P")
    a, b, e = ids["tags"]["A"], ids["tags"]["B"], ids["tags"]["E"]
    _open(wimi_page, ids["exam"])
    assert wimi_page.eval_js(
        f"document.querySelector('{BUTTON}').textContent.trim()") == "All error types"

    # The picker lists the type named <b>x</b> as text.
    real_click(wimi_page, centre_of(wimi_page, BUTTON))
    assert poll(wimi_page, f"!document.querySelector('{POPOVER}').hidden", timeout_ms=5000)
    picker = json.loads(wimi_page.eval_js(f"""(() => {{
        const pop = document.querySelector('{POPOVER}');
        const opt = pop.querySelector('[data-testid="{T}-picker-option-{e}"] .dt-picker-name');
        return JSON.stringify({{
            evil: opt ? opt.textContent : null,
            bold: pop.querySelectorAll('b').length,
            groups: Array.from(pop.querySelectorAll('.dt-picker-group-name')).map(n => n.textContent),
            untagged: pop.querySelector('[data-testid="{T}-picker-option-untagged"] .dt-picker-count').textContent,
            expanded: document.querySelector('{BUTTON}').getAttribute('aria-expanded'),
        }});
    }})()"""))
    assert picker["evil"] == EVIL and picker["bold"] == 0, picker
    assert picker["groups"] == ["W898P Group", "Other"], picker
    assert picker["untagged"] == "3" and picker["expanded"] == "true", picker
    # Escape closes it and gives focus back to the button.
    wimi_page.tab.Input.dispatchKeyEvent(type="keyDown", key="Escape", code="Escape",
                                         windowsVirtualKeyCode=27)
    wimi_page.tab.Input.dispatchKeyEvent(type="keyUp", key="Escape", code="Escape",
                                         windowsVirtualKeyCode=27)
    assert poll(wimi_page, f"document.querySelector('{POPOVER}').hidden"
                           f" && document.activeElement === document.querySelector('{BUTTON}')",
                timeout_ms=5000), "Escape did not close the picker onto its button"

    # One type: "N of M" in every quadrant.
    _pick(wimi_page, [a], "one")
    want = _expected(db, ids["exam"], [a])
    got = _texts(wimi_page)
    for q in QUADRANTS:
        s = want["buckets"][q]
        assert got[q]["count"].startswith(f"{s['match']['count']} of {s['count']}"), (q, got[q])
        assert got[q]["rows"] == [], (q, got[q])
    assert want["buckets"]["hard_slow"]["match"]["count"] > 0
    assert wimi_page.eval_js(
        f"document.querySelector('{BUTTON}').textContent.trim()") == "W898P A"

    # Three types, any: a row per type with the method's counts.
    _pick(wimi_page, [b, e], "any")
    want = _expected(db, ids["exam"], [a, b, e], match="any")
    got = _texts(wimi_page)
    names = {a: "W898P A", b: "W898P B", e: EVIL}
    for q in QUADRANTS:
        s = want["buckets"][q]
        assert got[q]["count"].startswith(f"{s['match']['count']} of {s['count']} carry any"), (q, got[q])
        assert got[q]["rows"] == [f"{names[p['tag_id']]}={p['count']}"
                                  for p in s["match"]["per_type"]], (q, got[q])
    assert got["bold"] == 0, "a type name was parsed as markup in the rows"
    assert "The coloured rows overlap" in got["accounting"], got["accounting"]
    assert got["middle"].startswith(
        f"Rated 3: {want['buckets']['middle']['match']['count']} mistake"), got["middle"]

    # Match all collapses the rows to one number.
    real_click(wimi_page, centre_of(wimi_page, f'[data-testid="{T}-match-all"]'))
    _wait_selection(wimi_page, "every")
    want = _expected(db, ids["exam"], [a, b, e], match="all")
    got = _texts(wimi_page)
    for q in QUADRANTS:
        s = want["buckets"][q]
        assert got[q]["count"].startswith(f"{s['match']['count']} of {s['count']} carry all"), (q, got[q])
        assert got[q]["rows"] == [], (q, got[q])

    # Back to one type; a quadrant click keeps the selection and lands on N.
    _pick(wimi_page, [b, e], "one")
    want = _expected(db, ids["exam"], [a])
    shown = want["buckets"]["hard_slow"]["match"]["count"]
    wimi_page.locator(css=f'{CARD} [data-testid="{T}-quadrant-hard_slow"]').click()
    assert poll(wimi_page, "location.pathname.endsWith('entry_browser.html')", timeout_ms=20000)
    assert poll(wimi_page, BROWSER_SETTLED, timeout_ms=20000)
    assert wimi_page.eval_js("entryBrowser.totalEntries") == shown


@pytest.mark.slow
@pytest.mark.regression
def test_no_error_type_lands_on_untagged_entries(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    ids = _seed(db, "W898U")
    _open(wimi_page, ids["exam"])
    _pick(wimi_page, ["untagged"], "untagged")
    want = _expected(db, ids["exam"], untagged=True)
    got = _texts(wimi_page)
    assert got["easy_fast"]["count"].startswith(
        f"{want['buckets']['easy_fast']['match']['count']} of "), got
    expected_ids = sorted(x["id"] for x in want["entries"]
                          if x["bucket"] == "easy_fast" and not x["tag_ids"])
    assert expected_ids, "the fixture has no untagged easy-and-fast mistake"

    wimi_page.locator(css=f'{CARD} [data-testid="{T}-quadrant-easy_fast"]').click()
    assert poll(wimi_page, "location.pathname.endsWith('entry_browser.html')", timeout_ms=20000)
    assert poll(wimi_page, BROWSER_SETTLED, timeout_ms=20000)
    assert "untagged=1" in wimi_page.eval_js("location.search")
    landed = json.loads(wimi_page.eval_js(
        "JSON.stringify(entryBrowser.entries.map(e => e.id).sort((a, b) => a - b))"))
    # Exactly the untagged easy-and-fast mistakes, none of which carries a type.
    assert landed == expected_ids, (landed, expected_ids)


SCATTER = """(() => {
    const svg = document.querySelector('[data-testid="%s-scatter"]');
    const dots = Array.from(svg.querySelectorAll('circle.dt-dot'));
    const fill = n => getComputedStyle(n).fill;
    const probe = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    probe.style.fill = 'var(--dt-dot-nonmatch)';
    svg.appendChild(probe);
    const grey = getComputedStyle(probe).fill;
    probe.remove();
    const matches = dots.filter(d => d.classList.contains('dt-dot--match'));
    return JSON.stringify({
        role: svg.getAttribute('role'),
        label: svg.getAttribute('aria-label'),
        dots: dots.length,
        grey: dots.filter(d => fill(d) === grey).length,
        nonmatch_r: Array.from(new Set(dots.filter(d => d.classList.contains('dt-dot--nonmatch'))
            .map(d => d.getAttribute('r')))),
        matches: matches.length,
        match_ids: matches.map(d => Number(d.dataset.entryId)).sort((a, b) => a - b),
        match_fills: Array.from(new Set(matches.map(fill))),
        rings: svg.querySelectorAll('circle.dt-dot-ring').length,
        ring_ids: Array.from(svg.querySelectorAll('circle.dt-dot-ring'))
            .map(d => Number(d.dataset.entryId)).sort((a, b) => a - b),
        median: !!svg.querySelector('.dt-median'),
        keyboard: (document.querySelector('[data-testid="%s-keyboard-note"]') || {}).textContent || '',
    });
})()""" % (T, T)


@pytest.mark.slow
@pytest.mark.regression
def test_the_scatter_draws_every_placed_mistake_and_colours_the_matches(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    ids = _seed(db, "W898S")
    t = ids["tags"]
    _open(wimi_page, ids["exam"])
    real_click(wimi_page, centre_of(wimi_page, f'[data-testid="{T}-tab-every"]'))
    assert poll(wimi_page, f"!document.querySelector('[data-testid=\"{T}-panel-every\"]').hidden"
                           f" && !!document.querySelector('[data-testid=\"{T}-scatter\"]')",
                timeout_ms=5000), "the Every entry tab did not open onto a scatter"

    want = _expected(db, ids["exam"])
    drawn = [x for x in want["entries"] if x["bucket"] != "not_placed"]
    got = json.loads(wimi_page.eval_js(SCATTER))
    assert got["role"] == "img" and "Scatter plot of 14 mistakes" in got["label"], got
    assert "Quadrants tab" in got["keyboard"], got
    assert got["dots"] == len(drawn) == 14, got
    assert got["median"], got
    # Control: on All no dot is the non-matching grey.
    assert got["grey"] == 0 and got["matches"] == 0, got

    _pick(wimi_page, [t["A"], t["B"], t["C"]], "any")
    want = _expected(db, ids["exam"], [t["A"], t["B"], t["C"]], match="any")
    drawn = [x for x in want["entries"] if x["bucket"] != "not_placed"]
    got = json.loads(wimi_page.eval_js(SCATTER))
    assert got["dots"] == len(drawn), got
    assert got["match_ids"] == sorted(x["id"] for x in drawn if x["matches"]), got
    assert got["grey"] == len(drawn) - got["matches"] > 0, got
    assert got["nonmatch_r"] == ["3"], got
    ringed = sorted(x["id"] for x in drawn if len(x["picked_hits"]) >= 2)
    assert ringed and got["ring_ids"] == ringed, got
    assert len(got["match_fills"]) == 3, got

    # The hover box reads a type named <b>x</b> as text.
    evil_entry = next(x["id"] for x in drawn if t["E"] in x["tag_ids"])
    hover = json.loads(wimi_page.eval_js(f"""(() => {{
        const dot = document.querySelector('circle.dt-dot[data-entry-id="{evil_entry}"]');
        dot.dispatchEvent(new MouseEvent('mouseenter'));
        const box = document.querySelector('[data-testid="{T}-scatter-hover"]');
        return JSON.stringify({{hidden: box.hidden, text: box.innerText, bold: box.querySelectorAll('b').length}});
    }})()"""))
    assert not hover["hidden"] and EVIL in hover["text"] and hover["bold"] == 0, hover
    assert "W898S session, question Q6" in hover["text"], hover
    assert "Very Hard" in hover["text"] or "rated 5" in hover["text"], hover
    assert "15 min" in hover["text"], hover

    # A fifth pick: every match turns one colour.
    _pick(wimi_page, [t["D"], t["E"]], "any")
    got = json.loads(wimi_page.eval_js(SCATTER))
    assert got["matches"] > 3 and len(got["match_fills"]) == 1, got

    # A click on a dot opens the entry, with no stale prev/next list.
    wimi_page.eval_js("sessionStorage.setItem('entryNavContext', '{}')")
    target = ids["entries"][0]
    wimi_page.eval_js(f"document.querySelector('circle.dt-dot[data-entry-id=\"{target}\"]')"
                      ".dispatchEvent(new MouseEvent('click', {bubbles: true}))")
    assert poll(wimi_page, "location.pathname.endsWith('entry_detail.html')", timeout_ms=20000)
    assert f"id={target}" in wimi_page.eval_js("location.search")
    assert wimi_page.eval_js("sessionStorage.getItem('entryNavContext')") is None


@pytest.mark.slow
@pytest.mark.regression
def test_only_the_newest_request_draws(
    wimi_session: WimiTestSession, wimi_page: WimiPage
) -> None:
    db = wimi_session.user.db
    ids = _seed(db, "W898N")
    a, b = ids["tags"]["A"], ids["tags"]["B"]
    _open(wimi_page, ids["exam"])
    # Hold back the first request that picks A alone, until well after the
    # next one has drawn.
    wimi_page.eval_js(f"""(() => {{
        const real = window.api.getDifficultyTimeQuadrants;
        window.__w898_slow = 'none';
        window.api.getDifficultyTimeQuadrants = async function (params) {{
            const ids = params.tagIds || [];
            if (ids.length === 1 && ids[0] === {a} && window.__w898_slow === 'none') {{
                window.__w898_slow = 'held';
                const result = await real.call(this, params);
                await new Promise(r => setTimeout(r, 2500));
                window.__w898_slow = 'resolved';
                return result;
            }}
            return real.call(this, params);
        }};
    }})()""")
    real_click(wimi_page, centre_of(wimi_page, BUTTON))
    real_click(wimi_page, centre_of(wimi_page, f'[data-testid="{T}-picker-option-{a}"] input'))
    assert poll(wimi_page, "window.__w898_slow === 'held'", timeout_ms=5000), \
        "the first request never went out"
    real_click(wimi_page, centre_of(wimi_page, f'[data-testid="{T}-picker-option-{b}"] input'))
    _wait_selection(wimi_page, "any")
    assert poll(wimi_page, "window.__w898_slow === 'resolved'", timeout_ms=10000), \
        "the held request never resolved, so nothing was tested"
    wimi_page.wait_for_timeout(300)
    want = _expected(db, ids["exam"], [a, b], match="any")
    got = _texts(wimi_page)
    assert wimi_page.eval_js(f"document.querySelector('{CARD}').dataset.selection") == "any"
    for q in QUADRANTS:
        s = want["buckets"][q]
        assert got[q]["count"].startswith(f"{s['match']['count']} of {s['count']} carry any"), (q, got[q])
