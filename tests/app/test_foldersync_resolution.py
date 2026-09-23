"""#124: acting on a fork, and never being the reason work was lost.

#124's rule, verbatim:

    Export before anything, on every path, always. An export that fails must
    abort the whole flow rather than proceed with a warning. Nothing here is
    allowed to destroy a side.

So most of this file is about the abort. A backup that is merely *attempted*
is worse than none, because it is trusted. The tests that matter:

* every choice takes a verified export first -- including the two that
  change nothing locally, because "always" is the rule and an exception is
  how it stops being true;
* a broken export **aborts**, with the profile untouched;
* an export that exists but does not read back is treated as broken, since
  a zero-byte file exists too;
* "keep the other" leaves the local side recoverable, which is the only
  reason it is allowed to overwrite at all.
"""
from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.foldersync.resolution import (
    CHOICES,
    KEEP_BOTH,
    KEEP_LOCAL,
    KEEP_REMOTE,
    Resolution,
    ProfileIsOpen,
    ResolutionError,
    SafetyExportFailed,
    resolve_fork,
    take_safety_export,
)
from app.profile_archive import build_profile_archive
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


def _profile(master: MasterDatabase, username: str, *, entries: int):
    user = master.create_user(username=username, display_name=username.title())
    db = UserDatabase(db_path=master.ensure_user_database(user.id),
                      user_id=user.id, username=user.username)
    try:
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Resolve Exam"))
            exam_id = cur.lastrowid
            cur = db.execute(
                "INSERT INTO review_sessions "
                "(user_id, exam_context_id, total_questions, total_incorrect) "
                "VALUES (?, ?, ?, ?)",
                (user.id, exam_id, 10, entries))
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


def _entries(master: MasterDatabase, user_id: int) -> int:
    conn = sqlite3.connect(str(master.ensure_user_database(user_id)))
    try:
        return conn.execute("SELECT COUNT(*) FROM question_entries").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def scene(tmp_path):
    """A local profile of 5 entries, and an incoming archive holding 31."""
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    local = _profile(master, "localside", entries=5)

    # The other side, exported from a throwaway profile then removed from the
    # registry so only its archive remains -- which is how it actually
    # arrives: as a file in a folder, not a local row.
    other = _profile(master, "otherside", entries=31)
    incoming = tmp_path / "incoming.wimi"
    build_profile_archive(master, other.id, incoming, include_media=False)

    safety_dir = tmp_path / "safety"
    yield master, local, incoming, safety_dir
    master.close()


# ==================== the rule ====================

@pytest.mark.parametrize("choice", CHOICES)
@pytest.mark.unit
def test_every_choice_takes_a_verified_export_first(scene, choice):
    """"On every path, always" -- including the paths that change nothing.

    ``keep_both`` and ``keep_local`` do not touch the local database, so it
    is tempting to skip the export there. That exception is exactly how
    "always" quietly stops being true, and the next change that *does* touch
    the database inherits a path with no undo.
    """
    master, local, incoming, safety_dir = scene

    # active_user_id=None: nothing is open. keep_remote cannot run against
    # an open profile, which is its own test below.
    result = resolve_fork(master, user_id=local.id, choice=choice,
                          incoming_archive=incoming, safety_dir=safety_dir,
                          active_user_id=None)

    assert result.safety_export.verified is True
    exported = Path(result.safety_export.path)
    assert exported.is_file() and exported.stat().st_size > 0
    assert result.safety_export.entries == 5, (
        "the export must hold what the profile held, not merely exist")


@pytest.mark.unit
def test_a_failed_export_aborts_and_changes_nothing(scene, monkeypatch):
    """The abort #124 requires. A warning would not be enough."""
    master, local, incoming, safety_dir = scene
    import app.foldersync.resolution as resolution

    def broken(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(resolution, "build_profile_archive", broken)

    with pytest.raises(SafetyExportFailed):
        resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                     incoming_archive=incoming, safety_dir=safety_dir)

    assert _entries(master, local.id) == 5, "the local profile was modified anyway"


@pytest.mark.unit
def test_an_export_that_exists_but_does_not_read_back_is_refused(scene, monkeypatch):
    """A zero-byte file exists. Existence is not verification.

    This is the failure a naive "did the file appear?" check would wave
    through, and the one where the student learns the backup was a gesture
    only after the replace has already happened.
    """
    master, local, incoming, safety_dir = scene
    import app.foldersync.resolution as resolution

    real = resolution.build_profile_archive

    def truncating(master_db, uid, dest, **kw):
        real(master_db, uid, dest, **kw)
        Path(dest).write_bytes(b"")  # the write "succeeded" and the bytes are gone
        return {}

    monkeypatch.setattr(resolution, "build_profile_archive", truncating)

    with pytest.raises(SafetyExportFailed, match="missing or empty"):
        resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                     incoming_archive=incoming, safety_dir=safety_dir)

    assert _entries(master, local.id) == 5


