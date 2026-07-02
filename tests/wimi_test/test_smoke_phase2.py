"""Phase 2 smoke tests for the WIMI test infrastructure.

These three tests are the **closing gate for Phase 2** of
``docs/planning/TEST_INFRASTRUCTURE.md``: once they pass locally, every
public surface introduced in T2.1 - T2.8 has been exercised end-to-end
through real pytest fixtures (no manual ``WimiProcess``/Playwright
plumbing the way Phase 1's smoke test did). After this gate, Phase 4
testid migration and Phase 5 MCP facade work can begin.

The three scenarios:

1. :func:`test_smoke_create_user_and_log_out` -- bare-minimum
   end-to-end: ``wimi_session`` spawns WIMI in test mode, ``wimi_page``
   navigates to the dashboard, a screenshot is captured and verified to
   be non-empty PNG bytes. This proves fixtures, route resolution, and
   the bridge-readiness wait all interlock correctly.
2. :func:`test_create_entry_and_assert_db_row` -- exercise the
   form-fill -> bridge -> DB write loop. ``seeded_user("minimal")``
   gives us an exam context, then the test fills the user-answer and
   correct-answer textareas on the entry form, clicks save, and verifies
   the row landed via :func:`assert_entry_count`.
3. :func:`test_browser_shows_seeded_entries` -- pre-seed five entries
   directly through the per-user :class:`UserDatabase`, navigate to the
   entry browser, and assert five ``.entry-card`` elements render. Pairs
   the visual count with a DB-side count for belt-and-braces coverage.

Locator strategy: every interactive element here is targeted by
``role + accessible name`` per the
:doc:`docs/testing/UI_AUDIT.md` preference order. Where an element
*lacks* an accessible name (the form fields are labelled by neighbouring
``<label for="...">`` markup that Playwright's role engine does pick up,
but the ``.entry-card`` rows are unlabelled), we drop to a CSS selector
or ``eval_js`` count and tag the call with a ``# TODO(Phase 4)`` comment
pointing at the eventual ``data-testid`` from
``docs/testing/UI_AUDIT.md``. Phase 4 (T4.1, T4.3) replaces those
fallbacks with proper ``locator(testid=...)`` calls.

All three tests are marked :pytest:mark:`slow` because each spawns a
real WIMI subprocess (~3-8s startup on a warm disk).
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from wimi_test.db.assertions import assert_entry_count
from wimi_test.db.test_user import TestUser
from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

# First 8 bytes of every PNG file. We don't decode the image -- the byte
# signature is enough to confirm Playwright returned a real PNG and not,
# e.g., an empty buffer or an HTML error page.
_PNG_MAGIC: bytes = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Test 1: minimal end-to-end (session + page + screenshot)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_smoke_create_user_and_log_out(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Spawn WIMI, navigate to dashboard, screenshot, exit.

    The simplest possible Phase 2 test: if this passes, the fixture
    chain (``wimi_config`` -> ``wimi_master_db`` -> ``wimi_session`` ->
    ``wimi_page``) is wired correctly end-to-end and the bridge-ready
    handshake completes inside the default timeout.

    Acceptance criteria (per ``TEST_INFRASTRUCTURE_TASKS.md`` T2.9):

    * Test passes locally.
    * Screenshot is non-empty PNG bytes.
    * Subprocess and per-session user are torn down by the
      ``wimi_session`` fixture (cleanup verified by the lack of stray
      ``app_data_test/users/test_*.db`` files after the run).
    """
    # ``wimi_session`` already started the process and attached the page.
    # We only need to navigate and screenshot.
    wimi_page.goto("dashboard")

    screenshot_bytes = wimi_page.screenshot()

    assert screenshot_bytes, "wimi_page.screenshot() returned empty bytes"
    assert screenshot_bytes.startswith(_PNG_MAGIC), (
        "screenshot bytes do not start with PNG magic; "
        f"got first 8 bytes: {screenshot_bytes[:8]!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: form fill -> bridge -> DB row
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_create_entry_and_assert_db_row(
    seeded_user: Callable[..., TestUser],
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Create one entry through the UI, assert one row landed in the DB.

    This test deliberately requests *both* fixtures even though they
    each create their own :class:`TestUser`:

    * ``seeded_user("minimal")`` returns the user owned by the
      ``test_user`` fixture, which lives in the master DB and is
      seeded with one exam context.
    * ``wimi_session`` (per the :class:`WimiTestSession` design note in
      T2.8) spawns its *own* user inside ``start()`` -- the running
      WIMI subprocess is logged in as ``wimi_session.user``, not as
      the seeded user above.

    The duality is intentional and is documented in
    ``wimi_test/fixtures/core.py``: the seeded-user fixture exists for
    DB-only tests; ``wimi_session.user`` is the one whose database the
    bridge is actually writing to. **All DB assertions in this test go
    through ``wimi_session.user.db``** -- the seeded user's DB is
    inspected only for its layout, not its content.

    Phase 4 escape hatch: the entry form's textareas have associated
    ``<label for="...">`` markup so role+name resolution works for the
    answer fields, but several other inputs on the page do not yet
    surface accessible names. If form-fill flakiness shows up in CI on
    this test, the documented fallback is :meth:`WimiPage.eval_js` to
    drive the bridge directly -- see the TODO at the bottom of this
    function for the exact replacement path.
    """
    # The seeded user proves the seeders pipeline runs end-to-end; the
    # actual DB writes from the bridge land on wimi_session.user.db.
    _seeded = seeded_user("minimal")  # noqa: F841 -- exercised for side effects

    wimi_page.goto("entry-form")

    # Role+name resolves textareas via their <label for="..."> binding.
    # The label text in question_entry.html includes the literal "*"
    # required marker, so we match it verbatim.
    user_answer = wimi_page.locator(role="textbox", name="Your Answer *")
    user_answer.fill("B")

    correct_answer = wimi_page.locator(role="textbox", name="Correct Answer *")
    correct_answer.fill("A")

    # The "Save & Next" button is gated by validation (subject mapping
    # is required). For the smoke test we use "Save as Draft" which
    # accepts a row with only the answer fields filled. Both buttons
    # are role=button with stable accessible names -- see lines 376
    # and 379 of question_entry.html.
    save_button = wimi_page.locator(role="button", name="Save as Draft")
    save_button.click()

    # Wait for the bridge write to land. The proper signal is the
    # auto-save indicator changing state, but that wiring is part of
    # Phase 3's BridgeCapture; for now a small fixed wait is the
    # documented Phase 2 escape hatch (T2.9 spec, scenario 2).
    # TODO(Phase 3 / T3.6): replace with wimi_page.wait_for_bridge_call(
    #     "createQuestionEntry", timeout_ms=2000) once BridgeCapture lands.
    wimi_page.pw_page.wait_for_timeout(500)

    # DB-side verification. ``wimi_session.user.db`` is the database the
    # running WIMI instance writes to, NOT seeded_user's DB.
    assert_entry_count(wimi_session.user.db, expected=1)

    # TODO(Phase 4 / T4.1): once data-testid="entry-form-user-answer"
    # and "entry-form-correct-answer" land per UI_AUDIT.md, the two
    # locator calls above become:
    #     wimi_page.locator(testid="entry-form-user-answer").fill("B")
    #     wimi_page.locator(testid="entry-form-correct-answer").fill("A")
    # and the save button becomes:
    #     wimi_page.locator(testid="entry-form-save-draft").click()


# ---------------------------------------------------------------------------
# Test 3: pre-seed entries, browse, count
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_browser_shows_seeded_entries(
    seeded_user: Callable[..., TestUser],
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """Pre-seed 5 entries in the DB, navigate to browser, count cards.

    Same dual-user caveat as
    :func:`test_create_entry_and_assert_db_row`: the seeded user's DB
    is *not* the DB the running WIMI subprocess is authenticated
    against. We therefore seed the entries directly into
    ``wimi_session.user.db`` so the running browser sees them.

    The ``seeded_user`` fixture is requested only to exercise the
    ``"minimal"`` seeder pipeline (so a regression there fails this
    test, not a Phase 4 navigation test).
    """
    # Exercise the seeders pipeline end-to-end (proves the registry
    # plumbing still resolves), but ignore its database -- WIMI is
    # running against wimi_session.user.db.
    _seeded = seeded_user("minimal")  # noqa: F841 -- exercised for side effects

    db = wimi_session.user.db

    # Bring the live (per-session) DB up to the same baseline the
    # ``minimal`` seeder produces for the seeded user, then create one
    # review session under it so entries have a parent FK to attach to.
    # Match seed_minimal()'s exam name verbatim so re-seeding is a
    # no-op when test ordering shifts.
    db._ensure_phase2_schema()
    db._ensure_phase4_schema()

    exam = db.get_exam_context_by_name("Test Minimal Exam")
    if exam is None:
        exam = db.create_exam_context(
            exam_name="Test Minimal Exam",
            exam_description="Smoke seed for entry-browser visibility check",
        )

    review_session = db.create_review_session(
        exam_context_id=exam.id,
        total_questions=5,
        total_incorrect=5,
        session_name="Smoke seed session",
    )

    # Five entries: question_id Q1..Q5, user answer "B", correct "A".
    # Mirrors the field names used in src/mcp_server.py's list_entries
    # tool and src/database/domains/entries.py::create_question_entry.
    for i in range(1, 6):
        db.create_question_entry(
            review_session_id=review_session.id,
            user_answer="B",
            correct_answer="A",
            question_id=f"Q{i}",
        )

    # Sanity-check the seed before we drive the UI.
    assert_entry_count(db, expected=5)

    wimi_page.goto("entry-browser")

    # The entry browser renders one ``.entry-card`` per row; without
    # testids the cleanest count is a DOM ``querySelectorAll`` via
    # eval_js. The browser issues an async fetch on load, so we wait
    # briefly for the cards to render before counting.
    # TODO(Phase 4 / T4.3): replace with
    #     len(wimi_page.locator(css="[data-testid^='browser-row-']")
    #         .pw_locator.all())
    # once data-testid="browser-row-{id}" lands per UI_AUDIT.md.
    wimi_page.pw_page.wait_for_timeout(500)
    visible_count: Any = wimi_page.eval_js(
        "document.querySelectorAll('.entry-card').length"
    )

    assert visible_count == 5, (
        f"Expected 5 .entry-card elements in the browser; "
        f"got {visible_count!r}"
    )

    # Belt-and-braces: confirm the DB-side count too. If this passes
    # but the UI count above failed, the regression is in the entry
    # browser's render path; if both fail, the regression is in the
    # write path.
    assert_entry_count(db, expected=5)
