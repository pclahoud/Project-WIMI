"""
Tests for startup profile resolution (app.main.resolve_startup_profile).

Covers the 5-rule cascade:
1. Expired-profile purge housekeeping (invoked; failure never blocks launch)
2. 'profiles.always_ask' == 'true' -> None (picker)
3. Valid + active 'profiles.last_used_id' -> open it (and touch last_active)
4. Exactly one active user -> auto-open (zero-friction upgrade path for
   legacy single-profile installs, e.g. demo_user)
5. Otherwise (0 or 2+ active users) -> None (picker)

Pure-Python tests: real MasterDatabase / UserDatabase in a temp dir,
no QApplication required.
"""
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from app.main import resolve_startup_profile
from database import MasterDatabase, UserDatabase


# ==================== Fixtures ====================

@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test databases"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def master_db(temp_dir: Path) -> Generator[MasterDatabase, None, None]:
    """Create a fresh MasterDatabase instance without error logger"""
    db = MasterDatabase(data_dir=temp_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def resolve(master_db):
    """Call resolve_startup_profile and track returned UserDatabase
    instances so they are closed at teardown (open WAL handles keep
    the temp dir locked on Windows)."""
    opened = []

    def _resolve(db=None):
        result = resolve_startup_profile(db or master_db, UserDatabase)
        if result is not None:
            opened.append(result)
        return result

    yield _resolve

    for user_db in opened:
        try:
            user_db.close()
        except Exception:
            pass


def _make_user(master_db, username: str, display_name: str = None):
    """Create an active (non-admin) user."""
    return master_db.create_user(
        username=username,
        display_name=display_name or username.title(),
        email=f"{username}@test.com"
    )


def _backdate_last_active(master_db, user_id: int):
    """Push last_active_at into the past so a touch is observable."""
    with master_db.transaction():
        master_db.execute(
            "UPDATE users SET last_active_at = '2000-01-01 00:00:00' WHERE id = ?",
            (user_id,)
        )


# ==================== Rule 2: always_ask ====================

@pytest.mark.unit
@pytest.mark.database
class TestAlwaysAsk:

    def test_always_ask_wins_over_last_used_and_single_active(self, master_db, resolve):
        user = _make_user(master_db, "alpha")
        master_db.set_setting('profiles.last_used_id', str(user.id))
        master_db.set_setting('profiles.always_ask', 'true')

        assert resolve() is None

    def test_always_ask_false_does_not_block_auto_open(self, master_db, resolve):
        user = _make_user(master_db, "alpha")
        master_db.set_setting('profiles.always_ask', 'false')

        result = resolve()
        assert result is not None
        assert result.user_id == user.id


# ==================== Rule 3: last_used_id ====================

@pytest.mark.unit
@pytest.mark.database
class TestLastUsed:

    def test_valid_last_used_opens_it(self, master_db, resolve):
        _make_user(master_db, "alpha")
        second = _make_user(master_db, "bravo")
        master_db.set_setting('profiles.last_used_id', str(second.id))

        result = resolve()
        assert result is not None
        assert result.user_id == second.id
        assert result.username == "bravo"

    def test_valid_last_used_touches_last_active(self, master_db, resolve):
        user = _make_user(master_db, "alpha")
        _make_user(master_db, "bravo")
        master_db.set_setting('profiles.last_used_id', str(user.id))
        _backdate_last_active(master_db, user.id)
        before = master_db.get_user(user.id).last_active_at

        result = resolve()

        assert result is not None
        after = master_db.get_user(user.id).last_active_at
        assert after > before

    def test_stale_last_used_falls_through_to_picker(self, master_db, resolve):
        _make_user(master_db, "alpha")
        _make_user(master_db, "bravo")
        master_db.set_setting('profiles.last_used_id', '9999')

        assert resolve() is None

    def test_stale_last_used_falls_through_to_single_active(self, master_db, resolve):
        user = _make_user(master_db, "alpha")
        master_db.set_setting('profiles.last_used_id', '9999')

        result = resolve()
        assert result is not None
        assert result.user_id == user.id

    def test_soft_deleted_last_used_falls_through(self, master_db, resolve):
        doomed = _make_user(master_db, "alpha")
        survivor = _make_user(master_db, "bravo")
        master_db.set_setting('profiles.last_used_id', str(doomed.id))
        master_db.soft_delete_user(doomed.id)

        # Rule 3 skips the deleted user; rule 4 opens the sole remaining
        # active profile.
        result = resolve()
        assert result is not None
        assert result.user_id == survivor.id

    def test_soft_deleted_last_used_with_multiple_actives_shows_picker(
        self, master_db, resolve
    ):
        doomed = _make_user(master_db, "alpha")
        _make_user(master_db, "bravo")
        _make_user(master_db, "charlie")
        master_db.set_setting('profiles.last_used_id', str(doomed.id))
        master_db.soft_delete_user(doomed.id)

        assert resolve() is None

    def test_non_integer_last_used_is_ignored(self, master_db, resolve):
        _make_user(master_db, "alpha")
        _make_user(master_db, "bravo")
        master_db.set_setting('profiles.last_used_id', 'not-a-number')

        # Must not raise; falls through to rule 5 (2 actives -> picker)
        assert resolve() is None


# ==================== Rules 4 & 5: active-user count ====================

@pytest.mark.unit
@pytest.mark.database
class TestActiveUserCount:

    def test_single_active_user_auto_opens(self, master_db, resolve):
        """Zero-friction upgrade path for legacy single-profile installs."""
        user = _make_user(master_db, "demo_user", display_name="Demo User")

        result = resolve()
        assert result is not None
        assert result.user_id == user.id
        assert result.username == "demo_user"

    def test_single_active_auto_open_touches_last_active(self, master_db, resolve):
        user = _make_user(master_db, "alpha")
        _backdate_last_active(master_db, user.id)
        before = master_db.get_user(user.id).last_active_at

        result = resolve()

        assert result is not None
        after = master_db.get_user(user.id).last_active_at
        assert after > before

    def test_zero_users_returns_none(self, master_db, resolve):
        assert resolve() is None

    def test_multiple_active_users_returns_none(self, master_db, resolve):
        _make_user(master_db, "alpha")
        _make_user(master_db, "bravo")

        assert resolve() is None


# ==================== Rule 1: expired-profile purge ====================

@pytest.mark.unit
@pytest.mark.database
class TestExpiredPurgeHousekeeping:

    def test_expired_purge_invoked(self, master_db, resolve, monkeypatch):
        calls = []
        original = master_db.permanently_delete_expired_users

        def recording():
            calls.append(True)
            return original()

        monkeypatch.setattr(
            master_db, 'permanently_delete_expired_users', recording
        )

        resolve()
        assert len(calls) == 1

    def test_expired_purge_failure_does_not_block_launch(
        self, master_db, resolve, monkeypatch
    ):
        user = _make_user(master_db, "alpha")

        def boom():
            raise RuntimeError("simulated purge failure")

        monkeypatch.setattr(
            master_db, 'permanently_delete_expired_users', boom
        )

        # Single active user should still auto-open despite the failure.
        result = resolve()
        assert result is not None
        assert result.user_id == user.id
