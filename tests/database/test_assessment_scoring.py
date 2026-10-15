"""Tests for the pure-Python assessment scoring module.

Stage 0 of the Psychometric Assessment Implementation Plan
(``docs/planning/PSYCHOMETRIC_ASSESSMENT_IMPLEMENTATION_PLAN.md``).

Most cases use a synthetic test fixture built in a tmpdir so the math
is verifiable independent of whether the production ``v1`` fixture has
been populated with real Cacioppo/VandeWalle item text yet. One
structural test loads the real ``v1`` fixture to assert counts and
subscale balance — it never asserts on prompt strings, since those are
placeholders that the project owner fills in from copyrighted source
papers before the assessment ships.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from database.domains import _assessment_scoring as scoring


# ---------------------------------------------------------------- helpers


def _write_test_fixture(tmp_path: Path) -> Path:
    """Build a minimal fixture exercising every scoring code path."""
    base = tmp_path / "vtest"
    base.mkdir(parents=True)
    (base / "manifest.json").write_text(json.dumps({
        "version": "vtest",
        "scales": {
            "likert_5": {"min": 1, "max": 5, "anchors": ["1", "2", "3", "4", "5"]},
            "likert_6": {"min": 1, "max": 6, "anchors": ["1", "2", "3", "4", "5", "6"]},
            "likert_7": {"min": 1, "max": 7, "anchors": ["1", "2", "3", "4", "5", "6", "7"]},
        },
        "sections": [
            {
                "name": "nfc", "title": "NFC", "scale": "likert_5",
                "fixture": "nfc.json",
                "scoring": {"method": "mean", "subscales": []},
            },
            {
                "name": "lgo", "title": "LGO", "scale": "likert_6",
                "fixture": "lgo.json",
                "scoring": {"method": "mean_per_subscale",
                            "subscales": ["learning", "prove", "avoid"]},
            },
            {
                "name": "importance", "title": "Importance", "scale": "likert_7",
                "fixture": "importance.json",
                "scoring": {"method": "mean_per_subscale",
                            "subscales": ["exam", "clinical", "mastery", "reflection"]},
            },
        ],
        "attention_checks": "attention_checks.json",
    }), encoding="utf-8")

    # 4 NFC items: 2 normal + 2 reverse-keyed. Lets the all-1s test
    # produce a numerically distinct mean from the all-3s sanity test.
    (base / "nfc.json").write_text(json.dumps([
        {"item_code": "nfc_01", "prompt": "n1", "reverse_scored": False},
        {"item_code": "nfc_02", "prompt": "n2", "reverse_scored": False},
        {"item_code": "nfc_03", "prompt": "n3", "reverse_scored": True},
        {"item_code": "nfc_04", "prompt": "n4", "reverse_scored": True},
    ]), encoding="utf-8")

    # 6 LGO items: 2 per subscale.
    (base / "lgo.json").write_text(json.dumps([
        {"item_code": "lgo_learning_01", "prompt": "l1", "subscale": "learning"},
        {"item_code": "lgo_learning_02", "prompt": "l2", "subscale": "learning"},
        {"item_code": "lgo_prove_01",    "prompt": "p1", "subscale": "prove"},
        {"item_code": "lgo_prove_02",    "prompt": "p2", "subscale": "prove"},
        {"item_code": "lgo_avoid_01",    "prompt": "a1", "subscale": "avoid"},
        {"item_code": "lgo_avoid_02",    "prompt": "a2", "subscale": "avoid"},
    ]), encoding="utf-8")

    # 8 importance items: 2 per subscale.
    (base / "importance.json").write_text(json.dumps([
        {"item_code": "imp_exam_01",       "prompt": "e1", "subscale": "exam"},
        {"item_code": "imp_exam_02",       "prompt": "e2", "subscale": "exam"},
        {"item_code": "imp_clinical_01",   "prompt": "c1", "subscale": "clinical"},
        {"item_code": "imp_clinical_02",   "prompt": "c2", "subscale": "clinical"},
        {"item_code": "imp_mastery_01",    "prompt": "m1", "subscale": "mastery"},
        {"item_code": "imp_mastery_02",    "prompt": "m2", "subscale": "mastery"},
        {"item_code": "imp_reflection_01", "prompt": "r1", "subscale": "reflection"},
        {"item_code": "imp_reflection_02", "prompt": "r2", "subscale": "reflection"},
    ]), encoding="utf-8")

    (base / "attention_checks.json").write_text(json.dumps([
        {"item_code": "atc_01", "prompt": "select 2", "expected_response": 2, "scale": "likert_5"},
        {"item_code": "atc_02", "prompt": "select 4", "expected_response": 4, "scale": "likert_6"},
    ]), encoding="utf-8")
    return base


@pytest.fixture
def test_fixture(tmp_path):
    base = _write_test_fixture(tmp_path)
    return scoring.load_fixture("vtest", base_dir=base)


# ---------------------------------------------------------------- reverse math


def test_contribute_reverse_5pt():
    item = scoring.ItemSpec(
        item_code="x", prompt="p",
        scale=scoring.ScaleSpec("likert_5", 1, 5),
        reverse_scored=True,
    )
    assert scoring._contribute(item, 1) == 5.0
    assert scoring._contribute(item, 5) == 1.0
    assert scoring._contribute(item, 4) == 2.0


def test_contribute_normal_passthrough():
    item = scoring.ItemSpec(
        item_code="x", prompt="p",
        scale=scoring.ScaleSpec("likert_5", 1, 5),
    )
    assert scoring._contribute(item, 3) == 3.0


# ---------------------------------------------------------------- section scoring


def test_nfc_all_ones_with_mixed_reverse(test_fixture):
    # 2 normal items contribute 1 + 1; 2 reverse items contribute 5 + 5.
    # Mean = (1+1+5+5)/4 = 3.0
    responses = {"nfc_01": 1, "nfc_02": 1, "nfc_03": 1, "nfc_04": 1}
    out = scoring.score_administration(responses, test_fixture)
    assert out.nfc_total == 3.0


def test_nfc_all_fives_with_mixed_reverse(test_fixture):
    # 2 normal contribute 5 + 5; 2 reverse contribute 1 + 1. Mean 3.0
    responses = {"nfc_01": 5, "nfc_02": 5, "nfc_03": 5, "nfc_04": 5}
    out = scoring.score_administration(responses, test_fixture)
    assert out.nfc_total == 3.0


def test_lgo_per_subscale(test_fixture):
    responses = {
        "lgo_learning_01": 6, "lgo_learning_02": 6,
        "lgo_prove_01": 3, "lgo_prove_02": 3,
        "lgo_avoid_01": 1, "lgo_avoid_02": 1,
    }
    out = scoring.score_administration(responses, test_fixture)
    assert out.lgo_learning == 6.0
    assert out.lgo_prove == 3.0
    assert out.lgo_avoid == 1.0


def test_importance_per_subscale(test_fixture):
    responses = {
        "imp_exam_01": 7, "imp_exam_02": 5,
        "imp_clinical_01": 7, "imp_clinical_02": 7,
        "imp_mastery_01": 4, "imp_mastery_02": 4,
        "imp_reflection_01": 1, "imp_reflection_02": 3,
    }
    out = scoring.score_administration(responses, test_fixture)
    assert out.importance_exam == 6.0
    assert out.importance_clinical == 7.0
    assert out.importance_mastery == 4.0
    assert out.importance_reflection == 2.0


def test_missing_subscale_returns_none(test_fixture):
    # NFC only — all LGO and importance subscales should be None
    responses = {"nfc_01": 3, "nfc_02": 3, "nfc_03": 3, "nfc_04": 3}
    out = scoring.score_administration(responses, test_fixture)
    assert out.nfc_total == 3.0
    assert out.lgo_learning is None
    assert out.lgo_prove is None
    assert out.lgo_avoid is None
    assert out.importance_exam is None
    assert out.importance_clinical is None
    assert out.importance_mastery is None
    assert out.importance_reflection is None


def test_partial_subscale_uses_only_present_items(test_fixture):
    # Only one of two learning items answered — mean of one value.
    responses = {"lgo_learning_01": 5}
    out = scoring.score_administration(responses, test_fixture)
    assert out.lgo_learning == 5.0
    assert out.lgo_prove is None


# ---------------------------------------------------------------- attention


def test_attention_check_both_pass(test_fixture):
    out = scoring.score_administration({"atc_01": 2, "atc_02": 4}, test_fixture)
    assert out.attention_check_pass is True


def test_attention_check_one_off(test_fixture):
    out = scoring.score_administration({"atc_01": 2, "atc_02": 5}, test_fixture)
    assert out.attention_check_pass is False


def test_attention_check_both_off(test_fixture):
    out = scoring.score_administration({"atc_01": 1, "atc_02": 1}, test_fixture)
    assert out.attention_check_pass is False


def test_attention_check_either_missing_fails(test_fixture):
    out = scoring.score_administration({"atc_01": 2}, test_fixture)
    assert out.attention_check_pass is False


# ---------------------------------------------------------------- loader


def test_load_fixture_unknown_version_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scoring.load_fixture("vnope", base_dir=tmp_path / "does_not_exist")


def test_load_v1_fixture_structural():
    """V1 fixture: assert counts/subscale balance only.

    Do NOT assert on prompt strings — those are placeholders the
    populator fills in from copyrighted source papers before shipping.
    """
    fixture = scoring.load_fixture("v1")
    assert fixture.version == "v1"

    nfc = next(s for s in fixture.sections if s.name == "nfc")
    assert len(nfc.items) == 34
    assert nfc.scoring_method == "mean"

    lgo = next(s for s in fixture.sections if s.name == "lgo")
    assert len(lgo.items) == 13
    assert lgo.scoring_method == "mean_per_subscale"
    assert len([i for i in lgo.items if i.subscale == "learning"]) == 5
    assert len([i for i in lgo.items if i.subscale == "prove"]) == 4
    assert len([i for i in lgo.items if i.subscale == "avoid"]) == 4

    importance = next(s for s in fixture.sections if s.name == "importance")
    assert len(importance.items) == 8
    for sub in ("exam", "clinical", "mastery", "reflection"):
        assert len([i for i in importance.items if i.subscale == sub]) == 2

    assert len(fixture.attention_checks) == 2


def test_fixture_item_lookup(test_fixture):
    item = test_fixture.item("nfc_03")
    assert item.reverse_scored is True
    with pytest.raises(KeyError):
        test_fixture.item("does_not_exist")


# ---------------------------------------------------------------- validate


def test_validate_response_accepts_bounds():
    item = scoring.ItemSpec("x", "p", scoring.ScaleSpec("l5", 1, 5))
    scoring.validate_response(item, 1)
    scoring.validate_response(item, 5)
    scoring.validate_response(item, 3)


def test_validate_response_rejects_below_min():
    item = scoring.ItemSpec("x", "p", scoring.ScaleSpec("l5", 1, 5))
    with pytest.raises(ValueError):
        scoring.validate_response(item, 0)


def test_validate_response_rejects_above_max():
    item = scoring.ItemSpec("x", "p", scoring.ScaleSpec("l5", 1, 5))
    with pytest.raises(ValueError):
        scoring.validate_response(item, 6)


def test_validate_response_rejects_non_int():
    item = scoring.ItemSpec("x", "p", scoring.ScaleSpec("l5", 1, 5))
    with pytest.raises(ValueError):
        scoring.validate_response(item, 3.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        scoring.validate_response(item, True)  # bool rejected
