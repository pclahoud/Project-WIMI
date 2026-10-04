"""The first-run model download (#59, T21): the failure paths, mostly.

The happy path is one test. The other twenty are about the ways a download can
end badly, because every one of them ends with a file on disk and §3.7 has
**no database column** recording whether a model is installed -- the file *is*
the record. R15 names the risk plainly: *a corrupt download presents as a
working install*. So what these tests really assert is a single invariant,
from several directions:

    after any outcome whatsoever, ``ggml-<size>.bin`` either is the pinned
    model or does not exist, and no ``.part`` is left behind except where a
    retry could resume from it.

The one that silently produces garbage in the wild is
``test_resume_restarts_when_the_server_ignores_range``. A server may answer a
``Range`` request with ``200`` and the whole body; appending that to the bytes
already on disk yields a file of plausible size and entirely wrong content,
with no error anywhere. Its companion,
``test_resume_onto_a_bad_part_is_caught_by_the_digest``, is why the digest
check is not optional on the resume path even once resume is known to work.

Everything runs against a stdlib ``http.server`` on localhost. No network, no
Qt, no database -- which is also the point: ``download.py`` runs on the worker
thread and is contractually forbidden to touch either (plan §3.4).
"""

from __future__ import annotations

import hashlib
import http.server
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from app.stt import download as dl
from app.stt import model_spec as ms
from app.stt.errors import RETRYABLE, SttError, SttErrorKind

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# a payload and a spec for it
# --------------------------------------------------------------------------

PAYLOAD_BYTES = 200_000


def make_payload(n: int = PAYLOAD_BYTES, seed: bytes = b'wimi-stt') -> bytes:
    """Deterministic pseudo-random bytes.

    Not ``b'x' * n``: a repeating payload would let an append-instead-of-restart
    bug produce a file whose digest was still wrong, but for the wrong reason,
    and would hide an off-by-one in the resume offset entirely.
    """
    out = bytearray()
    block = seed
    while len(out) < n:
        block = hashlib.sha256(block).digest()
        out.extend(block)
    return bytes(out[:n])


PAYLOAD = make_payload()


