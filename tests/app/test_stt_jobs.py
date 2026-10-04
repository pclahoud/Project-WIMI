"""The thread split for transcription, and the invariant it protects (#59, T6).

This is the folder-sync argument applied to a second feature, and it is
deliberately tested the same way (``tests/app/test_foldersync_threading.py``):
``base_db.py`` records that ``check_same_thread=False`` is set but that
**nothing in this application writes to the database from a second thread**,
and transaction re-entrancy is tracked per connection with a plain counter.
Speech is the second feature that wants a worker, so it is the second that
could break that -- and the break would be an interleaved transaction depth:
silent, intermittent, and nothing like a crash.

Two kinds of test hold the line:

* a **static** one, because transcription's worker body is a whole module
  (``runtime.py``) rather than one function, and the cheapest way to prove a
  module cannot touch Qt or a database is to prove it does not import them.
  It covers the *model download's* worker body as well -- see
  ``WORKER_MODULES``, which is where the second worker was missing;
* **dynamic** ones, which watch which thread each phase actually runs on, and
  hand the finish phase a ``Landmine`` that fails on any attribute access at
  all -- so a stray call cannot hide inside an exception path.

Markers: ``@pytest.mark.unit``. No Qt, no network, no database.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from app.stt import jobs as stt_jobs
from app.stt import runtime as rt
from app.stt.errors import SttError, SttErrorKind
from app.stt.jobs import (
    STATE_DONE,
    STATE_FAILED,
    STATE_RUNNING,
    TranscriptionJobs,
)
from app.stt.runtime import TranscriptionResult

from .test_stt_runtime import fake_whisper, model_file

pytestmark = pytest.mark.unit

STT_PACKAGE = Path(rt.__file__).parent

#: Modules the worker body may never reach for. ``sqlite3`` and ``database``
#: are the invariant above; ``PyQt6`` is §3.4's other half -- the worker must
#: touch no Qt object, and the surest way to keep that true is for the code it
#: runs to have no way of naming one.
FORBIDDEN_ROOTS = ('PyQt6', 'sqlite3', 'database')


class Landmine:
    """Stands in for the database during the worker phase.

    Any attribute access is a failure, including ``repr`` during a traceback,
    so a stray call cannot hide inside an exception path.
    """

    def __getattr__(self, name):  # noqa: D105
        raise AssertionError(
            f'the worker phase touched the database: db.{name}. Database work '
            f'belongs in the finish phase, on the polling thread -- see '
            f'base_db.py on check_same_thread.'
        )


class StubRuntime:
    """A ``WhisperRuntime`` with the subprocess taken out.

    It keeps the two parts of the real contract that this layer depends on:
    it blocks, and it deletes its input in a ``finally``.
    """

    def __init__(self, *, text='spoken words', error=None, gate=None):
        self.text = text
        self.error = error
        self.gate = gate
        self.threads: list[str] = []
        self.calls: list[tuple] = []
        self._live = 0
        self.max_live = 0
        self._lock = threading.Lock()

    def transcribe(self, audio_path, *, prompt='', delete_audio=True):
        self.threads.append(threading.current_thread().name)
        self.calls.append((Path(audio_path), prompt, delete_audio))
        with self._lock:
            self._live += 1
            self.max_live = max(self.max_live, self._live)
        try:
            if self.gate is not None:
                self.gate.wait(10)
            time.sleep(0.02)
            if self.error is not None:
                raise self.error
            return TranscriptionResult(text=self.text, ms=12, stderr='timings')
        finally:
            with self._lock:
                self._live -= 1
            if delete_audio:
                Path(audio_path).unlink(missing_ok=True)


def wait_for(predicate, timeout=10.0):
    """Poll against a wall-clock deadline rather than spinning.

    A tight loop outran the worker in the folder-sync tests and reported work
    as never finished while it was still running.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError('timed out waiting for the worker')


def settled(jobs: TranscriptionJobs, job_id: str) -> dict:
    """The job's report once it has stopped saying ``running``."""
    box: dict = {}

    def check():
        report = jobs.poll(job_id)
        if report['state'] != STATE_RUNNING:
            box['report'] = report
            return True
        return False

    wait_for(check)
    return box['report']


def clip(tmp_path: Path, name='clip.wav') -> Path:
    path = tmp_path / name
    path.write_bytes(b'RIFF....')
    return path


# --------------------------------------------------- the static invariant

#: **There are two workers, not one.** ``SttBridgeMixin`` runs the first-run
#: model download on its own single-thread executor, and its module docstring
#: makes the same promise this one does -- "Both workers touch no Qt object and
#: no database connection (Section 3.4)". ``download.py`` says it of itself in
#: its first paragraph. Until T17 only the transcription half was checked, so
#: an ``import sqlite3`` added to ``download.py`` left all 282 speech tests
#: green. ``model_spec.py`` is here because ``download.py`` imports it and the
#: guard is worth nothing if the module underneath it is exempt.
WORKER_MODULES = [
    'runtime.py', 'jobs.py', 'errors.py', 'download.py', 'model_spec.py',
]


