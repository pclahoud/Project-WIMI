"""AnkiMixin: templates, matches, the card cache and its sweep (#784 Wave 0).

Several tests here are about a defect in the plugin this replaces, and each
says which plan finding it guards:

* finding 1 -- a failed fetch wiped the cache. Here a failure never reaches the
  domain, and an *empty* answer is recorded as what it is without touching any
  other question's cards.
* finding 2 -- the cache keyed on question id text alone, so the same id in two
  exams shared one row, and one question's refresh deleted a card another
  question still referenced.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database.domains import anki as anki_domain
from database.exceptions import AnkiDataError, ValidationError
from database.user_db import UserDatabase

TPL = "tag:Bank::{{qid}}"


@pytest.fixture
def db(tmp_path):
    instance = UserDatabase(tmp_path / "anki.db", user_id=1, username="anki_user")
    yield instance
    try:
        instance.close()
    except Exception:
        pass


@pytest.fixture
def exam(db):
    return db.create_exam_context(exam_name="Step X")


@pytest.fixture
def bank(db, exam):
    return db.create_question_source(source_name="Bank A", exam_context=exam.exam_name)


def _entry(db, exam, bank, qid="101", **kw):
    session = db.create_review_session(exam_context_id=exam.id, total_questions=10,
                                       total_incorrect=3, question_source_id=bank.id if bank else None)
    return db.create_question_entry(session.id, "A", "B", question_id=qid, **kw)


def _card(card_id, note_id, *, model="Basic", queue=0, fields=None, **extra):
    card = {"cardId": card_id, "note": note_id, "deckName": "Deck", "modelName": model,
            "interval": 3, "due": 100, "reps": 4, "lapses": 1, "queue": queue, "type": 2,
            "ord": 0, "fields": fields if fields is not None else
            {"Front": {"value": f"<b>front {note_id}</b>", "order": 0},
             "Back": {"value": "back", "order": 1}}}
    card.update(extra)
    return card


def _key(exam, bank, qid="101"):
    return {"exam_context_id": exam.id, "question_source_id": bank.id, "question_id": qid}


def _count(db, table):
    return db.fetchone(f"SELECT COUNT(*) AS n FROM {table}")["n"]


# ------------------------------------------------------------------ templates

class TestTemplates:
    def test_add_list_update_remove(self, db, exam, bank):
        t = db.anki_add_template(exam.id, bank.id, "  " + TPL + "  ")
        assert t["template"] == TPL and t["source_name"] == "Bank A"
        assert [x["id"] for x in db.anki_get_templates(exam.id)] == [t["id"]]
        assert db.anki_templates_for(exam.id, bank.id) == [TPL]
        u = db.anki_update_template(t["id"], "deck:D note:{{qid}}")
        assert u["template"] == "deck:D note:{{qid}}"
        assert db.anki_remove_template(t["id"]) is True
        assert db.anki_get_templates() == []

    @pytest.mark.parametrize("template, fragment", [
        ("", "cannot be empty"),
        ("   ", "cannot be empty"),
        ("deck:Step2", "{{qid}}"),
        ("x{{qid}}" + "y" * 1000, "at most 1000"),
    ])
    def test_a_bad_template_is_refused_with_a_sentence(self, db, exam, bank, template, fragment):
        with pytest.raises(AnkiDataError, match=fragment.replace("{", r"\{").replace("}", r"\}")):
            db.anki_add_template(exam.id, bank.id, template)

    def test_a_duplicate_is_a_sentence_not_an_integrity_error(self, db, exam, bank):
        db.anki_add_template(exam.id, bank.id, TPL)
        with pytest.raises(AnkiDataError, match="already"):
            db.anki_add_template(exam.id, bank.id, TPL)
        other = db.anki_add_template(exam.id, bank.id, "deck:x {{qid}}")
        with pytest.raises(AnkiDataError, match="already"):
            db.anki_update_template(other["id"], TPL)

    def test_a_bank_is_required(self, db, exam):
        with pytest.raises(AnkiDataError, match="question bank"):
            db.anki_add_template(exam.id, None, TPL)

    def test_a_bank_of_another_exam_is_refused(self, db, exam):
        db.create_exam_context(exam_name="Other")
        foreign = db.create_question_source(source_name="Theirs", exam_context="Other")
        with pytest.raises(AnkiDataError, match="different exam"):
            db.anki_add_template(exam.id, foreign.id, TPL)

    def test_a_bank_with_no_exam_serves_every_exam(self, db, exam):
        shared = db.create_question_source(source_name="Shared")
        assert db.anki_add_template(exam.id, shared.id, TPL)["id"]

    def test_another_profiles_exam_is_refused(self, db, bank):
        foreign = db.execute(
            "INSERT INTO exam_contexts (user_id, exam_name) VALUES (2, 'Not mine')").lastrowid
        with pytest.raises(AnkiDataError, match="not one of this profile"):
            db.anki_add_template(foreign, bank.id, TPL)

    def test_the_placeholder_agrees_with_the_client(self):
        from app.anki.client import QID_PLACEHOLDER
        assert anki_domain.QID_PLACEHOLDER == QID_PLACEHOLDER


# ------------------------------------------------------- entry -> question key

class TestQuestionKeys:
    def test_an_entry_resolves_to_exam_bank_and_qid(self, db, exam, bank):
        entry = _entry(db, exam, bank, qid="  77 ")
        assert db.anki_question_key_for_entry(entry.id) == {
            "entry_id": entry.id, "exam_context_id": exam.id,
            "question_source_id": bank.id, "question_id": "77"}

    def test_a_session_without_a_bank_is_a_sentence(self, db, exam):
        entry = _entry(db, exam, None)
        with pytest.raises(AnkiDataError, match="no question bank"):
            db.anki_question_key_for_entry(entry.id)

    def test_an_entry_without_a_qid_is_a_sentence(self, db, exam, bank):
        entry = _entry(db, exam, bank, qid=None)
        with pytest.raises(AnkiDataError, match="no question id"):
            db.anki_question_key_for_entry(entry.id)

    def test_exam_keys_include_drafts_and_skip_banks_without_templates(self, db, exam, bank):
        """#12: a draft is the entry a student most wants cards for."""
        bare = db.create_question_source(source_name="No template", exam_context=exam.exam_name)
        db.anki_add_template(exam.id, bank.id, TPL)
        draft = _entry(db, exam, bank, qid="5")
        assert db.fetchone("SELECT is_draft FROM question_entries WHERE id = ?",
                           (draft.id,))["is_draft"], "the premise: this entry is a draft"
        _entry(db, exam, bank, qid="5")          # re-logged: one key, not two
        _entry(db, exam, bank, qid="6")
        _entry(db, exam, bare, qid="7")
        keys = db.anki_question_keys_for_exam(exam.id)
        assert [(k["question_source_id"], k["question_id"]) for k in keys] == \
            [(bank.id, "5"), (bank.id, "6")]


