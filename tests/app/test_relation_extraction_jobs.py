"""Relation-extraction jobs: the thread split, the id lifecycle, cancel, the watchdog (#60).

The threading contract is the contract. ``base_db.py`` records that nothing in
this application writes to a database from a second thread, so the worker
phase may touch **neither a Qt object nor a database connection**. Folder
sync proves its split by handing the worker a ``master_db`` that raises on any
attribute access (``tests/app/test_foldersync_threading.py``); this file does
the same with the two things a relation job carries that a database could hide
in -- the context and ``finish`` -- and asserts statically that the modules the
worker runs import neither Qt nor ``sqlite3`` nor ``database``.

No torch: the runtime is a stub with the real ``extract`` signature.

Markers: ``@pytest.mark.unit``. ``wait_for`` polls against a wall-clock
deadline rather than spinning, as the folder-sync tests learned to.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from app.relation_extraction import jobs as jobs_module
from app.relation_extraction.errors import (
    RelationExtractionError,
    RelationExtractionErrorKind as Kind,
)
from app.relation_extraction.jobs import (
    LOAD_CEILING_S,
    STATE_CANCELLED,
    STATE_DONE,
    STATE_FAILED,
    STATE_RUNNING,
    WEDGE_FACTOR,
    RelationJobs,
)
from app.relation_extraction.runtime import (
    ExtractionCancelled,
    ExtractionResult,
    Mention,
    Proposal,
    RelationLabel,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE = REPO_ROOT / 'src' / 'app' / 'relation_extraction'
LABELS = (RelationLabel(1, 'causes'), RelationLabel(2, 'treats'))


def proposal() -> Proposal:
    return Proposal(
        relation_type_id=1, label='causes',
        head=Mention('Smoking', 0, 7, 0.9), tail=Mention('cancer', 15, 21, 0.8),
        score=0.8, passage='Smoking causes cancer.', passage_start=0, passage_end=22,
    )


class StubRuntime:
    """The real ``extract`` signature; behaviour chosen per test."""

    def __init__(self, *, behaviour=None, timeout_s: float = 60.0):
        self.behaviour = behaviour
        self.timeout_s = timeout_s
        self.calls = []

    def extract(self, text, labels, *, cancel=None, timeout_s=None, threshold=None,
                on_pass_start=None):
        self.calls.append({'text': text, 'labels': labels, 'cancel': cancel,
                           'threshold': threshold,
                           'thread': threading.current_thread().name})
        # The worker receives plain data and an Event: nothing that could be a
        # connection.
        assert isinstance(text, str)
        assert all(isinstance(label, RelationLabel) for label in labels)
        assert isinstance(cancel, threading.Event)
        if on_pass_start is not None:
            on_pass_start()
        if self.behaviour is not None:
            return self.behaviour(text, labels, cancel)
        return ExtractionResult(proposals=(proposal(),), ms=12, load_ms=None)


class Landmine:
    """Any attribute access fails.

    Attribute access only: ``repr()`` and other dunder protocols are looked up
    on the type and do not reach ``__getattr__``, so they pass silently. That
    is enough here, because using a connection means calling a method on it.
    The negative control was an added ``job.context['db'].cursor()`` in the
    worker, which this file then failed with the message below; an added
    ``repr(...)`` was not caught, which is why this docstring says so.
    """

    def __getattr__(self, name):  # noqa: D105
        raise AssertionError(
            f'the worker phase touched {name!r} on something it was not given. '
            f'Database work belongs in finish, on the polling thread -- see '
            f"base_db.py's note on check_same_thread."
        )


def wait_for(predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError('condition not met before the deadline')


def settle(jobs, job_id, timeout: float = 5.0) -> dict:
    return wait_for(lambda: (r := jobs.poll(job_id))['state'] != STATE_RUNNING and r,
                    timeout)


@pytest.fixture
def make_jobs():
    made = []

    def _make(runtime=None, **kwargs):
        jobs = RelationJobs(runtime or StubRuntime(), **kwargs)
        made.append(jobs)
        return jobs

    yield _make
    for jobs in made:
        jobs.shutdown()


# --------------------------------------------------- the static invariant

#: The modules the worker phase runs. ``model_spec`` because ``verify_dir``
#: runs on the worker; ``errors`` because everything raises through it.
WORKER_MODULES = ['runtime.py', 'jobs.py', 'errors.py', 'model_spec.py']
FORBIDDEN_ROOTS = ('PyQt6', 'sqlite3', 'database')


@pytest.mark.parametrize('module', WORKER_MODULES)
def test_the_worker_body_cannot_name_qt_or_a_database(module):
    tree = ast.parse((PACKAGE / module).read_text(encoding='utf-8'))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.append(node.module)
    offenders = [name for name in imported if name.split('.')[0] in FORBIDDEN_ROOTS]
    assert not offenders, f'{module} imports {offenders}; the worker may touch neither'


# --------------------------------------------------- the thread split

def test_the_worker_never_touches_the_context(make_jobs):
    """The context is where a bridge would be tempted to put a connection."""
    jobs = make_jobs()
    mine = Landmine()
    report = settle(jobs, jobs.start('Smoking causes cancer.', LABELS,
                                     context={'db': mine}))
    assert report['state'] == STATE_DONE
    assert report['context']['db'] is mine


def test_the_work_really_happens_on_another_thread(make_jobs):
    """Otherwise the whole exercise is decoration."""
    runtime = StubRuntime()
    jobs = make_jobs(runtime)
    settle(jobs, jobs.start('text', LABELS))
    assert runtime.calls[0]['thread'].startswith(jobs_module.THREAD_NAME_PREFIX)
    assert runtime.calls[0]['thread'] != threading.current_thread().name


def test_finish_runs_on_the_polling_thread_and_only_once(make_jobs):
    """Database work comes back to the caller, not left on the worker."""
    jobs = make_jobs()
    seen = []

    def finish(result):
        seen.append(threading.get_ident())
        return {'kept': len(result.proposals)}

    job_id = jobs.start('text', LABELS, finish=finish)
    first = settle(jobs, job_id)
    second = jobs.poll(job_id)
    assert seen == [threading.get_ident()]
    assert first == second == {'state': STATE_DONE, 'context': {}, 'result': {'kept': 1}}


def test_a_finish_that_raises_reports_a_failure_instead_of_escaping_poll(make_jobs):
    """``poll`` is called from a slot; an exception there is a crash."""
    jobs = make_jobs()
    calls = []

    def finish(result):
        calls.append(1)
        raise LookupError('subject 9 vanished')

    job_id = jobs.start('text', LABELS, context={'entry': 3}, finish=finish)
    report = settle(jobs, job_id)
    assert report == {
        'state': STATE_FAILED, 'context': {'entry': 3},
        'error': {'kind': 'extraction_failed', 'retryable': True,
                  'detail': 'LookupError: subject 9 vanished'},
    }
    assert jobs.poll(job_id) == report and calls == [1]


def test_a_finish_that_raises_a_typed_error_keeps_its_kind(make_jobs):
    jobs = make_jobs()

    def finish(result):
        raise RelationExtractionError(Kind.MODEL_CORRUPT, 'no')

    report = settle(jobs, jobs.start('text', LABELS, finish=finish))
    assert report['error']['kind'] == 'model_corrupt'


# --------------------------------------------------- what a poll returns

def test_a_finished_job_reports_its_proposals_and_its_context(make_jobs):
    jobs = make_jobs()
    report = settle(jobs, jobs.start('Smoking causes cancer.', LABELS,
                                     context={'entry_id': 7, 'token': 'a1'}))
    assert report['state'] == STATE_DONE
    assert report['context'] == {'entry_id': 7, 'token': 'a1'}
    assert report['ms'] == 12 and report['load_ms'] is None
    [p] = report['proposals']
    assert p == proposal().to_dict()
    assert p['relation_type_id'] == 1 and p['passage'] == 'Smoking causes cancer.'


def test_a_running_job_says_so_with_its_context(make_jobs):
    release = threading.Event()
    jobs = make_jobs(StubRuntime(behaviour=lambda *a: (release.wait(5),
                                                      ExtractionResult((), 1))[1]))
    job_id = jobs.start('text', LABELS, context={'entry_id': 1})
    assert jobs.poll(job_id) == {'state': STATE_RUNNING, 'context': {'entry_id': 1}}
    release.set()
    assert settle(jobs, job_id)['state'] == STATE_DONE


def test_a_typed_failure_arrives_with_its_kind_and_retryability(make_jobs):
    def fail(*_):
        raise RelationExtractionError(Kind.OUT_OF_MEMORY, 'out', detail='RuntimeError: ...')

    jobs = make_jobs(StubRuntime(behaviour=fail))
    report = settle(jobs, jobs.start('text', LABELS))
    assert report['error'] == {'kind': 'out_of_memory', 'detail': 'RuntimeError: ...',
                               'retryable': False}


def test_an_untyped_failure_arrives_as_the_generic_kind(make_jobs):
    def fail(*_):
        raise ZeroDivisionError('boom')

    jobs = make_jobs(StubRuntime(behaviour=fail))
    report = settle(jobs, jobs.start('text', LABELS))
    assert report['error']['kind'] == 'extraction_failed'
    assert report['error']['detail'] == 'ZeroDivisionError: boom'


# --------------------------------------------------- the id lifecycle

def test_an_id_never_issued_is_unknown_not_an_exception(make_jobs):
    report = make_jobs().poll('not-a-job')
    assert report == {'state': STATE_FAILED, 'context': {},
                      'error': {'kind': 'unknown_job', 'detail': None, 'retryable': False}}


def test_a_forgotten_job_is_unknown_and_an_uncollected_one_cannot_be_forgotten(make_jobs):
    release = threading.Event()
    jobs = make_jobs(StubRuntime(behaviour=lambda *a: (release.wait(5),
                                                      ExtractionResult((), 1))[1]))
    job_id = jobs.start('text', LABELS)
    jobs.forget(job_id)  # still running: must be ignored
    release.set()
    assert settle(jobs, job_id)['state'] == STATE_DONE
    jobs.forget(job_id)
    assert jobs.poll(job_id)['error']['kind'] == 'unknown_job'


def test_ids_are_distinct(make_jobs):
    jobs = make_jobs()
    ids = {jobs.start('text', LABELS) for _ in range(20)}
    assert len(ids) == 20


@pytest.mark.parametrize('labels', [
    (),
    (RelationLabel(1, 'causes'), RelationLabel(2, 'CAUSES')),
])
def test_a_malformed_request_raises_at_start_and_queues_nothing(make_jobs, labels):
    runtime = StubRuntime()
    jobs = make_jobs(runtime)
    with pytest.raises(ValueError):
        jobs.start('text', labels)
    assert runtime.calls == [] and jobs._jobs == {}


# --------------------------------------------------- the confidence setting

def test_the_students_threshold_reaches_the_runtime(make_jobs):
    """Owner, 2026-10-05: 80% by default, and the student may change it."""
    runtime = StubRuntime()
    jobs = make_jobs(runtime)
    settle(jobs, jobs.start('text', LABELS, threshold=0.65))
    settle(jobs, jobs.start('text', LABELS))
    assert [c['threshold'] for c in runtime.calls] == [0.65, None]


@pytest.mark.parametrize('bad', [0, -0.1, 1.5, 'high', float('nan')])
def test_an_impossible_threshold_raises_at_start_and_queues_nothing(make_jobs, bad):
    runtime = StubRuntime()
    jobs = make_jobs(runtime)
    with pytest.raises(ValueError, match='threshold'):
        jobs.start('text', LABELS, threshold=bad)
    assert runtime.calls == [] and jobs._jobs == {}


# --------------------------------------------------- one worker, and cancel

def test_a_second_job_queues_rather_than_races(make_jobs):
    active, peak = [0], [0]
    lock = threading.Lock()

    def slow(*_):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return ExtractionResult((), 1)

    jobs = make_jobs(StubRuntime(behaviour=slow))
    ids = [jobs.start('text', LABELS) for _ in range(3)]
    for job_id in ids:
        settle(jobs, job_id)
    assert peak[0] == 1


def test_cancelling_a_queued_job_means_it_never_runs(make_jobs):
    release = threading.Event()
    runtime = StubRuntime(behaviour=lambda *a: (release.wait(5), ExtractionResult((), 1))[1])
    jobs = make_jobs(runtime)
    first = jobs.start('first', LABELS)
    second = jobs.start('second', LABELS)
    assert jobs.cancel(second) is True
    release.set()
    assert settle(jobs, first)['state'] == STATE_DONE
    assert settle(jobs, second) == {'state': STATE_CANCELLED, 'context': {}}
    assert [c['text'] for c in runtime.calls] == ['first']


def test_cancelling_a_running_job_stops_it_and_reports_cancelled(make_jobs):
    started = threading.Event()

    def cooperative(text, labels, cancel):
        started.set()
        while not cancel.wait(0.01):
            pass
        raise ExtractionCancelled()

    jobs = make_jobs(StubRuntime(behaviour=cooperative))
    job_id = jobs.start('text', LABELS, context={'entry_id': 2})
    started.wait(5)
    assert jobs.cancel(job_id) is True
    assert settle(jobs, job_id) == {'state': STATE_CANCELLED, 'context': {'entry_id': 2}}


def test_cancelling_a_finished_or_unknown_job_changes_nothing(make_jobs):
    jobs = make_jobs()
    job_id = jobs.start('text', LABELS)
    report = settle(jobs, job_id)
    assert jobs.cancel(job_id) is False and jobs.cancel('nope') is False
    assert jobs.poll(job_id) == report


def test_shutdown_signals_a_running_pass_and_does_not_wait(make_jobs):
    started, stopped = threading.Event(), threading.Event()

    def cooperative(text, labels, cancel):
        started.set()
        cancel.wait(5)
        stopped.set()
        raise ExtractionCancelled()

    jobs = make_jobs(StubRuntime(behaviour=cooperative))
    jobs.start('text', LABELS)
    started.wait(5)
    t = time.monotonic()
    jobs.shutdown()
    assert time.monotonic() - t < 1.0
    assert stopped.wait(5)


# --------------------------------------------------- the watchdog

class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_a_pass_that_never_returns_is_reported_and_later_jobs_refused(make_jobs):
    """The thread leaks; the page is told something true instead of spinning."""
    clock = Clock()
    entered, never = threading.Event(), threading.Event()

    def wedged(*_):
        entered.set()
        never.wait(10)  # a native call that does not come back
        return ExtractionResult((), 1)

    runtime = StubRuntime(behaviour=wedged, timeout_s=60.0)
    jobs = make_jobs(runtime, clock=clock)
    job_id = jobs.start('text', LABELS, context={'entry_id': 4})
    entered.wait(5)

    clock.now = WEDGE_FACTOR * 60.0  # exactly at the bound: still running
    assert jobs.poll(job_id)['state'] == STATE_RUNNING

    clock.now += 0.1
    report = jobs.poll(job_id)
    assert report['state'] == STATE_FAILED and report['context'] == {'entry_id': 4}
    assert report['error']['kind'] == 'extraction_timeout'
    assert report['error']['detail']['wedged'] is True
    assert report['error']['detail']['stage'] == 'extraction'

    refused = jobs.start('another', LABELS)
    again = jobs.poll(refused)
    assert again['state'] == STATE_FAILED and again['error']['kind'] == 'extraction_timeout'
    assert len(runtime.calls) == 1  # nothing was queued behind the wedged worker
    never.set()


def test_a_load_that_never_returns_is_reported_against_the_load_ceiling(make_jobs):
    clock = Clock()
    entered, never = threading.Event(), threading.Event()

    class LoadsForever(StubRuntime):
        def extract(self, text, labels, *, cancel=None, timeout_s=None, threshold=None,
                on_pass_start=None):
            entered.set()
            never.wait(10)  # stuck before the pass begins
            return ExtractionResult((), 1)

    jobs = make_jobs(LoadsForever(), clock=clock)
    job_id = jobs.start('text', LABELS)
    entered.wait(5)
    clock.now = LOAD_CEILING_S - 1
    assert jobs.poll(job_id)['state'] == STATE_RUNNING
    clock.now = LOAD_CEILING_S + 1
    report = jobs.poll(job_id)
    assert report['error']['detail']['stage'] == 'load'
    never.set()


_WEDGED_EXIT_SCRIPT = r"""
import sys, threading, time
sys.path.insert(0, 'src')
from app.relation_extraction.jobs import RelationJobs
from app.relation_extraction.runtime import RelationLabel
never = threading.Event()
class Stuck:
    timeout_s = 60.0
    def extract(self, text, labels, *, cancel=None, timeout_s=None, threshold=None,
                on_pass_start=None):
        never.wait()  # ignores cancel, like a native call that never returns
