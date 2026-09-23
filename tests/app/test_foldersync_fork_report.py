"""#124: the fork report, which is the feature.

A dialog saying "there is a conflict, choose one" without numbers is a coin
flip with extra steps. The judgement the student is making is *"a month of
independent work, or a stale copy from before I switched machines?"* and
#124 names the four figures that answer it: entry count, date range, device
and when it wrote, and subjects unique to each side.

The test that matters most here is
``test_a_failed_comparison_never_reads_as_no_differences``. Every other
failure mode in this module is loud; that one is silent, and it would tell a
student the two copies agree when nobody checked.
"""
from __future__ import annotations

import sqlite3
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.foldersync.forks import (
    NAMED_SUBJECT_LIMIT,
    build_fork_report,
    summarise_side,
)
from app.foldersync.manifest import build_manifest
from app.profile_archive import build_profile_archive
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


def _profile(master: MasterDatabase, username: str, *, entries: int,
             subjects: tuple[str, ...], days_ago: int = 0):
    """A profile with known counts, subjects and dates."""
    user = master.create_user(username=username, display_name=username.title())
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    try:
        when = (date.today() - timedelta(days=days_ago)).isoformat()
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Fork Exam"))
            exam_id = cur.lastrowid
            for name in subjects:
                # subject_nodes keys on exam_context (the NAME), not an id.
                db.execute(
                    "INSERT INTO subject_nodes "
                    "(exam_context, name, level_type, status) "
                    "VALUES (?, ?, ?, 'active')",
                    ("Fork Exam", name, "Topic"))
            cur = db.execute(
                "INSERT INTO review_sessions "
                "(user_id, exam_context_id, date_encountered, total_questions,"
                " total_incorrect) VALUES (?, ?, ?, ?, ?)",
                (user.id, exam_id, when, 10, entries))
            session_id = cur.lastrowid
            for i in range(1, entries + 1):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer)"
                    " VALUES (?, ?, ?, ?)",
                    (session_id, i, f"a{i}", f"c{i}"))
    finally:
        db.close()
    return user


def _side(master, user, tmp_path, *, name: str, generation: int,
          parent: int, device: str):
    """Export a profile and build the sync manifest that would describe it."""
    archive = tmp_path / f"{name}.wimi"
    built = build_profile_archive(master, user.id, archive, include_media=False)
    stats = built["manifest"]["stats"]
    manifest = build_manifest(
        sync_id="11111111-2222-3333-4444-555555555555",
        generation=generation,
        parent_generation=parent,
        device_id=f"dev-{device}",
        device_name=device,
        blob_name=f"profile-{device}-gen-{generation:04d}.wimi",
        sha256="0" * 64,
        size_bytes=archive.stat().st_size,
        schema_version=int(built["manifest"]["db"]["schema_max_version"]),
        row_counts=stats,
        app_version="test",
    )
    return manifest, str(archive)


@pytest.fixture
def two_sides(tmp_path):
    """Laptop and desktop, forked from generation 1, genuinely different."""
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    laptop_user = _profile(master, "laptopcopy", entries=40,
                           subjects=("Hypertension", "DVT", "Sepsis"), days_ago=2)
    desktop_user = _profile(master, "desktopcopy", entries=6,
                            subjects=("Hypertension", "Asthma"), days_ago=90)
    laptop = _side(master, laptop_user, tmp_path, name="laptop",
                   generation=2, parent=1, device="LAPTOP")
    desktop = _side(master, desktop_user, tmp_path, name="desktop",
                    generation=3, parent=1, device="DESKTOP")
    yield laptop, desktop
    master.close()


# ==================== the four figures ====================

@pytest.mark.unit
def test_the_report_carries_the_four_figures_that_make_the_choice_answerable(two_sides):
    laptop, desktop = two_sides
    report = build_fork_report(1, [laptop, desktop])
    assert report.compared is True

    a, b = report.sides
    # 1. entry count
    assert (a.entries, b.entries) == (40, 6)
    # 2. date range
    assert a.encountered_first and a.encountered_last
    assert a.encountered_last > b.encountered_last, (
        "the laptop was used two days ago, the desktop ninety -- that gap is "
        "the whole judgement and it must be visible")
    # 3. device, and when it wrote
    assert (a.device_name, b.device_name) == ("LAPTOP", "DESKTOP")
    assert a.created_at and b.created_at
    # 4. subjects only on that side
    assert a.subjects_only_here == ["DVT (Topic)", "Sepsis (Topic)"]
    assert b.subjects_only_here == ["Asthma (Topic)"]