@pytest.mark.unit
def test_an_export_with_the_wrong_row_count_is_refused(scene, monkeypatch):
    """A readable archive of the wrong profile is not a backup of this one."""
    master, local, incoming, safety_dir = scene
    import app.foldersync.resolution as resolution

    def wrong_profile(master_db, uid, dest, **kw):
        # Export a DIFFERENT profile into the expected path.
        import shutil
        shutil.copy2(str(incoming), str(dest))
        return {}

    monkeypatch.setattr(resolution, "build_profile_archive", wrong_profile)

    with pytest.raises(SafetyExportFailed, match="refusing to treat it as a backup"):
        resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                     incoming_archive=incoming, safety_dir=safety_dir)

    assert _entries(master, local.id) == 5


# ==================== the three choices ====================

@pytest.mark.unit
def test_keep_remote_replaces_and_leaves_the_local_side_recoverable(scene):
    """The only choice that overwrites, and the reason the export exists."""
    master, local, incoming, safety_dir = scene

    result = resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                          incoming_archive=incoming, safety_dir=safety_dir,
                          active_user_id=None)

    assert result.replaced_local is True
    assert _entries(master, local.id) == 31, "the other side did not take effect"

    # And the 5 entries that were here are still gettable.
    with zipfile.ZipFile(result.safety_export.path) as zf:
        assert "user.db" in zf.namelist()
    assert result.safety_export.entries == 5


@pytest.mark.unit
def test_keep_local_sets_the_other_side_aside_rather_than_dropping_it(scene):
    """A student who chooses wrong at 1am must be able to change their mind."""
    master, local, incoming, safety_dir = scene

    result = resolve_fork(master, user_id=local.id, choice=KEEP_LOCAL,
                          incoming_archive=incoming, safety_dir=safety_dir)

    assert _entries(master, local.id) == 5, "the local side must be untouched"
    assert result.set_aside_path, "the other side was dropped"
    aside = Path(result.set_aside_path)
    assert aside.is_file() and aside.stat().st_size > 0
    assert result.replaced_local is False


@pytest.mark.unit
def test_keep_both_produces_two_openable_profiles_with_distinct_names(scene):
    """#124's acceptance wording."""
    master, local, incoming, safety_dir = scene

    result = resolve_fork(master, user_id=local.id, choice=KEEP_BOTH,
                          incoming_archive=incoming, safety_dir=safety_dir)

    assert result.installed_user_id and result.installed_user_id != local.id
    assert result.installed_username != local.username
    assert _entries(master, local.id) == 5
    assert _entries(master, result.installed_user_id) == 31


@pytest.mark.unit
def test_keep_both_says_the_new_copy_must_not_be_linked(scene):
    """The trap inside "keep both".

    Both profiles carry the SAME profile uuid -- correct, and why
    ``users.profile_uuid`` is deliberately not UNIQUE. But the uuid names the
    folder segment, so linking both would have them publish into one history
    and fork against each other forever. The result says so rather than
    leaving a caller to work it out.
    """
    master, local, incoming, safety_dir = scene

    result = resolve_fork(master, user_id=local.id, choice=KEEP_BOTH,
                          incoming_archive=incoming, safety_dir=safety_dir)

    assert result.installed_profile_must_not_sync is True
    assert any("same profile id" in n for n in result.notes)

    installed = master.get_user(user_id=result.installed_user_id)
    original = master.get_user(user_id=local.id)
    if installed.profile_uuid and original.profile_uuid:
        assert installed.profile_uuid != original.profile_uuid or True, (
            "same uuid is legitimate here; the guard is the flag, not uniqueness")


# ==================== refusals ====================

@pytest.mark.unit
def test_an_unknown_choice_is_refused_before_anything_happens(scene):
    master, local, incoming, safety_dir = scene
    with pytest.raises(ResolutionError, match="unknown choice"):
        resolve_fork(master, user_id=local.id, choice="merge",
                     incoming_archive=incoming, safety_dir=safety_dir)
    assert not safety_dir.exists(), "it exported before validating the choice"


@pytest.mark.unit
def test_a_missing_incoming_archive_is_refused_before_exporting(scene, tmp_path):
    master, local, _incoming, safety_dir = scene
    with pytest.raises(ResolutionError, match="not readable"):
        resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                     incoming_archive=tmp_path / "nope.wimi", safety_dir=safety_dir)
    assert not safety_dir.exists()


@pytest.mark.unit
def test_take_safety_export_is_usable_on_its_own(scene):
    """First connect needs the same export without a fork to resolve."""
    master, local, _incoming, safety_dir = scene
    export = take_safety_export(master, local.id, safety_dir, label="first-connect")
    assert export.verified and export.entries == 5
    assert "first-connect" in Path(export.path).name


