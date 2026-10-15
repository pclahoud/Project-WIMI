"""The shipped NFC fixture is the 34-item Cacioppo & Petty (1982) scale with
the paper's keying and the paper's nine-point response scale (#766 decisions
7 and 9, owner 2026-10-12).

A wrong reverse flag silently inverts one item's contribution to the mean and
nothing downstream can tell, so the keying is pinned here by code, not by
count. Five of the reversed items carried no mark in the owner's transcription
and were confirmed against the paper on 2026-10-12; they are listed so the next
reader who sees the wording and reaches for the flag finds the decision first.
"""
from __future__ import annotations

import pytest

from database.domains._assessment_scoring import load_fixture

# Pool item numbers in Table 1 of the paper, in fixture order.
POOL_ORDER = [1, 4, 5, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22, 23, 24,
              26, 27, 28, 29, 30, 31, 32, 33, 35, 37, 39, 40, 41, 43, 44, 45]

REVERSED = {
    "nfc_05", "nfc_06", "nfc_08", "nfc_09", "nfc_10", "nfc_11", "nfc_13",
    "nfc_14", "nfc_15", "nfc_16", "nfc_17", "nfc_18", "nfc_20", "nfc_21",
    "nfc_22", "nfc_24", "nfc_25", "nfc_26", "nfc_31", "nfc_32", "nfc_33",
}

# Reversed in the paper but carrying no mark in the transcription; owner
# confirmed. Four of the five are also confirmed by the 1984 short form, which
# either rewrote the item positive or kept it marked reversed.
CONFIRMED_WITHOUT_A_MARK = {"nfc_08", "nfc_10", "nfc_11", "nfc_16", "nfc_18"}


@pytest.fixture(scope="module")
def nfc():
    fx = load_fixture("v1")
    return next(s for s in fx.sections if s.name == "nfc")


@pytest.mark.unit
def test_thirty_four_items_in_pool_order(nfc):
    assert [it.item_code for it in nfc.items] == [f"nfc_{i:02d}" for i in range(1, 35)]
    assert len(POOL_ORDER) == 34 and len(set(POOL_ORDER)) == 34


@pytest.mark.unit
def test_no_prompt_is_still_a_placeholder(nfc):
    for it in nfc.items:
        assert "[POPULATE" not in it.prompt, it.item_code
        assert it.prompt.strip(), it.item_code


@pytest.mark.unit
def test_the_keying_is_the_papers_twenty_one_and_thirteen(nfc):
    actual = {it.item_code for it in nfc.items if it.reverse_scored}
    assert actual == REVERSED, (
        f"extra reversed: {sorted(actual - REVERSED)}; missing: {sorted(REVERSED - actual)}")
    assert len(REVERSED) == 21
    assert CONFIRMED_WITHOUT_A_MARK <= REVERSED


@pytest.mark.unit
def test_every_reversed_item_reads_as_low_need_for_cognition(nfc):
    """A sanity read, not the keying: each reversed prompt carries a negation
    or a 'little'/'only' construction. Catches a flag landing on a positive
    item by a typo in the set above."""
    markers = ("not ", "n't ", "little", "only think", "just leads", "bliss",
               "relief rather than", "hesitant", "difficulty", "let things happen",
               "rather do something that requires little", "small, daily",
               "avoid situations", "Simply knowing the answer")
    for it in nfc.items:
        if it.reverse_scored:
            assert any(m in it.prompt for m in markers), it.item_code


@pytest.mark.unit
def test_nfc_runs_on_the_papers_nine_point_scale(nfc):
    assert nfc.scale.name == "likert_9"
    assert (nfc.scale.min, nfc.scale.max) == (1, 9)
    assert len(nfc.scale.anchors) == 9
    assert nfc.scale.anchors[0] == "Very strong disagreement"
    assert nfc.scale.anchors[4] == "Neither agreement nor disagreement"
    assert nfc.scale.anchors[8] == "Very strong agreement"


@pytest.mark.unit
def test_the_nfc_attention_check_uses_the_same_scale():
    fx = load_fixture("v1")
    atc = fx.item("atc_01")
    assert atc.scale.name == "likert_9"
    assert atc.expected_response == 3
    assert "Moderate disagreement" in atc.prompt