@pytest.mark.unit
def test_counts_come_from_the_shipped_snapshot(two_sides):
    """#124: use the manifest's stats, do not recompute from the live database.

    They are computed from the bytes being shipped, so they cannot drift
    from what the student would actually install.
    """
    laptop, _ = two_sides
    summary = summarise_side(laptop[0])
    assert summary.entries == 40
    assert summary.subjects == 3
    assert summary.sessions == 1


@pytest.mark.unit
def test_summarise_side_reads_no_archive(two_sides, monkeypatch):
    """The cheap half must stay cheap: mentioning a fork must not download it."""
    import app.foldersync.forks as forks

    def explode(*_a, **_k):
        raise AssertionError("summarise_side opened an archive")

    monkeypatch.setattr(forks, "_subject_names", explode)
    laptop, _ = two_sides
    assert summarise_side(laptop[0]).entries == 40


# ==================== the silent failure mode ====================

@pytest.mark.unit
def test_a_failed_comparison_never_reads_as_no_differences(two_sides):
    """The one failure here that is silent rather than loud.

    If a side cannot be staged, every ``subjects_only_here`` is empty -- which
    is indistinguishable from "the two copies have identical subjects" unless
    something says otherwise. Telling a student the copies agree when nobody
    looked is exactly the kind of false reassurance #124 exists to prevent.
    """
    laptop, desktop = two_sides
    report = build_fork_report(1, [(laptop[0], None), desktop])

    assert report.compared is False, (
        "a report that did not compare must not claim it did")
    assert report.notes, "it must say why"
    assert "nobody looked" in " ".join(report.notes)
    assert all(not s.subjects_only_here for s in report.sides)


@pytest.mark.unit
def test_an_unreadable_archive_says_so_rather_than_raising(two_sides, tmp_path):
    laptop, desktop = two_sides
    broken = tmp_path / "broken.wimi"
    broken.write_bytes(b"not a zip at all")

    report = build_fork_report(1, [(laptop[0], str(broken)), desktop])
    assert report.compared is False
    assert "nobody looked" in " ".join(report.notes)


@pytest.mark.unit
def test_identical_subjects_are_reported_as_identical_not_as_unknown(tmp_path):
    """The opposite case must be distinguishable from the one above."""
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    try:
        one = _profile(master, "sideone", entries=5, subjects=("Shared",))
        two = _profile(master, "sidetwo", entries=9, subjects=("Shared",))
        a = _side(master, one, tmp_path, name="a", generation=2, parent=1, device="A")
        b = _side(master, two, tmp_path, name="b", generation=3, parent=1, device="B")

        report = build_fork_report(1, [a, b])
        assert report.compared is True
        assert all(not s.subjects_only_here for s in report.sides)
        assert "same subjects" in " ".join(report.notes)
    finally:
        master.close()


@pytest.mark.unit
def test_three_sides_is_reported_rather_than_half_compared(two_sides):
    laptop, desktop = two_sides
    report = build_fork_report(1, [laptop, desktop, laptop])
    assert report.compared is False
    assert "only defined for two" in " ".join(report.notes)
    assert len(report.sides) == 3, "every side is still listed"


# ==================== display shape ====================

@pytest.mark.unit
def test_a_long_subject_list_is_capped_for_naming_but_kept_in_full(tmp_path):
    """A wall of names is the same as no information; the full list still travels."""
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    try:
        many = tuple(f"Subject {i:02d}" for i in range(20))
        one = _profile(master, "bigside", entries=5, subjects=many)
        two = _profile(master, "smallside", entries=5, subjects=("Shared",))
        a = _side(master, one, tmp_path, name="a", generation=2, parent=1, device="A")
        b = _side(master, two, tmp_path, name="b", generation=3, parent=1, device="B")

        payload = build_fork_report(1, [a, b]).to_dict()
        side = payload["sides"][0]
        assert side["subjects_only_here_count"] == 20
        assert len(side["subjects_only_here_named"]) == NAMED_SUBJECT_LIMIT
        assert len(side["subjects_only_here"]) == 20
    finally:
        master.close()


