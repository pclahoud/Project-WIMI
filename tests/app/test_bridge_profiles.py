"""
Tests for the profile management bridge mixin (bridge_domains/profiles.py).

Covers all nine ProfileBridgeMixin slots: response shapes, error mapping,
refusals, master_db=None behavior, and selectProfile side effects
(user DB attach, userDatabaseLoaded emission, last_active_at touch,
profiles.last_used_id persistence).
"""
import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from database.master_db import MasterDatabase
from app.bridge import DatabaseBridge


# ==================== Fixtures ====================

@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for the master database"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    """Create a MasterDatabase instance for testing"""
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(master_db: MasterDatabase) -> Generator[DatabaseBridge, None, None]:
    """Bridge with a master DB but no user DB (profile-picker state)"""
    b = DatabaseBridge(master_db=master_db, user_db=None)
    yield b
    # selectProfile may have attached a user DB inside the temp dir —
    # close it so TemporaryDirectory cleanup doesn't hit Windows file locks.
    if b.user_db is not None:
        b.user_db.close()


@pytest.fixture
def bridge_with_users(bridge: DatabaseBridge, master_db: MasterDatabase):
    """Bridge plus a bootstrapped admin and two regular profiles"""
    admin = master_db.bootstrap_first_user(
        username="admin",
        display_name="Test Admin",
        email="admin@test.com",
    )
    alpha = master_db.create_user(
        username="alpha",
        display_name="Profile Alpha",
        email="alpha@test.com",
    )
    beta = master_db.create_user(
        username="beta",
        display_name="Profile Beta",
    )
    return bridge, admin, alpha, beta


@pytest.fixture
def bridge_no_master() -> DatabaseBridge:
    """Bridge with no databases at all"""
    return DatabaseBridge(master_db=None, user_db=None)


# ==================== Helpers ====================

def parse_response(json_str: str) -> dict:
    return json.loads(json_str)


def assert_success(response: str) -> dict:
    result = parse_response(response)
    assert result['success'] is True, f"Expected success but got error: {result.get('error')}"
    return result.get('data')


def assert_error(response: str, expected_message: str = None) -> str:
    result = parse_response(response)
    assert result['success'] is False, "Expected error but got success"
    if expected_message:
        assert expected_message in result.get('error', ''), \
            f"Expected '{expected_message}' in error but got: {result.get('error')}"
    return result.get('error')


# ==================== master_db=None guard ====================

class TestNoMasterDb:
    """Every profile slot must fail cleanly when master_db is None"""

    @pytest.mark.parametrize("slot_name,args", [
        ("listProfiles", ()),
        ("createProfile", ('{"username": "someone"}',)),
        ("renameProfile", (1, "New Name")),
        ("deleteProfile", (1,)),
        ("restoreProfile", (1,)),
        ("selectProfile", (1,)),
        ("getCurrentProfile", ()),
        ("getProfileStartupPrefs", ()),
        ("setProfileStartupPrefs", ('{"always_ask": true}',)),
    ])
    def test_slot_errors_without_master_db(self, bridge_no_master, slot_name, args):
        response = getattr(bridge_no_master, slot_name)(*args)
        assert_error(response, "master DB not available")


# ==================== listProfiles ====================

class TestListProfiles:

    def test_lists_active_profiles(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.listProfiles())

        assert len(data['profiles']) == 3
        usernames = {p['username'] for p in data['profiles']}
        assert usernames == {"admin", "alpha", "beta"}
        assert data['deleted'] == []
        assert data['current_user_id'] is None

    def test_profile_shape(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.listProfiles())
        profile = next(p for p in data['profiles'] if p['username'] == 'alpha')

        assert profile['id'] == alpha.id
        assert profile['display_name'] == "Profile Alpha"
        assert profile['email'] == "alpha@test.com"
        assert profile['account_status'] == "active"
        assert profile['is_primary_admin'] is False
        assert 'created_at' in profile
        assert 'last_active_at' in profile

    def test_deleted_profile_within_grace_listed(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users
        master_db.soft_delete_user(alpha.id)

        data = assert_success(bridge.listProfiles())

        assert len(data['profiles']) == 2
        assert len(data['deleted']) == 1
        deleted = data['deleted'][0]
        assert deleted['id'] == alpha.id
        assert 0 < deleted['days_remaining'] <= MasterDatabase.DELETION_GRACE_PERIOD_DAYS
        assert deleted['soft_deleted_at'] is not None

    def test_expired_deleted_profile_not_listed(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users
        master_db.soft_delete_user(alpha.id)
        # Backdate the deletion past the grace period
        with master_db.transaction():
            master_db.execute(
                "UPDATE users SET soft_deleted_at = '2020-01-01 00:00:00' WHERE id = ?",
                (alpha.id,),
            )

        data = assert_success(bridge.listProfiles())

        assert data['deleted'] == []

    def test_current_user_id_after_select(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users
        assert_success(bridge.selectProfile(alpha.id))

        data = assert_success(bridge.listProfiles())

        assert data['current_user_id'] == alpha.id


# ==================== createProfile ====================

class TestCreateProfile:

    def test_create_valid_profile(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.createProfile(json.dumps({
            "username": "gamma",
            "display_name": "Profile Gamma",
            "email": "gamma@test.com",
        })))

        assert data['id'] > 0
        assert data['username'] == "gamma"
        assert data['display_name'] == "Profile Gamma"
        assert data['email'] == "gamma@test.com"

        # The per-user DB file must exist (ensure_user_database ran)
        user = master_db.get_user(user_id=data['id'])
        assert (master_db.users_dir / user.database_filename).exists()

    def test_display_name_defaults_to_username(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.createProfile(json.dumps({"username": "gamma"})))

        assert data['display_name'] == "gamma"
        assert data['email'] is None

    def test_duplicate_username_clean_error(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.createProfile(json.dumps({"username": "alpha"}))

        assert_error(response, "already exists")

    def test_invalid_username_clean_error(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.createProfile(json.dumps({"username": "ab"}))

        assert_error(response, "at least 3 characters")

    def test_invalid_username_chars_clean_error(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.createProfile(json.dumps({"username": "bad name!"}))

        assert_error(response)

    def test_malformed_json_clean_error(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.createProfile("{not json")

        assert_error(response, "Invalid profile payload")


# ==================== renameProfile ====================

class TestRenameProfile:

    def test_rename_changes_display_name_only(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.renameProfile(alpha.id, "Renamed Alpha"))

        assert data['display_name'] == "Renamed Alpha"
        assert data['username'] == "alpha"  # unchanged
        assert master_db.get_user(user_id=alpha.id).display_name == "Renamed Alpha"

    def test_rename_unknown_user_fails(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.renameProfile(99999, "Ghost")

        assert_error(response, "not found")

    def test_rename_empty_name_fails(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.renameProfile(alpha.id, "   ")

        assert_error(response, "empty")


# ==================== deleteProfile ====================

class TestDeleteProfile:

    def test_delete_soft_deletes_and_confirms(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.deleteProfile(alpha.id))

        assert data['user_id'] == alpha.id
        assert data['days_remaining'] == MasterDatabase.DELETION_GRACE_PERIOD_DAYS

        user = master_db.get_user(user_id=alpha.id)
        assert user.account_status == 'soft_deleted'
        assert user.deletion_confirmed is True

    def test_delete_refuses_currently_open_profile(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users
        assert_success(bridge.selectProfile(alpha.id))

        response = bridge.deleteProfile(alpha.id)

        assert_error(response, "switch")
        # Still active — nothing was deleted
        assert master_db.get_user(user_id=alpha.id).account_status == 'active'

    def test_delete_other_profile_while_one_open(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users
        assert_success(bridge.selectProfile(alpha.id))

        assert_success(bridge.deleteProfile(beta.id))

        assert master_db.get_user(user_id=beta.id).account_status == 'soft_deleted'

    def test_delete_primary_admin_fails(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.deleteProfile(admin.id)

        assert_error(response, "primary admin")

    def test_delete_unknown_user_fails(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.deleteProfile(99999)

        assert_error(response, "not found")


# ==================== restoreProfile ====================

class TestRestoreProfile:

    def test_restore_deleted_profile(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users
        assert_success(bridge.deleteProfile(alpha.id))

        data = assert_success(bridge.restoreProfile(alpha.id))

        assert data['id'] == alpha.id
        assert data['account_status'] == 'active'
        assert master_db.get_user(user_id=alpha.id).account_status == 'active'

    def test_restore_active_profile_fails(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.restoreProfile(alpha.id)

        assert_error(response, "not deleted")

    def test_restore_unknown_user_fails(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.restoreProfile(99999)

        assert_error(response, "not found")


# ==================== selectProfile ====================

class TestSelectProfile:

    def test_select_attaches_user_db(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.selectProfile(alpha.id))

        assert data['user_id'] == alpha.id
        assert data['username'] == "alpha"
        assert data['display_name'] == "Profile Alpha"
        assert data['db_path']
        assert bridge.user_db is not None
        assert bridge.user_db.user_id == alpha.id

    def test_select_emits_user_database_loaded(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users
        received = []
        bridge.userDatabaseLoaded.connect(received.append)

        assert_success(bridge.selectProfile(alpha.id))

        assert received == [alpha.id]

    def test_select_touches_last_active(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users
        # Plant a sentinel so we can detect the touch regardless of any
        # schema-level default on last_active_at.
        with master_db.transaction():
            master_db.execute(
                "UPDATE users SET last_active_at = '2020-01-01 00:00:00' WHERE id = ?",
                (alpha.id,),
            )

        assert_success(bridge.selectProfile(alpha.id))

        row = master_db.fetchone(
            "SELECT last_active_at FROM users WHERE id = ?", (alpha.id,)
        )
        assert row['last_active_at'] is not None
        assert row['last_active_at'] != '2020-01-01 00:00:00'

    def test_select_records_last_used_id(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users

        assert_success(bridge.selectProfile(alpha.id))

        setting = master_db.get_setting('profiles.last_used_id')
        assert setting is not None
        assert setting.setting_value == str(alpha.id)

    def test_select_creates_user_db_file(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.selectProfile(alpha.id))

        assert Path(data['db_path']).exists()

    def test_select_unknown_user_fails(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        response = bridge.selectProfile(99999)

        assert_error(response, "not found")
        assert bridge.user_db is None

    def test_select_deleted_profile_fails(self, bridge_with_users, master_db):
        bridge, admin, alpha, beta = bridge_with_users
        master_db.soft_delete_user(alpha.id)

        response = bridge.selectProfile(alpha.id)

        assert_error(response, "not active")
        assert bridge.user_db is None


# ==================== getCurrentProfile ====================

class TestGetCurrentProfile:

    def test_none_before_select(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users

        data = assert_success(bridge.getCurrentProfile())

        assert data['profile'] is None

    def test_returns_profile_after_select(self, bridge_with_users):
        bridge, admin, alpha, beta = bridge_with_users
        assert_success(bridge.selectProfile(alpha.id))

        data = assert_success(bridge.getCurrentProfile())

        assert data['profile'] is not None
        assert data['profile']['id'] == alpha.id
        assert data['profile']['username'] == "alpha"


# ==================== Startup prefs ====================

class TestProfileStartupPrefs:

    def test_defaults(self, bridge):
        data = assert_success(bridge.getProfileStartupPrefs())

        assert data['last_used_id'] is None
        assert data['always_ask'] is False

    def test_set_always_ask(self, bridge, master_db):
        data = assert_success(bridge.setProfileStartupPrefs(
            json.dumps({"always_ask": True})
        ))
        assert data['always_ask'] is True

        # Persisted in app_settings
        assert master_db.get_setting('profiles.always_ask').setting_value == 'true'

        data = assert_success(bridge.setProfileStartupPrefs(
            json.dumps({"always_ask": False})
        ))
        assert data['always_ask'] is False

    def test_set_last_used_id(self, bridge):
        data = assert_success(bridge.setProfileStartupPrefs(
            json.dumps({"last_used_id": 3})
        ))
        assert data['last_used_id'] == 3

        readback = assert_success(bridge.getProfileStartupPrefs())
        assert readback['last_used_id'] == 3

    def test_clear_last_used_id(self, bridge):
        assert_success(bridge.setProfileStartupPrefs(json.dumps({"last_used_id": 7})))

        data = assert_success(bridge.setProfileStartupPrefs(
            json.dumps({"last_used_id": None})
        ))

        assert data['last_used_id'] is None

    def test_malformed_json_fails(self, bridge):
        response = bridge.setProfileStartupPrefs("{not json")

        assert_error(response, "Invalid startup prefs payload")

    def test_non_object_payload_fails(self, bridge):
        response = bridge.setProfileStartupPrefs("[1, 2]")

        assert_error(response, "Invalid startup prefs payload")

    def test_non_numeric_last_used_id_fails(self, bridge):
        response = bridge.setProfileStartupPrefs(
            json.dumps({"last_used_id": "abc"})
        )

        assert_error(response, "Invalid startup prefs payload")
