"""WIMI speech-to-text bridge operations (#59).

The whole of the feature's surface to the page: microphone status, recording,
transcription, the first-run model download, and the settings round trip.
``src/app/stt/`` does the work; this file is the only thing that knows both
about that package and about ``self.user_db``.

**This mixin owns the entire ``stt`` bridge surface, download slots
included.** T21 wrote ``download.py``; this task exposes it. Two tasks
editing one bridge file is the collision the split exists to prevent.

A taxonomy error is data, not a failed response
-----------------------------------------------

``api._callBridge`` throws on ``success=false`` and **discards ``data``**
(``_bridge.js``'s ``_handleResponse``). So an ``SttError`` returned as a
failed response would reach the page as a bare sentence with no ``kind`` --
and §7 of the plan is entirely about the page branching on the kind, because
"no microphone", "another app has it", "you denied permission" and "the
Windows privacy toggle ate your audio" have four different remediations and
one of them (retry) is a lie for two of the four.

So the rule here, applied to every slot:

* ``success=false`` means **the bridge could not do its job** -- no user
  database, no app-data directory, malformed JSON, an unexpected exception.
  There is nothing for the student to act on and nothing to branch on.
* A **named** speech-to-text failure is a successful response carrying
  ``error: {kind, detail, retryable}`` in its data. The page renders it.

``kind`` is an ``SttErrorKind`` value; ``retryable`` is the taxonomy's own
answer to "is a retry button honest here", so no page has to re-derive it.

Threading, which is the contract and not an implementation detail
-----------------------------------------------------------------

Recording is Qt object lifecycle and stays on the **Qt main thread** --
``AudioRecorder`` is constructed, started and stopped inside these slots,
which Qt invokes on that thread. Only two things leave it:

* ``subprocess.run`` against a WAV already on disk, through
  ``TranscriptionJobs`` (``max_workers=1``); and
* the model download, through this mixin's own single-worker executor.

Both workers touch **no Qt object and no database connection** (§3.4).
``TranscriptionJobs.poll`` runs its finish phase inline on the polling
thread, which is this thread, and that is what makes it safe to touch the
database there and nowhere else.

The staleness contract (§3.5)
-----------------------------

``stopRecording(context_json)`` takes the entry id, the ``field_key``, a
monotonically increasing token and the subject ids for priming.
``pollTranscription`` hands all four back, unmodified, on every terminal
state. The **page** decides whether a transcript is stale; it can only do so
if what it sent comes back, so this file echoes rather than interprets. Under
D1 both dictation targets are *required* fields, so a stale transcript can
corrupt a required field on a different entry -- carrying the context
faithfully is the only thing standing in the way.

Plan: ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §3.4, §3.5,
§3.6, §3.8, §7 and task T11.
"""

import json
import logging
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import pyqtSlot

from app.bridge_test_instrumentation import instrumented_slot
from app.stt.errors import SttError, SttErrorKind

from ..bridge_helpers import serialize_response

logger = logging.getLogger(__name__)

#: The settings this feature owns, and the only keys ``updateSttSettings``
#: accepts. Two are user-level and two are device-local; the routing is
#: ``UserDatabase.update_settings``' job and is deliberately not restated
#: here (``src/database/device_local.py`` is the one definition).
STT_SETTING_FIELDS = (
    'stt_priming_enabled',
    'stt_show_first_use_notice',
    'stt_model_size',
    'stt_input_device_id',
)

#: Where a recording is parked between ``stopRecording`` and the worker.
#: The system temp directory rather than ``app_data/``: the file lives for
#: seconds, ``WhisperRuntime.transcribe`` deletes it in a ``finally``, and a
#: recording of the student's voice should not accumulate anywhere a backup
#: tool would sweep it up.
RECORDING_DIR_NAME = 'wimi-stt'

#: Caps on how much of the subject tree priming is allowed to walk. 223
#: tokens is roughly 150-200 words, so these are far above what can survive
#: the budget; they exist so a deeply-shared subject cannot turn one
#: ``stopRecording`` into thousands of queries on the Qt main thread.
_MAX_ENTRY_SUBJECTS = 8
_MAX_ANCESTORS = 24
_MAX_SIBLINGS = 40
_MAX_FREQUENT = 20

_DOWNLOAD_THREAD_PREFIX = 'wimi-stt-download'


