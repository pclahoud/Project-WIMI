"""#147: looking at the folder must not download the archive.

Measured on Box, 2026-09-21, on two machines through two entry points:
hashing a cloud-only 26 KB blob cost **1,474 ms against 49.7 ms** for the
same call on a local one, and Box's own driver log showed the whole file
being pulled down (``reportDownloadCompleteImpl ... backgroundDownload:
false``). A *status* check was doing that — downloading the entire archive
to render "generation 2, from the other computer".

That defeats Files On-Demand, which is the thing students are told to turn
on, and it gets worse with #125's media.

The fix is ``allow_hydration=False`` on the display path: read the residency
flag, which is measured not to hydrate, and report the head as
``verified=False`` rather than downloading it to check. **A not-local blob
is not a failure** — treating it as one would walk past a perfectly good
generation and name an older one as head, which is worse than admitting the
check has not run.

Faking dataless on Linux
------------------------
There is no eviction here, so these patch ``residency`` to report what Box
actually reports. The attribute values are the measured ones:

    0x3000  OFFLINE | NOT_CONTENT_INDEXED   cloud-only
    0x2000  NOT_CONTENT_INDEXED             downloaded by Box
    0x2020  ARCHIVE | NOT_CONTENT_INDEXED   written locally

so ``dataless`` is the OFFLINE bit and nothing else.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.foldersync import ProfileFolderSync
from app.foldersync.hydration import Residency
from app.foldersync.transport import FolderTransport
from database.master_db import MasterDatabase
from database.user_db import UserDatabase


def _seed(master_db: MasterDatabase, user) -> None:
    db_path = master_db.ensure_user_database(user.id)
    db = UserDatabase(db_path=db_path, user_id=user.id, username=user.username)
    try:
        with db.transaction():
            cur = db.execute(
                "INSERT INTO exam_contexts (user_id, exam_name) VALUES (?, ?)",
                (user.id, "Hydration Exam"),
            )
            exam_id = cur.lastrowid
            cur = db.execute(
                "INSERT INTO review_sessions "
                "(user_id, exam_context_id, total_questions, total_incorrect) "
                "VALUES (?, ?, ?, ?)",
                (user.id, exam_id, 10, 2),
            )
            session_id = cur.lastrowid
            for i in (1, 2):
                db.execute(
                    "INSERT INTO question_entries "
                    "(review_session_id, entry_order, user_answer, correct_answer) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, i, f"a{i}", f"c{i}"),
                )
    finally:
        db.close()


@pytest.fixture
def pushed(tmp_path):
    """One generation in a folder, and a sync service pointed at it."""
    master = MasterDatabase(data_dir=tmp_path / "app_data", error_logger=None)
    user = master.create_user(username="sam", display_name="Sam")
    _seed(master, user)
    folder = tmp_path / "cloud"
    folder.mkdir()
    sync = ProfileFolderSync(master, timeout_s=10.0)
    sync.link(user.id, folder, "box")
    sync.push(user.id)
    yield sync, user, folder
    master.close()


class _Evictor:
    """Report every ``.wimi`` as cloud-only, and count real reads."""

    def __init__(self, monkeypatch, *, dataless=True):
        self.reads: list[str] = []
        self.dataless = dataless
        import app.foldersync.transport as transport_mod

        real_residency = transport_mod.residency

        def fake_residency(path):
            res: Residency = real_residency(path)
            if str(path).endswith(".wimi") and self.dataless:
                return Residency(res.path, res.exists, res.size_bytes,
                                 dataless=True, determinate=True)
            return res

        def loud_sha256(path, timeout_s=30.0):
            self.reads.append(str(path))
            return transport_mod.sha256_bounded.__wrapped__(path, timeout_s) \
                if hasattr(transport_mod.sha256_bounded, "__wrapped__") \
                else _real_sha(path)

        import hashlib

        def _real_sha(p):
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()

        monkeypatch.setattr(transport_mod, "residency", fake_residency)
        monkeypatch.setattr(transport_mod, "sha256_bounded", loud_sha256)


@pytest.mark.unit
def test_status_does_not_read_a_cloud_only_blob(pushed, monkeypatch):
    """The defect, directly. Looking must not download."""
    sync, user, _folder = pushed
    spy = _Evictor(monkeypatch)

    status = sync.status(user.id)

    assert spy.reads == [], (
        f"status hashed a cloud-only blob and so downloaded it: {spy.reads}. "
        f"That is #147 -- on Box it cost 1,474 ms and pulled the whole archive."
    )
    assert status.head_generation == 1, "the head must still be reported"
    assert status.head_verified is False, (
        "an unchecked head must say it is unchecked, not imply it was validated")
    assert status.rejected == [], (
        "a not-local blob is not a verification failure and must not be listed "
        "as one -- that would walk past a good generation")


@pytest.mark.unit
def test_status_still_verifies_a_local_blob(pushed, monkeypatch):
    """Option 2, not option 1: when the bytes are here, checking is free."""
    sync, user, _folder = pushed
    spy = _Evictor(monkeypatch, dataless=False)

    status = sync.status(user.id)

    assert spy.reads, "a local blob should still be checked -- hashing it costs nothing"
    assert status.head_verified is True


@pytest.mark.unit
def test_fetch_still_hydrates_and_verifies(pushed, monkeypatch):
    """The acceptance criterion is unchanged: a pull checks the digest.

    #123 requires "a manifest whose blob fails verification is ignored".
    That is a pull-time guarantee and #147 must not weaken it.
    """
    sync, user, _folder = pushed
    spy = _Evictor(monkeypatch)
    link = sync.state.get_link(user.id)

    result = sync.fetch_from(link.folder, link.sync_id, link.provider_id)

    assert spy.reads, "fetch must hash the blob even when it has to be downloaded"
    assert result.generation == 1


@pytest.mark.unit
def test_a_corrupt_local_blob_is_still_rejected_by_status(pushed, monkeypatch):
    """The cheap path must not become a blind path."""
    sync, user, folder = pushed
    link = sync.state.get_link(user.id)
    blob = next((folder / "WIMI" / link.sync_id).glob("*.wimi"))
    original = blob.read_bytes()
    blob.write_bytes(b"x" + original[1:])  # same length, different bytes

    status = sync.status(user.id)

    assert status.head_generation is None, "a corrupt sole generation is no head"
    assert status.rejected and "checksum" in status.rejected[0]["reason"]


@pytest.mark.unit
def test_resolve_head_prefers_an_unverified_new_generation_over_an_old_local_one(
    pushed, monkeypatch, tmp_path,
):
    """The reason a not-local blob must not count as a failure.

    Generation 2 has arrived and is still in the cloud; generation 1 is local
    and checkable. Reporting 1 as the head would tell the student their newest
    work is not there, when it is -- it just has not been downloaded.
    """
    sync, user, folder = pushed
    sync.push(user.id)  # generation 2, both local for now
    link = sync.state.get_link(user.id)

    import app.foldersync.transport as transport_mod
    real_residency = transport_mod.residency

    def only_gen2_is_cloud_only(path):
        res = real_residency(path)
        if "gen-0002" in str(path) and str(path).endswith(".wimi"):
            return Residency(res.path, res.exists, res.size_bytes,
                             dataless=True, determinate=True)
        return res

    monkeypatch.setattr(transport_mod, "residency", only_gen2_is_cloud_only)

    transport = FolderTransport(link.folder, link.sync_id, link.provider_id, 10.0)
    head, failures = transport.resolve_head(allow_hydration=False)

    assert head is not None and head.manifest.generation == 2, (
        "the newest generation is the head even when it has not been downloaded")
    assert head.verified is False
    assert failures == []


# ==================== the two paths #147 missed ====================

@pytest.mark.unit
def test_discover_does_not_download_every_profile_in_the_folder(pushed, monkeypatch):
    """#147's own comment said the fix had to cover both entry points.

    It covered `status` and not `discover`, and `discover` is the worse
    case: one download PER PROFILE in the folder, to answer "what is
    already in here" while the student is still deciding whether to use it.
    Found by the project-wimi-windows-2 session reading `cmd_link`, which
    calls `discover` before linking -- so linking a folder downloaded an
    archive from every profile in it.
    """
    sync, _user, folder = pushed
    spy = _Evictor(monkeypatch)

    found = sync.discover(folder, "box")

    assert spy.reads == [], (
        f"discover hashed a cloud-only blob and so downloaded it: {spy.reads}")
    assert len(found) == 1 and found[0]["head"]["generation"] == 1, (
        "it must still report what is there -- the manifest says all of it")


@pytest.mark.unit
def test_pushing_does_not_download_the_previous_generation(pushed, monkeypatch):
    """A push needs the parent's NUMBER, not the parent's bytes.

    Verifying the head to learn the parent generation meant every push
    downloaded the whole generation before it -- on a machine that may
    never have wanted that archive. Chaining onto an unverified parent is
    sound because generations are independent snapshots, not deltas.
    """
    sync, user, _folder = pushed
    spy = _Evictor(monkeypatch)

    result = sync.push(user.id)

    # push DOES hash the blob it just wrote, to catch a truncated write into
    # the folder, and that is correct. What it must not do is hash the
    # PREVIOUS generation -- a file this machine may never have wanted.
    previous = [r for r in spy.reads if "gen-0001" in r]
    assert previous == [], (
        f"push downloaded generation 1 just to read its number: {previous}")
    assert any("gen-0002" in r for r in spy.reads), (
        "push must still verify the copy it wrote")
    assert (result.generation, result.parent_generation) == (2, 1), (
        "the lineage must still be right")


@pytest.mark.unit
def test_a_corrupt_parent_blob_does_not_change_what_a_push_descends_from(pushed):
    """Lineage is where the content came from, not the health of a file (#148).

    This test used to assert the opposite -- that a corrupt generation 1 must
    not be chained onto -- because the parent was then read off the folder
    head, and a corrupt head was skipped. That head-reading is #149. The
    parent is now this device's base: it made generation 1, so its next
    generation descends from 1 whatever has since happened to the folder's
    copy. Nothing is built from a parent's bytes (generations are snapshots,
    not deltas), so a damaged parent blob costs this push nothing.

    What must still hold: the push does not read the parent to decide, and
    the new generation is the one a pull takes, verified.
    """
    sync, user, folder = pushed
    link = sync.state.get_link(user.id)
    blob = next((folder / "WIMI" / link.sync_id).glob("*.wimi"))
    original = blob.read_bytes()
    blob.write_bytes(b"x" + original[1:])

    result = sync.push(user.id)

    assert (result.generation, result.parent_generation) == (2, 1)
    fetched = sync.fetch(user.id)
    assert fetched.generation == 2, "a pull must take the new, intact generation"
