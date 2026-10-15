"""Measure the Anki relevance scorer on a copy of a real profile (#784 Wave 5).

The plan asks, before Wave 5 closes: for entries whose question matched
several Anki cards, how often does the lexical scorer propose the cards the
student would pick? Only the student can judge that, so this prints what the
scorer proposes and the student marks it. The owner chose to run it
themselves and post the output on #784 (2026-10-14); no session reads a real
profile.

**Read-only, by construction.** The profile is opened read-only (and
``immutable`` when WIMI is closed, so not even an empty sidecar file is
created) and copied into memory with the backup API, which reads through the
WAL when there is one, so the newest commits are included and nothing is ever
written to the file. ``UserDatabase`` is deliberately not used: opening one runs the
migrations, which write.

It reads only what the entry page's scorer reads: the Anki cache (m034), the
verdicts (m035), the entries' question ids, banks, subjects, aliases and
correct answers. Run it after fetching at least one exam's cards in
Settings -> Anki, with WIMI closed or open (a read-only copy is safe either
way):

    python scripts/measure_anki_relevance.py PATH/TO/user_NNN_name.db
    python scripts/measure_anki_relevance.py PATH/TO/user_NNN_name.db --no-text

``--no-text`` leaves card text out of the sample, so the output can be posted
without the cards' content; card ids and the matched words remain.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app.anki.fields import field_to_text  # noqa: E402
from app.anki.relevance import proposals_for  # noqa: E402

SNIPPET = 70


def _copy_read_only(path: Path) -> sqlite3.Connection:
    """An in-memory copy. With no ``-wal`` beside the file (WIMI closed) the
    file is opened ``immutable``, which creates no sidecar files at all; with
    one (WIMI open) a plain read-only open is needed so the uncheckpointed
    commits in the WAL are read too -- SQLite then shares the existing
    ``-shm`` and writes nothing to the database."""
    wal = path.with_name(path.name + "-wal")
    flags = "mode=ro" if wal.exists() else "mode=ro&immutable=1"
    source = sqlite3.connect(f"file:{path}?{flags}", uri=True)
    memory = sqlite3.connect(":memory:")
    try:
        source.backup(memory)
    finally:
        source.close()
    memory.row_factory = sqlite3.Row
    return memory


def _has_tables(conn, *names) -> bool:
    found = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return set(names) <= found


def _entries(conn):
    """Entries whose question has a match with at least one card."""
    return conn.execute(
        "SELECT qe.id AS entry_id, TRIM(qe.question_id) AS question_id, qe.correct_answer, "
        "       m.id AS match_id "
        "FROM question_entries qe "
        "JOIN review_sessions rs ON rs.id = qe.review_session_id "
        "JOIN anki_question_matches m ON m.exam_context_id = rs.exam_context_id "
        "     AND m.question_source_id = rs.question_source_id "
        "     AND m.question_id = TRIM(qe.question_id) "
        "WHERE qe.question_id IS NOT NULL AND TRIM(qe.question_id) != '' "
        "ORDER BY qe.id").fetchall()


def _terms(conn, entry_id, answer):
    subjects = []
    for row in conn.execute(
            "SELECT DISTINCT sn.id, sn.name FROM entry_subject_mappings esm "
            "JOIN subject_nodes sn ON sn.id = esm.subject_node_id "
            "WHERE esm.question_entry_id = ? AND sn.status = 'active' "
            "ORDER BY CASE esm.mapping_type WHEN 'primary' THEN 0 ELSE 1 END, sn.name",
            (entry_id,)):
        aliases = [r["alias_name"] for r in conn.execute(
            "SELECT alias_name FROM subject_aliases WHERE subject_node_id = ? "
            "ORDER BY alias_name", (row["id"],))]
        subjects.append({"id": row["id"], "name": row["name"], "aliases": aliases})
    return {"subjects": subjects, "answer": answer or None}


def _cards(conn, match_id):
    cards = []
    for card in conn.execute(
            "SELECT c.card_id, c.note_id FROM anki_match_cards mc "
            "JOIN anki_cards c ON c.card_id = mc.card_id WHERE mc.match_id = ? "
            "ORDER BY c.note_id, c.card_ord, c.card_id", (match_id,)):
        fields = [{"text": field_to_text(r["field_value"] or "").text, "visible": True}
                  for r in conn.execute(
                      "SELECT field_value FROM anki_note_fields WHERE note_id = ? "
                      "ORDER BY field_order, field_name", (card["note_id"],))]
        cards.append({"card_id": card["card_id"], "fields": fields})
    return cards


def measure(path: Path, *, sample: int = 15, show_text: bool = True, out=print) -> dict:
    conn = _copy_read_only(path)
    try:
        if not _has_tables(conn, "anki_question_matches", "anki_card_verdicts"):
            raise SystemExit("This profile has no Anki tables at m035 yet; open it once in a "
                             "WIMI that includes #784 Wave 5, then fetch some cards.")
        stats = {"entries_with_cards": 0, "entries_with_several_cards": 0,
                 "with_proposals": 0, "with_no_subjects": 0,
                 "all_cards_proposed": 0, "cards_in_multi": 0, "proposals": 0}
        shown = 0
        for entry in _entries(conn):
            cards = _cards(conn, entry["match_id"])
            if not cards:
                continue
            stats["entries_with_cards"] += 1
            if len(cards) < 2:
                continue
            stats["entries_with_several_cards"] += 1
            stats["cards_in_multi"] += len(cards)
            terms = _terms(conn, entry["entry_id"], entry["correct_answer"])
            if not terms["subjects"]:
                stats["with_no_subjects"] += 1
            verdicts = {r["card_id"]: r["verdict"] for r in conn.execute(
                "SELECT card_id, verdict FROM anki_card_verdicts WHERE question_entry_id = ?",
                (entry["entry_id"],))}
            ids = [s["id"] for s in terms["subjects"]]
            rejected = {(r["subject_node_id"], r["card_id"]) for r in conn.execute(
                "SELECT subject_node_id, card_id FROM anki_card_subject_rejections "
                f"WHERE subject_node_id IN ({','.join('?' * len(ids)) or 'NULL'})", tuple(ids))}
            proposals = proposals_for(terms, cards, verdicts, rejected)
            if proposals:
                stats["with_proposals"] += 1
                stats["proposals"] += len(proposals)
                if len(proposals) == len(cards):
                    stats["all_cards_proposed"] += 1
            if shown < sample:
                shown += 1
                _print_entry(out, entry, cards, proposals, show_text)
    finally:
        conn.close()
    _print_summary(out, stats)
    return stats


def _print_entry(out, entry, cards, proposals, show_text):
    by_card = {p["card_id"]: p for p in proposals}
    out(f"\nEntry {entry['entry_id']}, question {entry['question_id']}: "
        f"{len(cards)} cards, {len(proposals)} proposed")
    for card in cards:
        mark = "PROPOSED" if card["card_id"] in by_card else "        "
        text = ""
        if show_text:
            first = next((f["text"] for f in card["fields"] if f["text"]), "")
            first = " ".join(first.split())
            text = "  " + (first[:SNIPPET] + "..." if len(first) > SNIPPET else first)
        out(f"  [{mark}] card {card['card_id']}{text}")
        if card["card_id"] in by_card:
            words = ", ".join(f"{r['text']} ({r['kind']})" for r in by_card[card["card_id"]]["reasons"])
            out(f"             matched: {words}")
    out("  Your pick:  (which card ids are about this mistake?)")


def _print_summary(out, s):
    multi = s["entries_with_several_cards"]
    out("\nSummary")
    out(f"  entries with fetched cards:          {s['entries_with_cards']}")
    out(f"  ... with two or more cards:          {multi}")
    if multi:
        out(f"  ... average cards each:              {s['cards_in_multi'] / multi:.1f}")
        out(f"  ... with at least one proposal:      {s['with_proposals']}")
        out(f"  ... where every card was proposed:   {s['all_cards_proposed']}")
        out(f"  ... with no subjects to match:       {s['with_no_subjects']}")
        out(f"  proposals in total:                  {s['proposals']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("profile", type=Path, help="the profile's user_NNN_name.db file")
    parser.add_argument("--sample", type=int, default=15,
                        help="how many several-card entries to print (default 15)")
    parser.add_argument("--no-text", action="store_true", help="leave card text out")
    args = parser.parse_args(argv)
    if not args.profile.is_file():
        parser.error(f"no such file: {args.profile}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    measure(args.profile, sample=args.sample, show_text=not args.no_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
