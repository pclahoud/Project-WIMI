# Psychometric Assessment Implementation Plan

**Status:** Proposed — drafted 2026-05-15
**Created:** 2026-05-15
**Companion docs:** `docs/planning/MIGRATION_RUNNER.md` (migration conventions), `docs/planning/WEIGHT_ALLOCATION_IMPLEMENTATION_PLAN.md` (plan style reference), `docs/planning/FUTURE_VISION.md` (where the moderator-research substrate is parked), `docs/planning/TEST_INFRASTRUCTURE.md` (regression framework)

This document concretizes the rollout of a one-time onboarding psychometric battery (with periodic re-measurement) covering **Need for Cognition (NFC)**, the three-factor **Learning Goal Orientation (LGO)**, and four **Personal Importance** subscales (exam / clinical / mastery / reflection). The feature is **passive-recording only** for v1 — scores are persisted and exposed by API, but no UI surface outside the assessment page itself adapts to them. The downstream consumers (adaptive reflection prompts, weight-budget nudges, the "moderator-aware" analytics view) are deliberately out of scope and will land in follow-up plans.

## Why this feature exists

Anseel, Lievens, and Schollaert (2009, *Organizational Behavior and Human Decision Processes*, 110(1):23–35) is the canonical meta-analysis showing that the reflective-learning effect on performance is moderated by individual differences. Their pooled effect sizes for the moderators we care about: **NFC r = .20**, **LGO r = .19**, and **personal importance r = .16**, each significant at p<.01 across k≥7 studies. These three constructs are *the* substrate WIMI needs to one day deliver moderator-aware reflection prompts and personalized study allocation (per the moderator-research thread parked in `FUTURE_VISION.md`). v1 makes the measurement happen and stores the data, nothing more. The empirical justification for measuring before adapting is exactly that: without a stored per-user score, no future adaptive surface has a signal to key on, and retro-fitting the measurement after the adaptive UX has shipped is structurally worse than landing the substrate first.

## Glossary and Conventions

- **Instrument version** = a string tag (`v1`, `v2`, …) stamped on every administration. It points to a fixture directory (`src/database/fixtures/assessments/v1/`) containing the item set, scoring rules, and attention-check positions. Changing wording or item count requires a new version string and a new fixture directory; rescoring an existing administration against a new version is **not** supported in v1 (deferred — captured in §Risks).
- **Administration** = one row in `user_assessments`. A user can have N administrations; the latest non-completed one is the "in-flight" administration. `is_complete=TRUE` rows are immutable.
- **Item code** = the stable identifier for one questionnaire item, scoped to the instrument version. Format: `<subscale>_<NN>` (e.g., `nfc_07`, `lgo_prove_03`, `imp_exam_01`, `atc_01`). Item codes are the durable key — prompt text is mutable but item codes are not.
- **Reverse-scored** = an item whose raw response is mirrored across the scale midpoint before being summed into its subscale total. NFC has ~16 reverse-keyed items per Cacioppo & Petty (1982); LGO and Personal Importance have none.
- **Attention check** = an instructed-response item ("Please select strongly disagree for this item") used as a data-quality flag, not as a scoring item.
- **Cadence** = the re-measurement interval in days, stored per-user, range 30–730, default 180.
- **Snooze** = a user-initiated postponement that pushes `next_due_at` forward without resetting the cadence.

Architecture reminder: `UserDatabase` and `DatabaseBridge` are mixin compositions. New methods land in domain mixins (`assessments.py` on the database side, `assessment.py` on the bridge side). Mixins never import each other; cross-domain calls go through `self.*`.

## Item provenance and IP

**Read before drafting any item content.** Two of the three sections in this battery are copyrighted scales whose item text WIMI must not reproduce without proper attribution and licensing:

| Section | Source | Citation | Reproduction status |
|---|---|---|---|
| NFC (34 items) | Cacioppo, J. T., & Petty, R. E. (1982) | *Journal of Personality and Social Psychology*, 42(1), 116–131. The 18-item short form (Cacioppo, Petty, & Kao 1984) is the more commonly cited variant; the project owner has chosen the original 34-item form. | Item text is copyrighted to APA. Do not commit verbatim wording to the repo until the project owner has confirmed permissions or licensed access. |
| LGO (13 items: 5 learning + 4 prove + 4 avoid) | VandeWalle, D. (1997) | *Educational and Psychological Measurement*, 57(6), 995–1015. | Item text is copyrighted to SAGE. Do not commit verbatim wording to the repo until the project owner has confirmed permissions or licensed access. |
| Personal Importance (8 items, 4 subscales × 2 items) | Original to WIMI (this plan) | This document. | Free to commit verbatim — see Stage 0 fixture content. |

**Mechanism:** every NFC and LGO item ships in the fixture as a **placeholder stub** with `prompt: "[POPULATE FROM <citation>]"`. The fixture's structure, scoring rules, reverse-score map, and item codes are committable from day one; only the prompt strings remain stubs until the project owner replaces them. **Tests assert on `item_code`, scoring math, subscale aggregation, and reverse-score handling — never on prompt wording** — so the test suite passes regardless of whether the stubs have been populated. A pre-launch checklist (Stage 7) gates the public release on the stubs being replaced and on `LICENSES.md` having the right attribution lines.

**Attribution surface:** a Credits section inside the assessment UI footer ("This battery includes items from Cacioppo & Petty (1982) and VandeWalle (1997). Used with permission / public-domain claim / under fair-use for personal-use software — finalize this language in Stage 7 once licensing posture is settled.") plus a top-level `LICENSES.md` entry stating the same. Citation footer renders from a `credits` block in `manifest.json`, never hard-coded in HTML.

## Storage Schema (Locked)

Three tables, all created by migration **`m008_assessments`**. Current head is m007 (`exam_length_triple`), so v8 is the next slot.

### `user_assessments` — one row per administration

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `user_id` | INTEGER NOT NULL | No FK in the per-user DB (user_id is a tautology in per-user DBs; we store it for cross-DB export symmetry). |
| `instrument_version` | TEXT NOT NULL | e.g., `"v1"`. Points to a fixture directory. |
| `started_at` | TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| `completed_at` | TIMESTAMP | NULL until completion. |
| `completion_time_ms` | INTEGER | NULL until completion. Wallclock total from `started_at` to `completed_at`. |
| `attention_check_pass` | INTEGER (BOOL) | NULL until completion; TRUE if all attention checks were answered as instructed. |
| `nfc_total` | REAL | Mean of 34 NFC items after reverse-scoring. Range 1.0–5.0. |
| `lgo_learning` | REAL | Mean of 5 learning-goal items. Range 1.0–6.0. |
| `lgo_prove` | REAL | Mean of 4 prove-goal items. Range 1.0–6.0. |
| `lgo_avoid` | REAL | Mean of 4 avoid-goal items. Range 1.0–6.0. |
| `importance_exam` | REAL | Mean of 2 items. Range 1.0–7.0. |
| `importance_clinical` | REAL | Mean of 2 items. Range 1.0–7.0. |
| `importance_mastery` | REAL | Mean of 2 items. Range 1.0–7.0. |
| `importance_reflection` | REAL | Mean of 2 items. Range 1.0–7.0. |
| `is_complete` | INTEGER (BOOL) NOT NULL DEFAULT 0 | Set TRUE in `finish_assessment`. Immutable once TRUE. |

Indexes:

- `idx_user_assessments_user_complete ON (user_id, is_complete, completed_at DESC)` — drives the "latest scores" read and the history page.
- `idx_user_assessments_in_flight ON (user_id, is_complete) WHERE is_complete = 0` — partial index speeds up the "resume in-flight administration" lookup (rare but possible after a crash mid-assessment).

### `user_assessment_responses` — one row per item per administration

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `assessment_id` | INTEGER NOT NULL REFERENCES `user_assessments(id)` ON DELETE CASCADE | |
| `item_code` | TEXT NOT NULL | Matches the fixture's `item_code`. |
| `raw_response` | INTEGER NOT NULL | The integer Likert value as the user selected it (1–5, 1–6, or 1–7 depending on subscale). Reverse-scoring is applied **at scoring time**, never to the stored raw value. |
| `response_time_ms` | INTEGER | Wallclock ms between when the item became visible and when the user advanced past it. |
| `answered_at` | TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP | |

Indexes:

- `idx_responses_assessment ON (assessment_id, item_code)` — UNIQUE composite. Prevents a user from submitting the same item twice within one administration; `submit_response` does an UPSERT against this.
- `idx_responses_by_item_code ON (item_code)` — future psychometric analyses (item difficulty, reliability) will key on this; cheap to add now.

### `user_assessment_preferences` — singleton per user

| Column | Type | Notes |
|---|---|---|
| `user_id` | INTEGER PRIMARY KEY | One row per user. |
| `cadence_days` | INTEGER NOT NULL DEFAULT 180 CHECK(cadence_days BETWEEN 30 AND 730) | |
| `next_due_at` | TIMESTAMP | NULL until the first administration completes; thereafter `completed_at + cadence_days`. |
| `last_snoozed_at` | TIMESTAMP | NULL if never snoozed. |
| `snooze_count` | INTEGER NOT NULL DEFAULT 0 | Lifetime snooze count across all administrations. |

