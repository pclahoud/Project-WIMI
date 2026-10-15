"""The shipped LGO fixture is VandeWalle's (1997) 13-item instrument adapted to
the study domain (#766 decision 8), with the owner's per-item approval of
2026-10-12 on #766 comment #10553.

The adaptation rule was "change only the words that name the work domain",
and the approved text is pinned here word for word: a later tidy that
"improves" an item makes it a different, second adaptation with no record of
who approved it. The keying (none reversed), the subscale structure and the
six-point scale with the paper's anchors are the published instrument's and
are pinned alongside.
"""
from __future__ import annotations

import pytest

from database.domains._assessment_scoring import load_fixture

APPROVED = {
    "lgo_learning_01": "I am willing to take on a challenging study task that I can learn a lot from.",
    "lgo_learning_02": "I often look for opportunities to develop new skills and knowledge.",
    "lgo_learning_03": "I enjoy challenging and difficult tasks in my studies where I'll learn new skills.",
    "lgo_learning_04": "For me, development of my ability is important enough to take risks.",
    "lgo_learning_05": "I prefer to work in situations that require a high level of ability and talent.",
    "lgo_prove_01": "I'm concerned with showing that I can perform better than my classmates.",
    "lgo_prove_02": "I try to figure out what it takes to prove my ability to others in my studies.",
    "lgo_prove_03": "I enjoy it when others in my program are aware of how well I'm doing.",
    "lgo_prove_04": "I prefer to work on assignments where I can prove my ability to others.",
    "lgo_avoid_01": "I would avoid taking on a new task if there was a chance that I would appear rather incompetent to others.",
    "lgo_avoid_02": "Avoiding a show of low ability is more important to me than learning a new skill.",
    "lgo_avoid_03": "I'm concerned about taking on a task in my studies if my performance would reveal that I had low ability.",
    "lgo_avoid_04": "I prefer to avoid situations in my studies where I might perform poorly.",
}

# Items the owner approved verbatim from the paper (#10553's tally).
VERBATIM = {"lgo_learning_02", "lgo_learning_04", "lgo_learning_05", "lgo_avoid_01", "lgo_avoid_02"}


@pytest.fixture(scope="module")
def lgo():
    fx = load_fixture("v1")
    return next(s for s in fx.sections if s.name == "lgo")


@pytest.mark.unit
def test_the_thirteen_prompts_are_the_approved_adaptation(lgo):
    actual = {it.item_code: it.prompt for it in lgo.items}
    assert actual == APPROVED, {k: (actual.get(k), APPROVED.get(k))
                                for k in set(actual) | set(APPROVED)
                                if actual.get(k) != APPROVED.get(k)}


@pytest.mark.unit
def test_no_prompt_is_still_a_placeholder(lgo):
    for it in lgo.items:
        assert "[POPULATE" not in it.prompt, it.item_code


@pytest.mark.unit
def test_no_item_names_the_work_domain(lgo):
    """The whole of decision 8. 'work' as a verb ('work in situations', 'work
    on assignments') is the paper's and stays; the domain nouns go."""
    for it in lgo.items:
        low = it.prompt.lower()
        assert "at work" not in low and "coworker" not in low and "work assignment" not in low, it.item_code


@pytest.mark.unit
def test_structure_and_keying_are_the_published_instruments(lgo):
    by = {}
    for it in lgo.items:
        by.setdefault(it.subscale, []).append(it.item_code)
        assert it.reverse_scored is False, it.item_code
    assert {k: len(v) for k, v in by.items()} == {"learning": 5, "prove": 4, "avoid": 4}
    assert VERBATIM <= set(APPROVED)


@pytest.mark.unit
def test_lgo_runs_on_the_papers_six_point_scale(lgo):
    assert lgo.scale.name == "likert_6"
    assert (lgo.scale.min, lgo.scale.max) == (1, 6)
    assert list(lgo.scale.anchors) == ["Strongly disagree", "Disagree", "Disagree somewhat",
                                       "Agree somewhat", "Agree", "Strongly agree"]


@pytest.mark.unit
def test_the_lgo_attention_check_names_an_anchor_that_exists():
    fx = load_fixture("v1")
    atc = fx.item("atc_02")
    assert atc.scale.name == "likert_6"
    assert atc.expected_response == 4
    assert atc.scale.anchors[atc.expected_response - 1] in atc.prompt
