"""Bridge tests for ``RelationExtractionBridgeMixin`` -- #60.

Status and the model download. Extraction and the write path are not built
yet, and two of their inputs are open product questions, so they are not
asserted here as absences either.

Three of these tests exist because the thing they check has no symptom
---------------------------------------------------------------------
* **A partial model must not read as READY.** This model is eight files and
  ``model_spec.model_dir()`` *creates* the directory, so a status built on
  "does the path exist" would report ready forever on a machine holding none
  of the weights -- no error, no log line, and a download button that never
  appears. The two composition tests below are the whole guard.
* **Looking must not hash.** ``verify_dir`` is monkeypatched to raise, so a
  future status slot that reaches for the honest check fails here instead of
  costing a student 845 MB of hashing to draw a line of text (#147).
* **A named failure is data, not ``success=false``.** ``api._callBridge``
  throws on a failed response and discards ``data``, so a kind returned that
  way reaches the page as a bare sentence and the page cannot branch. A test
  that only checked ``success is False`` would pass against exactly the bug.

No ``QApplication``: slots are called as plain methods, as every other
``tests/app/test_bridge_*.py`` does.

This machine has no relations runtime installed (agents must not install into
``.venv``), so ``_missing_runtime_packages`` is monkeypatched wherever a test
needs a particular state. A test that did not would assert whatever happens to
be in the venv.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Optional

import pytest

from app.bridge import DatabaseBridge
from app.relation_extraction import availability, model_spec
from app.relation_extraction.download import InstallResult
from app.relation_extraction.errors import (
    RelationExtractionError,
    RelationExtractionErrorKind as Kind,
)

pytestmark = pytest.mark.unit


def payload(response: str) -> dict:
    """The ``data`` of a successful response, or a failure naming its error.

    Unwrapping through one helper is what makes a ``success=false`` show its
    sentence instead of a ``KeyError`` on ``data`` three lines later.
    """
    parsed = json.loads(response)
    assert parsed['success'] is True, parsed.get('error')
    return parsed['data']


# ==================== fixtures ====================

class _Master:
    """Stands in for ``MasterDatabase``: the status slot reads one attribute.

    A real one would open ``users.db`` and run migrations for a test about
    eight ``stat`` calls.
    """

    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir


@pytest.fixture
def app_data(tmp_path):
    base = tmp_path / 'app_data'
    base.mkdir()
    return base


@pytest.fixture
def bridge(app_data):
    b = DatabaseBridge(master_db=_Master(app_data), user_db=None)
    yield b
    b.shutdown_relation_extraction()


@pytest.fixture
def runtime_present(monkeypatch):
    """A machine whose runtime packages are all findable."""
    monkeypatch.setattr(availability, '_missing_runtime_packages', lambda: ())


@pytest.fixture
def no_hashing(monkeypatch):
    """Any hash of the model during a status read is a failure."""
    def explode(*_args, **_kwargs):
        raise AssertionError(
            'the status slot hashed the model. 845 MB to draw a line of text '
            'is #147 in another costume -- use model_spec.missing_files.')
    monkeypatch.setattr(model_spec, 'verify_dir', explode)
    monkeypatch.setattr(model_spec, 'sha256_file', explode)


def _installed(monkeypatch, missing=()):
    monkeypatch.setattr(model_spec, 'missing_files', lambda _dir: tuple(missing))


def _await(bridge, job_id, timeout_s: float = 10.0) -> dict:
    """Poll the way the page will, against a wall-clock deadline.

    Not a tight spin: the download runs on a real worker thread, and a loop
    bounded by iterations reported "never finished" while it was still going
    in ``test_foldersync_threading.py``.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        report = payload(bridge.pollRelationModelDownload(job_id))
        if report['state'] != 'running':
            return report
        time.sleep(0.01)
    raise AssertionError(f'download {job_id} never finished within {timeout_s:g}s')


# ==================== status: the five states ====================

def test_a_checkout_without_the_runtime_asks_for_a_pip_command(
        bridge, monkeypatch, no_hashing):
    """The default state of this machine, and it must not read as "broken"."""
    monkeypatch.setattr(
        availability, '_missing_runtime_packages', lambda: ('torch', 'gliner2'))
    data = payload(bridge.getRelationExtractionStatus())

    assert data['state'] == 'dev_runtime_missing'
    assert data['ready'] is False
    assert data['actionable'] is True, 'a pip command is a real next step'
    assert data['missing'] == ['torch', 'gliner2']


