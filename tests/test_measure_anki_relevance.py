"""scripts/measure_anki_relevance.py: the owner's measurement tool (#784 Wave 5).

The owner runs it on their own profile, so two properties matter more than its
arithmetic: it must never write to the file it reads, and it must agree with
what the entry page proposes. Both are checked here against a synthetic
profile built through the real database layer.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from database.user_db import UserDatabase

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_anki_relevance.py"


def _load():
    spec = importlib.util.spec_from_file_location("measure_anki_relevance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _card(card_id, note_id, front):
    return {"cardId": card_id, "note": note_id, "deckName": "Deck", "modelName": "Basic",
            "interval": 3, "due": 1, "reps": 1, "lapses": 0, "queue": 0, "type": 2, "ord": 0,
            "fields": {"Front": {"value": front, "order": 0}}}


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "user_001_owner.db"
    db = UserDatabase(path, user_id=1, username="owner")
    exam = db.create_exam_context(exam_name="Step X")
    bank = db.create_question_source(source_name="Bank", exam_context="Step X")
    db.anki_add_template(exam.id, bank.id, "tag:Bank::{{qid}}")
    aorta = db.create_subject_node("Step X", "Aortic dissection", "System")
    session = db.create_review_session(exam_context_id=exam.id, total_questions=5,
                                       total_incorrect=2, question_source_id=bank.id)
    several = db.create_question_entry(session.id, "A", "B", question_id="7",
                                       primary_subject_ids=[aorta.id])
    db.create_question_entry(session.id, "A", "B", question_id="8")
    key = {"exam_context_id": exam.id, "question_source_id": bank.id}
    db.anki_record_refresh(dict(key, question_id="7"), reviews={}, cards=[
        _card(101, 10, "Aortic dissection pain"), _card(102, 11, "Renal")])
    db.anki_record_refresh(dict(key, question_id="8"), reviews={}, cards=[
        _card(103, 12, "Only card")])
    db.close()
    return path, several.id


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_it_counts_and_proposes_what_the_page_proposes(profile):
    path, entry_id = profile
    lines = []
    stats = _load().measure(path, show_text=False, out=lines.append)
    assert stats["entries_with_cards"] == 2
    assert stats["entries_with_several_cards"] == 1
    assert stats["with_proposals"] == 1 and stats["proposals"] == 1
    text = "\n".join(lines)
    assert f"Entry {entry_id}, question 7: 2 cards, 1 proposed" in text
    assert "[PROPOSED] card 101" in text and "matched: Aortic dissection (subject)" in text
    assert "Renal" not in text, "--no-text must leave card text out"


def test_it_never_writes_to_the_profile(profile):
    path, _ = profile
    before = {p.name: _digest(p) for p in path.parent.iterdir() if p.is_file()}
    _load().measure(path, out=lambda line: None)
    after = {p.name: _digest(p) for p in path.parent.iterdir() if p.is_file()}
    assert after == before


def test_it_reads_commits_still_in_the_wal(profile):
    """WIMI open: the newest work sits in the WAL, uncheckpointed."""
    import sqlite3
    path, _ = profile
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    match = writer.execute("SELECT id FROM anki_question_matches "
                           "WHERE question_id = '8'").fetchone()[0]
    writer.execute("INSERT INTO anki_cards (card_id, note_id, fetched_at) "
                   "VALUES (104, 12, '2026-10-14T00:00:00Z')")
    writer.execute("INSERT INTO anki_match_cards (match_id, card_id) VALUES (?, 104)", (match,))
    writer.commit()
    try:
        assert path.with_name(path.name + "-wal").stat().st_size > 0
        stats = _load().measure(path, show_text=False, out=lambda line: None)
        assert stats["entries_with_several_cards"] == 2
    finally:
        writer.close()


def test_it_refuses_a_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        _load().main([str(tmp_path / "nope.db")])
