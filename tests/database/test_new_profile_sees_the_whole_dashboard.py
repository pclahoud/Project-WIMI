"""#504: a new profile's analytics detail level is the whole page.

analytics_detail_level was read by nothing, so every student saw the whole
analytics page whatever it said. Now that it is live, a level that hides
anything must be a choice: a new profile starts at 'advanced'. The column's
m001 DEFAULT still says 'detailed' and cannot change without rebuilding the
table, so create_default_preferences states the value -- this is the test
that it does, and that the dataclass, the reader's fallback and the
Settings page agree.
"""
from __future__ import annotations

import re
from pathlib import Path

from database.models import UserPreferences
from database.user_db import UserDatabase

REPO = Path(__file__).resolve().parents[2]


def test_a_new_profile_starts_with_the_whole_analytics_page(tmp_path):
    db = UserDatabase(db_path=tmp_path / "u.db", user_id=1, username="u")
    try:
        assert db.get_preferences().analytics_detail_level == "advanced"
        stored = db.fetchone("SELECT analytics_detail_level FROM user_preferences WHERE user_id = 1")
        assert stored["analytics_detail_level"] == "advanced", "the row, not just the dataclass"
    finally:
        db.close()


def test_the_reader_falls_back_to_the_whole_page():
    assert UserPreferences.from_db_row({"id": 1, "user_id": 1}).analytics_detail_level == "advanced"


def test_the_settings_page_agrees():
    html = (REPO / "src/web/html/settings.html").read_text(encoding="utf-8")
    select = re.search(r'<select id="analytics_detail_level".*?</select>', html, re.S).group(0)
    assert re.search(r'value="advanced" selected', select)


def test_a_new_profile_is_still_offered_a_break_when_a_round_ends(tmp_path):
    """manual_break_control is live since #504; m001's column DEFAULT is 1
    ("only when I ask"), which would silently stop the round-end offer."""
    db = UserDatabase(db_path=tmp_path / "u.db", user_id=1, username="u")
    try:
        assert db.get_preferences().manual_break_control is False
        stored = db.fetchone("SELECT manual_break_control FROM user_preferences WHERE user_id = 1")
        assert not stored["manual_break_control"]
    finally:
        db.close()