def test_a_runtime_with_no_weights_is_actionable(
        bridge, monkeypatch, runtime_present, no_hashing):
    _installed(monkeypatch, model_spec.MODEL_FILE_NAMES)
    data = payload(bridge.getRelationExtractionStatus())

    assert data['state'] == 'model_not_downloaded'
    assert data['actionable'] is True, 'the download button belongs here'
    assert data['model']['installed'] is False
    assert data['model']['bytes_still_needed'] == model_spec.TOTAL_BYTES


def test_everything_present_is_ready(
        bridge, monkeypatch, runtime_present, no_hashing):
    _installed(monkeypatch)
    data = payload(bridge.getRelationExtractionStatus())

    assert data['state'] == 'ready'
    assert data['ready'] is True
    assert data['actionable'] is False
    assert data['model']['installed'] is True
    assert data['model']['missing_files'] == []
    assert data['model']['bytes_still_needed'] == 0


def test_one_missing_file_is_not_ready(
        bridge, monkeypatch, runtime_present, no_hashing):
    """The symptomless one. Seven of eight files is not a model.

    ``model_dir()`` creates the directory, so a status that asked whether the
    path existed would answer ``ready`` here -- permanently, with no error
    anywhere, on a machine that cannot extract a single relation.
    """
    _installed(monkeypatch, ('model.safetensors',))
    data = payload(bridge.getRelationExtractionStatus())

    assert data['state'] == 'model_not_downloaded'
    assert data['model']['installed'] is False
    assert data['model']['missing_files'] == ['model.safetensors']
    assert 0 < data['model']['bytes_still_needed'] < model_spec.TOTAL_BYTES, (
        'the remaining bytes are one file, not the whole set and not nothing')


def test_the_model_is_reported_even_with_no_runtime(
        bridge, monkeypatch, no_hashing):
    """"How big is this?" is answerable on the default artifact.

    The two facts are independent, and a student deciding whether to fetch the
    larger download is exactly who asks.
    """
    monkeypatch.setattr(
        availability, '_missing_runtime_packages', lambda: ('torch',))
    _installed(monkeypatch, model_spec.MODEL_FILE_NAMES)
    data = payload(bridge.getRelationExtractionStatus())

    assert data['state'] == 'dev_runtime_missing'
    assert data['model']['total_bytes'] == model_spec.TOTAL_BYTES
    assert data['model']['total_mb'] == pytest.approx(845.1, abs=0.1)


def test_the_licence_is_in_the_payload(bridge, no_hashing):
    """Settings states what the weights are under; the About panel needs it."""
    data = payload(bridge.getRelationExtractionStatus())

    assert data['licence']['model'] == 'Apache-2.0'
    assert data['licence']['base'] == 'MIT'
    assert data['licence']['revision'] == model_spec.MODEL_REVISION


def test_no_app_data_reports_the_runtime_rather_than_a_failure(
        monkeypatch, runtime_present, no_hashing):
    """A bridge with no master database is a real state, not an error.

    And the model is reported as "not located", never as "no runtime": those
    have different fixes, the same split ``_stt_status_without_app_data``
    makes.
    """
    bridge = DatabaseBridge(master_db=None, user_db=None)
    try:
        data = payload(bridge.getRelationExtractionStatus())
    finally:
        bridge.shutdown_relation_extraction()

    assert data['state'] == 'model_not_downloaded'
    assert data['model']['path'] is None
    assert data['model']['installed'] is False


# ==================== the download ====================

def _fake_install(*, bytes_downloaded=1024, files=('config.json',)):
    """An ``install_model`` that reports progress and succeeds."""
    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        for index, name in enumerate(files, start=1):
            if on_file is not None:
                on_file(name, index, len(files))
            if progress is not None:
                progress(index * 100, model_spec.TOTAL_BYTES)
        return InstallResult(installed=tuple(files), skipped=(),
                             bytes_downloaded=bytes_downloaded)
    return install