Index: none beyond the implicit PK. Reads are always user-scoped and trivial.

**Why three tables, not two:** preferences are user-scoped and orthogonal to administrations (cadence persists when the latest administration is deleted; an administration's existence shouldn't be a precondition for setting a cadence). Keeping them apart also lets the dashboard banner query `user_assessment_preferences` and `user_assessments` independently — one is a singleton read and one is an ORDER BY DESC LIMIT 1.

## Fixture Format (`src/database/fixtures/assessments/v1/`)

The fixture is structurally the source of truth for what each version of the instrument looks like. The database stores **raw responses keyed by `item_code`**, and the scoring math reads the fixture at scoring time to know which items are reverse-keyed, which subscale they belong to, and what the scale range is. This separation means a typo correction in v1's wording does NOT require a migration — the wording lives in the fixture, the responses live in the DB keyed by `item_code`.

Five JSON files plus a manifest:

- `manifest.json` — top-level metadata, scoring rules per subscale, attention-check positions, credits block, schema version.
- `nfc.json` — 34 NFC items as a list of `{item_code, prompt, reverse_scored}`. Likert scale defined once in the manifest, not per-item.
- `lgo.json` — 13 LGO items as a list of `{item_code, prompt, subscale}` where `subscale ∈ {"learning","prove","avoid"}`.
- `importance.json` — 8 Personal Importance items as a list of `{item_code, prompt, subscale}` where `subscale ∈ {"exam","clinical","mastery","reflection"}`.
- `attention_checks.json` — 2 attention-check items as a list of `{item_code, prompt, expected_response, insert_after_item_code}` — the latter pins the check to a specific position in the rendered flow.

### `manifest.json` shape (canonical for v1)

```json
{
  "instrument_version": "v1",
  "schema_version": 1,
  "title": "WIMI Onboarding Self-Report",
  "subscales": {
    "nfc":                { "likert": 5, "score": "mean",  "file": "nfc.json",        "items": 34 },
    "lgo_learning":       { "likert": 6, "score": "mean",  "file": "lgo.json",        "items": 5,  "subscale_filter": "learning" },
    "lgo_prove":          { "likert": 6, "score": "mean",  "file": "lgo.json",        "items": 4,  "subscale_filter": "prove" },
    "lgo_avoid":          { "likert": 6, "score": "mean",  "file": "lgo.json",        "items": 4,  "subscale_filter": "avoid" },
    "importance_exam":    { "likert": 7, "score": "mean",  "file": "importance.json", "items": 2,  "subscale_filter": "exam" },
    "importance_clinical":{ "likert": 7, "score": "mean",  "file": "importance.json", "items": 2,  "subscale_filter": "clinical" },
    "importance_mastery": { "likert": 7, "score": "mean",  "file": "importance.json", "items": 2,  "subscale_filter": "mastery" },
    "importance_reflection":{"likert": 7,"score": "mean",  "file": "importance.json", "items": 2,  "subscale_filter": "reflection" }
  },
  "attention_checks": { "file": "attention_checks.json", "items": 2 },
  "section_order": ["nfc", "lgo", "importance"],
  "credits": {
    "nfc":  "Need for Cognition Scale — Cacioppo & Petty (1982), J. Personality Soc. Psych., 42(1), 116–131.",
    "lgo":  "Learning Goal Orientation Scale — VandeWalle (1997), Ed. Psych. Meas., 57(6), 995–1015.",
    "importance": "Personal Importance items — original to WIMI; CC-BY-4.0."
  }
}
```

### `importance.json` (verbatim, can ship at commit)

The 8 Personal Importance items are original to WIMI and licenseable under CC-BY-4.0:

| `item_code` | Subscale | Prompt |
|---|---|---|
| `imp_exam_01` | exam | "Doing well on my upcoming high-stakes exam is one of my top priorities right now." |
| `imp_exam_02` | exam | "My score on this exam is something I care deeply about." |
| `imp_clinical_01` | clinical | "Becoming a genuinely competent clinician matters to me far more than any individual grade." |
| `imp_clinical_02` | clinical | "I think often about the kind of doctor I want to become." |
| `imp_mastery_01` | mastery | "Truly understanding the material is more important to me than simply passing." |
| `imp_mastery_02` | mastery | "Mastering the content — not just memorizing enough to pass — is central to why I study." |
| `imp_reflection_01` | reflection | "Taking time to think carefully about my mistakes is worth the effort." |
| `imp_reflection_02` | reflection | "Reflecting on what I got wrong is one of the most valuable things I can do as a learner." |

All 7-point Likert anchored 1 = Strongly disagree … 7 = Strongly agree. All positively keyed.

### `nfc.json` and `lgo.json` shape (with placeholder prompts)

```json
[
  {"item_code": "nfc_01", "prompt": "[POPULATE FROM Cacioppo & Petty 1982]", "reverse_scored": false},
  {"item_code": "nfc_02", "prompt": "[POPULATE FROM Cacioppo & Petty 1982]", "reverse_scored": true},
  ...
]
```

```json
[
  {"item_code": "lgo_learning_01", "prompt": "[POPULATE FROM VandeWalle 1997]", "subscale": "learning"},
  {"item_code": "lgo_prove_01",    "prompt": "[POPULATE FROM VandeWalle 1997]", "subscale": "prove"},
  {"item_code": "lgo_avoid_01",    "prompt": "[POPULATE FROM VandeWalle 1997]", "subscale": "avoid"},
  ...
]
```

The **exact set of reverse-keyed NFC items** is the published reverse-key map from Cacioppo & Petty (1982); ship the boolean flags committed (they are method, not item text — not copyrightable on their own), so tests against the scoring math can run even with placeholder prompts.

### `attention_checks.json` (verbatim)

```json
[
  {"item_code": "atc_01", "prompt": "To show you are paying attention, please select 'Disagree' for this item.", "expected_response": 2, "scale": "likert_5", "insert_after_item_code": "nfc_17"},
  {"item_code": "atc_02", "prompt": "Please select 'Slightly agree' for this item.", "expected_response": 4, "scale": "likert_6", "insert_after_item_code": "lgo_learning_03"}
]
```

Position rationale: one mid-NFC (after item 17 of 34) and one mid-LGO (after item 3 of 13). Both well past the warm-up but before fatigue.

---

## Stage 0 — Migration, Fixture Skeleton, Scoring Math

### Purpose

Land the substrate: the `m008_assessments` migration, the `v1` fixture directory with stubs in place, and a pure-Python scoring module that is fully unit-tested in isolation before any other code knows about it. After Stage 0, the schema is in production but nothing reads or writes to it yet — this is intentional. Decoupling the substrate from the consumers means a Stage 0 regression can be caught with `pytest tests/database/migrations/` before any bridge work begins.

### Dependencies

- None on the assessment side. Migration runner is already in production via `MIGRATION_RUNNER.md`.
- Current migration head is **m007** (`exam_length_triple`). `m008_assessments` slots in as the next version.

### Database changes

New migration `src/database/migrations/user/m008_assessments.py`. Idempotent via standard `CREATE TABLE IF NOT EXISTS` and (where applicable) `add_column_if_missing`. The body is three `CREATE TABLE IF NOT EXISTS` statements plus index creation; no data movement, no ALTER on existing tables.

```sql
CREATE TABLE IF NOT EXISTS user_assessments (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               INTEGER NOT NULL,
    instrument_version    TEXT NOT NULL,
    started_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at          TIMESTAMP,
    completion_time_ms    INTEGER,
    attention_check_pass  INTEGER,
    nfc_total             REAL,
    lgo_learning          REAL,
    lgo_prove             REAL,
    lgo_avoid             REAL,
    importance_exam       REAL,
    importance_clinical   REAL,
    importance_mastery    REAL,
    importance_reflection REAL,
    is_complete           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_user_assessments_user_complete
    ON user_assessments (user_id, is_complete, completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_assessments_in_flight
    ON user_assessments (user_id, is_complete)
    WHERE is_complete = 0;

CREATE TABLE IF NOT EXISTS user_assessment_responses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id   INTEGER NOT NULL REFERENCES user_assessments(id) ON DELETE CASCADE,
    item_code       TEXT NOT NULL,
    raw_response    INTEGER NOT NULL,
    response_time_ms INTEGER,
    answered_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (assessment_id, item_code)
);

CREATE INDEX IF NOT EXISTS idx_responses_assessment
    ON user_assessment_responses (assessment_id, item_code);
CREATE INDEX IF NOT EXISTS idx_responses_by_item_code
    ON user_assessment_responses (item_code);

CREATE TABLE IF NOT EXISTS user_assessment_preferences (
    user_id         INTEGER PRIMARY KEY,
    cadence_days    INTEGER NOT NULL DEFAULT 180
                    CHECK (cadence_days BETWEEN 30 AND 730),
    next_due_at     TIMESTAMP,
    last_snoozed_at TIMESTAMP,
    snooze_count    INTEGER NOT NULL DEFAULT 0
);
```