def spec_for(payload: bytes, *, size: str = 'fixture') -> ms.ModelSpec:
    return ms.ModelSpec(
        size=size,
        filename=f'ggml-{size}.bin',
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


SPEC = spec_for(PAYLOAD)


# --------------------------------------------------------------------------
# the fixture server
# --------------------------------------------------------------------------


@dataclass
class ServerConfig:
    """How the fixture server should misbehave for this test."""

    body: bytes = PAYLOAD
    honour_range: bool = True
    send_content_length: bool = True
    chunk_size: int = 8192
    chunk_delay_s: float = 0.0
    #: Every ``Range`` header the server was sent, in order (``None`` = absent).
    ranges: List[Optional[str]] = field(default_factory=list)
    #: Body bytes actually written, per request.
    served: List[int] = field(default_factory=list)


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    @property
    def cfg(self) -> ServerConfig:
        return self.server.cfg  # type: ignore[attr-defined]

    def do_GET(self):  # noqa: N802 - stdlib naming
        cfg = self.cfg
        if self.path != f'/{SPEC.filename}':
            self.send_error(404, 'Not Found')
            return
        raw_range = self.headers.get('Range')
        cfg.ranges.append(raw_range)

        body = cfg.body
        start = 0
        status = 200
        if raw_range and cfg.honour_range:
            match = re.match(r'bytes=(\d+)-', raw_range)
            if match:
                start = int(match.group(1))
                if start >= len(body):
                    self.send_error(416, 'Requested Range Not Satisfiable')
                    return
                status = 206

        chunk = body[start:]
        if not cfg.send_content_length:
            # No Content-Length and no chunked encoding is only legal if the
            # connection closes to mark the end of the body, so speak 1.0.
            self.protocol_version = 'HTTP/1.0'
            self.close_connection = True

        self.send_response(status)
        self.send_header('Content-Type', 'application/octet-stream')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
            self.send_header('Accept-Ranges', 'bytes')
        if cfg.send_content_length:
            self.send_header('Content-Length', str(len(chunk)))
        self.end_headers()

        written = 0
        try:
            for offset in range(0, len(chunk), cfg.chunk_size):
                self.wfile.write(chunk[offset:offset + cfg.chunk_size])
                self.wfile.flush()
                written += len(chunk[offset:offset + cfg.chunk_size])
                if cfg.chunk_delay_s:
                    time.sleep(cfg.chunk_delay_s)
        except (BrokenPipeError, ConnectionResetError):
            # The client cancelled and closed the socket. Expected.
            pass
        cfg.served.append(written)

    def log_message(self, *args):  # silence the stderr access log
        pass


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture
def server():
    """A localhost HTTP server whose behaviour each test edits in place."""
    httpd = _Server(('127.0.0.1', 0), _Handler)
    httpd.cfg = ServerConfig()  # type: ignore[attr-defined]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    httpd.url = f'http://{host}:{port}/ggml-fixture.bin'  # type: ignore[attr-defined]
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    return tmp_path / 'models' / 'whisper' / SPEC.filename


class Recorder:
    """A progress callback that remembers what it was told."""

    def __init__(self, cancel_after: Optional[int] = None,
                 event: Optional[threading.Event] = None):
        self.calls: List[Tuple[int, Optional[int]]] = []
        self._cancel_after = cancel_after
        self._event = event

    def __call__(self, done: int, total: Optional[int]) -> None:
        self.calls.append((done, total))
        if self._cancel_after is not None and done >= self._cancel_after and self._event:
            self._event.set()

    @property
    def bytes_seen(self) -> List[int]:
        return [done for done, _ in self.calls]

    @property
    def totals(self) -> List[Optional[int]]:
        return [total for _, total in self.calls]


def download(server, dest: Path, **kwargs) -> Path:
    kwargs.setdefault('timeout', 10)
    return dl.download_spec(SPEC, dest, url=server.url, **kwargs)


def part_of(dest: Path) -> Path:
    return ms.part_path(dest)


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


def test_downloads_verifies_and_installs_atomically(server, dest):
    progress = Recorder()

    installed = download(server, dest, progress=progress)

    assert installed == dest
    assert dest.read_bytes() == PAYLOAD
    assert not part_of(dest).exists(), 'the .part must be gone once it is the model'
    assert progress.bytes_seen[0] == 0
    assert progress.bytes_seen[-1] == len(PAYLOAD)
    assert progress.bytes_seen == sorted(progress.bytes_seen), 'progress must not go backwards'
    assert set(progress.totals) == {len(PAYLOAD)}


def test_the_directory_is_created_on_the_way(server, tmp_path):
    dest = tmp_path / 'a' / 'b' / 'c' / SPEC.filename
    assert not dest.parent.exists()

    download(server, dest)

    assert dest.exists()


def test_progress_is_bytes_and_total_never_a_percentage(server, dest):
    progress = Recorder()

    download(server, dest, progress=progress)

    for done, total in progress.calls:
        assert isinstance(done, int)
        assert total is None or isinstance(total, int)
        # A percentage would live in 0..100; bytes must exceed that long
        # before the end. The last call is the whole payload.
    assert progress.calls[-1] == (len(PAYLOAD), len(PAYLOAD))


def test_a_progress_callback_that_raises_does_not_fail_the_download(server, dest):
    def angry(done, total):
        raise RuntimeError('the UI blew up')

    installed = download(server, dest, progress=angry)

    assert installed.read_bytes() == PAYLOAD


# --------------------------------------------------------------------------
# a corrupted payload
# --------------------------------------------------------------------------


def test_refuses_a_corrupted_payload_and_leaves_no_part(server, dest):
    server.cfg.body = make_payload(seed=b'not the model')
    assert len(server.cfg.body) == len(PAYLOAD), 'same length, wrong bytes'

    with pytest.raises(SttError) as caught:
        download(server, dest)

    assert caught.value.kind is SttErrorKind.DOWNLOAD_FAILED
    assert 'sha256' in caught.value.detail
    assert not dest.exists(), 'nothing that failed verification may be named like a model'
    assert not part_of(dest).exists()


def test_refuses_a_short_payload_by_size_before_hashing(server, dest):
    server.cfg.body = PAYLOAD[:1000]

    with pytest.raises(SttError) as caught:
        download(server, dest)

    assert caught.value.kind is SttErrorKind.DOWNLOAD_FAILED
    assert '1000 bytes' in caught.value.detail
    assert not dest.exists()
    assert not part_of(dest).exists()


def test_a_failed_download_is_retryable(server, dest):
    server.cfg.body = make_payload(seed=b'wrong')

    with pytest.raises(SttError) as caught:
        download(server, dest)

    # DOWNLOAD_FAILED rather than MODEL_CORRUPT precisely so the UI may offer
    # a retry: a garbled transfer often succeeds the second time.
    assert caught.value.retryable
    assert caught.value.kind in RETRYABLE


def test_an_http_error_fails_without_creating_anything(server, dest):
    with pytest.raises(SttError) as caught:
        dl.download_spec(SPEC, dest, url=server.url.replace('.bin', '.missing'), timeout=10)

    assert caught.value.kind is SttErrorKind.DOWNLOAD_FAILED
    assert not dest.exists()
    assert not part_of(dest).exists()


# --------------------------------------------------------------------------
# resume
# --------------------------------------------------------------------------


def test_resumes_a_truncated_part(server, dest):
    already = 120_000
    dest.parent.mkdir(parents=True)
    part_of(dest).write_bytes(PAYLOAD[:already])
    progress = Recorder()

    download(server, dest, progress=progress)

    assert dest.read_bytes() == PAYLOAD
    assert server.cfg.ranges == [f'bytes={already}-']
    assert server.cfg.served == [len(PAYLOAD) - already], 'the head must not be re-sent'
    assert progress.bytes_seen[0] == already, 'progress resumes where the file did'
    assert progress.bytes_seen[-1] == len(PAYLOAD)
    assert set(progress.totals) == {len(PAYLOAD)}, 'total is the whole file, not the remainder'
    assert not part_of(dest).exists()


def test_resume_restarts_when_the_server_ignores_range(server, dest):
    """The case that silently produces garbage in the wild.

    The server is sent ``Range`` and answers ``200`` with the whole body. If
    the downloader appended, the file would be 320,000 bytes of nonsense; the
    size check would catch it here, but a payload whose length happened to
    work out would not be caught by anything except the digest. So the
    downloader restarts, and the assertion below is that it ended up with the
    real model rather than with an error.
    """
    already = 120_000
    dest.parent.mkdir(parents=True)
    part_of(dest).write_bytes(PAYLOAD[:already])
    server.cfg.honour_range = False
    progress = Recorder()

    download(server, dest, progress=progress)

    assert dest.read_bytes() == PAYLOAD
    assert server.cfg.ranges == [f'bytes={already}-'], 'it did ask'
    assert server.cfg.served == [len(PAYLOAD)], 'the server sent everything'
    assert progress.bytes_seen[0] == 0, 'and progress went back to zero, honestly'
    assert progress.bytes_seen[-1] == len(PAYLOAD)
    assert not part_of(dest).exists()


def test_resume_onto_a_bad_part_is_caught_by_the_digest(server, dest):
    """A resumed download is untrusted until the digest passes.

    The ``.part`` here is the right *length* for a prefix but the wrong bytes
    -- an earlier download from a different source, a partially overwritten
    file. The server honours the Range perfectly, so the result is exactly the
    pinned size and is still not the model.
    """
    already = 120_000
    dest.parent.mkdir(parents=True)
    part_of(dest).write_bytes(make_payload(already, seed=b'someone elses bytes'))

    with pytest.raises(SttError) as caught:
        download(server, dest)

    assert caught.value.kind is SttErrorKind.DOWNLOAD_FAILED
    assert 'sha256' in caught.value.detail
    assert not dest.exists()
    assert not part_of(dest).exists(), 'resuming from it again would only repeat the failure'


def test_an_oversized_part_is_discarded_and_the_download_restarts(server, dest):
    dest.parent.mkdir(parents=True)
    part_of(dest).write_bytes(PAYLOAD + b'trailing garbage')

    download(server, dest)

    assert dest.read_bytes() == PAYLOAD
    assert server.cfg.ranges == [None], 'no Range: there was nothing worth resuming'


def test_a_complete_part_is_verified_and_installed_without_a_download(server, dest):
    """The crash-between-write-and-rename case."""
    dest.parent.mkdir(parents=True)
    part_of(dest).write_bytes(PAYLOAD)

    installed = download(server, dest)

    assert installed.read_bytes() == PAYLOAD
    assert server.cfg.ranges == [], 'the server was never contacted'
    assert not part_of(dest).exists()


def test_a_complete_but_wrong_part_is_discarded_not_installed(server, dest):
    dest.parent.mkdir(parents=True)
    part_of(dest).write_bytes(make_payload(seed=b'complete and wrong'))

    download(server, dest)

    assert dest.read_bytes() == PAYLOAD
    assert server.cfg.ranges == [None]


# --------------------------------------------------------------------------
# cancel
# --------------------------------------------------------------------------


def test_cancel_mid_download_deletes_the_part(server, dest):
    server.cfg.chunk_size = 4096
    server.cfg.chunk_delay_s = 0.002
    cancel = threading.Event()
    progress = Recorder(cancel_after=20_000, event=cancel)

    with pytest.raises(SttError) as caught:
        download(server, dest, progress=progress, cancel=cancel)

    assert caught.value.kind is SttErrorKind.DOWNLOAD_CANCELLED
    assert not part_of(dest).exists(), 'a cancelled download leaves nothing to resume'
    assert not dest.exists()


def test_cancel_before_starting_downloads_nothing(server, dest):
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(SttError) as caught:
        download(server, dest, cancel=cancel)

    assert caught.value.kind is SttErrorKind.DOWNLOAD_CANCELLED
    assert server.cfg.ranges == []


def test_cancel_during_the_salvage_hash_still_deletes_the_part(server, dest):
    dest.parent.mkdir(parents=True)
    part_of(dest).write_bytes(PAYLOAD)
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(SttError) as caught:
        download(server, dest, cancel=cancel)

    assert caught.value.kind is SttErrorKind.DOWNLOAD_CANCELLED
    assert not part_of(dest).exists()


# --------------------------------------------------------------------------
# a host that sends no Content-Length
# --------------------------------------------------------------------------


def test_survives_a_response_with_no_content_length(server, dest):
    server.cfg.send_content_length = False
    progress = Recorder()

    installed = download(server, dest, progress=progress)

    assert installed.read_bytes() == PAYLOAD
    assert progress.totals == [None] * len(progress.calls), (
        'total is what the server said, and it said nothing -- the pinned size is '
        'not passed off as the server\'s answer'
    )
    assert progress.bytes_seen[-1] == len(PAYLOAD)


# --------------------------------------------------------------------------
# an existing install
# --------------------------------------------------------------------------


def test_an_installed_and_verifying_model_is_not_downloaded_again(server, dest):
    dest.parent.mkdir(parents=True)
    dest.write_bytes(PAYLOAD)

    installed = download(server, dest)

    assert installed == dest
    assert server.cfg.ranges == [], 'no request at all'


def test_an_installed_model_that_fails_the_pin_is_replaced(server, dest):
    dest.parent.mkdir(parents=True)
    dest.write_bytes(make_payload(seed=b'an older revision'))

    download(server, dest)

    assert dest.read_bytes() == PAYLOAD
    assert server.cfg.ranges == [None]


# --------------------------------------------------------------------------
# download_model: the app-facing entry point and where it puts things
# --------------------------------------------------------------------------


def test_download_model_installs_under_app_data_models_whisper(server, tmp_path, monkeypatch):
    monkeypatch.setitem(ms.MODELS, SPEC.size, SPEC)

    installed = dl.download_model(
        tmp_path, SPEC.size, url=server.url, timeout=10
    )

    assert installed == tmp_path / 'models' / 'whisper' / SPEC.filename
    assert installed.read_bytes() == PAYLOAD


# --------------------------------------------------------------------------
# the pin table and the install location
# --------------------------------------------------------------------------


def test_the_install_path_has_no_frozen_mode_branch(tmp_path, monkeypatch):
    """The binary branches on frozen mode; the model deliberately does not.

    A frozen branch here could only point inside the bundle, which is
    read-only on macOS and replaced wholesale on update.
    """
    dev = ms.model_path(tmp_path, 'base.en', create=False)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'WIMI.exe'), raising=False)
    frozen = ms.model_path(tmp_path, 'base.en', create=False)

    assert dev == frozen == tmp_path / 'models' / 'whisper' / 'ggml-base.en.bin'


