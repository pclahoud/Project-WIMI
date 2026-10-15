"""Anki domain mixin (#784 Wave 0).

Composed into :class:`UserDatabase`. Owns m034's ``anki_*`` tables: the
search templates, what each question matched in Anki, and the cached cards,
reviews and note fields. Plan: ``docs/planning/ANKI_INTEGRATION_IMPLEMENTATION_PLAN.md``
as amended by the owner's decisions on #784 comment #10774.

What this layer does and does not do
------------------------------------
It never talks to Anki. ``app.anki`` owns the connection and runs it on a
worker (#784 Wave 1); the bridge (Wave 2) reads what to ask for from here on
the main thread, hands plain data to the worker, and writes what came back
through :meth:`anki_record_refresh`, again on the main thread. So every method
here is an ordinary database read or a write in one transaction.

It also never decides what a *failed* fetch means. The plugin this replaces
treated "Anki did not answer" as "no cards" and wiped its cache (plan finding
1); here a failure never reaches this layer at all -- only a completed answer
is recorded, and an empty answer is recorded as what it is, a search that
found nothing.

Every method is prefixed ``anki_``: mixins share one namespace, and the
plugin's own names (``get_templates``, ``sync_exam``) would shadow or be
shadowed silently.

Scope
-----
No m034 table carries ``user_id`` (#776); a template and a match are scoped
through their exam, whose ``user_id`` is checked on every write that names
one. Cards, reviews and note fields belong to the profile database as a whole
and are reached only through a match.

Deleting an exam cascades its templates, matches and match-cards, **not** the
shared card, review and field rows, which are swept by the next refresh. Every
read reaches those rows through a live match, so the leftovers are invisible
in the meantime; they cost space until then, nothing else.

Untrusted content
-----------------
Field values are stored as Anki returned them -- HTML from a deck the student
may have downloaded. Nothing here renders them; the reader (Wave 2) turns a
value into text plus image filenames, and the page never sets one as HTML.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app_logging import ErrorCategory

from ..exceptions import AnkiDataError

#: A search template must hold this, or it would find the same cards for
#: every question. ``app.anki.client.QID_PLACEHOLDER`` is the same string;
#: this layer may not import ``app``, and a test asserts the two agree.
QID_PLACEHOLDER = "{{qid}}"

#: m034's CHECK on ``anki_search_templates.template``.
TEMPLATE_MAX_LENGTH = 1000


def _utc_now_iso() -> str:
    """A UTC instant with an explicit ``Z`` (#286: instants are UTC, and a
    naive ISO string is read as local time by ``new Date()``)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