### Fixture deliverables

`src/database/fixtures/assessments/v1/`:

- `manifest.json` — shape per the §Fixture Format section above.
- `nfc.json` — 34 stub rows, with the correct reverse-score flags filled in. Prompt fields are `"[POPULATE FROM Cacioppo & Petty 1982]"`.
- `lgo.json` — 13 stub rows, with correct subscale tags. Prompt fields are `"[POPULATE FROM VandeWalle 1997]"`.
- `importance.json` — 8 rows with **verbatim** prompts per the §Storage Schema table above.
- `attention_checks.json` — 2 rows with verbatim prompts and expected responses.

### Scoring module

New file `src/database/domains/_assessment_scoring.py` (underscore prefix indicates "support module, not a mixin"). Pure functions, no SQLite dependency, so the unit tests are sub-millisecond:

```python
def score_administration(
    responses: dict[str, int],
    fixture: AssessmentFixture,
) -> AssessmentScores:
    """Compute all subscale scores for one administration's raw responses.

    Args:
        responses: {item_code: raw_response} mapping.
        fixture:  Loaded manifest + item files.

    Returns:
        AssessmentScores dataclass with nfc_total, lgo_learning, lgo_prove,
        lgo_avoid, importance_exam, importance_clinical, importance_mastery,
        importance_reflection, attention_check_pass — all floats except the
        last which is bool. Returns None for any subscale whose items are
        all missing (allows partial-completion edge case in resumption).

    Reverse-scoring: applied at score time. For a 5-point item with
    raw_response=4 marked reverse_scored=True, the contributing value is
    (5 + 1 - 4) = 2 — i.e., (max + min - raw).
    """
```

Helper `load_fixture(version: str) -> AssessmentFixture` resolves the fixture directory using the frozen-mode pattern from `CLAUDE.md`:

```python
if getattr(sys, 'frozen', False):
    base_path = Path(sys.executable).parent / '_internal'
else:
    base_path = Path(__file__).parent.parent  # src/database/
fixture_dir = base_path / 'fixtures' / 'assessments' / version
```

### Files to create

- `src/database/migrations/user/m008_assessments.py`
- `src/database/migrations/user/__init__.py` — register the new migration (append `build_migration(m008_assessments)`)
- `src/database/fixtures/assessments/v1/manifest.json`
- `src/database/fixtures/assessments/v1/nfc.json`
- `src/database/fixtures/assessments/v1/lgo.json`
- `src/database/fixtures/assessments/v1/importance.json`
- `src/database/fixtures/assessments/v1/attention_checks.json`
- `src/database/domains/_assessment_scoring.py`

### Files to modify

- `src/database/migrations/user/__init__.py`

### Bridge / JS / UI

None in this stage.

### Test strategy

`tests/database/migrations/test_user_008_assessments.py`:

- Apply migration v8 to a v7 DB. Assert all three tables exist via `PRAGMA table_info`.
- Apply migration v8 a second time — must be a no-op (idempotency).
- Assert the partial index `idx_user_assessments_in_flight` exists.
- Assert the CHECK constraint on `cadence_days` rejects 29 and 731.
- Assert the UNIQUE constraint on `(assessment_id, item_code)` rejects duplicates.

`tests/database/test_assessment_scoring.py`:

- Reverse-scoring math: a 5-point Likert with `raw=4, reverse_scored=True` contributes 2.0; `raw=1, reverse_scored=True` contributes 5.0.
- All-1s NFC responses (all reverse-keyed items at 1, all non-reverse at 1) → expected mean reflects the reverse split.
- LGO mean is computed per subscale, NOT pooled across subscales.
- Importance mean treats missing items as None for that subscale.
- Attention check pass: both checks answered as instructed → True; one off → False; both off → False; either skipped → False.
- Fixture loader resolves both dev mode and frozen mode (mock `sys.frozen`).
- Fixture loader rejects an unknown version with `FileNotFoundError`.
- Loading the v1 fixture: all 34 NFC items present, 13 LGO items present (5+4+4), 8 importance items present (2+2+2+2), 2 attention checks present. Assert counts only; do **not** assert prompt strings.

Coverage target: 90% on the scoring module (small, easy to cover exhaustively).

### Risk and rollback

