"""Bridge tests for ``SttBridgeMixin`` (#59).

``src/app/stt/`` is covered by its own tests; these prove the seam between
it and the page -- the JSON contract, the guard paths, and the three things
that would be silent if they broke.

**Every slot is exercised twice**, once with ``user_db=None`` (the profile
picker runs before a database is attached) and once against a real one. That
is the task's stated done-when and it is not ceremony: a slot that assumed a
profile was open would fail on the picker, where nobody is looking.

**A named failure is data, not a failed response.** ``_callBridge`` throws on
``success=false`` and drops ``data``, so an ``SttError`` returned that way
reaches the page with no ``kind`` -- and §7 is entirely about branching on
the kind. ``test_a_named_capture_failure_is_data`` is the guard.

**The four staleness fields come back.** The page compares the entry id, the
field key and the token against what it is still looking at before inserting
anything, and it can only do that if what it sent comes back (§3.5). Both
dictation targets are *required* fields under D1, so a stale transcript
corrupts something that gates the save button.

**The worker touches no database.** After ``stopRecording`` hands the work
over, ``user_db`` is replaced with a ``Landmine`` that raises on any
attribute access -- the same device ``tests/app/test_foldersync_threading.py``
uses, for the same invariant in ``base_db.py``.

Markers: ``@pytest.mark.unit`` -- no ``QApplication``, no microphone, no
network. Every microphone and every subprocess here is a fake.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Generator

import pytest

from app.bridge import DatabaseBridge
from app.stt.errors import SttError, SttErrorKind
from app.stt.jobs import TranscriptionJobs
from app.stt.runtime import TranscriptionResult
from database.master_db import MasterDatabase
from database.user_db import UserDatabase

pytestmark = pytest.mark.unit


EXAM = 'STT Exam'


# ==================== Fixtures ====================

@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except OSError:
        pass


@pytest.fixture
def temp_master_db_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def user_db(temp_db_path: Path) -> Generator[UserDatabase, None, None]:
    db = UserDatabase(db_path=temp_db_path, user_id=1, username='stt_user')
    yield db
    db.close()


@pytest.fixture
def master_db(temp_master_db_dir: Path) -> Generator[MasterDatabase, None, None]:
    db = MasterDatabase(data_dir=temp_master_db_dir, error_logger=None)
    yield db
    db.close()


@pytest.fixture
def bridge(user_db: UserDatabase, master_db: MasterDatabase):
    b = DatabaseBridge(master_db=master_db, user_db=user_db)
    yield b
    b.shutdown_stt()


@pytest.fixture
def bridge_no_user(master_db: MasterDatabase):
    b = DatabaseBridge(master_db=master_db, user_db=None)
    yield b
    b.shutdown_stt()


@pytest.fixture
def bare_bridge():
    """No master database either -- the shape a unit test builds by hand."""
    b = DatabaseBridge(master_db=None, user_db=None)
    yield b
    b.shutdown_stt()


# ==================== Fakes ====================

class _Signal:
    """Just enough of a ``pyqtSignal`` for ``connect``."""

    def __init__(self) -> None:
        self.slots = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self.slots):
            slot(*args)


class FakeRecording:
    def __init__(self, path: Path, *, peak: float = 0.4, capture_error=None) -> None:
        self.path = path
        self.sample_rate = 16_000
        self.channels = 1
        self.sample_width = 2
        self.frames = 16_000
        self.peak = peak
        self.rms = peak / 2
        self.degraded_format = False
        self.capture_error = capture_error

    @property
    def duration_seconds(self) -> float:
        return self.frames / float(self.sample_rate)


class FakeFormat:
    sample_rate = 16_000
    channels = 1
    degraded = False


class FakeDevice:
    id = 'fake-mic'
    label = 'Fake Microphone'
    is_default = True


class FakeRecorder:
    """Stands in for ``AudioRecorder``. Writes a real (tiny) file."""

    #: Set to raise from ``start``; the bridge must report it as data.
    start_error: SttError | None = None
    #: Set to raise from ``stop`` -- ``no_audio_captured`` is the real case.
    stop_error: SttError | None = None

    def __init__(self, *, preferred_device_id=None, **_kwargs) -> None:
        self.preferred_device_id = preferred_device_id
        self.levelChanged = _Signal()
        self.errorOccurred = _Signal()
        self.is_recording = False
        self.device = FakeDevice()
        self.device_choice_honoured = True
        self.path: Path | None = None
        self.aborted = False

    def start(self, path):
        if self.start_error is not None:
            raise self.start_error
        self.path = Path(path)
        self.path.write_bytes(b'RIFF....WAVEfake')
        self.is_recording = True
        return FakeFormat()

    def stop(self):
        self.is_recording = False
        if self.stop_error is not None:
            raise self.stop_error
        return FakeRecording(self.path)

    def abort(self):
        self.is_recording = False
        self.aborted = True
        if self.path is not None:
            Path(self.path).unlink(missing_ok=True)


class FakeRuntime:
    """A ``WhisperRuntime`` that returns a canned transcript.

    Records the thread it ran on and the prompt it was handed, which is how
    the threading and priming tests see inside the worker.
    """

    def __init__(self, text: str = 'the patient has hypertension') -> None:
        self.text = text
        self.prompts: list[str] = []
        self.threads: list[str] = []
        self.audio: list[Path] = []
        self.delay = 0.0

    def transcribe(self, audio_path, *, prompt='', delete_audio=True):
        self.threads.append(threading.current_thread().name)
        self.prompts.append(prompt)
        self.audio.append(Path(audio_path))
        if self.delay:
            time.sleep(self.delay)
        if delete_audio:
            Path(audio_path).unlink(missing_ok=True)
        return TranscriptionResult(text=self.text, ms=12)


class Landmine:
    """Any attribute access is a failure, ``repr`` during a traceback included."""

    def __getattr__(self, name):
        # "a worker", not "the transcription worker": both of this mixin's
        # executors are held to this, and the download one reaches it too.
        raise AssertionError(
            f'a speech worker thread touched the database: user_db.{name}. '
            f'Database work belongs on the calling thread -- see base_db.py.'
        )


def ok(response: str) -> dict:
    """Unwrap a successful envelope, failing loudly on ``success=false``."""
    parsed = json.loads(response)
    assert parsed['success'] is True, parsed.get('error')
    return parsed.get('data')


def failed(response: str) -> str:
    parsed = json.loads(response)
    assert parsed['success'] is False, parsed
    return parsed['error']


def install_fake_recorder(monkeypatch) -> type:
    monkeypatch.setattr('app.stt.recorder.AudioRecorder', FakeRecorder)
    return FakeRecorder


def await_state(bridge, job_id: str, *, timeout: float = 5.0) -> dict:
    """Poll against a wall clock. A tight loop outruns the worker."""
    deadline = time.monotonic() + timeout
    report = ok(bridge.pollTranscription(job_id))
    while report['state'] == 'running' and time.monotonic() < deadline:
        time.sleep(0.02)
        report = ok(bridge.pollTranscription(job_id))
    return report


CONTEXT = {
    'entry_id': 77,
    'field_key': 'explanation',
    'token': 9,
    'subject_ids': [],
}


# ==================== Every slot, with no user database ====================

class TestGuardPaths:
    """The profile picker runs before a database is attached."""

    def test_status_answers_with_no_user_db(self, bridge_no_user):
        data = ok(bridge_no_user.getSttStatus())
        assert data['priming_enabled'] is True
        assert data['show_first_use_notice'] is True
        assert data['model_size']
        assert 'engine_ready' in data and 'model_ready' in data
        assert data['recording'] is False
        assert set(data['mic']) >= {'permission', 'devices', 'ready'}

    def test_settings_answer_with_no_user_db(self, bridge_no_user):
        data = ok(bridge_no_user.getSttSettings())
        assert data['stt_model_size'] is None
        assert data['stt_input_device_id'] is None
        assert data['resolved_model_size'] == data['default_model_size']
        assert data['available_models'], 'the pin table should offer sizes'

    def test_update_settings_refuses_with_no_user_db(self, bridge_no_user):
        assert 'No user database' in failed(
            bridge_no_user.updateSttSettings('{"stt_priming_enabled": false}'))

    def test_permission_answers_with_no_user_db(self, bridge_no_user):
        data = ok(bridge_no_user.requestMicrophonePermission())
        assert data['permission'] in ('granted', 'denied', 'undetermined')

    def test_level_answers_with_no_user_db(self, bridge_no_user):
        data = ok(bridge_no_user.getRecordingLevel())
        assert data == {'recording': False, 'rms': 0.0, 'peak': 0.0,
                        'stream_error': None}

    def test_cancel_recording_is_idempotent_with_no_user_db(self, bridge_no_user):
        assert ok(bridge_no_user.cancelRecording()) == {
            'recording': False, 'cancelled': False}

    def test_record_and_transcribe_with_no_user_db(self, bridge_no_user, monkeypatch):
        """Recording needs a microphone, not a profile. Priming is what
        needs the database, and its absence costs the prompt and nothing
        else."""
        install_fake_recorder(monkeypatch)
        runtime = FakeRuntime()
        bridge_no_user._stt_jobs_obj = TranscriptionJobs(runtime=runtime)

        assert ok(bridge_no_user.startRecording(''))['recording'] is True
        started = ok(bridge_no_user.stopRecording(json.dumps(CONTEXT)))
        assert started['job_id']
        assert started['primed'] is False
        report = await_state(bridge_no_user, started['job_id'])
        assert report['state'] == 'done'
        assert report['text'] == runtime.text

    def test_stop_without_start_with_no_user_db(self, bridge_no_user):
        data = ok(bridge_no_user.stopRecording(json.dumps(CONTEXT)))
        assert data['job_id'] is None
        assert data['error']['kind'] == SttErrorKind.CAPTURE_FAILED.value

    def test_poll_unknown_job_with_no_user_db(self, bridge_no_user):
        bridge_no_user._stt_jobs_obj = TranscriptionJobs(runtime=FakeRuntime())
        report = ok(bridge_no_user.pollTranscription('nope'))
        assert report['state'] == 'failed'
        assert report['error']['kind'] == SttErrorKind.UNKNOWN_JOB.value

    def test_download_slots_with_no_user_db(self, bridge_no_user, monkeypatch):
        monkeypatch.setattr(
            'app.stt.download.download_model',
            lambda app_data, size=None, **kw: Path(app_data) / f'ggml-{size}.bin')
        started = ok(bridge_no_user.startModelDownload(''))
        assert started['job_id'] and started['filename']
        deadline = time.monotonic() + 5.0
        report = ok(bridge_no_user.pollModelDownload(started['job_id']))
        while report['state'] == 'running' and time.monotonic() < deadline:
            time.sleep(0.02)
            report = ok(bridge_no_user.pollModelDownload(started['job_id']))
        assert report['state'] == 'done'
        assert ok(bridge_no_user.cancelModelDownload('nope')) == {'cancelled': False}

    def test_transcription_needs_an_app_data_directory(self, bare_bridge):
        """No master database means no ``app_data/``, so no model can be
        resolved. It is refused with a sentence rather than defaulting to
        the working directory and creating ``./models/`` there."""
        assert 'app data directory' in failed(bare_bridge.pollTranscription('x'))
        assert 'app data directory' in failed(bare_bridge.startModelDownload(''))
        assert not (Path.cwd() / 'models').exists()

    def test_engine_state_is_still_honest_with_no_app_data(self, bare_bridge):
        """The binary ships with the build; where it lives has nothing to do
        with ``app_data/``. "We cannot find your model" must not be reported
        as "this build has no speech engine" -- different fixes."""
        data = ok(bare_bridge.getSttStatus())
        assert data['model_ready'] is False
        assert data['model']['error']['kind'] == SttErrorKind.MODEL_MISSING.value
        assert data['engine']['path'].endswith('whisper-cli') or \
            data['engine']['path'].endswith('whisper-cli.exe')


# ==================== Every slot, against a real database ====================

class TestWithAProfileOpen:

    def test_status_reads_the_stored_preference(self, bridge):
        bridge.user_db.update_settings(stt_priming_enabled=False)
        assert ok(bridge.getSttStatus())['priming_enabled'] is False

    def test_settings_round_trip(self, bridge):
        written = ok(bridge.updateSttSettings(json.dumps({
            'stt_priming_enabled': False,
            'stt_show_first_use_notice': False,
            'stt_model_size': 'tiny.en',
            'stt_input_device_id': 'usb-headset-7',
        })))
        assert written['stt_priming_enabled'] is False
        assert written['stt_model_size'] == 'tiny.en'
        assert written['resolved_model_size'] == 'tiny.en'

        read_back = ok(bridge.getSttSettings())
        assert read_back['stt_input_device_id'] == 'usb-headset-7'
        assert read_back['stt_show_first_use_notice'] is False

    def test_an_unknown_setting_is_refused_by_name(self, bridge):
        error = failed(bridge.updateSttSettings('{"stt_model_sixe": "tiny.en"}'))
        assert 'stt_model_sixe' in error
        # Accept-and-ignore is how #138 lost --test-mode in every frozen
        # build: the caller has no way to tell nothing happened.
        assert ok(bridge.getSttSettings())['stt_model_size'] is None

    def test_malformed_settings_json_is_refused(self, bridge):
        assert 'Invalid' in failed(bridge.updateSttSettings('{not json'))

    def test_empty_settings_object_is_a_read(self, bridge):
        assert ok(bridge.updateSttSettings('{}'))['resolved_model_size']

    def test_changing_the_model_size_builds_a_new_runtime(self, bridge):
        first = bridge._stt_runtime()
        assert bridge._stt_runtime() is first, 'unchanged settings should cache'
        ok(bridge.updateSttSettings('{"stt_model_size": "tiny.en"}'))
        second = bridge._stt_runtime()
        assert second is not first
        assert second.model_size == 'tiny.en'

    def test_permission_and_level_answer(self, bridge):
        assert ok(bridge.requestMicrophonePermission())['permission']
        assert ok(bridge.getRecordingLevel())['recording'] is False

    def test_cancel_deletes_the_wav(self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        ok(bridge.startRecording(''))
        path = bridge._stt_recording_path
        assert path.exists()
        assert ok(bridge.cancelRecording()) == {'recording': False,
                                                'cancelled': True}
        assert not path.exists()
        assert bridge._stt_recorder_obj() is None

    def test_a_second_start_while_recording_is_refused(self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        ok(bridge.startRecording(''))
        again = ok(bridge.startRecording(''))
        assert again['recording'] is True
        assert again['error']['kind'] == SttErrorKind.CAPTURE_FAILED.value

    def test_the_stored_device_is_used_when_none_is_named(self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        ok(bridge.updateSttSettings('{"stt_input_device_id": "usb-headset-7"}'))
        ok(bridge.startRecording(''))
        assert bridge._stt_recorder_obj().preferred_device_id == 'usb-headset-7'

    def test_an_explicit_device_outranks_the_stored_one(self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        ok(bridge.updateSttSettings('{"stt_input_device_id": "usb-headset-7"}'))
        ok(bridge.startRecording('built-in'))
        assert bridge._stt_recorder_obj().preferred_device_id == 'built-in'

    def test_malformed_context_is_refused(self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        ok(bridge.startRecording(''))
        assert 'Invalid' in failed(bridge.stopRecording('{not json'))

    def test_download_start_poll_cancel(self, bridge, monkeypatch):
        gate = threading.Event()

        def fake_download(app_data, size=None, *, progress=None, cancel=None, **kw):
            progress(1024, 4096)
            gate.wait(2.0)
            if cancel is not None and cancel.is_set():
                raise SttError(SttErrorKind.DOWNLOAD_CANCELLED, 'cancelled')
            return Path(app_data) / f'ggml-{size}.bin'

        monkeypatch.setattr('app.stt.download.download_model', fake_download)
        started = ok(bridge.startModelDownload('tiny.en'))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            report = ok(bridge.pollModelDownload(started['job_id']))
            if report['bytes'] == 1024:
                break
            time.sleep(0.02)
        assert report == {'job_id': started['job_id'], 'state': 'running',
                          'bytes': 1024, 'total': 4096, 'size': 'tiny.en'}

        assert ok(bridge.cancelModelDownload(started['job_id']))['cancelled'] is True
        gate.set()
        deadline = time.monotonic() + 5.0
        report = ok(bridge.pollModelDownload(started['job_id']))
        while report['state'] == 'running' and time.monotonic() < deadline:
            time.sleep(0.02)
            report = ok(bridge.pollModelDownload(started['job_id']))
        assert report['state'] == 'failed'
        assert report['code'] == SttErrorKind.DOWNLOAD_CANCELLED.value
        assert report['job_id'] == started['job_id']

    def test_every_poll_says_which_job_it_is_about(self, bridge, monkeypatch):
        """#171. ``api.downloadSttModel`` starts the job itself and keeps the
        id in a local, so the poll payload is the **only** place a caller
        using the composite can learn it -- and without it there is no
        argument for ``cancelModelDownload`` and §3.8's "cancel must be
        possible mid-download" is unreachable from the composite.

        Asserted on all four branches, ``unknown_job`` included: a payload
        that says a job is unknown without saying which job is the least
        traceable of the lot, and it is the branch a page hits after the
        next download has cleared this one.
        """
        gate = threading.Event()

        def fake_download(app_data, size=None, *, progress=None, cancel=None, **kw):
            progress(2048, 8192)
            gate.wait(2.0)
            return Path(app_data) / f'ggml-{size}.bin'

        monkeypatch.setattr('app.stt.download.download_model', fake_download)
        started = ok(bridge.startModelDownload('tiny.en'))
        job = started['job_id']

        deadline = time.monotonic() + 5.0
        running = ok(bridge.pollModelDownload(job))
        while running['bytes'] != 2048 and time.monotonic() < deadline:
            time.sleep(0.02)
            running = ok(bridge.pollModelDownload(job))
        assert running['state'] == 'running'
        assert running['job_id'] == job

        gate.set()
        done = ok(bridge.pollModelDownload(job))
        deadline = time.monotonic() + 5.0
        while done['state'] == 'running' and time.monotonic() < deadline:
            time.sleep(0.02)
            done = ok(bridge.pollModelDownload(job))
        assert done['state'] == 'done'
        assert done['job_id'] == job

        # The failed branch, and the unknown-job branch that replaces this
        # record once the next download starts.
        unknown = ok(bridge.pollModelDownload('no-such-job'))
        assert unknown['code'] == SttErrorKind.UNKNOWN_JOB.value
        assert unknown['job_id'] == 'no-such-job'

    def test_an_unknown_model_size_is_refused(self, bridge):
        assert 'Unknown speech model' in failed(bridge.startModelDownload('enormous'))

    def test_a_finished_download_survives_a_second_poll(self, bridge, monkeypatch):
        monkeypatch.setattr(
            'app.stt.download.download_model',
            lambda app_data, size=None, **kw: Path(app_data) / f'ggml-{size}.bin')
        started = ok(bridge.startModelDownload('tiny.en'))
        deadline = time.monotonic() + 5.0
        first = ok(bridge.pollModelDownload(started['job_id']))
        while first['state'] == 'running' and time.monotonic() < deadline:
            time.sleep(0.02)
            first = ok(bridge.pollModelDownload(started['job_id']))
        assert first['state'] == 'done'
        assert ok(bridge.pollModelDownload(started['job_id'])) == first

        # ...until the next one starts, which is what clears it.
        ok(bridge.startModelDownload('base-q5_1'))
        stale = ok(bridge.pollModelDownload(started['job_id']))
        assert stale['code'] == SttErrorKind.UNKNOWN_JOB.value


# ==================== The things that would be silent ====================

class TestNamedFailuresAreData:
    """``_callBridge`` throws on ``success=false`` and discards ``data``."""

    @pytest.mark.parametrize('kind', [
        SttErrorKind.NO_INPUT_DEVICE,
        SttErrorKind.PERMISSION_DENIED,
        SttErrorKind.DEVICE_IN_USE,
    ])
    def test_a_named_capture_failure_is_data(self, bridge, monkeypatch, kind):
        install_fake_recorder(monkeypatch)
        monkeypatch.setattr(FakeRecorder, 'start_error', SttError(kind, 'measured'))
        data = ok(bridge.startRecording(''))
        assert data['recording'] is False
        assert data['error']['kind'] == kind.value
        assert data['error']['retryable'] == (kind is SttErrorKind.DEVICE_IN_USE)

    def test_a_refused_start_leaves_nothing_behind(self, bridge, monkeypatch):
        """The recorder from the previous, finished recording must not
        survive a refused start -- ``cancelRecording`` would then abort a
        capture that ended minutes ago."""
        install_fake_recorder(monkeypatch)
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=FakeRuntime())
        ok(bridge.startRecording(''))
        ok(bridge.stopRecording(json.dumps(CONTEXT)))

        monkeypatch.setattr(FakeRecorder, 'start_error', SttError(
            SttErrorKind.NO_INPUT_DEVICE, 'unplugged between takes'))
        assert ok(bridge.startRecording(''))['recording'] is False
        assert bridge._stt_recorder_obj() is None
        assert ok(bridge.cancelRecording())['cancelled'] is False

    def test_silence_is_reported_and_the_wav_is_removed(self, bridge, monkeypatch):
        """The silent path (§7). Three seconds of digital silence
        transcribes to the word " you", so refusing to transcribe is what
        keeps an invented word out of a required field."""
        install_fake_recorder(monkeypatch)
        monkeypatch.setattr(FakeRecorder, 'stop_error', SttError(
            SttErrorKind.NO_AUDIO_CAPTURED, 'peak 0.00000 never rose'))
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=FakeRuntime())

        ok(bridge.startRecording(''))
        path = bridge._stt_recording_path
        data = ok(bridge.stopRecording(json.dumps(CONTEXT)))

        assert data['job_id'] is None
        assert data['error']['kind'] == SttErrorKind.NO_AUDIO_CAPTURED.value
        assert data['error']['retryable'] is True
        assert data['context']['field_key'] == 'explanation'
        assert not path.exists(), 'stop() leaves the WAV; nothing will read it'

    def test_a_mid_stream_failure_still_transcribes_what_arrived(
            self, bridge, monkeypatch):
        """Do not discard the student's first sentence to report a problem
        with their second (§7)."""
        install_fake_recorder(monkeypatch)
        captured = SttError(SttErrorKind.CAPTURE_FAILED, 'IOError at 4s')
        monkeypatch.setattr(
            FakeRecorder, 'stop',
            lambda self: FakeRecording(self.path, capture_error=captured))
        runtime = FakeRuntime()
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=runtime)

        ok(bridge.startRecording(''))
        started = ok(bridge.stopRecording(json.dumps(CONTEXT)))
        assert started['job_id'], 'a partial recording is still worth transcribing'
        assert started['capture']['capture_error']['kind'] == \
            SttErrorKind.CAPTURE_FAILED.value
        assert await_state(bridge, started['job_id'])['text'] == runtime.text


class TestStaleness:
    """§3.5. The page compares; the bridge echoes."""

    def test_the_four_fields_come_back_on_done(self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=FakeRuntime())
        context = {'entry_id': 41, 'field_key': 'reflection', 'token': 3,
                   'subject_ids': [5, 6]}

        ok(bridge.startRecording(''))
        started = ok(bridge.stopRecording(json.dumps(context)))
        assert started['context'] == context

        report = await_state(bridge, started['job_id'])
        assert report['state'] == 'done'
        assert report['entry_id'] == 41
        assert report['field_key'] == 'reflection'
        assert report['token'] == 3
        assert report['context']['subject_ids'] == [5, 6]

    def test_the_four_fields_come_back_on_failure_too(self, bridge, monkeypatch):
        """A failure the page cannot place is a failure it cannot report
        beside the right field."""
        install_fake_recorder(monkeypatch)

        class Exploding(FakeRuntime):
            def transcribe(self, audio_path, *, prompt='', delete_audio=True):
                Path(audio_path).unlink(missing_ok=True)
                raise SttError(SttErrorKind.TRANSCRIPTION_TIMEOUT, '120s')

        bridge._stt_jobs_obj = TranscriptionJobs(runtime=Exploding())
        ok(bridge.startRecording(''))
        started = ok(bridge.stopRecording(json.dumps(CONTEXT)))

        report = await_state(bridge, started['job_id'])
        assert report['state'] == 'failed'
        assert report['code'] == SttErrorKind.TRANSCRIPTION_TIMEOUT.value
        assert report['message'] == '120s'
        assert report['entry_id'] == 77
        assert report['field_key'] == 'explanation'
        assert report['token'] == 9

    def test_a_finished_job_survives_a_second_poll(self, bridge, monkeypatch):
        """``jobs.poll`` is repeatable on purpose -- a page with a timer
        will poll once more before it notices the first result. Forgetting
        on the first terminal read would turn that into ``unknown_job``,
        which the page would render as a failure it cannot place."""
        install_fake_recorder(monkeypatch)
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=FakeRuntime())
        ok(bridge.startRecording(''))
        started = ok(bridge.stopRecording(json.dumps(CONTEXT)))

        first = await_state(bridge, started['job_id'])
        second = ok(bridge.pollTranscription(started['job_id']))
        assert first == second

    def test_the_previous_job_is_dropped_when_the_next_recording_starts(
            self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=FakeRuntime())
        ok(bridge.startRecording(''))
        first = ok(bridge.stopRecording(json.dumps(CONTEXT)))
        await_state(bridge, first['job_id'])

        ok(bridge.startRecording(''))
        ok(bridge.stopRecording(json.dumps(CONTEXT)))
        stale = ok(bridge.pollTranscription(first['job_id']))
        assert stale['state'] == 'failed'
        assert stale['error']['kind'] == SttErrorKind.UNKNOWN_JOB.value

    def test_an_unfamiliar_field_key_is_echoed_not_rejected(self, bridge, monkeypatch):
        """The page's comparison is the check. A second policy here would be
        free to disagree with it."""
        install_fake_recorder(monkeypatch)
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=FakeRuntime())
        ok(bridge.startRecording(''))
        started = ok(bridge.stopRecording(json.dumps(
            {'entry_id': None, 'field_key': 'something_else', 'token': 0,
             'subject_ids': []})))
        assert started['context']['field_key'] == 'something_else'


class TestThreading:
    """§3.4, and ``base_db.py``'s note on ``check_same_thread``."""

    def test_the_worker_runs_off_the_calling_thread(self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        runtime = FakeRuntime()
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=runtime)

        ok(bridge.startRecording(''))
        started = ok(bridge.stopRecording(json.dumps(CONTEXT)))
        await_state(bridge, started['job_id'])

        assert runtime.threads, 'the worker never ran'
        assert runtime.threads[0].startswith('wimi-stt')
        assert runtime.threads[0] != threading.current_thread().name

    def test_the_worker_touches_no_database(self, bridge, monkeypatch):
        """``stopRecording`` does its database work -- settings, priming --
        before handing over. Replacing ``user_db`` with a ``Landmine`` the
        instant it returns proves nothing downstream reaches for it."""
        install_fake_recorder(monkeypatch)
        runtime = FakeRuntime()
        runtime.delay = 0.05
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=runtime)

        ok(bridge.startRecording(''))
        started = ok(bridge.stopRecording(json.dumps(CONTEXT)))
        bridge.user_db = Landmine()
        try:
            report = await_state(bridge, started['job_id'])
        finally:
            bridge.user_db = None
        assert report['state'] == 'done'

    def test_the_wav_is_deleted_when_the_transcription_returns(
            self, bridge, monkeypatch):
        install_fake_recorder(monkeypatch)
        runtime = FakeRuntime()
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=runtime)

        ok(bridge.startRecording(''))
        path = bridge._stt_recording_path
        started = ok(bridge.stopRecording(json.dumps(CONTEXT)))
        await_state(bridge, started['job_id'])
        assert not path.exists()

    def test_shutdown_is_idempotent(self, bridge):
        bridge.shutdown_stt()
        bridge.shutdown_stt()