def test_model_dir_creates_eagerly_but_can_be_asked_not_to(tmp_path):
    assert not ms.model_dir(tmp_path, create=False).exists()
    assert ms.model_dir(tmp_path).is_dir()


def test_part_path_is_a_suffix_so_it_sorts_beside_the_model(tmp_path):
    target = tmp_path / 'ggml-base.en.bin'
    assert ms.part_path(target).name == 'ggml-base.en.bin.part'


def test_every_pin_is_a_plausible_pin():
    assert ms.MODELS, 'an empty pin table would make every download a no-op'
    seen = set()
    for size, spec in ms.MODELS.items():
        assert spec.size == size
        assert re.fullmatch(r'[0-9a-f]{64}', spec.sha256), (
            f'{size}: a digest that is not 64 lowercase hex characters is a '
            f'transcription error -- T1 truncated its own to 63'
        )
        assert spec.size_bytes > 1_000_000
        assert spec.filename == f'ggml-{size}.bin'
        assert spec.filename not in seen
        seen.add(spec.filename)


def test_the_default_size_is_in_the_table():
    assert ms.DEFAULT_MODEL_SIZE in ms.MODELS
    assert ms.get_spec(None) is ms.MODELS[ms.DEFAULT_MODEL_SIZE]
    assert ms.get_spec('') is ms.MODELS[ms.DEFAULT_MODEL_SIZE]