class SttBridgeMixin:
    """Bridge mixin for speech to text. Composed into DatabaseBridge."""

    # ==================================================================
    # Helpers (not slots)
    # ==================================================================

    def _stt_app_data_dir(self) -> Optional[Path]:
        """This installation's ``app_data/``, or ``None``.

        Read off the master database, which is where ``main.py`` put it.
        ``None`` is a real state -- a bridge constructed without one in a
        test -- and the slots that need a path say so rather than
        defaulting to the working directory and creating ``./models/``.
        """
        base = getattr(self.master_db, 'data_dir', None) if self.master_db else None
        return Path(base) if base else None

    def _stt_settings(self) -> Dict[str, Any]:
        """The four stored values, with their defaults filled in.

        Resolved at call time from ``self.user_db``, never captured: the
        database is swapped on profile switch, and the profile picker runs
        before there is one at all. With no profile open this is the
        defaults, which is what a page asking "can I dictate?" before a
        profile loads should see.
        """
        values = {
            'stt_priming_enabled': True,
            'stt_show_first_use_notice': True,
            'stt_model_size': None,
            'stt_input_device_id': None,
        }
        db = self.user_db
        if db is None:
            return values
        try:
            stored = db.get_all_settings() or {}
        except Exception as e:  # noqa: BLE001 - a settings read must not break status
            self._log_error(f'stt: could not read settings: {e}')
            return values
        for field in STT_SETTING_FIELDS:
            if field in stored:
                values[field] = stored[field]
        values['stt_priming_enabled'] = bool(values['stt_priming_enabled'])
        values['stt_show_first_use_notice'] = bool(values['stt_show_first_use_notice'])
        return values

    def _stt_model_size(self) -> str:
        """The size that will actually be used.

        The stored value when this machine has chosen one, else the pin
        table's default. ``device_settings.stt_model_size`` defaults to
        ``None`` precisely so that the default lives in one place
        (``model_spec.DEFAULT_MODEL_SIZE``) rather than being restated
        here as a second answer.
        """
        stored = self._stt_settings().get('stt_model_size')
        if stored:
            return str(stored)
        from app.stt.runtime import default_model_size
        return default_model_size()

    def _stt_runtime(self):
        """A ``WhisperRuntime`` pointed at the current app data and model.

        Rebuilt whenever either changes. A fresh **instance** rather than a
        mutated one is load-bearing: ``TranscriptionJobs.start`` submits
        ``self.runtime.transcribe`` as a *bound method*, so a job already in
        flight keeps the runtime it was started with and a model-size change
        mid-transcription cannot swap the model out from under the worker.
        """
        app_data = self._stt_app_data_dir()
        if app_data is None:
            return None
        size = self._stt_model_size()
        key = (str(app_data), size)
        if getattr(self, '_stt_runtime_key', None) == key:
            return self._stt_runtime_obj
        from app.stt.runtime import WhisperRuntime
        runtime = WhisperRuntime(app_data_dir=app_data, model_size=size)
        self._stt_runtime_key = key
        self._stt_runtime_obj = runtime
        return runtime

    def _stt_jobs(self):
        """The single-worker transcription executor, built on first use.

        A plain attribute so a test can inject a fake, the way the browser
        pane controller is. ``None`` when there is no app-data directory to
        resolve a model against.

        The re-point applies **only to the executor this built**. An
        injected one is left exactly as it was handed over -- otherwise the
        seam would quietly replace the fake runtime a test had just put
        there, which is a seam that does not work.
        """
        runtime = self._stt_runtime()
        if runtime is None:
            return None
        jobs = getattr(self, '_stt_jobs_obj', None)
        if jobs is None:
            from app.stt.jobs import TranscriptionJobs
            jobs = TranscriptionJobs(runtime=runtime)
            self._stt_jobs_obj = jobs
            self._stt_jobs_owned = True
        elif getattr(self, '_stt_jobs_owned', False):
            # Re-point at the current runtime. See _stt_runtime: jobs already
            # submitted hold the previous one through their bound method.
            jobs.runtime = runtime
        return jobs

    def _stt_recorder_obj(self):
        return getattr(self, '_stt_recorder', None)

    def _stt_microphone_state(self) -> Dict[str, Any]:
        """What the microphone can do right now, in the order §7 requires.

        Never raises. Qt's multimedia stack warns and returns an empty list
        when there is no ``QCoreApplication`` (a bridge unit test), and an
        empty list is the honest answer there -- it is also exactly what a
        machine with no microphone reports, which T2 measured and §0.1
        records as indistinguishable at runtime.
        """
        state: Dict[str, Any] = {
            'permission': 'undetermined',
            'devices': [],
            'ready': False,
            'error': None,
        }
        try:
            from app.stt.recorder import check_permission, list_input_devices
            devices = list_input_devices()
            state['devices'] = [
                {'id': d.id, 'label': d.label, 'is_default': d.is_default}
                for d in devices if not d.is_null
            ]
            state['permission'] = check_permission().value
        except Exception as e:  # noqa: BLE001 - status must always answer
            self._log_error(f'stt: could not read microphone state: {e}')
            state['error'] = SttError(
                SttErrorKind.CAPTURE_FAILED, str(e)
            ).to_dict()
            return state

        if not state['devices']:
            state['error'] = SttError(
                SttErrorKind.NO_INPUT_DEVICE, 'no audio input devices'
            ).to_dict()
        elif state['permission'] == 'denied':
            state['error'] = SttError(
                SttErrorKind.PERMISSION_DENIED, 'microphone permission denied'
            ).to_dict()
        else:
            state['ready'] = True
        return state

    # -- priming -------------------------------------------------------

    def _stt_aliases(self, node_id: int, memo: Dict[int, List[str]]) -> List[str]:
        if node_id in memo:
            return memo[node_id]
        try:
            names = [
                a.alias_name
                for a in self.user_db.get_aliases_for_subject(node_id)
                if getattr(a, 'alias_name', '')
            ]
        except Exception:  # noqa: BLE001 - an alias is a bonus, never a blocker
            names = []
        memo[node_id] = names
        return names

    def _stt_priming_prompt(self, context: Dict[str, Any]) -> str:
        """The ``--prompt`` string for this recording, or ``''``.

        ``''`` means *pass no ``--prompt`` at all* -- that is
        ``build_priming_prompt``'s documented contract, and
        ``WhisperRuntime.build_argv`` honours it by omitting the flag.

        Built at transcription time rather than page load (§3.6): the
        subject selection changes while the student works, and the prompt
        should describe what they are about to say.

        **Never raises.** Priming is an optimisation; a failure to walk the
        subject tree costs the prompt, not the transcript.
        """
        db = self.user_db
        if db is None:
            return ''
        if not self._stt_settings().get('stt_priming_enabled', True):
            return ''
        try:
            return self._build_priming_prompt(context)
        except Exception as e:  # noqa: BLE001 - see docstring
            self._log_error(f'stt: priming failed, continuing unprimed: {e}')
            return ''

    def _build_priming_prompt(self, context: Dict[str, Any]) -> str:
        from app.stt.priming import build_priming_prompt, select_priming_terms

        db = self.user_db
        memo: Dict[int, List[str]] = {}

        raw_ids = context.get('subject_ids') or []
        subject_ids: List[int] = []
        for value in raw_ids:
            try:
                subject_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        subject_ids = subject_ids[:_MAX_ENTRY_SUBJECTS]

        def row(node_id: int, name: str) -> Dict[str, Any]:
            return {'name': name, 'aliases': self._stt_aliases(node_id, memo)}

        entry_subjects: List[Dict[str, Any]] = []
        ancestors: List[Dict[str, Any]] = []
        siblings: List[Dict[str, Any]] = []
        seen = set(subject_ids)

        for node_id in subject_ids:
            node = db.get_subject_node(node_id)
            if node is not None and getattr(node, 'name', ''):
                entry_subjects.append(row(node_id, node.name))

        for node_id in subject_ids:
            for path in db.get_paths_to_root(node_id):
                for ancestor_id in path:
                    if ancestor_id in seen or len(ancestors) >= _MAX_ANCESTORS:
                        continue
                    seen.add(ancestor_id)
                    ancestor = db.get_subject_node(ancestor_id)
                    if ancestor is not None and getattr(ancestor, 'name', ''):
                        ancestors.append(row(ancestor_id, ancestor.name))

        for node_id in subject_ids:
            for parent in db.get_parents(node_id):
                for edge in db.get_sibling_edges(parent.parent_id):
                    child_id = edge['child_id']
                    if child_id in seen or len(siblings) >= _MAX_SIBLINGS:
                        continue
                    seen.add(child_id)
                    if edge.get('child_name'):
                        siblings.append(row(child_id, edge['child_name']))

        frequent: List[Dict[str, Any]] = []
        exam_context_id = context.get('exam_context_id')
        if not entry_subjects and exam_context_id:
            # The fallback tier (§3.6.4): an entry with nothing tagged yet
            # still deserves a prompt, so use the exam's most-mistaken
            # subjects. Only when nothing is tagged -- when something is,
            # the tiers above already describe what is about to be said.
            try:
                rows = db.get_subject_analytics(
                    exam_context_id=int(exam_context_id), limit=_MAX_FREQUENT
                )
            except Exception:  # noqa: BLE001 - the fallback tier is a bonus
                rows = []
            for entry in rows:
                node_id = entry.get('subject_id')
                name = entry.get('subject_name')
                if not name or node_id in seen:
                    continue
                seen.add(node_id)
                frequent.append(row(node_id, name))

        terms = select_priming_terms(
            entry_subjects=entry_subjects,
            ancestors=ancestors,
            siblings=siblings,
            frequent_subjects=frequent,
        )
        return build_priming_prompt(terms)

    # -- context -------------------------------------------------------

    @staticmethod
    def _stt_context(raw: Dict[str, Any]) -> Dict[str, Any]:
        """The four staleness fields, echoed rather than interpreted.

        ``entry_id``, ``field_key`` and ``token`` come back on every poll so
        the page can compare them with what it is still looking at (§3.5).
        They are **not** validated against a list of known field keys: the
        page's comparison is the check, and a bridge that rejected an
        unfamiliar key would be a second policy free to disagree with it.
        """
        context = {
            'entry_id': raw.get('entry_id'),
            'field_key': raw.get('field_key'),
            'token': raw.get('token'),
            'subject_ids': list(raw.get('subject_ids') or []),
        }
        if raw.get('exam_context_id') is not None:
            context['exam_context_id'] = raw.get('exam_context_id')
        return context

    @staticmethod
    def _stt_failure(error: SttError, **extra) -> str:
        """A named failure as *data*. See the module docstring."""
        payload = {'error': error.to_dict()}
        payload.update(extra)
        return serialize_response(True, data=payload)

    # -- downloads -----------------------------------------------------

    def _stt_download_pool(self) -> ThreadPoolExecutor:
        pool = getattr(self, '_stt_download_pool_obj', None)
        if pool is None:
            pool = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=_DOWNLOAD_THREAD_PREFIX
            )
            self._stt_download_pool_obj = pool
        return pool

    def _stt_downloads(self) -> Dict[str, Dict[str, Any]]:
        downloads = getattr(self, '_stt_download_jobs', None)
        if downloads is None:
            downloads = {}
            self._stt_download_jobs = downloads
        return downloads

    def shutdown_stt(self) -> None:
        """Stop the workers. Safe to call more than once, and never raises.

        Not wired into ``MainWindow`` -- folder sync's executor is not
        either, and the process exiting is what stops both today. It exists
        so a host that does want an orderly teardown has one call to make,
        and so a test can reclaim the threads.
        """
        jobs = getattr(self, '_stt_jobs_obj', None)
        if jobs is not None:
            try:
                jobs.shutdown()
            except Exception as e:  # noqa: BLE001
                logger.warning('stt: transcription shutdown failed: %s', e)
            self._stt_jobs_obj = None
            self._stt_jobs_owned = False
        for record in self._stt_downloads().values():
            cancel = record.get('cancel')
            if cancel is not None:
                cancel.set()
        pool = getattr(self, '_stt_download_pool_obj', None)
        if pool is not None:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception as e:  # noqa: BLE001
                logger.warning('stt: download shutdown failed: %s', e)
            self._stt_download_pool_obj = None
        recorder = self._stt_recorder_obj()
        if recorder is not None:
            try:
                recorder.abort()
            except Exception as e:  # noqa: BLE001
                logger.warning('stt: recorder abort failed: %s', e)
            self._stt_recorder = None

    def _stt_status_without_app_data(self, microphone: Dict[str, Any]) -> Dict[str, Any]:
        """The status payload when no model can be resolved.

        The **engine** is still answered honestly: the binary is bundled
        with the build and its location has nothing to do with
        ``app_data/``, so "we cannot find your model" must not be reported
        as "this build has no speech engine". They have different fixes.
        """
        from app.stt.runtime import binary_path, find_binary
        found = find_binary()
        return {
            'engine_ready': found is not None,
            'model_ready': False,
            'engine': {
                'ready': found is not None,
                'path': str(found or binary_path()),
                'error': None if found is not None else SttError(
                    SttErrorKind.BINARY_MISSING, str(binary_path())
                ).to_dict(),
            },
            'model': {
                'ready': False,
                'installed': False,
                'error': SttError(
                    SttErrorKind.MODEL_MISSING,
                    'no app data directory; no master database is attached',
                ).to_dict(),
            },
            'mic': microphone,
            'microphone_ready': microphone['ready'],
        }

    # ==================================================================
    # Status
    # ==================================================================

    @pyqtSlot(result=str)
    @instrumented_slot
    def getSttStatus(self) -> str:
        """The three independent states, never one ``available`` boolean.

        The engine, the model and the microphone fail for different reasons
        with different fixes, and collapsing them is how a student ends up
        with a greyed button and no idea which of three problems they have
        (§3.8, §7).

        Returns:
            JSON response with ``{engine_ready, model_ready, model_size,
            engine, model, mic: {permission, devices, ready, error},
            priming_enabled, show_first_use_notice, recording}``.
            ``mic.permission`` is ``granted`` / ``denied`` / ``undetermined``
            -- and is **expected to be ``granted`` on Windows regardless of
            what the OS thinks**, because Qt has no Windows backend (§0.1).

            Answers with ``user_db=None``: the settings fall back to their
            defaults and the model size to the pin table's.
        """
        try:
            settings = self._stt_settings()
            microphone = self._stt_microphone_state()
            runtime = self._stt_runtime()
            if runtime is None:
                data = self._stt_status_without_app_data(microphone)
            else:
                try:
                    data = runtime.availability(microphone=microphone).to_dict()
                except Exception as e:  # noqa: BLE001 - see below
                    # A stored ``stt_model_size`` naming a size the pin table
                    # no longer has reaches here as a KeyError rather than an
                    # SttError. It is a real problem and it belongs on the
                    # model line, not as a failed status call that tells the
                    # page nothing about the microphone or the engine.
                    self._log_error(f'stt: model resolution failed: {e}')
                    data = self._stt_status_without_app_data(microphone)
                    data['model']['error'] = SttError(
                        SttErrorKind.MODEL_MISSING, str(e)
                    ).to_dict()

            data['model_size'] = self._stt_model_size()
            data['priming_enabled'] = settings['stt_priming_enabled']
            data['show_first_use_notice'] = settings['stt_show_first_use_notice']
            recorder = self._stt_recorder_obj()
            data['recording'] = bool(recorder is not None and recorder.is_recording)
            return serialize_response(True, data=data)
        except Exception as e:
            self._log_error(f'getSttStatus failed: {e}')
            return serialize_response(False, error=f'Failed to read speech status: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def requestMicrophonePermission(self) -> str:
        """Ask the OS for microphone access and report where that landed.

        Meaningful on macOS, where TCC prompts once and remembers the answer
        system-wide -- which is also why a "try again" button is a lie there
        once the answer is no. On Windows and Linux Qt has no backend and
        resolves ``granted`` without asking anyone.

        Qt's request is callback-shaped and may not resolve inside this
        call. When it does not, the answer is the *current* state with
        ``pending: true`` beside it, rather than a guess in either
        direction.

        Returns:
            JSON response with ``{permission, pending}``.
        """
        try:
            from app.stt.recorder import check_permission, request_permission

            landed: List[str] = []
            request_permission(lambda state: landed.append(state.value))
            if landed:
                return serialize_response(
                    True, data={'permission': landed[-1], 'pending': False}
                )
            return serialize_response(
                True, data={'permission': check_permission().value, 'pending': True}
            )
        except Exception as e:
            self._log_error(f'requestMicrophonePermission failed: {e}')
            return serialize_response(
                False, error=f'Failed to request microphone permission: {e}'
            )

    # ==================================================================
    # Recording -- main thread only
    # ==================================================================

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def startRecording(self, device_id: str) -> str:
        """Open the microphone and begin writing a WAV.

        Runs on the Qt main thread and stays there: ``AudioRecorder`` is Qt
        object lifecycle, and only the transcription that follows it goes to
        a worker (§3.4).

        Args:
            device_id: a ``QAudioDevice`` id, or ``''`` to use this
                machine's stored ``stt_input_device_id`` and fall back to
                the system default.

        Returns:
            JSON response with ``{recording: true, device, format,
            device_choice_honoured}``, or -- for a named capture failure --
            ``{recording: false, error: {kind, detail, retryable}}`` with
            ``success=true``. See the module docstring for why the second
            one is not a failed response.
        """
        try:
            from app.stt.recorder import AudioRecorder
        except Exception as e:
            self._log_error(f'startRecording could not load the recorder: {e}')
            return serialize_response(False, error=f'Audio capture unavailable: {e}')

        existing = self._stt_recorder_obj()
        if existing is not None and existing.is_recording:
            return self._stt_failure(
                SttError(SttErrorKind.CAPTURE_FAILED, 'a recording is already running'),
                recording=True,
            )

        preferred = str(device_id or '') or self._stt_settings().get(
            'stt_input_device_id'
        )
        try:
            recorder = AudioRecorder(preferred_device_id=preferred or None)
            recorder.levelChanged.connect(self._on_stt_level)
            recorder.errorOccurred.connect(self._on_stt_capture_error)
        except Exception as e:
            self._log_error(f'startRecording could not build a recorder: {e}')
            return serialize_response(False, error=f'Audio capture unavailable: {e}')

        directory = Path(tempfile.gettempdir()) / RECORDING_DIR_NAME
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._log_error(f'startRecording could not create {directory}: {e}')
            return self._stt_failure(
                SttError(SttErrorKind.CAPTURE_FAILED, f'cannot write {directory}: {e}'),
                recording=False,
            )
        path = directory / f'{uuid.uuid4().hex}.wav'

        # Drop the finished recorder before trying, so a refused start
        # leaves nothing behind for cancelRecording to abort a second time.
        self._stt_recorder = None
        self._stt_recording_path = None
        self._stt_level = {'rms': 0.0, 'peak': 0.0}
        self._stt_stream_error = None
        try:
            capture_format = recorder.start(path)
        except SttError as e:
            logger.info('stt: recording refused (%s): %s', e.kind.value, e.detail)
            return self._stt_failure(e, recording=False)
        except Exception as e:
            self._log_error(f'startRecording failed: {e}')
            return serialize_response(False, error=f'Failed to start recording: {e}')

        self._stt_recorder = recorder
        self._stt_recording_path = path
        device = recorder.device
        return serialize_response(True, data={
            'recording': True,
            'error': None,
            'device': None if device is None else {
                'id': device.id, 'label': device.label, 'is_default': device.is_default,
            },
            'device_choice_honoured': recorder.device_choice_honoured,
            'format': {
                'sample_rate': capture_format.sample_rate,
                'channels': capture_format.channels,
                'degraded': capture_format.degraded,
            },
        })

    def _on_stt_level(self, rms: float, peak: float) -> None:
        """Latest level, for the meter. Plain attribute, polled not pushed.

        ``getRecordingLevel`` reads this. A Qt signal injected into the page
        would land in the wrong JavaScript world for a scenario to see
        (``TEST_INFRASTRUCTURE.md`` §12a), and the page is already polling
        the transcription job, so a poll costs nothing new.
        """
        self._stt_level = {'rms': float(rms), 'peak': float(peak)}

    def _on_stt_capture_error(self, kind: str, detail: str) -> None:
        """A mid-stream failure. Recorded, not raised: whatever already
        reached the file is kept (§7 -- do not discard the student's first
        sentence to report a problem with their second)."""
        self._stt_stream_error = {'kind': kind, 'detail': detail}
        logger.warning('stt: capture error mid-stream (%s): %s', kind, detail)

    @pyqtSlot(result=str)
    @instrumented_slot
    def getRecordingLevel(self) -> str:
        """The most recent microphone level, for the live meter.

        ``{rms, peak}`` normalised 0.0-1.0, updated roughly every 100 ms of
        audio while recording. The meter is not decoration: §7 makes it one
        of the two detectors for the silent-capture path, because it is the
        only one that tells the student *while they are still speaking*.

        Returns:
            JSON response with ``{recording, rms, peak, stream_error}``.
        """
        try:
            recorder = self._stt_recorder_obj()
            level = getattr(self, '_stt_level', None) or {'rms': 0.0, 'peak': 0.0}
            return serialize_response(True, data={
                'recording': bool(recorder is not None and recorder.is_recording),
                'rms': level['rms'],
                'peak': level['peak'],
                'stream_error': getattr(self, '_stt_stream_error', None),
            })
        except Exception as e:
            self._log_error(f'getRecordingLevel failed: {e}')
            return serialize_response(False, error=f'Failed to read level: {e}')

    @pyqtSlot(result=str)
    @instrumented_slot
    def cancelRecording(self) -> str:
        """Discard the recording in progress.

        Nothing was transcribed, so nothing is queued; the WAV is deleted by
        ``AudioRecorder.abort``. Idempotent -- cancelling when nothing is
        recording is a success, because the page may cancel on navigation
        without knowing.

        Returns:
            JSON response with ``{recording: false, cancelled}``.
        """
        recorder = self._stt_recorder_obj()
        if recorder is None:
            return serialize_response(
                True, data={'recording': False, 'cancelled': False})
        try:
            was_recording = recorder.is_recording
            recorder.abort()
            self._stt_recorder = None
            self._stt_recording_path = None
            self._stt_level = {'rms': 0.0, 'peak': 0.0}
            return serialize_response(
                True, data={'recording': False, 'cancelled': was_recording})
        except Exception as e:
            self._log_error(f'cancelRecording failed: {e}')
            return serialize_response(False, error=f'Failed to cancel recording: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def stopRecording(self, context_json: str) -> str:
        """Stop the microphone and queue the transcription.

        Args:
            context_json: JSON object carrying the four staleness fields --
                ``entry_id``, ``field_key`` (``'reflection'`` /
                ``'explanation'``), ``token`` (monotonically increasing) and
                ``subject_ids`` (for vocabulary priming) -- plus an optional
                ``exam_context_id``, which is what lets priming fall back to
                the exam's most-mistaken subjects when nothing is tagged
                yet. All of them come back on every ``pollTranscription``.

        Returns:
            JSON response with ``{job_id, context, primed, capture}``, or --
            for a named capture failure such as ``no_audio_captured`` --
            ``{job_id: null, error: {kind, detail, retryable}, context}``
            with ``success=true``.

        The prompt is built **here**, on this thread, because it reads the
        subject tree and the worker may not touch the database (§3.4). It is
        built now rather than at page load because the subject selection
        changes while the student works (§3.6).
        """
        try:
            raw = json.loads(context_json) if context_json else {}
            if not isinstance(raw, dict):
                raise ValueError('context must be a JSON object')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid recording context: {e}')

        context = self._stt_context(raw)

        recorder = self._stt_recorder_obj()
        if recorder is None or not recorder.is_recording:
            return self._stt_failure(
                SttError(SttErrorKind.CAPTURE_FAILED, 'no recording in progress'),
                job_id=None, context=context,
            )

        path = getattr(self, '_stt_recording_path', None)
        try:
            recording = recorder.stop()
        except SttError as e:
            # stop() leaves the WAV on disk whatever happens, and on this
            # path nothing will ever read it -- so it is deleted here rather
            # than left for a temp sweep that may never come.
            self._stt_discard_recording(path)
            logger.info('stt: capture rejected (%s): %s', e.kind.value, e.detail)
            return self._stt_failure(e, job_id=None, context=context)
        except Exception as e:
            self._stt_discard_recording(path)
            self._log_error(f'stopRecording failed: {e}')
            return serialize_response(False, error=f'Failed to stop recording: {e}')
        finally:
            self._stt_recorder = None
            self._stt_recording_path = None

        jobs = self._stt_jobs()
        if jobs is None:
            self._stt_discard_recording(recording.path)
            return serialize_response(
                False, error='Speech to text is not available: no app data directory')

        # Drop the job before this one, now that nothing can still be
        # polling it. Doing it here rather than in ``pollTranscription``
        # keeps a repeat poll of a finished job answerable.
        previous = getattr(self, '_stt_last_job_id', None)
        if previous:
            jobs.forget(previous)

        prompt = self._stt_priming_prompt(context)
        try:
            job_id = jobs.start(
                recording.path, prompt=prompt, context=context, delete_audio=True
            )
        except Exception as e:
            self._stt_discard_recording(recording.path)
            self._log_error(f'stopRecording could not queue a transcription: {e}')
            return serialize_response(False, error=f'Failed to queue transcription: {e}')

        self._stt_last_job_id = job_id
        return serialize_response(True, data={
            'job_id': job_id,
            'error': None,
            'context': context,
            'primed': bool(prompt),
            'capture': {
                'seconds': round(recording.duration_seconds, 2),
                'peak': recording.peak,
                'rms': recording.rms,
                'degraded_format': recording.degraded_format,
                # A stream that failed part-way still transcribes what
                # arrived; the page gets to say so beside the transcript.
                'capture_error': (
                    None if recording.capture_error is None
                    else recording.capture_error.to_dict()
                ),
            },
        })

    def _stt_discard_recording(self, path: Optional[Path]) -> None:
        if path is None:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as e:
            logger.warning('stt: could not remove %s: %s', path, e)

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def pollTranscription(self, job_id: str) -> str:
        """Where a transcription has got to.

        The finish phase runs **inside this call, on this thread**, which is
        the Qt main thread -- that is the point of the whole arrangement and
        the one place a transcription job may touch the database (§3.4).

        Returns:
            JSON response with ``{state: 'running'}``, or ``{state: 'done',
            text, ms, entry_id, field_key, token, context}``, or
            ``{state: 'failed', error: {kind, detail, retryable}, code,
            message, entry_id, field_key, token, context}``.

            ``state`` uses ``jobs.py``'s vocabulary -- ``running`` / ``done``
            / ``failed``, the same three strings as folder sync. T11's task
            entry says ``'error'`` for the third; ``code`` and ``message``
            are carried alongside ``error`` so a page written to either
            reading finds what it expects.

            The four staleness fields are echoed on **every** terminal
            state, done and failed alike: a failure the page cannot place is
            a failure it cannot report next to the right field (§3.5).
        """
        jobs = self._stt_jobs()
        if jobs is None:
            return serialize_response(
                False, error='Speech to text is not available: no app data directory')
        try:
            report = jobs.poll(str(job_id))
        except Exception as e:
            self._log_error(f'pollTranscription failed: {e}', {'job_id': job_id})
            return serialize_response(False, error=f'Failed to poll transcription: {e}')

        state = report.get('state')
        context = dict(report.get('context') or {})
        data: Dict[str, Any] = {'state': state, 'context': context}
        for field in ('entry_id', 'field_key', 'token'):
            data[field] = context.get(field)

        if state == 'done':
            data['text'] = report.get('text', '')
            data['ms'] = report.get('ms')
            if 'result' in report:
                data['result'] = report['result']
        elif state == 'failed':
            error = report.get('error') or SttError(
                SttErrorKind.TRANSCRIPTION_FAILED, 'the job reported no reason'
            ).to_dict()
            data['error'] = error
            data['code'] = error.get('kind')
            data['message'] = error.get('detail')

        # **Not forgotten here.** ``jobs.poll`` is deliberately repeatable --
        # its docstring says the page may well poll once more before it
        # notices the first result -- and forgetting on the first terminal
        # read would turn that second poll into ``unknown_job``, which the
        # page would render as a failure it cannot place. The previous job
        # is dropped when the next recording starts instead.
        return serialize_response(True, data=data)

    # ==================================================================
    # The first-run model download (D2, §3.8)
    # ==================================================================

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def startModelDownload(self, size: str) -> str:
        """Fetch the pinned weights for ``size`` on a worker thread.

        "No model yet" is **not** a failure (§7): it is the first-run
        resting state, and this is the button the student presses from it.

        Args:
            size: a model size from the pin table, or ``''`` for whatever
                this machine has chosen and, failing that, the default.

        Returns:
            JSON response with ``{job_id, size, filename, total_bytes}``.
            Poll ``pollModelDownload``.
        """
        app_data = self._stt_app_data_dir()
        if app_data is None:
            return serialize_response(
                False, error='Speech to text is not available: no app data directory')

        try:
            from app.stt.download import download_model
            from app.stt.model_spec import get_spec
            spec = get_spec(str(size) or self._stt_model_size())
        except Exception as e:
            self._log_error(f'startModelDownload failed to resolve {size!r}: {e}')
            return serialize_response(False, error=f'Unknown speech model: {e}')

        job_id = uuid.uuid4().hex
        cancel = threading.Event()
        record: Dict[str, Any] = {
            'state': 'running',
            'bytes': 0,
            # ``total`` really can stay None -- a response without
            # Content-Length is legal, and a page that divides by it breaks.
            'total': spec.size_bytes,
            'size': spec.size,
            'cancel': cancel,
            'error': None,
            'path': None,
        }
        lock = threading.Lock()
        record['lock'] = lock

        def progress(done: int, total: Optional[int]) -> None:
            with lock:
                record['bytes'] = done
                if total:
                    record['total'] = total

        def run() -> None:
            try:
                path = download_model(
                    app_data, spec.size, progress=progress, cancel=cancel
                )
            except SttError as exc:
                with lock:
                    record['state'] = 'failed'
                    record['error'] = exc.to_dict()
                logger.info('stt: model download %s failed: %s', job_id, exc)
                return
            except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
                with lock:
                    record['state'] = 'failed'
                    record['error'] = SttError(
                        SttErrorKind.DOWNLOAD_FAILED,
                        str(exc) or exc.__class__.__name__,
                    ).to_dict()
                logger.exception('stt: model download %s raised', job_id)
                return
            with lock:
                record['state'] = 'done'
                record['path'] = str(path)

        downloads = self._stt_downloads()
        for done_id in [
            key for key, value in downloads.items() if value['state'] != 'running'
        ]:
            downloads.pop(done_id, None)
        downloads[job_id] = record
        try:
            self._stt_download_pool().submit(run)
        except Exception as e:
            self._stt_downloads().pop(job_id, None)
            self._log_error(f'startModelDownload could not queue {spec.size}: {e}')
            return serialize_response(False, error=f'Failed to start download: {e}')

        # A new download means the runtime's cached verdict on the old file
        # is about to be wrong. Forget it now rather than when it bites.
        try:
            from app.stt.runtime import clear_verification_cache
            clear_verification_cache()
        except Exception:  # noqa: BLE001 - a cache is not worth failing over
            pass

        return serialize_response(True, data={
            'job_id': job_id,
            'size': spec.size,
            'filename': spec.filename,
            'total_bytes': spec.size_bytes,
        })

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def pollModelDownload(self, job_id: str) -> str:
        """Where a download has got to.

        **``job_id`` is echoed back on every branch, and that is the whole
        of the fix for #171.** ``api.downloadSttModel`` starts the job
        itself and keeps the id in a local, so a page that uses the
        composite sees only what this slot returns; without the id in here
        there was no argument to hand ``cancelModelDownload`` and a
        download could only be waited out, which §3.8 forbids. It is
        echoed on the ``unknown_job`` branch too -- a payload saying a job
        is unknown without saying *which* job is the least traceable of
        the lot, and the second reason to do it this way is that a poll
        line in a log now identifies itself.

        Returns:
            JSON response with ``{job_id, state: 'running', bytes, total,
            size}``, ``{job_id, state: 'done', path, size}``, or
            ``{job_id, state: 'failed', error, code, message}``. ``total``
            may be ``null`` -- the server is not obliged to say how big the
            body is, and a page that treats it as a number will divide by
            it.
        """
        record = self._stt_downloads().get(str(job_id))
        if record is None:
            return serialize_response(True, data={
                'job_id': str(job_id),
                'state': 'failed',
                'error': SttError(
                    SttErrorKind.UNKNOWN_JOB, f'no such download job: {job_id}'
                ).to_dict(),
                'code': SttErrorKind.UNKNOWN_JOB.value,
                'message': f'no such download job: {job_id}',
            })
        with record['lock']:
            state = record['state']
            data: Dict[str, Any] = {
                'job_id': str(job_id),
                'state': state,
                'bytes': record['bytes'],
                'total': record['total'],
                'size': record['size'],
            }
            if state == 'done':
                data['path'] = record['path']
            elif state == 'failed':
                error = record['error'] or {}
                data['error'] = error
                data['code'] = error.get('kind')
                data['message'] = error.get('detail')
        # Kept, for the same reason a finished transcription is kept: a page
        # that polls once more must get its answer, not ``unknown_job``. The
        # previous download is dropped when the next one starts.
        return serialize_response(True, data=data)

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def cancelModelDownload(self, job_id: str) -> str:
        """Stop a download and remove its ``.part`` file.

        The ``.part`` goes because a cancel is a decision not to have the
        model, and leaving a partial file behind would make the next attempt
        resume something the student said no to. ``download.py`` closes the
        handle before unlinking, which is the difference between this
        working and not working on Windows.

        Returns:
            JSON response with ``{cancelled}``. Poll once more to see the
            job reach ``failed`` with ``download_cancelled``.
        """
        record = self._stt_downloads().get(str(job_id))
        if record is None:
            return serialize_response(True, data={'cancelled': False})
        try:
            record['cancel'].set()
            return serialize_response(True, data={'cancelled': True})
        except Exception as e:
            self._log_error(f'cancelModelDownload failed: {e}', {'job_id': job_id})
            return serialize_response(False, error=f'Failed to cancel download: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def removeSttModel(self, size: str) -> str:
        """Delete one downloaded model from this machine.

        Changing size **downloads the new model and leaves the old one
        alone** (T14): a student who switches, dislikes it and switches back
        should not pay for the download twice. The cost of that decision is
        that models accumulate, ~190 MB at a time, with nothing to undo it --
        so removal is offered explicitly instead of happening behind a
        settings change.

        The ``.part`` goes with it. A partial file is the same decision:
        keeping one would make the next download resume toward a model the
        student has just said they do not want here.

        No guard on the model currently in use. Removing it is a legitimate
        thing to want -- a student reclaiming the disk -- and after it the
        status line says ``model_missing``, which is the first-run resting
        state and not a failure (§7). The **caller** decides what to offer;
        this slot only refuses a size the pin table does not know, because
        there it cannot tell which file was meant.

        Args:
            size: a model size from the pin table. ``''`` means this
                machine's resolved size, matching every other slot here.

        Returns:
            JSON response with ``{size, removed, path}``. ``removed`` is
            false when there was nothing there, which is a success: the
            student asked for the file to be gone and it is gone.
        """
        app_data = self._stt_app_data_dir()
        if app_data is None:
            return serialize_response(
                False, error='Speech to text is not available: no app data directory')

        try:
            from app.stt import model_spec
            spec = model_spec.get_spec(str(size) or self._stt_model_size())
        except Exception as e:
            self._log_error(f'removeSttModel could not resolve {size!r}: {e}')
            return serialize_response(False, error=f'Unknown speech model: {e}')

        path = model_spec.model_path(app_data, spec.size, create=False)
        try:
            removed = False
            for candidate in (path, model_spec.part_path(path)):
                if candidate.exists():
                    candidate.unlink()
                    removed = removed or candidate == path
        except OSError as e:
            self._log_error(f'removeSttModel failed for {spec.size}: {e}')
            return serialize_response(
                False, error=f'Could not delete {spec.filename}: {e}')

        # The runtime remembers that it verified this file. Forget it now
        # rather than when it bites, exactly as startModelDownload does.
        try:
            from app.stt.runtime import clear_verification_cache
            clear_verification_cache()
        except Exception:  # noqa: BLE001 - a cache is not worth failing over
            pass

        logger.info('stt: removed model %s (%s)', spec.size, removed)
        return serialize_response(True, data={
            'size': spec.size,
            'removed': removed,
            'path': str(path),
        })

    # ==================================================================
    # Settings
    # ==================================================================

    @pyqtSlot(result=str)
    @instrumented_slot
    def getSttSettings(self) -> str:
        """The four stored settings, plus what can be chosen.

        Two are user-level (``stt_priming_enabled``,
        ``stt_show_first_use_notice``) and two device-local
        (``stt_model_size``, ``stt_input_device_id``). The page sees one
        flat object; the routing is the database's job and is not something
        a settings screen has any reason to model.

        Returns:
            JSON response with the four fields, ``resolved_model_size``
            (what will actually be used), ``default_model_size`` and
            ``available_models`` -- each with ``installed``, read from the
            filesystem, because §3.7 keeps no column claiming a model is
            there.

            With ``user_db=None`` the four are their defaults, so a page can
            still render before a profile is open.
        """
        try:
            data: Dict[str, Any] = dict(self._stt_settings())
            data['resolved_model_size'] = self._stt_model_size()
            app_data = self._stt_app_data_dir()

            from app.stt import model_spec
            models = []
            for size in model_spec.MODEL_SIZES:
                spec = model_spec.get_spec(size)
                models.append({
                    'size': spec.size,
                    'filename': spec.filename,
                    'size_bytes': spec.size_bytes,
                    'megabytes': round(spec.megabytes(), 1),
                    'english_only': spec.english_only,
                    'quantisation': spec.quantisation,
                    'licence': spec.licence,
                    'installed': (
                        bool(app_data) and model_spec.is_installed(app_data, spec.size)
                    ),
                })
            data['available_models'] = models
            data['default_model_size'] = model_spec.DEFAULT_MODEL_SIZE
            return serialize_response(True, data=data)
        except Exception as e:
            self._log_error(f'getSttSettings failed: {e}')
            return serialize_response(False, error=f'Failed to read speech settings: {e}')

    @pyqtSlot(str, result=str)
    @instrumented_slot
    def updateSttSettings(self, params_json: str) -> str:
        """Write any of the four settings, routed to the store that owns it.

        An unknown key is **refused by name** rather than dropped. Accepting
        and ignoring a flag is how #138 lost ``--test-mode`` in every frozen
        build for months, and a settings write is the same shape of mistake:
        the caller has no way to tell that nothing happened.

        Args:
            params_json: JSON object with any of ``stt_priming_enabled``,
                ``stt_show_first_use_notice``, ``stt_model_size``,
                ``stt_input_device_id``.

        Returns:
            JSON response shaped exactly like ``getSttSettings``.
        """
        if not self.user_db:
            return serialize_response(False, error='No user database loaded')
        try:
            params = json.loads(params_json) if params_json else {}
            if not isinstance(params, dict):
                raise ValueError('settings must be a JSON object')
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            return serialize_response(False, error=f'Invalid speech settings: {e}')

        unknown = [key for key in params if key not in STT_SETTING_FIELDS]
        if unknown:
            return serialize_response(
                False,
                error=f"Unknown speech setting(s) {', '.join(sorted(unknown))}; "
                      f"expected any of {', '.join(STT_SETTING_FIELDS)}",
            )
        if not params:
            return self.getSttSettings()

        from database.exceptions import ValidationError
        try:
            self.user_db.update_settings(**params)
        except ValidationError as e:
            return serialize_response(False, error=str(e))
        except Exception as e:
            self._log_error(
                f'updateSttSettings failed: {e}', {'fields': sorted(params)}
            )
            return serialize_response(False, error=f'Failed to save speech settings: {e}')

        # The model size decides which weights file the runtime resolves, so
        # a change to it must not be served from the cached runtime.
        self._stt_runtime_key = None
        return self.getSttSettings()
