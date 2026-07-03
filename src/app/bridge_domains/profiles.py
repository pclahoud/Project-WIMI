"""WIMI Profile management bridge operations.

Master-DB-backed profile picker surface: list/create/rename/delete/restore
profiles, switch the active profile (opens its per-user database and emits
``userDatabaseLoaded``), and startup preferences (``profiles.last_used_id``,
``profiles.always_ask`` rows in ``app_settings``).

All slots work with ``self.user_db is None`` — the profile picker runs
before any user database is attached.
"""
import json
from datetime import datetime

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response
from database.exceptions import (
    UserAlreadyExistsError, UserNotFoundError, InvalidUsernameError,
    PrimaryAdminError, DeletionError,
)


class ProfileBridgeMixin:
    """Bridge mixin for profile management operations. Composed into DatabaseBridge."""

    # ==================== Helpers (not slots) ====================

    def _profile_dict(self, user) -> dict:
        """Serialize a User model into the profile payload shape."""
        return {
            'id': user.id,
            'username': user.username,
            'display_name': user.display_name,
            'email': user.email,
            'account_status': user.account_status,
            'is_primary_admin': user.is_primary_admin,
            'created_at': user.created_at,
            'last_active_at': user.last_active_at,
        }

    def _current_user_id(self):
        """Return the user_id of the currently open user DB, or None."""
        return getattr(self.user_db, 'user_id', None) if self.user_db is not None else None

    def _startup_prefs_dict(self) -> dict:
        """Read the profile startup preference rows from app_settings."""
        last = self.master_db.get_setting('profiles.last_used_id')
        ask = self.master_db.get_setting('profiles.always_ask')

        last_used_id = None
        if last and last.setting_value:
            try:
                last_used_id = int(last.setting_value)
            except (TypeError, ValueError):
                last_used_id = None

        return {
            'last_used_id': last_used_id,
            'always_ask': (ask.setting_value == 'true') if ask else False,
        }

    # ==================== Slots ====================

    @pyqtSlot(result=str)
    @instrumented_slot
    def listProfiles(self) -> str:
        """List active profiles plus soft-deleted profiles still within grace.

        Returns:
            JSON response: {profiles: [...], deleted: [...], current_user_id}
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            grace_days = self.master_db.DELETION_GRACE_PERIOD_DAYS

            profiles = [
                self._profile_dict(u)
                for u in self.master_db.get_all_users(account_status='active')
            ]

            deleted = []
            for user in self.master_db.get_all_users(include_deleted=True):
                if user.account_status != 'soft_deleted':
                    continue
                if user.soft_deleted_at is not None:
                    # soft_deleted_at is written by SQLite CURRENT_TIMESTAMP
                    # (UTC); datetime.now() is local. Clamp elapsed at 0 so
                    # a just-deleted profile never reports > grace_days.
                    elapsed_days = max(0, (datetime.now() - user.soft_deleted_at).days)
                    days_remaining = grace_days - elapsed_days
                else:
                    days_remaining = grace_days
                if days_remaining <= 0:
                    continue
                entry = self._profile_dict(user)
                entry['days_remaining'] = days_remaining
                entry['soft_deleted_at'] = user.soft_deleted_at
                deleted.append(entry)

            return serialize_response(True, data={
                'profiles': profiles,
                'deleted': deleted,
                'current_user_id': self._current_user_id(),
            })
        except Exception as e:
            self._log_error(f'listProfiles failed: {e}')
            return serialize_response(False, error=f'Failed to list profiles: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def createProfile(self, payload_json: str) -> str:
        """Create a new profile and its user database.

        Args:
            payload_json: JSON object {username, display_name?, email?}

        Returns:
            JSON response with the created profile
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            payload = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError) as e:
            return serialize_response(False, error=f'Invalid profile payload: {e}')

        username = (payload.get('username') or '').strip()
        display_name = (payload.get('display_name') or '').strip() or username
        email = (payload.get('email') or '').strip() or None

        try:
            user = self.master_db.create_user(
                username=username,
                display_name=display_name,
                email=email,
            )
            self.master_db.ensure_user_database(user.id)
            return serialize_response(True, data=self._profile_dict(user))
        except (UserAlreadyExistsError, InvalidUsernameError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'createProfile failed: {e}', {'username': username})
            return serialize_response(False, error=f'Failed to create profile: {e}')

    @pyqtSlot(int, str, result=str)
    @instrumented_slot
    def renameProfile(self, user_id: int, display_name: str) -> str:
        """Update a profile's display name (username is immutable — it is
        baked into the database filename and media directory).

        Args:
            user_id: Profile to rename
            display_name: New display name

        Returns:
            JSON response with the updated profile
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        display_name = (display_name or '').strip()
        if not display_name:
            return serialize_response(False, error='Display name cannot be empty')

        try:
            user = self.master_db.update_user(user_id, display_name=display_name)
            return serialize_response(True, data=self._profile_dict(user))
        except UserNotFoundError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'renameProfile failed: {e}', {'user_id': user_id})
            return serialize_response(False, error=f'Failed to rename profile: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def deleteProfile(self, user_id: int) -> str:
        """Soft-delete a profile and confirm deletion (starts the grace clock).

        Refuses to delete the currently open profile — switch first.

        Args:
            user_id: Profile to delete

        Returns:
            JSON response with {user_id, days_remaining}
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        if self._current_user_id() == user_id:
            return serialize_response(
                False,
                error='Cannot delete the currently open profile — switch profiles first',
            )

        try:
            self.master_db.soft_delete_user(user_id)
            self.master_db.confirm_user_deletion(user_id)
            return serialize_response(True, data={
                'user_id': user_id,
                'days_remaining': self.master_db.DELETION_GRACE_PERIOD_DAYS,
            })
        except (UserNotFoundError, PrimaryAdminError, DeletionError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'deleteProfile failed: {e}', {'user_id': user_id})
            return serialize_response(False, error=f'Failed to delete profile: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def restoreProfile(self, user_id: int) -> str:
        """Restore a soft-deleted profile within its grace period.

        Args:
            user_id: Profile to restore

        Returns:
            JSON response with the restored profile
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            user = self.master_db.restore_user(user_id)
            return serialize_response(True, data=self._profile_dict(user))
        except (UserNotFoundError, DeletionError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'restoreProfile failed: {e}', {'user_id': user_id})
            return serialize_response(False, error=f'Failed to restore profile: {e}')

    @pyqtSlot(int, result=str)
    @instrumented_slot
    def selectProfile(self, user_id: int) -> str:
        """Open a profile's user database and make it the active one.

        Production twin of ``loadTestUserDatabase`` (utility.py): opens the
        per-user ``UserDatabase`` (which auto-applies pending migrations),
        attaches it to the bridge, emits ``userDatabaseLoaded`` so
        ``MainWindow`` can rewire media/plugins, touches ``last_active_at``
        and records ``profiles.last_used_id`` for the next launch.

        Args:
            user_id: Profile to open

        Returns:
            JSON response with {user_id, username, display_name, db_path}
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            user = self.master_db.get_user(user_id=user_id)
            if user is None:
                return serialize_response(False, error=f'user_id={user_id} not found')
            if user.account_status != 'active':
                return serialize_response(
                    False, error='Profile is not active — restore it first'
                )

            # Make sure the per-user .db file exists and the schema is
            # initialised. Idempotent.
            self.master_db.ensure_user_database(user.id)

            from database import UserDatabase

            db_path = self.master_db.users_dir / user.database_filename
            new_db = UserDatabase(
                db_path=db_path,
                user_id=user.id,
                username=user.username,
            )
            self.user_db = new_db
            self.userDatabaseLoaded.emit(user.id)

            self.master_db.touch_user_last_active(user.id)
            self.master_db.set_setting(
                'profiles.last_used_id',
                str(user.id),
                description='Last profile opened via the profile picker',
            )

            return serialize_response(True, data={
                'user_id': user.id,
                'username': user.username,
                'display_name': user.display_name,
                'db_path': str(db_path),
            })
        except Exception as e:
            self._log_error(f'selectProfile failed: {e}', {'user_id': user_id})
            return serialize_response(False, error=f'Failed to select profile: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def getCurrentProfile(self) -> str:
        """Get the profile of the currently open user database (or None).

        Returns:
            JSON response with {profile: {...} | null}
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            user_id = self._current_user_id()
            if user_id is None:
                return serialize_response(True, data={'profile': None})

            user = self.master_db.get_user(user_id=user_id)
            profile = self._profile_dict(user) if user else None
            return serialize_response(True, data={'profile': profile})
        except Exception as e:
            self._log_error(f'getCurrentProfile failed: {e}')
            return serialize_response(False, error=f'Failed to get current profile: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def getProfileStartupPrefs(self) -> str:
        """Get profile startup preferences.

        Returns:
            JSON response with {last_used_id: int|null, always_ask: bool}
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            return serialize_response(True, data=self._startup_prefs_dict())
        except Exception as e:
            self._log_error(f'getProfileStartupPrefs failed: {e}')
            return serialize_response(False, error=f'Failed to get startup prefs: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def setProfileStartupPrefs(self, payload_json: str) -> str:
        """Set profile startup preferences.

        Args:
            payload_json: JSON object with optional keys
                ``always_ask`` (bool) and ``last_used_id`` (int|null)

        Returns:
            JSON response with the updated prefs
        """
        if self.master_db is None:
            return serialize_response(False, error='master DB not available')

        try:
            payload = json.loads(payload_json)
            if not isinstance(payload, dict):
                raise ValueError('payload must be a JSON object')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid startup prefs payload: {e}')

        try:
            if 'always_ask' in payload:
                self.master_db.set_setting(
                    'profiles.always_ask',
                    'true' if payload['always_ask'] else 'false',
                    description='Show the profile picker on every launch',
                )
            if 'last_used_id' in payload:
                value = payload['last_used_id']
                self.master_db.set_setting(
                    'profiles.last_used_id',
                    '' if value is None else str(int(value)),
                    description='Last profile opened via the profile picker',
                )
            return serialize_response(True, data=self._startup_prefs_dict())
        except (TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid startup prefs payload: {e}')
        except Exception as e:
            self._log_error(f'setProfileStartupPrefs failed: {e}')
            return serialize_response(False, error=f'Failed to set startup prefs: {e}')
