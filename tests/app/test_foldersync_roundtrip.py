"""
Two devices, one folder — the end-to-end proof for the folder transport (SPIKE, #123).

A "device" here is an **app-data directory**: its own ``MasterDatabase``, its own
per-user databases, its own device identity. Two of them pointed at one plain
local directory is exactly the shape of a laptop and a desktop sharing a Box
folder, minus Box — and that is deliberate, because the transport must not care
which client is watching the folder, and there is no Box account to test with.

What these prove:

*   a profile pushed on device A arrives on device B with **byte-identical**
    content, verified by SHA-256 and by comparing the snapshot bytes;
*   a manifest whose blob fails verification is ignored and the next-highest
    valid generation is used instead;
*   a push interrupted between blob and manifest leaves the previous generation
    authoritative;
*   an archive from a newer schema is refused with ``preflight_schema``'s reason;
*   a simulated Box conflict copy is recognised and reported as recoverable;
*   two devices editing from the same ancestor are detected as a fork.

No Qt, no network, no cloud client.
"""
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.foldersync import ProfileFolderSync
from app.foldersync.transport import FolderTransport, TransportError
from app.profile_archive import (
    VERDICT_NEWER_APP_REQUIRED,
    build_profile_archive,
    VERDICT_OK,
    install_profile_as_new,
)
from database.master_db import MasterDatabase
from database.migrations.user import MIGRATIONS as USER_MIGRATIONS
from database.user_db import UserDatabase

LOCAL_MAX = max(m.version for m in USER_MIGRATIONS)


# ==================== helpers ====================

def _seed(master_db: MasterDatabase, user, n_entries: int = 3, exam_name: str = "Sample Exam") -> None:
    """Open the user's DB (which runs migrations) and seed exam / session / entries."""
    db_path = master_db.ensure_user_database(user.id)
    db = UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
    try:
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, exam_name),
            )
            exam_id = cur.lastrowid
            cur = db.execute(
                "INSERT INTO review_sessions "
                "(user_id, exam_context_id, total_questions, total_incorrect) "
                "VALUES (?, ?, ?, ?)",
                (user.id, exam_id, 10, n_entries),
            )
            session_id = cur.lastrowid
            for i in range(1, n_entries + 1):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, i, f"answer_{i}", f"correct_{i}"),
                )
    finally:
        db.close()


def _add_entries(master_db: MasterDatabase, user, n: int) -> None:
    """Append more entries to an existing profile — 'the student did more work'."""
    db_path = master_db.ensure_user_database(user.id)
    db = UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
    try:
        with db.transaction():
            session_id = db.execute(
                "SELECT id FROM review_sessions ORDER BY id LIMIT 1"
            ).fetchone()[0]
            start = db.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
            for i in range(start + 1, start + 1 + n):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, i, f"answer_{i}", f"correct_{i}"),
                )
    finally:
        db.close()


def _entry_count(master_db: MasterDatabase, user_id: int) -> int:
    conn = sqlite3.connect(str(master_db.ensure_user_database(user_id)))
    try:
        return conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
    finally:
        conn.close()


def _db_bytes_from_archive(archive: Path) -> bytes:
    """The exact ``user.db`` member bytes — the payload the sync actually moved."""
    with zipfile.ZipFile(str(archive)) as zf:
        return zf.read("user.db")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ==================== fixtures ====================

@pytest.fixture
def cloud_folder(tmp_path):
    """
    The 'cloud' folder — a plain local directory.

    This stands in for whatever Box Drive, OneDrive, Drive or a USB stick would
    present. The transport is not told which, and must not care.
    """
    folder = tmp_path / "CloudFolder"
    folder.mkdir()
    return folder