# ------------------------------------------------------------ the card cache

class TestRecording:
    def test_a_refresh_records_cards_reviews_and_fields(self, db, exam, bank):
        reviews = {1: [{"id": 10, "ease": 3, "ivl": 1, "lastIvl": 0, "factor": 2500,
                        "time": 5000, "type": 0},
                       {"id": 20, "ease": 3, "ivl": 4, "lastIvl": 1, "factor": 2500,
                        "time": 4000, "type": 1}]}
        result = db.anki_record_refresh(_key(exam, bank), cards=[_card(1, 50), _card(2, 50)],
                                        reviews=reviews, synced_at="2026-10-12T10:00:00Z")
        assert result["card_count"] == 2
        entry = _entry(db, exam, bank)
        cache = db.anki_get_entry_cache(entry.id)
        assert cache["match"]["last_synced_at"] == "2026-10-12T10:00:00Z"
        assert [c["card_id"] for c in cache["cards"]] == [1, 2]
        assert [r["review_id_ms"] for r in cache["cards"][0]["reviews"]] == [10, 20]
        assert [f["field_name"] for f in cache["cards"][0]["fields"]] == ["Front", "Back"]
        # The value is stored as Anki returned it: untrusted HTML, rendered by nobody here.
        assert cache["cards"][0]["fields"][0]["field_value"] == "<b>front 50</b>"
        # Fields belong to the note: two cards of one note store them once.
        assert _count(db, "anki_note_fields") == 2

    def test_a_card_answered_without_fields_does_not_blank_its_siblings(self, db, exam, bank):
        """Every card of a note carries its fields; whichever card has them wins."""
        db.anki_record_refresh(_key(exam, bank), reviews={},
                               cards=[_card(1, 50), _card(2, 50, fields={})])
        assert _count(db, "anki_note_fields") == 2

    def test_the_full_log_is_replaced_not_appended(self, db, exam, bank):
        key = _key(exam, bank)
        db.anki_record_refresh(key, cards=[_card(1, 50)],
                               reviews={1: [{"id": 10}, {"id": 20}]})
        db.anki_record_refresh(key, cards=[_card(1, 50)],
                               reviews={1: [{"id": 20}, {"id": 30}]})
        rows = db.fetchall("SELECT review_id_ms FROM anki_reviews ORDER BY review_id_ms")
        assert [r["review_id_ms"] for r in rows] == [20, 30]

    def test_finding_2_the_same_qid_in_two_exams_is_two_matches(self, db, exam, bank):
        other_exam = db.create_exam_context(exam_name="Other")
        shared = db.create_question_source(source_name="Shared")
        db.anki_record_refresh(_key(exam, shared, "1"), cards=[_card(11, 1)], reviews={})
        db.anki_record_refresh(_key(other_exam, shared, "1"), cards=[_card(22, 2)], reviews={})
        a = db.anki_get_match(_key(exam, shared, "1"))
        b = db.anki_get_match(_key(other_exam, shared, "1"))
        assert a["id"] != b["id"]
        ids = lambda m: [r["card_id"] for r in db.fetchall(
            "SELECT card_id FROM anki_match_cards WHERE match_id = ?", (m["id"],))]
        assert ids(a) == [11] and ids(b) == [22]

    def test_finding_2_a_shared_card_survives_the_other_questions_refresh(self, db, exam, bank):
        db.anki_record_refresh(_key(exam, bank, "1"), cards=[_card(7, 70)],
                               reviews={7: [{"id": 1}]})
        db.anki_record_refresh(_key(exam, bank, "2"), cards=[_card(7, 70)],
                               reviews={7: [{"id": 1}]})
        # Question 1 is refreshed and no longer finds card 7.
        db.anki_record_refresh(_key(exam, bank, "1"), cards=[], reviews={})
        assert _count(db, "anki_cards") == 1
        assert _count(db, "anki_reviews") == 1
        assert _count(db, "anki_note_fields") == 2

    def test_an_orphaned_card_is_swept_with_its_reviews_and_fields(self, db, exam, bank):
        key = _key(exam, bank)
        db.anki_record_refresh(key, cards=[_card(7, 70)], reviews={7: [{"id": 1}]})
        db.anki_record_refresh(key, cards=[], reviews={})
        assert (_count(db, "anki_cards"), _count(db, "anki_reviews"),
                _count(db, "anki_note_fields")) == (0, 0, 0)

    def test_finding_1_an_empty_answer_is_recorded_and_touches_no_other_question(
            self, db, exam, bank):
        db.anki_record_refresh(_key(exam, bank, "1"), cards=[_card(7, 70)], reviews={})
        db.anki_record_refresh(_key(exam, bank, "2"), cards=[], reviews={},
                               synced_at="2026-10-12T11:00:00Z")
        empty = db.anki_get_match(_key(exam, bank, "2"))
        assert empty["last_synced_at"] == "2026-10-12T11:00:00Z"
        assert _count(db, "anki_cards") == 1, "question 1's card is untouched"

    def test_a_vanished_card_is_skipped(self, db, exam, bank):
        """AnkiConnect answers {} for a card deleted between findCards and cardsInfo."""
        result = db.anki_record_refresh(_key(exam, bank), cards=[{}, _card(3, 30)], reviews={})
        assert result["card_count"] == 1

    def test_a_refresh_for_another_profiles_exam_is_refused(self, db, bank):
        foreign = db.execute(
            "INSERT INTO exam_contexts (user_id, exam_name) VALUES (2, 'Not mine')").lastrowid
        with pytest.raises(AnkiDataError):
            db.anki_record_refresh({"exam_context_id": foreign, "question_source_id": bank.id,
                                    "question_id": "1"}, cards=[], reviews={})

    def test_deleting_the_exam_takes_its_matches(self, db, exam, bank):
        db.anki_add_template(exam.id, bank.id, TPL)
        db.anki_record_refresh(_key(exam, bank), cards=[_card(1, 10)], reviews={})
        with db.transaction():  # hard delete requires a suspended exam
            db.execute("UPDATE exam_contexts SET is_active = 0 WHERE id = ?", (exam.id,))
        db.hard_delete_exam_context(exam.id)
        assert _count(db, "anki_search_templates") == 0
        assert _count(db, "anki_question_matches") == 0
        assert _count(db, "anki_match_cards") == 0

    def test_a_deleted_exams_note_types_are_not_listed(self, db, exam, bank):
        """#797 note 2: the cards linger until the next refresh's sweep, and the
        read-time filter keeps their note types out of Settings meanwhile."""
        db.anki_record_refresh(_key(exam, bank), cards=[_card(1, 10)], reviews={})
        assert db.anki_get_note_types() != {}
        with db.transaction():
            db.execute("UPDATE exam_contexts SET is_active = 0 WHERE id = ?", (exam.id,))
        db.hard_delete_exam_context(exam.id)
        assert db.anki_get_note_types() == {}

    def test_restored_queues_come_from_anki_or_the_card_type(self, db, exam, bank):
        cards = [dict(_card(1, 10), type=2), dict(_card(2, 10), type=3),
                 dict(_card(3, 10), type=2)]
        db.anki_record_refresh(_key(exam, bank), cards=cards, reviews={})
        db.anki_set_card_queue([1, 2, 3], -1)
        assert db.anki_restore_card_queues([1, 2, 3, 999], {3: 1}) == 3
        queues = {r["card_id"]: r["queue"]
                  for r in db.fetchall("SELECT card_id, queue FROM anki_cards")}
        assert queues == {1: 2, 2: 1, 3: 1}

    def test_suspension_is_mirrored_and_ids_come_from_the_match(self, db, exam, bank):
        entry = _entry(db, exam, bank)
        db.anki_record_refresh(_key(exam, bank), cards=[_card(1, 10), _card(2, 10)], reviews={})
        assert db.anki_entry_card_ids(entry.id) == [1, 2]
        assert db.anki_set_card_queue([1, 999], -1) == 1
        assert db.fetchone("SELECT queue FROM anki_cards WHERE card_id = 1")["queue"] == -1
        assert db.anki_set_card_queue([], -1) == 0

    def test_an_unsynced_entry_has_a_key_and_no_match(self, db, exam, bank):
        db.anki_add_template(exam.id, bank.id, TPL)
        cache = db.anki_get_entry_cache(_entry(db, exam, bank).id)
        assert cache["match"] is None and cache["cards"] == []
        assert cache["templates"] == [TPL]