class TestPriming:
    """§3.6. Built at transcription time, from the student's own tree."""

    @staticmethod
    def _tree(db: UserDatabase):
        # "Nephrology" rather than "Cardiovascular System": the latter is
        # priming.py's own worked example of a term the ordinary-English
        # filter drops, so it would make this test about the filter.
        cardio = db.create_subject_node(EXAM, 'Nephrology', 'System')
        htn = db.create_subject_node(EXAM, 'Hypertension', 'Topic')
        neph = db.create_subject_node(
            EXAM, 'Hypertensive Nephrosclerosis', 'Subtopic')
        db.add_edge(cardio.id, htn.id, is_primary=True)
        db.add_edge(htn.id, neph.id, is_primary=True)
        sibling = db.create_subject_node(EXAM, 'Glomerulosclerosis', 'Subtopic')
        db.add_edge(htn.id, sibling.id, is_primary=True)
        db.create_subject_alias(neph.id, EXAM, 'HTN nephrosclerosis', 'colloquial')
        return cardio, htn, neph, sibling

    def _run(self, bridge, monkeypatch, context) -> FakeRuntime:
        install_fake_recorder(monkeypatch)
        runtime = FakeRuntime()
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=runtime)
        ok(bridge.startRecording(''))
        started = ok(bridge.stopRecording(json.dumps(context)))
        await_state(bridge, started['job_id'])
        return runtime

    def test_the_prompt_carries_the_subject_its_ancestors_and_its_siblings(
            self, bridge, monkeypatch):
        _cardio, _htn, neph, _sibling = self._tree(bridge.user_db)
        runtime = self._run(bridge, monkeypatch, dict(CONTEXT, subject_ids=[neph.id]))

        prompt = runtime.prompts[0]
        assert 'Hypertensive Nephrosclerosis' in prompt
        assert 'HTN nephrosclerosis' in prompt      # its alias ranks with it
        assert 'Nephrology' in prompt                # ancestor
        assert 'Glomerulosclerosis' in prompt        # sibling

    def test_the_most_relevant_terms_land_last(self, bridge, monkeypatch):
        """Whisper truncates a prompt from the FRONT, silently. The tagged
        subject must therefore be at the end (§0.1 finding 2)."""
        _cardio, _htn, neph, _sibling = self._tree(bridge.user_db)
        runtime = self._run(bridge, monkeypatch, dict(CONTEXT, subject_ids=[neph.id]))

        prompt = runtime.prompts[0]
        assert prompt.index('Nephrology') < \
            prompt.index('Hypertensive Nephrosclerosis')

    def test_priming_off_passes_no_prompt_at_all(self, bridge, monkeypatch):
        """An empty string means omit ``--prompt``, not ``--prompt ''``."""
        _c, _h, neph, _s = self._tree(bridge.user_db)
        bridge.user_db.update_settings(stt_priming_enabled=False)
        runtime = self._run(bridge, monkeypatch, dict(CONTEXT, subject_ids=[neph.id]))
        assert runtime.prompts == ['']

    def test_nothing_tagged_and_no_exam_context_is_unprimed(self, bridge, monkeypatch):
        runtime = self._run(bridge, monkeypatch, CONTEXT)
        assert runtime.prompts == ['']

    def test_a_broken_subject_id_costs_the_prompt_and_nothing_else(
            self, bridge, monkeypatch):
        runtime = self._run(
            bridge, monkeypatch, dict(CONTEXT, subject_ids=['not-an-id', 999999]))
        assert runtime.prompts == ['']
        assert runtime.threads, 'the transcription still ran'


