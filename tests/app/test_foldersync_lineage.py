"""#148 / #149: lineage by digest, and fork detection as "more than one head".

The rule everything else rests on: a generation is a **head** when no other
generation names it, as a content parent or as something it supersedes. More
than one head, from more than one device, is a divergence.

These drive ``FolderTransport`` directly with explicit ``parents`` /
``supersedes``, so the rule is tested without the service's idea of a base.
The service-level consequences -- #149's stale push becoming a reported fork,
a resolution send clearing it -- are in ``test_foldersync_base_lineage.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.foldersync.transport import FolderTransport

SYNC_ID = "11111111-2222-3333-4444-555555555555"


def _transport(tmp_path: Path) -> FolderTransport:
    folder = tmp_path / "cloud"
    folder.mkdir(exist_ok=True)
    return FolderTransport(folder, SYNC_ID, "generic", timeout_s=10.0)


_counter = {"n": 0}


def _push(t: FolderTransport, tmp_path: Path, *, device: str, parents=None,
          supersedes=None, parent_generation=None):
    """Push a unique blob. Distinct payloads give distinct digests."""
    _counter["n"] += 1
    src = tmp_path / f"blob-{_counter['n']}.wimi"
    src.write_bytes(f"payload {_counter['n']} from {device}".encode())
    return t.push(
        blob_source=src, device_id=f"id-{device}", device_name=device,
        schema_version=22, row_counts={"entries": 1}, app_version="test",
        parents=parents, supersedes=supersedes,
        parent_generation=parent_generation,
    )


def _sha(t: FolderTransport, result) -> str:
    for e in t.scan().usable_manifests:
        if e.manifest.blob_name == result.blob_name:
            return e.manifest.sha256
    raise AssertionError(f"{result.blob_name} not found")


# ==================== the heads rule ====================

@pytest.mark.unit
def test_a_linear_lineage_has_one_head(tmp_path):
    t = _transport(tmp_path)
    g1 = _push(t, tmp_path, device="laptop", parents=[])
    g2 = _push(t, tmp_path, device="desktop", parents=[_sha(t, g1)])
    g3 = _push(t, tmp_path, device="laptop", parents=[_sha(t, g2)])

    heads = t.lineage().heads
    assert [h.blob_name for h in heads] == [g3.blob_name]
    assert t.detect_forks() == []


@pytest.mark.unit
def test_two_children_of_one_parent_are_two_heads(tmp_path):
    t = _transport(tmp_path)
    g1 = _push(t, tmp_path, device="laptop", parents=[])
    base = _sha(t, g1)
    _push(t, tmp_path, device="laptop", parents=[base])
    _push(t, tmp_path, device="desktop", parents=[base])

    forks = t.detect_forks()
    assert len(forks) == 1 and forks[0].first_connect is False
    assert forks[0].parent_generation == 1, "they went their own way at generation 1"
    assert {s.device_name for s in forks[0].sides} == {"laptop", "desktop"}


@pytest.mark.unit
def test_a_resolution_that_supersedes_the_other_side_clears_the_fork(tmp_path):
    """The thing #148 said was impossible.

    Publishing a descendant of the chosen side is NOT enough on its own: the
    rejected side would stay a leaf -- a head -- forever. Naming it in
    ``supersedes`` is what retires it.
    """
    t = _transport(tmp_path)
    base = _sha(t, _push(t, tmp_path, device="laptop", parents=[]))
    mine = _sha(t, _push(t, tmp_path, device="laptop", parents=[base]))
    theirs = _sha(t, _push(t, tmp_path, device="desktop", parents=[base]))
    assert t.detect_forks(), "precondition: a real fork"

    _push(t, tmp_path, device="laptop", parents=[mine], supersedes=[theirs])

    assert t.detect_forks() == [], "the resolution did not clear the fork"
    assert len(t.lineage().heads) == 1


@pytest.mark.unit
def test_a_descendant_of_one_side_alone_does_not_clear_the_fork(tmp_path):
    """Why ``supersedes`` has to exist at all."""
    t = _transport(tmp_path)
    base = _sha(t, _push(t, tmp_path, device="laptop", parents=[]))
    mine = _sha(t, _push(t, tmp_path, device="laptop", parents=[base]))
    _push(t, tmp_path, device="desktop", parents=[base])

    _push(t, tmp_path, device="laptop", parents=[mine])  # no supersedes

    assert t.detect_forks(), (
        "the other side was silently treated as rejected without anything "
        "saying so -- that is the stale notice problem inverted")


@pytest.mark.unit
def test_first_connect_keep_mine_with_no_ancestor_still_retires_the_other(tmp_path):
    """The case that forced ``supersedes`` to be a separate field.

    Content with no folder ancestor at all -- ``parents=()`` -- that must
    nonetheless retire the other head. A single ``parents`` list whose first
    entry meant "content" could not say this.
    """
    # The realistic shape: the laptop has never published. It linked to a
    # folder that already holds the desktop's work, was told the two do not
    # share a history, and chose its own copy -- so its first push has no
    # parent in the folder at all.
    t = _transport(tmp_path)
    other = _sha(t, _push(t, tmp_path, device="desktop", parents=[]))

    _push(t, tmp_path, device="laptop", parents=[], supersedes=[other])

    heads = t.lineage().heads
    assert [h.device_name for h in heads] == ["laptop"]
    assert t.detect_forks() == []


@pytest.mark.unit
def test_an_earlier_root_from_the_same_device_stays_a_head_but_is_not_a_fork(tmp_path):
    """Superseding the other side does not retire your own earlier root.

    Nothing names it, so it is still a head. It is harmless -- one device --
    and the service never produces it, because a device that has published
    parents its next push to what it published.
    """
    t = _transport(tmp_path)
    other = _sha(t, _push(t, tmp_path, device="desktop", parents=[]))
    _push(t, tmp_path, device="laptop", parents=[])
    assert t.detect_forks()[0].first_connect is True

    _push(t, tmp_path, device="laptop", parents=[], supersedes=[other])

    assert [h.device_name for h in t.lineage().heads] == ["laptop", "laptop"]
    assert t.detect_forks() == []


# ==================== the single-device rule ====================

@pytest.mark.unit
def test_two_heads_from_one_device_are_not_a_divergence(tmp_path):
    """A retry after a crash is its own work twice, not two students' work."""
    t = _transport(tmp_path)
    base = _sha(t, _push(t, tmp_path, device="laptop", parents=[]))
    _push(t, tmp_path, device="laptop", parents=[base])
    _push(t, tmp_path, device="laptop", parents=[base])

    assert len(t.lineage().heads) == 2
    assert t.detect_forks() == []