def test_a_download_runs_and_reports_what_it_installed(bridge, monkeypatch):
    from app.relation_extraction import download
    monkeypatch.setattr(download, 'install_model', _fake_install())

    started = payload(bridge.startRelationModelDownload())
    assert started['already_running'] is False
    assert started['file_count'] == len(model_spec.MODEL_FILE_NAMES)

    report = _await(bridge, started['job_id'])
    assert report['state'] == 'done'
    assert report['installed'] == ['config.json']
    assert report['bytes_downloaded'] == 1024
    assert report['job_id'] == started['job_id']


def test_progress_starts_at_what_is_already_on_disk(bridge, monkeypatch):
    """A resumed download must not crawl from 0% through ground it has covered.

    Both numbers come from the pin table, so neither is ever ``null`` -- the
    difference from #59, where a response with no ``Content-Length`` is legal
    and a page dividing by the total breaks.
    """
    from app.relation_extraction import download
    held = threading.Event()
    monkeypatch.setattr(model_spec, 'missing_files',
                        lambda _dir: ('model.safetensors',))

    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        held.wait(5.0)
        return InstallResult()
    monkeypatch.setattr(download, 'install_model', install)

    started = payload(bridge.startRelationModelDownload())
    try:
        first = payload(bridge.pollRelationModelDownload(started['job_id']))
        assert first['total'] == model_spec.TOTAL_BYTES
        assert first['bytes'] > 0, 'seven of eight files are already here'
        assert first['bytes'] < model_spec.TOTAL_BYTES
    finally:
        held.set()
    _await(bridge, started['job_id'])


def test_a_second_press_polls_the_transfer_in_flight(bridge, monkeypatch):
    """One worker. A double press must not queue 845 MB behind 845 MB."""
    from app.relation_extraction import download
    held = threading.Event()

    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        held.wait(5.0)
        return InstallResult()
    monkeypatch.setattr(download, 'install_model', install)

    first = payload(bridge.startRelationModelDownload())
    second = payload(bridge.startRelationModelDownload())
    try:
        assert second['already_running'] is True
        assert second['job_id'] == first['job_id']
    finally:
        held.set()
    _await(bridge, first['job_id'])


def test_a_failure_arrives_as_data_with_its_kind(bridge, monkeypatch):
    """The module docstring's central rule, and the one a page branches on."""
    from app.relation_extraction import download

    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        raise RelationExtractionError(
            Kind.DOWNLOAD_FAILED, 'the link went away', detail='Errno 101')
    monkeypatch.setattr(download, 'install_model', install)

    report = _await(bridge, payload(bridge.startRelationModelDownload())['job_id'])
    assert report['state'] == 'failed'
    assert report['error']['kind'] == 'download_failed'
    assert report['error']['retryable'] is True
    assert report['code'] == 'download_failed'
    assert report['message'] == 'Errno 101'


def test_an_unnamed_exception_still_arrives_as_a_kind(bridge, monkeypatch):
    """Anything the taxonomy does not name must still be renderable."""
    from app.relation_extraction import download

    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        raise RuntimeError('something nobody classified')
    monkeypatch.setattr(download, 'install_model', install)

    report = _await(bridge, payload(bridge.startRelationModelDownload())['job_id'])
    assert report['state'] == 'failed'
    assert report['error']['kind'] == 'download_failed'
    assert 'something nobody classified' in report['error']['detail']


def test_an_unknown_job_id_is_named_in_its_own_failure(bridge):
    """#171: a payload saying a job is unknown without saying which job."""
    report = payload(bridge.pollRelationModelDownload('nope'))

    assert report['job_id'] == 'nope'
    assert report['state'] == 'failed'
    assert report['error']['kind'] == 'unknown_job'
    assert report['error']['retryable'] is False


def test_a_finished_download_is_still_pollable(bridge, monkeypatch):
    """A page polls once more before it notices the first terminal answer."""
    from app.relation_extraction import download
    monkeypatch.setattr(download, 'install_model', _fake_install())

    job_id = payload(bridge.startRelationModelDownload())['job_id']
    _await(bridge, job_id)
    again = payload(bridge.pollRelationModelDownload(job_id))

    assert again['state'] == 'done', (
        'forgetting on the first terminal read turns the next poll into '
        'unknown_job, which the page renders as a failure')