@pytest.fixture
def device_a(tmp_path):
    """Device A — its own app-data dir, its own master registry, its own identity."""
    db = MasterDatabase(data_dir=tmp_path / "device_a", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def device_b(tmp_path):
    """Device B — a genuinely separate installation."""
    db = MasterDatabase(data_dir=tmp_path / "device_b", error_logger=None)
    yield db
    db.close()


@pytest.fixture
def sync_a(device_a):
    return ProfileFolderSync(device_a, timeout_s=10.0)


@pytest.fixture
def sync_b(device_b):
    return ProfileFolderSync(device_b, timeout_s=10.0)


@pytest.fixture
def alice(device_a):
    user = device_a.create_user(
        username="alice", display_name="Alice Example", email="alice@example.com"
    )
    _seed(device_a, user, n_entries=3)
    return user


# ==================== the round trip ====================

class TestTwoDeviceRoundTrip:

    def test_profile_pushed_on_a_arrives_byte_identical_on_b(
        self, sync_a, sync_b, alice, cloud_folder
    ):
        """
        The headline acceptance criterion from #123.

        Byte-identity is asserted three ways, because each catches a different
        failure: the blob's SHA-256 (transport integrity), the ``user.db`` member
        bytes (payload integrity), and the row counts after install (the thing
        the student actually cares about).
        """
        sync_a.link(alice.id, cloud_folder, "box")
        pushed = sync_a.push(alice.id)
        assert pushed.generation == 1
        assert pushed.parent_generation == 0

        # Device B has never seen this folder before.
        discovered = sync_b.discover(cloud_folder, "box")
        assert len(discovered) == 1
        assert discovered[0]["head"]["generation"] == 1
        sync_id = discovered[0]["sync_id"]

        fetched = sync_b.fetch_from(cloud_folder, sync_id, "box")
        assert fetched.generation == 1
        assert fetched.schema_verdict == VERDICT_OK
        assert fetched.blocked is False

        # (1) transport integrity
        assert _sha256(Path(fetched.archive_path)) == pushed.sha256
        # (2) payload integrity — the snapshot bytes are the same bytes
        assert _db_bytes_from_archive(Path(pushed.blob_path)) == \
               _db_bytes_from_archive(Path(fetched.archive_path))

        # (3) install it and compare what the student would see
        installed = install_profile_as_new(sync_b.master_db, fetched.archive_path)
        assert _entry_count(sync_b.master_db, installed["user_id"]) == 3
        assert installed["username"] == "alice"

    def test_a_full_lap_back_to_the_first_device(
        self, sync_a, sync_b, device_a, device_b, alice, cloud_folder
    ):
        """
        A -> B -> (more work) -> A. The generation chain must stay linear and the
        second device's work must come back.
        """
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)

        sync_id = sync_a.state.get_link(alice.id).sync_id
        fetched = sync_b.fetch_from(cloud_folder, sync_id, "box")
        installed = install_profile_as_new(device_b, fetched.archive_path)
        bob_id = installed["user_id"]
        # What B now holds descends from generation 1, and only B can say
        # so (#149). Without this B's push would claim no ancestor.
        sync_b.record_install(bob_id, sync_id, fetched.manifest)

        # B does more work and pushes generation 2.
        _add_entries(device_b, device_b.get_user(user_id=bob_id), 4)
        sync_b.link(bob_id, cloud_folder, "box")
        second = sync_b.push(bob_id)
        assert second.generation == 2
        assert second.parent_generation == 1

        # A fetches it back.
        back = sync_a.fetch(alice.id)
        assert back.generation == 2
        assert back.manifest.row_counts["entries"] == 7
        # The two devices are genuinely distinct writers.
        assert second.blob_name != sync_a.state.get_link(alice.id).sync_id
        assert sync_a._device_identity().device_id != sync_b._device_identity().device_id

    def test_the_two_devices_write_disjoint_paths(
        self, sync_a, sync_b, device_b, alice, cloud_folder
    ):
        """
        The property everything else rests on. Every provider misbehaviour worth
        fearing is downstream of two writers sharing a path.
        """
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)

        sync_id = sync_a.state.get_link(alice.id).sync_id
        installed = install_profile_as_new(
            device_b, sync_b.fetch_from(cloud_folder, sync_id, "box").archive_path
        )
        sync_b.link(installed["user_id"], cloud_folder, "box")
        sync_b.push(installed["user_id"])

        names = sorted(p.name for p in (cloud_folder / "WIMI" / sync_id).iterdir())
        assert len(names) == len(set(names))          # nothing was overwritten
        assert len([n for n in names if n.endswith(".wimi")]) == 2
        assert len([n for n in names if n.endswith(".json")]) == 2

    def test_the_same_profile_on_both_devices_derives_one_folder_segment(
        self, sync_a, sync_b, device_b, alice, cloud_folder, tmp_path
    ):
        """
        Pointing both devices at one folder must not split it in two -- and
        there is now nothing to negotiate in order to get that right.

        The segment is ``WIMI/<profile-uuid>/``, and ``install_profile_as_new``
        preserves the incoming uuid, so device B *computes* the same path
        rather than adopting one out of a manifest it found there.
        """
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)

        archive = tmp_path / "alice.wimi"
        build_profile_archive(sync_a.master_db, alice.id, archive)
        installed = install_profile_as_new(device_b, archive)

        link_b = sync_b.link(installed["user_id"], cloud_folder, "box")
        assert link_b.sync_id == sync_a.state.get_link(alice.id).sync_id
        assert len(list((cloud_folder / "WIMI").iterdir())) == 1

    def test_a_different_profile_gets_its_own_segment_not_the_first_ones(
        self, sync_a, sync_b, device_b, alice, cloud_folder
    ):
        """
        The regression the identity change actually buys.

        The spike adopted the folder's sync id whenever the folder held
        exactly one profile -- so an unrelated profile linked to a shared
        folder silently joined **someone else's generation chain** and began
        overwriting a history that was not its own. #129 called this "a manual
        act of faith"; it was worse than that, because nothing could detect it.

        With the segment derived from the profile uuid the two cannot
        collide, and the folder simply holds two profiles.
        """
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)

        bob = device_b.create_user(username="bob", display_name="Bob")
        _seed(device_b, bob, n_entries=1, exam_name="Bob's Exam")

        link_b = sync_b.link(bob.id, cloud_folder, "box")
        assert link_b.sync_id != sync_a.state.get_link(alice.id).sync_id

        # Bob's first push lands beside Alice's chain, not inside it. Under
        # the spike this would have been generation 2 of *Alice's* history.
        pushed = sync_b.push(bob.id)
        assert pushed.generation == 1
        assert len(list((cloud_folder / "WIMI").iterdir())) == 2

    def test_a_profile_with_no_identity_yet_is_refused_rather_than_invented(
        self, sync_b, device_b, cloud_folder
    ):
        """
        Minting a uuid here would give one profile two identities across two
        machines. Refusing names what to do instead.
        """
        stranger = device_b.create_user(username="stranger", display_name="S")
        with pytest.raises(TransportError, match="no stable identifier"):
            sync_b.link(stranger.id, cloud_folder, "box")

    def test_discover_recognises_a_profile_this_machine_already_has(
        self, sync_a, sync_b, device_b, alice, cloud_folder, tmp_path
    ):
        """
        #129: there was no "this profile is already linked here" check
        anywhere. The folder segment is the profile uuid, so there is one now.
        """
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)

        # Before B has the profile at all, the folder is unrecognised.
        assert sync_b.discover(cloud_folder, "box")[0]["local_profiles"] == []

        archive = tmp_path / "alice.wimi"
        build_profile_archive(sync_a.master_db, alice.id, archive)
        installed = install_profile_as_new(device_b, archive)

        found = sync_b.discover(cloud_folder, "box")
        assert len(found) == 1
        assert [p["user_id"] for p in found[0]["local_profiles"]] == [installed["user_id"]]


