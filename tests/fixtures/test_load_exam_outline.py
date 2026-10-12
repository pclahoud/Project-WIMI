"""Tests for the synthetic exam-outline fixture and its loader.

These guard the properties downstream tests rely on without saying so. If one
of them breaks, the polyhierarchy tests, ``test_seeders.py``'s bounds and the
folder-sync round trip all keep passing *less* — they silently stop covering
the multi-parent cases they exist for, which is why the bounds are asserted
here rather than left implicit in the fixture.

The fixture is generated; ``build_exam_outline.py --check`` is what asserts the
committed file still matches its generator.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.fixtures.load_exam_outline import (
    ExamOutline,
    OutlineTopic,
    load_exam_outline,
)

GENERATOR = Path(__file__).resolve().parent / "build_exam_outline.py"


def test_loads_without_error() -> None:
    outline = load_exam_outline()
    assert isinstance(outline, ExamOutline)
    assert outline.topics
    assert isinstance(outline.topics[0], OutlineTopic)
    assert "Test Fixture" in outline.exam_name
    # Sanity: parent_index keys match topic names exactly.
    assert set(outline.parent_index.keys()) == {t.name for t in outline.topics}


def test_topics_are_in_document_order() -> None:
    outline = load_exam_outline()
    assert [t.order for t in outline.topics] == list(range(len(outline.topics)))


def test_the_fixture_is_large_enough_to_be_realistic() -> None:
    """The bounds other files assert, stated once where the fixture lives.

    ``tests/wimi_test/test_seeders.py`` wants >= 1,000 nodes and edges once
    seeded and ``tests/app/test_foldersync_roundtrip.py`` wants > 2,000
    subjects, so a fixture that shrank below this would make both of them pass
    against a profile too small to measure anything.
    """
    outline = load_exam_outline()
    assert len(outline.topics) > 2000, len(outline.topics)
    assert len(outline.parent_index) > 2000, len(outline.parent_index)


def test_every_topic_has_a_parent_path() -> None:
    """A root-level topic would seed as its own root, which the fixture never
    intends: every topic sits under a system and a category."""
    outline = load_exam_outline()
    orphans = [t.name for t in outline.topics if len(t.parent_path) < 2]
    assert orphans == [], orphans


def test_containers_are_not_emitted_as_topics() -> None:
    """A category is a path, not a topic.

    Emitting one as a topic too would make a category name shared by two roots
    into a single multi-parent node — so "Neoplastic disorders" would become
    one subject with nine parents, and the multi-parent count would stop
    measuring the cross-listings it is supposed to measure.
    """
    outline = load_exam_outline()
    names = {t.name for t in outline.topics}
    containers = {part for t in outline.topics for part in t.parent_path}
    assert names & containers == set()


def test_finds_the_deliberate_multi_parent_topics() -> None:
    outline = load_exam_outline()
    multi = set(outline.multi_parent_topics)

    assert len(multi) >= 50, f"only {len(multi)} multi-parent topics"

    # These two are named by test_seeders.py, which asserts each is a single
    # canonical node with one primary parent and at least one other.
    for required in ("hypertension", "deep venous thrombosis"):
        assert required in multi, required
        assert len(outline.parent_index[required]) >= 2

    # test_polyhierarchy_traversal.py and the old fixture's own test both
    # reach for one of these three.
    assert {"sepsis", "diabetes mellitus", "asthma"} <= multi


def test_a_multi_parent_topic_names_distinct_full_paths() -> None:
    outline = load_exam_outline()
    for name in outline.multi_parent_topics:
        paths = outline.parent_index[name]
        assert len(paths) == len(set(paths))
        for path in paths:
            assert " > " in path, (name, path)


def test_the_committed_fixture_matches_its_generator() -> None:
    """Same gate shape as scripts/check_import_guide_sync.py.

    The fixture is the thing tests read, so an edit to the generator that was
    never re-run would leave the two describing different hierarchies with
    nothing to notice.
    """
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