@pytest.mark.parametrize('module', WORKER_MODULES)
def test_the_worker_body_cannot_name_qt_or_a_database(module):
    """Proved by import, because the worker body is a module, not a closure."""
    tree = ast.parse((STT_PACKAGE / module).read_text(encoding='utf-8'))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.append(node.module)

    offenders = [
        name for name in imported
        if name.split('.')[0] in FORBIDDEN_ROOTS
    ]
    assert not offenders, (
        f'{module} imports {offenders}; neither worker -- transcription or '
        f'model download -- may touch a Qt object or a database connection '
        f'(plan Section 3.4)'
    )


def test_the_executor_is_one_worker_named_for_the_feature(tmp_path):
    runtime = StubRuntime()
    jobs = TranscriptionJobs(runtime=runtime)
    try:
        job_id = jobs.start(clip(tmp_path))
        wait_for(lambda: jobs.poll(job_id)['state'] != STATE_RUNNING)
    finally:
        jobs.shutdown()

    assert runtime.threads[0].startswith(stt_jobs.THREAD_NAME_PREFIX)
    assert runtime.threads[0] != threading.current_thread().name


def test_a_second_transcription_queues_rather_than_races(tmp_path):
    """One worker, deliberately: two runs would contend for the same cores."""
    runtime = StubRuntime()
    jobs = TranscriptionJobs(runtime=runtime)
    try:
        ids = [jobs.start(clip(tmp_path, f'clip{i}.wav')) for i in range(4)]
        for job_id in ids:
            wait_for(lambda jid=job_id: jobs.poll(jid)['state'] == STATE_DONE)
    finally:
        jobs.shutdown()

    assert runtime.max_live == 1
    assert len(runtime.calls) == 4


# -------------------------------------------------- where each phase runs

def test_the_finish_phase_runs_on_the_polling_thread(tmp_path):
    """That is the whole reason a finish phase exists: it is the one place a
    transcription job may touch the database."""
    seen: dict = {}

    def finish(result):
        seen['thread'] = threading.current_thread()
        return result

    jobs = TranscriptionJobs(runtime=StubRuntime())
    try:
        job_id = jobs.start(clip(tmp_path), finish=finish)
        wait_for(lambda: jobs.poll(job_id)['state'] == STATE_DONE)
    finally:
        jobs.shutdown()

    assert seen['thread'] is threading.current_thread()


def test_the_worker_never_reaches_the_finish_phases_resources(tmp_path):
    """A ``Landmine`` in the finish phase proves where each half ran.

    The worker completes successfully -- so it never touched it -- and the
    explosion happens on the polling thread, which is where the database
    lives. ``poll`` reports it rather than raising, because a bridge slot has
    to return something.
    """
    landmine = Landmine()
    jobs = TranscriptionJobs(runtime=StubRuntime())
    try:
        job_id = jobs.start(clip(tmp_path), finish=lambda result: landmine.save(result))
        # The worker lands cleanly, with the landmine untouched...
        wait_for(lambda: jobs._jobs[job_id].future.done())
        assert jobs._jobs[job_id].future.exception() is None
        # ...and only the poll sets it off.
        report = jobs.poll(job_id)
    finally:
        jobs.shutdown()

    assert report['state'] == STATE_FAILED
    assert 'touched the database' in report['error']['detail']


# ------------------------------------------------------- the job contract

def test_a_finished_job_hands_back_the_transcript_and_the_context(tmp_path):
    """§3.5: the page has to be able to tell which field a transcript is for."""
    context = {'entry_id': 41, 'field_key': 'reflection', 'token': 7}
    jobs = TranscriptionJobs(runtime=StubRuntime(text='Deep vein thrombosis.'))
    try:
        job_id = jobs.start(clip(tmp_path), prompt='thrombosis', context=context)
        first = jobs.poll(job_id)
        assert first['context'] == context      # even while still running
        report = settled(jobs, job_id)
    finally:
        jobs.shutdown()

    assert first['state'] in (STATE_RUNNING, STATE_DONE)
    assert report['state'] == STATE_DONE
    assert report['text'] == 'Deep vein thrombosis.'
    assert report['ms'] == 12
    assert report['context'] == context


def test_polling_again_repeats_the_answer_instead_of_rerunning(tmp_path):
    """The page may well poll once more before it notices the first result."""
    finishes = []
    jobs = TranscriptionJobs(runtime=StubRuntime())
    try:
        job_id = jobs.start(
            clip(tmp_path), finish=lambda r: (finishes.append(r), r)[1]
        )
        wait_for(lambda: jobs.poll(job_id)['state'] == STATE_DONE)
        again = jobs.poll(job_id)
        once_more = jobs.poll(job_id)
    finally:
        jobs.shutdown()

    assert len(finishes) == 1
    assert again == once_more
    assert again['state'] == STATE_DONE


