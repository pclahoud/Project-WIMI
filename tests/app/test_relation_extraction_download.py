"""Acquiring the GLiNER2 weights: install, skip, resume, verify, cancel (#60).

Most of this runs through **real `urllib` against a local HTTP server** that
honours `Range`, rather than against a faked `_open`. The resume path is the
only genuinely subtle logic in the module and its correctness is a property of
HTTP status codes and `Content-Range` headers, so a fake response would be
testing the test.

The two adversarial cases a cooperative server cannot produce -- it ignores
`Range` and answers `200`, or it answers `206` with the wrong offset -- are
driven by configuring this server to misbehave, not by patching the module.

Integration with the real host is already measured elsewhere: this session
downloaded all seven non-weight pinned files from Hugging Face and verified
them against the pin table, so `urllib` reaching that CDN is established. What
needs tests is what this module does with the bytes.
"""
from __future__ import annotations

import ast
import hashlib
import http.server
import re
import threading
from pathlib import Path

import pytest

from app.relation_extraction import download, model_spec
from app.relation_extraction.errors import RelationExtractionErrorKind

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

RANGE_RE = re.compile(r'bytes=(\d+)-')


# --------------------------------------------------------------------------
# A local host that can also behave badly
# --------------------------------------------------------------------------

class _Host:
    """Serves bytes by name, with configurable misbehaviour."""

    def __init__(self, files):
        self.files = dict(files)
        #: 'honour' | 'ignore_range' | 'wrong_offset'
        self.range_mode = 'honour'
        #: Truncate every body to this many bytes, to simulate a cut transfer.
        self.cut_after = None
        self.requests = []


def _make_handler(host: _Host):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):  # keep pytest output clean
            pass

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's contract
            name = self.path.lstrip('/')
            body = host.files.get(name)
            if body is None:
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return

            wanted = 0
            match = RANGE_RE.search(self.headers.get('Range', '') or '')
            if match:
                wanted = int(match.group(1))
            host.requests.append((name, wanted))

            if wanted and host.range_mode == 'honour':
                start = wanted
                status, content_range = 206, f'bytes {start}-{len(body) - 1}/{len(body)}'
            elif wanted and host.range_mode == 'wrong_offset':
                # 206, but describing a different offset from the one asked
                # for. Appending this would corrupt the file silently.
                start = 0
                status, content_range = 206, f'bytes 0-{len(body) - 1}/{len(body)}'
            else:
                # Either no Range asked, or the server is ignoring it.
                start = 0
                status, content_range = 200, None

            payload = body[start:]
            if host.cut_after is not None:
                payload = payload[:host.cut_after]

            self.send_response(status)
            if content_range:
                self.send_header('Content-Range', content_range)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


@pytest.fixture
def host(monkeypatch):
    """A tiny pinned model served locally, with the pin table pointed at it.

    Four files, one in a subdirectory, in ascending size order exactly as the
    real table is -- so the "smallest first" property is exercised rather than
    assumed.
    """
    blobs = {
        'config.json': b'{"model_type":"extractor"}',
        'sub/extra.json': b'x' * 64,
        'tokenizer.json': b'y' * 4096,
        'model.safetensors': bytes(range(256)) * 300,  # 76,800 bytes
    }
    pins = {
        name: model_spec.FilePin(
            name=name,
            sha256=hashlib.sha256(blob).hexdigest(),
            size_bytes=len(blob),
        )
        for name, blob in blobs.items()
    }
    monkeypatch.setattr(model_spec, 'MODEL_FILES', pins)
    monkeypatch.setattr(model_spec, 'MODEL_FILE_NAMES', tuple(pins))
    monkeypatch.setattr(
        model_spec, 'TOTAL_BYTES', sum(p.size_bytes for p in pins.values()))

    served = _Host(blobs)
    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), _make_handler(served))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    monkeypatch.setattr(
        model_spec, '_DOWNLOAD_URL_TEMPLATE', base + '/{filename}')
    # The template still takes repo/revision kwargs; they are simply unused.
    served.blobs = blobs
    try:
        yield served
    finally:
        server.shutdown()
        server.server_close()


