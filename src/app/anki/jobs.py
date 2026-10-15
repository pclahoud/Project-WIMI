"""AnkiConnect calls off the Qt main thread, and nothing else moved off it (#784).

This mirrors ``src/app/foldersync/jobs.py`` and ``src/app/stt/jobs.py``
deliberately, because the constraint is the same one: ``base_db.py`` records
that **nothing in this application writes to the database from a second
thread**, and transaction depth is a per-connection counter. The plugin this
replaces made every AnkiConnect call synchronously inside a bridge slot, so a
closed Anki or a slow review-log fetch froze the window for up to ten seconds
per request (#784, plan finding 5).

===============  ==========================  ===============================
phase            thread                      may touch
===============  ==========================  ===============================
``start``        caller's (Qt main)          anything -- it runs inline
``work``         worker                      an ``AnkiConnectClient`` only
``finish``       caller's (Qt main)          the database, Qt, anything
===============  ==========================  ===============================

``work`` is handed a client and nothing else. The bridge (Wave 2) reads what
it needs from the database **before** calling ``start`` and passes plain data
into the closure, and writes what came back in ``finish``. ``client.py`` --
the entire body of every ``work`` -- imports neither Qt nor ``sqlite3`` nor
``database``, and ``tests/app/test_anki_jobs.py`` asserts that statically.

The profile check
-----------------

A student can switch profile while a job is in flight. ``start`` records the
user id that was open; ``poll`` compares it with the one open *now* and, if
they differ, fails the job as ``PROFILE_CHANGED`` **without running
``finish``**, so one profile's card data is never written into another's
database. Folder sync's ``_Job`` records ``user_id`` for the same reason.

The finish runs on poll, never on completion
--------------------------------------------

So a page that navigated away before polling -- the entry detail page's
previous/next is a full page load -- leaves a finished job that is simply
never collected, and nothing is written on its behalf. ``forget`` and
``shutdown`` drop such jobs.

**One worker, not a pool.** AnkiConnect serves requests one at a time on
Anki's main thread; two concurrent jobs would queue there anyway, and two
refreshes of one entry racing to write the cache is the worse outcome.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .client import AnkiConnectClient
from .errors import AnkiError, AnkiErrorKind

logger = logging.getLogger(__name__)

#: The same three states, with the same strings, as folder sync and speech,
#: so the bridge layer does not learn a third vocabulary.
STATE_RUNNING = 'running'
STATE_DONE = 'done'
STATE_FAILED = 'failed'

#: Thread name prefix, so a stack dump says which feature owns the worker.
THREAD_NAME_PREFIX = 'wimi-anki'

#: ``work(client) -> result``; runs on the worker.
Work = Callable[[AnkiConnectClient], Any]
#: ``finish(result) -> payload``; runs on the polling (Qt main) thread.
Finish = Callable[[Any], Any]


@dataclass
class _Job:
    future: Future
    finish: Finish
    context: dict
    user_id: Optional[int]
    collected: bool = False
    result: Any = None
    error: Optional[dict] = None
    state: str = STATE_RUNNING


@dataclass
class AnkiJobs:
    """One worker, a dictionary of jobs, and no Qt anywhere in it.

    ``client_factory`` is called **on the worker** at the start of each job,
    so the port the student saved a moment ago is the one used, and builds a
    client from plain data (it must not read the database -- the bridge
    captures the port before calling ``start``). ``current_user_id`` is
    called on the polling thread and answers which profile is open now.
    """

    current_user_id: Callable[[], Optional[int]]
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
        work: Work,
        *,
        client_factory: Callable[[], AnkiConnectClient],
        finish: Optional[Finish] = None,
        context: Optional[dict] = None,
        user_id: Optional[int] = None,
    ) -> str:
        """Queue one job and return its id immediately.

        ``user_id`` is the profile open at the moment of the press; ``None``
        means "no profile", which only a profile-independent job such as the
        connection ping should pass.
        """
        job_id = uuid.uuid4().hex

        def run() -> Any:
            return work(client_factory())

        job = _Job(
            future=self._pool.submit(run),
            finish=finish or (lambda result: result),
            context=dict(context or {}),
            user_id=user_id,
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info('queued anki job %s %s', job_id, job.context.get('kind', ''))
        return job_id

    # ------------------------------------------------------------------- poll

    def poll(self, job_id: str) -> Dict[str, Any]:
        """Where the job has got to, running the finish phase on **this** thread.

        Polling again after completion returns the same answer without
        re-running anything.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {
                'state': STATE_FAILED,
                'error': AnkiError(
                    AnkiErrorKind.UNKNOWN_JOB, f'no such Anki job: {job_id}'
                ).to_dict(),
                'context': {},
            }

        if job.collected:
            return self._report(job)
        if not job.future.done():
            return {'state': STATE_RUNNING, 'context': dict(job.context)}

        job.collected = True
        try:
            result = job.future.result()
            if job.user_id is not None and self.current_user_id() != job.user_id:
                raise AnkiError(
                    AnkiErrorKind.PROFILE_CHANGED,
                    f'started for user {job.user_id}; that profile is no longer open',
                )
            job.result = job.finish(result)
            job.state = STATE_DONE
        except AnkiError as exc:
            job.state = STATE_FAILED
            job.error = exc.to_dict()
            logger.warning('anki job %s failed: %s', job_id, exc)
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            job.state = STATE_FAILED
            job.error = AnkiError(
                AnkiErrorKind.FAILED, str(exc) or exc.__class__.__name__
            ).to_dict()
            logger.exception('anki job %s raised', job_id)
        return self._report(job)

    def forget(self, job_id: str) -> None:
        """Drop a collected job. Uncollected work is left alone."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.collected:
                del self._jobs[job_id]

    def shutdown(self) -> None:
        """Stop accepting work; do not wait for what is already running.

        ``wait=False, cancel_futures=True`` as in ``SyncJobs.shutdown``: this
        runs while the window is closing, and a request in flight has its own
        timeout. Uncollected jobs are dropped, so no finish phase runs after
        teardown.
        """
        self._pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            self._jobs.clear()

    # -------------------------------------------------------------- internals

    @staticmethod
    def _report(job: _Job) -> Dict[str, Any]:
        if job.state == STATE_FAILED:
            return {'state': STATE_FAILED, 'error': job.error, 'context': dict(job.context)}
        return {'state': STATE_DONE, 'result': job.result, 'context': dict(job.context)}
