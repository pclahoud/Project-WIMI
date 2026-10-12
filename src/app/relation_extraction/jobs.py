"""Relation extraction off the Qt main thread, with nothing else moved off it (#60).

Mirrors ``src/app/stt/jobs.py``, which mirrors ``src/app/foldersync/jobs.py``,
and for the same reason: ``base_db.py`` records that **nothing in this
application writes to the database from a second thread**, and transaction
re-entrancy is tracked per connection with a plain counter. So the split is by
*what is touched*:

===============  ==========================  ===================================
phase            thread                      may touch
===============  ==========================  ===================================
prepare          caller's (Qt main)          anything -- the bridge reads the
                                             entry's text and the exam's active
                                             relation types, then calls
                                             :meth:`RelationJobs.start`
``start``        caller's (Qt main)          nothing but its arguments; inline
perform          worker                      the model directory and the model.
                                             **No Qt object, no database
                                             connection, not the context.**
``finish``       polling (Qt main)           the database, Qt, anything
===============  ==========================  ===================================

``prepare`` is not a method here: it is whatever the bridge does before
``start``, and ``start`` takes plain data (a string and a tuple of
:class:`~.runtime.RelationLabel`) precisely so that nothing the worker receives
*can* be a connection. ``finish`` is the callable handed to ``start``; ``poll``
runs it **inline on the polling thread**, which is the one place this feature
may touch the database. ``tests/app/test_relation_extraction_jobs.py`` proves
the worker half by handing the job a context and a finish whose every attribute
access raises, and asserts statically that ``runtime.py`` and this module
import neither Qt nor ``sqlite3`` nor ``database``.

This module does not import torch
---------------------------------
:mod:`.runtime` is imported at module scope, and *it* imports torch only inside
the function that builds the model, which runs on the worker. So constructing a
:class:`RelationJobs` on the Qt main thread costs nothing, and the 10+ seconds of
importing torch and gliner2 and loading 845 MB of weights happen on the first
job, off the main thread, where a frozen window cannot result.

One worker, and what "cancellable" can honestly mean
----------------------------------------------------
``max_workers=1``: two passes would contend for the same cores and the same
model, and the runtime serialises them with a lock anyway.

:meth:`RelationJobs.cancel` stops a queued job before it starts, and a running
one **at the next chunk**: the runtime checks the cancel event before each
encoder forward (see :mod:`.runtime`). A pass is one chunk per ~384 words, so on
an ordinary explanation that is the next fraction of a second. The same
mechanism enforces ``EXTRACTION_TIMEOUT``, so one wedged pass releases the
worker within a chunk of its ceiling rather than holding it forever. What
neither can stop is the first model load, which is a single
``from_pretrained`` call; a job cancelled during it reports ``cancelled`` as
soon as the load returns, and the loaded model is kept for the next job.

A call that never returns: the watchdog
---------------------------------------
The chunk checks cannot stop a single native call that never returns, and a
thread cannot be reclaimed from Python. What *can* be kept honest is the
report. :meth:`RelationJobs.poll` treats a pass running more than
:data:`WEDGE_FACTOR` times the runtime's ceiling, or a load running past
:data:`LOAD_CEILING_S`, as wedged: the job polls as ``failed`` with
``extraction_timeout`` and ``detail.wedged = True``, and every later
:meth:`~RelationJobs.start` returns a job that has already failed the same way,
**until WIMI restarts**. The thread leaks; the page stops showing a spinner
with no end and says something true. Under a working runtime the watchdog
never fires, because the chunk check stops an overrunning pass within a chunk
of the ceiling, long before twice the ceiling.

**A wedge must not also hang the quit, and with ``ThreadPoolExecutor`` it
did.** ``concurrent.futures`` joins its worker threads at interpreter exit
whatever ``shutdown(wait=False)`` asked for, so a worker stuck in a call that
never returns held the process forever after the window closed. Measured:
``shutdown()`` returned at once and the process was still alive when killed at
20 s. So the worker here is :class:`_DaemonWorker`, one **daemon** thread,
which interpreter exit does not wait for. With it the same script exits
immediately. ``tests/app/test_relation_extraction_jobs.py`` runs that script
in a child process with a deadline and checks it exits. A clean exit after a
wedge is therefore a property this module guarantees, not one the bridge has
to arrange.

**This is safe here because this worker only computes.** It reads the model
directory and writes nothing anywhere, so abandoning it mid-pass at exit
loses time and nothing else. **Do not port the pattern to a worker that
writes files.** Folder sync's worker writes ``.wimi`` archives into a folder
another device reads, on filesystems where it cannot rely on atomic rename
(``foldersync/naming.py``, ``transport.py``). There, an abandoned daemon would
trade a hung quit for a partial archive carrying a valid generation name.
Whether to accept that trade is open as #376.

When ``finish`` raises
----------------------
``finish`` runs inside :meth:`~RelationJobs.poll`, on the Qt main thread,
where it may touch the database, so it can raise anything the database can.
That never escapes ``poll`` into a slot. A ``RelationExtractionError`` keeps
its own kind; anything else becomes ``failed`` with ``extraction_failed`` and
``detail`` naming the exception. Either way the outcome is cached like any
other terminal state, and ``finish`` is not run a second time.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
import queue
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from .errors import RelationExtractionError, RelationExtractionErrorKind as Kind
from .runtime import (
    ExtractionCancelled,
    ExtractionResult,
    RelationLabel,
    RelationRuntime,
    label_index,
    validate_threshold,
)

logger = logging.getLogger(__name__)

#: Job lifecycle. The first three are folder sync's and speech-to-text's names
#: and strings, so the bridge does not learn a second vocabulary. ``cancelled``
#: is the one addition, because this is the one job of the three that a
#: student can stop and that can honestly be stopped.
STATE_RUNNING = 'running'
STATE_DONE = 'done'
STATE_FAILED = 'failed'
STATE_CANCELLED = 'cancelled'

#: Thread name prefix, so a stack dump says which feature owns the worker.
THREAD_NAME_PREFIX = 'wimi-relations'

#: A pass running this many times the runtime's ``timeout_s`` is wedged. The
#: chunk check should have stopped it at one ceiling plus one chunk, so twice
#: the ceiling means the check is not being reached at all.
WEDGE_FACTOR = 2.0

#: A load (verify, the torch and gliner2 imports, the build) running this long
#: is wedged. A cold first load measured 16.1 s on the development machine;
#: 300 s leaves room for a slow disk and a slow CPU many times over.
LOAD_CEILING_S = 300.0


class _DaemonWorker:
    """One daemon thread running submitted calls in order.

    The subset of ``ThreadPoolExecutor`` this module uses (``submit`` and
    ``shutdown(cancel_futures=True)``), with the one difference that matters:
    the thread is a daemon, so a call that never returns cannot hold the
    interpreter at exit (see the module docstring). Futures are the stdlib's,
    so cancelling a queued one works exactly as it does there.
    """

    _STOP = object()

    def __init__(self, name: str) -> None:
        self._queue: 'queue.Queue[Any]' = queue.Queue()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        if self._closed:
            raise RuntimeError('cannot schedule new work after shutdown')
        future: Future = Future()
        self._queue.put((future, fn, args))
        return future

    def shutdown(self, *, cancel_futures: bool = True) -> None:
        """Stop accepting work and cancel what is queued. Never waits."""
        self._closed = True
        if cancel_futures:
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is not self._STOP:
                    item[0].cancel()
        self._queue.put(self._STOP)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                return
            future, fn, args = item
            if not future.set_running_or_notify_cancel():
                continue  # cancelled while queued
            try:
                result = fn(*args)
            except BaseException as exc:  # noqa: BLE001 - handed to the future
                future.set_exception(exc)
            else:
                future.set_result(result)


@dataclass
class _Job:
    future: Future
    cancel: threading.Event
    finish: Callable[[ExtractionResult], Any]
    context: dict
    #: Clock readings written by the worker, read by the watchdog.
    worker_started: Optional[float] = None
    pass_started: Optional[float] = None
    collected: bool = False
    result: Any = None
    error: Optional[dict] = None
    state: str = STATE_RUNNING


@dataclass
class RelationJobs:
    """One worker, a dictionary of jobs, and no Qt anywhere in it.

    Not Qt-aware, so it is testable without a ``QApplication``, like
    ``SyncJobs`` and ``TranscriptionJobs``.
    """

    runtime: RelationRuntime
    clock: Callable[[], float] = time.monotonic
    _wedged: Optional[dict] = field(init=False, default=None)
    _pool: _DaemonWorker = field(init=False)
    _jobs: Dict[str, _Job] = field(init=False, default_factory=dict)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._pool = _DaemonWorker(f'{THREAD_NAME_PREFIX}_0')

    # ------------------------------------------------------------------ start

    def start(
        self,
        text: str,
        labels: Sequence[RelationLabel],
        *,
        context: Optional[dict] = None,
        finish: Optional[Callable[[ExtractionResult], Any]] = None,
        threshold: Optional[float] = None,
    ) -> str:
        """Queue one extraction and return its id immediately.

        ``labels`` must be non-empty and free of case-insensitive duplicates;
        that is checked **here**, on the caller's thread, so a malformed
        request raises ``ValueError`` at the call rather than surfacing later
        as a failed job. Build them with :func:`.runtime.labels_from_types`,
        which also drops retired types.

        ``finish`` runs on the polling thread when the worker lands. It is the
        seam for anything that must touch the database or a Qt object; leave
        it ``None`` and the result passes straight through.

        ``context`` is opaque and comes back untouched on every poll, so the
        page can check that the proposals it receives belong to the entry it
        is still showing.

        ``threshold`` is the student's confidence setting, read by the caller
        on its own thread (a preference is a database read) and passed in as a
        number. ``None`` means the runtime's default
        (``runtime.EXTRACTION_THRESHOLD``). A value outside
        ``runtime.THRESHOLD_MIN`` .. ``THRESHOLD_MAX`` raises ``ValueError``
        here, like a malformed label list. The constants are named rather than
        their values restated, because this sentence once stated the bound
        from before #380 decided it.
        """
        labels = tuple(labels)
        label_index(labels)  # raises ValueError here, on the caller's thread
        if threshold is not None:
            threshold = validate_threshold(threshold)
        job_id = uuid.uuid4().hex
        job = _Job(
            future=Future(),
            cancel=threading.Event(),
            finish=finish or (lambda result: result),
            context=dict(context or {}),
        )
        if self._wedged is not None:
            # The single worker is held by a call that never returned, so
            # anything queued behind it would spin forever. Fail it now.
            job.future.set_exception(RelationExtractionError(
                Kind.EXTRACTION_TIMEOUT, 'an earlier extraction never finished',
                detail=dict(self._wedged)))
            logger.warning('refused relation extraction %s: worker is wedged', job_id)
        else:
            job.future = self._pool.submit(self._perform, str(text), labels, job, threshold)
            logger.info('queued relation extraction %s (%d chars, %d types)',
                        job_id, len(text), len(labels))
        with self._lock:
            self._jobs[job_id] = job
        return job_id

    def _perform(self, text: str, labels: tuple, job: _Job,
                 threshold: Optional[float]) -> ExtractionResult:
        """The worker phase: the runtime, and nothing else.

        It writes two clock readings onto the job for the watchdog and reads
        nothing from it but the cancel event; the context and ``finish`` are
        never touched here.
        """
        job.worker_started = self.clock()

        def pass_started() -> None:
            job.pass_started = self.clock()

        return self.runtime.extract(text, labels, cancel=job.cancel,
                                    threshold=threshold, on_pass_start=pass_started)

    # ------------------------------------------------------------------- poll

    def poll(self, job_id: str) -> Dict[str, Any]:
        """Where the job has got to, running ``finish`` on **this** thread.

        Calling it again after completion returns the same answer rather than
        re-running anything, until :meth:`forget`.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            # Not an exception: the page polls with an id it was given, and a
            # forgotten job or a restarted bridge is a state it has to be able
            # to render rather than a crash.
            return {
                'state': STATE_FAILED,
                'error': RelationExtractionError(
                    Kind.UNKNOWN_JOB, f'no such extraction job: {job_id}'
                ).to_dict(),
                'context': {},
            }

        if job.collected:
            return self._report(job)
        if not job.future.done():
            wedged = self._wedge_detail(job)
            if wedged is None:
                return {'state': STATE_RUNNING, 'context': dict(job.context)}
            job.cancel.set()  # in case it ever reaches a checkpoint again
            self._wedged = wedged
            job.collected = True
            job.state = STATE_FAILED
            job.error = RelationExtractionError(
                Kind.EXTRACTION_TIMEOUT, 'extraction never finished', detail=wedged,
            ).to_dict()
            logger.error('relation extraction %s is wedged (%s); refusing new '
                         'extractions until restart', job_id, wedged)
            return self._report(job)

        job.collected = True
        try:
            job.result = job.finish(job.future.result())
            job.state = STATE_DONE
        except (ExtractionCancelled, CancelledError):
            job.state = STATE_CANCELLED
            logger.info('relation extraction %s cancelled', job_id)
        except RelationExtractionError as exc:
            job.state = STATE_FAILED
            job.error = exc.to_dict()
            logger.warning('relation extraction %s failed: %r', job_id, exc)
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            # Anything the taxonomy does not name -- including a finish phase
            # that raised -- still has to reach the page as something it can
            # render, so it arrives as the generic kind with the real message
            # in ``detail``.
            job.state = STATE_FAILED
            job.error = RelationExtractionError(
                Kind.EXTRACTION_FAILED, 'relation extraction failed',
                detail=f'{type(exc).__name__}: {exc}',
            ).to_dict()
            logger.exception('relation extraction %s raised', job_id)
        return self._report(job)

    def _wedge_detail(self, job: _Job) -> Optional[dict]:
        """``None`` while the job is within bounds, else what overran."""
        now = self.clock()
        if job.pass_started is not None:
            ceiling = WEDGE_FACTOR * self.runtime.timeout_s
            elapsed = now - job.pass_started
            stage = 'extraction'
        elif job.worker_started is not None:
            ceiling = LOAD_CEILING_S
            elapsed = now - job.worker_started
            stage = 'load'
        else:
            return None  # still queued
        if elapsed <= ceiling:
            return None
        return {'wedged': True, 'stage': stage,
                'elapsed_s': round(elapsed, 1), 'ceiling_s': ceiling}

    # ----------------------------------------------------------------- cancel

    def cancel(self, job_id: str) -> bool:
        """Ask a job to stop. Returns whether there was anything to stop.

        A queued job never starts. A running one stops at its next chunk and
        then polls as ``cancelled``. A finished one is left alone: its result
        exists, and pretending otherwise would discard work the student waited
        for. An unknown id returns ``False`` rather than raising.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.future.done():
            return False
        job.cancel.set()
        job.future.cancel()  # succeeds only if it has not started
        return True

    def forget(self, job_id: str) -> None:
        """Drop a collected job; a later poll of its id is ``UNKNOWN_JOB``.

        Uncollected work is left alone, so a page that forgets too early
        cannot lose a result still on its way.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.collected:
                del self._jobs[job_id]

    def shutdown(self) -> None:
        """Stop accepting work; ask what is running to stop; do not wait.

        Cancels what is queued and does not wait, as ``SyncJobs.shutdown`` and
        ``TranscriptionJobs.shutdown`` do: this runs from the bridge's
        teardown while the window closes, and a queued pass must not hold the
        close. A running pass is also signalled, so it stops at its next chunk
        instead of finishing work nobody will read. A pass that never reaches
        a chunk again -- a wedge -- does not hold the exit either, because the
        worker is a daemon thread (module docstring).
        """
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
        for job in jobs:
            job.cancel.set()
        self._pool.shutdown(cancel_futures=True)

    # -------------------------------------------------------------- internals

    @staticmethod
    def _report(job: _Job) -> Dict[str, Any]:
        if job.state == STATE_FAILED:
            return {'state': STATE_FAILED, 'error': job.error,
                    'context': dict(job.context)}
        if job.state == STATE_CANCELLED:
            return {'state': STATE_CANCELLED, 'context': dict(job.context)}
        result = job.result
        payload: Dict[str, Any] = {'state': STATE_DONE, 'context': dict(job.context)}
        if isinstance(result, ExtractionResult):
            payload.update(result.to_dict())
        else:
            # A ``finish`` that returned something of its own replaces the
            # proposals wholesale; the bridge decides what that means.
            payload['result'] = result
        return payload

