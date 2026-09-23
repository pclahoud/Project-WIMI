"""Regression: the efficiency score is drawn as a band only when asked (#133).

#133 took weight provenance out of ``_calculate_efficiency_score``'s
arithmetic — a confidence factor that multiplied a *penalty*, so a
weight WIMI could not vouch for produced a **higher** score. The
uncertainty did not disappear, it stopped being priced in: it is now
rendered, and whether it is rendered is
``user_preferences.efficiency_show_confidence_band`` (m022, default
off).

This is a frontend-only coupling — the backend computes
``efficiency_band`` unconditionally and ``weight_analysis.js`` decides
whether to draw it — so pytest against the database layer cannot see a
regression here. Per ``CLAUDE.md`` §"Dimension code path symmetry", an
"after write X, the UI shows the new state" claim needs a scenario.

Asserted:

* preference **off** (the default) — one number, ``NN/100``, and no
  band note;
* preference **on** — a range, ``LO-HI/100`` (en dash), plus the
  ``[data-testid=efficiency-band-note]`` sentence naming the unverified
  share;
* the info affordance at the card is present either way.

API alias note: ``src/web/js/api/_loader.js`` aliases
``window._wimiApi`` -> ``window.api``; probes use ``window.api``.
"""
from __future__ import annotations

import pytest

from wimi_test.page import WimiPage
from wimi_test.session import WimiTestSession

_RELOAD_JS = """
(async () => {
    try {
        await window.api.ready();
        const dash = window.analyticsDashboard || window.dashboard || null;
        if (!dash) return {ok: false, error: 'no dashboard global'};
        dash.currentExamFilter = %d;
        if (dash.weightAnalysis) dash.weightAnalysis.showConfidenceBand = null;
        await dash.loadWeightAnalysis();
        for (let i = 0; i < 50; i += 1) {
            const el = document.querySelector(
                '[data-testid="efficiency-score-value"]');
            if (el && el.textContent.trim()) {
                return {
                    ok: true,
                    value: el.textContent.trim(),
                    note: (document.querySelector(
                        '[data-testid="efficiency-band-note"]'
                    ) || {}).textContent || null,
                    info: !!document.querySelector(
                        '[data-testid="efficiency-confidence-info"]'),
                };
            }
            await new Promise(r => setTimeout(r, 100));
        }
        return {ok: false, error: 'score never rendered'};
    } catch (e) {
        return {ok: false, error: String(e)};
    }
})()
"""


def _seed(db):
    """An exam whose weights are all ``user_defined`` — i.e. unverified.

    That is the realistic case (the subject importer writes
    ``user_defined`` for every imported subject), and it is what makes
    the band non-empty.
    """
    exam = db.create_exam_context(
        exam_name="Efficiency Band Toggle",
        exam_description="Regression for #133's band rendering",
    )
    for name, low, high in (
        ("Band Cardio", 20, 30),
        ("Band Renal", 10, 20),
        ("Band Neuro", 5, 15),
    ):
        db.create_subject_node_with_weight(
            exam_context=exam.exam_name, name=name, level_type='System',
            exam_weight_low=low, exam_weight_high=high,
            weight_source='user_defined',
        )
    return exam


@pytest.mark.slow
@pytest.mark.regression
def test_efficiency_band_follows_the_preference(
    wimi_session: WimiTestSession,
    wimi_page: WimiPage,
) -> None:
    db = wimi_session.user.db
    db._ensure_phase2_schema()
    exam = _seed(db)

    assert db.get_all_settings()['efficiency_show_confidence_band'] is False, (
        "m022 must default the band off: the rating bands (>= 85 "
        "Excellent) assume a scalar."
    )

    wimi_page.goto("analytics")
    assert wimi_page.eval_js(
        "(() => typeof window.api !== 'undefined' "
        "&& typeof window.api.getUserPreferences === 'function')()"
    ), "window.api.getUserPreferences is missing; check api/_loader.js."

    # ---- default: one number ----------------------------------------
    off = wimi_page.eval_js(_RELOAD_JS % exam.id, await_promise=True)
    assert off.get('ok'), f"Weight analysis did not render: {off!r}"
    assert '–' not in off['value'], (
        f"Band drawn with the preference off: {off['value']!r}"
    )
    assert off['note'] is None, (
        f"Band note drawn with the preference off: {off['note']!r}"
    )
    assert off['info'], (
        "The info affordance at the card is unconditional (#133) and is "
        "the only place the single number says provenance exists."
    )

    # ---- turned on: a range plus its explanation ---------------------
    db.update_settings(efficiency_show_confidence_band=True)
    on = wimi_page.eval_js(_RELOAD_JS % exam.id, await_promise=True)
    assert on.get('ok'), f"Weight analysis did not re-render: {on!r}"
    assert '–' in on['value'], (
        f"Expected a range once the preference is on, got {on['value']!r}"
    )
    assert on['note'] and 'typed or derived' in on['note'], (
        f"Band note missing or unexpected: {on['note']!r}"
    )

    # ---- and back off again ------------------------------------------
    db.update_settings(efficiency_show_confidence_band=False)
    again = wimi_page.eval_js(_RELOAD_JS % exam.id, await_promise=True)
    assert again.get('ok'), f"Weight analysis did not re-render: {again!r}"
    assert again['value'] == off['value'], (
        "The score itself must be the same number either way -- the "
        "toggle governs presentation, not arithmetic. "
        f"off={off['value']!r} back-off={again['value']!r}"
    )
