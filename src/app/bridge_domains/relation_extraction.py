"""Relation extraction's bridge surface (#60).

``src/app/relation_extraction/`` does the work; this file is the only thing
that knows both about that package and about ``self.user_db``. It mirrors
``bridge_domains/stt.py``, which solved the same shape of problem for #59: a
downloaded model, a worker that can fail several ways, and a UI that must not
offer a button which cannot work.

**This mixin owns the whole relation-extraction bridge surface.** Status and
the model download land first; extraction and the write path follow. Two tasks
editing one bridge file is the collision that split exists to prevent.

Every import of the feature is function-level, and that is a CI gate
-------------------------------------------------------------------
``scripts/check_relations_runtime_imports.py`` rule 2: **no module outside
``app.relation_extraction`` may import it at module scope** -- not the runtime,
not ``model_spec``, not even ``errors``, which touches nothing. The prefix is
what is matched, so a module-scope ``from app.relation_extraction.errors
import ...`` here fails the gate.

This looks pedantic beside ``stt.py``, which imports ``app.stt.errors`` at its
top, and the difference is real rather than stylistic. WIMI ships **two
artifacts per platform** (owner's decision, 2026-10-04) and the default one
carries no torch. The bridge is constructed on the startup path, so a
module-scope import here reaches the quarantine package at startup on the
artifact almost everyone downloads -- and PyInstaller's analysis is static, so
it would also drag torch toward that artifact at build time. There is no
``app.stt`` equivalent because speech-to-text ships in both.

The cost is that nothing in this file may annotate a type it cannot name.
``_relations_failure`` takes an untyped ``error`` for that reason.

A named failure is data, not a failed response
----------------------------------------------
``api._callBridge`` throws on ``success=false`` and **discards ``data``**
(``_bridge.js``'s ``_handleResponse``). So a ``RelationExtractionError``
returned as a failed response would reach the page as a bare sentence with no
``kind`` -- and the kinds are the whole point: ``model_missing`` wants a
download, ``out_of_memory`` wants something closed, ``download_failed`` wants
a retry, and offering a retry for the first two is a lie (#174, and
``errors.RETRYABLE`` is the taxonomy's own answer).

So, as in ``stt.py``:

* ``success=false`` means **the bridge could not do its job** -- no master
  database, no app-data directory, malformed JSON, an unexpected exception.
  Nothing for the student to act on and nothing to branch on.
* A **named** extraction or download failure is a successful response carrying
  ``error: {kind, detail, retryable}`` in its data.

Two deliberate departures from #60's sketched plan
--------------------------------------------------
#60 comment #4883 §6 sketched this layer as slots on ``bridge_domains/
relations.py`` with ``getRelationModelStatus()``. That section was explicitly
hedged (*"I don't recommend dispatching this"*) and withdrawn in #4889, so it
is a proposal rather than a decision -- but where it is followed and where it
is not should be on the record.

* **Its own file, not #14's.** ``relations.py`` holds five thin marshalling
  slots and no import discipline at all. The gate above makes this file's
  imports unusual, and putting that rule in the file #14's slots live in means
  every future editor of #14's work has to know it or break the default
  artifact. ``startRelationModelDownload`` keeps the sketched name exactly.
* **``getRelationExtractionStatus``, not ``getRelationModelStatus``.** Three of
  the five states it reports -- ``not_in_this_build``, ``runtime_broken``,
  ``dev_runtime_missing`` -- are not about the model, and the one thing this
  payload must not do is make a student read "no model" when their build never
  had the runtime. The narrower name would have been a small lie in the one
  place the five states exist to prevent one.

Silence is the resting state, not an error
------------------------------------------
Owner's decision, 2026-10-04: a machine that cannot extract gets **a line in
Settings and silence everywhere else** -- no disabled button on the entry form,
no "unavailable" notice. So ``getRelationExtractionStatus`` is written for
Settings, and the only thing the entry form may read from it is ``ready``.
That follows #14's decisions 10 and 11 rather than inventing a rule.

Looking must not download, and must not hash
--------------------------------------------
``getRelationExtractionStatus`` is eight ``stat`` calls. It must never call
``verify_dir``: hashing 845 MB to draw a line of text is #147's defect (a
status check doing real work) in another costume, and this model is 23x the
size of the archive that one was measured on.
"""

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from database.exceptions import SubjectNodeError, ValidationError

from ..bridge_helpers import serialize_response

logger = logging.getLogger(__name__)

_DOWNLOAD_THREAD_PREFIX = 'wimi-relations-download'


