"""Pure scoring functions for the psychometric assessment battery.

Stage 0 of the Psychometric Assessment Implementation Plan
(``docs/planning/PSYCHOMETRIC_ASSESSMENT_IMPLEMENTATION_PLAN.md``).

No SQLite dependency, no I/O during scoring (fixture loading is a
separate, explicitly invoked step). All score computation happens here
so the math can be exhaustively unit-tested without spinning up a
database.

Naming: the underscore-prefix matches the codebase convention for
"support module, not a domain mixin" — see ``_base.py``.

Reverse-scoring rule: for an item with raw response ``r`` on a Likert
scale with bounds ``[lo, hi]`` and ``reverse_scored=True``, the
contributing value is ``(lo + hi - r)``. On a 5-point scale, raw=1
contributes 5 and raw=5 contributes 1.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------- specs


@dataclass(frozen=True)
class ScaleSpec:
    """A single Likert scale definition (bounds + display anchors)."""
    name: str
    min: int
    max: int
    anchors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ItemSpec:
    """A single questionnaire item."""
    item_code: str
    prompt: str
    scale: ScaleSpec
    reverse_scored: bool = False
    subscale: Optional[str] = None
    # Attention checks only — the response the participant is instructed
    # to give. None for substantive items.
    expected_response: Optional[int] = None
    # Attention checks only — the substantive item this check is shown
    # directly after. None for substantive items. Carried from the
    # fixture so the flow can be shaped without re-reading the JSON
    # (#766 Wave 1); the loader used to drop it.
    insert_after_item_code: Optional[str] = None


@dataclass(frozen=True)
class SectionSpec:
    """One section of the battery (e.g. NFC, LGO, Importance)."""
    name: str
    title: str
    scale: ScaleSpec
    items: tuple[ItemSpec, ...]
    # "mean" → single composite keyed by section.name.
    # "mean_per_subscale" → one composite per declared subscale.
    scoring_method: str
    subscales: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AssessmentFixture:
    """The loaded fixture: version + scales + sections + attention checks."""
    version: str
    scales: dict[str, ScaleSpec]
    sections: tuple[SectionSpec, ...]
    attention_checks: tuple[ItemSpec, ...]

    @property
    def all_items(self) -> tuple[ItemSpec, ...]:
        out: list[ItemSpec] = []
        for section in self.sections:
            out.extend(section.items)
        out.extend(self.attention_checks)
        return tuple(out)

    def item(self, item_code: str) -> ItemSpec:
        for it in self.all_items:
            if it.item_code == item_code:
                return it
        raise KeyError(item_code)


@dataclass
class AssessmentScores:
    """Computed scores for one administration.

    Any subscale with no responses present in the input dict is left as
    ``None`` rather than zero — that distinguishes "abstained" from
    "scored low on every item".
    """
    nfc_total: Optional[float] = None
    lgo_learning: Optional[float] = None
    lgo_prove: Optional[float] = None
    lgo_avoid: Optional[float] = None
    importance_exam: Optional[float] = None
    importance_clinical: Optional[float] = None
    importance_mastery: Optional[float] = None
    importance_reflection: Optional[float] = None
    attention_check_pass: bool = False


# ---------------------------------------------------------------- loader


def _resolve_fixture_dir(version: str) -> Path:
    """Resolve the on-disk fixture dir using the frozen-mode pattern."""
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).parent / "_internal"
    else:
        # this file is src/database/domains/_assessment_scoring.py;
        # the fixture dir is src/database/fixtures/...
        base_path = Path(__file__).resolve().parent.parent
    return base_path / "fixtures" / "assessments" / version


def load_fixture(
    version: str = "v1",
    base_dir: Optional[Path] = None,
) -> AssessmentFixture:
    """Load the manifest plus every section item file from disk.

    Args:
        version: Instrument version tag (e.g. ``"v1"``). Resolved against
            ``src/database/fixtures/assessments/<version>/`` in dev mode
            or ``_internal/fixtures/...`` in frozen mode.
        base_dir: Optional override pointing directly at the fixture
            directory (skips the version-based resolver). Used by tests
            that build a synthetic fixture in a tmpdir.
    """
    fixture_dir = base_dir if base_dir is not None else _resolve_fixture_dir(version)
    if not fixture_dir.is_dir():
        raise FileNotFoundError(
            f"Assessment fixture {version!r} not found at {fixture_dir}"
        )

    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))

    scales = {
        name: ScaleSpec(
            name=name,
            min=int(spec["min"]),
            max=int(spec["max"]),
            anchors=tuple(spec.get("anchors", [])),
        )
        for name, spec in manifest["scales"].items()
    }

    sections: list[SectionSpec] = []
    for section_spec in manifest["sections"]:
        scale = scales[section_spec["scale"]]
        items_data = json.loads(
            (fixture_dir / section_spec["fixture"]).read_text(encoding="utf-8")
        )
        items = tuple(
            ItemSpec(
                item_code=item["item_code"],
                prompt=item["prompt"],
                scale=scale,
                reverse_scored=bool(item.get("reverse_scored", False)),
                subscale=item.get("subscale"),
            )
            for item in items_data
        )
        scoring = section_spec.get("scoring", {}) or {}
        sections.append(SectionSpec(
            name=section_spec["name"],
            title=section_spec.get("title", section_spec["name"]),
            scale=scale,
            items=items,
            scoring_method=scoring.get("method", "mean"),
            subscales=tuple(scoring.get("subscales", [])),
        ))

    attention_data = json.loads(
        (fixture_dir / manifest["attention_checks"]).read_text(encoding="utf-8")
    )
    attention_checks = tuple(
        ItemSpec(
            item_code=item["item_code"],
            prompt=item["prompt"],
            scale=scales[item["scale"]],
            expected_response=int(item["expected_response"]),
            insert_after_item_code=item.get("insert_after_item_code"),
        )
        for item in attention_data
    )

    return AssessmentFixture(
        version=manifest["version"],
        scales=scales,
        sections=tuple(sections),
        attention_checks=attention_checks,
    )


# ---------------------------------------------------------------- scoring


def _contribute(item: ItemSpec, raw: int) -> float:
    """Per-item contribution to the section mean, accounting for reversal."""
    if item.reverse_scored:
        return float(item.scale.min + item.scale.max - raw)
    return float(raw)


def _mean_or_none(values: list[float]) -> Optional[float]:
    return (sum(values) / len(values)) if values else None


def _section_score(
    section: SectionSpec,
    responses: dict[str, int],
) -> dict[str, Optional[float]]:
    """Compute mean score(s) for one section.

    Returns ``{section.name: mean}`` for ``"mean"`` scoring, or
    ``{f"{section.name}_{sub}": mean, ...}`` for ``"mean_per_subscale"``.
    """
    if section.scoring_method == "mean":
        values = [
            _contribute(it, responses[it.item_code])
            for it in section.items
            if it.item_code in responses
        ]
        return {section.name: _mean_or_none(values)}

    if section.scoring_method == "mean_per_subscale":
        out: dict[str, Optional[float]] = {}
        for subscale in section.subscales:
            sub_items = [it for it in section.items if it.subscale == subscale]
            values = [
                _contribute(it, responses[it.item_code])
                for it in sub_items
                if it.item_code in responses
            ]
            out[f"{section.name}_{subscale}"] = _mean_or_none(values)
        return out

    raise ValueError(f"Unknown scoring method: {section.scoring_method!r}")


def _attention_pass(
    fixture: AssessmentFixture,
    responses: dict[str, int],
) -> bool:
    """Pass iff every attention check is answered with the expected value."""
    if not fixture.attention_checks:
        return True
    for check in fixture.attention_checks:
        raw = responses.get(check.item_code)
        if raw is None or raw != check.expected_response:
            return False
    return True


# Maps a section's scoring-output key onto the AssessmentScores field.
# nfc_total is a one-off: the section is named "nfc" but the canonical
# column is nfc_total. LGO and Importance follow the {section}_{sub}
# convention which already matches the dataclass field names.
_NFC_SECTION_TO_FIELD = {"nfc": "nfc_total"}


def score_administration(
    responses: dict[str, int],
    fixture: AssessmentFixture,
) -> AssessmentScores:
    """Compute AssessmentScores from a {item_code: raw_response} dict.

    Missing items are silently skipped (their contribution to the mean
    is just left out). A subscale with zero responses present yields
    ``None`` rather than zero.
    """
    scores = AssessmentScores()
    for section in fixture.sections:
        section_out = _section_score(section, responses)
        for key, value in section_out.items():
            target = _NFC_SECTION_TO_FIELD.get(key, key)
            if hasattr(scores, target):
                setattr(scores, target, value)
    scores.attention_check_pass = _attention_pass(fixture, responses)
    return scores


# ---------------------------------------------------------------- validation


def validate_response(item: ItemSpec, raw: int) -> None:
    """Raise ``ValueError`` if ``raw`` is outside the scale bounds for ``item``."""
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(
            f"Raw response for {item.item_code!r} must be int, "
            f"got {type(raw).__name__}"
        )
    if raw < item.scale.min or raw > item.scale.max:
        raise ValueError(
            f"Raw response for {item.item_code!r} must be in "
            f"[{item.scale.min}, {item.scale.max}], got {raw}"
        )