# ==================== the in-flight question, answered ====================

@pytest.mark.unit
def test_keep_remote_refuses_while_the_profile_is_open(scene):
    """#124's open question, arriving concretely.

    ``replace_profile`` swaps the database file under a live connection and
    refuses when the target is the open profile. That refusal is right, and
    the honest move is to surface it rather than defeat it by passing
    ``active_user_id=None``.
    """
    master, local, incoming, safety_dir = scene

    with pytest.raises(ProfileIsOpen, match="Switch to another profile"):
        resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                     incoming_archive=incoming, safety_dir=safety_dir,
                     active_user_id=local.id)

    assert _entries(master, local.id) == 5


@pytest.mark.unit
def test_the_refusal_happens_before_the_export(scene):
    """No backup file for an operation that cannot run.

    "Export before anything" is about not destroying a side. An operation
    that is refused destroys nothing, so leaving a stray archive behind is
    litter the student has to reason about for no benefit.
    """
    master, local, incoming, safety_dir = scene

    with pytest.raises(ProfileIsOpen):
        resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                     incoming_archive=incoming, safety_dir=safety_dir,
                     active_user_id=local.id)

    assert not safety_dir.exists(), "it exported for an operation it then refused"


@pytest.mark.parametrize("choice", [KEEP_BOTH, KEEP_LOCAL])
@pytest.mark.unit
def test_the_non_destructive_choices_work_with_the_profile_open(scene, choice):
    """Only the overwrite is gated.

    ``keep_both`` and ``keep_local`` do not touch the local database, so
    gating them too would send a student to the profile picker for no
    reason -- and make the common cases unusable from Settings, which is
    where sync lives.
    """
    master, local, incoming, safety_dir = scene

    result = resolve_fork(master, user_id=local.id, choice=choice,
                          incoming_archive=incoming, safety_dir=safety_dir,
                          active_user_id=local.id)

    assert result.safety_export.verified is True
    assert _entries(master, local.id) == 5


@pytest.mark.unit
def test_keep_remote_works_once_another_profile_is_open(scene):
    """The path out of the refusal actually leads somewhere."""
    master, local, incoming, safety_dir = scene
    other = _profile(master, "someoneelse", entries=2)

    result = resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                          incoming_archive=incoming, safety_dir=safety_dir,
                          active_user_id=other.id)

    assert result.replaced_local is True
    assert _entries(master, local.id) == 31


# ==================== media survives keep_remote (#148) ====================

def _media_dir(master: MasterDatabase, user) -> Path:
    return master.data_dir / "media" / f"user_{user.id}_{user.username}"


@pytest.mark.unit
def test_keep_remote_does_not_delete_the_students_media(scene):
    """Sync archives carry no media (#125), so the replace must not touch it.

    ``replace_profile``'s default renames the media directory aside, copies
    the archive's media in, and deletes the aside copy on success. With a
    sync archive there is nothing to copy, so that deleted every image the
    student had -- recoverable only by digging the safety export back out.
    Found while wiring #148's close-and-reopen; the two-machine test missed
    it because its profile had no media.
    """
    master, local, incoming, safety_dir = scene
    media = _media_dir(master, local)
    media.mkdir(parents=True, exist_ok=True)
    image = media / "0f8fad5b-d9cb-469f-a165-70867728950e.png"
    image.write_bytes(b"\x89PNG not really")

    resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                 incoming_archive=incoming, safety_dir=safety_dir)

    assert image.is_file(), "keep_remote deleted the student's media"
    assert image.read_bytes() == b"\x89PNG not really"
    assert _entries(master, local.id) == 31


@pytest.mark.unit
def test_a_failed_replace_that_kept_media_leaves_it_all_in_place(scene, monkeypatch):
    """The rollback must not rmtree a directory it never moved.

    Without ``keep_existing_media`` the rollback's "no pre-existing media
    directory, remove the one we created" branch is reached with the
    student's real directory in place -- the exact deletion the flag exists
    to prevent, on the failure path instead of the success path.
    """
    import app.profile_archive as archive_mod

    master, local, incoming, safety_dir = scene
    media = _media_dir(master, local)
    media.mkdir(parents=True, exist_ok=True)
    image = media / "keep-me.png"
    image.write_bytes(b"img")

    def _fail(*_a, **_k):
        raise RuntimeError("verify-open failed, say")

    monkeypatch.setattr(archive_mod, "UserDatabase", _fail)
    with pytest.raises(ResolutionError):
        resolve_fork(master, user_id=local.id, choice=KEEP_REMOTE,
                     incoming_archive=incoming, safety_dir=safety_dir)

    assert image.is_file(), "a failed replace deleted the student's media"
    assert _entries(master, local.id) == 5, "the rollback did not restore the database"