# --------------------------------------------------------------- staleness

class TestStaleness:
    NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

    def _match(self, minutes_ago):
        stamp = (self.NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"last_synced_at": stamp}

    def test_never_synced_is_stale(self, db):
        assert db.anki_match_is_stale(None, self.NOW) is True

    def test_the_default_interval_is_sixty_minutes(self, db):
        assert db.anki_match_is_stale(self._match(59), self.NOW) is False
        assert db.anki_match_is_stale(self._match(60), self.NOW) is True

    def test_manual_only_is_never_stale_once_synced(self, db):
        db.update_preferences(anki_auto_refresh=False)
        assert db.anki_match_is_stale(self._match(10_000), self.NOW) is False
        assert db.anki_match_is_stale(None, self.NOW) is True

    def test_the_interval_is_the_students(self, db):
        db.update_preferences(anki_cache_refresh_interval_minutes=5)
        assert db.anki_match_is_stale(self._match(6), self.NOW) is True


# ------------------------------------------------------- field visibility

class TestFieldVisibility:
    def test_note_types_come_from_the_cache_in_ankis_order(self, db, exam, bank):
        db.anki_record_refresh(_key(exam, bank), cards=[_card(1, 10, model="Cloze", fields={
            "Text": {"value": "t", "order": 0}, "Extra": {"value": "e", "order": 1}})],
            reviews={})
        assert db.anki_get_note_types() == {"Cloze": ["Text", "Extra"]}

    def test_set_and_read(self, db):
        db.anki_set_field_visibility("Basic", "Back", False)
        db.anki_set_field_visibility("Basic", "Back", True)
        db.anki_set_field_visibility("Basic", "Front", False)
        assert db.anki_get_field_visibility() == {"Basic": {"Back": True, "Front": False}}

    @pytest.mark.parametrize("args", [("", "F", True), ("M", " ", True), ("M", "F", 1)])
    def test_refusals(self, db, args):
        with pytest.raises(AnkiDataError):
            db.anki_set_field_visibility(*args)