class AnkiMixin:
    """Mixin for the Anki integration's data. Composed into UserDatabase."""

    # ------------------------------------------------------------------
    # Scope checks
    # ------------------------------------------------------------------

    def _anki_exam(self, exam_context_id: Any):
        if isinstance(exam_context_id, bool) or not isinstance(exam_context_id, int):
            raise AnkiDataError("Choose an exam")
        exam = self.get_exam_context_config(exam_context_id)
        if exam is None or exam.user_id != self.user_id:
            raise AnkiDataError(f"Exam {exam_context_id} is not one of this profile's exams")
        return exam

    def _anki_check_bank(self, question_source_id: Any, exam) -> None:
        """A bank is required (owner, #784 decision 7) and must fit the exam.

        ``question_sources`` names its exam by *name* (``exam_context``), not
        by id, and a bank with no exam name serves every exam -- the same rule
        the calendar applies (``CalendarMixin._calendar_source_fits_exam``).
        """
        if isinstance(question_source_id, bool) or not isinstance(question_source_id, int):
            raise AnkiDataError("Choose a question bank; a search template belongs to one")
        source = self.get_question_source(question_source_id)
        if source is None or source.user_id != self.user_id:
            raise AnkiDataError(f"Question bank {question_source_id} does not exist")
        if source.exam_context and source.exam_context != exam.exam_name:
            raise AnkiDataError(
                f"Question bank {question_source_id} belongs to a different exam")

    @staticmethod
    def _anki_clean_template(template: Any) -> str:
        if not isinstance(template, str) or not template.strip():
            raise AnkiDataError("A search template cannot be empty")
        text = template.strip()
        if len(text) > TEMPLATE_MAX_LENGTH:
            raise AnkiDataError(
                f"A search template is at most {TEMPLATE_MAX_LENGTH} characters")
        if QID_PLACEHOLDER not in text:
            raise AnkiDataError(
                f"A search template needs {QID_PLACEHOLDER} where the question id "
                "goes; without it every question would find the same cards")
        return text

    # ------------------------------------------------------------------
    # Search templates
    # ------------------------------------------------------------------

    def anki_get_templates(self, exam_context_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """This profile's templates with their bank's name, oldest first."""
        sql = (
            "SELECT t.id, t.exam_context_id, t.question_source_id, t.template, "
            "t.created_at, t.updated_at, s.source_name "
            "FROM anki_search_templates t "
            "JOIN exam_contexts e ON e.id = t.exam_context_id "
            "JOIN question_sources s ON s.id = t.question_source_id "
            "WHERE e.user_id = ?"
        )
        params: List[Any] = [self.user_id]
        if exam_context_id is not None:
            sql += " AND t.exam_context_id = ?"
            params.append(exam_context_id)
        sql += " ORDER BY t.exam_context_id, s.source_name, t.id"
        return [dict(r) for r in self.fetchall(sql, tuple(params))]

    def anki_get_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        row = self.fetchone(
            "SELECT t.*, s.source_name FROM anki_search_templates t "
            "JOIN exam_contexts e ON e.id = t.exam_context_id "
            "JOIN question_sources s ON s.id = t.question_source_id "
            "WHERE t.id = ? AND e.user_id = ?",
            (template_id, self.user_id))
        return dict(row) if row else None

    def anki_add_template(self, exam_context_id: int, question_source_id: int,
                          template: str) -> Dict[str, Any]:
        exam = self._anki_exam(exam_context_id)
        self._anki_check_bank(question_source_id, exam)
        text = self._anki_clean_template(template)
        if self.fetchone(
                "SELECT id FROM anki_search_templates WHERE exam_context_id = ? "
                "AND question_source_id = ? AND template = ?",
                (exam_context_id, question_source_id, text)):
            raise AnkiDataError("That search template is already on this question bank")
        with self.transaction():
            cur = self.execute(
                "INSERT INTO anki_search_templates (exam_context_id, question_source_id, template) "
                "VALUES (?, ?, ?)", (exam_context_id, question_source_id, text))
            new_id = cur.lastrowid
        if self.error_logger:
            self.error_logger.info(f"Anki search template {new_id} added",
                                   category=ErrorCategory.ANKI)
        return self.anki_get_template(new_id)

    def anki_update_template(self, template_id: int, template: str) -> Dict[str, Any]:
        current = self.anki_get_template(template_id)
        if current is None:
            raise AnkiDataError(f"Search template {template_id} does not exist")
        text = self._anki_clean_template(template)
        if text == current["template"]:
            return current
        if self.fetchone(
                "SELECT id FROM anki_search_templates WHERE exam_context_id = ? "
                "AND question_source_id = ? AND template = ? AND id != ?",
                (current["exam_context_id"], current["question_source_id"], text, template_id)):
            raise AnkiDataError("That search template is already on this question bank")
        with self.transaction():
            self.execute(
                "UPDATE anki_search_templates SET template = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?", (text, template_id))
        return self.anki_get_template(template_id)

    def anki_remove_template(self, template_id: int) -> bool:
        if self.anki_get_template(template_id) is None:
            raise AnkiDataError(f"Search template {template_id} does not exist")
        with self.transaction():
            self.execute("DELETE FROM anki_search_templates WHERE id = ?", (template_id,))
        return True

    def anki_templates_for(self, exam_context_id: int, question_source_id: int) -> List[str]:
        """The template strings for one (exam, bank), oldest first."""
        rows = self.fetchall(
            "SELECT t.template FROM anki_search_templates t "
            "JOIN exam_contexts e ON e.id = t.exam_context_id "
            "WHERE t.exam_context_id = ? AND t.question_source_id = ? AND e.user_id = ? "
            "ORDER BY t.id",
            (exam_context_id, question_source_id, self.user_id))
        return [r["template"] for r in rows]

    # ------------------------------------------------------------------
    # From an entry to what Anki is asked about
    # ------------------------------------------------------------------

    def anki_question_key_for_entry(self, entry_id: int) -> Dict[str, Any]:
        """``{entry_id, exam_context_id, question_source_id, question_id}``.

        Refuses with a sentence when the entry cannot be matched: it is not
        this profile's, its session has no question bank, or it has no
        question id. The plugin crashed on the second (``source`` is ``None``
        in ``get_entry_with_context`` for a session with no bank).
        """
        row = self.fetchone(
            "SELECT qe.id AS entry_id, qe.question_id, rs.exam_context_id, "
            "rs.question_source_id FROM question_entries qe "
            "JOIN review_sessions rs ON rs.id = qe.review_session_id "
            "WHERE qe.id = ? AND rs.user_id = ?",
            (entry_id, self.user_id))
        if row is None:
            raise AnkiDataError(f"Entry {entry_id} is not one of this profile's entries")
        if row["question_source_id"] is None:
            raise AnkiDataError("This entry's session has no question bank, so it has no "
                                "search template to look its cards up with")
        qid = (row["question_id"] or "").strip()
        if not qid:
            raise AnkiDataError("This entry has no question id to search Anki for")
        return {
            "entry_id": row["entry_id"],
            "exam_context_id": row["exam_context_id"],
            "question_source_id": row["question_source_id"],
            "question_id": qid,
        }

    def anki_question_keys_for_exam(self, exam_context_id: int) -> List[Dict[str, Any]]:
        """Every distinct (bank, question id) logged in an exam, drafts included.

        Drafts count (#12): a draft is the entry a student most wants cards
        for. Only banks that have at least one template are returned, because
        a question with nothing to search with cannot be synced.
        """
        self._anki_exam(exam_context_id)
        rows = self.fetchall(
            "SELECT DISTINCT rs.question_source_id, TRIM(qe.question_id) AS question_id "
            "FROM question_entries qe "
            "JOIN review_sessions rs ON rs.id = qe.review_session_id "
            "WHERE rs.exam_context_id = ? AND rs.user_id = ? "
            "AND rs.question_source_id IS NOT NULL "
            "AND qe.question_id IS NOT NULL AND TRIM(qe.question_id) != '' "
            "AND EXISTS (SELECT 1 FROM anki_search_templates t "
            "            WHERE t.exam_context_id = rs.exam_context_id "
            "            AND t.question_source_id = rs.question_source_id) "
            "ORDER BY rs.question_source_id, question_id",
            (exam_context_id, self.user_id))
        return [{"exam_context_id": exam_context_id,
                 "question_source_id": r["question_source_id"],
                 "question_id": r["question_id"]} for r in rows]

    # ------------------------------------------------------------------
    # Recording what Anki answered
    # ------------------------------------------------------------------

    def anki_record_refresh(self, key: Mapping[str, Any], *, cards: Iterable[Mapping[str, Any]],
                            reviews: Mapping[int, Iterable[Mapping[str, Any]]],
                            synced_at: Optional[str] = None) -> Dict[str, Any]:
        """Record one completed answer for one question, in one transaction.

        ``cards`` are AnkiConnect ``cardsInfo`` objects for every card the
        templates found -- possibly none, which is recorded as a search that
        found nothing. An empty ``{}`` (AnkiConnect's answer for a card that
        vanished between ``findCards`` and ``cardsInfo``) is skipped.
        ``reviews`` maps a card id to its ``getReviewsOfCards`` rows; each
        card's log is replaced whole, which is how the full log stays exact
        (owner, #784 decision 2).

        Called only with a completed answer. A failed fetch must not reach
        here; that is what keeps a closed Anki from looking like "no cards".
        """
        exam = self._anki_exam(key.get("exam_context_id"))
        self._anki_check_bank(key.get("question_source_id"), exam)
        question_id = str(key.get("question_id") or "").strip()
        if not question_id:
            raise AnkiDataError("A match needs a question id")
        stamp = synced_at or _utc_now_iso()

        kept: List[Mapping[str, Any]] = []
        for card in cards:
            card_id = _int_or_none(card.get("cardId"))
            note_id = _int_or_none(card.get("note"))
            if card_id is None or note_id is None:
                continue
            kept.append(card)

        with self.transaction():
            self.execute(
                "INSERT INTO anki_question_matches "
                "(exam_context_id, question_source_id, question_id, last_synced_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (exam_context_id, question_source_id, question_id) "
                "DO UPDATE SET last_synced_at = excluded.last_synced_at",
                (exam.id, key["question_source_id"], question_id, stamp))
            match_id = self.fetchone(
                "SELECT id FROM anki_question_matches WHERE exam_context_id = ? "
                "AND question_source_id = ? AND question_id = ?",
                (exam.id, key["question_source_id"], question_id))["id"]
            self.execute("DELETE FROM anki_match_cards WHERE match_id = ?", (match_id,))
            for card in kept:
                card_id = card["cardId"]
                self.execute(
                    "INSERT OR IGNORE INTO anki_match_cards (match_id, card_id) VALUES (?, ?)",
                    (match_id, card_id))
                self.execute(
                    "INSERT INTO anki_cards (card_id, note_id, deck_name, model_name, interval, "
                    "due, reps, lapses, queue, card_type, card_ord, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (card_id) DO UPDATE SET note_id = excluded.note_id, "
                    "deck_name = excluded.deck_name, model_name = excluded.model_name, "
                    "interval = excluded.interval, due = excluded.due, reps = excluded.reps, "
                    "lapses = excluded.lapses, queue = excluded.queue, "
                    "card_type = excluded.card_type, card_ord = excluded.card_ord, "
                    "fetched_at = excluded.fetched_at",
                    (card_id, card["note"], card.get("deckName"), card.get("modelName"),
                     _int_or_none(card.get("interval")), _int_or_none(card.get("due")),
                     _int_or_none(card.get("reps")), _int_or_none(card.get("lapses")),
                     _int_or_none(card.get("queue")), _int_or_none(card.get("type")),
                     _int_or_none(card.get("ord")), stamp))
                self.execute("DELETE FROM anki_reviews WHERE card_id = ?", (card_id,))
                for review in reviews.get(card_id, ()) or ():
                    review_id = _int_or_none(review.get("id"))
                    if review_id is None:
                        continue
                    self.execute(
                        "INSERT OR REPLACE INTO anki_reviews (card_id, review_id_ms, ease, ivl, "
                        "last_ivl, factor, time_ms, review_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (card_id, review_id, _int_or_none(review.get("ease")),
                         _int_or_none(review.get("ivl")), _int_or_none(review.get("lastIvl")),
                         _int_or_none(review.get("factor")), _int_or_none(review.get("time")),
                         _int_or_none(review.get("type"))))
            # Every card of a note carries the note's fields; take them from
            # the first card that has any, so one card answered without
            # fields cannot blank its siblings'.
            by_note: Dict[int, Mapping[str, Any]] = {}
            for c in kept:
                if c["note"] not in by_note or (
                        not by_note[c["note"]].get("fields") and c.get("fields")):
                    by_note[c["note"]] = c
            for note_id, card in by_note.items():
                fields = card.get("fields")
                if not isinstance(fields, Mapping) or not fields:
                    continue
                self.execute("DELETE FROM anki_note_fields WHERE note_id = ?", (note_id,))
                model = card.get("modelName") or ""
                for name, spec in fields.items():
                    value = spec.get("value") if isinstance(spec, Mapping) else None
                    order = spec.get("order") if isinstance(spec, Mapping) else None
                    self.execute(
                        "INSERT INTO anki_note_fields (note_id, field_name, model_name, "
                        "field_order, field_value) VALUES (?, ?, ?, ?, ?)",
                        (note_id, str(name), model, _int_or_none(order) or 0,
                         value if isinstance(value, str) else None))
            self._anki_sweep_orphans()
        return {"match_id": match_id, "card_count": len(kept), "last_synced_at": stamp}

    def _anki_sweep_orphans(self) -> None:
        """Drop cards no match references any more, then their reviews and
        their notes' fields. A card shared by two questions survives either
        one's refresh; the plugin deleted it (plan finding 2)."""
        self.execute(
            "DELETE FROM anki_cards WHERE card_id NOT IN (SELECT card_id FROM anki_match_cards)")
        self.execute(
            "DELETE FROM anki_reviews WHERE card_id NOT IN (SELECT card_id FROM anki_cards)")
        self.execute(
            "DELETE FROM anki_note_fields WHERE note_id NOT IN (SELECT note_id FROM anki_cards)")

    def anki_set_card_queue(self, card_ids: Iterable[int], queue: int) -> int:
        """Mirror a suspend (-1) or unsuspend (0) Anki accepted into the cache."""
        ids = [c for c in card_ids if _int_or_none(c) is not None]
        if not ids:
            return 0
        with self.transaction():
            cur = self.execute(
                f"UPDATE anki_cards SET queue = ? WHERE card_id IN ({','.join('?' * len(ids))})",
                (queue, *ids))
        return cur.rowcount

    def anki_restore_card_queues(self, card_ids: Iterable[int],
                                 queues: Mapping[int, int]) -> int:
        """Mirror an unsuspend Anki accepted. ``queues`` is what Anki reported
        afterwards; a card it did not report gets the queue Anki's own
        unsuspend restores from the card's type (relearning goes back to
        learning), rather than 0, which would show a review card as new."""
        ids = [c for c in card_ids if _int_or_none(c) is not None]
        if not ids:
            return 0
        changed = 0
        with self.transaction():
            for card_id in ids:
                queue = queues.get(card_id)
                if isinstance(queue, int) and not isinstance(queue, bool):
                    cur = self.execute("UPDATE anki_cards SET queue = ? WHERE card_id = ?",
                                       (queue, card_id))
                else:
                    cur = self.execute(
                        "UPDATE anki_cards SET queue = CASE card_type WHEN 3 THEN 1 "
                        "ELSE COALESCE(card_type, 0) END WHERE card_id = ?", (card_id,))
                changed += cur.rowcount
        return changed

    # ------------------------------------------------------------------
    # Reading the cache
    # ------------------------------------------------------------------

    def anki_get_match(self, key: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        row = self.fetchone(
            "SELECT m.* FROM anki_question_matches m "
            "JOIN exam_contexts e ON e.id = m.exam_context_id "
            "WHERE m.exam_context_id = ? AND m.question_source_id = ? AND m.question_id = ? "
            "AND e.user_id = ?",
            (key.get("exam_context_id"), key.get("question_source_id"),
             str(key.get("question_id") or "").strip(), self.user_id))
        return dict(row) if row else None

    def anki_get_entry_cache(self, entry_id: int) -> Dict[str, Any]:
        """What the cache holds for one entry: the match, its cards with their
        full review logs, and each card's note fields in Anki's order.

        Raw rows only. Turning a field into text, and a log into estimates, is
        the bridge's (``app.anki.fsrs``), because this layer may not import it.
        """
        key = self.anki_question_key_for_entry(entry_id)
        match = self.anki_get_match(key)
        result: Dict[str, Any] = {"key": key, "match": match, "cards": [],
                                  "templates": self.anki_templates_for(
                                      key["exam_context_id"], key["question_source_id"])}
        if match is None:
            return result
        cards = self.fetchall(
            "SELECT c.* FROM anki_match_cards mc JOIN anki_cards c ON c.card_id = mc.card_id "
            "WHERE mc.match_id = ? ORDER BY c.note_id, c.card_ord, c.card_id",
            (match["id"],))
        for card in cards:
            card = dict(card)
            card["reviews"] = [dict(r) for r in self.fetchall(
                "SELECT * FROM anki_reviews WHERE card_id = ? ORDER BY review_id_ms",
                (card["card_id"],))]
            card["fields"] = [dict(r) for r in self.fetchall(
                "SELECT field_name, field_order, field_value FROM anki_note_fields "
                "WHERE note_id = ? ORDER BY field_order, field_name", (card["note_id"],))]
            result["cards"].append(card)
        return result

    def anki_entry_card_ids(self, entry_id: int) -> List[int]:
        """The card ids this entry's match found: the only ids a suspend from
        this entry may name (plan: card ids validated against the match)."""
        key = self.anki_question_key_for_entry(entry_id)
        match = self.anki_get_match(key)
        if match is None:
            return []
        return [r["card_id"] for r in self.fetchall(
            "SELECT card_id FROM anki_match_cards WHERE match_id = ? ORDER BY card_id",
            (match["id"],))]

    def anki_match_is_stale(self, match: Optional[Mapping[str, Any]],
                            now: Optional[datetime] = None) -> bool:
        """Whether a match should be refreshed on sight.

        Never synced is always stale. With auto-refresh off ("manual only")
        nothing else is. Otherwise stale once older than the interval.
        """
        if not match:
            return True
        prefs = self.get_preferences()
        if not prefs.anki_auto_refresh:
            return False
        synced = _parse_utc(match.get("last_synced_at"))
        if synced is None:
            return True
        now = now or datetime.now(timezone.utc)
        return now - synced >= timedelta(minutes=prefs.anki_cache_refresh_interval_minutes)

    # ------------------------------------------------------------------
    # Which fields the panel shows
    # ------------------------------------------------------------------

    def anki_get_note_types(self) -> Dict[str, List[str]]:
        """Each cached note type and its fields in Anki's order."""
        out: Dict[str, List[str]] = {}
        # Only notes some match still reaches. Cards, reviews and fields are
        # swept on a refresh, not when an exam is deleted (its matches
        # cascade, the shared card rows do not), so without this filter a
        # deleted exam's note types would linger in Settings until the next
        # refresh anywhere. #797 review note 2.
        for row in self.fetchall(
                "SELECT f.model_name, f.field_name, MIN(f.field_order) AS ord "
                "FROM anki_note_fields f "
                "WHERE EXISTS (SELECT 1 FROM anki_cards c JOIN anki_match_cards mc "
                "              ON mc.card_id = c.card_id WHERE c.note_id = f.note_id) "
                "GROUP BY f.model_name, f.field_name "
                "ORDER BY f.model_name, ord, f.field_name"):
            out.setdefault(row["model_name"], []).append(row["field_name"])
        return out

    def anki_get_field_visibility(self) -> Dict[str, Dict[str, bool]]:
        out: Dict[str, Dict[str, bool]] = {}
        for row in self.fetchall(
                "SELECT model_name, field_name, visible FROM anki_field_visibility"):
            out.setdefault(row["model_name"], {})[row["field_name"]] = bool(row["visible"])
        return out

    def anki_set_field_visibility(self, model_name: str, field_name: str, visible: bool) -> None:
        if not isinstance(model_name, str) or not model_name.strip() \
                or not isinstance(field_name, str) or not field_name.strip():
            raise AnkiDataError("A field is named by its note type and its field name")
        if not isinstance(visible, bool):
            raise AnkiDataError("Visibility is shown or hidden")
        with self.transaction():
            self.execute(
                "INSERT INTO anki_field_visibility (model_name, field_name, visible) "
                "VALUES (?, ?, ?) ON CONFLICT (model_name, field_name) "
                "DO UPDATE SET visible = excluded.visible",
                (model_name, field_name, 1 if visible else 0))

    # ------------------------------------------------------------------
    # Relevance: what the scorer reads, and the student's verdicts (m035)
    # ------------------------------------------------------------------

    def anki_relevance_terms(self, entry_id: int) -> Dict[str, Any]:
        """The entry facts the lexical scorer matches against card text.

        ``subjects`` are the entry's active primary and secondary subjects,
        each with its ``subject_aliases``; ``answer`` is the stored correct
        answer, which is often only a choice letter -- the scorer decides
        whether it is words. Refuses an entry that is not this profile's.
        """
        self.anki_question_key_for_entry(entry_id)
        rows = self.fetchall(
            "SELECT DISTINCT sn.id, sn.name FROM entry_subject_mappings esm "
            "JOIN subject_nodes sn ON sn.id = esm.subject_node_id "
            "WHERE esm.question_entry_id = ? AND sn.status = 'active' "
            "ORDER BY CASE esm.mapping_type WHEN 'primary' THEN 0 ELSE 1 END, sn.name",
            (entry_id,))
        subjects = []
        for row in rows:
            aliases = [r["alias_name"] for r in self.fetchall(
                "SELECT alias_name FROM subject_aliases WHERE subject_node_id = ? "
                "ORDER BY alias_name", (row["id"],))]
            subjects.append({"id": row["id"], "name": row["name"], "aliases": aliases})
        answer = self.fetchone(
            "SELECT correct_answer FROM question_entries WHERE id = ?", (entry_id,))
        return {"subjects": subjects,
                "answer": (answer["correct_answer"] if answer else None) or None}

    def anki_get_verdicts(self, entry_id: int) -> Dict[int, str]:
        """``{card_id: 'confirmed' | 'not_for_entry'}`` for one entry."""
        self.anki_question_key_for_entry(entry_id)
        return {r["card_id"]: r["verdict"] for r in self.fetchall(
            "SELECT card_id, verdict FROM anki_card_verdicts WHERE question_entry_id = ?",
            (entry_id,))}

    def anki_subject_rejections(self, subject_ids: Iterable[int]) -> set:
        """``{(subject_id, card_id)}`` the student has said never to propose."""
        ids = [s for s in subject_ids if _int_or_none(s) is not None]
        if not ids:
            return set()
        return {(r["subject_node_id"], r["card_id"]) for r in self.fetchall(
            "SELECT subject_node_id, card_id FROM anki_card_subject_rejections "
            f"WHERE subject_node_id IN ({','.join('?' * len(ids))})", tuple(ids))}

    def anki_set_verdict(self, entry_id: int, card_id: int, verdict: Optional[str]) -> None:
        """Record, change or (``None``) clear one entry's verdict on one card.

        The card must be one this entry's match found, as for suspend: the
        page may only name this entry's cards.
        """
        if verdict not in ("confirmed", "not_for_entry", None):
            raise AnkiDataError("A card is shown first, set aside for this entry, or neither")
        if _int_or_none(card_id) is None or card_id not in self.anki_entry_card_ids(entry_id):
            raise AnkiDataError("That card is not this entry's; refresh the entry and try again")
        with self.transaction():
            if verdict is None:
                self.execute("DELETE FROM anki_card_verdicts "
                             "WHERE question_entry_id = ? AND card_id = ?", (entry_id, card_id))
            else:
                self.execute(
                    "INSERT INTO anki_card_verdicts (question_entry_id, card_id, verdict, "
                    "decided_at) VALUES (?, ?, ?, ?) ON CONFLICT (question_entry_id, card_id) "
                    "DO UPDATE SET verdict = excluded.verdict, decided_at = excluded.decided_at",
                    (entry_id, card_id, verdict, _utc_now_iso()))

    def anki_reject_for_subjects(self, entry_id: int, card_id: int,
                                 subject_ids: Iterable[int]) -> int:
        """Never propose ``card_id`` on the strength of these subjects again.

        Each subject must be one of this entry's, so a rejection cannot reach a
        subject the student was not looking at.
        """
        if _int_or_none(card_id) is None or card_id not in self.anki_entry_card_ids(entry_id):
            raise AnkiDataError("That card is not this entry's; refresh the entry and try again")
        own = {s["id"] for s in self.anki_relevance_terms(entry_id)["subjects"]}
        ids = [s for s in subject_ids if s in own]
        if not ids:
            raise AnkiDataError("Only the answer text matched this card, so it can only be "
                                "set aside for this entry")
        stamp = _utc_now_iso()
        with self.transaction():
            for subject_id in ids:
                self.execute(
                    "INSERT OR IGNORE INTO anki_card_subject_rejections "
                    "(subject_node_id, card_id, decided_at) VALUES (?, ?, ?)",
                    (subject_id, card_id, stamp))
        return len(ids)
