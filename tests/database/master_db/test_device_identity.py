"""This installation's identity, in the master database (#126).

The device id lives here — not in a user database — because master is
per-install and is **never packed into a ``.wimi``** archive
(``build_profile_archive`` writes the manifest, ``user.db`` and media,
and nothing else). An identifier kept here therefore cannot travel with
a profile, which is the whole requirement:
``ankiconnect_host = 'localhost'`` denotes a different machine on each
device, so the thing that names the machine must stay behind.

The profile-id mirror lives here too, for the opposite reason: it is an
*index*, re-derived from the user database whenever a profile is opened,
so the registry can answer "do I already have this profile?" without
opening every profile in turn.
"""
from __future__ import annotations

import pytest

from database.master_db import MasterDatabase


# ==================== device id ====================

class TestDeviceId:
    def test_minted_on_first_use_and_stable_after(self, master_db):
        first = master_db.get_device_id()
        assert len(first) == 36
        assert master_db.get_device_id() == first

    def test_survives_a_restart(self, temp_dir):
        first = MasterDatabase(temp_dir / "install")
        minted = first.get_device_id()
        first.close()

        second = MasterDatabase(temp_dir / "install")
        try:
            assert second.get_device_id() == minted
        finally:
            second.close()

    def test_two_installations_differ(self, temp_dir):
        a = MasterDatabase(temp_dir / "desktop")
        b = MasterDatabase(temp_dir / "laptop")
        try:
            assert a.get_device_id() != b.get_device_id()
        finally:
            a.close()
            b.close()

    def test_it_is_stored_as_an_app_setting(self, master_db):
        """Where it is stored is the load-bearing part, so it is asserted.

        ``app_settings`` lives in ``users.db``, and ``users.db`` is not
        part of a profile archive. Moving this into a user database would
        make every exported profile carry the sending machine's identity.
        """
        minted = master_db.get_device_id()
        setting = master_db.get_setting(MasterDatabase.DEVICE_ID_SETTING_KEY)
        assert setting is not None
        assert setting.setting_value == minted


class TestDeviceName:
    def test_defaults_to_something_human_readable(self, master_db):
        assert master_db.get_device_name()

    def test_rename_keeps_the_id(self, master_db):
        minted = master_db.get_device_id()
        assert master_db.set_device_name("Study Laptop") == "Study Laptop"
        assert master_db.get_device_name() == "Study Laptop"
        assert master_db.get_device_id() == minted

    def test_a_blank_name_is_refused(self, master_db):
        with pytest.raises(ValueError):
            master_db.set_device_name("   ")


# ==================== profile id mirror ====================

class TestProfileUuidMirror:
    def test_a_new_profile_has_no_mirror_until_it_is_opened(self, master_db):
        """The authority is the user database, which ``create_user`` does not touch.

        ``create_user`` writes a registry row; the per-user database file
        is created later. Minting an id here would claim an identity the
        profile has never heard of.
        """
        user = master_db.create_user(username="alice", display_name="Alice")
        assert master_db.get_user(user.id).profile_uuid is None

    def test_recording_is_an_overwrite(self, master_db):
        """A mirror that has drifted is corrected, never merged."""
        user = master_db.create_user(username="alice", display_name="Alice")
        master_db.record_profile_uuid(user.id, "aaaa-1")
        master_db.record_profile_uuid(user.id, "bbbb-2")
        assert master_db.get_user(user.id).profile_uuid == "bbbb-2"

    def test_a_blank_identifier_is_ignored(self, master_db):
        """An archive from before m021 has no id; that must not blank the mirror."""
        user = master_db.create_user(username="alice", display_name="Alice")
        master_db.record_profile_uuid(user.id, "aaaa-1")
        master_db.record_profile_uuid(user.id, "")
        assert master_db.get_user(user.id).profile_uuid == "aaaa-1"

    def test_lookup_finds_every_profile_carrying_the_id(self, master_db):
        """Two installs of one archive are a fork, not a corruption.

        ``install_profile_as_new()`` renames on collision by design, so
        both copies are legitimate. The column is indexed but not UNIQUE
        for exactly this reason; choosing between them is #124.
        """
        shared = "11111111-2222-3333-4444-555555555555"
        first = master_db.create_user(username="alice", display_name="Alice")
        second = master_db.create_user(username="alice_2", display_name="Alice")
        other = master_db.create_user(username="bob", display_name="Bob")
        master_db.record_profile_uuid(first.id, shared)
        master_db.record_profile_uuid(second.id, shared)
        master_db.record_profile_uuid(other.id, "9999-other")

        found = master_db.find_users_by_profile_uuid(shared)
        assert [u.id for u in found] == [first.id, second.id]

        excluded = master_db.find_users_by_profile_uuid(
            shared, exclude_user_id=first.id
        )
        assert [u.id for u in excluded] == [second.id]

    def test_lookup_of_an_unknown_or_blank_id_is_empty(self, master_db):
        assert master_db.find_users_by_profile_uuid("nobody") == []
        assert master_db.find_users_by_profile_uuid("") == []
