"""Regression: subject-search dropdown hides the alias-match indicator.

Bug source: ``docs/bugs/bugs.md`` (first entry,
``# Bug Report: UI Overflow in Subject Hierarchy``).

Reproduced verbatim from ``bugs.md`` lines 1-19:

    When a subject has a long hierarchical path (e.g.
    ``Male & Transgender Reproductive System > Neoplasms >
    penile malignant neoplasms > Carcinoma of the penis``), the text
    container does not expand to accommodate the full length.
    Consequently, the alias match text (e.g. ``(matched: Penile cancer)``)
    is pushed outside the visible container and becomes invisible to the
    user.

The expected behaviour, per the report, is that the alias-match text
remains visible — either by container expansion, ellipsis truncation of
the path, or both. This regression test asserts the *visibility* leg of
that contract: regardless of how a fix renders the path, the
``.alias-match`` span inside the matching ``.subject-option`` row must be
within the dropdown's clipping rectangle when the user types an alias
query.

How the bug manifests in the DOM
--------------------------------

The dropdown row markup (rendered in
``src/web/js/question_entry.js`` around line 528) is::

    <div class="subject-option" ...>
      <div class="subject-option-content">
        <div class="subject-option-name">{name}</div>
        <div class="subject-option-path">{full path}<span class="alias-match">
          <span class="alias-label">matched:</span> {aliasName}
        </span></div>
      </div>
    </div>

The bug is a CSS overflow / clipping issue: ``.subject-option-path`` is
single-line and doesn't wrap, so when ``{full path}`` is long, the
``.alias-match`` span falls past the right edge of the visible
``.subject-option`` row. ``getBoundingClientRect`` on the alias span
returns coordinates outside the parent's clip rect, which is what this
test asserts against (and against, once a fix lands).

How this test verifies a fix
----------------------------

1. Seed a deep subject hierarchy whose leaf has an alias that doesn't
   share words with the leaf name (so fuzzy search will hit via the
   alias rather than the name).
2. Open the entry form, type the alias text into the primary subject
   search box, and wait for the dropdown to render a row with class
   ``alias-match``.
3. Use ``eval_js`` to compute, for that row, whether the alias span's
   right edge is within the row's right edge (and whether the alias
   span has non-zero rendered width).

A fix for the bug (CSS wrap, ellipsis on the path, container expansion,
or any combination) makes this assertion pass; the current
implementation fails it for long paths.

Markers / fixtures
------------------

* ``@pytest.mark.slow`` — spawns a real WIMI subprocess.
* ``@pytest.mark.regression`` — registered in ``pytest.ini`` so
  collection emits no warning. Reserved for bug-report regression
  scenarios.
* Fixtures: ``wimi_session``, ``wimi_page``, ``test_user`` (we seed
  manually because no named seeder produces a deep alias-bearing
  hierarchy yet — when one is added, swap to ``seeded_user``).
"""

from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


# Long-path leaf and its alias, copied from the bug report so the
# scenario is faithful to the reproducer. The alias is the search query
# the user would type (``"Penile cancer"``) — that's how we trigger the
# alias-match branch of the dropdown render.
_DEEP_PATH_LEAF: str = "Carcinoma of the penis"
_LEAF_ALIAS: str = "Penile cancer"