def _installed(app_data: Path):
    base = model_spec.model_dir(app_data, create=False)
    return sorted(p.relative_to(base).as_posix()
                  for p in base.rglob('*') if p.is_file())


# --------------------------------------------------------------------------
# The ordinary paths
# --------------------------------------------------------------------------

def test_a_fresh_install_fetches_everything_and_verifies_it(host, tmp_path):
    result = download.install_model(tmp_path)

    assert sorted(result.installed) == sorted(host.blobs)
    assert result.skipped == ()
    assert result.bytes_downloaded == sum(len(b) for b in host.blobs.values())
    assert model_spec.is_installed(tmp_path)

    # Contents, not just names -- a downloader that wrote the right sizes and
    # the wrong bytes would pass a name check.
    base = model_spec.model_dir(tmp_path, create=False)
    for name, blob in host.blobs.items():
        assert (base / name).read_bytes() == blob


def test_a_nested_name_lands_in_its_subdirectory(host, tmp_path):
    download.install_model(tmp_path)
    assert 'sub/extra.json' in _installed(tmp_path)


def test_nothing_is_left_named_like_a_model_that_is_not_one(host, tmp_path):
    """No `.part` survives a successful install.

    The filesystem is the only record that the model is installed (#59 §3.7),
    which is only safe if nothing that is not a verified file is ever named
    like one.
    """
    download.install_model(tmp_path)
    assert not list(model_spec.model_dir(tmp_path, create=False).rglob('*.part'))


def test_a_second_call_skips_everything(host, tmp_path):
    download.install_model(tmp_path)
    host.requests.clear()

    result = download.install_model(tmp_path)

    assert result.installed == ()
    assert sorted(result.skipped) == sorted(host.blobs)
    assert result.bytes_downloaded == 0
    assert host.requests == [], 'a complete install must not touch the network'


def test_a_partial_install_fetches_only_what_is_missing(host, tmp_path):
    download.install_model(tmp_path)
    model_spec.file_path(tmp_path, 'tokenizer.json', create=False).unlink()
    host.requests.clear()

    result = download.install_model(tmp_path)

    assert result.installed == ('tokenizer.json',)
    assert result.bytes_downloaded == len(host.blobs['tokenizer.json'])
    assert [name for name, _ in host.requests] == ['tokenizer.json']


def test_the_smallest_file_is_fetched_first(host, tmp_path):
    """So a 236-byte config with a bad digest fails before 834 MB does.

    The order comes from the pin table, which `pin_relations_model.py` sorts.
    Asserted here because the ordering is the reason the sort exists.
    """
    download.install_model(tmp_path)
    sizes = [len(host.blobs[name]) for name, _ in host.requests]
    assert sizes == sorted(sizes), f'not ascending: {host.requests}'


# --------------------------------------------------------------------------
# Resume, and the trap inside it
# --------------------------------------------------------------------------

def _leave_partial(app_data: Path, name: str, blob: bytes, keep: int) -> Path:
    destination = model_spec.file_path(app_data, name, create=True)
    part = model_spec.part_path(destination)
    part.write_bytes(blob[:keep])
    return part


def test_a_partial_file_is_resumed_rather_than_refetched(host, tmp_path):
    blob = host.blobs['model.safetensors']
    _leave_partial(tmp_path, 'model.safetensors', blob, 50_000)

    result = download.install_model(tmp_path)

    assert result.bytes_downloaded < len(blob), 'the whole file was refetched'
    assert ('model.safetensors', 50_000) in host.requests
    assert model_spec.file_path(
        tmp_path, 'model.safetensors', create=False).read_bytes() == blob


def test_a_server_that_ignores_range_does_not_corrupt_the_file(host, tmp_path):
    """200 with the whole body, appended to a prefix, is the silent corruption.

    It would produce a file of the right length and the wrong contents, caught
    only by the digest -- after paying for the transfer. The module checks the
    status instead and discards the stale prefix first.
    """
    blob = host.blobs['model.safetensors']
    _leave_partial(tmp_path, 'model.safetensors', blob, 50_000)
    host.range_mode = 'ignore_range'

    download.install_model(tmp_path)

    assert model_spec.file_path(
        tmp_path, 'model.safetensors', create=False).read_bytes() == blob


