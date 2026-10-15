"""The Anki job layer: off the main thread, finished on poll, profile-checked (#784).

Two kinds of test, as for the speech jobs:

* **behavioural** -- a job runs on the worker against the fake AnkiConnect,
  its finish runs on the polling thread, a profile switch suppresses the
  finish, and a slow Anki does not hold ``start`` or ``poll``;
* **static** -- the worker body is ``client.py`` (and ``errors.py``), and the
  only way to prove a module cannot touch Qt or a database is to prove it
  does not import them.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from app.anki import client as anki_client
from app.anki import errors as anki_errors
from app.anki import fsrs as anki_fsrs
from app.anki.client import AnkiConnectClient
from app.anki.errors import AnkiError, AnkiErrorKind
from app.anki.jobs import STATE_DONE, STATE_FAILED, STATE_RUNNING, AnkiJobs
from tests._fake_ankiconnect import FakeAnkiConnect

FORBIDDEN_ROOTS = ('PyQt6', 'sqlite3', 'database')


@pytest.fixture
def anki():
    with FakeAnkiConnect() as fake:
        yield fake


class Profile:
    """Stands in for the bridge's notion of which profile is open."""

    def __init__(self, user_id):
        self.user_id = user_id

    def __call__(self):
        return self.user_id


@pytest.fixture
def profile():
    return Profile(1)


@pytest.fixture
def jobs(profile):
    j = AnkiJobs(current_user_id=profile)
    yield j
    j.shutdown()


def _wait(jobs: AnkiJobs, job_id: str, deadline_s: float = 5.0) -> dict:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        report = jobs.poll(job_id)
        if report['state'] != STATE_RUNNING:
            return report
        time.sleep(0.01)
    raise AssertionError(f'job {job_id} still running after {deadline_s} s')