# ==================== Removing a downloaded model (T14) ====================

class TestRemovingAModel:
    """Changing size keeps the old model on purpose, so that switching back
    is free (T14). That is only defensible with an explicit way out: without
    one, models accumulate ~190 MB at a time and nothing in the product can
    undo it."""

    def _write(self, bridge, size: str) -> Path:
        """A file of exactly the pinned byte size, which is all
        ``is_installed`` looks at. Sparse -- writing 190 MB of zeros per test
        to satisfy a ``stat()`` would be 350 MB of disk across this class."""
        from app.stt import model_spec
        spec = model_spec.get_spec(size)
        path = model_spec.model_path(bridge._stt_app_data_dir(), size)
        with open(path, 'wb') as handle:
            handle.truncate(spec.size_bytes)
        return path

    def test_it_deletes_the_file_and_says_so(self, bridge):
        path = self._write(bridge, 'tiny.en')
        assert ok(bridge.getSttSettings())['available_models'][0]['installed']

        data = ok(bridge.removeSttModel('tiny.en'))
        assert data == {'size': 'tiny.en', 'removed': True, 'path': str(path)}
        assert not path.exists()
        assert not ok(bridge.getSttSettings())['available_models'][0]['installed']

    def test_the_partial_file_goes_too(self, bridge):
        """A ``.part`` left behind would make the next download resume toward
        a model the student has just said they do not want here."""
        from app.stt import model_spec
        path = model_spec.model_path(bridge._stt_app_data_dir(), 'tiny.en')
        part = model_spec.part_path(path)
        part.write_bytes(b'\0' * 1024)

        data = ok(bridge.removeSttModel('tiny.en'))
        # Nothing was installed, so ``removed`` is False -- and the partial
        # file is gone regardless.
        assert data['removed'] is False
        assert not part.exists()

    def test_removing_what_is_not_there_is_a_success(self, bridge):
        """The student asked for the file to be gone. It is gone."""
        data = ok(bridge.removeSttModel('base-q5_1'))
        assert data['removed'] is False

    def test_an_empty_size_means_this_machines_resolved_one(self, bridge):
        bridge.user_db.update_settings(stt_model_size='tiny')
        self._write(bridge, 'tiny')
        assert ok(bridge.removeSttModel(''))['size'] == 'tiny'

    def test_the_model_in_use_may_be_removed(self, bridge):
        """Reclaiming the disk is a legitimate thing to want, and what
        follows is ``model_missing`` -- the first-run resting state, not a
        failure (section 7). The confirmation is the caller's job."""
        self._write(bridge, 'small.en-q5_1')
        assert ok(bridge.removeSttModel('small.en-q5_1'))['removed'] is True
        status = ok(bridge.getSttStatus())
        assert status['model_ready'] is False
        assert status['model']['error']['kind'] == SttErrorKind.MODEL_MISSING.value

    def test_an_unknown_size_is_refused_by_name(self, bridge):
        """It cannot tell which file was meant, and guessing would delete
        something the student did not name."""
        assert 'Unknown speech model' in failed(bridge.removeSttModel('enormous'))

    def test_it_needs_an_app_data_directory(self, bare_bridge):
        assert 'app data directory' in failed(bare_bridge.removeSttModel('tiny.en'))

    def test_it_works_with_no_profile_open(self, bridge_no_user):
        """Like every other slot here: the picker runs before a database is
        attached, and a model on disk is not a per-profile fact."""
        assert ok(bridge_no_user.removeSttModel('tiny.en'))['removed'] is False


