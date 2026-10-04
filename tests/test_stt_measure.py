"""Tests for ``scripts/stt_measure.py``, the #59 T3 measurement harness.

The scorer being wrong is the one failure that would silently waste the
measurement: the owner records the corpus once, in their own voice, and a
number that came out of a broken scorer looks exactly like a number that came
out of a working one.  So the arithmetic is pinned against hand-computed cases
here, not checked by eye at the microphone.

Three groups:

* **the scorer** -- WER against a hand-counted edit distance, term recall,
  term precision (the invented-term detector), and the normalisation rules the
  corpus file declares;
* **the corpus** -- that the shipped fixture describes itself consistently, and
  that every priming term really does come from the published USMLE outline
  rather than from the answer key;
* **the read-aloud script** -- that the generated copy is in sync, the same
  shape of gate as ``scripts/check_import_guide_sync.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "stt_measure.py"
CORPUS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "stt_vocabulary_terms.json"
SCRIPT_MD_PATH = PROJECT_ROOT / "tests" / "fixtures" / "stt_vocabulary_script.md"
OUTLINE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "usmle_step1_outline.txt"


def _load_harness():
    """Import the harness by path -- ``scripts/`` is not a package.

    The module must be registered in ``sys.modules`` before ``exec_module``:
    ``@dataclass`` resolves its annotations through
    ``sys.modules[cls.__module__]`` and raises ``AttributeError`` on a module
    that is not there yet.
    """
    spec = importlib.util.spec_from_file_location("stt_measure", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["stt_measure"] = module
    spec.loader.exec_module(module)
    return module


stt = _load_harness()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_BASE_NORMALISATION = {
    "applied_in_this_order": [
        "nfkc", "lowercase", "split_joiners", "drop_punctuation", "numbers",
        "units", "letter_runs", "disfluencies", "collapse_whitespace",
    ],
    "unit_map": {"milligrams": "mg", "milligram": "mg"},
    "disfluencies": ["um", "uh"],
}


def make_corpus(tmp_path: Path, utterances, *, variants=None, base_terms=()):
    payload = {
        "schema_version": 1,
        "corpus_id": "test",
        "normalisation": _BASE_NORMALISATION,
        "term_variants": variants or {},
        "priming": {"frame": "Terms:", "token_budget": 223,
                    "base_terms": list(base_terms)},
        "utterances": utterances,
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return stt.load_corpus(path)


def utt(uid, reference, terms=(), entry_terms=()):
    return {
        "id": uid,
        "file": uid + ".wav",
        "category": "test",
        "reference": reference,
        "priming_entry_terms": list(entry_terms),
        "terms": [{"text": t, "category": c} for t, c in terms],
    }


# ==========================================================================
# WER
# ==========================================================================


class TestWordErrorRate:
    def test_hand_computed_substitution_and_deletion(self):
        """Reference 5 words; one substitution and one deletion -> 2/5 = 0.4.

        ref: the metoprolol dose was doubled
        hyp: the metropolol dose     doubled
                  ^sub          ^del
        """
        norm = stt.Normaliser()
        ref = norm.tokens("The metoprolol dose was doubled.")
        hyp = norm.tokens("The metropolol dose doubled.")
        assert len(ref) == 5
        alignment = stt.align(ref, hyp)
        assert (alignment.substitutions, alignment.deletions,
                alignment.insertions) == (1, 1, 0)
        assert stt.word_error_rate(ref, hyp) == pytest.approx(0.4)

    def test_hand_computed_insertions(self):
        """Two words inserted into a 7-word reference -> 2/7."""
        norm = stt.Normaliser()
        ref = norm.tokens("warfarin takes about five days to work")
        hyp = norm.tokens("warfarin takes about five days to really work well")
        assert len(ref) == 7
        alignment = stt.align(ref, hyp)
        assert (alignment.substitutions, alignment.deletions,
                alignment.insertions) == (0, 0, 2)
        assert stt.word_error_rate(ref, hyp) == pytest.approx(2 / 7)

    def test_perfect_transcript_is_zero(self):
        norm = stt.Normaliser()
        ref = norm.tokens("the patient has a deep venous thrombosis")
        assert stt.word_error_rate(ref, list(ref)) == 0.0

    def test_is_minimal_edit_distance_not_just_an_alignment(self):
        """A shifted sequence costs one insertion, not a cascade of substitutions.

        difflib would produce a valid alignment here but not necessarily the
        minimal one, which is why this scorer computes Levenshtein directly.
        """
        ref = ["a", "b", "c", "d", "e"]
        hyp = ["x", "a", "b", "c", "d", "e"]
        alignment = stt.align(ref, hyp)
        assert alignment.errors == 1
        assert alignment.insertions == 1


# ==========================================================================
# Normalisation -- the declared rules, each one pinned
# ==========================================================================


class TestNormalisation:
    @pytest.mark.parametrize("written", ["COPD", "copd", "C.O.P.D.", "C O P D"])
    def test_letter_sequences_collapse_to_one_token(self, written):
        assert stt.Normaliser().tokens(written) == ["copd"]

    def test_number_words_become_digits(self):
        norm = stt.Normaliser()
        assert norm.tokens("fourteen days") == ["14", "days"]
        assert norm.tokens("forty five") == ["45"]
        assert norm.tokens("six point four") == ["6.4"]
        assert norm.tokens("one hundred") == ["100"]

    def test_digits_and_words_normalise_alike(self):
        norm = stt.Normaliser()
        assert norm.tokens("a potassium of 6.4") == norm.tokens(
            "a potassium of six point four")

    def test_units_are_canonicalised(self):
        norm = stt.Normaliser(unit_map={"milligrams": "mg"})
        assert norm.tokens("five milligrams") == norm.tokens("5 mg")

    def test_hyphens_split_and_apostrophes_vanish(self):
        norm = stt.Normaliser()
        assert norm.tokens("heparin-induced") == ["heparin", "induced"]
        assert norm.tokens("the patient's X-ray") == ["the", "patients", "x", "ray"]

    def test_disfluencies_are_dropped_from_both_sides(self):
        norm = stt.Normaliser(disfluencies=frozenset({"um", "uh"}))
        assert norm.tokens("um so uh warfarin") == ["so", "warfarin"]

    def test_decimal_point_survives_between_digits_only(self):
        norm = stt.Normaliser()
        assert norm.tokens("a troponin of 0.9. Then what?") == [
            "a", "troponin", "of", "0.9", "then", "what"]


# ==========================================================================
# Term recall
# ==========================================================================


class TestTermRecall:
    def test_every_marked_term_survives(self, tmp_path):
        corpus = make_corpus(tmp_path, [
            utt("u1", "I started warfarin and then I checked the INR.",
                [("warfarin", "drug_generic"), ("INR", "abbrev_letters")]),
        ], variants={"INR": ["I.N.R."]})
        result = stt.score_utterance(
            corpus, corpus.utterances[0],
            "I started warfarin and then I checked the I.N.R.")
        assert (result.term_hits, result.term_total) == (2, 2)
        assert result.misses == ()

    def test_a_mangled_drug_name_is_a_miss_and_says_what_was_heard(self, tmp_path):
        corpus = make_corpus(tmp_path, [
            utt("u1", "I started warfarin and then I checked the INR.",
                [("warfarin", "drug_generic"), ("INR", "abbrev_letters")]),
        ])
        result = stt.score_utterance(
            corpus, corpus.utterances[0],
            "I started wolfrin and then I checked the INR.")
        assert (result.term_hits, result.term_total) == (1, 2)
        missed = {name: heard for name, _cat, heard in result.misses}
        assert "warfarin" in missed
        # The point of the breakdown: it names the substitution, not just a rate.
        assert "wolfrin" in missed["warfarin"]

    def test_a_repeated_term_counts_every_occurrence(self, tmp_path):
        corpus = make_corpus(tmp_path, [
            utt("u1", "An ACE inhibitor is why the ACE inhibitor was stopped.",
                [("ACE inhibitor", "abbrev_letters")]),
        ])
        utterance = corpus.utterances[0]
        assert stt.count_term(utterance.ref_tokens, utterance.terms[0]) == 2
        half = stt.score_utterance(
            corpus, utterance, "An ACE inhibitor is why the drug was stopped.")
        assert (half.term_hits, half.term_total) == (1, 2)

    def test_an_accepted_variant_counts_as_a_hit(self, tmp_path):
        corpus = make_corpus(tmp_path, [
            utt("u1", "He has a deep venous thrombosis.",
                [("deep venous thrombosis", "disease")]),
        ], variants={"deep venous thrombosis": ["deep vein thrombosis"]})
        result = stt.score_utterance(
            corpus, corpus.utterances[0], "He has a deep vein thrombosis.")
        assert result.term_hits == 1

    def test_a_term_is_never_counted_inside_a_longer_term(self, tmp_path):
        corpus = make_corpus(tmp_path, [
            utt("u1", "Immune thrombocytopenic purpura is not the same thing.",
                [("immune thrombocytopenic purpura", "disease")]),
        ])
        term = corpus.utterances[0].terms[0]
        assert len(stt.find_term_spans(corpus.utterances[0].ref_tokens, term)) == 1


# ==========================================================================
# Term precision -- the invented-term detector
# ==========================================================================


class TestInventedTerms:
    def test_a_term_from_another_utterance_is_an_invention(self, tmp_path):
        """Priming's failure mode: a primed word inserted where nothing said it.

        The hunt has to run over the whole corpus vocabulary. A per-utterance
        vocabulary cannot see a term that leaked in from somewhere else, which
        is the only place this failure comes from.
        """
        corpus = make_corpus(tmp_path, [
            utt("u1", "The patient has COPD.", [("COPD", "abbrev_letters")]),
            utt("u2", "I started metoprolol.", [("metoprolol", "drug_generic")]),
        ])
        result = stt.score_utterance(
            corpus, corpus.utterances[0], "The patient has COPD and metoprolol.")
        invented = {name: count for name, _cat, count in result.invented}
        assert invented == {"metoprolol": 1}
        assert result.term_hits == 1  # COPD still survived

    def test_an_unmarked_word_that_is_in_the_reference_is_not_an_invention(
            self, tmp_path):
        """Reference counts come from the reference TEXT, not the marked list.

        ``two weeks`` is marked in one utterance and merely spoken in another.
        Counting from the marked list would report the second as a
        hallucination.
        """
        corpus = make_corpus(tmp_path, [
            utt("u1", "The imaging lags by two weeks.",
                [("two weeks", "number_unit")]),
            utt("u2", "It shows up about two weeks after the sore throat.", []),
        ])
        result = stt.score_utterance(
            corpus, corpus.utterances[1],
            "It shows up about two weeks after the sore throat.")
        assert result.invented == ()

    def test_precision_and_the_drug_or_disease_gate(self, tmp_path):
        corpus = make_corpus(tmp_path, [
            utt("u1", "The patient has COPD.", [("COPD", "abbrev_letters")]),
            utt("u2", "I started metoprolol.", [("metoprolol", "drug_generic")]),
        ])
        config = stt.ConfigResult(model="test", primed=True)
        config.results.append(stt.score_utterance(
            corpus, corpus.utterances[0], "The patient has COPD and metoprolol."))
        config.results.append(stt.score_utterance(
            corpus, corpus.utterances[1], "I started metoprolol."))
        assert config.term_hits == 2 and config.term_total == 2
        assert config.term_recall == 1.0
        assert config.invented_total == 1
        assert config.term_precision == pytest.approx(2 / 3)
        # A hallucinated drug name is its own bar, separate from precision.
        assert config.invented_drug_or_disease == 1


# ==========================================================================
# Corpus validation
# ==========================================================================


class TestCorpusValidation:
    def test_a_marked_term_absent_from_its_reference_is_refused(self, tmp_path):
        with pytest.raises(SystemExit):
            make_corpus(tmp_path, [
                utt("u1", "The patient has COPD.",
                    [("metoprolol", "drug_generic")]),
            ])

    def test_overlapping_marked_terms_are_refused(self, tmp_path):
        """Marking both halves would double-count the recall denominator."""
        with pytest.raises(SystemExit):
            make_corpus(tmp_path, [
                utt("u1", "Chronic bronchitis is a mucus problem.",
                    [("chronic bronchitis", "disease"),
                     ("bronchitis", "disease")]),
            ])

    def test_one_term_may_not_carry_two_categories(self, tmp_path):
        with pytest.raises(SystemExit):
            make_corpus(tmp_path, [
                utt("u1", "I started warfarin.", [("warfarin", "drug_generic")]),
                utt("u2", "I stopped warfarin.", [("warfarin", "disease")]),
            ])

    def test_a_normalisation_pipeline_the_scorer_does_not_implement_is_refused(
            self, tmp_path):
        """A rule declared in the file but absent from the scorer is a silent
        scoring change, so it stops the run instead."""
        payload = {
            "corpus_id": "test",
            "normalisation": {"applied_in_this_order": ["lowercase", "magic"]},
            "priming": {},
            "utterances": [utt("u1", "hello there")],
        }
        path = tmp_path / "corpus.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SystemExit):
            stt.load_corpus(path)

    def test_a_missing_corpus_file_says_what_to_do(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            stt.load_corpus(tmp_path / "nope.json")
        assert "--corpus" in capsys.readouterr().err


# ==========================================================================
# Priming
# ==========================================================================


class TestPriming:
    def test_entry_terms_land_at_the_end(self, tmp_path):
        """whisper.cpp keeps the TAIL of an over-long prompt and discards the
        front, silently.  So the most relevant terms must be last."""
        corpus = make_corpus(
            tmp_path,
            [utt("u1", "hello there", entry_terms=["hypertension"])],
            base_terms=["asthma", "cirrhosis"])
        prompt = stt.build_prompt(corpus, corpus.utterances[0])
        assert prompt.rstrip(".").endswith("hypertension")
        assert prompt.index("asthma") < prompt.index("hypertension")

    def test_truncation_drops_from_the_front(self, tmp_path):
        corpus = make_corpus(
            tmp_path,
            [utt("u1", "hello there", entry_terms=["hypertension"])],
            base_terms=["filler subject name " + str(i) for i in range(400)])
        prompt = stt.build_prompt(corpus, corpus.utterances[0])
        assert stt.estimate_tokens(prompt) <= corpus.token_budget
        assert prompt.rstrip(".").endswith("hypertension")
        assert "filler subject name 0" not in prompt
        assert "filler subject name 399" in prompt

    def test_the_token_estimate_over_counts_rather_than_under_counts(self):
        """Measured against whisper.cpp's own tokenizer: this glossary runs
        3.46-3.69 characters per token, and the estimator divides by 3.3."""
        glossary = ", ".join(["thrombocytopenia", "glomerulonephritis",
                              "hypertensive nephrosclerosis"] * 10)
        assert stt.estimate_tokens(glossary) > len(glossary) / 3.7

    def test_an_empty_prompt_costs_nothing(self):
        assert stt.estimate_tokens("") == 0
        assert stt.estimate_tokens("   ") == 0


# ==========================================================================
# The shipped fixture
# ==========================================================================


class TestShippedCorpus:
    @pytest.fixture(scope="class")
    def corpus(self):
        return stt.load_corpus(CORPUS_PATH)

    def test_it_loads_and_validates(self, corpus):
        assert stt.validate_corpus(corpus) == []
        assert len(corpus.utterances) == 24

    def test_it_carries_enough_marked_terms_to_separate_95_from_90(self, corpus):
        """The metric's denominator is marked terms, not utterances.

        At 100 occurrences the 95% confidence interval around a 95% recall is
        about +/-4 points, which is what makes the pass bar decidable.  Below
        that the corpus cannot tell a pass from a fail.
        """
        occurrences = sum(stt.count_term(u.ref_tokens, t)
                          for u in corpus.utterances for t in u.terms)
        assert occurrences >= 100

    def test_every_case_that_breaks_asr_is_covered(self, corpus):
        categories = {t.category for u in corpus.utterances for t in u.terms}
        for required in ("drug_generic", "drug_brand", "disease",
                         "abbrev_letters", "abbrev_word", "number_unit"):
            assert required in categories, required

    def test_there_are_control_utterances_with_no_domain_vocabulary(self, corpus):
        controls = [u for u in corpus.utterances if not u.terms]
        assert len(controls) >= 3

    def test_every_priming_term_comes_from_the_published_outline(self, corpus):
        """The honesty guard.

        Priming built from the marked-terms list would be an oracle prompt: the
        prompt would contain exactly the words being scored, and the measurement
        would say nothing about the feature, which primes from the student's
        imported subject tree.  Requiring every priming term to appear verbatim
        in the real USMLE outline is what stops that happening by degrees.
        """
        outline = OUTLINE_PATH.read_text(encoding="latin-1").lower()
        outline = " ".join(outline.split())
        terms = list(corpus.priming_base_terms)
        for utterance in corpus.utterances:
            terms.extend(utterance.priming_entry_terms)
        missing = [t for t in dict.fromkeys(terms)
                   if " ".join(t.lower().split()) not in outline]
        assert missing == [], "not in usmle_step1_outline.txt: " + repr(missing)

    def test_every_prompt_fits_the_223_token_budget(self, corpus):
        for utterance in corpus.utterances:
            prompt = stt.build_prompt(corpus, utterance)
            assert stt.estimate_tokens(prompt) <= stt.PROMPT_TOKEN_BUDGET
            # And the entry's own subjects survived the front truncation.
            for term in utterance.priming_entry_terms:
                assert term in prompt

    @pytest.mark.parametrize("term,spelling", [
        ("COPD", "C.O.P.D."), ("COPD", "copd"),
        ("GERD", "G.E.R.D."),
        ("ACE inhibitor", "ace-inhibitor"), ("ACE inhibitor", "A.C.E. inhibitor"),
        ("hemoglobin A1c", "hemoglobin A1C"), ("hemoglobin A1c", "HbA1c"),
        ("HLA B27", "HLA-B27"),
        ("electrocardiogram", "EKG"), ("electrocardiogram", "ECG"),
        ("6 ml per kg", "6 mL/kg"),
        ("6 ml per kg", "six milliliters per kilogram"),
        ("0.9", "zero point nine"), ("0.9", ".9"),
        ("Wolff Parkinson White", "Wolff-Parkinson-White"),
        ("Wolff Parkinson White", "WPW"),
        ("x ray", "X-ray"), ("x ray", "xray"),
        ("deep venous thrombosis", "deep vein thrombosis"),
    ])
    def test_the_spellings_whisper_actually_writes_are_accepted(
            self, corpus, term, spelling):
        """The variants list has to survive contact with real output.

        Whisper renders a letter abbreviation inconsistently -- ``ACE``,
        ``ace``, ``A.C.E.`` -- and that is a normalisation problem, not an
        accuracy one.  Each of these is a spelling a model plausibly produces;
        scoring any of them as a miss would report a normalisation bug as a
        model failure, and the owner would have no way to tell the difference.
        """
        marked = corpus.vocabulary[term.lower()]
        tokens = corpus.normaliser.tokens("they said " + spelling + " out loud")
        assert stt.count_term(tokens, marked) == 1

    def test_reading_it_aloud_takes_about_ten_minutes(self, corpus):
        words = sum(len(u.reference.split()) for u in corpus.utterances)
        assert 800 <= words <= 1600, words


# ==========================================================================
# The generated read-aloud script
# ==========================================================================


class TestReadAloudScript:
    def test_the_generated_script_is_in_sync(self):
        """Same gate shape as scripts/check_import_guide_sync.py.

        The reference transcripts live in the JSON; the human reads the
        Markdown.  An edit to one that never reaches the other would score the
        recording against words nobody said.
        """
        corpus = stt.load_corpus(CORPUS_PATH)
        assert SCRIPT_MD_PATH.read_text(encoding="utf-8") == stt.render_script(corpus)

    def test_it_tells_the_reader_the_filename_convention(self):
        text = SCRIPT_MD_PATH.read_text(encoding="utf-8")
        assert "u01.wav" in text
        assert "one file per utterance" in text.lower()
        assert "same room" in text.lower()

    def test_every_utterance_appears_with_its_filename(self):
        corpus = stt.load_corpus(CORPUS_PATH)
        text = SCRIPT_MD_PATH.read_text(encoding="utf-8")
        for utterance in corpus.utterances:
            assert utterance.file in text
            assert utterance.reference in text


# ==========================================================================
# Reporting
# ==========================================================================


class TestReport:
    def test_the_table_survives_a_configuration_with_no_usable_result(self,
                                                                      tmp_path):
        """A model that failed on every utterance must still render a row.

        The alternative is a crash halfway through writing the report, after
        the transcription time has already been spent.
        """
        corpus = make_corpus(tmp_path, [
            utt("u1", "The patient has COPD.", [("COPD", "abbrev_letters")]),
        ])
        broken = stt.ConfigResult(model="tiny.en", primed=False)
        broken.results.append(stt.UtteranceResult(
            utterance_id="u1", ok=False, error="exit 1: no such file"))
        markdown = stt.render_markdown(corpus, [broken], environment={})
        assert "tiny.en" in markdown
        assert "no such file" in markdown

    def test_the_report_is_ascii(self, tmp_path):
        """The owner will redirect this to a file on Windows (#137)."""
        corpus = make_corpus(tmp_path, [
            utt("u1", "The patient has COPD.", [("COPD", "abbrev_letters")]),
        ])
        config = stt.ConfigResult(model="base.en", primed=True, model_bytes=1024)
        config.results.append(stt.score_utterance(
            corpus, corpus.utterances[0], "The patient has COPD."))
        markdown = stt.render_markdown(corpus, [config],
                                       environment={"date": "2026-09-23"})
        markdown.encode("ascii")  # raises if anything non-ASCII crept in

    def test_an_incomplete_recording_set_stops_the_run(self, tmp_path, capsys):
        """A half-recorded corpus must not quietly become a whole measurement.

        The gate runs before any transcription, so a naming mistake costs
        seconds rather than the half hour the matrix takes.  An empty file
        counts as incomplete too -- silently measuring 21 of 24 because three
        recordings came out zero-length is the same failure wearing a
        different hat.
        """
        binary = tmp_path / "whisper-cli"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        models = tmp_path / "models"
        models.mkdir()
        (models / "ggml-tiny.en.bin").write_bytes(b"x")
        audio = tmp_path / "audio"
        audio.mkdir()
        (audio / "jfk.wav").write_bytes(b"")  # empty: present but unusable

        argv = ["run", "--corpus", "jfk", "--audio-dir", str(audio),
                "--whisper-cli", str(binary), "--models-dir", str(models),
                "--models", "tiny.en"]
        with pytest.raises(SystemExit):
            stt.main(argv)
        err = capsys.readouterr().err
        assert "empty" in err
        assert "u01.wav" in err or "filenames" in err

    def test_realtime_factor_is_reported_per_utterance(self, tmp_path):
        corpus = make_corpus(tmp_path, [
            utt("u1", "The patient has COPD.", [("COPD", "abbrev_letters")]),
        ])
        result = stt.score_utterance(corpus, corpus.utterances[0],
                                     "The patient has COPD.")
        result.seconds = 4.0
        result.audio_seconds = 16.0
        assert result.realtime_factor == pytest.approx(0.25)
        config = stt.ConfigResult(model="base.en", primed=False)
        config.results.append(result)
        assert config.median_rtf == pytest.approx(0.25)
