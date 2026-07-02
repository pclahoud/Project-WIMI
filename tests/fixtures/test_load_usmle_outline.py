"""Tests for the USMLE outline fixture parser.

These tests verify that the parser locates the well-known multi-parent topics
called out in ``docs/planning/POLYHIERARCHY_MIGRATION.md`` (DVT, hypertension,
sepsis, etc.). If a parser change breaks these assertions, polyhierarchy
traversal tests downstream will silently skip the cases they exist to cover.
"""

from __future__ import annotations

from tests.fixtures.load_usmle_outline import (
    OutlineTopic,
    USMLEOutline,
    load_usmle_outline,
)


def test_loads_without_error() -> None:
    outline = load_usmle_outline()
    assert isinstance(outline, USMLEOutline)
    assert outline.topics, "outline should produce at least some topics"
    assert isinstance(outline.topics[0], OutlineTopic)
    # Sanity: parent_index keys match topic names exactly.
    assert set(outline.parent_index.keys()) == {t.name for t in outline.topics}


def test_topic_count_is_reasonable() -> None:
    outline = load_usmle_outline()
    # 1,327-line outline; expect well over 200 distinct semicolon-separated
    # leaf topics. This is a loose lower bound; the parser typically produces
    # well above this.
    assert len(outline.topics) > 200, f"only found {len(outline.topics)} topics"


def test_finds_known_multi_parent_topics() -> None:
    outline = load_usmle_outline()
    multi = set(outline.multi_parent_topics)

    # Hypertension is the canonical example — the migration plan lists 7
    # distinct sections for it.
    assert "hypertension" in multi, (
        "hypertension should be detected as multi-parent; "
        f"got {len(multi)} multi-parent topics total"
    )

    # DVT appears under cardiovascular vascular-veins AND under
    # pregnancy/systemic-disorders. The pregnancy listing spells it as
    # "deep venous thrombosis (DVT)" (parenthetical stripped) so the
    # normalized form is "deep venous thrombosis".
    dvt_names = {"deep venous thrombosis", "dvt", "deep vein thrombosis"}
    assert dvt_names & multi, (
        "expected some form of DVT/deep venous thrombosis in multi_parent_topics"
    )

    # At least one of sepsis / diabetes mellitus / asthma should be flagged
    # as multi-parent per the migration plan.
    common_multi = {"sepsis", "diabetes mellitus", "asthma"}
    assert common_multi & multi, (
        "expected at least one of sepsis/diabetes mellitus/asthma as multi-parent"
    )


def test_parent_index_contains_known_paths() -> None:
    outline = load_usmle_outline()
    paths = outline.parent_index.get("hypertension", [])
    assert len(paths) >= 2, (
        f"hypertension should have >=2 distinct parent paths, found {len(paths)}: {paths}"
    )
    # Each path should be non-empty and start with a system-level name.
    for p in paths:
        assert p, "parent path should not be empty"
        assert " > " in p or p, "parent path should be a hierarchy"