# ==================== The sweep (T17) ====================
#
# Everything above was written by the task that wrote the code beside it.
# What follows came from looking at the feature whole and asking what no
# single task's tests would catch. Each of these was **proved** missing by
# breaking the thing it names and watching all 282 speech tests stay green;
# the proof is recorded per class.


class TestTheRecordingIsNeverLeftBehind:
    """A WAV that will never be transcribed is deleted where it is dropped.

    The engine's own input is deleted in ``transcribe``'s ``finally`` and
    ``test_stt_runtime.py::test_the_recording_is_deleted_on_every_path``
    holds that end on success, failure and timeout alike. What it cannot see
    is the three ways a recording never reaches the engine at all -- and
    each leaves a *recording of the student's voice* in the system temp
    directory with nothing left that will ever come back for it.

    Only the ``no_audio_captured`` route (above) was covered. Removing the
    ``_stt_discard_recording`` call from all three routes below left the
    suite green.
    """

    def test_a_recording_with_nowhere_to_transcribe_is_removed(
            self, bare_bridge, monkeypatch):
        """No master database means no ``app_data/`` and so no model.

        Recording does not need one -- ``startRecording`` succeeds -- which
        is exactly why this path exists and why it is easy to miss.
        """
        install_fake_recorder(monkeypatch)
        assert ok(bare_bridge.startRecording(''))['recording'] is True
        path = bare_bridge._stt_recording_path
        assert path.exists(), 'the fake recorder writes a real file'

        assert 'app data directory' in failed(
            bare_bridge.stopRecording(json.dumps(CONTEXT)))
        assert not path.exists()

    def test_a_recording_that_cannot_be_queued_is_removed(self, bridge, monkeypatch):
        """The executor refusing the work is the one failure after which the
        WAV is definitely nobody's: ``transcribe`` never runs, so its
        ``finally`` never runs either."""
        class RefusingJobs:
            def start(self, *_args, **_kwargs):
                raise RuntimeError('cannot schedule new futures after shutdown')

            def forget(self, _job_id):
                pass

            def shutdown(self):
                pass

        install_fake_recorder(monkeypatch)
        bridge._stt_jobs_obj = RefusingJobs()

        ok(bridge.startRecording(''))
        path = bridge._stt_recording_path
        assert 'queue transcription' in failed(
            bridge.stopRecording(json.dumps(CONTEXT)))
        assert not path.exists()

    def test_an_unexpected_stop_failure_still_removes_the_recording(
            self, bridge, monkeypatch):
        """The branch beside the ``SttError`` one, which is the one that gets
        forgotten because nothing is *meant* to reach it."""
        def boom(self):
            self.is_recording = False
            raise RuntimeError('the WAV sink was already closed')

        install_fake_recorder(monkeypatch)
        monkeypatch.setattr(FakeRecorder, 'stop', boom)
        bridge._stt_jobs_obj = TranscriptionJobs(runtime=FakeRuntime())

        ok(bridge.startRecording(''))
        path = bridge._stt_recording_path
        assert 'Failed to stop recording' in failed(
            bridge.stopRecording(json.dumps(CONTEXT)))
        assert not path.exists()

    def test_closing_the_window_mid_dictation_removes_the_recording(
            self, bridge, monkeypatch):
        """``TranscriptionJobs.shutdown`` deletes the WAV of a job that was
        cancelled before it ran (``test_stt_jobs.py``). The recording still
        being *written* is a different file with the same problem, and it is
        ``shutdown_stt``'s ``recorder.abort()`` that removes it.

        Proved: replacing that ``abort()`` with ``pass`` left every speech
        test passing.
        """
        install_fake_recorder(monkeypatch)
        ok(bridge.startRecording(''))
        path = bridge._stt_recording_path
        assert path.exists()

        bridge.shutdown_stt()

        assert not path.exists()
        assert bridge._stt_recorder_obj() is None