# ==================== the failure modes that must not lose data ====================

class TestDurability:

    def test_push_interrupted_between_blob_and_manifest(
        self, sync_a, device_a, alice, cloud_folder
    ):
        """
        #123 acceptance: 'A push interrupted between blob and manifest leaves the
        previous generation authoritative.'
        """
        sync_a.link(alice.id, cloud_folder, "generic")
        good = sync_a.push(alice.id)

        _add_entries(device_a, alice, 5)
        second = sync_a.push(alice.id)
        # Simulate the crash: the manifest never landed.
        Path(second.manifest_path).unlink()

        transport = FolderTransport(cloud_folder, sync_a.state.get_link(alice.id).sync_id, "generic")
        head, failures = transport.resolve_head()
        assert head.manifest.generation == good.generation == 1
        assert failures == []          # an orphan blob is nothing, not a failure
        assert Path(second.blob_path).exists()   # and it is left alone, not deleted

    def test_corrupted_head_falls_back_to_the_previous_generation(
        self, sync_a, device_a, alice, cloud_folder
    ):
        """
        #123 acceptance: 'A manifest whose blob fails verification is ignored, and
        the next-highest valid generation is used instead.'
        """
        sync_a.link(alice.id, cloud_folder, "generic")
        sync_a.push(alice.id)

        _add_entries(device_a, alice, 5)
        second = sync_a.push(alice.id)

        blob = Path(second.blob_path)
        payload = bytearray(blob.read_bytes())
        payload[len(payload) // 2] ^= 0xFF          # same length, one flipped bit
        blob.write_bytes(bytes(payload))

        fetched = sync_a.fetch(alice.id)
        assert fetched.generation == 1
        assert [f.generation for f in fetched.skipped] == [2]
        assert "checksum" in fetched.skipped[0].reason

    def test_a_newer_schema_is_refused_with_preflights_own_reason(
        self, sync_a, sync_b, alice, cloud_folder
    ):
        """
        #123 acceptance: 'An archive from a newer schema is refused with
        preflight_schema's reason string.' Cross-device schema skew is ALREADY
        solved — this asserts the verdict is surfaced, not re-derived.
        """
        sync_a.link(alice.id, cloud_folder, "generic")
        pushed = sync_a.push(alice.id)
        sync_id = sync_a.state.get_link(alice.id).sync_id

        # Rewrite the blob as an archive claiming a migration this build lacks,
        # then re-stamp the manifest so it verifies — the schema check must be
        # what stops it, not the checksum.
        self._forge_newer_schema(Path(pushed.blob_path), Path(pushed.manifest_path))

        fetched = sync_b.fetch_from(cloud_folder, sync_id, "generic")
        assert fetched.schema_verdict == VERDICT_NEWER_APP_REQUIRED
        assert fetched.blocked is True
        assert fetched.schema_reason           # a real, user-facing sentence
        assert str(LOCAL_MAX + 5) in fetched.schema_reason or "newer" in fetched.schema_reason.lower()

    @staticmethod
    def _forge_newer_schema(blob: Path, manifest_path: Path) -> None:
        work = blob.parent / "_forge"
        work.mkdir(exist_ok=True)
        try:
            with zipfile.ZipFile(str(blob)) as zf:
                zf.extractall(str(work))
            db = work / "user.db"
            conn = sqlite3.connect(str(db))
            try:
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                    (LOCAL_MAX + 5, "m999_from_the_future", "x" * 64),
                )
                conn.commit()
            finally:
                conn.close()

            with zipfile.ZipFile(str(blob), "w", zipfile.ZIP_DEFLATED) as out:
                for item in sorted(work.rglob("*")):
                    if item.is_file():
                        out.write(str(item), str(item.relative_to(work)).replace("\\", "/"))

            raw = json.loads(manifest_path.read_text())
            raw["sha256"] = _sha256(blob)
            raw["bytes"] = blob.stat().st_size
            manifest_path.write_text(json.dumps(raw), encoding="utf-8")
        finally:
            import shutil
            shutil.rmtree(str(work), ignore_errors=True)

    def test_media_is_not_shipped(self, sync_a, device_a, alice, cloud_folder):
        """
        Database only. Media is content-addressed and ships separately (#125),
        which is what keeps a generation at ~0.28 MB.
        """
        media_dir = device_a.data_dir / "media" / f"user_{alice.id}_{alice.username}"
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / "aaaa-bbbb.png").write_bytes(b"x" * 4096)

        sync_a.link(alice.id, cloud_folder, "generic")
        pushed = sync_a.push(alice.id)
        with zipfile.ZipFile(pushed.blob_path) as zf:
            assert not [n for n in zf.namelist() if n.startswith("media/")]

    def test_the_live_database_never_enters_the_folder(
        self, sync_a, alice, cloud_folder
    ):
        """
        Sealed archives only. Box documents that a database modified in place
        inside the folder produces conflict copies even with a single user.
        """
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)
        present = [p.name for p in cloud_folder.rglob("*") if p.is_file()]
        assert all(not n.endswith((".db", ".db-wal", ".db-shm")) for n in present), present
        assert all(n.endswith((".wimi", ".json")) for n in present), present

    def test_pushing_while_the_profile_is_open_still_works(
        self, sync_a, device_a, alice, cloud_folder
    ):
        """
        ``build_profile_archive`` snapshots via ``sqlite3.Connection.backup``, so
        an open profile is not a reason to refuse. Asserted because a sync that
        only works when the app is closed is not a sync.
        """
        db_path = device_a.ensure_user_database(alice.id)
        live = UserDatabase(db_path=db_path, user_id=alice.id, username=alice.username)
        try:
            sync_a.link(alice.id, cloud_folder, "generic")
            pushed = sync_a.push(alice.id)
            assert pushed.generation == 1
            assert pushed.bytes > 0
        finally:
            live.close()


