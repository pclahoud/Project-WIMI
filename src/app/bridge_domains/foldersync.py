"""WIMI folder-sync bridge operations (#123).

A student picks a folder inside whatever cloud client they already run, and
WIMI writes sealed, generation-named archives into it. No provider APIs, no
OAuth, no credentials -- see ``app.foldersync``.

Two kinds of slot, and the split is not cosmetic
------------------------------------------------

**Cheap slots answer immediately.** ``getFolderSyncLink`` and
``getFolderSyncProviders`` read a small JSON file and a static table. Nothing
they touch can block.

**Anything that touches the sync folder is a job.** ``startFolderSyncJob``
returns a job id and the page polls ``pollFolderSyncJob``. This is not
ceremony: #123 requires folder enumeration and evicted reads to run off the Qt
main thread, and on Box that is the *normal* path rather than an edge case --
Box streams by default and evicts a file after 30 days without modification,
which our write-once generation files trigger by construction. A slot that
read the folder inline would freeze the window for up to the hydration
timeout, on every status refresh.

The database work stays on this thread regardless. ``base_db.py`` records that
nothing in the application writes from a second thread; ``SyncJobs`` runs only
the folder phase on a worker, and runs the phases either side of it on
whichever thread called ``submit``/``poll`` -- which, from here, is Qt's main
thread. See ``app.foldersync.service``'s *Threading* section.

What this deliberately does not have
------------------------------------

**No ``setCloudSyncEnabled``.** The owner settled on 2026-09-21 that the
*Enable Cloud Sync* checkbox reflects and toggles **the link**, and that no
boolean is stored for it. There were already two ``cloud_sync_enabled``
columns -- one on master's ``users``, one on ``user_preferences`` -- and the
one the checkbox was bound to is user-level, so it travelled inside a
``.wimi``: a profile exported with sync on arrived on the next machine
claiming to be syncing with no folder linked anywhere. Storing it again, even
device-locally, would be a second answer to a question ``state.json`` already
answers. So ``getFolderSyncLink().linked`` **is** the checkbox state, and
linking or unlinking is what ticking it does.
"""
import json
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot

from ..bridge_helpers import serialize_response

#: Job kinds the page may start. An unknown kind is refused by name rather
#: than silently ignored -- #138's accept-and-drop is a recent enough memory.
JOB_KINDS = ('status', 'push', 'fetch', 'link', 'discover',
             'fork_report', 'resolve', 'install')