class TestAModelSizeThePinTableNoLongerHas:
    """m023 chose **no CHECK constraint** on ``stt_model_size``, and said why:

        "a value the app cannot use must be something to clamp at read
        time, not a failed migration and an app that will not open."

    So the clamp is the whole of that guarantee, and it lives in one
    ``except Exception`` in ``getSttStatus``. Narrowing that catch to
    ``SttError`` -- which is what a tidy-up would do, since every other
    handler in the file catches exactly that -- left the suite green while
    ``getSttStatus`` became a failed response. ``_callBridge`` throws on
    those and drops ``data``, so the page would lose the microphone and
    engine lines as well: the collapse Section 7 exists to prevent.
    """

    BAD = 'enormous.en'

    def _store_it(self, bridge):
        ok(bridge.updateSttSettings(json.dumps({'stt_model_size': self.BAD})))

    def test_the_status_call_still_succeeds(self, bridge):
        self._store_it(bridge)
        assert ok(bridge.getSttStatus())['model_size'] == self.BAD

    def test_only_the_model_line_reports_the_problem(self, bridge):
        self._store_it(bridge)
        data = ok(bridge.getSttStatus())

        assert data['model_ready'] is False
        assert data['model']['error']['kind'] == SttErrorKind.MODEL_MISSING.value
        assert self.BAD in data['model']['error']['detail'], (
            'the detail has to name the size, or the student is told a model '
            'is missing with no way to find out which')

    def test_the_microphone_and_engine_lines_are_still_answered(self, bridge):
        """The three states are independent (Section 3.8). A model size
        nobody recognises says nothing about either of the other two."""
        self._store_it(bridge)
        data = ok(bridge.getSttStatus())

        assert data['mic'] is not None and 'permission' in data['mic']
        assert data['engine']['path'].endswith(('whisper-cli', 'whisper-cli.exe'))
        assert data['engine_ready'] == (data['engine']['error'] is None)