def test_a_206_describing_the_wrong_offset_is_refused(host, tmp_path):
    """The nastier version: the right status, the wrong `Content-Range`."""
    blob = host.blobs['model.safetensors']
    _leave_partial(tmp_path, 'model.safetensors', blob, 50_000)
    host.range_mode = 'wrong_offset'

    download.install_model(tmp_path)

    assert model_spec.file_path(
        tmp_path, 'model.safetensors', create=False).read_bytes() == blob


def test_an_oversized_part_is_discarded(host, tmp_path):
    """A `.part` longer than the pin cannot be a prefix of it."""
    blob = host.blobs['tokenizer.json']
    _leave_partial(tmp_path, 'tokenizer.json', blob + b'junk' * 100,
                   len(blob) + 400)

    download.install_model(tmp_path)

    assert model_spec.file_path(
        tmp_path, 'tokenizer.json', create=False).read_bytes() == blob


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------

def test_progress_is_monotonic_and_ends_at_the_pinned_total(host, tmp_path):
    seen = []
    download.install_model(tmp_path, progress=lambda d, t: seen.append((d, t)))

    assert seen, 'no progress was reported'
    totals = {t for _, t in seen}
    assert totals == {model_spec.TOTAL_BYTES}, f'total varied: {totals}'
    values = [d for d, _ in seen]
    assert values == sorted(values), f'not monotonic: {values}'
    assert values[0] == 0
    assert values[-1] == model_spec.TOTAL_BYTES


def test_progress_starts_from_what_is_already_present(host, tmp_path):
    """A resumed first use must not restart the bar at zero and crawl."""
    download.install_model(tmp_path)
    model_spec.file_path(tmp_path, 'model.safetensors', create=False).unlink()

    seen = []
    download.install_model(tmp_path, progress=lambda d, t: seen.append(d))

    already = model_spec.TOTAL_BYTES - len(host.blobs['model.safetensors'])
    assert seen[0] == already


def test_a_resumed_prefix_counts_toward_progress(host, tmp_path):
    """The defect this caught in review, and the reason `on_resume` exists.

    Bytes a resume keeps are on disk and belong to the set, but they are never
    passed to `on_bytes`, which reports only what this call transferred. Left
    uncounted, a resumed `model.safetensors` would hold the bar short by the
    kept prefix for the whole 834 MB and reach 100% only because the final
    callback says so.

    So the assertion is on an INTERMEDIATE value: the total must be reached by
    the transfer itself, not announced at the end.
    """
    blob = host.blobs['model.safetensors']
    _leave_partial(tmp_path, 'model.safetensors', blob, 50_000)

    seen = []
    download.install_model(tmp_path, progress=lambda d, t: seen.append(d))

    assert model_spec.TOTAL_BYTES in seen[:-1], (
        f'the bar never reached {model_spec.TOTAL_BYTES} before the final '
        f'callback; highest intermediate was {max(seen[:-1])}, short by '
        f'{model_spec.TOTAL_BYTES - max(seen[:-1])} -- the resumed prefix')


def test_on_file_names_each_file_and_its_place_in_the_set(host, tmp_path):
    seen = []
    download.install_model(tmp_path, on_file=lambda n, i, c: seen.append((n, i, c)))

    assert [i for _, i, _ in seen] == [1, 2, 3, 4]
    assert {c for _, _, c in seen} == {4}


# --------------------------------------------------------------------------
# Failure and cancellation
# --------------------------------------------------------------------------

def test_a_truncated_transfer_is_download_failed_not_model_corrupt(host, tmp_path):
    """The kinds differ by what the student can do.

    `DOWNLOAD_FAILED` is retryable and a second attempt very often works.
    `MODEL_CORRUPT` is `runtime.py`'s verdict on a file already installed,
    which is a different conversation. The digest is kept in `detail` either
    way, so the choice hides nothing.
    """
    host.cut_after = 10

    with pytest.raises(Exception) as exc:
        download.install_model(tmp_path)

    assert exc.value.kind is RelationExtractionErrorKind.DOWNLOAD_FAILED
    assert exc.value.retryable