@pytest.mark.slow
@pytest.mark.regression
def test_alias_match_visible_in_subject_dropdown(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The ``(matched: ...)`` indicator must be inside the row's clip rect.

    Arrange
    -------
    Seed a 4-level subject hierarchy ending in a leaf with an alias.
    Hierarchy depth and alias content are taken verbatim from
    ``bugs.md`` so the reproducer matches what the user reported.

    Act
    ---
    Navigate to the entry form, type the alias text into the primary
    subject search input, and wait for the dropdown row with
    ``.alias-match`` to appear.

    Assert
    ------
    For the alias-bearing row, the alias span's bounding rect right edge
    must be ``<=`` the row's right edge (i.e. not clipped off the visible
    width). Width must also be non-zero — a zero-width span has no
    visible glyphs even if its left edge is in-bounds.
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()

    exam_name = "Bug Repro Exam"
    db.create_exam_context(
        exam_name=exam_name,
        exam_description="Regression scenario for bugs.md alias-overflow bug",
    )

    # Build the hierarchy from the bug report verbatim:
    # System > Subsystem > Topic > Leaf (alias)
    system = db.create_subject_node(
        exam_context=exam_name,
        name="Male & Transgender Reproductive System",
        level_type="System",
        parent_id=None,
        sort_order=1,
    )
    neoplasms = db.create_subject_node(
        exam_context=exam_name,
        name="Neoplasms",
        level_type="Subsystem",
        parent_id=system.id,
        sort_order=1,
    )
    topic = db.create_subject_node(
        exam_context=exam_name,
        name="penile malignant neoplasms",
        level_type="Topic",
        parent_id=neoplasms.id,
        sort_order=1,
    )
    leaf = db.create_subject_node(
        exam_context=exam_name,
        name=_DEEP_PATH_LEAF,
        level_type="Topic",
        parent_id=topic.id,
        sort_order=1,
    )
    # Alias attaches to the leaf — this is the lookup key the user types.
    # Method signature: create_subject_alias(subject_node_id, exam_context,
    # alias_name, alias_type='alternate_name', ...). The alias_name is what
    # the fuzzy search hits on; the exam_context scopes the alias to this
    # exam (the same string used in create_subject_node above).
    db.create_subject_alias(
        subject_node_id=leaf.id,
        exam_context=exam_name,
        alias_name=_LEAF_ALIAS,
    )

    # ``question_entry.html`` requires a session_id query param or it
    # redirects back to the dashboard. The bug under test is the search
    # dropdown, not session lifecycle, so we just create a minimal
    # session to satisfy the navigation guard.
    from datetime import date
    review_session = db.create_review_session(
        exam_context_id=db.get_exam_context_by_name(exam_name).id,
        total_questions=1,
        total_incorrect=1,
        session_name="Bug repro: alias overflow",
        date_encountered=date.today(),
    )

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("entry-form", query={"session_id": review_session.id})

    # The Subjects section starts collapsed by default; CSS hides the
    # content via ``.entry-section:not(.expanded) .entry-section-content
    # { display: none; }`` (see entry.css:498-506), so the search input
    # inside has zero rect and the locator can't click it. Add the
    # ``expanded`` class directly — calling ``toggleSection()`` is
    # unreliable in tests because page-side init logic that runs on
    # initializeEntryPage() can re-collapse non-current sections in
    # response to focus/blur or required-field validation.
    wimi_page.eval_js(
        "document.getElementById('section-subjects').classList.add('expanded')"
    )

    # The primary subject search input has data-testid
    # 'entry-form-subject-primary-search' (UI_AUDIT.md §question_entry).
    search_input = wimi_page.locator(testid="entry-form-subject-primary-search")
    search_input.fill(_LEAF_ALIAS)

    # The page's input event listener is attached inside
    # ``initSubjectSearchField`` which runs late in ``initializeEntryPage``
    # (after the awaited ``loadAllSubjectsForFuzzySearch``). When the test
    # navigates and fills quickly, ``fill()``'s synthetic ``input`` event
    # can fire BEFORE the page-side listener is attached, leaving the
    # dropdown empty. Re-dispatching the event after a short wait gives
    # the listener time to attach and then triggers it. This is purely
    # a timing escape hatch; the bug under test is the layout overflow,
    # not the search wiring, so dispatching twice is acceptable.
    # TODO(Phase 3 / T3.6): replace with
    #     wimi_page.wait_for_bridge_call("searchSubjectsFuzzy")
    wimi_page.wait_for_timeout(500)
    wimi_page.eval_js(
        "document.getElementById('primary-subject-search')"
        ".dispatchEvent(new Event('input', { bubbles: true }))"
    )
    wimi_page.wait_for_timeout(300)

    # ---- Assert ------------------------------------------------------
    # Compute alias-span clipping in the page so we don't have to handle
    # async layout in Python. The script returns a small dict the test
    # can structurally validate.
    layout_check: Any = wimi_page.eval_js(
        """
        (() => {
            // Find the first dropdown row that rendered an alias-match
            // span — that's the row we're verifying.
            const row = document.querySelector(
                '#primary-subject-dropdown .subject-option:has(.alias-match)'
            );
            if (!row) {
                return { found: false };
            }
            const alias = row.querySelector('.alias-match');
            if (!alias) {
                return { found: false };
            }
            const rowRect = row.getBoundingClientRect();
            const aliasRect = alias.getBoundingClientRect();
            return {
                found: true,
                rowRight: rowRect.right,
                aliasRight: aliasRect.right,
                aliasWidth: aliasRect.width,
                aliasText: alias.textContent.trim(),
            };
        })()
        """
    )

    assert layout_check["found"], (
        "No dropdown row with class 'alias-match' rendered for query "
        f"{_LEAF_ALIAS!r}. The alias seed or the search wiring regressed "
        "before the layout assertion could fire."
    )

    # Width sanity-check first: a zero-width alias span is invisible even
    # if its right edge happens to fall within bounds.
    assert layout_check["aliasWidth"] > 0, (
        f"Alias-match span rendered with zero width ({layout_check!r}); "
        "the (matched: ...) indicator is not visible to the user."
    )

    # The crux of the bug: alias.right must not exceed row.right.
    # A small tolerance (1px) accounts for sub-pixel rounding.
    assert layout_check["aliasRight"] <= layout_check["rowRight"] + 1, (
        "Alias-match span overflows the dropdown row — this is the "
        "regression from bugs.md (UI Overflow in Subject Hierarchy). "
        f"row.right={layout_check['rowRight']}, "
        f"alias.right={layout_check['aliasRight']}, "
        f"alias text={layout_check['aliasText']!r}"
    )