def test_a_failed_transcription_keeps_its_kind(tmp_path):
    """The taxonomy survives the thread boundary; the page branches on it."""
    error = SttError(SttErrorKind.TRANSCRIPTION_TIMEOUT, 'did not finish within 120s')
    jobs = TranscriptionJobs(runtime=StubRuntime(error=error))
    try:
        job_id = jobs.start(clip(tmp_path), context={'field_key': 'explanation'})
        report = settled(jobs, job_id)
    finally:
        jobs.shutdown()

    assert report['state'] == STATE_FAILED
    assert report['error']['kind'] == SttErrorKind.TRANSCRIPTION_TIMEOUT.value
    assert report['error']['retryable'] is True
    assert report['context'] == {'field_key': 'explanation'}


def test_an_unknown_job_id_is_a_named_kind_not_a_crash(tmp_path):
    jobs = TranscriptionJobs(runtime=StubRuntime())
    try:
        report = jobs.poll('never-issued')
    finally:
        jobs.shutdown()

    assert report['state'] == STATE_FAILED
    assert report['error']['kind'] == SttErrorKind.UNKNOWN_JOB.value
    assert report['error']['retryable'] is False


def test_forgetting_a_collected_job_makes_it_unknown(tmp_path):
    jobs = TranscriptionJobs(runtime=StubRuntime())
    try:
        job_id = jobs.start(clip(tmp_path))
        wait_for(lambda: jobs.poll(job_id)['state'] == STATE_DONE)
        jobs.forget(job_id)
        report = jobs.poll(job_id)
    finally:
        jobs.shutdown()

    assert report['error']['kind'] == SttErrorKind.UNKNOWN_JOB.value


def test_forget_leaves_uncollected_work_alone(tmp_path):
    gate = threading.Event()
    jobs = TranscriptionJobs(runtime=StubRuntime(gate=gate))
    try:
        job_id = jobs.start(clip(tmp_path))
        jobs.forget(job_id)                    # never polled -> still there
        gate.set()
        assert wait_for(lambda: jobs.poll(job_id)['state'] == STATE_DONE)
    finally:
        gate.set()
        jobs.shutdown()


# ------------------------------------------------------------- the recording

def test_the_recording_is_gone_once_the_worker_has_run(tmp_path):
    jobs = TranscriptionJobs(runtime=StubRuntime())
    audio = clip(tmp_path)
    try:
        job_id = jobs.start(audio)
        wait_for(lambda: jobs.poll(job_id)['state'] == STATE_DONE)
    finally:
        jobs.shutdown()

    assert not audio.exists()


def test_shutdown_deletes_the_recording_of_a_job_that_never_ran(tmp_path):
    """``transcribe``'s ``finally`` cannot fire for a future that was cancelled.

    Closing the window mid-dictation would otherwise leave the student's
    recording on disk for good.
    """
    gate = threading.Event()
    jobs = TranscriptionJobs(runtime=StubRuntime(gate=gate))
    running = clip(tmp_path, 'running.wav')
    queued = clip(tmp_path, 'queued.wav')
    try:
        jobs.start(running)
        wait_for(lambda: jobs.runtime.calls)   # the first job is in the worker
        jobs.start(queued)
        jobs.shutdown()          # cancels the queued future
        assert not queued.exists()
    finally:
        gate.set()
        wait_for(lambda: not running.exists())


def test_a_file_the_caller_owns_is_left_alone(tmp_path):
    jobs = TranscriptionJobs(runtime=StubRuntime())
    audio = clip(tmp_path)
    try:
        job_id = jobs.start(audio, delete_audio=False)
        wait_for(lambda: jobs.poll(job_id)['state'] == STATE_DONE)
    finally:
        jobs.shutdown()

    assert audio.exists()
    assert jobs.runtime.calls[0][2] is False


# --------------------------------------------- against the real runtime

def test_end_to_end_against_a_real_subprocess(tmp_path):
    """The same path with ``WhisperRuntime`` rather than a stub in it.

    The engine is faked (there is no whisper binary on a fresh checkout) but
    everything between the job id and the transcript is production code: a
    real ``subprocess.run``, a real model verification, a real delete.
    """
    binary, argv_log = fake_whisper(tmp_path)
    spec = model_file(tmp_path)
    runtime = rt.WhisperRuntime(
        app_data_dir=tmp_path,
        model_size=spec.size,
        binary=binary,
        spec_lookup=lambda size: spec,
    )
    jobs = TranscriptionJobs(runtime=runtime)
    audio = clip(tmp_path, 'spoken.wav')
    try:
        job_id = jobs.start(audio, prompt='thrombosis, embolism')
        report = settled(jobs, job_id)
    finally:
        jobs.shutdown()

    assert report['state'] == STATE_DONE
    assert report['text']
    assert not audio.exists()
    assert argv_log.read_text().splitlines()[-2:] == [
        '--prompt', 'thrombosis, embolism',
    ]