class TestTheDownloadWorkerTouchesNoDatabase:
    """The second worker, held to the first one's rule.

    ``TestThreading`` above hands the *transcription* worker a ``Landmine``.
    The model download runs on this mixin's own single-thread executor and
    had no equivalent in either direction: ``download.py`` was also absent
    from the static import guard in ``test_stt_jobs.py`` until T17 added it,
    so an ``import sqlite3`` there left all 282 speech tests green.
    """

    def test_neither_the_slot_nor_the_worker_reaches_user_db(
            self, bridge, user_db, monkeypatch):
        """The Landmine goes in **before** the slot is called.

        ``TestThreading`` above can swap the database out after
        ``stopRecording`` returns, because the transcription worker sits
        behind a queue. This one cannot: ``run()`` is submitted and starts
        executing inside ``startModelDownload``, so a Landmine installed
        after it returns is a race the first draft of this test lost -- it
        passed against a ``run()`` that read ``bridge.user_db`` on its first
        line.

        An explicit size is passed so the slot has no legitimate reason to
        read a setting: ``''`` resolves through ``_stt_model_size``, which
        touches the database on this thread and correctly.
        """
        monkeypatch.setattr(
            'app.stt.download.download_model',
            lambda app_data, size=None, **_kw: Path(app_data) / f'ggml-{size}.bin')

        bridge.user_db = Landmine()
        try:
            started = ok(bridge.startModelDownload('tiny.en'))
            deadline = time.monotonic() + 5.0
            report = ok(bridge.pollModelDownload(started['job_id']))
            while report['state'] == 'running' and time.monotonic() < deadline:
                time.sleep(0.02)
                report = ok(bridge.pollModelDownload(started['job_id']))
        finally:
            bridge.user_db = user_db

        assert report['state'] == 'done', report.get('error')
