"""Creating a profile opens it (#775, owner 2026-10-12), and the manual says so.

Two chapters taught the opposite for three months ("creating a profile does
not open it... click that card to go in"), and the picker scenario pinned it.
A chapter that documents a defect is a dependency of that defect's fix, so
this test holds the retraction: neither chapter may say the old thing again,
and the create flow must call selectProfile.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CHAPTERS = [
    REPO / "docs/manual/02_the_first_hour.md",
    REPO / "docs/manual/70_profiles_and_profile_files.md",
]
PICKER_JS = REPO / "src/web/js/profile_select.js"


@pytest.mark.unit
@pytest.mark.parametrize("chapter", CHAPTERS, ids=lambda p: p.name)
def test_the_chapter_no_longer_says_creating_a_profile_stays_on_the_picker(chapter):
    text = chapter.read_text(encoding="utf-8").lower()
    assert "does not open it" not in text, chapter.name
    assert "click that card to go in" not in text, chapter.name
    assert "you click the card to go in" not in text, chapter.name


@pytest.mark.unit
def test_the_create_flow_opens_the_profile_it_created():
    """submitCreateForm must hand the new id to selectProfile. Asserted as a
    call inside that function's body, not as a name anywhere in the file,
    which the file already contained before the fix."""
    src = PICKER_JS.read_text(encoding="utf-8")
    start = src.index("async function submitCreateForm()")
    end = src.index("\n}\n", start)
    body = src[start:end]
    assert "selectProfile(" in body, "submitCreateForm does not open the created profile"
    assert "loadProfiles()" not in body, (
        "submitCreateForm still redraws the picker instead of leaving it")
