#!/usr/bin/env python3
"""Speech-to-text accuracy measurement harness for issue #59 (task T3).

WHAT THIS IS
------------
#59's acceptance criterion is *"transcription accuracy on exam-domain
vocabulary is measured and recorded in this issue before the engine choice is
final."*  The engine is settled (whisper.cpp, #59 comment #1583), so what this
measures is the **model size**, and through it what the first-run download
costs.  See ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` section 6.

It runs a directory of recordings through the matrix of
{model} x {priming on, priming off} and reports, per configuration:

* **term recall on the marked domain terms** -- the headline.  Did "warfarin",
  "thrombocytopenia" and "COPD" survive?  A model that scores well on WER while
  mangling every drug name is useless for this feature.
* **term precision** -- terms the transcript *invented*.  Vocabulary priming's
  specific failure mode is inserting a primed word that was never said, and a
  hallucinated drug name is worse than a garbled one because the student cannot
  tell it is wrong by looking at it.
* **overall WER**, for comparability with published numbers only.
* **wall-clock seconds per utterance and realtime factor**.  #59 comment #1583
  keeps ``mlx-whisper`` available if whisper.cpp proves "too slow"; nothing else
  in the project produces a number that clause could fire on.

WHAT THE HUMAN HAS TO DO
------------------------
Record the corpus in their own voice.  A synthetic voice reading the same script
measures the TTS engine's pronunciation, not this feature.  The read-aloud
script and full recording instructions are generated into
``tests/fixtures/stt_vocabulary_script.md``; print or open that and read it.

In short: **one file per utterance, named after the utterance id**
(``u01.wav`` ... ``u24.wav``), all in one directory, mono WAV, 16 kHz
preferred.  Record on the machine and in the room where you will actually use
the feature -- the same laptop fan, the same distance from the microphone, the
same time of night.

THE COMMANDS
------------
Measure (the one the owner runs)::

    python scripts/stt_measure.py run \\
        --audio-dir ~/wimi-stt-recordings \\
        --whisper-cli /path/to/whisper-cli \\
        --models-dir /path/to/models \\
        --out stt_results.md

Prove the harness works before recording anything -- no microphone needed::

    python scripts/stt_measure.py self-test
    python scripts/stt_measure.py run --corpus jfk \\
        --audio-dir /path/to/whisper.cpp/samples \\
        --whisper-cli ... --models-dir ...

Regenerate the read-aloud script after editing the corpus JSON::

    python scripts/stt_measure.py write-script

MODELS
------
Default matrix: ``tiny.en``, ``base.en``, ``base``, ``base-q5_1``,
``base-q8_0``, ``small.en``.  Download each as
``ggml-<name>.bin`` from
``https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<name>.bin``
into one directory and point ``--models-dir`` at it.  Note that ``base-q5_1``
and ``base-q8_0`` are quantisations of the **multilingual** ``base``, so
``base`` is their comparison baseline; comparing them against ``base.en``
conflates quantisation with the English-only head.

WHISPER-CLI CONTRACT (established by task T1, do not re-derive)
--------------------------------------------------------------
* The binary is ``whisper-cli``.  ``main``/``main.exe`` is a deprecated stub.
* ``-m MODEL -f FILE -l en -t N -np -nt`` and read **stdout**; every log line
  goes to stderr regardless.
* ``--prompt "..."`` is the vocabulary priming flag.  The usable budget is
  ``n_text_ctx/2 - 1`` = **223 tokens**, and truncation keeps the **tail** and
  discards the **front**, silently.  So the priming string is assembled least
  relevant first, most relevant last, and this harness truncates from the front
  itself so that what was sent is inspectable.
* whisper.cpp accepts wav/flac/mp3/ogg at any sample rate and resamples
  internally.  16 kHz mono 16-bit is preferred, not required.
* **It exits 0 on an audio file it cannot read** (measured here, not in T1): a
  text file renamed to ``.wav`` prints ``error: failed to read audio file`` on
  stderr, writes nothing to stdout, and returns 0.  A missing model does return
  3.  So empty stdout -- not the return code -- is what says a recording
  failed, and T6's subprocess wrapper needs the same check.

This script deliberately adds no dependency: stdlib only, nothing in
``requirements-prod.txt``.  Its output is pure ASCII, for the reason recorded in
``CLAUDE.md`` under #137 -- the owner will pipe this to a file on Windows.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

# --------------------------------------------------------------------------
# stdio, before anything can print.  See CLAUDE.md, "Every entry point
# configures stdio first" (#137).  The None guard is load-bearing: a frozen
# windowless build has sys.stdout is None and an unguarded reconfigure()
# raises AttributeError on the very line added to stop a crash.
# --------------------------------------------------------------------------
for _stream, _errors in ((sys.stdout, "replace"), (sys.stderr, "backslashreplace")):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors=_errors)
        except (ValueError, OSError):  # pragma: no cover - platform dependent
            pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = PROJECT_ROOT / "tests" / "fixtures" / "stt_vocabulary_terms.json"
DEFAULT_SCRIPT = PROJECT_ROOT / "tests" / "fixtures" / "stt_vocabulary_script.md"

DEFAULT_MODELS = ("tiny.en", "base.en", "base", "base-q5_1", "base-q8_0", "small.en")
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"

AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".ogg")

#: whisper.cpp's usable prompt budget: ``n_text_ctx / 2 - 1`` for the 448-context
#: models.  Task T1 verified this three ways and verified that overflow is
#: silent at these sizes -- with ``-np`` the binary does not even print its own
#: tokenizer warning.  So the budget is enforced here or not at all.
PROMPT_TOKEN_BUDGET = 223


# ==========================================================================
# Failure handling.  Every exit says what to do, not what went wrong inside.
# ==========================================================================


def die(message: str) -> "NoReturn":  # type: ignore[valid-type]
    print("stt_measure: " + message, file=sys.stderr)
    raise SystemExit(2)


# ==========================================================================
# Normalisation.  Declared in the corpus file, applied here, never tuned
# after seeing a result.
# ==========================================================================

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALE_WORDS = {"hundred": 100, "thousand": 1000}

@dataclass(frozen=True)
class Normaliser:
    """The declared normalisation pipeline, built from the corpus file.

    Rules, in order (and the corpus file states the same list so the two
    cannot drift silently -- ``validate`` checks it):

    1. NFKC, curly quotes and dashes folded to ASCII
    2. lowercase
    3. ``/``, ``-``, ``_`` become spaces
    4. apostrophes deleted; other punctuation becomes a space, except a ``.``
       between two digits
    5. number words become digits, including ``point`` between numbers
    6. unit words canonicalised through ``unit_map``
    7. runs of two or more single-letter tokens are joined, so ``c o p d``,
       ``C.O.P.D.`` and ``COPD`` all land on ``copd``
    8. filler tokens removed
    9. whitespace collapsed
    """

    unit_map: dict[str, str] = field(default_factory=dict)
    disfluencies: frozenset[str] = frozenset()

    RULE_IDS = (
        "nfkc", "lowercase", "split_joiners", "drop_punctuation", "numbers",
        "units", "letter_runs", "disfluencies", "collapse_whitespace",
    )

    def tokens(self, text: str) -> list[str]:
        text = unicodedata.normalize("NFKC", text or "")
        # Written as escapes, not literals, so this file stays pure ASCII on a
        # machine that reads source with the console codepage (see #137).
        for _fancy, _plain in (("\u2019", "'"), ("\u2018", "'"),
                               ("\u201c", '"'), ("\u201d", '"'),
                               ("\u2013", "-"), ("\u2014", "-"),
                               ("\u2212", "-")):
            text = text.replace(_fancy, _plain)
        text = text.lower()
        text = text.replace("'", "")
        text = re.sub(r"[/\-_]", " ", text)
        # Punctuation out, except a decimal point flanked by digits.
        out: list[str] = []
        for i, ch in enumerate(text):
            if ch.isalnum() or ch.isspace():
                out.append(ch)
            elif ch == "." and i > 0 and i + 1 < len(text) \
                    and text[i - 1].isdigit() and text[i + 1].isdigit():
                out.append(ch)
            else:
                out.append(" ")
        toks = "".join(out).split()
        toks = self._numbers(toks)
        toks = [self.unit_map.get(t, t) for t in toks]
        toks = self._letter_runs(toks)
        toks = [t for t in toks if t not in self.disfluencies]
        return toks

    def text(self, text: str) -> str:
        return " ".join(self.tokens(text))

    # -- rule 5 ------------------------------------------------------------
    @staticmethod
    def _numbers(toks: Sequence[str]) -> list[str]:
        """Number words to digits.

        Handles ``forty five`` -> ``45``, ``one hundred`` -> ``100`` and
        ``six point four`` -> ``6.4``.  Deliberately conservative: anything it
        does not recognise is left alone, because a wrong number is worse than
        an unconverted one, and both sides get the same treatment so WER is
        never charged for the difference.
        """
        out: list[str] = []
        i = 0
        n = len(toks)
        while i < n:
            tok = toks[i]
            if tok in _NUMBER_WORDS:
                value = _NUMBER_WORDS[tok]
                i += 1
                # tens + units: "forty five"
                if value >= 20 and value % 10 == 0 and i < n \
                        and toks[i] in _NUMBER_WORDS and _NUMBER_WORDS[toks[i]] < 10:
                    value += _NUMBER_WORDS[toks[i]]
                    i += 1
                # scale: "one hundred", "two thousand"
                while i < n and toks[i] in _SCALE_WORDS:
                    value *= _SCALE_WORDS[toks[i]]
                    i += 1
                    if i < n and toks[i] in _NUMBER_WORDS:
                        nxt = _NUMBER_WORDS[toks[i]]
                        value += nxt
                        i += 1
                        if (nxt >= 20 and nxt % 10 == 0 and i < n
                                and toks[i] in _NUMBER_WORDS
                                and _NUMBER_WORDS[toks[i]] < 10):
                            value += _NUMBER_WORDS[toks[i]]
                            i += 1
                out.append(str(value))
            else:
                out.append(tok)
                i += 1
        # "6 point 4" -> "6.4"
        merged: list[str] = []
        j = 0
        while j < len(out):
            if (j + 2 < len(out) and out[j + 1] == "point"
                    and out[j].isdigit() and out[j + 2].isdigit()):
                merged.append(out[j] + "." + out[j + 2])
                j += 3
            else:
                merged.append(out[j])
                j += 1
        return merged

    # -- rule 7 ------------------------------------------------------------
    @staticmethod
    def _letter_runs(toks: Sequence[str]) -> list[str]:
        out: list[str] = []
        run: list[str] = []
        for tok in toks:
            if len(tok) == 1 and tok.isalpha():
                run.append(tok)
                continue
            if len(run) >= 2:
                out.append("".join(run))
            else:
                out.extend(run)
            run = []
            out.append(tok)
        if len(run) >= 2:
            out.append("".join(run))
        else:
            out.extend(run)
        return out


# ==========================================================================
# Corpus
# ==========================================================================


@dataclass
class Term:
    text: str
    category: str
    forms: tuple[tuple[str, ...], ...]  # normalised token tuples, longest first

    @property
    def key(self) -> str:
        return self.text.lower()


@dataclass
class Utterance:
    id: str
    file: str
    category: str
    reference: str
    ref_tokens: tuple[str, ...]
    terms: tuple[Term, ...]
    priming_entry_terms: tuple[str, ...]
    note: str = ""


@dataclass
class Corpus:
    corpus_id: str
    normaliser: Normaliser
    utterances: tuple[Utterance, ...]
    vocabulary: dict[str, Term]  # key -> Term, every marked term in the corpus
    priming_frame: str
    priming_base_terms: tuple[str, ...]
    token_budget: int
    source_path: Path | None = None
    raw: dict = field(default_factory=dict)


def _term_forms(norm: Normaliser, text: str, variants: Iterable[str]) -> tuple[tuple[str, ...], ...]:
    forms = {tuple(norm.tokens(text))}
    for variant in variants:
        toks = tuple(norm.tokens(variant))
        if toks:
            forms.add(toks)
    forms.discard(())
    return tuple(sorted(forms, key=len, reverse=True))


def load_corpus(source: str | Path) -> Corpus:
    """Load and validate a corpus file (or the embedded ``jfk`` proof corpus)."""
    if str(source) == "jfk":
        data = json.loads(_JFK_CORPUS)
        path = None
    else:
        path = Path(source)
        if not path.is_file():
            die(
                "no corpus file at " + str(path) + ".\n"
                "  Pass --corpus with the path to the marked-terms JSON, or use\n"
                "  --corpus jfk for the built-in proof corpus."
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            die("the corpus file " + str(path) + " is not valid JSON: " + str(exc)
                + "\n  Fix the JSON; nothing else in this run will make sense until it parses.")

    normalisation = data.get("normalisation", {})
    norm = Normaliser(
        unit_map={k.lower(): v.lower() for k, v in normalisation.get("unit_map", {}).items()},
        disfluencies=frozenset(w.lower() for w in normalisation.get("disfluencies", [])),
    )

    declared = [rule.split(":", 1)[0].strip()
                for rule in normalisation.get("applied_in_this_order", [])]
    if declared and tuple(declared) != Normaliser.RULE_IDS:
        die(
            "the corpus file declares a normalisation pipeline this scorer does not\n"
            "  implement. Declared: " + ", ".join(declared) + "\n"
            "  Implemented: " + ", ".join(Normaliser.RULE_IDS) + "\n"
            "  Either the file or Normaliser has been edited alone. Reconcile them\n"
            "  BEFORE scoring -- a normalisation rule changed after results exist is\n"
            "  not a measurement."
        )

    variants_raw = {k.lower(): v for k, v in data.get("term_variants", {}).items()}

    vocabulary: dict[str, Term] = {}
    utterances: list[Utterance] = []
    for raw in data.get("utterances", []):
        uid = raw["id"]
        reference = raw["reference"]
        ref_tokens = tuple(norm.tokens(reference))
        if not ref_tokens:
            die("utterance " + uid + " has an empty reference. Every utterance needs "
                "the words that get read aloud.")

        terms: list[Term] = []
        for spec in raw.get("terms", []):
            text = spec["text"]
            category = spec.get("category", "concept")
            forms = _term_forms(norm, text, variants_raw.get(text.lower(), ()))
            term = Term(text=text, category=category, forms=forms)
            existing = vocabulary.get(term.key)
            if existing is None:
                vocabulary[term.key] = term
            elif existing.category != category:
                die("the term '" + text + "' is category '" + existing.category
                    + "' in one utterance and '" + category + "' in " + uid
                    + ". One term, one category -- the 'no invented drug or disease'\n"
                      "  bar reads the category.")
            terms.append(vocabulary[term.key])

        utterances.append(Utterance(
            id=uid,
            file=raw.get("file", uid + ".wav"),
            category=raw.get("category", ""),
            reference=reference,
            ref_tokens=ref_tokens,
            terms=tuple(terms),
            priming_entry_terms=tuple(raw.get("priming_entry_terms", ())),
            note=raw.get("note", ""),
        ))

    if not utterances:
        die("the corpus file has no utterances.")

    priming = data.get("priming", {})
    corpus = Corpus(
        corpus_id=data.get("corpus_id", "unnamed"),
        normaliser=norm,
        utterances=tuple(utterances),
        vocabulary=vocabulary,
        priming_frame=priming.get("frame", "Terms:"),
        priming_base_terms=tuple(priming.get("base_terms", ())),
        token_budget=int(priming.get("token_budget", PROMPT_TOKEN_BUDGET)),
        source_path=path,
        raw=data,
    )
    problems = validate_corpus(corpus)
    if problems:
        die("the corpus does not describe itself consistently:\n  - "
            + "\n  - ".join(problems)
            + "\n  Fix the corpus file. Scoring against it would produce a number "
              "that means nothing.")
    return corpus


def validate_corpus(corpus: Corpus) -> list[str]:
    """Return the reasons the corpus cannot be scored, or an empty list.

    Split out from ``load_corpus`` so the test suite can assert on the
    individual failures without catching ``SystemExit``.
    """
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for utt in corpus.utterances:
        if utt.id in seen_ids:
            problems.append("duplicate utterance id " + utt.id)
        seen_ids.add(utt.id)
        if utt.file in seen_files:
            problems.append("two utterances claim the same audio file " + utt.file)
        seen_files.add(utt.file)

        spans: list[tuple[int, int, str]] = []
        for term in utt.terms:
            found = find_term_spans(utt.ref_tokens, term)
            if not found:
                problems.append(
                    utt.id + ": the marked term '" + term.text + "' does not occur in "
                    "its own reference text (after normalisation). Either the term or "
                    "the reference is wrong.")
            spans.extend((start, end, term.text) for start, end in found)

        spans.sort()
        for (a_start, a_end, a_text), (b_start, b_end, b_text) in zip(spans, spans[1:]):
            if b_start < a_end:
                problems.append(
                    utt.id + ": marked terms '" + a_text + "' and '" + b_text
                    + "' overlap in the reference. Mark only the longer span -- "
                      "overlapping marks double-count the recall denominator.")
    return problems


# ==========================================================================
# Term counting
# ==========================================================================


def find_term_spans(tokens: Sequence[str], term: Term) -> list[tuple[int, int]]:
    """Non-overlapping occurrences of any accepted form of ``term``.

    Longest form first, left to right, so ``ACE inhibitor`` is never counted as
    ``ACE`` plus a stray word.
    """
    spans: list[tuple[int, int]] = []
    taken = [False] * len(tokens)
    for form in term.forms:  # already longest-first
        width = len(form)
        for start in range(0, len(tokens) - width + 1):
            if any(taken[start:start + width]):
                continue
            if tuple(tokens[start:start + width]) == form:
                spans.append((start, start + width))
                for k in range(start, start + width):
                    taken[k] = True
    spans.sort()
    return spans


def count_term(tokens: Sequence[str], term: Term) -> int:
    return len(find_term_spans(tokens, term))


# ==========================================================================
# WER -- true word-level Levenshtein with a backtrace.
#
# difflib would give a valid alignment but not a minimal edit distance, so a
# hand-computed WER in a test could legitimately disagree with it. The corpus
# is a few hundred tokens; the quadratic table costs nothing and the number is
# then the one everybody else's WER means.
# ==========================================================================


@dataclass
class Alignment:
    substitutions: int
    deletions: int
    insertions: int
    ops: tuple[tuple[str, int, int], ...]  # (op, ref_index, hyp_index)

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions


def align(ref: Sequence[str], hyp: Sequence[str]) -> Alignment:
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    back = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i
        back[i][0] = "del"
    for j in range(1, m + 1):
        cost[0][j] = j
        back[0][j] = "ins"
    for i in range(1, n + 1):
        ref_tok = ref[i - 1]
        row, prev = cost[i], cost[i - 1]
        brow = back[i]
        for j in range(1, m + 1):
            if ref_tok == hyp[j - 1]:
                row[j] = prev[j - 1]
                brow[j] = "eq"
                continue
            sub = prev[j - 1] + 1
            dele = prev[j] + 1
            ins = row[j - 1] + 1
            best = min(sub, dele, ins)
            row[j] = best
            brow[j] = "sub" if best == sub else ("del" if best == dele else "ins")

    ops: list[tuple[str, int, int]] = []
    subs = dels = inss = 0
    i, j = n, m
    while i > 0 or j > 0:
        op = back[i][j]
        if op == "eq":
            i, j = i - 1, j - 1
            ops.append(("eq", i, j))
        elif op == "sub":
            i, j = i - 1, j - 1
            ops.append(("sub", i, j))
            subs += 1
        elif op == "del":
            i -= 1
            ops.append(("del", i, j))
            dels += 1
        else:
            j -= 1
            ops.append(("ins", i, j))
            inss += 1
    ops.reverse()
    return Alignment(subs, dels, inss, tuple(ops))


def word_error_rate(ref: Sequence[str], hyp: Sequence[str]) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    return align(ref, hyp).errors / len(ref)


def heard_instead(ali: Alignment, ref_span: tuple[int, int],
                  hyp_tokens: Sequence[str]) -> str:
    """What the hypothesis has where the reference had ``ref_span``.

    This is the difference between "recall was 0.91" and "u12 said
    rhabdomyolysis and the model heard 'rabdo my olysis'".
    """
    start, end = ref_span
    lo, hi = None, None
    for op, i, j in ali.ops:
        if op == "ins":
            continue
        if start <= i < end:
            lo = j if lo is None else min(lo, j)
            hi = j + 1 if hi is None else max(hi, j + 1)
    if lo is None:
        return "(nothing)"
    lo = max(0, lo - 1)
    hi = min(len(hyp_tokens), hi + 1)
    return " ".join(hyp_tokens[lo:hi]) or "(nothing)"


# ==========================================================================
# Priming
# ==========================================================================


#: Characters per Whisper BPE token for this glossary, measured rather than
#: guessed.  whisper.cpp's tokenizer prints the true token count when a prompt
#: exceeds its 1024-token tokenize buffer ("too many resulting tokens: N (max
#: 1024)"), which turns that error into a calibration instrument.  Four probe
#: strings built from this corpus's own priming glossary (7,137 / 9,488 /
#: 11,839 / 14,190 characters) tokenised to 1,935 / 2,574 / 3,213 / 3,852
#: tokens: 3.69 characters per token, within 0.3% across all four.  A single
#: budget-sized prompt measured the same way came out denser, at 3.46 -- the
#: ratio moves with the mix of long Latin names and short framing words, so it
#: is a range, not a constant.  3.3 is used: comfortably below both measurements,
#: leaving 5-8% headroom.  The asymmetry is the reason.  Over-counting costs two
#: or three glossary terms off the front, which is where the least relevant ones
#: are.  Under-counting hands the truncation back to the engine, which takes it
#: from the front too -- but silently, and possibly through the terms that
#: matter.  Note the probe only works without ``-np``; with the flags the
#: product uses, even that overflow warning is suppressed.
_CHARS_PER_TOKEN = 3.3


def estimate_tokens(text: str) -> int:
    """Token estimate for the priming budget -- calibrated, still conservative.

    There is no Whisper tokeniser in-process and this script adds no
    dependency, so the budget is estimated.  See ``_CHARS_PER_TOKEN`` for the
    measurement behind the ratio.  The word floor catches a degenerate string
    of very short words, where the character ratio would under-count.
    """
    if not text.strip():
        return 0
    chars = math.ceil(len(text) / _CHARS_PER_TOKEN)
    words = math.ceil(len(text.split()) * 1.3)
    return max(chars, words)


def build_prompt(corpus: Corpus, utt: Utterance,
                 budget: int | None = None) -> str:
    """Assemble the priming string for one utterance.

    Order is least relevant first, most relevant last, because whisper.cpp
    keeps the TAIL (plan section 3.6).  The base terms stand in for the
    student's imported exam-context subject tree; ``priming_entry_terms`` stand
    in for the subjects tagged on the open entry, so they go last.

    Truncation is done here, from the front, one term at a time, so the string
    that was actually sent is knowable.  Letting the engine do it is silent.
    """
    budget = corpus.token_budget if budget is None else budget
    terms = list(corpus.priming_base_terms) + list(utt.priming_entry_terms)
    # Drop duplicates but keep the LAST occurrence, since last is most relevant.
    seen: set[str] = set()
    kept: list[str] = []
    for term in reversed(terms):
        low = term.lower()
        if low in seen:
            continue
        seen.add(low)
        kept.append(term)
    kept.reverse()

    frame = corpus.priming_frame.rstrip()
    while kept:
        candidate = frame + " " + ", ".join(kept) + "."
        if estimate_tokens(candidate) <= budget:
            return candidate
        kept.pop(0)  # from the FRONT: the least relevant term goes first
    return frame


# ==========================================================================
# Running whisper-cli
# ==========================================================================


@dataclass
class Transcription:
    text: str
    seconds: float
    ok: bool
    error: str = ""


def resolve_binary(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get("WHISPER_CLI")
    if env:
        candidates.append(Path(env).expanduser())
    found = shutil.which("whisper-cli")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
        if candidate.is_dir() and (candidate / "whisper-cli").is_file():
            return (candidate / "whisper-cli").resolve()
    die(
        "cannot find whisper-cli.\n"
        "  Pass --whisper-cli /path/to/whisper-cli, or set WHISPER_CLI, or put it\n"
        "  on PATH. Get it from a whisper.cpp b#### release:\n"
        "    Windows: whisper-bin-x64.zip\n"
        "    Linux:   whisper-bin-ubuntu-x64.tar.gz\n"
        "    macOS:   no prebuilt binary is published, ever -- build from source\n"
        "             (Xcode Command Line Tools + CMake). See plan section 3.2.\n"
        "  The binary is whisper-cli; 'main' is a deprecated stub and is not this."
    )


def resolve_model(models_dir: Path, name: str) -> Path:
    path = models_dir / ("ggml-" + name + ".bin")
    if path.is_file():
        return path
    bare = models_dir / (name + ".bin")
    if bare.is_file():
        return bare
    die(
        "model '" + name + "' is not in " + str(models_dir) + ".\n"
        "  Expected the file ggml-" + name + ".bin. Download it with:\n"
        "    curl -L -o \"" + str(path) + "\" \\\n"
        "      " + MODEL_URL.format(name=name) + "\n"
        "  Then re-run. Use --models to measure a smaller set."
    )


def audio_duration_seconds(path: Path) -> float | None:
    """Duration in seconds, or None for a container this stdlib cannot read.

    whisper.cpp reads mp3/ogg/flac too, so an unreadable header is not fatal --
    it only means this utterance contributes no realtime factor.
    """
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
    except (wave.Error, EOFError, OSError):
        return None
    if not rate:
        return None
    return frames / float(rate)


def transcribe(binary: Path, model: Path, audio: Path, *, prompt: str | None,
               threads: int, timeout: float) -> Transcription:
    cmd = [str(binary), "-m", str(model), "-f", str(audio),
           "-l", "en", "-t", str(threads), "-np", "-nt"]
    if prompt:
        cmd += ["--prompt", prompt]

    env = dict(os.environ)
    # whisper.cpp ships its shared libraries beside the binary. RPATH usually
    # finds them; on a build without one this is the difference between a
    # transcript and a loader error, and it costs nothing when unneeded.
    lib_var = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
    if sys.platform != "win32":
        existing = env.get(lib_var, "")
        env[lib_var] = str(binary.parent) + (os.pathsep + existing if existing else "")

    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return Transcription("", time.perf_counter() - started, False,
                             "timed out after " + str(int(timeout)) + "s")
    except OSError as exc:
        die("could not run " + str(binary) + ": " + str(exc)
            + "\n  Check it is executable (chmod +x) and built for this machine.")
    elapsed = time.perf_counter() - started

    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        detail = tail[-1] if tail else "no stderr"
        return Transcription("", elapsed, False,
                             "exit " + str(proc.returncode) + ": " + detail)

    text = proc.stdout.decode("utf-8", "replace").strip()
    if not text:
        # whisper-cli EXITS 0 ON AN AUDIO FILE IT CANNOT READ. Measured: a
        # text file renamed to .wav prints "error: failed to read audio file"
        # on stderr, writes nothing to stdout, and returns 0. (A missing model
        # does return 3.) So empty stdout is the only reliable failure signal
        # for a bad recording, and any caller of this binary -- including the
        # product's own subprocess wrapper -- has to check it.
        stderr = proc.stderr.decode("utf-8", "replace")
        errors = [ln for ln in stderr.splitlines() if "error" in ln.lower()]
        if errors:
            return Transcription("", elapsed, False,
                                 "exit 0 but no transcript: " + errors[-1].strip())
        return Transcription("", elapsed, False,
                             "no transcript and no error -- is the recording silent?")
    return Transcription(text, elapsed, True)


# ==========================================================================
# Scoring
# ==========================================================================


@dataclass
class UtteranceResult:
    utterance_id: str
    ok: bool
    error: str = ""
    hypothesis: str = ""
    seconds: float = 0.0
    audio_seconds: float | None = None
    ref_words: int = 0
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0
    term_total: int = 0
    term_hits: int = 0
    misses: tuple[tuple[str, str, str], ...] = ()      # (term, category, heard)
    invented: tuple[tuple[str, str, int], ...] = ()    # (term, category, count)
    primed_marked_terms: int = 0

    @property
    def wer(self) -> float:
        if not self.ref_words:
            return 0.0
        return (self.substitutions + self.deletions + self.insertions) / self.ref_words

    @property
    def realtime_factor(self) -> float | None:
        if not self.audio_seconds:
            return None
        return self.seconds / self.audio_seconds


@dataclass
class ConfigResult:
    model: str
    primed: bool
    model_bytes: int = 0
    results: list[UtteranceResult] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.model + (" + priming" if self.primed else "")

    @property
    def scored(self) -> list[UtteranceResult]:
        return [r for r in self.results if r.ok]

    @property
    def failures(self) -> list[UtteranceResult]:
        return [r for r in self.results if not r.ok]

    @property
    def term_total(self) -> int:
        return sum(r.term_total for r in self.scored)

    @property
    def term_hits(self) -> int:
        return sum(r.term_hits for r in self.scored)

    @property
    def term_recall(self) -> float | None:
        return (self.term_hits / self.term_total) if self.term_total else None

    @property
    def invented_total(self) -> int:
        return sum(count for r in self.scored for _, _, count in r.invented)

    @property
    def term_precision(self) -> float | None:
        produced = self.term_hits + self.invented_total
        return (self.term_hits / produced) if produced else None

    @property
    def invented_drug_or_disease(self) -> int:
        return sum(count for r in self.scored for _, cat, count in r.invented
                   if cat in ("drug_generic", "drug_brand", "disease"))

    @property
    def wer(self) -> float | None:
        words = sum(r.ref_words for r in self.scored)
        if not words:
            return None
        errs = sum(r.substitutions + r.deletions + r.insertions for r in self.scored)
        return errs / words

    @property
    def realtime_factors(self) -> list[float]:
        return [rtf for r in self.scored
                if (rtf := r.realtime_factor) is not None]

    @property
    def median_rtf(self) -> float | None:
        rtfs = self.realtime_factors
        return statistics.median(rtfs) if rtfs else None

    @property
    def max_rtf(self) -> float | None:
        rtfs = self.realtime_factors
        return max(rtfs) if rtfs else None

    @property
    def mean_seconds(self) -> float | None:
        vals = [r.seconds for r in self.scored]
        return statistics.mean(vals) if vals else None


def score_utterance(corpus: Corpus, utt: Utterance, hypothesis: str,
                    *, prompt: str | None = None) -> UtteranceResult:
    """Score one transcript against one reference.  No I/O -- unit testable."""
    norm = corpus.normaliser
    ref = list(utt.ref_tokens)
    hyp = norm.tokens(hypothesis)
    ali = align(ref, hyp)

    term_total = 0
    term_hits = 0
    misses: list[tuple[str, str, str]] = []
    for term in utt.terms:
        ref_spans = find_term_spans(ref, term)
        hyp_count = count_term(hyp, term)
        term_total += len(ref_spans)
        hits = min(hyp_count, len(ref_spans))
        term_hits += hits
        for span in ref_spans[hits:]:
            misses.append((term.text, term.category, heard_instead(ali, span, hyp)))

    # Invented terms are hunted across the WHOLE corpus vocabulary, not this
    # utterance's marked list. Priming's failure mode is inserting a primed word
    # into an utterance that never contained it, and a per-utterance vocabulary
    # cannot see that.  The reference count comes from the reference TEXT, not
    # from the marked list, so a term that legitimately appears unmarked (u07
    # says "two weeks" without marking it) is not reported as an invention.
    invented: list[tuple[str, str, int]] = []
    for term in corpus.vocabulary.values():
        hyp_count = count_term(hyp, term)
        if not hyp_count:
            continue
        spurious = hyp_count - count_term(ref, term)
        if spurious > 0:
            invented.append((term.text, term.category, spurious))
    invented.sort()

    primed_marked = 0
    if prompt:
        prompt_tokens = norm.tokens(prompt)
        primed_marked = sum(1 for term in utt.terms
                            if count_term(prompt_tokens, term) > 0)

    return UtteranceResult(
        utterance_id=utt.id,
        ok=True,
        hypothesis=hypothesis,
        ref_words=len(ref),
        substitutions=ali.substitutions,
        deletions=ali.deletions,
        insertions=ali.insertions,
        term_total=term_total,
        term_hits=term_hits,
        misses=tuple(misses),
        invented=tuple(invented),
        primed_marked_terms=primed_marked,
    )


# ==========================================================================
# Reporting
# ==========================================================================


def _pct(value: float | None) -> str:
    return "-" if value is None else "{:.1f}%".format(value * 100.0)


def _num(value: float | None, fmt: str = "{:.2f}") -> str:
    return "-" if value is None else fmt.format(value)


def _mib(value: int) -> str:
    return "-" if not value else "{:.0f} MiB".format(value / (1024 * 1024))


def render_markdown(corpus: Corpus, configs: Sequence[ConfigResult], *,
                    environment: dict, full: bool = True) -> str:
    lines: list[str] = []
    add = lines.append

    add("## Speech-to-text measurement -- #59 T3")
    add("")
    add("Corpus `" + corpus.corpus_id + "`, " + str(len(corpus.utterances))
        + " utterances. Engine: whisper.cpp `whisper-cli`.")
    add("")
    add("| | |")
    add("|---|---|")
    for key in ("date", "machine", "os", "cpu", "threads", "binary",
                "binary_version", "audio_dir", "corpus"):
        if environment.get(key):
            add("| " + key.replace("_", " ") + " | " + str(environment[key]) + " |")
    add("")

    add("### Headline")
    add("")
    add("Term recall is the number that decides this. WER is reported for "
        "comparability only.")
    add("")
    spoken = sum(count_term(u.ref_tokens, t)
                 for u in corpus.utterances for t in u.terms)
    if spoken:
        # Binomial interval at the bar, so the reader can see how much of a
        # difference between two rows is real.
        half = 1.96 * math.sqrt(0.95 * 0.05 / spoken) * 100
        add("Denominator: **" + str(spoken) + " marked term occurrences** across "
            + str(len(corpus.utterances)) + " utterances. At 95% recall that is "
            "about +/-{:.1f} percentage points, so two rows closer together than "
            "that are not distinguishable by this corpus.".format(half))
        add("")
    add("| Model | Priming | Term recall | Term precision | Invented drug/disease "
        "| WER | Median RTF | Max RTF | Mean s/utt | Model size |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for cfg in configs:
        add("| `" + cfg.model + "` | " + ("on" if cfg.primed else "off") + " | "
            + _pct(cfg.term_recall) + " | " + _pct(cfg.term_precision) + " | "
            + str(cfg.invented_drug_or_disease) + " | " + _pct(cfg.wer) + " | "
            + _num(cfg.median_rtf) + "x | " + _num(cfg.max_rtf) + "x | "
            + _num(cfg.mean_seconds, "{:.1f}") + " | " + _mib(cfg.model_bytes) + " |")
    add("")
    add("RTF is wall-clock seconds divided by audio seconds, for a cold "
        "invocation including model load -- which is what the product does, one "
        "subprocess per recording. Lower is faster; the proposed bar is 0.5x.")
    add("")

    failures = [(cfg, r) for cfg in configs for r in cfg.failures]
    if failures:
        add("### Utterances that did not transcribe")
        add("")
        for cfg, res in failures:
            add("- `" + cfg.label + "` / " + res.utterance_id + ": " + res.error)
        add("")

    add("### Against the proposed bar")
    add("")
    add("Bar (plan section 6, for the owner to confirm): term recall >= 95%, "
        "zero invented drug or disease names, RTF <= 0.5x.")
    add("")
    add("| Model | Best config | Recall | Invented | Max RTF | Verdict |")
    add("|---|---|---|---|---|---|")
    by_model: dict[str, list[ConfigResult]] = {}
    for cfg in configs:
        by_model.setdefault(cfg.model, []).append(cfg)
    for model, cfgs in by_model.items():
        best = max(cfgs, key=lambda c: (c.term_recall or 0.0))
        checks = []
        if (best.term_recall or 0.0) < 0.95:
            checks.append("recall")
        if best.invented_drug_or_disease:
            checks.append("inventions")
        if best.max_rtf is not None and best.max_rtf > 0.5:
            checks.append("speed")
        verdict = "PASSES" if not checks else "fails on " + ", ".join(checks)
        add("| `" + model + "` | priming "
            + ("on" if best.primed else "off") + " | " + _pct(best.term_recall)
            + " | " + str(best.invented_drug_or_disease) + " | "
            + _num(best.max_rtf) + "x | " + verdict + " |")
    add("")

    add("### Priming, on versus off")
    add("")
    add("| Model | Recall unprimed | Recall primed | Delta | Invented unprimed "
        "| Invented primed |")
    add("|---|---|---|---|---|---|")
    for model, cfgs in by_model.items():
        off = next((c for c in cfgs if not c.primed), None)
        on = next((c for c in cfgs if c.primed), None)
        if off is None or on is None:
            continue
        delta = None
        if off.term_recall is not None and on.term_recall is not None:
            delta = on.term_recall - off.term_recall
        add("| `" + model + "` | " + _pct(off.term_recall) + " | "
            + _pct(on.term_recall) + " | "
            + ("-" if delta is None else "{:+.1f} pp".format(delta * 100))
            + " | " + str(off.invented_total) + " | " + str(on.invented_total) + " |")
    add("")
    primed_overlap = sum(r.primed_marked_terms
                         for cfg in configs if cfg.primed for r in cfg.scored)
    if primed_overlap:
        n_primed = sum(len(cfg.scored) for cfg in configs if cfg.primed) or 1
        add("Of the marked terms, an average of {:.1f} per utterance were also in "
            "the priming string. Priming is built from the USMLE outline by topic, "
            "never from the marked-terms list, but the overlap is real and is "
            "reported rather than assumed.".format(primed_overlap / n_primed))
        add("")

    # Which terms failed, across the whole matrix.
    term_misses: dict[tuple[str, str], int] = {}
    term_spoken: dict[tuple[str, str], int] = {}
    for cfg in configs:
        for res in cfg.scored:
            for name, category, _heard in res.misses:
                term_misses[(name, category)] = term_misses.get((name, category), 0) + 1
    for utt in corpus.utterances:
        for term in utt.terms:
            key = (term.text, term.category)
            term_spoken[key] = term_spoken.get(key, 0) + count_term(utt.ref_tokens, term)
    if term_misses:
        n_configs = len(configs) or 1
        add("### Which terms actually broke")
        add("")
        add("Summed over every configuration in the matrix above. A term near "
            "the top is a term this feature cannot currently capture, whatever "
            "model is chosen -- which is more actionable than any single "
            "percentage.")
        add("")
        add("| Term | Category | Attempts | Missed | Miss rate |")
        add("|---|---|---|---|---|")
        for (name, category), missed in sorted(
                term_misses.items(), key=lambda kv: (-kv[1], kv[0][0])):
            attempts = term_spoken.get((name, category), 0) * n_configs
            rate = _pct(missed / attempts) if attempts else "-"
            add("| " + name + " | " + category + " | " + str(attempts) + " | "
                + str(missed) + " | " + rate + " |")
        add("")
        add("Attempts = occurrences in the corpus x " + str(n_configs)
            + " configurations.")
        add("")

    if full:
        add("### Per-utterance detail")
        add("")
        for cfg in configs:
            interesting = [r for r in cfg.scored if r.misses or r.invented]
            if not interesting:
                add("<details><summary><code>" + cfg.label
                    + "</code> -- every marked term survived</summary>")
                add("")
                add("</details>")
                add("")
                continue
            add("<details><summary><code>" + cfg.label + "</code> -- "
                + str(len(interesting)) + " utterance(s) with a problem</summary>")
            add("")
            for res in interesting:
                add("**" + res.utterance_id + "** (WER " + _pct(res.wer)
                    + ", " + _num(res.seconds, "{:.1f}") + "s)")
                add("")
                for name, _category, heard in res.misses:
                    add("- missed `" + name + "` -- heard \"" + heard + "\"")
                for name, category, count in res.invented:
                    add("- INVENTED `" + name + "` (" + category + ") x"
                        + str(count))
                add("")
                add("> " + res.hypothesis)
                add("")
            add("</details>")
            add("")

    return "\n".join(lines) + "\n"


# ==========================================================================
# The read-aloud script, generated from the corpus so the two cannot drift.
# ==========================================================================

_SCRIPT_HEADER = """<!--
GENERATED FILE -- do not edit by hand.