# ------------------------------------------------------------- settings

class TestSettings:
    def test_preferences_round_trip_through_the_flat_settings(self, db):
        db.update_settings(anki_display_mode="note", anki_auto_refresh=False,
                           anki_cache_refresh_interval_minutes=360)
        merged = db.get_all_settings()
        assert (merged["anki_display_mode"], merged["anki_auto_refresh"],
                merged["anki_cache_refresh_interval_minutes"]) == ("note", False, 360)

    @pytest.mark.parametrize("field, value", [("anki_display_mode", "grid"),
                                              ("anki_cache_refresh_interval_minutes", 0)])
    def test_preference_validation(self, db, field, value):
        with pytest.raises(ValidationError):
            db.update_preferences(**{field: value})

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
    def test_a_loopback_host_is_accepted(self, db, host):
        assert db.update_device_settings(ankiconnect_host=host).ankiconnect_host == host

    @pytest.mark.parametrize("host", ["203.0.113.5", "anki.example.com", "::1", ""])
    def test_decision_4_any_other_host_is_refused(self, db, host):
        with pytest.raises(ValidationError, match="this computer"):
            db.update_device_settings(ankiconnect_host=host)

    def test_797_note_3_no_host_is_refused_as_empty_not_as_remote(self, db):
        with pytest.raises(ValidationError, match="cannot be empty"):
            db.update_device_settings(ankiconnect_host=None)