# ==================== conflict copies, with real archives ====================

class TestBoxConflictCopyRecovery:
    """
    Box: "Documents with conflicts will either be appended with a number or email
    address in parentheses." (support.box.com 360044193873, stated identically in
    both the PC and Mac sections.)

    Generation-named files mean WIMI's own writes should never produce one. These
    can still appear if a student copies a profile between machines or restores
    from backup, so they are detected and offered — never acted on.
    """

    def test_an_identical_box_conflict_copy_is_reported_as_safe_to_delete(
        self, sync_a, alice, cloud_folder
    ):
        sync_a.link(alice.id, cloud_folder, "box")
        pushed = sync_a.push(alice.id)
        sync_dir = Path(pushed.blob_path).parent

        # Exactly what Box does: same bytes, a number in parentheses.
        copy = sync_dir / pushed.blob_name.replace(".wimi", " (1).wimi")
        copy.write_bytes(Path(pushed.blob_path).read_bytes())

        status = sync_a.status(alice.id)
        assert len(status.conflict_copies) == 1
        found = status.conflict_copies[0]
        assert found["marker"] == "1"
        assert found["copy_of"] == pushed.blob_name
        assert found["verifies_against_manifest"] is True
        assert "safe to delete" in found["note"]
        # And the real generation is still authoritative.
        assert status.head_generation == 1

    def test_a_box_email_conflict_copy_holding_different_work_is_flagged(
        self, sync_a, device_a, alice, cloud_folder
    ):
        sync_a.link(alice.id, cloud_folder, "box")
        pushed = sync_a.push(alice.id)
        sync_dir = Path(pushed.blob_path).parent

        # The other documented Box shape: an email address in parentheses,
        # carrying content that is NOT what the manifest describes.
        _add_entries(device_a, alice, 9)
        from app.profile_archive import build_profile_archive
        other = sync_dir.parent / "other.wimi"
        build_profile_archive(device_a, alice.id, other, include_media=False)
        copy = sync_dir / pushed.blob_name.replace(".wimi", " (alice@example.com).wimi")
        copy.write_bytes(other.read_bytes())
        other.unlink()

        found = sync_a.status(alice.id).conflict_copies[0]
        assert found["marker"] == "alice@example.com"
        assert found["verifies_against_manifest"] is False
        assert "may hold work" in found["note"]

    def test_a_students_own_unrelated_file_is_left_entirely_alone(
        self, sync_a, alice, cloud_folder
    ):
        sync_a.link(alice.id, cloud_folder, "box")
        pushed = sync_a.push(alice.id)
        sync_dir = Path(pushed.blob_path).parent
        (sync_dir / "Lecture notes (draft).pdf").write_bytes(b"not ours")

        status = sync_a.status(alice.id)
        assert status.conflict_copies == []
        assert (sync_dir / "Lecture notes (draft).pdf").read_bytes() == b"not ours"