jobs = RelationJobs(Stuck())
jobs.start('x', (RelationLabel(1, 'causes'),))
time.sleep(0.2)
jobs.shutdown()
print('left main', flush=True)
"""


def test_a_wedged_worker_does_not_hold_the_process_at_exit():
    """After a wedge the student will quit WIMI; the quit must complete.

    With ``ThreadPoolExecutor`` this script was still alive when killed at
    20 s, because ``concurrent.futures`` joins its workers at interpreter exit
    regardless of ``shutdown(wait=False)``. The daemon worker exits in about a
    second.
    """
    done = subprocess.run([sys.executable, '-c', _WEDGED_EXIT_SCRIPT],
                          cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0 and 'left main' in done.stdout, done.stderr


def test_a_queued_job_is_not_mistaken_for_a_wedged_one(make_jobs):
    """Time spent waiting behind another job is not the job's own time."""
    clock = Clock()
    release = threading.Event()
    jobs = make_jobs(StubRuntime(behaviour=lambda *a: (release.wait(5),
                                                      ExtractionResult((), 1))[1]),
                     clock=clock)
    jobs.start('first', LABELS)
    second = jobs.start('second', LABELS)
    clock.now = 10 * LOAD_CEILING_S
    assert jobs.poll(second)['state'] == STATE_RUNNING
    release.set()