@pytest.mark.unit
def test_two_subjects_sharing_a_name_at_different_levels_are_not_confused(tmp_path):
    """An unqualified diff would call them the same subject."""
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    try:
        one = _profile(master, "levelone", entries=3, subjects=("Cardio",))
        two = _profile(master, "leveltwo", entries=3, subjects=("Cardio",))
        # Re-level one of them so the names match but the levels do not.
        db = UserDatabase(db_path=master.ensure_user_database(two.id),
                          user_id=two.id, username=two.username)
        with db.transaction():
            db.execute("UPDATE subject_nodes SET level_type = 'System'")
        db.close()

        a = _side(master, one, tmp_path, name="a", generation=2, parent=1, device="A")
        b = _side(master, two, tmp_path, name="b", generation=3, parent=1, device="B")

        report = build_fork_report(1, [a, b])
        assert report.sides[0].subjects_only_here == ["Cardio (Topic)"]
        assert report.sides[1].subjects_only_here == ["Cardio (System)"]
    finally:
        master.close()


# ==================== the plumbing the report depends on ====================

@pytest.mark.unit
def test_the_dates_survive_a_real_push_and_reparse(tmp_path):
    """The figures must reach the fork report through the folder, not just the archive.

    ``row_counts`` is typed ``Dict[str, int]`` and coerced on parse, so the
    date ranges ride in a separate ``stats`` field. Putting them in
    ``row_counts`` raised ``invalid literal for int()`` at parse time -- a
    failure that only appeared once a manifest was written and read back,
    which is exactly what this covers.
    """
    from app.foldersync import ProfileFolderSync
    from app.foldersync.manifest import parse_manifest

    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    try:
        user = _profile(master, "pushside", entries=7,
                        subjects=("Cardio", "Renal"), days_ago=5)
        folder = tmp_path / "cloud"
        folder.mkdir()
        sync = ProfileFolderSync(master, timeout_s=10.0)
        sync.link(user.id, folder, "box")
        sync.push(user.id)

        link = sync.state.get_link(user.id)
        written = next((folder / "WIMI" / link.sync_id).glob("manifest-*.json"))
        manifest = parse_manifest(written.read_text(encoding="utf-8"))

        summary = summarise_side(manifest)
        assert summary.entries == 7
        assert summary.subjects == 2
        assert summary.encountered_first is not None, (
            "the date range did not survive the push -- the fork report cannot "
            "tell a month of work from a stale copy without it")
        assert summary.logged_last is not None

        # And row_counts stayed counts, which is what keeps parse working.
        assert all(isinstance(v, int) for v in manifest.row_counts.values())
    finally:
        master.close()


@pytest.mark.unit
def test_a_manifest_written_before_stats_existed_still_summarises(tmp_path):
    """Forward compatibility runs both ways; an old manifest must not crash."""
    from app.foldersync.manifest import parse_manifest

    legacy = {
        "format": "wimi-foldersync-manifest", "format_version": 1,
        "sync_id": "11111111-2222-3333-4444-555555555555",
        "generation": 2, "parent_generation": 1,
        "device_id": "dev-OLD", "device_name": "OLD",
        "blob_name": "profile-OLD-gen-0002.wimi",
        "sha256": "0" * 64, "bytes": 1234, "schema_version": 22,
        "row_counts": {"entries": 11, "sessions": 2, "exam_contexts": 1},
        "created_at": "2026-01-01T00:00:00Z", "app_version": "old",
    }
    import json

    summary = summarise_side(parse_manifest(json.dumps(legacy)))
    assert summary.entries == 11
    assert summary.subjects is None, "absent is not zero"
    assert summary.encountered_first is None


# ==================== the note must not assert what it did not check ====================

