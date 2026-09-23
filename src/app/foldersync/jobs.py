"""
Running a sync operation without blocking the caller's thread.

Why this exists
---------------
#123 requires that folder enumeration and evicted reads run **off the Qt main
thread, bounded, with a timeout**. On Box that is not an edge case: Box streams
by default and evicts a cached file after 30 days without modification, and our
generation files are written once and never modified, so they start that clock
the moment they land (#123 comment #1503). The hydration path is the normal
path, and every read of the folder can block for as long as the timeout allows.

The obvious fix -- run the whole operation on a worker -- is **not available**,
and the reason is worth stating because it is easy to undo. ``base_db.py``
documents that ``check_same_thread=False`` is set but that *nothing in the
application writes from a second thread*, and transaction re-entrancy is
tracked per connection with a plain counter. Driving ``master_db`` from a
worker would make this the first code to break that invariant, and the failure
would be an interleaved transaction depth: silent, intermittent, and nothing
like a crash.

So the split is by *what is touched*, not by convenience:

===============  ==========================  ==============================
phase            thread                      may touch
===============  ==========================  ==============================
``prepare_*``    caller's (Qt main)          ``master_db``, local disk
``perform_*``    worker                      the sync folder, and nothing else
``finish_*``     caller's (Qt main)          ``master_db``, ``state.json``
===============  ==========================  ==============================

``FolderTransport`` already knew nothing about databases, so the seam existed
before this module did; ``service.py`` just names it now.
``tests/app/test_foldersync_threading.py`` asserts the middle row by handing
the worker phase a ``master_db`` that raises on **any** attribute access.

How a caller uses it
--------------------
``submit_*`` runs phase 1 inline and returns a job id. ``poll`` returns
``{"state": "running"}`` until the worker is done, then runs phase 3 -- still
on the polling thread -- and returns the result. So the bridge slot stays an
ordinary synchronous request/response, and the page polls.

One worker for the whole process, deliberately. Two pushes racing for the next
generation number is a real hazard and serialising them costs nothing: a push
is one archive copy and one small JSON write.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, ContextManager, Dict, Optional

from .service import FetchResult, ProfileFolderSync, PushPlan, StatusInputs, SyncStatus
from .transport import PushResult, TransportError

#: Job lifecycle. There is no "cancelled": a bounded read that timed out has
#: already given up on its own, and the worker thread it left behind is a
#: daemon that cannot be killed safely (see ``hydration._run_bounded``).
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"


@dataclass
class _Job:
    kind: str
    user_id: int
    future: Future
    finish: Callable[[Any], Any]
    discard: Optional[Callable[[], None]] = None
    collected: bool = False
    result: Any = None
    error: Optional[str] = None
    state: str = STATE_RUNNING


@dataclass
class SyncJobs:
    """
    Folder I/O off the caller's thread, with the database work left on it.

    Not Qt-aware -- it is an executor and a dictionary -- so it is testable
    without a ``QApplication``, like everything else in this package.
    """

    sync: ProfileFolderSync
    _pool: ThreadPoolExecutor = field(init=False)
    _jobs: Dict[str, _Job] = field(init=False, default_factory=dict)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wimi-sync")

    # ------------------------------------------------------------------ submit

    def submit_status(self, user_id: int) -> str:
        """Look at the folder. Phase 1 reads the link and this machine's identity."""
        inputs = self.sync.prepare_status(user_id)
        if inputs.link is None:
            return self._completed(
                "status", user_id, SyncStatus(linked=False)
            )
        return self._start(
            "status",
            user_id,
            work=lambda: self.sync.observe_folder(
                inputs.link, inputs.identity.device_id if inputs.identity else None),
            finish=lambda observed: self.sync.finish_status(user_id, inputs, observed),
        )

    def submit_push(self, user_id: int) -> str:
        """
        Publish the next generation. Phase 1 seals the archive.

        The archive is built **before** the thread boundary, so a failure to
        read the database surfaces from ``submit_push`` itself rather than
        arriving later as a job error with no context.
        """
        plan: PushPlan = self.sync.prepare_push(user_id)
        return self._start(
            "push",
            user_id,
            work=lambda: self.sync.perform_push(plan),
            finish=lambda result: self.sync.finish_push(plan, result),
            discard=lambda: self.sync.discard_push(plan),
        )

    def submit_fetch(self, user_id: int) -> str:
        """
        Stage the highest verified generation. Nothing is installed.

        ``fetch_from`` is already database-free -- it reads the folder, then a
        staged zip and its ``user.db`` as plain files -- so the whole of it is
        the worker phase. Only ``record_seen`` comes back to the caller.
        """
        link = self.sync.state.get_link(user_id)
        if link is None:
            raise TransportError("this profile is not linked to a sync folder")

        def _finish(result: FetchResult) -> FetchResult:
            self.sync.state.record_seen(user_id, result.generation)
            return result

        return self._start(
            "fetch",
            user_id,
            work=lambda: self.sync.fetch_from(link.folder, link.sync_id, link.provider_id),
            finish=_finish,
        )

    def submit_link(self, user_id: int, folder: str, provider_id: str = "generic") -> str:
        """
        Point a profile at a folder. Phase 1 resolves which segment it owns.

        The preflight is folder I/O -- a ``stat`` and a write probe -- so it
        cannot run on the UI thread even though it looks trivial. A cloud
        filesystem can block on either while the client is offline.
        """
        plan = self.sync.prepare_link(user_id, folder, provider_id)
        return self._start(
            "link",
            user_id,
            work=lambda: self.sync.check_folder(plan),
            finish=lambda problems: self.sync.finish_link(plan, problems),
        )

    def submit_discover(self, folder: str, provider_id: str = "generic") -> str:
        """
        What is already in this folder, and which of it this machine holds.

        Phase 2 enumerates; phase 3 asks the registry which uuids are ours,
        which is the "this profile is already linked here" check #129 found
        missing (see ``ProfileFolderSync.annotate_discovery``).
        """
        return self._start(
            "discover",
            0,
            work=lambda: self.sync.scan_folder(folder, provider_id),
            finish=lambda found: self.sync.annotate_discovery(found),
        )

    def submit_install(self, folder: str, sync_id: str, provider_id: str = "generic") -> str:
        """A computer's first copy of a profile, from the folder (#151).

        Needs no profile open -- the picker runs before one exists. Phase 1
        refuses a profile this computer already has, so that error arrives
        from ``submit_install`` itself, before anything is downloaded.
        Phase 2 fetches and verifies (a download, by design: the student
        asked for this copy). Phase 3 installs, records the base and links.
        """
        plan = self.sync.prepare_install(folder, sync_id, provider_id)
        return self._start(
            "install",
            0,
            work=lambda: self.sync.perform_install(plan),
            finish=lambda performed: self.sync.finish_install(plan, performed),
        )

    def submit_fork_report(
        self, user_id: int, parent_generation: Optional[int] = None
    ) -> str:
        """Find a fork and compare its two sides.

        The worker phase stages both blobs, which downloads them. Deliberate
        -- see ``collect_fork_sides``.
        """
        inputs = self.sync.prepare_fork_report(user_id)
        if inputs.link is None:
            return self._completed("fork_report", user_id, None)
        return self._start(
            "fork_report",
            user_id,
            work=lambda: self.sync.collect_fork_sides(
                inputs.link, parent_generation,
                inputs.identity.device_id if inputs.identity else None),
            finish=lambda observed: self.sync.finish_fork_report(observed),
        )

    def submit_resolve(
        self,
        user_id: int,
        *,
        choice: str,
        blob_name: str,
        safety_dir: str,
        active_user_id: Optional[int] = None,
        release_profile: Optional[Callable[[], ContextManager[Any]]] = None,
    ) -> str:
        """Apply the student's choice to a fork.

        The side is named by its **blob name**, not a generation number: the
        two sides of a fork usually share a generation, so a number would be
        ambiguous between the copy the student chose and the one they
        rejected.

        The split is unusually load-bearing here. Phase 2 brings the chosen
        side out of the folder -- network-ish work that must not freeze the
        window. Phase 3 takes the safety export and applies the choice, and
        **must** be on the caller's thread: both are heavy ``master_db``
        work, and ``base_db`` records that nothing in this application
        writes from a second thread.

        So the one operation here that can destroy something runs where the
        database expects it to, and only the download is moved.

        ``release_profile`` is how ``keep_remote`` reaches the profile that is
        open (the owner's decision on #148: close and reopen around the
        replace). It is a context manager factory: entering closes the live
        connection, leaving reopens whatever is on disk -- the replaced copy
        on success, the untouched original on failure. Without it,
        ``keep_remote`` on the open profile is refused exactly as before,
        because ``replace_profile`` swapping a file under a live connection
        is the thing that must never happen.

        Nothing is sent. The choice is recorded as pending on the link and
        the student's next push carries it (#148).
        """
        from .resolution import CHOICES, ResolutionError, resolve_fork

        # Validate the choice BEFORE the worker stages anything. Left to
        # phase 3 it is still caught, but only after a download -- and the
        # error the student sees is then whatever the staging said, which
        # for a bad choice plus a stale blob name was "not in this folder":
        # true, unhelpful, and about the wrong problem.
        if choice not in CHOICES:
            raise ResolutionError(
                f"unknown choice {choice!r}; expected one of {', '.join(CHOICES)}")

        link = self.sync.state.get_link(user_id)
        if link is None:
            raise TransportError("this profile is not linked to a sync folder")

        from .resolution import KEEP_REMOTE

        device_id = self.sync._device_identity().device_id

        def _apply(staged: Dict[str, Any], active: Optional[int]):
            return resolve_fork(
                self.sync.master_db,
                user_id=user_id,
                choice=choice,
                incoming_archive=staged["archive_path"],
                safety_dir=safety_dir,
                active_user_id=active,
            )

        def _finish(staged: Dict[str, Any]):
            releasing = (
                choice == KEEP_REMOTE
                and release_profile is not None
                and active_user_id is not None
                and int(active_user_id) == int(user_id)
            )
            if releasing:
                with release_profile():
                    # Closed now, so honestly not active: the guard in
                    # replace_profile is satisfied by the fact, not defeated.
                    resolution = _apply(staged, None)
            else:
                resolution = _apply(staged, active_user_id)
            send = self.sync.finish_resolution(user_id, choice, staged, resolution)
            resolution.notes.extend(_send_notes(send))
            resolution.send_needed = send["send_needed"]
            resolution.pending = send["pending"]
            return resolution

        return self._start(
            "resolve",
            user_id,
            work=lambda: self.sync.stage_for_resolution(link, blob_name, device_id),
            finish=_finish,
        )

    # ------------------------------------------------------------------ poll

    def poll(self, job_id: str) -> Dict[str, Any]:
        """
        Where the job has got to, running phase 3 on **this** thread when it lands.

        Calling it again after completion returns the same answer rather than
        re-running anything: the page may poll once more before it notices.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {"state": STATE_FAILED, "error": f"no such sync job: {job_id}"}

        if job.collected:
            return self._report(job)
        if not job.future.done():
            return {"state": STATE_RUNNING, "kind": job.kind}

        job.collected = True
        try:
            job.result = job.finish(job.future.result())
            job.state = STATE_DONE
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            # Phase 2 or phase 3 failed. Either way the staging directory is
            # this job's to clean up: leaving it would accumulate a sealed
            # copy of the profile per failed push.
            if job.discard is not None:
                job.discard()
            job.state = STATE_FAILED
            job.error = str(exc) or exc.__class__.__name__
        return self._report(job)

    def forget(self, job_id: str) -> None:
        """Drop a collected job. Uncollected work is left alone."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.collected:
                del self._jobs[job_id]

    def shutdown(self) -> None:
        """
        Stop accepting work and discard anything staged but never collected.

        A push whose job was never polled -- the window was closed mid-sync --
        otherwise leaves a sealed archive in staging for good.
        """
        self._pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
        for job in jobs:
            if not job.collected and job.discard is not None:
                job.discard()

    # ------------------------------------------------------------------ internals

    def _start(self, kind, user_id, work, finish, discard=None) -> str:
        job_id = uuid.uuid4().hex
        job = _Job(
            kind=kind,
            user_id=user_id,
            future=self._pool.submit(work),
            finish=finish,
            discard=discard,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job_id

    def _completed(self, kind: str, user_id: int, value: Any) -> str:
        """A job that needed no folder I/O at all -- an unlinked profile."""
        future: Future = Future()
        future.set_result(value)
        job = _Job(kind=kind, user_id=user_id, future=future, finish=lambda v: v)
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = job
        return job_id

    @staticmethod
    def _report(job: _Job) -> Dict[str, Any]:
        if job.state == STATE_FAILED:
            return {"state": STATE_FAILED, "kind": job.kind, "error": job.error}
        return {"state": STATE_DONE, "kind": job.kind, "result": job.result}


def _send_notes(send: Dict[str, Any]) -> list:
    """What the student is told about the folder after choosing (#148)."""
    if not send.get("send_needed"):
        return ["This device now holds the same copy as the sync folder. "
                "There is nothing to send."]
    return ["Your choice is saved on this device only. The other device "
            "will keep seeing two copies until you send -- use Send now "
            "in Settings when you are ready."]


__all__ = [
    "SyncJobs",
    "STATE_RUNNING",
    "STATE_DONE",
    "STATE_FAILED",
    "PushResult",
]