- Migration is purely additive — rollback is "ignore the new tables" (the data-bearing code doesn't land until Stage 1). If Stage 0 is reverted, the migration runner won't re-run v8 because the ledger still records it; this is OK because the unused tables don't cost anything to keep, and re-landing Stage 0 would no-op the schema and only need to re-add the source files.
- Fixture format is a contract change: if Stage 1+ relies on the v1 layout and Stage 0 ships a slightly different layout, every consumer breaks at once. Mitigate by writing the scoring module first (Stage 0 deliverable) so the fixture format is forced to be consumer-tested before any other code is written against it.

### Effort

Small (1 day). Mostly fixture data entry and migration boilerplate.

---

## Stage 1 — `AssessmentsMixin` (Database CRUD + Scoring + Preferences)

### Purpose

The full backend surface. After Stage 1, the assessment can be exercised end-to-end from a Python REPL: start an administration, submit each response, finish, read back the scores. The bridge layer doesn't exist yet, but every method that the bridge will eventually delegate to is implemented and tested.

### Dependencies

- Stage 0 (migration, fixture, scoring module).

### Files to create

- `src/database/domains/assessments.py` — new mixin `AssessmentsMixin`.

### Files to modify

- `src/database/domains/__init__.py` — export `AssessmentsMixin`.
- `src/database/user_db.py` — add `AssessmentsMixin` to the `UserDatabase` composition list. Insert in the mixin chain after `PreferencesMixin` and before `GoalsMixin` — alphabetical ordering is not a hard rule, but composing assessments adjacent to preferences keeps the conceptually-related modules close.
- `src/database/models.py` — add three dataclasses: `AssessmentRecord`, `AssessmentResponse`, `AssessmentPreferences`. Each with a `to_dict()` method (mirrors the `SubjectEdge` / `UserPreferences` convention).
- `src/database/exceptions.py` — add `AssessmentError` (base), `AssessmentAlreadyCompleteError`, `AssessmentNotFoundError`, `InvalidLikertResponseError`. None of these surface raw SQLite errors to the bridge.

### `AssessmentsMixin` API

```python
class AssessmentsMixin:
    # ---- administration lifecycle ----
    def start_assessment(self, instrument_version: str = "v1") -> AssessmentRecord
    def get_in_flight_assessment(self) -> Optional[AssessmentRecord]
    def submit_response(self, assessment_id: int, item_code: str,
                        raw_response: int, response_time_ms: int) -> None
    def finish_assessment(self, assessment_id: int) -> AssessmentRecord
    def delete_assessment(self, assessment_id: int) -> None  # admin-only path

    # ---- read-side queries ----
    def get_latest_scores(self) -> Optional[AssessmentRecord]
    def get_assessment_history(self, limit: int = 50) -> list[AssessmentRecord]
    def get_assessment_responses(self, assessment_id: int) -> list[AssessmentResponse]

    # ---- preferences / cadence ----
    def get_assessment_preferences(self) -> AssessmentPreferences
    def set_reassessment_cadence(self, cadence_days: int) -> AssessmentPreferences
    def snooze_reassessment(self, days: int) -> AssessmentPreferences
    def get_reassessment_status(self) -> dict
        # → {"due": bool, "next_due_at": iso8601, "days_until_due": int,
        #    "snooze_count": int, "has_completed_administration": bool}
```

### Method semantics (load-bearing details)

**`start_assessment(instrument_version="v1")`** — under a single transaction: (1) lazily upsert a `user_assessment_preferences` row for `self.user_id` if absent, (2) check if there's an in-flight administration via the partial index, (3) if there is, **return it** rather than creating a new one (resumption-safe; the user can navigate away and back), (4) else INSERT a new `user_assessments` row with `is_complete=0`. Returns the `AssessmentRecord` with `started_at` set by the DB.

**`submit_response(assessment_id, item_code, raw_response, response_time_ms)`** — validates `raw_response` is within the scale range declared in the fixture for that `item_code`'s subscale (raises `InvalidLikertResponseError` if not), then UPSERTs into `user_assessment_responses` (UNIQUE constraint on `(assessment_id, item_code)` makes this an `INSERT ... ON CONFLICT(assessment_id, item_code) DO UPDATE`). Also validates the administration is still `is_complete=0`; raises `AssessmentAlreadyCompleteError` otherwise.

**`finish_assessment(assessment_id)`** — under a single transaction: (1) load all responses for this administration, (2) load the fixture for the administration's `instrument_version`, (3) call `_assessment_scoring.score_administration`, (4) UPDATE `user_assessments` SET all the score columns + `completed_at=CURRENT_TIMESTAMP` + `completion_time_ms` (computed as `(now - started_at).total_seconds() * 1000`) + `attention_check_pass` + `is_complete=1`, (5) UPDATE `user_assessment_preferences` SET `next_due_at = completed_at + cadence_days`, (6) return the finalized `AssessmentRecord`. The two UPDATEs share a transaction so a crash between them does not leave preferences pointing to a stale `next_due_at`.

**Partial-completion contract:** `finish_assessment` does NOT require all items to have responses. The scoring math returns NULL for any subscale that has no responses; the dashboard later treats NULL subscale scores as "not enough data" rather than as zero. This protects against the user genuinely abandoning mid-section AND covers the test mode where we want to ship 5 fake responses and read the scores.

**`get_latest_scores()`** — returns the most recent `is_complete=1` administration, or None. Used by the dashboard banner gating logic in Stage 5 (no banner if None).

**`get_reassessment_status()`** — returns `{due, next_due_at, days_until_due, snooze_count, has_completed_administration}`. `due` is `next_due_at <= now()`. `has_completed_administration` is the gating signal Stage 5 needs to know whether to show the banner at all (no completed administration → no banner, regardless of `due`).

**`snooze_reassessment(days)`** — increments `snooze_count`, sets `last_snoozed_at=CURRENT_TIMESTAMP`, sets `next_due_at = next_due_at + days days` (NOT `now + days` — accumulated snoozes shouldn't reset the clock to "now"; if the user snoozed by 7 days yesterday and snoozes by another 30 today, the new due date is 37 days from the original due date). Caller validates `days` is one of the supported values (7, 30) but the DB accepts any positive integer up to 730 to allow future UI changes without a DB migration.

**`set_reassessment_cadence(cadence_days)`** — UPDATE `cadence_days`. Does **not** retroactively reset `next_due_at`; the next administration after this point will use the new cadence. Rationale: changing your cadence from 180 to 90 should not punish you by jumping `next_due_at` back to "yesterday".

### Test strategy

`tests/database/test_assessments.py` (~30 cases):

**Lifecycle:**

- `start_assessment` on a fresh DB returns a record with `id`, `started_at`, `is_complete=False`.
- Calling `start_assessment` twice without finishing returns the **same** administration (resumption).
- `submit_response` happy path: response is persisted; second call with same `(assessment_id, item_code)` overwrites the raw value.
- `submit_response` with `raw_response=0` on a 5-point item raises `InvalidLikertResponseError`.
- `submit_response` with `raw_response=6` on a 5-point item raises `InvalidLikertResponseError`.
- `submit_response` against a completed administration raises `AssessmentAlreadyCompleteError`.
- `finish_assessment` happy path: all 57 items + 2 attention checks submitted (use synthetic responses since real prompts aren't yet populated); scores are populated; `is_complete=True`; preferences `next_due_at` advances by the default cadence.
- `finish_assessment` partial: only NFC submitted; `nfc_total` is set, all other subscale columns are NULL; `is_complete=True`.
- `finish_assessment` twice on the same id raises `AssessmentAlreadyCompleteError`.

**Reverse-scoring round-trip:**

- Submit all NFC items as `raw=1`. Expected `nfc_total` reflects the reverse split: if 16 items are reverse-keyed, the mean is `(18×1 + 16×5) / 34 = (18 + 80) / 34 ≈ 2.88` — and the test asserts on the math, not the absolute value, so a different reverse-key count in the fixture changes the expected number cleanly.

**Attention checks:**

- Submit `atc_01` with `expected_response=2` and `raw_response=2` → `attention_check_pass=True` (assuming the other check also passes).
- Submit `atc_01` with `raw_response=5` → `attention_check_pass=False`.

**History and reads:**

- `get_latest_scores` on a fresh DB returns None.
- After one finished administration, `get_latest_scores` returns that record.
- After two finished administrations, `get_latest_scores` returns the more recent; `get_assessment_history(limit=10)` returns both, newest first.

**Preferences:**

- `get_assessment_preferences` on a fresh DB returns the default (180 / NULL / NULL / 0).
- `set_reassessment_cadence(90)` round-trips.
- `set_reassessment_cadence(29)` raises `BaseDatabaseError` (CHECK violation).
- `snooze_reassessment(7)` increments count, advances `next_due_at` by exactly 7 days, sets `last_snoozed_at`.
- `snooze_reassessment(30)` after `snooze_reassessment(7)` advances by another 30 days from the snoozed-once value, not from "now".

**Reassessment status:**

- `get_reassessment_status` with no completed administration: `due=False, has_completed_administration=False, next_due_at=None`.
- `get_reassessment_status` 1 day before the due date: `due=False, days_until_due=1`.
- `get_reassessment_status` 1 day after the due date: `due=True, days_until_due=-1`.

Coverage target: 90% on `assessments.py`.

### Risk and rollback

- Mixin composition order: putting `AssessmentsMixin` in `UserDatabase` is mechanical, but if the order accidentally places it before `BaseDatabase`, `self.transaction()` will resolve to the wrong MRO entry. Mitigate by adding a one-shot sanity test that constructs `UserDatabase` and calls `start_assessment` — failure on construction is loud.
- Resumption semantics (start returning the in-flight administration instead of creating a new one) is a deliberate choice. If a user genuinely wants to abandon and restart, they need an explicit "discard" path. v1 deliberately omits this — the in-flight administration auto-resolves on the next `finish` call, or stays open indefinitely with no UI consequence. A future "restart from scratch" UI button can call `delete_assessment` first.
- Score columns are stored, not derived on read. If the scoring math ever changes (it shouldn't — the math is fixed; only prompt wording changes per version), historical scores keep their old math. That is the **correct** invariant for longitudinal data, but it does mean a v2 fixture with a re-keyed item set cannot be rescored against v1 administrations — captured in §Risks as "rescoring is out of scope".

### Effort

Medium (2 days). Most of the time is in the lifecycle test cases and the resumption-safety paths.

---

## Stage 2 — `AssessmentBridgeMixin` + JS API Module

### Purpose

Wire the database mixin through the bridge to JavaScript so the assessment page can be written against a working backend. After Stage 2, the assessment is invokable from the JS console; the UI rendering work is independent (Stage 3) but unblocked.

### Dependencies

- Stage 1.

### Files to create

- `src/app/bridge_domains/assessment.py` — new mixin `AssessmentBridgeMixin`.
- `src/web/js/api/assessments.js` — new API module.

### Files to modify

- `src/app/bridge_domains/__init__.py` — export `AssessmentBridgeMixin`.
- `src/app/bridge.py` — add `AssessmentBridgeMixin` to the `DatabaseBridge` composition. Place it adjacent to `PreferencesBridgeMixin` for symmetry with the database-side ordering.
- `src/web/js/api/_loader.js` — register `assessments.js` (alphabetical position in the loader list).

### Bridge surface

All slots follow the existing `serialize_response()` contract (`{success, data, error}` JSON string).

| Slot | Signature | Returns (`data` shape) |
|---|---|---|
| `startAssessment` | `@pyqtSlot(str, result=str)` `(instrument_version="v1")` | `{assessment_id, instrument_version, started_at, sections: [{name, items: [{item_code, prompt, scale, position, reverse_scored, subscale}]}]}` — the sections shape is built by reading the fixture + manifest, NOT by reading the database. The database stores only raw responses keyed by `item_code`; the fixture is the source of the rendered prompts. Attention checks are spliced into their assigned positions per `insert_after_item_code` in `attention_checks.json`. |
| `submitResponse` | `@pyqtSlot(int, str, int, int, result=str)` `(assessment_id, item_code, raw_response, response_time_ms)` | `{ok: true}` on success; `{ok: false, error: ...}` on validation failure (raw out of range, etc.). |
| `finishAssessment` | `@pyqtSlot(int, result=str)` `(assessment_id)` | `{scores: {nfc_total, lgo_learning, lgo_prove, lgo_avoid, importance_exam, importance_clinical, importance_mastery, importance_reflection}, attention_check_pass, completed_at, completion_time_ms, next_due_at}` |
| `getLatestScores` | `@pyqtSlot(result=str)` `()` | The full latest `AssessmentRecord.to_dict()` or `null` if none. |
| `getAssessmentHistory` | `@pyqtSlot(int, result=str)` `(limit=50)` | `[AssessmentRecord.to_dict(), ...]` newest first. |
| `getReassessmentStatus` | `@pyqtSlot(result=str)` `()` | `{due, next_due_at, days_until_due, snooze_count, has_completed_administration}` |
| `snoozeReassessment` | `@pyqtSlot(int, result=str)` `(days)` | The updated `AssessmentPreferences.to_dict()`. |
| `setReassessmentCadence` | `@pyqtSlot(int, result=str)` `(cadence_days)` | The updated `AssessmentPreferences.to_dict()`. |
| `getReassessmentCadence` | `@pyqtSlot(result=str)` `()` | `{cadence_days}` |

**Why `startAssessment` returns the full item list inline:** the alternative is a separate `getAssessmentItems(version)` slot called after `startAssessment`. That adds a round-trip for no benefit and makes the JS state machine harder (which call do you key the "in-progress" flag against?). Inline keeps the contract one-call-one-response.

**Section shaping logic** (in `startAssessment` slot, before serialization):

1. Load the fixture for the requested version (caches the loaded manifest + items per process — fixtures are read-only).
2. Build three section payloads: `nfc` (34 items in their canonical order), `lgo` (13 items in the order learning → prove → avoid), `importance` (8 items in the order exam → clinical → mastery → reflection).
3. Insert attention checks into the flow at their pinned positions (per `insert_after_item_code`).
4. Compute a `position` integer per item (1-indexed across the full flow, including attention checks) so the UI can render a "Question N of M" indicator.
5. Return `{assessment_id, sections}` where `sections` is the ordered list.

### JS API surface

`src/web/js/api/assessments.js` mirrors the bridge. Function names use camelCase (matches existing convention in `weights.js`, `entries.js`). All functions return promises that resolve to the unwrapped `data` payload and throw on `success=false`.

```js
(function(api) {
    'use strict';

    api.startAssessment = async function(version) {
        return api._callBridge('startAssessment', version || 'v1');
    };

    api.submitAssessmentResponse = async function({assessmentId, itemCode, rawResponse, responseTimeMs}) {
        return api._callBridge('submitResponse', assessmentId, itemCode, rawResponse, responseTimeMs || 0);
    };

    api.finishAssessment = async function(assessmentId) {
        return api._callBridge('finishAssessment', assessmentId);
    };

    api.getLatestAssessmentScores = async function() {
        return api._callBridge('getLatestScores');
    };

    api.getAssessmentHistory = async function(limit) {
        return api._callBridge('getAssessmentHistory', limit || 50);
    };

    api.getReassessmentStatus = async function() {
        return api._callBridge('getReassessmentStatus');
    };

    api.snoozeReassessment = async function(days) {
        return api._callBridge('snoozeReassessment', days);
    };

    api.setReassessmentCadence = async function(cadenceDays) {
        return api._callBridge('setReassessmentCadence', cadenceDays);
    };

    api.getReassessmentCadence = async function() {
        return api._callBridge('getReassessmentCadence');
    };
})(window._wimiApi);
```

### Test strategy

`tests/app/test_assessment_bridge.py` (~20 cases):

- Each slot returns well-formed JSON with the standard `success/data/error` shape.
- `startAssessment` returns a sections payload with 3 sections and the right item counts per section (`nfc: 34+1 attention check = 35`, `lgo: 13+1 attention check = 14`, `importance: 8`).
- `startAssessment` does NOT leak prompt text for items where the fixture has the `[POPULATE FROM ...]` stub — the prompt is passed through verbatim, but the test asserts on item count/codes, not on text. (Validates that the bridge layer's behavior is fixture-agnostic.)
- `submitResponse` validation errors surface in the bridge response as `success=false, error="..."`, not as raw exceptions.
- `finishAssessment` with all responses submitted returns score values populated; with no responses, returns NULL scores and `attention_check_pass=false`.
- `getLatestScores` returns `null` initially, then returns the latest after finishing.
- `getReassessmentStatus` correctly reflects has_completed_administration after `finishAssessment`.
- `snoozeReassessment(7)` advances next_due_at and increments the counter; subsequent `snoozeReassessment(30)` stacks per Stage 1 semantics.
- `setReassessmentCadence(29)` returns `success=false, error="..."` with a useful message (cadence out of range).

### Risk and rollback

- The fixture loader is now invoked at slot-call time. If the fixture is missing in a frozen build (PyInstaller didn't bundle `src/database/fixtures/`), every `startAssessment` returns a server error. **Mitigation:** add `fixtures/` to the PyInstaller spec file as a `datas` entry in the same change as Stage 0. Verify in Stage 2 by running the build script in CI on a follow-up PR.
- Section-shaping is done in Python and serialized. If the test mode wants to drive the flow programmatically (Stage 6 regression scenarios), the test must replay the same item ordering. Use the bridge's `startAssessment` response as the authoritative ordering; do NOT hard-code item order in test scenarios.
- Bridge backward compat: this is a pure addition; no existing slot signatures change. Risk of breaking existing JS callers is zero.

### Effort

Medium (2 days). Bridge work is mechanical; the section-shaping logic is the only non-trivial piece.

---

## Stage 3 — Assessment Page UI (`assessment.html` + `assessment.js`)

### Purpose

The page that actually administers the battery. Sectioned delivery (NFC first, then LGO, then Importance), per-section progress bar, attention-check rendering identical to surrounding items (so the user can't visually distinguish them), and a completion screen showing the scores back. No adaptive behavior anywhere — just collect, score, persist, display.

### Dependencies

- Stage 2 (bridge surface available).

### Files to create

- `src/web/html/assessment.html` — the single-page assessment.
- `src/web/js/assessment.js` — the controller.
- `src/web/css/assessment.css` (or extend `styles.css`) — the assessment-specific styling. **Important:** every new selector uses existing CSS variables only (`--bg-primary`, `--color-primary`, `--radius-lg`, `--space-md`, etc.) — no hardcoded colors, per the theme-system rule in `CLAUDE.md`.

### Files to modify

- `src/web/css/styles.css` — only if extending shared styling; prefer a new `assessment.css` for cohesion.

### Page anatomy

```
┌─ Header ───────────────────────────────────────────────┐
│ WIMI Self-Assessment                                   │
│ Section 1 of 3 · Need for Cognition                    │
│ ▓▓▓▓▓░░░░░░░░░░░ 18 of 34                              │
└────────────────────────────────────────────────────────┘

┌─ Current item card ────────────────────────────────────┐
│ [Q18]                                                  │
│ "[Prompt text from fixture]"                           │
│                                                        │
│ ○ Strongly disagree                                    │
│ ○ Disagree                                             │
│ ○ Neutral                                              │
│ ● Agree                                                │
│ ○ Strongly agree                                       │
│                                                        │
│         [← Previous]      [Next →]                     │
└────────────────────────────────────────────────────────┘

┌─ Footer ───────────────────────────────────────────────┐
│ Items: Cacioppo & Petty (1982); VandeWalle (1997);    │
│ original to WIMI. See LICENSES.md for full citations.  │
└────────────────────────────────────────────────────────┘
```

### Controller state machine

```js
const state = {
    assessmentId: null,
    instrumentVersion: 'v1',
    sections: [],             // populated by startAssessment
    currentSectionIdx: 0,     // 0..2
    currentItemIdx: 0,        // index within the current section's items array
    responses: {},            // {item_code: {raw_response, response_time_ms}} — locally cached for back-navigation
    itemShownAt: null,        // Date.now() when the current item became visible
    completed: false,
};
```

State transitions:

- **On page load:** call `api.startAssessment()`. Store the returned `assessment_id` and `sections`. Restore any cached responses from the bridge if this is a resumption (call `api.getAssessmentResponses(assessment_id)` — a method that needs to be added at Stage 2; capture it there). Render the first un-answered item.
- **On Next:** record `response_time_ms = Date.now() - itemShownAt`. Call `api.submitAssessmentResponse({...})`. Advance to next item. If the section is exhausted, advance to next section. If all sections are exhausted, transition to the completion screen.
- **On Previous:** decrement the item index (does NOT un-submit the response; the user can re-answer if they want and the UPSERT in `submit_response` handles it). Do NOT record a new `response_time_ms` for the prior item (the original was already submitted).
- **On the final Next:** call `api.finishAssessment(assessmentId)`. Render the completion screen with the scores.

### Likert rendering

Three variants based on subscale `likert` from the manifest:

- 5-point (NFC + atc_01): Strongly disagree, Disagree, Neutral, Agree, Strongly agree.
- 6-point (LGO + atc_02): Strongly disagree, Disagree, Slightly disagree, Slightly agree, Agree, Strongly agree.
- 7-point (Importance): Strongly disagree, Disagree, Slightly disagree, Neutral, Slightly agree, Agree, Strongly agree.

Radio buttons stacked vertically (not a horizontal scale) per usability research on long-form questionnaire instruments — vertical layout reduces left-right bias and is easier on narrow viewports.

**Attention checks are rendered identically to surrounding items** — same card layout, same Likert anchors, no visual indication that it's an attention check. The prompt itself contains the instruction ("Please select 'Disagree' for this item.").

### Progress and completion screen

Progress bar is **per-section**, not global. Rationale: a 57-item progress bar that's "16 of 57" feels like an eternity; a per-section progress bar resets twice during the flow and gives the user three perceived "halfway points". The bar widget receives `(itemsAnswered, sectionTotal)` and renders `█████░░░░░ 5 of 10`.

The completion screen shows the eight subscale scores in a compact two-column layout, plus a "thank you" line and a return-to-dashboard button. Critically: the screen does **not** interpret the scores ("your NFC is high/low"). v1 is passive-recording; interpretive copy is a future-feature concern. Numbers only, with a small explanatory line like "These scores are stored privately on your device." Scores are rendered to 2 decimal places (e.g., `NFC: 3.41`).

### Auto-save and resumption

Every `submitAssessmentResponse` call is the unit of save. If the user closes the window mid-assessment, the next time they open the assessment page, the bridge will return the same `assessment_id` (per `start_assessment`'s resumption semantics from Stage 1) and the responses will be restored. The UI should jump to the first un-answered item on resumption.

### Test strategy

Manual exploratory checks during Stage 3:

- Tab key navigates through radio options in DOM order.
- Enter key on the focused Next button advances.
- Refresh mid-flow restores position.
- All three Likert variants render correctly.
- Theme toggle (light/dark) doesn't break any contrast.
- Progress bar updates after each Next.

Stage 6 will add a `wimi_test` regression scenario covering the full flow.

### Risk and rollback

- The single-page-controller approach means a bug in `assessment.js` can lock the user mid-flow. Mitigate by adding a "Skip to end" hidden affordance only present in dev mode (`if (!dev_mode) return null` short-circuit). Production builds will not expose it.
- Attention-check positioning is a fixture decision (`insert_after_item_code`). If the project owner re-orders the fixture, the attention checks may end up in an awkward position. Document this in the fixture's `manifest.json` comment.
- Stage 3 ships behind a "feature flag" in practice — the page exists but no link points to it from anywhere else in the app. Stages 4 and 5 are what actually surface it to users. This means Stage 3 can be merged independently and tested via direct URL navigation (`http://localhost/web/html/assessment.html` in dev), without forcing a user-facing rollout.

### Effort

Large (3-4 days). Most of the time is in the controller state machine, the Likert variants, and the auto-save resumption flow.

---

## Stage 4 — Onboarding Hook in `main.py`

### Purpose

Route first-launch users to the assessment page automatically. After a returning user with a completed administration starts WIMI, they go to the dashboard as before. After a fresh-install user starts WIMI, they go to the assessment page first and then to the dashboard upon completion.

### Dependencies

- Stages 1–3 (page must exist and be functional).

### Files to modify

- `src/app/main.py` — add the gating logic between `setup_demo_user` and the navigation to `index.html`.
- `src/app/main_window.py` — `MainWindow.__init__` currently loads `index.html` unconditionally; refactor the initial URL selection to be passed in by the caller. This is a one-line change to the constructor: accept `initial_page: str = 'index.html'`.
- `src/web/js/assessment.js` — on completion, navigate to `index.html`. (Stage 3 already specifies a "return to dashboard" button; Stage 4 promotes that button to the only exit path on the post-completion screen and adds a 3-second auto-redirect.)

### Gating logic (in `main.py` after user_db is created)

```python
def _resolve_initial_page(user_db) -> str:
    """Decide whether to land on the dashboard or the assessment page.

    Returns 'assessment.html' if the user has never completed an
    assessment; 'index.html' otherwise. Test mode always returns
    'index.html' so regression scenarios that don't care about the
    assessment don't have to dismiss it.
    """
    if user_db is None:
        return 'index.html'  # test mode or no demo user
    latest = user_db.get_latest_scores()
    return 'assessment.html' if latest is None else 'index.html'
```

The pre-frame call site:

```python
initial_page = _resolve_initial_page(user_db)
exit_code = run_application(
    master_db=master_db,
    user_db=user_db,
    dev_mode=dev_mode,
    app_data_dir=app_data_dir,
    plugin_manager=plugin_manager,
    initial_page=initial_page,
)
```

`run_application` and `MainWindow` thread the parameter through; the existing default of `'index.html'` keeps the test-mode path and the no-user path unchanged.

### Test strategy

`tests/app/test_onboarding_routing.py`:

- `_resolve_initial_page` with `user_db=None` returns `'index.html'`.
- `_resolve_initial_page` with a `user_db` that has no completed administrations returns `'assessment.html'`.
- `_resolve_initial_page` with a `user_db` with one completed administration returns `'index.html'`.

These are pure-function tests against `_resolve_initial_page`; no Qt setup needed.

### Risk and rollback

- **Critical:** the test-mode regression suite has hundreds of scenarios that assume `index.html` is the initial page. Stage 4 must NOT change that behavior in test mode. The gating logic uses `user_db is None` as a proxy for test mode (matches the existing `setup_demo_user` skip in `main.py`); if test mode ever starts spawning a fully-populated demo user, this proxy breaks. Reinforce with: an explicit `test_mode.is_active()` check in `_resolve_initial_page` that short-circuits to `'index.html'` before consulting `user_db`.
- An in-flight administration with no `completed_at` is treated as "never completed" — the user re-lands on the assessment page and resumes (per Stage 1 semantics). This is the desired UX.
- Rollback: revert the one-line constructor parameter in `MainWindow`, the `_resolve_initial_page` function, and the call-site change. No data is affected; the assessment page itself remains accessible by URL.

### Effort

Small (0.5 day). Mostly threading a parameter through three call sites.

---

## Stage 5 — Dashboard Banner + Settings Integration

### Purpose

Re-measurement surface. Once the user has a completed administration, the cadence-driven re-measurement logic governs whether they see a "Time to retake your self-assessment" banner on the dashboard. Settings gets a cadence-control widget so the user can change the interval or take an assessment on demand.

### Dependencies

- Stages 1–3.

### Files to modify

- `src/web/html/index.html` — add a banner element (`<div id="assessment-banner" class="dashboard-banner" hidden></div>`) near the top of `landing-content`. Initially hidden; populated and shown by JS.
- `src/web/js/dashboard.js` (or `landing.js` — name TBD by repo convention; check existing file naming) — on page load, call `api.getReassessmentStatus()`. If `has_completed_administration && due`, populate and show the banner.
- `src/web/html/settings.html` — add a new "Self-assessment" section under the Profile tab.
- `src/web/js/settings.js` — wire the new section to `api.getReassessmentCadence`, `setReassessmentCadence`, `getLatestAssessmentScores`, `getAssessmentHistory`.
- `src/web/css/assessment.css` (or `landing.css`) — banner styling.

### Banner anatomy

```
┌─ Banner ────────────────────────────────────────────────────────┐
│ ⓘ Time to retake your self-assessment                           │
│   Your last self-assessment was 184 days ago (due 4 days ago).  │
│                                                                  │
│   [Take now]   [Remind in 7 days]   [Snooze 30 days]            │
└─────────────────────────────────────────────────────────────────┘
```

Button bindings:

- `Take now` → navigate to `assessment.html`.
- `Remind in 7 days` → `api.snoozeReassessment(7)` then hide the banner.
- `Snooze 30 days` → `api.snoozeReassessment(30)` then hide the banner.

Banner is dismissed automatically when any of the three actions is taken. Refreshing the page won't re-show it until the (snooze-pushed) `next_due_at` lapses again.

### Settings — Self-assessment section

```
┌─ Self-assessment ───────────────────────────────────────────────┐
│ How often to retake the assessment                              │
│   [    180 ] days  (range 30 – 730)                             │
│   [Save cadence]                                                │
│                                                                  │
│ Last completed: 2025-11-12  (184 days ago)                      │
│ Next due:       2026-05-11  (4 days ago — overdue)              │
│ Snooze count:   2 (lifetime)                                    │
│                                                                  │
│ [Take a new assessment now]   [View history]                    │
└─────────────────────────────────────────────────────────────────┘
```

`Take a new assessment now` is an explicit affordance — clicking it routes to `assessment.html` even when not due. `View history` (deferred to a follow-up; v1 stub renders a placeholder dialog showing the JSON dump of `getAssessmentHistory()`) shows past administrations.

When no completed administration exists yet, the whole section shows a single CTA: "Complete your first self-assessment to enable re-measurement settings" with a "Take it now" button. All the inputs are disabled in this state.

### Test strategy

`tests/web/test_dashboard_banner_logic.js` (if JS testing infrastructure exists; otherwise manual checks during Stage 5):

- `getReassessmentStatus` returns `{due: true, has_completed_administration: true}` → banner is visible with the right text.
- `getReassessmentStatus` returns `{due: false}` → banner is hidden.
- `getReassessmentStatus` returns `{has_completed_administration: false}` → banner is hidden regardless of `due`.

Manual checks:

- Dashboard banner doesn't flicker on page load (status fetched before render or with a loading state).
- Settings page renders cadence value round-trips after page reload.
- Cadence out-of-range input shows an inline validation error and does not call the bridge.

A regression scenario lands in Stage 6.

### Risk and rollback

- **Critical:** Stage 5 must NOT show the banner before the user's first administration. The gating signal is `has_completed_administration` from `getReassessmentStatus`. Verify in the regression scenario that a fresh-install user with no completed assessments never sees the banner under any circumstance (including time advancement).
- The dashboard already has several other UI sections; adding the banner at the top must not displace any existing layout. Stage 5 uses an `<aside>` (or banner block) above `landing-content` with a small bottom margin; if there's a layout shift, fix it in `landing.css` not by reordering existing markup.
- Settings page already has multiple sections; the new "Self-assessment" section is appended to the existing structure, with no reordering or restyling of pre-existing sections.
- Snooze button copy: "Remind in 7 days" actually pushes `next_due_at` forward by 7 days from the **current** `next_due_at` (not from now), per Stage 1 semantics. If the assessment is 100 days overdue and the user snoozes 7 days, the next_due_at is now 93 days overdue. This is intentional — snoozes accumulate against the original cadence. But it means the UI copy "Remind in 7 days" is approximate. Acceptable for v1; future iteration may surface "skip this cycle" as a distinct action.

### Effort

Medium (2 days). Settings work is mechanical; the banner state-machine and the empty-state messaging take the bulk.

---

## Stage 6 — Regression Scenarios (`wimi_test`)

### Purpose

End-to-end coverage in the regression framework. Two scenarios: a happy-path completion and a snooze flow. After Stage 6, breakages in any of Stages 1–5 are caught by CI on push to master.

### Dependencies

- Stages 1–5 all landed.
- `wimi_test` regression infrastructure (already operational; `tests/wimi_test/scenarios/`).

### Files to create

- `tests/wimi_test/scenarios/test_onboarding_assessment_happy_path.py`
- `tests/wimi_test/scenarios/test_reassessment_snooze_flow.py`

### Scenario 1: happy-path completion

```
1. start_session() with a fresh test user (no completed administrations)
2. Wait for page load; assert URL is assessment.html
3. For each item in the rendered flow (53 + 2 attention checks):
     - assert the Likert radios are rendered with the right count
     - select the middle option
     - if it's an attention check, select the expected_response value
     - click Next
4. On the completion screen, assert all 8 score values are present and numeric
5. Click "Return to dashboard"
6. Assert URL is index.html
7. Verify via mcp__wimi-db: user_assessments has exactly 1 row, is_complete=1
8. Verify the row has all 8 score columns populated
9. Verify user_assessment_responses has 55 rows for this assessment_id (53 + 2)
10. end_session()
```

The scenario reads the bridge's `startAssessment` response to drive the flow — it does NOT hard-code the item ordering. Item codes are read off the rendered DOM (`data-item-code` attribute on each card) to be resilient to fixture reordering.

### Scenario 2: snooze flow

```
1. start_session() with a test user that has 1 completed administration
   from 200 days ago (seeded via direct DB insert in the test setup)
2. Wait for page load; assert URL is index.html
3. Assert the assessment-banner is visible
4. Assert the banner text contains "due"
5. Click "Snooze 30 days"
6. Assert the banner is now hidden
7. Verify via mcp__wimi-db: user_assessment_preferences.snooze_count = 1
8. Verify user_assessment_preferences.next_due_at has advanced by 30 days
9. Reload the page; assert the banner remains hidden
10. end_session()
```

### Test strategy

- Use `mcp__wimi-test`'s session machinery (`start_session`, `navigate_to`, `click`, `wait_for`, `eval_js`, `dump_dom`).
- Use `mcp__wimi-db` for DB-side verification (avoid round-tripping through the bridge for assertions).
- Locator preference order from `docs/testing/UI_AUDIT.md`: role+name → testid → CSS. Add testids `assessment-banner`, `assessment-banner-take-now`, `assessment-banner-snooze-7`, `assessment-banner-snooze-30`, `assessment-card-{item_code}`, `assessment-likert-option-{N}`, `assessment-next-button`, `assessment-prev-button`, `assessment-complete-card`.

### Risk and rollback

- Stage 6's first scenario doubles as the smoke test for Stages 1–4 — if it passes, the basic flow works. Treat its failure as a build-breaker.
- Both scenarios run in headless mode (`QT_QPA_PLATFORM=offscreen`). The page must render correctly under offscreen rendering; this is the default for the existing scenarios so no surprises expected.
- Seeding "1 completed administration from 200 days ago" in Scenario 2 needs a helper in `wimi_test/db/seeders.py`. Adding it is part of Stage 6's scope. The helper signature: `seed_completed_assessment(user_db, days_ago: int, **score_overrides) -> int` returning the `assessment_id`. Default scores are the mean of the scale (e.g., `nfc_total=3.0`).

### Effort

Medium (1-2 days). Most of the time is in writing the deterministic item-by-item interaction loop and the seeder helper.

---

## Stage 7 — Documentation, Credits, and Pre-Launch Checklist

### Purpose

Polish + IP cleanup. Stage 7 is the gate before the feature is enabled for any real user. The substrate is in place by Stage 6; Stage 7 ensures (a) the placeholder item prompts are replaced with the real wording, (b) the LICENSES.md and the in-app credits panel say the right thing, and (c) the project owner has a checklist they can run through before flipping the switch.

### Dependencies

- Stages 0–6.
- Project owner action: source NFC and LGO item text from the original papers and update the fixture stubs.

### Files to create

- `docs/guides/PSYCHOMETRIC_ASSESSMENT.md` — user-facing concept explainer (what NFC / LGO / Importance are, why WIMI measures them, how the data is used today, how it might be used tomorrow). Plain-language style matching `docs/guides/SHARED_SUBJECTS.md`.
- `docs/handoff/psychometric_owner_checklist.md` — pre-launch checklist for the project owner:
  - [ ] Replace all 34 NFC prompts in `nfc.json` with verbatim text from Cacioppo & Petty (1982).
  - [ ] Verify the reverse-key flags in `nfc.json` match the published reverse-key map.
  - [ ] Replace all 13 LGO prompts in `lgo.json` with verbatim text from VandeWalle (1997).
  - [ ] Confirm fair-use / licensed-access posture for both copyrighted scales (consult counsel if shipping commercially).
  - [ ] Update `LICENSES.md` with the right attribution language.
  - [ ] Run `pytest tests/database/test_assessments.py` to confirm scoring math still passes after fixture changes.
  - [ ] Run the Stage 6 regression scenario manually with the populated fixture to confirm wording renders correctly.

### Files to modify

- `LICENSES.md` — add an "Assessment Items" section:
  ```
  ## Psychometric Assessment Items

  The WIMI self-assessment battery includes items from:

  - Cacioppo, J. T., & Petty, R. E. (1982). The need for cognition.
    *Journal of Personality and Social Psychology*, 42(1), 116–131.
    [License terms to be confirmed by project owner.]
  - VandeWalle, D. (1997). Development and validation of a work
    domain goal orientation instrument. *Educational and Psychological
    Measurement*, 57(6), 995–1015.
    [License terms to be confirmed by project owner.]

  The Personal Importance subscale items are original to WIMI and are
  released under CC-BY-4.0. Use is permitted with attribution to:
    "WIMI Personal Importance Scale, 2026."
  ```
- `docs/planning/FUTURE_VISION.md` — add an "Adaptive consumers (deferred)" sub-bullet under the moderator-research thread referencing the scores as the substrate that now exists.
- `src/web/html/assessment.html` — extend the footer with a `<div id="assessment-credits">` populated from the manifest's `credits` block by `assessment.js` at render time. Keep this dynamic so changes to the `manifest.json` propagate without re-editing HTML.

### Test strategy

Stage 7 has minimal automated test coverage; it's docs and IP work. Add one test that asserts `LICENSES.md` contains the expected citation lines (regression against accidental edits):

`tests/docs/test_licenses_md_has_assessment_section.py`:

- Read `LICENSES.md`.
- Assert the strings "Cacioppo" and "VandeWalle" appear somewhere in the file.
- Assert the string "Psychometric Assessment Items" (the section header) appears.

This is a tiny test that costs nothing and catches the failure mode of "someone refactored LICENSES.md and the assessment section got deleted".

### Risk and rollback

- **Critical:** the IP posture cannot be hand-waved. If the project owner cannot confirm fair-use or licensed access to NFC and LGO items, the assessment must not ship publicly. v1's intent is **personal-use only** software; in that posture, fair-use is plausible but the project owner is responsible for the final call. Stage 7's checklist treats this as an explicit gate.
- The `manifest.json` credits block is loaded by `assessment.js` at runtime. A bad edit to `manifest.json` would silently break the footer render. The fixture loader (from Stage 0) treats `credits` as optional and renders a fallback string if missing; this is the safety net.
- Once the fixture's stub prompts are replaced with real wording, the historical responses keyed by `item_code` retain their validity (responses are keyed by code, not text). Replacing wording does **not** require a new instrument version. Re-wording an item is a fixture edit; re-numbering or removing an item is a new instrument version.

### Effort

Small (1 day for the WIMI side; the prompt-population work itself is on the project owner's clock and is variable).

---

## Dependency Graph

```
                       +--------------------------+
                       | Stage 0                  |
                       | Migration m008 +         |
                       | fixture skeleton +       |
                       | scoring math (isolated)  |
                       +-------------+------------+
                                     |
                                     v
                       +--------------------------+
                       | Stage 1                  |
                       | AssessmentsMixin (DB)    |
                       +-------------+------------+
                                     |
                                     v
                       +--------------------------+
                       | Stage 2                  |
                       | AssessmentBridgeMixin +  |
                       | JS API module            |
                       +-------------+------------+
                                     |
                                     v
                       +--------------------------+
                       | Stage 3                  |
                       | assessment.html +        |
                       | assessment.js + CSS      |
                       +------+-------------+-----+
                              |             |
                              v             v
              +--------------------+  +--------------------+
              | Stage 4            |  | Stage 5            |
              | Onboarding hook    |  | Dashboard banner + |
              | in main.py         |  | Settings           |
              +---------+----------+  +----------+---------+
                        |                        |
                        +-----------+------------+
                                    |
                                    v
                       +--------------------------+
                       | Stage 6                  |
                       | wimi_test regression     |
                       | scenarios                |
                       +-------------+------------+
                                     |
                                     v
                       +--------------------------+
                       | Stage 7                  |
                       | Docs + LICENSES.md +     |
                       | owner checklist          |
                       +--------------------------+
```

**Parallelism:**

- Stages 1, 2, 3 are strictly sequential (each consumes the previous stage's output).
- Stages 4 and 5 can land in parallel after Stage 3 — they touch different files (main.py vs index.html/settings.html) and the work is independent.
- Stage 6 needs everything from 1–5; it's the integration gate.
- Stage 7 is largely orthogonal docs/IP work; the docs themselves can be drafted in parallel with Stage 6, but the launch gate (the pre-flight checklist) is only meaningful once 0–6 are stable.

## Recommended Landing Order

1. **Stage 0** — schema + fixture + scoring math, all behind feature-disabled state (no consumer code yet).
2. **Stage 1** — DB mixin, fully unit-tested.
3. **Stage 2** — bridge + JS API, with bridge-contract tests.
4. **Stage 3** — assessment page UI (still feature-disabled from any user-facing route).
5. **Stages 4 + 5** in parallel — flip the onboarding hook and the banner on. Behind this point the feature is user-visible.
6. **Stage 6** — regression scenarios as the merge gate.
7. **Stage 7** — pre-launch polish. Owner-checklist gates the actual public ship.

Stages 0–3 can be merged as separate PRs without flipping any user-facing behavior (the assessment page is reachable only by direct URL, not from any link). Stage 4 is the first PR that changes any user-facing route, so it's also the right merge boundary for "we're committed to this feature" — back out of 4 and the feature is dormant again.

---

## Risks and Unknowns

### Architectural

- **Fixture vs DB split.** The fixture is the source of prompt wording; the DB stores only responses keyed by item code. If a fixture is deleted or corrupted in a frozen build, the user's stored responses are orphaned (numbers without prompts). Mitigate by bundling fixtures in the PyInstaller `datas` block and adding a startup integrity check that confirms the v1 fixture is present and parseable. The check raises a loud error if missing; the app refuses to administer a new assessment but doesn't lose historical data.
- **Instrument-version migration is out of scope for v1.** If/when a v2 fixture lands (different item set, different scoring rules), v1 administrations cannot be rescored to v2 because the items don't map 1-to-1. The right path forward: keep v1 administrations readable forever with v1 scoring; new administrations after v2 ships use v2. Historical comparison across instrument versions is a research-grade concern that v1 does not attempt to solve. Document this in the docs/guides/PSYCHOMETRIC_ASSESSMENT.md.
- **Score interpretation is deliberately absent.** Stage 3's completion screen shows raw scores with no interpretation ("your NFC is high"). The Anseel et al. (2009) finding that motivates the feature is a population-level moderator effect; individual scores are noisy. v1 takes the position that surfacing interpretive copy would imply more precision than the instrument supports. A future "your reflection style profile" feature is the right place to interpret these scores in aggregate with behavioral data — not in this PR.

### Empirical investigation needed

- **Response time semantics.** `response_time_ms` is recorded per item. Edge cases: a user opens the page, walks away for 10 minutes, comes back, hits a radio, then Next — that response is recorded with a 10-minute response time. The scoring math doesn't use response times at all; they're stored for future psychometric analysis (item difficulty, careless-responding flags). Acceptable for v1 but worth noting that "low response time on early items" might one day become a data-quality flag, and we'd want to differentiate "fast and confident" from "didn't read".
- **Cadence default of 180 days.** No empirical basis. Picked because it's roughly two academic semesters for a medical-student user. Could be 90 (more sensitive to shifts in goal orientation post-clerkship) or 365 (less burden). Defer the empirical question until we have ≥6 months of data from real users.

### IP and copyright

- **NFC and LGO items.** Covered in Item provenance and IP. The strict reading: until the project owner confirms licensing posture, the fixture's NFC and LGO prompts stay as `[POPULATE FROM ...]` stubs, the feature ships behind a "for personal use" disclaimer, and the assessment page footer cites both sources prominently. This is a soft gate, not a code gate — Stage 7's checklist is what holds it.
- **Personal Importance items.** Original to WIMI, CC-BY-4.0 in the LICENSES.md entry. Free to ship at any time.

### Migration risk

- m008 is purely additive (three new tables; no ALTER on existing tables). Risk of breaking existing user databases is effectively zero. The migration runner's checksum protection (per `MIGRATION_RUNNER.md`) catches any accidental future edit of the m008 module.
- If a user uninstalls and reinstalls WIMI, their `user_assessments` rows survive (per-user DB persists in `app_data/`). The fresh-install onboarding hook (Stage 4) consults `get_latest_scores()` against the actual DB, so a user with prior administrations skips the onboarding even if the binary changed. Desired behavior.

### Open Questions

- **OQ-A (response-time anomalies):** if `response_time_ms > 10 minutes` on an item, should we flag the administration as low-quality? **Decision for v1:** no flag. Store raw times; flagging is a future concern.
- **OQ-B (Likert scale anchors):** the 6-point scale we ship for LGO has no neutral midpoint (4-step "agree" to 4-step "disagree" symmetric). This matches VandeWalle's published instrument. **Decision:** stay faithful to the original instrument; the absence of a midpoint is a deliberate design property of the scale, not an oversight.
- **OQ-C (multi-session assessments):** can a user pause an in-flight administration for days and come back? **Decision for v1:** yes, via the resumption semantics from Stage 1. No timeout. If the user takes >7 days to finish, the administration is still valid; we trust the user. Future iteration may add a "the data quality of multi-day administrations is lower" caveat.
- **OQ-D (assessment dismissal in onboarding):** the Stage 4 hook routes a fresh user to `assessment.html`. Can they skip? **Decision for v1:** no explicit "skip onboarding" button; the user is expected to either complete the assessment or close the app. Close+reopen lands them back on `assessment.html` (since `get_latest_scores()` still returns None). If this proves user-hostile, add a skip affordance in a follow-up that creates a "skipped" administration row (new `is_skipped` column or a sentinel value) so the hook stops routing them.

---

## Testing Infrastructure Notes

| Stage | Recommended test surface |
|---|---|
| 0 | `tests/database/migrations/test_user_008_assessments.py`; `tests/database/test_assessment_scoring.py` |
| 1 | `tests/database/test_assessments.py` (~30 cases) |
| 2 | `tests/app/test_assessment_bridge.py` (~20 cases) |
| 3 | Manual checks; testid-attribution for Stage 6 |
| 4 | `tests/app/test_onboarding_routing.py` (pure-function unit tests) |
| 5 | Manual checks; testid-attribution for Stage 6 |
| 6 | `tests/wimi_test/scenarios/test_onboarding_assessment_happy_path.py`; `tests/wimi_test/scenarios/test_reassessment_snooze_flow.py` |
| 7 | `tests/docs/test_licenses_md_has_assessment_section.py` |

**Locator convention** (per `docs/testing/UI_AUDIT.md`): role+name → testid → CSS. New testids:

- `assessment-card-{item_code}` — the per-item card.
- `assessment-likert-option-{N}` — each radio (N is the integer value).
- `assessment-next-button`, `assessment-prev-button`.
- `assessment-complete-card` — completion screen.
- `assessment-credits` — footer credits panel.
- `assessment-banner`, `assessment-banner-take-now`, `assessment-banner-snooze-7`, `assessment-banner-snooze-30`.
- `settings-assessment-cadence-input`, `settings-assessment-take-now-button`.

**`mcp__wimi-db` verification helpers needed** (add in Stage 6 or a follow-up MCP server PR):

- `get_assessment_count(user_id) -> int`
- `get_latest_assessment_scores(user_id) -> dict | None`
- `get_assessment_preferences(user_id) -> dict`

These mirror existing patterns (`get_preferences`, `get_study_streak`) on the MCP server. They are not strictly required — the regression scenarios can run raw SQL through the existing `eval_js` capture — but they make assertions more readable.

### Critical Files for Implementation

The five files most load-bearing for landing this plan:

- `src/database/migrations/user/m008_assessments.py`
- `src/database/domains/assessments.py`
- `src/app/bridge_domains/assessment.py`
- `src/web/js/assessment.js`
- `src/web/html/assessment.html`