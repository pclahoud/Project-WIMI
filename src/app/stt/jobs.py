"""Transcription off the Qt main thread, with nothing else moved off it (#59).

This mirrors ``src/app/foldersync/jobs.py`` deliberately and almost line for
line, because the constraint is the same one and it is already written down:
``base_db.py`` records that ``check_same_thread=False`` is set but that
**nothing in this application writes to the database from a second thread**,
and transaction re-entrancy is tracked per connection with a plain counter. A
second feature that quietly drove a database from a worker would break that
invariant in the same silent, intermittent way.

So the split here is by *what is touched*, not by convenience (§3.4):

===============  ==========================  ==============================
phase            thread                      may touch
===============  ==========================  ==============================
``start``        caller's (Qt main)          anything -- it runs inline
``work``         worker                      the audio file and one subprocess
``finish``       caller's (Qt main)          the database, Qt, anything
===============  ==========================  ==============================

``poll`` runs the finish phase **inline on the polling thread**, which is the
Qt main thread, and that is the whole reason a finish phase exists: it is the
one place a transcription job may touch the database. ``WhisperRuntime`` --
the entire body of ``work`` -- imports neither Qt nor ``sqlite3``, and
``tests/app/test_stt_jobs.py`` asserts that statically rather than trusting
anyone to remember.

**One worker, not a pool.** Two concurrent transcriptions would contend for
the same cores and produce two results for one field. ``max_workers=1`` means
a second press queues rather than races, which is also what the student
expects from a single microphone.

The context travels with the job
--------------------------------

``start(..., context=...)`` takes an opaque dict -- the entry id, the field
key, the staleness token, whatever T11 needs -- and ``poll`` hands it back
untouched on the result. The page has to be able to check that the transcript
it just received belongs to the field it is still looking at (§3.5), and the
only way it can is if the thing it sent comes back.

Plan: ``docs/planning/FEYNMAN_CAPTURE_IMPLEMENTATION_PLAN.md`` §3.4, task T6.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .errors import SttError, SttErrorKind
from .runtime import TranscriptionResult, WhisperRuntime

logger = logging.getLogger(__name__)

#: Job lifecycle, with the same three names and the same three strings as
#: folder sync, so the bridge layer does not have to learn a second
#: vocabulary. There is no "cancelled": a transcription that has already
#: started is killed by its own wall-clock ceiling
#: (``runtime.TRANSCRIBE_TIMEOUT_S``) and nothing else can stop it safely.
STATE_RUNNING = 'running'
STATE_DONE = 'done'
STATE_FAILED = 'failed'

#: Thread name prefix, so a stack dump says which feature owns the worker.
THREAD_NAME_PREFIX = 'wimi-stt'


@dataclass
class _Job:
    future: Future
    finish: Callable[[TranscriptionResult], Any]
    context: dict
    #: Kept so ``shutdown`` can clean up after a job that was cancelled
    #: before the worker ever reached ``transcribe``'s ``finally``.
    audio: Optional[Path] = None
    delete_audio: bool = True
    collected: bool = False
    result: Any = None
    error: Optional[dict] = None
    state: str = STATE_RUNNING


@dataclass
class TranscriptionJobs:
    """One worker, a dictionary of jobs, and no Qt anywhere in it.

    Not Qt-aware -- it is an executor and a dictionary -- so it is testable
    without a ``QApplication``, like ``SyncJobs`` and like everything else
    that has to be driven from a bridge slot.
    """

    runtime: WhisperRuntime
    _pool: ThreadPoolExecutor = field(init=False)
    _jobs: Dict[str, _Job] = field(init=False, default_factory=dict)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=THREAD_NAME_PREFIX
        )

    # ------------------------------------------------------------------ start

    def start(
        self,
        audio_path: str | Path,
        *,
        prompt: str = '',
        context: Optional[dict] = None,
        finish: Optional[Callable[[TranscriptionResult], Any]] = None,
        delete_audio: bool = True,
    ) -> str:
        """Queue one transcription and return its id immediately.

        Nothing is validated here beyond what ``runtime`` will check anyway:
        the recording already exists on disk by the time this is called, and
        an input format is explicitly **not** checked (T1 -- whisper.cpp
        resamples whatever it is handed).

        ``finish`` runs on the polling thread when the worker lands. It is the
        seam for anything that must touch the database or a Qt object; leave
        it ``None`` and the transcript passes straight through.
        """
        job_id = uuid.uuid4().hex
        audio = Path(audio_path)
        job = _Job(
            future=self._pool.submit(
                self.runtime.transcribe,
                audio,
                prompt=prompt,
                delete_audio=delete_audio,
            ),
            finish=finish or (lambda result: result),
            context=dict(context or {}),
            audio=audio,
            delete_audio=delete_audio,
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info('queued transcription %s for %s', job_id, audio.name)
        return job_id

    # ------------------------------------------------------------------- poll

    def poll(self, job_id: str) -> Dict[str, Any]:
        """Where the job has got to, running the finish phase on **this** thread.

        Calling it again after completion returns the same answer rather than
        re-running anything: the page may well poll once more before it
        notices the first result.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            # Not an exception: the page polls with an id it was given, and a
            # forgotten or restarted bridge is a state it has to be able to
            # render rather than a crash.
            return {
                'state': STATE_FAILED,
                'error': SttError(
                    SttErrorKind.UNKNOWN_JOB, f'no such transcription job: {job_id}'
                ).to_dict(),
                'context': {},
            }

        if job.collected:
            return self._report(job)
        if not job.future.done():
            return {'state': STATE_RUNNING, 'context': dict(job.context)}

        job.collected = True
        try:
            job.result = job.finish(job.future.result())
            job.state = STATE_DONE
        except SttError as exc:
            job.state = STATE_FAILED
            job.error = exc.to_dict()
            logger.warning('transcription %s failed: %s', job_id, exc)
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            # Anything the taxonomy does not name still has to reach the page
            # as something it can render, so it arrives as the generic kind
            # with the real message in ``detail``.
            job.state = STATE_FAILED
            job.error = SttError(
                SttErrorKind.TRANSCRIPTION_FAILED,
                str(exc) or exc.__class__.__name__,
            ).to_dict()
            logger.exception('transcription %s raised', job_id)
        return self._report(job)

    def forget(self, job_id: str) -> None:
        """Drop a collected job. Uncollected work is left alone."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.collected:
                del self._jobs[job_id]

    def shutdown(self) -> None:
        """Stop accepting work; do not wait for what is already running.

        ``wait=False, cancel_futures=True`` matches ``SyncJobs.shutdown`` and
        matters more here than it looks: this is called from the bridge's
        teardown while the window is closing, and a queued transcription that
        had not started yet must not hold the close for two minutes. A run
        already in flight is a subprocess with its own ceiling; the executor's
        thread is not joined and the process exits around it.

        The one thing it does do is delete the recordings of jobs that never
        ran. ``transcribe`` deletes its input in a ``finally``, but a future
        that was cancelled before it started never reaches that ``finally``,
        and its WAV would otherwise outlive the session that made it.
        """
        self._pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
        for job in jobs:
            if job.collected or not job.delete_audio or job.audio is None:
                continue
            try:
                job.audio.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning('could not remove %s: %s', job.audio, exc)

    # -------------------------------------------------------------- internals

    @staticmethod
    def _report(job: _Job) -> Dict[str, Any]:
        if job.state == STATE_FAILED:
            return {
                'state': STATE_FAILED,
                'error': job.error,
                'context': dict(job.context),
            }
        result = job.result
        payload: Dict[str, Any] = {'state': STATE_DONE, 'context': dict(job.context)}
        if isinstance(result, TranscriptionResult):
            payload['text'] = result.text
            payload['ms'] = result.ms
        else:
            # A ``finish`` that returned something of its own replaces the
            # transcript wholesale; the bridge decides what that means.
            payload['result'] = result
        return payload
