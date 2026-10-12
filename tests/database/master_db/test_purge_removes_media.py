"""A purged profile takes its images with it (#506, #496).

The delete modal promises that after the grace period a profile "is
permanently removed, including all its entries and data". The purge removed
the ``users`` row and the archived ``.db`` and never touched
``media/user_<id>_<username>/``, so every image survived, attributable by the
username in the folder name, with no row left that could find it again.
Measured on master at ``c464b54`` on Windows machine B before this change.

Every deletion here goes through the path the bridge takes --
``soft_delete_user`` **then** ``confirm_user_deletion`` (``profiles.py``'s
``deleteProfile``). A probe that skips the confirmation reports that nothing
is ever purged, because the purge requires ``deletion_confirmed``, and that
reads exactly like a second, larger defect.

``soft_deleted_at`` is backdated 20 days rather than 11 so that #501 (a UTC
stamp compared with local time) cannot move the result either way.
"""
from __future__ import annotations

import shutil

import pytest


def _media_dir(master_db, user):
    return master_db.data_dir / "media" / f"user_{user.id}_{user.username}"


def _profile_with_images(master_db, username):
    user = master_db.create_user(username=username, display_name=username)
    master_db.ensure_user_database(user.id)
    media = _media_dir(master_db, user)
    (media / "entry_7").mkdir(parents=True)
    (media / "entry_7" / "a1b2.png").write_bytes(b"png")
    (media / "entry_7" / "a1b2_thumb.jpg").write_bytes(b"jpg")
    return user


def _delete(master_db, user, *, days_ago):
    master_db.soft_delete_user(user.id)
    master_db.confirm_user_deletion(user.id)
    with master_db.transaction():
        master_db.execute(
            "UPDATE users SET soft_deleted_at = datetime('now', ?) WHERE id = ?",
            (f"-{days_ago} days", user.id))


def test_the_purge_removes_the_profiles_images(master_db, admin_user):
    user = _profile_with_images(master_db, "sam")
    _delete(master_db, user, days_ago=20)

    assert master_db.permanently_delete_expired_users() == [user.id]
    assert master_db.get_user(user.id) is None
    assert not (master_db.archive_dir / user.database_filename).exists()
    assert not _media_dir(master_db, user).exists(), "the images outlived the profile"


def test_inside_the_grace_period_the_images_stay_so_restore_gets_them_back(
        master_db, admin_user):
    """Positive control: the purge is gated on the grace period, not just working."""
    user = _profile_with_images(master_db, "sam")
    _delete(master_db, user, days_ago=1)

    assert master_db.permanently_delete_expired_users() == []
    assert (_media_dir(master_db, user) / "entry_7" / "a1b2.png").exists()
    master_db.restore_user(user.id)
    assert (_media_dir(master_db, user) / "entry_7" / "a1b2.png").exists()


def test_an_unconfirmed_deletion_is_not_purged_and_keeps_its_images(master_db, admin_user):
    user = _profile_with_images(master_db, "sam")
    master_db.soft_delete_user(user.id)
    with master_db.transaction():
        master_db.execute(
            "UPDATE users SET soft_deleted_at = datetime('now', '-20 days') WHERE id = ?",
            (user.id,))

    assert master_db.permanently_delete_expired_users() == []
    assert _media_dir(master_db, user).exists()


def test_another_profiles_images_are_untouched(master_db, admin_user):
    doomed = _profile_with_images(master_db, "sam")
    kept = _profile_with_images(master_db, "samantha")
    _delete(master_db, doomed, days_ago=20)

    master_db.permanently_delete_expired_users()
    assert (_media_dir(master_db, kept) / "entry_7" / "a1b2.png").exists()


def test_a_profile_with_no_media_folder_still_purges(master_db, admin_user):
    user = master_db.create_user(username="plain", display_name="plain")
    master_db.ensure_user_database(user.id)
    _delete(master_db, user, days_ago=20)

    assert master_db.permanently_delete_expired_users() == [user.id]


def test_if_the_images_cannot_be_removed_the_profile_is_kept_for_the_next_launch(
        master_db, admin_user, monkeypatch):
    """A half-done purge must not forget the folder: the row is what names it."""
    user = _profile_with_images(master_db, "sam")
    _delete(master_db, user, days_ago=20)

    def locked(path, *a, **k):
        raise PermissionError(32, "The process cannot access the file", str(path))

    monkeypatch.setattr(shutil, "rmtree", locked)
    assert master_db.permanently_delete_expired_users() == []
    assert master_db.get_user(user.id) is not None
    assert (master_db.archive_dir / user.database_filename).exists()

    monkeypatch.undo()
    assert master_db.permanently_delete_expired_users() == [user.id]
    assert not _media_dir(master_db, user).exists()


# ------------------------------------------------- the database's sidecars (#496)

@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_soft_delete_moves_the_sidecars_with_the_database(master_db, admin_user, suffix):
    """A ``-wal`` left behind holds commits the archived file does not have."""
    user = master_db.create_user(username="sam", display_name="sam")
    db_path = master_db.ensure_user_database(user.id)
    sidecar = db_path.with_name(db_path.name + suffix)
    sidecar.write_bytes(b"tail")

    master_db.soft_delete_user(user.id)
    archived = master_db.archive_dir / sidecar.name
    assert not sidecar.exists(), "the sidecar was left behind in users/"
    assert archived.read_bytes() == b"tail"

    master_db.restore_user(user.id)
    assert sidecar.read_bytes() == b"tail", "restore did not bring the sidecar back"
    assert not archived.exists()


def test_the_purge_removes_archived_sidecars(master_db, admin_user):
    user = master_db.create_user(username="sam", display_name="sam")
    db_path = master_db.ensure_user_database(user.id)
    db_path.with_name(db_path.name + "-wal").write_bytes(b"tail")
    _delete(master_db, user, days_ago=20)

    master_db.permanently_delete_expired_users()
    # Both places: a sidecar never moved to archive/ would leave the archive
    # empty and still be sitting in users/, belonging to nobody.
    assert list(master_db.archive_dir.iterdir()) == []
    assert not any(p.name.startswith(db_path.name) for p in master_db.users_dir.iterdir())