class FolderSyncBridgeMixin:
    """Bridge mixin for folder-based profile sync. Composed into DatabaseBridge."""

    # ==================== Helpers (not slots) ====================

    def _folder_sync(self):
        """The sync service for this installation, built on first use.

        Held as a plain attribute so a test can inject a fake, the way the
        browser pane controller is. Returns ``None`` when there is no master
        database, which is a normal state: the profile picker runs before one
        is attached.
        """
        if getattr(self, '_folder_sync_jobs', None) is not None:
            return self._folder_sync_jobs
        if self.master_db is None:
            return None
        from app.foldersync import ProfileFolderSync, SyncJobs
        self._folder_sync_jobs = SyncJobs(ProfileFolderSync(self.master_db))
        return self._folder_sync_jobs

    def _safety_dir(self):
        """Where a fork resolution puts its pre-flight export.

        Chosen here rather than by the page: it must be durable and
        **outside the sync folder**, because writing a backup into the
        folder whose conflict we are resolving is how the backup becomes
        part of the conflict. A page-supplied path could be either.
        """
        from pathlib import Path
        base = Path(getattr(self.master_db, 'data_dir', '.'))
        directory = base / 'foldersync' / 'safety'
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _active_profile_id(self) -> Optional[int]:
        """Which profile the page is asking about.

        Sync is per profile, and the bridge only ever has one open. Resolved
        at call time rather than captured, because the database is swapped on
        profile switch.
        """
        return self.user_db.user_id if self.user_db is not None else None

    @contextmanager
    def _released_profile(self, user_id: int):
        """Close the open profile for the duration, then reopen it (#148).

        The owner's decision for ``keep_remote``: rather than refusing to
        replace the profile the student is looking at, close it, replace it,
        and open it again. Reopened through ``selectProfile`` -- the ordinary
        profile-switch path -- so ``MainWindow`` rewires media, plugins and
        the scheme handler exactly as it does for any switch, rather than
        through a second mechanism that would drift from it.

        Reopened on **every** exit. On failure the file on disk is the
        untouched original (``replace_profile`` rolls back), and leaving the
        student with no profile open because a replace failed would turn a
        refusal into an outage.
        """
        db = self.user_db
        if db is None or int(getattr(db, 'user_id', -1)) != int(user_id):
            yield
            return
        db.close()
        self.user_db = None
        try:
            yield
        finally:
            reopened = json.loads(self.selectProfile(int(user_id)))
            if not reopened.get('success'):
                self._log_error(
                    f"could not reopen profile {user_id} after a fork "
                    f"resolution: {reopened.get('error')}")

    def teardownFolderSync(self) -> None:
        """Discard any staged-but-uncollected work. Called from ``closeEvent``.

        A push whose job was never polled -- the window closed mid-sync --
        otherwise leaves a sealed copy of the profile in staging for good.
        Not a slot: the shutdown path is Qt's, not the page's.
        """
        jobs = getattr(self, '_folder_sync_jobs', None)
        if jobs is not None:
            try:
                jobs.shutdown()
            except Exception as e:
                self._log_error(f'teardownFolderSync failed: {e}')
            self._folder_sync_jobs = None

    @staticmethod
    def _status_payload(status) -> Dict[str, Any]:
        """A ``SyncStatus`` as the page sees it.

        Spelled out rather than ``asdict``-ed so the wire contract is a
        decision. Note what is **not** here: there is no ``synced`` flag and
        no ``up_to_date``. You cannot force a sync or know when one finished,
        so "nothing new" and "the other device has not uploaded yet" are
        indistinguishable from the filesystem -- every field below is an
        observation with a timestamp, and the panel may not imply more.
        """
        return {
            'linked': status.linked,
            'folder': status.folder,
            'provider_id': status.provider_id,
            'provider_name': status.provider_name,
            'sync_id': status.sync_id,
            'device_name': status.device_name,
            'last_seen_generation': status.last_seen_generation,
            'last_seen_at': status.last_seen_at,
            'last_pushed_generation': status.last_pushed_generation,
            'last_pushed_at': status.last_pushed_at,
            'head_generation': status.head_generation,
            'head_device': status.head_device,
            'head_created_at': status.head_created_at,
            # False when the newest copy is still in the cloud, so its
            # checksum has not been run. Looking is free; checking costs
            # a download (#147). The panel must say which it did.
            'head_verified': status.head_verified,
            # Where this device's copy stands (#148). 'superseded' is the
            # losing side of a choice made on another device; the panel and
            # the startup notice must both say so.
            'base_generation': status.base_generation,
            'base_relation': status.base_relation,
            'relation_detail': status.relation_detail,
            # Chosen here, not yet sent. Standing state, not a toast.
            'pending': status.pending,
            'pending_state': status.pending_state,
            # Has this computer changed since it last synced (#151)? Only
            # what was checked -- see SyncStatus.local_changes.
            'local_changes': status.local_changes,
            'forks': status.forks,
            'rejected': status.rejected,
            'conflict_copies': status.conflict_copies,
            'problems': status.problems,
            'pin_hint': status.pin_hint,
        }

    @staticmethod
    def _fetch_payload(result) -> Dict[str, Any]:
        """A staged fetch. ``blocked`` is ``preflight_schema``'s verdict, surfaced."""
        return {
            'archive_path': result.archive_path,
            'generation': result.generation,
            'schema_verdict': result.schema_verdict,
            'schema_reason': result.schema_reason,
            'blocked': result.blocked,
            'summary': result.summary,
            'skipped': [
                {'generation': f.generation, 'manifest': f.manifest_name,
                 'reason': f.reason}
                for f in result.skipped
            ],
        }

    @staticmethod
    def _fork_payload(report) -> Optional[Dict[str, Any]]:
        """A fork report, or ``None`` when there is no fork.

        ``None`` is the ordinary case and must stay distinguishable from a
        report that found a fork but could not compare its sides -- the
        latter arrives with ``compared: false`` and a note, because an empty
        "only on this side" list would otherwise read as "the copies agree".
        """
        return report.to_dict() if report is not None else None

    @staticmethod
    def _resolution_payload(result) -> Dict[str, Any]:
        return result.to_dict()

    def _job_payload(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Translate a job report into the page's shape."""
        state = report.get('state')
        if state != 'done':
            return report
        kind, value = report.get('kind'), report.get('result')
        if kind == 'status':
            return {'state': state, 'kind': kind,
                    'result': self._status_payload(value)}
        if kind == 'fetch':
            return {'state': state, 'kind': kind,
                    'result': self._fetch_payload(value)}
        if kind == 'push':
            return {'state': state, 'kind': kind, 'result': {
                'generation': value.generation,
                'parent_generation': value.parent_generation,
                'blob_name': value.blob_name,
                'manifest_name': value.manifest_name,
                'bytes': value.bytes,
            }}
        if kind == 'fork_report':
            return {'state': state, 'kind': kind,
                    'result': self._fork_payload(value)}
        if kind == 'resolve':
            return {'state': state, 'kind': kind,
                    'result': self._resolution_payload(value)}
        if kind == 'install':
            installed = value['installed']
            return {'state': state, 'kind': kind, 'result': {
                'user_id': installed.get('user_id'),
                'username': installed.get('username'),
                'profile_uuid': installed.get('profile_uuid'),
                'generation': value['fetched'].generation,
                'linked': value['linked'],
                'link_error': value['link_error'],
                'folder': value['folder'],
            }}
        if kind == 'link':
            return {'state': state, 'kind': kind, 'result': {
                'linked': True,
                'folder': value.folder,
                'provider_id': value.provider_id,
                'sync_id': value.sync_id,
            }}
        return {'state': state, 'kind': kind, 'result': value}

    # ==================== Cheap slots ====================

    @pyqtSlot(result=str)
    @instrumented_slot
    def getFolderSyncProviders(self) -> str:
        """The cloud clients WIMI knows quirks for, as data.

        Adding a provider is a row in ``foldersync/providers.py``, not a code
        path, so this is simply that table. The page needs
        ``pin_setting_label`` in particular: telling a student to turn on
        "Always keep on device" is the single most useful thing the panel
        says, and each client calls it something different.
        """
        try:
            import sys as _sys
            from app.foldersync import PROVIDERS
            return serialize_response(True, data=[
                {
                    'id': p.id,
                    'name': p.display_name,
                    'pin_setting_label': p.pin_setting_label,
                    'streaming_by_default': p.streaming_by_default,
                    'scheduled_eviction': p.scheduled_eviction,
                    # Only the folders for THIS platform, and only as a hint
                    # for the picker. Never assume one exists -- Box's real
                    # macOS home is ~/Library/CloudStorage/Box-Box, not the
                    # ~/Box the install guide shows.
                    'default_folders': list(p.default_folders.get(_sys.platform, ())),
                    'caveats': list(p.caveats),
                }
                for p in PROVIDERS.values()
            ])
        except Exception as e:
            self._log_error(f'getFolderSyncProviders failed: {e}')
            return serialize_response(False, error=f'Failed to read providers: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def getFolderSyncLink(self) -> str:
        """Whether this profile is linked to a folder on **this** machine.

        This is the *Enable Cloud Sync* checkbox's state. No boolean is
        stored for it -- see the module docstring. Reads one small JSON file
        on local disk, so it never blocks and the page may call it freely.
        """
        jobs = self._folder_sync()
        if jobs is None:
            return serialize_response(False, error='folder sync not available')
        user_id = self._active_profile_id()
        if user_id is None:
            return serialize_response(False, error='No user database loaded')
        try:
            link = jobs.sync.state.get_link(user_id)
            if link is None:
                return serialize_response(True, data={'linked': False})
            from app.foldersync import get_provider
            provider = get_provider(link.provider_id)
            return serialize_response(True, data={
                'linked': True,
                'folder': link.folder,
                'provider_id': link.provider_id,
                'provider_name': provider.display_name,
                'pin_hint': provider.pin_setting_label,
                'sync_id': link.sync_id,
                # This machine's id, so a page can tell which side of a fork
                # is its own. By ID and never by name: hostnames are not
                # unique, and picking by name is the same class of bug that
                # let two devices write one file.
                'device_id': jobs.sync._device_identity().device_id,
                'last_seen_generation': link.last_seen_generation,
                'last_seen_at': link.last_seen_at,
                'last_pushed_generation': link.last_pushed_generation,
                'last_pushed_at': link.last_pushed_at,
                # Local and cheap, so the panel can show "chosen, not sent"
                # before any folder look has come back.
                'pending': link.pending,
            })
        except Exception as e:
            self._log_error(f'getFolderSyncLink failed: {e}')
            return serialize_response(False, error=f'Failed to read sync link: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def unlinkFolderSync(self) -> str:
        """Stop syncing this profile on this machine.

        **Nothing in the folder is touched.** The archives are the student's,
        and an unlink that deleted them would make unticking a checkbox a
        destructive act.
        """
        jobs = self._folder_sync()
        if jobs is None:
            return serialize_response(False, error='folder sync not available')
        user_id = self._active_profile_id()
        if user_id is None:
            return serialize_response(False, error='No user database loaded')
        try:
            jobs.sync.unlink(user_id)
            return serialize_response(True, data={'linked': False})
        except Exception as e:
            self._log_error(f'unlinkFolderSync failed: {e}')
            return serialize_response(False, error=f'Failed to unlink: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def pickFolderSyncFolder(self) -> str:
        """Open a native directory picker for the cloud-synced folder.

        Split from ``startFolderSyncJob`` on the session-import pattern, so a
        headless regression test can drive the work with a plain path.
        """
        try:
            from PyQt6.QtWidgets import QFileDialog
            folder = QFileDialog.getExistingDirectory(
                None,
                "Choose a folder your cloud client keeps synced",
                "",
                QFileDialog.Option.ShowDirsOnly,
            )
            if not folder:
                return serialize_response(True, data=None)
            return serialize_response(True, data={'folder': folder})
        except Exception as e:
            self._log_error(f'pickFolderSyncFolder failed: {e}')
            return serialize_response(False, error=f'Failed to open folder dialog: {e}')

    # ==================== Job slots ====================

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def startFolderSyncJob(self, params_json: str) -> str:
        """Begin a folder operation on a worker thread.

        Args:
            params_json: JSON object with ``kind`` (one of ``JOB_KINDS``).
                ``link``, ``discover`` and ``install`` take ``folder`` and
                ``provider_id``; ``install`` also ``sync_id``. ``resolve``
                takes ``choice`` and ``blob_name``; ``fork_report`` an
                optional ``parent_generation``. ``discover`` and ``install``
                are the two that need no profile open.

        Returns:
            JSON response with ``{job_id}``. Poll ``pollFolderSyncJob``.

        Phase 1 runs inline, so a failure to read the database surfaces here
        with context rather than arriving later as a bare job error.
        """
        jobs = self._folder_sync()
        if jobs is None:
            return serialize_response(False, error='folder sync not available')

        try:
            params = json.loads(params_json) if params_json else {}
            if not isinstance(params, dict):
                raise ValueError('params must be a JSON object')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid sync job params: {e}')

        kind = str(params.get('kind') or '')
        if kind not in JOB_KINDS:
            return serialize_response(
                False,
                error=f"Unknown sync job kind {kind!r}; expected one of "
                      f"{', '.join(JOB_KINDS)}",
            )

        provider_id = str(params.get('provider_id') or 'generic')
        folder = str(params.get('folder') or '')

        if kind == 'discover':
            if not folder:
                return serialize_response(False, error='discover needs a folder')
            try:
                return serialize_response(
                    True, data={'job_id': jobs.submit_discover(folder, provider_id)})
            except Exception as e:
                self._log_error(f'startFolderSyncJob(discover) failed: {e}')
                return serialize_response(False, error=f'Failed to start discover: {e}')

        if kind == 'install':
            # Like discover, needs no profile open: this is how a computer
            # with no copy of the profile gets one (#151), from the picker.
            sync_id = str(params.get('sync_id') or '')
            if not folder or not sync_id:
                return serialize_response(
                    False, error='install needs a folder and the sync_id of the profile in it')
            try:
                return serialize_response(True, data={
                    'job_id': jobs.submit_install(folder, sync_id, provider_id)})
            except Exception as e:
                self._log_error(f'startFolderSyncJob(install) failed: {e}')
                return serialize_response(False, error=str(e))

        user_id = self._active_profile_id()
        if user_id is None:
            return serialize_response(False, error='No user database loaded')

        try:
            if kind == 'status':
                job_id = jobs.submit_status(user_id)
            elif kind == 'push':
                job_id = jobs.submit_push(user_id)
            elif kind == 'fetch':
                job_id = jobs.submit_fetch(user_id)
            elif kind == 'fork_report':
                parent = params.get('parent_generation')
                job_id = jobs.submit_fork_report(
                    user_id, int(parent) if parent is not None else None)
            elif kind == 'resolve':
                choice = str(params.get('choice') or '')
                blob = str(params.get('blob_name') or '')
                if not blob:
                    return serialize_response(
                        False,
                        error='resolve needs blob_name: the two sides of a fork '
                              'usually share a generation number, so a number '
                              'cannot say which side was chosen')
                job_id = jobs.submit_resolve(
                    user_id,
                    choice=choice,
                    blob_name=blob,
                    safety_dir=str(self._safety_dir()),
                    # The bridge knows which profile is open; the page does
                    # not, and must not be trusted to say. replace_profile
                    # refuses to overwrite a live database and that guard is
                    # not the page's to defeat -- keep_remote closes the
                    # profile first instead (#148), so the guard holds.
                    active_user_id=self._active_profile_id(),
                    release_profile=lambda: self._released_profile(user_id),
                )
            else:  # link
                if not folder:
                    return serialize_response(False, error='link needs a folder')
                job_id = jobs.submit_link(user_id, folder, provider_id)
            return serialize_response(True, data={'job_id': job_id})
        except Exception as e:
            self._log_error(f'startFolderSyncJob({kind}) failed: {e}',
                            {'kind': kind, 'user_id': user_id})
            return serialize_response(False, error=str(e))

    @pyqtSlot(result=str)
    @instrumented_slot
    def startFolderSyncStartupCheck(self) -> str:
        """The once-per-launch look behind the dashboard notice (#148).

        The owner decided the notice fires **once, at startup** -- not on
        every page load, and not on a timer. The dashboard reloads on every
        navigation, so "once" is kept here, per profile per launch, rather
        than trusted to the page. A profile switched to later gets its own
        one look.

        Returns ``{job_id}`` for a status job the page polls as usual, or
        ``{skipped: reason}``. An unlinked profile is skipped without
        touching the folder at all.
        """
        jobs = self._folder_sync()
        if jobs is None:
            return serialize_response(False, error='folder sync not available')
        user_id = self._active_profile_id()
        if user_id is None:
            return serialize_response(False, error='No user database loaded')
        checked = getattr(self, '_folder_sync_startup_checked', None)
        if checked is None:
            checked = self._folder_sync_startup_checked = set()
        if user_id in checked:
            return serialize_response(True, data={'skipped': 'already checked'})
        checked.add(user_id)
        try:
            if jobs.sync.state.get_link(user_id) is None:
                return serialize_response(True, data={'skipped': 'not linked'})
            return serialize_response(
                True, data={'job_id': jobs.submit_status(user_id)})
        except Exception as e:
            self._log_error(f'startFolderSyncStartupCheck failed: {e}')
            return serialize_response(False, error=str(e))

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def pollFolderSyncJob(self, job_id: str) -> str:
        """Where a job has got to.

        Returns ``{state: 'running'}`` until the worker lands, then the
        result. Phase 3 -- the database half -- runs inside this call, on
        this thread, which is the point of the whole arrangement.
        """
        jobs = self._folder_sync()
        if jobs is None:
            return serialize_response(False, error='folder sync not available')
        try:
            report = self._job_payload(jobs.poll(str(job_id)))
            if report.get('state') == 'done':
                jobs.forget(str(job_id))
            return serialize_response(True, data=report)
        except Exception as e:
            self._log_error(f'pollFolderSyncJob failed: {e}', {'job_id': job_id})
            return serialize_response(False, error=f'Failed to poll sync job: {e}')