def test_a_failed_file_is_not_installed_and_leaves_a_part(host, tmp_path):
    host.cut_after = 10

    with pytest.raises(Exception):
        download.install_model(tmp_path)

    base = model_spec.model_dir(tmp_path, create=False)
    assert list(base.rglob('*.part')), 'nothing left to resume'
    assert not model_spec.is_installed(tmp_path)
    # The smallest file is 26 bytes and cut_after=10 truncates it, so the very
    # first file fails and nothing is installed under its real name.
    assert _installed(tmp_path) == [
        p for p in _installed(tmp_path) if p.endswith('.part')]


def test_a_cancel_stops_and_keeps_what_was_already_installed(host, tmp_path):
    cancel = threading.Event()
    calls = {'n': 0}

    def stop_after_two(name, index, count):
        calls['n'] += 1
        if calls['n'] == 3:
            cancel.set()

    with pytest.raises(Exception) as exc:
        download.install_model(tmp_path, cancel=cancel, on_file=stop_after_two)

    assert exc.value.kind is RelationExtractionErrorKind.DOWNLOAD_CANCELLED
    assert not exc.value.retryable, (
        'a cancelled download is not a failure to retry; the student stopped it')
    # The two that finished are installed and usable; the set is describable.
    assert len(model_spec.missing_files(tmp_path)) == 2
    assert not model_spec.is_installed(tmp_path)


def test_discard_partials_removes_only_parts(host, tmp_path):
    download.install_model(tmp_path)
    blob = host.blobs['model.safetensors']
    model_spec.file_path(tmp_path, 'model.safetensors', create=False).unlink()
    _leave_partial(tmp_path, 'model.safetensors', blob, 1000)

    removed = download.discard_partials(tmp_path)

    assert removed == ('model.safetensors',)
    assert not list(model_spec.model_dir(tmp_path, create=False).rglob('*.part'))
    # Uninstalling is a different action with a different button.
    assert model_spec.missing_files(tmp_path) == ('model.safetensors',)


# --------------------------------------------------------------------------
# The worker contract
# --------------------------------------------------------------------------

def _import_lines() -> list:
    """Every import statement in download.py, and nothing else.

    Scanning the whole file is what the first version of these two tests did,
    and `test_no_hub_client_is_used` promptly failed on its own module
    docstring, which NAMES `huggingface_hub` while explaining why it is not
    used. Same shape as #317's lesson: a sweep measures whatever it reads, so
    read the thing the rule is about. Prose that discusses a banned name is
    the documentation working, not a violation.
    """
    source = (REPO_ROOT / 'src' / 'app' / 'relation_extraction'
              / 'download.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            lines.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            lines.append(node.module or '')
    return lines


def test_the_module_touches_no_qt_and_no_database():
    """It runs on a worker thread, where neither is allowed.

    `base_db.py` records that nothing in this application writes from a second
    thread, and `tests/app/test_foldersync_threading.py` enforces the same
    split for that feature. Here the rule is kept by the module importing
    neither, which is checkable without a thread.
    """
    imports = _import_lines()
    for banned in ('PyQt6', 'sqlite3', 'database'):
        offenders = [m for m in imports if m == banned or m.startswith(banned + '.')]
        assert not offenders, (
            f'download.py imports {offenders}, and it runs on the worker')


def test_no_hub_client_is_used():
    """Plain urllib against the pinned revision URLs, deliberately.

    `huggingface_hub` resolves `main` for some reads, which is the trap #60
    recorded when GLiNER2's own tokenizer load reached past a pinned revision.
    Checked against the import list, not the text -- the docstring names the
    package in order to explain the decision.
    """
    imports = _import_lines()
    offenders = [m for m in imports
                 if m == 'huggingface_hub' or m.startswith('huggingface_hub.')]
    assert not offenders, f'download.py imports {offenders}'
    assert any(m == 'urllib.request' for m in imports), (
        'the transport should be plain urllib; if that changed, this guard '
        'needs rewriting rather than deleting')