class TestBehaviour:
    def test_work_runs_on_the_worker_and_finish_on_the_poller(self, jobs, anki):
        threads = {}

        def work(client):
            threads['work'] = threading.current_thread().name
            return client.version()

        def finish(result):
            threads['finish'] = threading.current_thread().name
            return {'version': result}

        job_id = jobs.start(work, client_factory=lambda: AnkiConnectClient(anki.port),
                            finish=finish, context={'kind': 'ping'}, user_id=1)
        report = _wait(jobs, job_id)
        assert report == {'state': STATE_DONE, 'result': {'version': 6},
                          'context': {'kind': 'ping'}}
        assert threads['work'].startswith('wimi-anki')
        assert threads['finish'] == threading.current_thread().name

    def test_finish_runs_once_however_often_it_is_polled(self, jobs, anki):
        calls = []
        job_id = jobs.start(lambda c: c.version(),
                            client_factory=lambda: AnkiConnectClient(anki.port),
                            finish=lambda r: calls.append(r) or len(calls), user_id=1)
        first = _wait(jobs, job_id)
        assert jobs.poll(job_id) == first
        assert calls == [6]

    def test_an_anki_failure_reaches_the_page_as_its_kind(self, jobs):
        port = _closed_port()
        finished = []
        job_id = jobs.start(lambda c: c.version(),
                            client_factory=lambda: AnkiConnectClient(port),
                            finish=finished.append, user_id=1)
        report = _wait(jobs, job_id)
        assert report['state'] == STATE_FAILED
        assert report['error']['kind'] == AnkiErrorKind.UNAVAILABLE.value
        assert report['error']['retryable'] is True
        assert finished == [], 'a failed fetch must not reach the finish phase'

    def test_anything_else_is_failed_with_the_message(self, jobs, anki):
        def work(client):
            raise RuntimeError('boom')
        report = _wait(jobs, jobs.start(work, client_factory=lambda: AnkiConnectClient(anki.port)))
        assert report['error']['kind'] == AnkiErrorKind.FAILED.value
        assert report['error']['detail'] == 'boom'

    def test_a_profile_switch_suppresses_the_finish(self, jobs, anki, profile):
        finished = []
        gate = threading.Event()

        def work(client):
            gate.wait(5)
            return client.version()

        job_id = jobs.start(work, client_factory=lambda: AnkiConnectClient(anki.port),
                            finish=finished.append, user_id=1)
        profile.user_id = 2          # the student switched profile mid-job
        gate.set()
        report = _wait(jobs, job_id)
        assert report['state'] == STATE_FAILED
        assert report['error']['kind'] == AnkiErrorKind.PROFILE_CHANGED.value
        assert finished == []

    def test_control_the_same_job_finishes_when_the_profile_stays(self, jobs, anki):
        finished = []
        job_id = jobs.start(lambda c: c.version(),
                            client_factory=lambda: AnkiConnectClient(anki.port),
                            finish=finished.append, user_id=1)
        assert _wait(jobs, job_id)['state'] == STATE_DONE
        assert finished == [6]

    def test_a_slow_anki_holds_neither_start_nor_poll(self, jobs, anki):
        """The plugin froze the window; this is the property that replaces it."""
        anki.delay_s = 1.5
        t0 = time.monotonic()
        job_id = jobs.start(lambda c: c.version(),
                            client_factory=lambda: AnkiConnectClient(anki.port), user_id=1)
        assert jobs.poll(job_id)['state'] == STATE_RUNNING
        assert time.monotonic() - t0 < 0.5
        assert _wait(jobs, job_id)['state'] == STATE_DONE

    def test_the_client_is_built_on_the_worker(self, jobs, anki):
        built_on = []

        def factory():
            built_on.append(threading.current_thread().name)
            return AnkiConnectClient(anki.port)

        _wait(jobs, jobs.start(lambda c: c.version(), client_factory=factory))
        assert built_on[0].startswith('wimi-anki')

    def test_an_unknown_job_is_a_report_not_an_exception(self, jobs):
        report = jobs.poll('nope')
        assert report['state'] == STATE_FAILED
        assert report['error']['kind'] == AnkiErrorKind.UNKNOWN_JOB.value

    def test_forget_drops_only_collected_jobs(self, jobs, anki):
        gate = threading.Event()
        running = jobs.start(lambda c: gate.wait(5),
                             client_factory=lambda: AnkiConnectClient(anki.port))
        jobs.forget(running)
        assert jobs.poll(running)['state'] == STATE_RUNNING
        gate.set()
        _wait(jobs, running)
        jobs.forget(running)
        assert jobs.poll(running)['error']['kind'] == AnkiErrorKind.UNKNOWN_JOB.value

    def test_after_shutdown_no_finish_runs(self, profile, anki):
        jobs = AnkiJobs(current_user_id=profile)
        finished = []
        job_id = jobs.start(lambda c: c.version(),
                            client_factory=lambda: AnkiConnectClient(anki.port),
                            finish=finished.append)
        jobs.shutdown()
        assert jobs.poll(job_id)['error']['kind'] == AnkiErrorKind.UNKNOWN_JOB.value
        assert finished == []


def _closed_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


# --------------------------------------------------------- the static invariant

#: The modules a ``work`` body reaches: the client, what it raises, and the
#: pure estimates a worker may compute. ``jobs.py`` itself is not here -- it
#: runs ``finish`` on the polling thread by design -- but it must not import
#: the database either, so it is checked separately below.
WORKER_MODULES = (anki_client, anki_errors, anki_fsrs)


def _imports(module) -> list[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize('module', WORKER_MODULES, ids=lambda m: m.__name__)
def test_the_worker_body_imports_no_qt_and_no_database(module):
    offenders = [n for n in _imports(module) if n.split('.')[0] in FORBIDDEN_ROOTS]
    assert not offenders, f'{module.__name__} imports {offenders}'


def test_the_job_layer_imports_no_database():
    from app.anki import jobs as anki_jobs
    offenders = [n for n in _imports(anki_jobs) if n.split('.')[0] in FORBIDDEN_ROOTS]
    assert not offenders, f'app.anki.jobs imports {offenders}'


def test_the_static_check_can_fail(tmp_path, monkeypatch):
    """Control: the reader sees an import when one is there."""
    probe = tmp_path / 'probe.py'
    probe.write_text('import sqlite3\nfrom database.domains import x\n', encoding='utf-8')

    class Module:
        __file__ = str(probe)
        __name__ = 'probe'

    found = [n for n in _imports(Module) if n.split('.')[0] in FORBIDDEN_ROOTS]
    assert found == ['sqlite3', 'database.domains']