def test_every_anki_write_path_survives_a_real_logger(tmp_path):
    """Every fixture above has ``error_logger=None``, so a guarded log call is
    never executed; CLAUDE.md's logging invariant 2 and
    ``test_relation_confirmation`` say why that has bitten before."""
    from app_logging import ErrorLogger
    from database.master_db import MasterDatabase

    logger = ErrorLogger(app_name="AnkiWriteTest", log_dir=tmp_path / "logs",
                         flush_interval=60.0)
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=logger)
    user = master.create_user(username="logged", display_name="L", user_types=["student"])
    db = UserDatabase(db_path=master.ensure_user_database(user.id), user_id=user.id,
                      username=user.username, error_logger=logger)
    try:
        assert db.error_logger is not None, "the premise of this test"
        exam = db.create_exam_context("Logged")
        bank = db.create_question_source(source_name="B", exam_context=exam.exam_name)
        t = db.anki_add_template(exam.id, bank.id, TPL)
        db.anki_update_template(t["id"], "deck:x {{qid}}")
        db.anki_record_refresh(_key(exam, bank), cards=[_card(1, 10)], reviews={1: [{"id": 5}]})
        db.anki_set_card_queue([1], -1)
        db.anki_set_field_visibility("Basic", "Front", False)
        db.anki_remove_template(t["id"])
    finally:
        db.close()
        master.close()
        logger.cleanup(wait=False)