class RelationExtractionBridgeMixin:
    """Bridge mixin for relation extraction. Composed into DatabaseBridge."""

    # ==================================================================
    # Helpers (not slots)
    # ==================================================================

    def _relations_app_data_dir(self) -> Optional[Path]:
        """This installation's ``app_data/``, or ``None``.

        Read off the master database, which is where ``main.py`` put it.
        ``None`` is a real state -- a bridge built without one in a test -- and
        the slots that need a path say so rather than defaulting to the working
        directory and creating ``./models/`` beside the checkout.

        Duplicated from ``_stt_app_data_dir`` on purpose. A cross-mixin
        ``self._stt_app_data_dir()`` is legal (mixins share the instance) but
        would make a relations status line depend on a speech-to-text helper's
        contract, and the two features are delivered in different artifacts.
        """
        base = getattr(self.master_db, 'data_dir', None) if self.master_db else None
        return Path(base) if base else None

    # -- downloads -----------------------------------------------------

    def _relations_download_pool(self) -> ThreadPoolExecutor:
        pool = getattr(self, '_relations_download_pool_obj', None)
        if pool is None:
            pool = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=_DOWNLOAD_THREAD_PREFIX
            )
            self._relations_download_pool_obj = pool
        return pool

    def _relations_downloads(self) -> Dict[str, Dict[str, Any]]:
        downloads = getattr(self, '_relations_download_jobs', None)
        if downloads is None:
            downloads = {}
            self._relations_download_jobs = downloads
        return downloads

    def _relations_active_download(self) -> Optional[Dict[str, Any]]:
        """The running download's record, or ``None``.

        There is at most one: the pool has a single worker and
        ``startRelationModelDownload`` refuses to queue a second.
        """
        for record in self._relations_downloads().values():
            if record['state'] == 'running':
                return record
        return None

    @staticmethod
    def _relations_download_payload(job_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """One download's state, read under its own lock."""
        with record['lock']:
            data: Dict[str, Any] = {
                'job_id': job_id,
                'state': record['state'],
                'bytes': record['bytes'],
                'total': record['total'],
                'file': record['file'],
                'file_index': record['file_index'],
                'file_count': record['file_count'],
            }
            if record['state'] == 'done':
                data['installed'] = list(record['installed'])
                data['skipped'] = list(record['skipped'])
                data['bytes_downloaded'] = record['bytes_downloaded']
            elif record['state'] == 'failed':
                error = record['error'] or {}
                data['error'] = error
                data['code'] = error.get('kind')
                data['message'] = error.get('detail')
            return data

    # -- the runtime and its single worker -----------------------------

    def _relations_threshold(self) -> float:
        """The confidence a proposal must reach to be shown.

        **Owner's decision (#380, 2026-10-05): default 0.80, student
        configurable, range 0.10-0.95 stepped at 0.05.** 0.80 is cited to
        #4904 -- the owner's blind adjudication of 102 cards, where precision
        was 0.69 overall and 0.80 at a 0.8 cut -- not to GLiNER2's own
        default, which is what the shipped 0.5 was.

        ``user_preferences.relation_confidence_threshold`` (m028) holds the
        student's value. It is **user-level, not device-local**: #126/#129's
        test is whether a value denotes a machine, and a judgement about
        proposal quality does not -- so it travels in a ``.wimi``, which is
        also why Settings offers the dial on a build that cannot run
        extraction at all. The preference is for the student's *other*
        machine as much as this one.

        ``.get`` with a fallback rather than a subscript, and that is not
        defensive habit: m028 arrives on a separate branch, so this has to
        answer correctly both before and after it lands, and a profile opened
        from an older archive legitimately has no such column until its
        migration runs. The fallback is the same 0.80.

        Passed **per call** to ``RelationJobs.start``, never baked into the
        runtime: see ``_relations_runtime`` for why the loaded model must not
        depend on it.
        """
        from app.relation_extraction.runtime import EXTRACTION_THRESHOLD
        db = self.user_db
        if db is None:
            return EXTRACTION_THRESHOLD
        try:
            stored = (db.get_all_settings() or {}).get(
                'relation_confidence_threshold')
        except Exception as e:  # noqa: BLE001 - a settings read must not break this
            self._log_error(f'relations: could not read the threshold: {e}')
            return EXTRACTION_THRESHOLD
        if stored is None:
            return EXTRACTION_THRESHOLD
        try:
            return float(stored)
        except (TypeError, ValueError):
            self._log_error(
                f'relations: ignoring a non-numeric threshold {stored!r}')
            return EXTRACTION_THRESHOLD

    def _relations_runtime(self):
        """A ``RelationRuntime`` for the current app data, built on first use.

        Keyed on the app-data directory **and nothing else**, which is the
        whole point: the instance is what holds the 845 MB of loaded weights,
        so anything in its identity that a student can change is a 16 s load
        they paid for by changing it.

        **The threshold is deliberately not in the key.** It was, until #384
        landed a per-call ``threshold=`` on ``RelationJobs.start``; with it in
        the key, moving the Settings dial dropped the loaded model and the
        next pass reloaded it. The cutoff is a number compared against scores
        the model has already produced, so it never belonged in the identity
        of the thing that produces them.

        ``None`` when there is no app-data directory to resolve a model
        against.
        """
        app_data = self._relations_app_data_dir()
        if app_data is None:
            return None
        key = str(app_data)
        if getattr(self, '_relations_runtime_key', None) == key:
            return self._relations_runtime_obj
        from app.relation_extraction.runtime import RelationRuntime
        runtime = RelationRuntime(app_data_dir=app_data)
        self._relations_runtime_key = key
        self._relations_runtime_obj = runtime
        return runtime

    def _relations_jobs(self):
        """The single-worker extraction executor, built on first use.

        A plain attribute so a test can inject a fake, as the browser pane's
        controller is. The re-point applies **only to an executor this
        built**: replacing an injected one would quietly discard the fake a
        test had just put there, which is a seam that does not work.
        """
        runtime = self._relations_runtime()
        if runtime is None:
            return None
        jobs = getattr(self, '_relations_jobs_obj', None)
        if jobs is None:
            from app.relation_extraction.jobs import RelationJobs
            jobs = RelationJobs(runtime=runtime)
            self._relations_jobs_obj = jobs
            self._relations_jobs_owned = True
        elif getattr(self, '_relations_jobs_owned', False):
            jobs.runtime = runtime
        return jobs

    def shutdown_relation_extraction(self) -> None:
        """Stop the workers. Safe to call more than once, and never raises.

        Not wired into ``MainWindow`` -- neither folder sync's executor nor
        speech-to-text's is, and the process exiting is what stops them. It
        exists so a host that wants an orderly teardown has one call to make,
        and so a test can reclaim the threads.

        A cancelled download leaves its ``.part`` files, which is what makes
        the next attempt resume rather than refetch 845 MB. See
        ``cancelRelationModelDownload``.
        """
        jobs = getattr(self, '_relations_jobs_obj', None)
        if jobs is not None:
            try:
                jobs.shutdown()
            except Exception as e:  # noqa: BLE001 - teardown must not raise
                logger.warning('relations: extraction shutdown failed: %s', e)
            self._relations_jobs_obj = None
            self._relations_jobs_owned = False
        # The runtime goes too, so the model's ~1.7 GB is released rather than
        # held by a bridge nobody is using any more.
        runtime = getattr(self, '_relations_runtime_obj', None)
        if runtime is not None:
            try:
                runtime.unload()
            except Exception as e:  # noqa: BLE001
                logger.warning('relations: model unload failed: %s', e)
            self._relations_runtime_obj = None
            self._relations_runtime_key = None
        for record in self._relations_downloads().values():
            cancel = record.get('cancel')
            if cancel is not None:
                cancel.set()
        pool = getattr(self, '_relations_download_pool_obj', None)
        if pool is not None:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception as e:  # noqa: BLE001 - teardown must not raise
                logger.warning('relations: download shutdown failed: %s', e)
            self._relations_download_pool_obj = None

    # ==================================================================
    # Status
    # ==================================================================

    @pyqtSlot(result=str)
    @instrumented_slot
    def getRelationExtractionStatus(self) -> str:
        """Whether this copy of WIMI can extract relations, and what is missing.

        Five states, not one ``available`` boolean, because three of them are
        actionable and the actions differ: the other download exists
        (``not_in_this_build``), a pip command (``dev_runtime_missing``), a
        download button (``model_not_downloaded``). Collapsing them into the
        most pessimistic wording tells a student their machine cannot run this
        when what they actually have is the smaller download, which is false.

        Returns:
            JSON response whose ``data`` carries:

            * ``state`` -- an ``AvailabilityState`` value;
            * ``ready`` / ``actionable`` -- the taxonomy's own answers;
            * ``missing`` -- runtime packages that could not be found;
            * ``model`` -- ``{installed, path, missing_files, total_bytes,
              bytes_still_needed, total_mb}``, all from ``stat`` calls and the
              pin table. Never a hash (module docstring);
            * ``licence`` -- what the weights are under, for the Settings line
              and the About panel's §5(d) notices;
            * ``download`` -- the running download's poll payload, or ``null``.
              Carried so Settings reopened mid-download finds the job id it
              needs in order to poll and cancel. That is #171's lesson: a page
              that cannot name the job can only wait the download out.

        ``model`` is reported even when the runtime is absent. A student on the
        default artifact asking "how big is this" deserves the number, and the
        two facts are independent.
        """
        from app.relation_extraction import model_spec
        from app.relation_extraction.availability import get_availability

        app_data = self._relations_app_data_dir()
        try:
            if app_data is None:
                # Report the runtime honestly and say the model cannot be
                # located, rather than reporting "no model" as "no runtime".
                # They have different fixes; see stt.py's
                # _stt_status_without_app_data for the same split.
                #
                # ``model_installed=False`` is not decoration. Without it a
                # working runtime reports ``ready`` here while ``model`` in the
                # same payload says nothing is installed -- and the entry form
                # reads ``ready``, so it would offer extraction against a model
                # that cannot be located. Caught by
                # test_no_app_data_reports_the_runtime_rather_than_a_failure.
                availability = get_availability(model_installed=False)
                model = {
                    'installed': False,
                    'path': None,
                    'missing_files': list(model_spec.MODEL_FILE_NAMES),
                    'total_bytes': model_spec.TOTAL_BYTES,
                    'bytes_still_needed': model_spec.TOTAL_BYTES,
                    'total_mb': model_spec.total_megabytes(),
                }
            else:
                directory = model_spec.model_dir(app_data, create=False)
                missing = model_spec.missing_files(app_data)
                availability = get_availability(
                    model_path=directory, model_installed=not missing)
                model = {
                    'installed': not missing,
                    'path': str(directory),
                    'missing_files': list(missing),
                    'total_bytes': model_spec.TOTAL_BYTES,
                    'bytes_still_needed': model_spec.bytes_still_needed(app_data),
                    'total_mb': model_spec.total_megabytes(),
                }
        except Exception as e:
            self._log_error(f'getRelationExtractionStatus failed: {e}')
            return serialize_response(
                False, error=f'Failed to read relation extraction status: {e}')

        active = self._relations_active_download()
        download = None
        if active is not None:
            download = self._relations_download_payload(active['job_id'], active)

        return serialize_response(True, data={
            'state': availability.state.value,
            'ready': availability.ready,
            'actionable': availability.actionable,
            'missing': list(availability.missing),
            'model': model,
            'licence': {
                'model': model_spec.MODEL_LICENCE,
                'base': model_spec.MODEL_BASE_LICENCE,
                'url': model_spec.MODEL_LICENCE_URL,
                'repo': model_spec.MODEL_REPO,
                'revision': model_spec.MODEL_REVISION,
            },
            'download': download,
        })

    # ==================================================================
    # The first-use model download
    # ==================================================================

    @pyqtSlot(result=str)
    @instrumented_slot
    def startRelationModelDownload(self) -> str:
        """Fetch the pinned weights on a worker thread.

        "No model yet" is not a failure: it is the resting state of a relations
        build nobody has used yet, and this is the button the student presses
        from it. Resumable and idempotent -- files already present at their
        pinned size are skipped and a ``.part`` is continued, so pressing this
        after a cancelled transfer costs only what is left.

        Takes no arguments. Unlike speech-to-text there is no size to choose:
        the pin table names one revision of one model, and which files it holds
        is not a user decision.

        Returns:
            JSON response with ``{job_id, total_bytes, bytes_still_needed,
            file_count}``. Poll ``pollRelationModelDownload``.

            A download already running is **not** started again: the response
            carries that job's id with ``already_running: true``, so a double
            press polls the transfer in flight instead of queueing a second one
            behind it on the single worker.
        """
        from app.relation_extraction import model_spec
        from app.relation_extraction.errors import (
            RelationExtractionError, RelationExtractionErrorKind as Kind,
        )

        app_data = self._relations_app_data_dir()
        if app_data is None:
            return serialize_response(
                False,
                error='Relation extraction is not available: no app data directory')

        active = self._relations_active_download()
        if active is not None:
            return serialize_response(True, data={
                'job_id': active['job_id'],
                'already_running': True,
                'total_bytes': model_spec.TOTAL_BYTES,
                'bytes_still_needed': model_spec.bytes_still_needed(app_data),
                'file_count': len(model_spec.MODEL_FILE_NAMES),
            })

        job_id = uuid.uuid4().hex
        cancel = threading.Event()
        lock = threading.Lock()
        record: Dict[str, Any] = {
            'job_id': job_id,
            'state': 'running',
            # Both numbers come from the pin table, so neither can be None --
            # the difference from #59, where a response without Content-Length
            # is legal and a page dividing by the total breaks.
            'bytes': model_spec.TOTAL_BYTES - model_spec.bytes_still_needed(app_data),
            'total': model_spec.TOTAL_BYTES,
            'file': None,
            'file_index': 0,
            'file_count': 0,
            'installed': (),
            'skipped': (),
            'bytes_downloaded': 0,
            'cancel': cancel,
            'error': None,
            'lock': lock,
        }

        def progress(done: int, total: int) -> None:
            with lock:
                record['bytes'] = done
                record['total'] = total

        def on_file(name: str, index: int, count: int) -> None:
            with lock:
                record['file'] = name
                record['file_index'] = index
                record['file_count'] = count

        def run() -> None:
            from app.relation_extraction.download import install_model
            try:
                result = install_model(
                    app_data, cancel=cancel, progress=progress, on_file=on_file)
            except RelationExtractionError as exc:
                with lock:
                    record['state'] = 'failed'
                    record['error'] = exc.to_dict()
                logger.info('relations: model download %s failed: %s', job_id, exc)
                return
            except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
                with lock:
                    record['state'] = 'failed'
                    # The text goes in ``detail``, not in the message.
                    # ``to_dict`` deliberately drops the message -- copy is
                    # chosen from ``kind`` -- so passing it there would discard
                    # the only description of what went wrong, leaving the page
                    # a bare ``download_failed`` with ``detail: null`` and the
                    # cause in the log alone. ``jobs.py`` spells it this way
                    # for the same reason.
                    record['error'] = RelationExtractionError(
                        Kind.DOWNLOAD_FAILED, 'the download failed',
                        detail=f'{type(exc).__name__}: {exc}',
                    ).to_dict()
                logger.exception('relations: model download %s raised', job_id)
                return
            with lock:
                record['state'] = 'done'
                record['installed'] = result.installed
                record['skipped'] = result.skipped
                record['bytes_downloaded'] = result.bytes_downloaded
            logger.info('relations: model download %s done (%s)',
                        job_id, result.describe())

        downloads = self._relations_downloads()
        for done_id in [
            key for key, value in downloads.items() if value['state'] != 'running'
        ]:
            downloads.pop(done_id, None)
        downloads[job_id] = record
        try:
            self._relations_download_pool().submit(run)
        except Exception as e:
            downloads.pop(job_id, None)
            self._log_error(f'startRelationModelDownload could not queue: {e}')
            return serialize_response(False, error=f'Failed to start download: {e}')

        return serialize_response(True, data={
            'job_id': job_id,
            'already_running': False,
            'total_bytes': model_spec.TOTAL_BYTES,
            'bytes_still_needed': model_spec.bytes_still_needed(app_data),
            'file_count': len(model_spec.MODEL_FILE_NAMES),
        })

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def pollRelationModelDownload(self, job_id: str) -> str:
        """Where a download has got to.

        ``job_id`` is echoed on every branch, the unknown-job one included: a
        payload saying a job is unknown without saying which job is the least
        traceable of the lot (#171).

        Returns:
            JSON response with ``{job_id, state, bytes, total, file,
            file_index, file_count}``, plus ``{installed, skipped,
            bytes_downloaded}`` when done or ``{error, code, message}`` when
            failed. ``bytes`` starts at what is already on disk rather than at
            zero, so a resumed download does not crawl from 0% through ground
            it has already covered.

        A finished job is **kept**, not forgotten: a page polls once more
        before it notices the first terminal answer, and forgetting here would
        turn that poll into ``unknown_job``, which reads as a failure. The
        previous job is dropped when the next download starts.
        """
        from app.relation_extraction.errors import (
            RelationExtractionError, RelationExtractionErrorKind as Kind,
        )

        record = self._relations_downloads().get(str(job_id))
        if record is None:
            message = f'no such download job: {job_id}'
            return serialize_response(True, data={
                'job_id': str(job_id),
                'state': 'failed',
                'error': RelationExtractionError(Kind.UNKNOWN_JOB, message).to_dict(),
                'code': Kind.UNKNOWN_JOB.value,
                'message': message,
            })
        return serialize_response(
            True, data=self._relations_download_payload(str(job_id), record))

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def cancelRelationModelDownload(self, job_id: str) -> str:
        """Stop a download, **keeping** what has been fetched.

        This is the deliberate difference from ``cancelModelDownload`` (#59),
        which deletes the ``.part`` because resuming something the student said
        no to would be wrong. Here the quantity decides: one 845 MB set across
        eight files, against a single file of 142 MB. A cancel on a train is
        far more often "not now" than "never", and refetching 800 MB to honour
        the stricter reading costs the student more than it protects them.

        ``discardRelationModelDownload`` is the other half -- the explicit
        "start over" -- so neither reading is unavailable, and the one that
        throws work away is the one that has to be asked for.

        Returns:
            JSON response with ``{cancelled}``. Poll once more to see the job
            reach ``failed`` with ``download_cancelled``.
        """
        record = self._relations_downloads().get(str(job_id))
        if record is None:
            return serialize_response(True, data={'cancelled': False})
        try:
            record['cancel'].set()
            return serialize_response(True, data={'cancelled': True})
        except Exception as e:
            self._log_error(f'cancelRelationModelDownload failed: {e}',
                            {'job_id': job_id})
            return serialize_response(False, error=f'Failed to cancel download: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def discardRelationModelDownload(self) -> str:
        """Throw away partial files so the next download starts over.

        For a transfer that stalled on a bad link, where resuming keeps
        continuing from a prefix that may be the problem. Installed files are
        **not** touched -- those are at their pinned size and deleting them is
        uninstalling, which is a different action and will be a different
        button.

        Refuses while a download is running, rather than deleting the ``.part``
        the worker is writing into.

        Returns:
            JSON response with ``{discarded: [names], running: false}``.
        """
        app_data = self._relations_app_data_dir()
        if app_data is None:
            return serialize_response(
                False,
                error='Relation extraction is not available: no app data directory')
        if self._relations_active_download() is not None:
            return serialize_response(True, data={'discarded': [], 'running': True})
        try:
            from app.relation_extraction.download import discard_partials
            removed = discard_partials(app_data)
        except Exception as e:
            self._log_error(f'discardRelationModelDownload failed: {e}')
            return serialize_response(
                False, error=f'Failed to discard partial downloads: {e}')
        return serialize_response(
            True, data={'discarded': list(removed), 'running': False})

    # ==================================================================
    # Proposing relations from an entry's explanation
    # ==================================================================

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def proposeRelationsForEntry(self, params_json: str) -> str:
        """Ask the model what the student's explanation relates, on a worker.

        **Started by a press, never automatically** (owner's decision, #380):
        a pass is 0.35-0.42 s for a short explanation and 7.7 s for 16,200
        characters, and the *first* pass of a session also loads the model --
        16.1 s and a 2-3 GB peak. Automatic would mean the first entry of
        every session paying that unasked.

        Args:
            params_json: JSON with ``entry_id`` (required) and an optional
                opaque ``token``. The token is echoed on every poll and is
                never interpreted: the **page** decides whether proposals are
                stale, and it can only do that if what it sent comes back
                (#59's §3.5, where a stale transcript could corrupt a
                different entry's field).

        Returns:
            JSON response whose ``data`` carries ``{available, state}`` and,
            when a pass started, ``{job_id, token, labels, vocabulary_terms}``.

            **An unavailable machine is a success carrying ``available:
            false``, not a failure.** The owner's decision is that the entry
            form shows *nothing* when extraction cannot run, so a page that
            reaches this slot with a stale button has to be able to go quiet
            rather than raise a toast. ``success=false`` is reserved for the
            bridge being unable to do its job at all.

            ``started: false`` with a ``reason`` is also a success: an entry
            with no explanation yet, an exam with no relation types, and an
            exam with no subjects are all ordinary states, and none of them is
            worth a model pass or an error.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')

        from app.relation_extraction import model_spec
        from app.relation_extraction.availability import get_availability
        from app.relation_extraction.matching import Vocabulary
        from app.relation_extraction.runtime import labels_from_types, plain_text

        try:
            params = json.loads(params_json) if params_json else {}
            entry_id = params.get('entry_id')
            if not entry_id:
                return serialize_response(False, error='entry_id is required')
            entry_id = int(entry_id)
            token = params.get('token')

            # This check is also what guarantees a runtime below:
            # ``_relations_runtime`` returns ``None`` only when there is no
            # app-data directory, so there is deliberately no second guard
            # for that after this point.
            app_data = self._relations_app_data_dir()
            if app_data is None:
                return serialize_response(True, data={
                    'available': False, 'state': 'model_not_downloaded',
                    'started': False, 'reason': 'no_app_data'})
            availability = get_availability(
                model_path=model_spec.model_dir(app_data, create=False),
                model_installed=not model_spec.missing_files(app_data))
            if not availability.ready:
                return serialize_response(True, data={
                    'available': False, 'state': availability.state.value,
                    'started': False, 'reason': availability.state.value})

            source = self.user_db.get_extraction_source(entry_id)
            text = plain_text(source['explanation'])
            if not text:
                return serialize_response(True, data={
                    'available': True, 'state': 'ready', 'started': False,
                    'reason': 'no_explanation', 'token': token})

            types = self.user_db.get_relation_types(source['exam_id'])
            labels = labels_from_types(types)
            if not labels:
                # An exam whose list is empty or entirely retired. Asking the
                # model about no labels would return nothing, slowly.
                return serialize_response(True, data={
                    'available': True, 'state': 'ready', 'started': False,
                    'reason': 'no_relation_types', 'token': token})

            vocabulary = Vocabulary.from_subjects(
                self.user_db.get_extraction_vocabulary(source['exam_context']))
            if not len(vocabulary):
                return serialize_response(True, data={
                    'available': True, 'state': 'ready', 'started': False,
                    'reason': 'no_subjects', 'token': token})

            jobs = self._relations_jobs()
            symmetric = frozenset(
                int(t['id']) for t in types if t.get('is_symmetric'))
            finish = self._relations_finish(
                entry_id=entry_id,
                exam_context=source['exam_context'],
                vocabulary=vocabulary,
                symmetric_type_ids=symmetric,
            )
            job_id = jobs.start(
                text, labels,
                context={'entry_id': entry_id, 'token': token},
                finish=finish,
                # Read on this thread, because a preference is a database
                # read and the worker may not make one. ``start`` validates
                # it here too, so a value outside 0.10-0.95 is refused at the
                # call rather than producing a flooded or empty panel.
                threshold=self._relations_threshold(),
            )
            # Drop the *previous* extraction, not this one and not on its
            # first terminal poll: a page polls once more after it sees a
            # result, and forgetting earlier would turn that into
            # ``unknown_job``. ``forget`` leaves an uncollected job alone, so
            # a result still on its way cannot be lost either. Without this
            # every extraction in a session keeps its finished job -- and
            # each one holds a vocabulary of the whole exam in its ``finish``
            # closure.
            previous = getattr(self, '_relations_last_job', None)
            if previous is not None and previous != job_id:
                jobs.forget(previous)
            self._relations_last_job = job_id
        except SubjectNodeError as e:
            return serialize_response(False, error=str(e))
        except ValueError as e:
            # Three things land here, and all three are a malformed request
            # rather than a failure of the feature: a non-numeric id, invalid
            # JSON (``JSONDecodeError`` is a ``ValueError``), and the label
            # set. ``RelationJobs.start`` validates that last one on **this**
            # thread precisely so it fails at the call rather than later as a
            # failed job nobody can place.
            self._log_error(f'proposeRelationsForEntry refused: {e}',
                            {'params_json': params_json})
            return serialize_response(False, error=f'Cannot extract relations: {e}')
        except Exception as e:
            self._log_error(f'proposeRelationsForEntry failed: {e}',
                            {'params_json': params_json})
            return serialize_response(
                False, error=f'Failed to start relation extraction: {e}')

        return serialize_response(True, data={
            'available': True,
            'state': 'ready',
            'started': True,
            'job_id': job_id,
            'token': token,
            'entry_id': entry_id,
            'labels': [label.label for label in labels],
            'vocabulary_terms': len(vocabulary),
        })

    def _relations_finish(self, *, entry_id, exam_context, vocabulary,
                          symmetric_type_ids):
        """The callable ``RelationJobs.poll`` runs on the polling thread.

        **This is the one place this feature touches the database**, and it is
        safe only because ``poll`` runs it inline on the thread that called
        it, which is the Qt main thread. Nothing here may move onto the
        worker: ``base_db.py`` records that nothing in this application writes
        to the database from a second thread, and the breakage would be an
        interleaved transaction depth -- silent and intermittent.

        It writes each matched proposal as an **unconfirmed** relation
        (#5494): ``origin='extracted'``, the passage as the reason,
        ``confirmed_at`` NULL, so it is invisible until the student endorses
        it. The model's confidence is deliberately **not** stored -- #4883
        §6.1 measured that it does not separate an accepted proposal from a
        rejected one, so a column for it would be a number nobody can act on.
        """
        from app.relation_extraction.matching import match_proposals

        def finish(result) -> Dict[str, Any]:
            db = self.user_db
            if db is None:
                # The profile was switched while the pass ran. The result is
                # about a database that is no longer attached, so it is
                # reported rather than written anywhere.
                return {'proposals': [], 'counts': {}, 'written': 0,
                        'reason': 'profile_closed'}

            written: List[Dict[str, Any]] = []
            refused: List[Dict[str, Any]] = []

            # One transaction over the discard and the writes. Re-running an
            # extraction replaces that entry's own unconfirmed proposals
            # (#382), and a failure part-way must not leave the entry with
            # neither the old ones nor the new.
            with db.transaction():
                discarded = db.discard_unconfirmed_proposals_for_entry(entry_id)

                # Read the suppression set **after** the discard and inside
                # the transaction, for two reasons. The discard changes it --
                # this entry's own previous proposals were occupying m026's
                # UNIQUE and would otherwise suppress every pair they had
                # already proposed, so a second run would report everything
                # as suppressed and write nothing. And a relation written by
                # the student while the pass ran has to be in it, or m026
                # refuses that insert: a refusal they did not cause.
                rejected = db.rejected_pairs_for_entry(entry_id)
                suppressed = rejected | db.existing_relation_pairs(exam_context)
                report = match_proposals(
                    result.proposals, vocabulary,
                    suppressed_pairs=suppressed,
                    symmetric_type_ids=symmetric_type_ids,
                )
                pending_elsewhere = self._relations_pending_elsewhere(
                    db, report.suppressed, rejected, exam_context, entry_id,
                    symmetric_type_ids)

                for candidate in report.matched:
                    try:
                        relation = db.create_subject_relation(
                            candidate.from_subject_id,
                            candidate.to_subject_id,
                            candidate.proposal.passage,
                            origin='extracted',
                            source_entry_id=entry_id,
                            relation_type_id=candidate.relation_type_id,
                        )
                    except (ValidationError, SubjectNodeError) as exc:
                        # One proposal must not lose the rest, and this is
                        # safe inside the enclosing transaction precisely
                        # because #95 made it re-entrant: the failed insert
                        # opened a savepoint, so only its own work is
                        # discarded and the transaction stays alive to carry
                        # on. The reachable case is a passage longer than
                        # MAX_REASON_LENGTH -- a run-on sentence rather than
                        # a bug, and truncating it would store words the
                        # student did not write as their own reason.
                        refused.append({**candidate.to_dict(), 'error': str(exc)})
                        continue
                    written.append({**candidate.to_dict(),
                                    'relation_id': relation['id']})

            logger.info('relations: entry %s -> %s (%d written, %d refused, '
                        '%d previous discarded)', entry_id, report.describe(),
                        len(written), len(refused), discarded)
            return {
                'proposals': written,
                'refused': refused,
                'pending_elsewhere': pending_elsewhere,
                'unmatched': [u.to_dict() for u in report.unmatched],
                'ambiguous': [a.to_dict() for a in report.ambiguous],
                'counts': {**report.counts, 'written': len(written),
                           'refused': len(refused),
                           'previous_discarded': discarded},
                'ms': result.ms,
                'load_ms': result.load_ms,
            }

        return finish

    @staticmethod
    def _relations_pending_elsewhere(db, suppressed, rejected, exam_context,
                                     entry_id, symmetric_type_ids):
        """The suppressed pairs worth a note on the card (#390), one per pair.

        A pair is suppressed for one of four reasons, and the owner's decision
        is a note for exactly one of them: **an unanswered proposal waiting on
        another entry**. The other three say nothing:

        * a **rejection** -- the student's own decision, and re-surfacing it
          would undo the point of making it. Checked first, because the union
          the matcher saw cannot say which source suppressed a pair;
        * a **confirmed** relation, already on the deep-dive panel;
        * a **hidden** one, whose subject was archived.

        The last two never reach this list because
        ``pending_proposals_elsewhere`` filters them in SQL.
        """
        from app.relation_extraction.matching import canonical_pair

        if not suppressed:
            return []
        pending = db.pending_proposals_elsewhere(exam_context, entry_id)
        notes, seen = [], set()
        for candidate in suppressed:
            first, second = canonical_pair(
                candidate.from_subject_id, candidate.to_subject_id,
                candidate.relation_type_id, symmetric_type_ids)
            key = (first, second, candidate.relation_type_id)
            if key in rejected or key in seen or key not in pending:
                continue
            if not (candidate.from_subject_name and candidate.to_subject_name):
                # Unreachable today (the vocabulary names every subject it
                # matched), but a note would read "None causes None".
                continue
            seen.add(key)
            notes.append({
                'from_subject_name': candidate.from_subject_name,
                'to_subject_name': candidate.to_subject_name,
                'label': candidate.proposal.label,
                'relation_type_id': candidate.relation_type_id,
                **pending[key],
            })
        return notes

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def pollRelationProposals(self, job_id: str) -> str:
        """Where an extraction has got to, writing its proposals when it lands.

        The finish phase runs **inside this call, on this thread** -- see
        ``_relations_finish``.

        Returns:
            JSON response with ``{job_id, state, context, entry_id, token}``
            plus, when done, the proposals and the counts; when failed,
            ``{error: {kind, detail, retryable}, code, message}``; and
            ``state: 'cancelled'`` when the student stopped it.

            **``retryable`` is forced to false after a wedge**, whatever the
            taxonomy says about ``extraction_timeout``. #174's rule is that a
            message may not direct a press when nothing is pressable, and a
            wedged worker is exactly that: ``RelationJobs`` refuses every
            later ``start`` with the same error until WIMI restarts, so a
            retry button would be a guaranteed-failing press. The honest copy
            names the restart, which is why ``wedged`` is lifted out of
            ``detail`` into its own key rather than left for the page to dig
            for.
        """
        from app.relation_extraction.errors import (
            RelationExtractionError, RelationExtractionErrorKind as Kind,
        )

        # The **existing** runner, never a fresh one. ``_relations_jobs()``
        # would build a runtime and start a worker thread here, and a stray
        # poll of an id nobody issued must not do that -- it has no job to
        # report on, so the answer is ``unknown_job`` either way.
        jobs = getattr(self, '_relations_jobs_obj', None)
        if jobs is None:
            message = f'no such extraction job: {job_id}'
            return serialize_response(True, data={
                'job_id': str(job_id),
                'state': 'failed',
                'error': RelationExtractionError(Kind.UNKNOWN_JOB, message).to_dict(),
                'code': Kind.UNKNOWN_JOB.value,
                'message': message,
                'wedged': False,
            })
        try:
            report = jobs.poll(str(job_id))
        except Exception as e:
            self._log_error(f'pollRelationProposals failed: {e}',
                            {'job_id': job_id})
            return serialize_response(
                False, error=f'Failed to poll relation extraction: {e}')

        state = report.get('state')
        context = dict(report.get('context') or {})
        data: Dict[str, Any] = {
            'job_id': str(job_id),
            'state': state,
            'context': context,
            'entry_id': context.get('entry_id'),
            'token': context.get('token'),
        }

        if state == 'done':
            data.update(report.get('result') or {})
        elif state == 'failed':
            error = report.get('error') or RelationExtractionError(
                Kind.EXTRACTION_FAILED, 'the job reported no reason').to_dict()
            detail = error.get('detail')
            wedged = bool(isinstance(detail, dict) and detail.get('wedged'))
            if wedged:
                error = {**error, 'retryable': False}
            data['error'] = error
            data['wedged'] = wedged
            data['code'] = error.get('kind')
            data['message'] = detail if isinstance(detail, str) else None

        # Not forgotten here, for the same reason a finished transcription is
        # kept: a page polls once more before it notices the first terminal
        # answer, and forgetting would turn that into ``unknown_job``.
        return serialize_response(True, data=data)

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def cancelRelationExtraction(self, job_id: str) -> str:
        """Ask a pass to stop. It stops at its next chunk.

        A queued pass never starts; a running one stops before the next
        encoder forward, which on an ordinary explanation is the next fraction
        of a second. What cannot be stopped is a first model load, which is
        one ``from_pretrained`` call -- that job reports ``cancelled`` when
        the load returns, and the loaded model is kept for the next one.

        Returns:
            JSON response with ``{cancelled}``: whether there was anything to
            stop. A finished pass is left alone, because its result exists and
            discarding it would throw away work the student waited for.
        """
        jobs = self._relations_jobs()
        if jobs is None:
            return serialize_response(True, data={'cancelled': False})
        try:
            return serialize_response(
                True, data={'cancelled': bool(jobs.cancel(str(job_id)))})
        except Exception as e:
            self._log_error(f'cancelRelationExtraction failed: {e}',
                            {'job_id': job_id})
            return serialize_response(
                False, error=f'Failed to cancel relation extraction: {e}')

    # ==================================================================
    # Accepting and rejecting a proposal
    # ==================================================================

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def acceptRelationProposal(self, params_json: str) -> str:
        """Endorse a proposed relation, which is what makes it visible (#5494).

        Args:
            params_json: JSON with ``relation_id`` (required), optional
                ``reason`` (the edited passage) and, when the student retyped
                it, ``relation_type_id`` **with** ``change_type: true``.
                ``change_type`` exists because ``null`` is a legitimate value
                for that column -- it means untyped -- so without the flag
                this slot could not tell "leave the type alone" from "make it
                untyped", and one of those silently retypes a relation the
                student did not retype.

        Returns:
            JSON response with the confirmed row, or ``success=false``
            carrying the sentence it was refused with. A blank reason and a
            retype onto an occupied pair are both normal user states and both
            arrive that way, because the student is looking at the field.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            params = json.loads(params_json) if params_json else {}
            relation_id = params.get('relation_id')
            if not relation_id:
                return serialize_response(False, error='relation_id is required')
            type_id = params.get('relation_type_id')
            return serialize_response(True, data=self.user_db.confirm_subject_relation(
                int(relation_id),
                reason=params.get('reason'),
                relation_type_id=int(type_id) if type_id is not None else None,
                change_type=bool(params.get('change_type')),
            ))
        except (ValidationError, SubjectNodeError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'acceptRelationProposal failed: {e}',
                            {'params_json': params_json})
            return serialize_response(
                False, error=f'Failed to confirm relation: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def rejectRelationProposal(self, params_json: str) -> str:
        """Record a rejection by **kind** and remove the unconfirmed row (m027).

        The kind decides the scope, and there is no default: ``misread``
        suppresses the pair for *this entry only*, because it is a statement
        about one piece of text; ``not_related`` suppresses it everywhere,
        because it is a claim about the two subjects. #60's adjudication found
        **25 of 45 rejections meant "you misread my sentence"**, which is why
        #14's ``strength = -1`` sentinel was the wrong mechanism: it would
        have globally suppressed 25 true pairs.

        Args:
            params_json: JSON with ``relation_id`` (the unconfirmed row) or
                the pair as ``from_subject_id``/``to_subject_id``, plus
                ``kind`` (required) and optional ``relation_type_id`` and
                ``passage``.

        **The rejection and the deletion are one transaction.** If the
        rejection were recorded and the delete failed, the pair would stay
        suppressed *and* keep an invisible row occupying m026's ``UNIQUE`` --
        so the student could neither be proposed it again nor write it by
        hand. That is precisely the trap #4883 §6.2 identified in the sentinel
        approach, reached by a different route.

        Returns:
            JSON response with ``{rejection, deleted}``, or ``success=false``
            carrying the refusal -- an unknown kind, a self-loop, or a
            ``misread`` with no entry, each of which is a sentence rather than
            a constraint failure three frames down.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database connected')
        try:
            params = json.loads(params_json) if params_json else {}
            kind = params.get('kind')
            if not kind:
                return serialize_response(
                    False,
                    error=('kind is required: "misread" if the extractor read '
                           'the sentence wrongly, "not_related" if the two '
                           'subjects are not related. They are scoped '
                           'differently, so there is no safe default.'))

            relation_id = params.get('relation_id')
            from_id = params.get('from_subject_id')
            to_id = params.get('to_subject_id')
            type_id = params.get('relation_type_id')
            source_entry_id = params.get('source_entry_id')
            passage = params.get('passage')

            row = None
            if relation_id:
                row = self.user_db.get_subject_relation(int(relation_id))
                if row is None:
                    return serialize_response(
                        False, error=f'Relation {relation_id} not found')
                # **A confirmed or hand-written relation is not a proposal**,
                # and without this that is a destructive surprise: this slot
                # deletes the row it is given, so rejecting an id that
                # happened to name the student's own visible relation would
                # delete it *and* suppress the pair for good. Only an
                # unconfirmed extraction is a proposal; anything else is
                # removed deliberately, through deleteSubjectRelation.
                if row['origin'] != 'extracted' or row['confirmed_at'] is not None:
                    return serialize_response(
                        False,
                        error=('That relation is not a proposal: it has been '
                               'confirmed or was written by hand. Remove it '
                               'from the relations panel instead.'))
                from_id = row['from_subject_id']
                to_id = row['to_subject_id']
                if type_id is None:
                    type_id = row['relation_type_id']
                if source_entry_id is None:
                    source_entry_id = row['source_entry_id']
                if passage is None:
                    passage = row['reason']
            if not from_id or not to_id:
                return serialize_response(
                    False,
                    error='relation_id, or both from_subject_id and '
                          'to_subject_id, are required')

            with self.user_db.transaction():
                rejection = self.user_db.record_relation_rejection(
                    int(from_id), int(to_id),
                    kind=str(kind),
                    relation_type_id=int(type_id) if type_id is not None else None,
                    source_entry_id=(int(source_entry_id)
                                     if source_entry_id is not None else None),
                    passage=passage,
                )
                deleted = False
                if row is not None:
                    deleted = self.user_db.delete_subject_relation(int(relation_id))
            return serialize_response(
                True, data={'rejection': rejection, 'deleted': bool(deleted)})
        except (ValidationError, SubjectNodeError) as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(f'rejectRelationProposal failed: {e}',
                            {'params_json': params_json})
            return serialize_response(
                False, error=f'Failed to record the rejection: {e}')