Source: tests/fixtures/stt_vocabulary_terms.json
Regenerate: python scripts/stt_measure.py write-script
Gate:       python scripts/stt_measure.py check-script  (tests/test_stt_measure.py)

The reference transcripts in the JSON are what the scorer compares against, so
an edit here that does not reach the JSON would silently score the recording
against the wrong words.
-->

# Read-aloud script -- speech-to-text measurement (#59, task T3)

This is the corpus for the transcription-accuracy measurement that #59's
acceptance criterion asks for. **It has to be your voice.** A synthetic voice
reading this measures the text-to-speech engine's pronunciation, not whether
this feature works for you.

## Before you start

- **Record where you will actually use the feature.** Same laptop, same room,
  same distance from the microphone, same time of night. If you study with a
  fan on, leave the fan on. The measurement is worthless if it is made under
  conditions the feature will never see.
- **One file per utterance.** {count} files in one directory.
- **Name each file after its utterance id**: `u01.wav`, `u02.wav`, and so on.
  The scorer matches by that name and will tell you which ones it could not
  find.
- **Format: mono WAV.** 16 kHz 16-bit is preferred because it is what the
  engine works in natively. It is *not* required -- whisper.cpp resamples
  internally and accepts wav, flac, mp3 and ogg at any rate -- so if your
  recorder only does 44.1 kHz stereo, use it and do not spend time converting.