def test_an_unknown_size_is_refused_rather_than_quietly_defaulted():
    with pytest.raises(ms.UnknownModelSize) as caught:
        ms.get_spec('enormous')
    assert 'enormous' in str(caught.value)
    assert ms.DEFAULT_MODEL_SIZE in str(caught.value), 'the message lists what is pinned'


def test_the_download_url_is_pinned_to_a_revision_not_a_branch():
    url = ms.download_url('base.en')
    assert ms.MODEL_REVISION in url
    assert '/resolve/' in url
    assert url.endswith('ggml-base.en.bin')
    assert re.fullmatch(r'[0-9a-f]{40}', ms.MODEL_REVISION), 'a commit, not "main"'


def test_quantisation_and_baseline_are_derived_from_the_name():
    q = ms.MODELS['base-q5_1']
    assert q.quantisation == 'q5_1'
    assert q.baseline_size == 'base', 'the comparison baseline is multilingual base'
    assert not q.english_only
    assert ms.MODELS['base.en'].quantisation is None
    assert ms.MODELS['base.en'].english_only


def test_is_installed_is_cheap_and_does_not_hash(tmp_path):
    spec = ms.MODELS['base.en']
    assert not ms.is_installed(tmp_path, 'base.en')
    target = ms.model_path(tmp_path, 'base.en')
    target.write_bytes(b'\0' * spec.size_bytes)
    assert ms.is_installed(tmp_path, 'base.en'), 'right size is enough for the cheap check'
    assert ms.installed_sizes(tmp_path) == ('base.en',)
    with pytest.raises(SttError) as caught:
        ms.verify_file(target, spec)
    assert caught.value.kind is SttErrorKind.MODEL_CORRUPT, 'the honest check hashes'


def test_verify_file_distinguishes_missing_from_corrupt(tmp_path):
    spec = spec_for(PAYLOAD)
    target = tmp_path / spec.filename

    with pytest.raises(SttError) as missing:
        ms.verify_file(target, spec)
    assert missing.value.kind is SttErrorKind.MODEL_MISSING

    target.write_bytes(PAYLOAD)
    ms.verify_file(target, spec)  # no raise

    target.write_bytes(PAYLOAD[:-1])
    with pytest.raises(SttError) as corrupt:
        ms.verify_file(target, spec)
    assert corrupt.value.kind is SttErrorKind.MODEL_CORRUPT