# ==================== forks ====================

class TestForkDetection:
    """Detection is #123. The three-way choice dialog is #124 and is NOT here."""

    def test_two_devices_from_one_ancestor_are_detected_as_a_fork(
        self, sync_a, sync_b, device_a, device_b, alice, cloud_folder
    ):
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)                       # generation 1, the shared ancestor
        sync_id = sync_a.state.get_link(alice.id).sync_id

        installed = install_profile_as_new(
            device_b, sync_b.fetch_from(cloud_folder, sync_id, "box").archive_path
        )
        bob_id = installed["user_id"]
        sync_b.link(bob_id, cloud_folder, "box")

        # Both devices work offline from generation 1, then both push.
        _add_entries(device_a, alice, 5)
        _add_entries(device_b, device_b.get_user(user_id=bob_id), 11)
        sync_a.push(alice.id)                       # generation 2, parent 1

        # Device B pushes from parent 1 as well. Driven through the transport
        # directly so the fork is constructed deliberately: in the field this is
        # what happens when B pushed before it ever saw A's generation 2.
        transport = FolderTransport(cloud_folder, sync_id, "box")
        transport.push(
            blob_source=self._stage(device_b, bob_id, cloud_folder),
            device_id=sync_b._device_identity().device_id,
            device_name=sync_b._device_identity().device_name,
            schema_version=LOCAL_MAX,
            row_counts={"entries": 14},
            generation=3,
            parent_generation=1,                    # the fork: both built on 1
        )

        forks = sync_a.forks(alice.id)
        assert len(forks) == 1
        assert forks[0].parent_generation == 1
        assert len(forks[0].sides) == 2

        status = sync_a.status(alice.id)
        assert status.forks
        sides = status.forks[0]["sides"]
        # The fork report carries REAL NUMBERS, which is what makes the choice
        # answerable -- a student must be able to tell a month of work from a
        # stale copy, and only counts and dates do that.
        assert all("entries" in s and "created_at" in s and "device_name" in s for s in sides)

    @staticmethod
    def _stage(master_db, user_id, cloud_folder):
        from app.profile_archive import build_profile_archive
        staged = cloud_folder.parent / f"staged-{user_id}.wimi"
        build_profile_archive(master_db, user_id, staged, include_media=False)
        return staged

    def test_a_linear_history_is_never_a_fork(self, sync_a, device_a, alice, cloud_folder):
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)
        _add_entries(device_a, alice, 2)
        sync_a.push(alice.id)
        _add_entries(device_a, alice, 2)
        sync_a.push(alice.id)
        assert sync_a.forks(alice.id) == []