# ----------------------------------------------------------- relevance (m035)

def _tagged_entry(db, exam, bank, *names, qid="101"):
    subjects = [db.create_subject_node(exam.exam_name, n, "System") for n in names]
    session = db.create_review_session(exam_context_id=exam.id, total_questions=10,
                                       total_incorrect=3, question_source_id=bank.id)
    entry = db.create_question_entry(session.id, "A", "Beta blocker", question_id=qid,
                                     primary_subject_ids=[subjects[0].id],
                                     secondary_subject_ids=[s.id for s in subjects[1:]])
    return entry, subjects


class TestRelevance:
    def test_terms_are_the_entrys_active_subjects_with_aliases_and_the_answer(
            self, db, exam, bank):
        entry, (aorta, mi) = _tagged_entry(db, exam, bank, "Aortic dissection", "MI")
        db.create_subject_alias(aorta.id, exam.exam_name, "Tearing aorta")
        terms = db.anki_relevance_terms(entry.id)
        assert [(s["name"], s["aliases"]) for s in terms["subjects"]] == [
            ("Aortic dissection", ["Tearing aorta"]), ("MI", [])]
        assert terms["answer"] == "Beta blocker"
        with db.transaction():
            db.execute("UPDATE subject_nodes SET status = 'archived' WHERE id = ?", (mi.id,))
        assert [s["name"] for s in db.anki_relevance_terms(entry.id)["subjects"]] == [
            "Aortic dissection"]

    def test_a_verdict_names_only_this_entrys_cards_and_can_be_cleared(self, db, exam, bank):
        entry, _ = _tagged_entry(db, exam, bank, "Aortic dissection")
        db.anki_record_refresh(_key(exam, bank), cards=[_card(1, 10), _card(2, 10)], reviews={})
        db.anki_set_verdict(entry.id, 1, "confirmed")
        db.anki_set_verdict(entry.id, 2, "not_for_entry")
        assert db.anki_get_verdicts(entry.id) == {1: "confirmed", 2: "not_for_entry"}
        db.anki_set_verdict(entry.id, 1, None)
        assert db.anki_get_verdicts(entry.id) == {2: "not_for_entry"}
        with pytest.raises(AnkiDataError, match="not this entry's"):
            db.anki_set_verdict(entry.id, 999, "confirmed")
        with pytest.raises(AnkiDataError):
            db.anki_set_verdict(entry.id, 1, "maybe")

    def test_rejecting_for_subjects_keeps_to_this_entrys_subjects(self, db, exam, bank):
        entry, (aorta,) = _tagged_entry(db, exam, bank, "Aortic dissection")
        stranger = db.create_subject_node(exam.exam_name, "Elsewhere", "System")
        db.anki_record_refresh(_key(exam, bank), cards=[_card(1, 10), _card(2, 10)], reviews={})
        assert db.anki_reject_for_subjects(entry.id, 1, [aorta.id, stranger.id]) == 1
        assert db.anki_subject_rejections([aorta.id, stranger.id]) == {(aorta.id, 1)}
        with pytest.raises(AnkiDataError, match="only be set aside for this entry"):
            db.anki_reject_for_subjects(entry.id, 2, [stranger.id])

    def test_another_profiles_entry_is_refused(self, db, exam, bank):
        foreign = db.execute(
            "INSERT INTO review_sessions (user_id, exam_context_id, date_encountered, "
            "total_questions, total_incorrect, question_source_id) "
            "VALUES (2, ?, '2026-10-14', 1, 1, ?)", (exam.id, bank.id)).lastrowid
        entry = db.execute(
            "INSERT INTO question_entries (review_session_id, entry_order, user_answer, "
            "correct_answer, question_id) VALUES (?, 1, 'A', 'B', '9')", (foreign,)).lastrowid
        with pytest.raises(AnkiDataError, match="not one of this profile's"):
            db.anki_relevance_terms(entry)
        with pytest.raises(AnkiDataError):
            db.anki_get_verdicts(entry)
