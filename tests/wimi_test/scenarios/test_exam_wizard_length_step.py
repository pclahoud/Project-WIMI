"""Regression: exam wizard renders + persists the Stage 4 length triple.

Stage 4 of ``docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md``.
Verifies that the new ``Length`` wizard step:

1. Renders with three radio options (fixed / range / unknown).
2. Reveals the variable-length input grid when the user picks
   ``Variable length (CAT)``.
3. Persists the user-entered triple via ``api.updateExamLength`` and
   the value round-trips through ``api.getExamLength``.

Why a wimi-test scenario rather than a pytest-only test
-------------------------------------------------------

The validation invariants live in pytest tests at
``tests/database/test_exam_length.py``. This scenario covers the
*wiring* — that the wizard's HTML markup, JS event listeners, and
bridge calls connect correctly when WIMI is actually running. A pure
pytest test could not catch a missing ``data-testid`` attribute or a
JS event listener that never wires the radio change to the backing
model.

Markers / fixtures
------------------

* ``@pytest.mark.slow`` — spawns a real WIMI subprocess.
* ``@pytest.mark.regression`` — registered in ``pytest.ini`` so
  collection emits no warning.
* Fixtures: ``wimi_session``, ``wimi_page``. We exercise the wizard's
  client-side state via ``eval_js`` rather than driving every step of
  the wizard with synthetic clicks; the bug class under test is
  "does the length step persist correctly", not "does the rest of the
  wizard render". Validation invariants are covered by the pytest
  unit tests on the user_db method.
"""

from __future__ import annotations

from typing import Any

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession


@pytest.mark.slow
@pytest.mark.regression
def test_exam_wizard_length_step_renders_and_persists(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    """The length step renders, switches input groups, and persists state.

    Arrange
    -------
    Create an exam context up-front through the database so we have
    a stable ID to drive ``api.updateExamLength`` against without
    walking the entire wizard. The wizard step itself is then driven
    via ``eval_js`` to populate radios + inputs (the wizard's heavy
    state machine spans 7+ steps which is not the SUT here).

    Act
    ---
    1. Navigate to the exam wizard page.
    2. Assert the length step exists in the DOM (testid lookup).
    3. Drive the length-step radios and number inputs via JS.
    4. Persist via ``api.updateExamLength``.
    5. Read back via ``api.getExamLength``.

    Assert
    ------
    The persisted triple matches what we wrote (kind='range',
    min=85, max=150, typical=100).
    """
    # ---- Arrange -----------------------------------------------------
    db = wimi_session.user.db
    db._ensure_phase2_schema()

    exam = db.create_exam_context(
        exam_name="Stage 4 Length Step Repro",
        exam_description="Regression for exam-length wizard step",
    )

    # ---- Act ---------------------------------------------------------
    wimi_page.goto("exam-wizard")

    # Sanity: the new length step exists in the DOM. data-testid is the
    # stable locator path per docs/testing/UI_AUDIT.md preference order.
    length_step_present = wimi_page.eval_js(
        "!!document.querySelector('[data-testid=\"exam-wizard-length-step\"]')"
    )
    assert length_step_present, (
        "exam-wizard-length-step is missing from the DOM — the new "
        "wizard step's HTML did not render."
    )

    # All three radios + the inputs share a common testid family. Verify
    # they are all present so a missing element fails fast with a clear
    # message rather than as a side effect of a later assertion.
    expected_testids = [
        "exam-wizard-length-kind-fixed",
        "exam-wizard-length-kind-range",
        "exam-wizard-length-kind-unknown",
        "exam-wizard-length-min",
        "exam-wizard-length-max",
        "exam-wizard-length-range-typical",
        "exam-wizard-length-typical",
        "exam-wizard-length-note",
    ]
    missing = wimi_page.eval_js(
        """
        (() => {
            const ids = %s;
            return ids.filter(id => !document.querySelector(`[data-testid="${id}"]`));
        })()
        """ % expected_testids
    )
    assert missing == [], f"Missing data-testids on the length step: {missing!r}"

    # Drive the length-step inputs via JS rather than synthetic clicks
    # to keep the scenario robust against CDP click-routing quirks
    # described in MEMORY.md ("CDP click drops on inline-styled modal
    # buttons"). The handlers under test are bound by
    # setupExamLengthListeners; firing the same change/input events the
    # wizard itself listens for exercises the same code path.
    wimi_page.eval_js(
        """
        (() => {
            const range = document.getElementById('exam-length-kind-range');
            range.checked = true;
            range.dispatchEvent(new Event('change', {bubbles: true}));

            const setVal = (id, v) => {
                const el = document.getElementById(id);
                el.value = String(v);
                el.dispatchEvent(new Event('input', {bubbles: true}));
            };
            setVal('exam-length-range-min', 85);
            setVal('exam-length-range-typical', 100);
            setVal('exam-length-range-max', 150);

            const note = document.getElementById('exam-length-note');
            note.value = 'CAT regression';
            note.dispatchEvent(new Event('input', {bubbles: true}));
        })()
        """
    )

    # Sanity: after the radio change, the range field group should be
    # visible (i.e. the .hidden class is removed).
    range_visible = wimi_page.eval_js(
        """
        (() => {
            const el = document.getElementById('exam-length-fields-range');
            return !el.classList.contains('hidden');
        })()
        """
    )
    assert range_visible, (
        "Range field group did not become visible after kind=range was "
        "selected — the radio change handler did not toggle the field "
        "visibility."
    )

    # Persist via the bridge. The wizard does this on createNewExam, but
    # we drive the bridge directly here so the assertion targets the
    # length-step contract specifically (rather than coupling to the
    # rest of the wizard's submit flow).
    update_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const res = await api.updateExamLength({{
                    examContextId: {exam.id},
                    kind: 'range',
                    min: 85,
                    max: 150,
                    typical: 100,
                    note: 'CAT regression'
                }});
                return {{ok: true, length: res.length}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert update_result.get("ok"), (
        f"api.updateExamLength returned an error: {update_result!r}"
    )

    # ---- Assert: bridge round-trip ----------------------------------
    read_result: Any = wimi_page.eval_js(
        f"""
        (async () => {{
            try {{
                const length = await api.getExamLength({exam.id});
                return {{ok: true, length: length}};
            }} catch (e) {{
                return {{ok: false, error: String(e)}};
            }}
        }})()
        """,
        await_promise=True,
    )
    assert read_result.get("ok"), (
        f"api.getExamLength returned an error: {read_result!r}"
    )

    length = read_result["length"]
    assert length["kind"] == "range", (
        f"Persisted length_kind was {length['kind']!r}, expected 'range'"
    )
    assert length["min"] == 85
    assert length["max"] == 150
    assert length["typical"] == 100
    assert length["note"] == "CAT regression"

    # ---- Assert: DB-level confirmation ------------------------------
    # Direct DB read confirms the bridge actually wrote to SQLite (not
    # just returned a memoized in-process value). This is the kind of
    # cross-layer assertion that catches a bridge that swallows errors
    # silently.
    db_length = db.get_exam_length(exam.id)
    assert db_length["kind"] == "range"
    assert db_length["min"] == 85
    assert db_length["max"] == 150
    assert db_length["typical"] == 100
    assert db_length["note"] == "CAT regression"