- **Read at your normal speaking pace**, the way you would actually talk to the
  app at the end of a question block. Hesitation is realistic. Do not perform.
- **If you fluff a line, re-record that one file.** Do not stitch takes
  together and do not read the whole script again.
- Read the punctuation as pauses, not as words.

The whole thing is about {minutes} minutes of speech. Budget twice that.

## Why {count} utterances and not more

The metric's denominator is **marked terms**, not utterances, and this corpus
carries {terms} of them in {count} readings. That is enough to tell 95% recall
from 90% (about +/-4 percentage points at 95%), which is the distinction the
pass bar actually turns on. Doubling the utterance count would narrow that to
about +/-3 points and double the reading -- and a corpus abandoned at utterance
35 measures nothing at all.

## Pronunciation notes

Some of these are deliberately about *how* an abbreviation is said, so read
them the way the note says. Getting this wrong makes the reference transcript
wrong, which is worse than a bad model.

## The script

"""


def render_script(corpus: Corpus) -> str:
    words = sum(len(u.reference.split()) for u in corpus.utterances)
    terms = sum(count_term(u.ref_tokens, t) for u in corpus.utterances for t in u.terms)
    minutes = max(1, round(words / 150.0))
    out = [_SCRIPT_HEADER.format(count=len(corpus.utterances), terms=terms,
                                 minutes=minutes)]
    for utt in corpus.utterances:
        out.append("### " + utt.id + " -- save as `" + utt.file + "`")
        out.append("")
        if utt.note:
            out.append("> **Note:** " + utt.note)
            out.append("")
        out.append(utt.reference)
        out.append("")
    out.append("---")
    out.append("")
    out.append("When all " + str(len(corpus.utterances))
               + " files exist, run the measurement -- see the module docstring "
                 "of `scripts/stt_measure.py` for the exact command.")
    out.append("")
    return "\n".join(out)


# ==========================================================================
# The embedded proof corpus.
#
# whisper.cpp's samples/jfk.wav: an 11-second excerpt of John F. Kennedy's 1961
# inaugural address, distributed in a repository licensed MIT (the LICENSE in
# the release archive reads "MIT License, Copyright (c) 2023-2026 The ggml
# authors").  The samples README makes no licence claim of its own, so the
# conclusion rests on two things together: the repository's MIT licence, and
# the underlying speech being a work of the United States federal government,
# which is not subject to copyright under 17 U.S.C. 105.  Both routes are
# permissive.  The file is NOT committed to this repository -- fetch it from
# https://github.com/ggml-org/whisper.cpp/raw/master/samples/jfk.wav
# ==========================================================================

_JFK_CORPUS = json.dumps({
    "schema_version": 1,
    "corpus_id": "whisper.cpp-jfk-proof",
    "description": "Single public-domain utterance with a well-known transcript, "
                   "used to prove the harness end to end without a microphone.",
    "normalisation": {
        "applied_in_this_order": [
            "nfkc", "lowercase", "split_joiners", "drop_punctuation", "numbers",
            "units", "letter_runs", "disfluencies", "collapse_whitespace",
        ],
        "unit_map": {},
        "disfluencies": ["um", "uh"],
    },
    "term_variants": {"Americans": ["american"]},
    "priming": {
        "frame": "A recording of a political speech. Terms:",
        "token_budget": 223,
        "base_terms": ["inaugural address", "citizens", "freedom", "nation"],
    },
    "utterances": [{
        "id": "jfk",
        "file": "jfk.wav",
        "category": "control",
        "priming_entry_terms": ["fellow Americans", "country"],
        "reference": "And so my fellow Americans, ask not what your country can do "
                     "for you, ask what you can do for your country.",
        "terms": [
            {"text": "Americans", "category": "concept"},
            {"text": "country", "category": "concept"},
        ],
    }],
})


# ==========================================================================
# CLI
# ==========================================================================


def _binary_version(binary: Path) -> str:
    """The engine version, for the report.

    Recorded because #135 is this project's standing lesson about version
    drift: a Windows machine shipped Chromium 134 while every test ran 130, and
    nothing in the artefact said so.  An accuracy measurement with no engine
    version attached has the same hole.
    """
    for args in (["--version"], ["--help"]):
        try:
            proc = subprocess.run([str(binary), *args], capture_output=True,
                                  timeout=30)
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        blob = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        match = re.search(r"whisper\.cpp version:?[^\n]*", blob)
        if match:
            return match.group(0).strip()
    return "unknown"


def cmd_run(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus)
    binary = resolve_binary(args.whisper_cli)

    models_dir = Path(args.models_dir).expanduser() if args.models_dir else None
    if models_dir is None:
        env = os.environ.get("WHISPER_MODELS_DIR")
        models_dir = Path(env).expanduser() if env else None
    if models_dir is None or not models_dir.is_dir():
        die("no model directory.\n"
            "  Pass --models-dir DIR (or set WHISPER_MODELS_DIR). DIR holds the\n"
            "  ggml-*.bin files; download them from\n"
            "    " + MODEL_URL.format(name="<model>"))

    audio_dir = Path(args.audio_dir).expanduser()
    if not audio_dir.is_dir():
        die("no audio directory at " + str(audio_dir) + ".\n"
            "  --audio-dir is where your recordings are: one file per utterance,\n"
            "  named after the utterance id (u01.wav, u02.wav, ...). See\n"
            "  tests/fixtures/stt_vocabulary_script.md.")

    # Resolve audio up front, so a naming mistake is reported before a
    # half-hour of transcription rather than after it.
    pairs: list[tuple[Utterance, Path]] = []
    missing: list[str] = []
    empty: list[str] = []
    for utt in corpus.utterances:
        found = None
        for suffix in AUDIO_SUFFIXES:
            candidate = audio_dir / (Path(utt.file).stem + suffix)
            if candidate.is_file():
                found = candidate
                break
        if found is None:
            missing.append(utt.file)
            continue
        if found.stat().st_size == 0:
            empty.append(found.name)
            continue
        duration = audio_duration_seconds(found)
        if duration is not None and duration < 0.2:
            empty.append(found.name + " (" + "{:.2f}".format(duration) + "s)")
            continue
        pairs.append((utt, found))

    if empty:
        print("stt_measure: skipping empty or near-empty recordings: "
              + ", ".join(empty), file=sys.stderr)
    if missing:
        print("stt_measure: no recording found for: " + ", ".join(missing),
              file=sys.stderr)
        print("  Expected <id>.wav in " + str(audio_dir)
              + " (.flac/.mp3/.ogg also accepted).", file=sys.stderr)
    if not pairs:
        die("none of the corpus utterances have a recording in " + str(audio_dir)
            + ".\n  Check the filenames: they must be u01.wav, u02.wav, and so on.")
    # An empty recording counts as incomplete too. Silently measuring 21 of 24
    # because three files came out zero-length is how a partial result gets
    # reported as a whole one.
    short_by = len(missing) + len(empty)
    if short_by and not args.allow_partial:
        die(str(short_by) + " of " + str(len(corpus.utterances))
            + " recordings are missing or empty (listed above).\n"
              "  Record them, or pass --allow-partial to measure on what exists\n"
              "  (the report will then say the run was partial).")

    known = {Path(u.file).stem for u in corpus.utterances}
    strays = sorted(p.name for p in audio_dir.iterdir()
                    if p.suffix.lower() in AUDIO_SUFFIXES and p.stem not in known)
    if strays:
        print("stt_measure: ignoring files that match no utterance id: "
              + ", ".join(strays), file=sys.stderr)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    priming_modes: list[bool]
    if args.priming == "on":
        priming_modes = [True]
    elif args.priming == "off":
        priming_modes = [False]
    else:
        priming_modes = [False, True]

    model_paths = {name: resolve_model(models_dir, name) for name in models}

    configs: list[ConfigResult] = []
    total = len(models) * len(priming_modes) * len(pairs)
    done = 0
    for name in models:
        model_path = model_paths[name]
        for primed in priming_modes:
            cfg = ConfigResult(model=name, primed=primed,
                               model_bytes=model_path.stat().st_size)
            for utt, audio in pairs:
                done += 1
                prompt = build_prompt(corpus, utt) if primed else None
                print("[{}/{}] {} priming={} {}".format(
                    done, total, name, "on" if primed else "off", utt.id),
                    file=sys.stderr)
                out = transcribe(binary, model_path, audio, prompt=prompt,
                                 threads=args.threads, timeout=args.timeout)
                if not out.ok:
                    cfg.results.append(UtteranceResult(
                        utterance_id=utt.id, ok=False, error=out.error,
                        seconds=out.seconds))
                    continue
                res = score_utterance(corpus, utt, out.text, prompt=prompt)
                res.seconds = out.seconds
                res.audio_seconds = audio_duration_seconds(audio)
                cfg.results.append(res)
            configs.append(cfg)

    environment = {
        "date": time.strftime("%Y-%m-%d %H:%M %Z"),
        "machine": platform.node(),
        "os": platform.platform(),
        "cpu": (platform.processor() or platform.machine())
               + " (" + str(os.cpu_count()) + " logical)",
        "threads": args.threads,
        "binary": str(binary),
        "binary_version": _binary_version(binary),
        "audio_dir": str(audio_dir),
        "corpus": corpus.corpus_id + (" (PARTIAL: " + str(len(pairs)) + "/"
                                      + str(len(corpus.utterances))
                                      + " utterances)" if short_by else ""),
    }

    markdown = render_markdown(corpus, configs, environment=environment,
                               full=not args.brief)
    if args.out:
        Path(args.out).expanduser().write_text(markdown, encoding="utf-8")
        print("stt_measure: wrote " + str(args.out), file=sys.stderr)
    else:
        print(markdown)

    if args.json_out:
        payload = {
            "environment": environment,
            "corpus": corpus.corpus_id,
            "configs": [{
                "model": c.model,
                "primed": c.primed,
                "model_bytes": c.model_bytes,
                "term_recall": c.term_recall,
                "term_precision": c.term_precision,
                "wer": c.wer,
                "invented_total": c.invented_total,
                "invented_drug_or_disease": c.invented_drug_or_disease,
                "median_rtf": c.median_rtf,
                "max_rtf": c.max_rtf,
                "mean_seconds": c.mean_seconds,
                "utterances": [{
                    "id": r.utterance_id, "ok": r.ok, "error": r.error,
                    "hypothesis": r.hypothesis, "seconds": r.seconds,
                    "audio_seconds": r.audio_seconds, "wer": r.wer,
                    "term_total": r.term_total, "term_hits": r.term_hits,
                    "ref_words": r.ref_words,
                    "substitutions": r.substitutions,
                    "deletions": r.deletions,
                    "insertions": r.insertions,
                    "primed_marked_terms": r.primed_marked_terms,
                    "misses": [list(m) for m in r.misses],
                    "invented": [list(i) for i in r.invented],
                } for r in c.results],
            } for c in configs],
        }
        Path(args.json_out).expanduser().write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
        print("stt_measure: wrote " + str(args.json_out), file=sys.stderr)

    # The report is always written -- a partial result is still a result, and
    # the transcription time has already been spent.  But a run where nothing
    # transcribed at all exits non-zero, so it cannot be mistaken for a
    # measurement by anything reading the exit code.
    if not any(cfg.scored for cfg in configs):
        print("stt_measure: not one utterance transcribed. The report above "
              "lists why for each one.", file=sys.stderr)
        return 1
    return 0


def cmd_write_script(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus)
    target = Path(args.script)
    target.write_text(render_script(corpus), encoding="utf-8")
    print("stt_measure: wrote " + str(target), file=sys.stderr)
    return 0


def cmd_check_script(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus)
    target = Path(args.script)
    if not target.is_file():
        print("stt_measure: " + str(target) + " does not exist. Run:\n"
              "  python scripts/stt_measure.py write-script", file=sys.stderr)
        return 1
    expected = render_script(corpus)
    if target.read_text(encoding="utf-8") != expected:
        print("stt_measure: " + str(target) + " is out of date with "
              + str(args.corpus) + ". Run:\n"
              "  python scripts/stt_measure.py write-script", file=sys.stderr)
        return 1
    print("stt_measure: read-aloud script is in sync.", file=sys.stderr)
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    """Scorer sanity check with no binary, no model and no audio."""
    corpus = load_corpus(args.corpus)
    print("corpus: " + corpus.corpus_id)
    print("utterances: " + str(len(corpus.utterances)))
    occurrences = sum(count_term(u.ref_tokens, t)
                      for u in corpus.utterances for t in u.terms)
    print("marked term occurrences: " + str(occurrences))
    print("distinct marked terms: " + str(len(corpus.vocabulary)))
    words = sum(len(u.ref_tokens) for u in corpus.utterances)
    print("reference words: " + str(words)
          + " (about {:.1f} minutes at 150 wpm)".format(words / 150.0))

    sample = corpus.utterances[min(1, len(corpus.utterances) - 1)]
    prompt = build_prompt(corpus, sample)
    print("")
    print("priming prompt for " + sample.id + ": "
          + str(estimate_tokens(prompt)) + " estimated tokens / budget "
          + str(corpus.token_budget) + ", " + str(len(prompt)) + " chars")
    print("  tail: ..." + prompt[-160:])

    # A perfect transcript must score 100% / 0% WER; a mangled one must not.
    perfect = score_utterance(corpus, sample, sample.reference)
    assert perfect.term_hits == perfect.term_total, "perfect transcript lost a term"
    assert perfect.wer == 0.0, "perfect transcript has nonzero WER"
    print("")
    print("perfect transcript: recall "
          + str(perfect.term_hits) + "/" + str(perfect.term_total)
          + ", WER 0.0% -- OK")

    mangled = score_utterance(corpus, sample, "totally different words entirely")
    assert mangled.term_hits == 0, "mangled transcript kept a term"
    assert mangled.wer > 0.5, "mangled transcript has a suspiciously low WER"
    print("mangled transcript: recall 0/" + str(mangled.term_total)
          + ", WER " + _pct(mangled.wer) + " -- OK")
    print("")
    print("scorer self-test passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stt_measure",
        description="Measure whisper.cpp transcription accuracy on exam-domain "
                    "vocabulary (#59 T3).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Recording instructions: tests/fixtures/stt_vocabulary_script.md",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_corpus(p: argparse.ArgumentParser) -> None:
        p.add_argument("--corpus", default=str(DEFAULT_CORPUS),
                       help="marked-terms JSON, or the literal 'jfk' for the "
                            "built-in public-domain proof corpus")

    run = sub.add_parser("run", help="transcribe and score the matrix")
    add_corpus(run)
    run.add_argument("--audio-dir", required=True,
                     help="directory of recordings, one file per utterance id")
    run.add_argument("--whisper-cli", default=None,
                     help="path to whisper-cli (or set WHISPER_CLI)")
    run.add_argument("--models-dir", default=None,
                     help="directory of ggml-*.bin files (or set WHISPER_MODELS_DIR)")
    run.add_argument("--models", default=",".join(DEFAULT_MODELS),
                     help="comma-separated model names (default: %(default)s)")
    run.add_argument("--priming", choices=("both", "on", "off"), default="both")
    run.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    run.add_argument("--timeout", type=float, default=600.0,
                     help="seconds per transcription before giving up")
    run.add_argument("--out", default=None, help="write the Markdown report here")
    run.add_argument("--json-out", default=None, help="write the full results as JSON")
    run.add_argument("--brief", action="store_true",
                     help="omit the per-utterance appendix")
    run.add_argument("--allow-partial", action="store_true",
                     help="measure even though some recordings are missing")
    run.set_defaults(func=cmd_run)

    write = sub.add_parser("write-script",
                           help="regenerate the read-aloud script from the corpus")
    add_corpus(write)
    write.add_argument("--script", default=str(DEFAULT_SCRIPT))
    write.set_defaults(func=cmd_write_script)

    check = sub.add_parser("check-script",
                           help="verify the read-aloud script matches the corpus")
    add_corpus(check)
    check.add_argument("--script", default=str(DEFAULT_SCRIPT))
    check.set_defaults(func=cmd_check_script)

    test = sub.add_parser("self-test",
                          help="validate the corpus and the scorer, no audio needed")
    add_corpus(test)
    test.set_defaults(func=cmd_self_test)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
