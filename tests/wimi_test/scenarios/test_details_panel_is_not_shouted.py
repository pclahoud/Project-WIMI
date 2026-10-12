"""Nothing in the tree editor's details panel is painted in capitals (#346).

The owner's decision, 2026-10-10: the panel's ALL-CAPS runs go, and the
source strings are cased so that what is painted is what is written.

**This has to be a rendered test, and that is the whole reason the file
exists.** Three of the fifteen uppercased nodes could not be found by
reading CSS classes:

* ``CURRENT WEIGHT``, ``SIBLING WEIGHT DISTRIBUTION`` and ``RECENT CHANGES``
  are bare ``<label>`` elements. Their rules are ``.weight-current-header
  label`` and friends — parent-plus-element selectors, so a grep for a class
  returns nothing and #346's own inventory missed them.
* ``.parents-count-badge`` carries no ``text-transform`` of its own. It is a
  ``<span>`` inside the ``<h3 class="details-section-title">``, so it
  **inherits** one, and uppercases a digit. No static reader resolves that.
* The whole weight editor renders *into* this panel, despite every class on
  it being named ``weight-modal-*``. ``#weight-editor-container`` sits inside
  a ``.details-section``, so ``weight.css`` paints panel text. #346's
  inventory read ``tree.css`` and reported six runs where there are fifteen.

So the instrument is ``getComputedStyle``, over every visible element in the
panel, and the test is self-counting: it reports what it read.

**The positive controls are not decoration.** An assertion that nothing is
uppercase passes against a panel that never rendered, which is #121's
lesson. So this asserts the panel drew its header, its sections and a
multi-parent subject's parent rows *before* concluding anything from an
absence — and it asserts a lower bound on how many text nodes it inspected,
so a selector that stops matching cannot pass by inspecting nothing.

Verified able to fail: putting ``text-transform: uppercase`` back on
``.details-section-title`` alone reports 6 shouted nodes (five headings plus
the inherited count badge), which is also the control for the inheritance
claim above.

Loader quirk note
-----------------

Probes use ``window.api`` (NOT ``window._wimiApi``) because ``_loader.js``
aliases ``window._wimiApi`` -> ``window.api`` then deletes the source handle.
``TreeState`` is a top-level ``const``, so it is reachable as a bare name
from ``eval_js`` and is ``undefined`` as ``window.TreeState``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# A subject with THREE parents, because that is what puts both meta-line
# variants on screen at once -- one primary row and two others. Built here
# rather than taken from `exam_outline`, so the test does not depend on which
# topics that fixture happens to cross-list, and so the tree renders 4 rows
# instead of 2,471.
MULTI_PARENT_SUBJECT = "atrial fibrillation"
PARENT_NAMES = (
    "Disorders of rhythm and conduction",
    "Disorders of fluid and electrolytes",
    "Disorders of the adrenal gland",
)
EXPECTED_PARENT_ROWS = len(PARENT_NAMES)


def _seed_a_subject_with_three_parents(db):
    """One child under three roots, the first of them primary."""
    db._ensure_phase2_schema()
    exam = db.create_exam_context(
        exam_name="Details panel 346",
        exam_description="#346 - a multi-parent subject for the copy pass",
    )
    parents = [
        db.create_subject_node_with_weight(
            exam_context=exam.exam_name,
            name=name,
            level_type="System",
            exam_weight_low=5,
            exam_weight_high=10,
            weight_source="user_defined",
        )
        for name in PARENT_NAMES
    ]
    child = db.create_subject_node_with_weight(
        exam_context=exam.exam_name,
        name=MULTI_PARENT_SUBJECT,
        level_type="Topic",
        parent_id=parents[0].id,
        relative_weight=5,
        weight_source="user_defined",
    )
    for parent in parents[1:]:
        db.add_edge(parent.id, child.id, is_primary=False)
    return exam, child

# Measured on master c34fb77 before the fix: 15 uppercased nodes over 14
# distinct strings. The panel has far more text than that, so a floor well
# below the real figure still catches a probe that matched nothing.
MIN_TEXT_NODES_INSPECTED = 40


def _poll(wimi_page: WimiPage, read, predicate, *, timeout_ms: int = 20000):
    elapsed, last = 0, None
    while elapsed < timeout_ms:
        try:
            last = read()
        except Exception:
            last = None
        if predicate(last):
            return last
        wimi_page.wait_for_timeout(100)
        elapsed += 100
    return last


@pytest.mark.slow
@pytest.mark.regression
def test_no_text_in_the_details_panel_is_painted_in_capitals(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    exam, child = _seed_a_subject_with_three_parents(wimi_session.user.db)
    wimi_page.goto("tree-editor", query={"exam_id": exam.id})

    # ---- Positive control 1: the tree drew, so there is something to select.
    rows = _poll(
        wimi_page,
        lambda: wimi_page.eval_js("document.querySelectorAll('.tree-node').length"),
        lambda n: isinstance(n, int) and n > 0,
    )
    assert rows and rows > 0, "the tree editor drew no rows"
    wimi_page.eval_js(
        "document.querySelector('[data-testid=\"tree-expand-all\"]').click()")

    wimi_page.eval_js(f"selectNode({child.id})")

    # ---- Positive control 2: wait for the PANEL CONTENT, not its existence.
    # The weight editor keeps the previous subject's markup on screen while
    # the next one loads, so polling for `.weight-modal-context-header` to
    # exist reads the subject before this one -- #672's two-elements-two-
    # schedules shape. Both the title and the weight header have to name the
    # subject under test before anything is measured.
    settled = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            "(() => { const t = document.querySelector('.details-title');"
            " const w = document.querySelector('#weight-modal-child-name');"
            " return {t: t && t.textContent.trim(), w: w && w.textContent.trim()}; })()"
        ),
        lambda d: isinstance(d, dict)
        and d.get("t") == MULTI_PARENT_SUBJECT
        and d.get("w") == MULTI_PARENT_SUBJECT,
    )
    assert settled == {"t": MULTI_PARENT_SUBJECT, "w": MULTI_PARENT_SUBJECT}, (
        f"the panel never settled on {MULTI_PARENT_SUBJECT!r}: {settled!r}")

    # ---- Positive control 3: the parent rows drew, so the meta lines that
    # decision 2 rewrote are actually on screen and in scope of the sweep.
    parent_rows = wimi_page.eval_js(
        "document.querySelectorAll('.parent-row').length")
    assert parent_rows == EXPECTED_PARENT_ROWS, (
        f"expected {EXPECTED_PARENT_ROWS} parent rows for "
        f"{MULTI_PARENT_SUBJECT!r}, drew {parent_rows}")

    report = wimi_page.eval_js(
        """
        (() => {
          const panel = document.getElementById('details-content');
          const shouted = [];
          let inspected = 0;
          panel.querySelectorAll('*').forEach(el => {
            if (el.getClientRects().length === 0) return;
            const own = Array.from(el.childNodes)
              .filter(n => n.nodeType === 3 && n.textContent.trim())
              .map(n => n.textContent.trim()).join(' ');
            if (!own) return;
            inspected += 1;
            if (getComputedStyle(el).textTransform === 'uppercase') {
              shouted.push({cls: el.className || '(' + el.tagName.toLowerCase() + ')',
                            text: own});
            }
          });
          return {inspected, shouted};
        })()
        """
    )

    # ---- Positive control 4: the sweep read the panel rather than nothing.
    assert report["inspected"] >= MIN_TEXT_NODES_INSPECTED, (
        f"the sweep inspected only {report['inspected']} text-bearing nodes; "
        f"it is matching the wrong thing, so its empty result means nothing")

    assert report["shouted"] == [], (
        f"{len(report['shouted'])} node(s) in the details panel are still "
        f"painted in capitals: {report['shouted']!r}")


@pytest.mark.slow
@pytest.mark.regression
def test_the_weight_header_reads_as_one_sentence(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """"Weight for X under Y" is a sentence, and the caps hid that (#346).

    Four spans in a baseline-aligned flex row. Uppercasing the two
    connectives painted ``WEIGHT FOR hyperkalemia UNDER Disorders of rhythm
    and conduction`` -- the joining words shouting over the names they join.

    This also pins the sizing half: at ``--font-size-xs`` the connectives sat
    3px off the names' baseline, so the row carried three distinct baselines
    for two visual lines. Chapter 11 describes this header as "the subject's
    name, the word \\"under\\", and the parent", which is only literally true
    once the word is painted as the word.
    """
    exam, child = _seed_a_subject_with_three_parents(wimi_session.user.db)
    wimi_page.goto("tree-editor", query={"exam_id": exam.id})
    _poll(
        wimi_page,
        lambda: wimi_page.eval_js("document.querySelectorAll('.tree-node').length"),
        lambda n: isinstance(n, int) and n > 0,
    )
    wimi_page.eval_js(f"selectNode({child.id})")

    header = _poll(
        wimi_page,
        lambda: wimi_page.eval_js(
            """
            (() => {
              const h = document.querySelector('.weight-modal-context-header');
              const n = document.querySelector('#weight-modal-child-name');
              if (!h || !n) return null;
              const kids = Array.from(h.children);
              return {
                child: n.textContent.trim(),
                line: h.innerText.replace(/\\s+/g, ' ').trim(),
                sizes: [...new Set(kids.map(e => getComputedStyle(e).fontSize))],
                baselines: [...new Set(kids.map(
                  e => Math.round(e.getBoundingClientRect().top)))].length,
              };
            })()
            """
        ),
        lambda d: isinstance(d, dict) and d.get("child") == MULTI_PARENT_SUBJECT,
    )
    assert header and header["child"] == MULTI_PARENT_SUBJECT, (
        f"the weight header never settled on {MULTI_PARENT_SUBJECT!r}: {header!r}")

    # The connectives are written lower case and must be painted that way.
    assert " under " in header["line"], (
        f"the header does not read as a sentence: {header['line']!r}")
    assert "UNDER" not in header["line"], (
        f"the header is still shouting its connectives: {header['line']!r}")
    assert header["line"].startswith("Weight for "), (
        f"the header does not open with the sentence: {header['line']!r}")

    # One type size across the whole line is what makes it one sentence
    # rather than a label-and-value pair, and it is what puts every fragment
    # on a shared baseline grid.
    assert len(header["sizes"]) == 1, (
        f"the sentence is set in {len(header['sizes'])} sizes {header['sizes']!r}; "
        f"the connectives should match the names they join")