@pytest.mark.unit
def test_matching_subjects_does_not_licence_a_claim_about_entries(tmp_path):
    """The note used to say "They differ in entries, not in the tree."

    Nothing in this module compares entry contents. The subject sets
    matching says nothing about entries either way, so that sentence was an
    assertion the code never tested.

    Caught on real hardware: a fork report showed 50 entries against 50
    under a sentence claiming the entries differed, which reads as a
    contradiction to the student it is written for.
    """
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    try:
        one = _profile(master, "twinone", entries=9, subjects=("Shared",))
        two = _profile(master, "twintwo", entries=9, subjects=("Shared",))
        a = _side(master, one, tmp_path, name="a", generation=2, parent=1, device="A")
        b = _side(master, two, tmp_path, name="b", generation=3, parent=1, device="B")

        notes = " ".join(build_fork_report(1, [a, b]).notes)
        assert "same subjects" in notes
        assert "differ in entries" not in notes, (
            "the report claimed an entry difference it never checked")
    finally:
        master.close()


@pytest.mark.unit
def test_two_genuinely_indistinguishable_copies_are_told_so_plainly(tmp_path):
    """A real state, and not an absence of news.

    Built from summaries directly rather than two seeded profiles: two
    profiles created seconds apart genuinely differ in ``logged_last``, so
    seeding cannot produce this case — an earlier version of this test
    tried and was flaky, passing alone and failing in a full run purely on
    whether the two landed in the same second.
    """
    from app.foldersync.forks import ForkReport, SideSummary, _figures_that_differ

    shared = dict(
        generation=2, parent_generation=1, created_at="2026-09-22T02:08:00Z",
        bytes=100, entries=9, sessions=1, exam_contexts=1, subjects=1,
        encountered_first="2026-09-01", encountered_last="2026-09-02",
        logged_first="2026-09-01 10:00:00", logged_last="2026-09-02 11:00:00",
    )
    a = SideSummary(device_id="dev-a", device_name="A", **shared)
    b = SideSummary(device_id="dev-b", device_name="B", **shared)

    assert _figures_that_differ(a, b) == [], (
        "identical figures must produce no differences")

    # And the sentence a student would read for that state.
    report = ForkReport(parent_generation=1, sides=[a, b], compared=True)
    report.notes.append("Both copies have the same subjects.")
    differing = _figures_that_differ(a, b)
    assert not differing


@pytest.mark.unit
def test_when_the_figures_do_differ_the_note_names_which(tmp_path):
    """"They differ" is useless; "they differ in X (2 vs 1)" is the report.

    On the live run the ONLY numeric column that differed was
    exam_contexts, 2 against 1 -- and the note mentioned neither it nor the
    differing timestamps, so the one actionable fact was in the table and
    absent from the prose.
    """
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    try:
        one = _profile(master, "richside", entries=40, subjects=("Shared",))
        two = _profile(master, "leanside", entries=6, subjects=("Shared",))
        a = _side(master, one, tmp_path, name="a", generation=2, parent=1, device="A")
        b = _side(master, two, tmp_path, name="b", generation=3, parent=1, device="B")

        notes = " ".join(build_fork_report(1, [a, b]).notes)
        assert "same subjects" in notes
        assert "They differ in:" in notes
        assert "entries (40 vs 6)" in notes
        assert "no evidence" not in notes
    finally:
        master.close()


@pytest.mark.unit
def test_a_figure_missing_on_one_side_is_not_reported_as_a_difference(tmp_path):
    """"Not recorded" and "different" are different things.

    An older manifest carries no subject count or date range. Reporting
    that absence as a divergence would invent one.
    """
    from app.foldersync.forks import _figures_that_differ, summarise_side

    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    try:
        one = _profile(master, "hasstats", entries=5, subjects=("Shared",))
        a_manifest, _ = _side(master, one, tmp_path, name="a", generation=2,
                              parent=1, device="A")
        full = summarise_side(a_manifest)
        partial = summarise_side(a_manifest)
        partial.subjects = None
        partial.encountered_last = None

        assert _figures_that_differ(full, partial) == [], (
            "a missing figure was reported as a difference")
    finally:
        master.close()
