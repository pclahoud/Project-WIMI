"""#503: a second local copy of one profile cannot be linked into the folder
its sibling already uses.

The folder segment is the profile uuid, and an archive installed twice -- or
a fork resolved with Keep both -- leaves two local profiles sharing one. If
both were linked to the same folder they would publish into one segment and
fork against each other on this very computer, which is the state #124 says
only one of them may be in. ``install_from_folder`` already refuses the
equivalent case with a sentence; linking used to accept it silently.

Narrow by design: only the SAME folder is refused. A different folder is a
different root and collides with nothing.
"""
from __future__ import annotations

import pytest

from app.foldersync import ProfileFolderSync
from app.foldersync.service import LinkNeedsConfirmation
from app.foldersync.transport import TransportError
from app.profile_archive import build_profile_archive, install_profile_as_new
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


def _seed(master: MasterDatabase, username: str) -> int:
    user = master.create_user(username=username, display_name=username.title())
    UserDatabase(db_path=master.ensure_user_database(user.id),
                 user_id=user.id, username=user.username).close()
    return user.id


@pytest.fixture
def here(tmp_path):
    """One computer holding two copies of one profile, and an unrelated one."""
    master = MasterDatabase(data_dir=tmp_path / "app", error_logger=None)
    first = _seed(master, "student")
    archive = tmp_path / "student.wimi"
    build_profile_archive(master, first, archive, include_media=False)
    second = int(install_profile_as_new(master, archive)["user_id"])
    other = _seed(master, "someone_else")
    sync = ProfileFolderSync(master, timeout_s=10.0)
    folder = tmp_path / "cloud"
    folder.mkdir()
    yield {"master": master, "sync": sync, "folder": folder, "tmp": tmp_path,
           "first": first, "second": second, "other": other}
    master.close()


def _usernames(master, *ids):
    return [master.get_user(user_id=i).username for i in ids]


@pytest.mark.unit
def test_the_fixture_really_holds_two_copies_of_one_profile(here):
    """Positive control: without a shared uuid every test below is vacuous."""
    sync = here["sync"]
    assert sync._profile_uuid(here["first"]) == sync._profile_uuid(here["second"])
    assert sync._profile_uuid(here["other"]) != sync._profile_uuid(here["first"])


@pytest.mark.unit
def test_a_second_copy_is_refused_the_folder_its_sibling_uses(here):
    sync, folder = here["sync"], here["folder"]
    sync.link(here["first"], folder, "generic")

    with pytest.raises(TransportError) as exc:
        sync.link(here["second"], folder, "generic")

    first_name, = _usernames(here["master"], here["first"])
    assert repr(first_name) in str(exc.value), "the sentence must name the sibling"
    assert "different folder" in str(exc.value)
    assert sync.state.get_link(here["second"]) is None, "nothing may be recorded"


@pytest.mark.unit
def test_the_refusal_comes_before_the_warning_question(here):
    """Asking "use this folder anyway?" and then refusing is a question for nothing."""
    sync, folder = here["sync"], here["folder"]
    sync.link(here["first"], folder, "generic")
    plan = sync.prepare_link(here["second"], folder, "generic")

    with pytest.raises(TransportError, match="already linked to this folder"):
        sync.finish_link(plan, ["a warning the student has not seen yet"])


@pytest.mark.unit
def test_the_same_folder_spelled_differently_is_still_the_same_folder(here):
    sync, folder = here["sync"], here["folder"]
    sync.link(here["first"], folder, "generic")
    # ``Path`` keeps a ``..`` segment (it drops a trailing separator, so that
    # spelling never reached the comparison); only the normalisation folds it.
    respelt = str(folder / ".." / folder.name)
    assert respelt != str(folder)

    with pytest.raises(TransportError, match="already linked to this folder"):
        sync.link(here["second"], respelt, "generic")


@pytest.mark.unit
def test_a_different_folder_is_allowed(here):
    sync = here["sync"]
    sync.link(here["first"], here["folder"], "generic")
    elsewhere = here["tmp"] / "other-cloud"
    elsewhere.mkdir()

    link = sync.link(here["second"], elsewhere, "generic")

    assert not isinstance(link, LinkNeedsConfirmation)
    assert sync.state.get_link(here["second"]).folder == str(elsewhere)


@pytest.mark.unit
def test_an_unrelated_profile_shares_the_folder_freely(here):
    """Different uuids are different segments; that is what the uuid is for."""
    sync, folder = here["sync"], here["folder"]
    sync.link(here["first"], folder, "generic")

    sync.link(here["other"], folder, "generic")

    assert sync.state.get_link(here["other"]).folder == str(folder)


@pytest.mark.unit
def test_relinking_the_same_profile_to_its_own_folder_is_not_refused(here):
    """The profile being linked is not its own sibling."""
    sync, folder = here["sync"], here["folder"]
    sync.link(here["first"], folder, "generic")

    sync.link(here["first"], folder, "generic")

    assert sync.state.get_link(here["first"]).folder == str(folder)


@pytest.mark.unit
def test_an_unlinked_sibling_does_not_block(here):
    sync, folder = here["sync"], here["folder"]
    sync.link(here["first"], folder, "generic")
    sync.unlink(here["first"])

    sync.link(here["second"], folder, "generic")

    assert sync.state.get_link(here["second"]).folder == str(folder)