# ==================== legacy manifests ====================

@pytest.mark.unit
def test_a_legacy_linear_history_still_has_one_head(tmp_path):
    """Manifests written before lineage fall back to parent_generation."""
    t = _transport(tmp_path)
    _push(t, tmp_path, device="laptop")          # no parents -> legacy
    _push(t, tmp_path, device="desktop")
    g3 = _push(t, tmp_path, device="laptop")
    assert [h.blob_name for h in t.lineage().heads] == [g3.blob_name]


@pytest.mark.unit
def test_a_legacy_fork_is_still_detected(tmp_path):
    """Tonight's WIMI-fork-test folder is exactly this shape."""
    t = _transport(tmp_path)
    _push(t, tmp_path, device="laptop")
    _push(t, tmp_path, device="laptop", parent_generation=1)
    _push(t, tmp_path, device="desktop", parent_generation=1)
    forks = t.detect_forks()
    assert len(forks) == 1 and forks[0].parent_generation == 1


@pytest.mark.unit
def test_a_lineage_manifest_can_resolve_a_legacy_fork(tmp_path):
    """Mixed folders: the first post-#148 push must be able to clear an old fork."""
    t = _transport(tmp_path)
    _push(t, tmp_path, device="laptop")
    left = _sha(t, _push(t, tmp_path, device="laptop", parent_generation=1))
    right = _sha(t, _push(t, tmp_path, device="desktop", parent_generation=1))
    assert t.detect_forks()

    _push(t, tmp_path, device="laptop", parents=[left], supersedes=[right])
    assert t.detect_forks() == []


# ==================== the losing side learns it lost ====================

@pytest.mark.unit
def test_is_superseded_names_the_generation_that_retired_a_side(tmp_path):
    """How a device learns its copy was not the one kept."""
    t = _transport(tmp_path)
    base = _sha(t, _push(t, tmp_path, device="laptop", parents=[]))
    mine = _sha(t, _push(t, tmp_path, device="laptop", parents=[base]))
    theirs = _sha(t, _push(t, tmp_path, device="desktop", parents=[base]))
    resolution = _push(t, tmp_path, device="laptop", parents=[mine], supersedes=[theirs])

    graph = t.lineage()
    retired_by = graph.is_superseded(theirs)
    assert retired_by is not None and retired_by.blob_name == resolution.blob_name
    assert graph.is_superseded(mine) is None


# ==================== robustness ====================

@pytest.mark.unit
def test_a_reference_to_a_missing_digest_is_ignored_not_fatal(tmp_path):
    """An append-only folder should not lose files; one that has must still enumerate."""
    t = _transport(tmp_path)
    _push(t, tmp_path, device="laptop", parents=["f" * 64])
    assert len(t.lineage().heads) == 1
    assert t.detect_forks() == []


@pytest.mark.unit
def test_the_newest_generation_is_always_a_head(tmp_path):
    """Why resolve_head (highest generation) needs no change.

    A generation can only be named by one pushed after it, which is numbered
    higher. So nothing can name the newest one, and it is always a head.
    """
    t = _transport(tmp_path)
    base = _sha(t, _push(t, tmp_path, device="laptop", parents=[]))
    _push(t, tmp_path, device="laptop", parents=[base])
    newest = _push(t, tmp_path, device="desktop", parents=[base])

    head, _ = t.resolve_head(allow_hydration=False)
    assert head.manifest.blob_name == newest.blob_name
    assert newest.blob_name in {h.blob_name for h in t.lineage().heads}