# ==================== honest status ====================

class TestStatusHonesty:
    """
    'You cannot force a sync or know when one finished.' The panel shows last
    seen generation and when — never a tick implying more than it knows.
    """

    def test_status_has_no_boolean_synced_field(self, sync_a, alice, cloud_folder):
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)
        status = sync_a.status(alice.id)
        assert not hasattr(status, "synced")
        assert not hasattr(status, "up_to_date")
        assert not hasattr(status, "in_sync")

    def test_status_reports_observations_with_timestamps(self, sync_a, alice, cloud_folder):
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)
        status = sync_a.status(alice.id)
        assert status.linked is True
        assert status.head_generation == 1
        assert status.last_seen_generation == 1
        assert status.last_seen_at and status.last_pushed_at
        assert status.head_created_at

    def test_status_names_the_pin_setting_for_the_chosen_provider(
        self, sync_a, alice, cloud_folder
    ):
        """Box's current menu wording, so the advice a user is given is followable."""
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)
        assert sync_a.status(alice.id).pin_hint == "Always keep on this device"

    def test_an_unlinked_profile_says_so_rather_than_guessing(self, sync_a, alice):
        status = sync_a.status(alice.id)
        assert status.linked is False
        assert status.folder is None

    def test_status_surfaces_rejected_generations(self, sync_a, device_a, alice, cloud_folder):
        """'We ignored generation 2 and used 1' is something a user is entitled to."""
        sync_a.link(alice.id, cloud_folder, "box")
        sync_a.push(alice.id)
        _add_entries(device_a, alice, 3)
        second = sync_a.push(alice.id)
        payload = bytearray(Path(second.blob_path).read_bytes())
        payload[10] ^= 0xFF
        Path(second.blob_path).write_bytes(bytes(payload))

        status = sync_a.status(alice.id)
        assert status.head_generation == 1
        assert status.rejected and status.rejected[0]["generation"] == 2


# ==================== realistic scale ====================

@pytest.mark.slow
class TestRealisticProfile:
    """
    The same round trip against a 2,575-subject profile from the USMLE Step 1
    outline fixture — the profile #22 comment #1455 measured at 54 ms -> 0.28 MB.
    """

    def test_full_outline_profile_round_trips_byte_identically(
        self, sync_a, sync_b, device_a, cloud_folder
    ):
        from wimi_test.db.seeders import seed_usmle_step1_outline

        user = device_a.create_user(username="emma", display_name="Emma")
        db_path = device_a.ensure_user_database(user.id)
        db = UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
        try:
            seed_usmle_step1_outline(db)
            subjects = db.execute("SELECT COUNT(*) FROM subject_nodes").fetchone()[0]
        finally:
            db.close()
        assert subjects > 2000, f"fixture only produced {subjects} subjects"

        sync_a.link(user.id, cloud_folder, "box")
        pushed = sync_a.push(user.id)
        sync_id = sync_a.state.get_link(user.id).sync_id

        fetched = sync_b.fetch_from(cloud_folder, sync_id, "box")
        assert _sha256(Path(fetched.archive_path)) == pushed.sha256
        assert _db_bytes_from_archive(Path(pushed.blob_path)) == \
               _db_bytes_from_archive(Path(fetched.archive_path))

        installed = install_profile_as_new(sync_b.master_db, fetched.archive_path)
        conn = sqlite3.connect(str(sync_b.master_db.ensure_user_database(installed["user_id"])))
        try:
            assert conn.execute("SELECT COUNT(*) FROM subject_nodes").fetchone()[0] == subjects
        finally:
            conn.close()