def test_the_running_download_is_in_the_status(bridge, monkeypatch, no_hashing):
    """Settings reopened mid-download finds the id it needs in order to poll.

    Without this the page can only wait the transfer out, which is #171 again
    one level up: the bridge outlives the page, the page's local does not.
    """
    from app.relation_extraction import download
    held = threading.Event()

    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        held.wait(5.0)
        return InstallResult()
    monkeypatch.setattr(download, 'install_model', install)

    started = payload(bridge.startRelationModelDownload())
    try:
        data = payload(bridge.getRelationExtractionStatus())
        assert data['download'] is not None
        assert data['download']['job_id'] == started['job_id']
        assert data['download']['state'] == 'running'
    finally:
        held.set()
    _await(bridge, started['job_id'])

    assert payload(bridge.getRelationExtractionStatus())['download'] is None, (
        'a finished download is not a running one')


# ==================== cancel, and what it keeps ====================

def test_cancelling_keeps_the_partial_files(bridge, monkeypatch):
    """The deliberate difference from #59's cancel. 845 MB decides it.

    ``cancelModelDownload`` deletes the ``.part`` because resuming something
    the student said no to would be wrong. Here a cancel is far more often
    "not now" than "never", and refetching 800 MB to honour the stricter
    reading costs the student more than it protects them.
    """
    from app.relation_extraction import download
    part = model_spec.part_path(
        model_spec.model_dir(bridge._relations_app_data_dir()) / 'model.safetensors')
    part.write_bytes(b'half a model')
    seen: list[Optional[threading.Event]] = []

    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        seen.append(cancel)
        for _ in range(500):
            if cancel is not None and cancel.is_set():
                raise RelationExtractionError(
                    Kind.DOWNLOAD_CANCELLED, 'cancelled before finishing')
            time.sleep(0.01)
        return InstallResult()
    monkeypatch.setattr(download, 'install_model', install)

    job_id = payload(bridge.startRelationModelDownload())['job_id']
    while not seen:
        time.sleep(0.01)
    assert payload(bridge.cancelRelationModelDownload(job_id))['cancelled'] is True

    report = _await(bridge, job_id)
    assert report['state'] == 'failed'
    assert report['error']['kind'] == 'download_cancelled'
    assert part.is_file(), 'the next attempt resumes; that is the whole point'


def test_discarding_removes_the_partials_and_leaves_installed_files(bridge):
    """The explicit "start over". Uninstalling is a different action."""
    base = model_spec.model_dir(bridge._relations_app_data_dir())
    part = model_spec.part_path(base / 'model.safetensors')
    part.write_bytes(b'half a model')
    kept = base / 'config.json'
    kept.write_bytes(b'{}')

    data = payload(bridge.discardRelationModelDownload())

    assert data['running'] is False
    assert data['discarded'] == ['model.safetensors']
    assert not part.exists()
    assert kept.is_file(), 'an installed file is at its pinned size; deleting it is uninstalling'


def test_discarding_refuses_while_a_download_is_running(bridge, monkeypatch):
    """Rather than deleting the ``.part`` the worker is writing into."""
    from app.relation_extraction import download
    held = threading.Event()

    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        held.wait(5.0)
        return InstallResult()
    monkeypatch.setattr(download, 'install_model', install)

    job_id = payload(bridge.startRelationModelDownload())['job_id']
    try:
        data = payload(bridge.discardRelationModelDownload())
        assert data['running'] is True
        assert data['discarded'] == []
    finally:
        held.set()
    _await(bridge, job_id)


def test_cancelling_an_unknown_job_is_not_an_error(bridge):
    report = payload(bridge.cancelRelationModelDownload('nope'))
    assert report['cancelled'] is False


def test_shutdown_is_idempotent_and_cancels_what_is_running(bridge, monkeypatch):
    from app.relation_extraction import download
    held = threading.Event()
    cancels: list[threading.Event] = []

    def install(app_data_dir, *, cancel=None, progress=None, on_file=None):
        cancels.append(cancel)
        held.wait(5.0)
        return InstallResult()
    monkeypatch.setattr(download, 'install_model', install)

    bridge.startRelationModelDownload()
    while not cancels:
        time.sleep(0.01)
    bridge.shutdown_relation_extraction()
    bridge.shutdown_relation_extraction()
    held.set()

    assert cancels[0].is_set()
