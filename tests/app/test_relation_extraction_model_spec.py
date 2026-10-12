"""The GLiNER2 pin table and what reads it (#60).

Three groups, and they answer different questions.

The first asserts things about the **real** table, because a pin table nobody
checked is the failure this arrangement exists to prevent -- a committed row of
64 zeros would otherwise sail through every other test here, since the logic
tests all run against a small fake table.

The second drives that fake table through the filesystem helpers. It is fake
for a concrete reason: the real ``model.safetensors`` is 834 MB, and a test
that creates a file of that size to check a ``stat`` either wastes a minute of
I/O or depends on sparse-file support, which is a property of the filesystem
rather than of this code.

The third is the quarantine check for this module specifically. ``model_spec``
is **not** re-exported by the package ``__init__``, so
``test_relation_extraction_availability.py``'s quarantine test does not cover
it -- and this is the module the download path and Settings both import.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.relation_extraction import RelationExtractionErrorKind
from app.relation_extraction import model_spec as ms

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ZERO_DIGEST = '0' * 64


# --------------------------------------------------------------------------
# The real table
# --------------------------------------------------------------------------

def test_every_row_is_actually_pinned():
    """A row of 64 zeros means the pinning script was never run.

    That is the one defect every other test in this file would miss, because
    they use a fake table. ``scripts/pin_relations_model.py`` refuses to write
    a table in this state, so reaching it means somebody hand-edited a row and
    committed it.
    """
    unpinned = [
        name for name, pin in ms.MODEL_FILES.items()
        if pin.sha256 == ZERO_DIGEST or pin.size_bytes == 0
    ]
    assert not unpinned, (
        f"{unpinned} carry a placeholder digest or a zero size. Run "
        f"`python scripts/pin_relations_model.py` rather than typing a digest")


def test_every_digest_is_a_sha256():
    for name, pin in ms.MODEL_FILES.items():
        assert len(pin.sha256) == 64, f"{name}: {len(pin.sha256)} characters"
        assert set(pin.sha256) <= set('0123456789abcdef'), name


def test_the_ignored_list_and_the_pin_table_do_not_overlap():
    """The half of the partition that can be checked without a network.

    The other half -- that the two lists together cover the repository -- is
    checked by the pinning script against the live listing, because only the
    repository knows what it contains.
    """
    both = set(ms.IGNORED_FILES) & set(ms.MODEL_FILES)
    assert not both, (
        f"{both} are both pinned and ignored, so the two lists contradict "
        f"each other about whether the model needs them")


def test_the_total_is_the_sum_and_the_unit_is_decimal_mb():
    """845.1 MB, not 806.

    Earlier #60 notes quote 806 MB and that figure is **MiB**. Both are
    asserted so the next person to 'correct' one of them has to read this.
    #59 settled that a download dialog speaks decimal MB.
    """
    assert ms.TOTAL_BYTES == sum(p.size_bytes for p in ms.MODEL_FILES.values())
    assert ms.TOTAL_BYTES == 845_060_368

    assert round(ms.total_megabytes(), 1) == 845.1
    assert round(ms.TOTAL_BYTES / (1 << 20), 1) == 805.9, (
        "this is where 806 comes from -- it is the MiB figure, and it is not "
        "what a download dialog should say")


def test_the_weights_dominate_so_order_matters():
    """Smallest first, and the biggest file last.

    Not a style preference: a failure on 236 bytes of config should happen
    before 834 MB of weights, both when downloading and when verifying.
    """
    sizes = [ms.MODEL_FILES[n].size_bytes for n in ms.MODEL_FILE_NAMES]
    assert sizes == sorted(sizes), f"not in ascending size order: {sizes}"
    assert ms.MODEL_FILE_NAMES[-1] == 'model.safetensors'


def test_the_url_carries_the_pinned_revision():
    url = ms.download_url('config.json')
    assert ms.MODEL_REVISION in url
    assert url.endswith('/config.json')
    assert 'main' not in url.split('/resolve/')[1].split('/')[0], (
        "a branch name here would let a re-upload change what a student "
        "downloads without this file changing")


def test_an_unpinned_name_is_refused_rather_than_guessed():
    with pytest.raises(KeyError) as exc:
        ms.download_url('definitely-not-a-model-file.bin')
    assert 'pinned files are' in str(exc.value)


# --------------------------------------------------------------------------
# Name validation. The names come from a remote listing.
# --------------------------------------------------------------------------

@pytest.mark.parametrize('name', [
    '../../users.db',
    'a/../../b',
    '/etc/passwd',
    'C:\\windows\\system32\\x',
    'nested\\windows\\separator',
    '',
    ' config.json',
    'config.json ',
])
def test_a_name_that_could_escape_the_model_directory_is_refused(name):
    """This is the difference from #59's module, and it is not theoretical.

    ``app/stt/model_spec.py`` writes each filename as a literal constant. Here
    the pinning script enumerates a *remote repository* and writes what it
    finds, so the publisher chooses these strings -- and the downloader joins
    them onto the model directory and writes there.
    """
    with pytest.raises(ValueError):
        ms._validate_name(name)


@pytest.mark.parametrize('name', ['./config.json', 'a//b', 'a/./b'])
def test_a_name_that_is_not_canonical_is_refused_for_a_different_reason(name):
    """These are harmless to *write* and poisonous to *compare*.

    ``./config.json`` normalises to the right file, so it is not a traversal
    risk. It is still refused, because the pinning script decides that the pin
    table and ``IGNORED_FILES`` partition the repository listing by comparing
    these strings for equality against the names the API returns. A name that
    means the right file and spells it differently matches nothing, gets
    reported as unclassified, and turns the check that exists to catch a *new*
    required file into an argument about an existing one.
    """
    with pytest.raises(ValueError) as exc:
        ms._validate_name(name)
    assert 'canonical' in str(exc.value)


@pytest.mark.parametrize('name', ['config.json', 'encoder_config/config.json'])
def test_the_real_names_validate(name):
    assert ms._validate_name(name) == name


# --------------------------------------------------------------------------
# A small fake table, driven through the filesystem helpers
# --------------------------------------------------------------------------

@pytest.fixture
def fake_table(monkeypatch):
    """Three files, one in a subdirectory, totalling 30 bytes.

    Returns ``{name: content}``. The subdirectory entry mirrors
    ``encoder_config/config.json``, which is the case that needs a nested
    ``mkdir`` and is the one a flat implementation passes anyway.
    """
    contents = {
        'small.json': b'a' * 5,
        'sub/nested.json': b'b' * 10,
        'weights.bin': b'c' * 15,
    }
    files = {
        name: ms.FilePin(
            name=name,
            sha256=hashlib.sha256(blob).hexdigest(),
            size_bytes=len(blob),
        )
        for name, blob in contents.items()
    }
    monkeypatch.setattr(ms, 'MODEL_FILES', files)
    monkeypatch.setattr(ms, 'MODEL_FILE_NAMES', tuple(files))
    monkeypatch.setattr(ms, 'TOTAL_BYTES', sum(p.size_bytes for p in files.values()))
    return contents


def _install(app_data: Path, contents: dict, *, only=None) -> None:
    for name, blob in contents.items():
        if only is not None and name not in only:
            continue
        target = ms.file_path(app_data, name)
        target.write_bytes(blob)


def test_the_model_directory_is_the_same_in_dev_and_frozen(tmp_path):
    """No ``sys.frozen`` branch anywhere, so nothing to parametrise.

    Asserted by reading the source rather than by faking frozen mode, because
    the claim is about the absence of a branch.
    """
    source = (REPO_ROOT / 'src' / 'app' / 'relation_extraction'
              / 'model_spec.py').read_text(encoding='utf-8')
    code = source.split('"""', 2)[2]
    # `sys.frozen`, not the bare word: `@dataclass(frozen=True)` is unrelated
    # and a scan for 'frozen' matches it, which is how this test first failed.
    assert 'sys.frozen' not in code and "'frozen'" not in code, (
        "a frozen-mode branch here could only point inside the bundle, which "
        "is read-only on macOS and replaced on every update")

    assert ms.model_dir(tmp_path, create=False) == tmp_path / 'models' / 'gliner2'


def test_create_false_has_no_side_effect(tmp_path):
    ms.model_dir(tmp_path, create=False)
    assert not (tmp_path / 'models').exists(), (
        "a Settings line reporting a path must not create one")


def test_a_nested_name_gets_its_subdirectory(tmp_path, fake_table):
    target = ms.file_path(tmp_path, 'sub/nested.json')
    assert target == tmp_path / 'models' / 'gliner2' / 'sub' / 'nested.json'
    assert target.parent.is_dir(), "the parent is not always the model directory"


def test_part_path_sorts_beside_the_file_it_becomes(tmp_path, fake_table):
    target = ms.file_path(tmp_path, 'weights.bin', create=False)
    assert ms.part_path(target).name == 'weights.bin.part'


def test_nothing_installed_means_every_file_is_missing(tmp_path, fake_table):
    assert ms.missing_files(tmp_path) == tuple(ms.MODEL_FILE_NAMES)
    assert ms.is_installed(tmp_path) is False
    assert ms.bytes_still_needed(tmp_path) == 30


def test_a_partial_install_is_described_rather_than_rejected(tmp_path, fake_table):
    """Six files present and the weights absent is the ordinary state after a
    cancel. It is neither installed nor empty, and the set is what says so."""
    _install(tmp_path, fake_table, only={'small.json', 'sub/nested.json'})

    assert ms.missing_files(tmp_path) == ('weights.bin',)
    assert ms.is_installed(tmp_path) is False
    assert ms.bytes_still_needed(tmp_path) == 15


def test_everything_present_at_the_pinned_size_is_installed(tmp_path, fake_table):
    _install(tmp_path, fake_table)
    assert ms.missing_files(tmp_path) == ()
    assert ms.is_installed(tmp_path) is True
    assert ms.bytes_still_needed(tmp_path) == 0


def test_a_wrong_sized_file_counts_as_missing_in_full(tmp_path, fake_table):
    """The downloader replaces rather than range-resuming, so a truncated file
    costs its whole size again. Reporting the difference would understate it."""
    _install(tmp_path, fake_table)
    ms.file_path(tmp_path, 'weights.bin', create=False).write_bytes(b'c' * 3)

    assert ms.missing_files(tmp_path) == ('weights.bin',)
    assert ms.bytes_still_needed(tmp_path) == 15


def test_is_installed_does_not_hash(tmp_path, fake_table, monkeypatch):
    """It is what a page asks before offering a download.

    Hashing 845 MB to render a button is #147's mistake -- a status check doing
    real work -- in another costume.
    """
    _install(tmp_path, fake_table)
    monkeypatch.setattr(ms, 'sha256_file', lambda *a, **k: pytest.fail(
        'is_installed hashed a file'))
    assert ms.is_installed(tmp_path) is True


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def test_a_missing_file_is_missing_not_corrupt(tmp_path, fake_table):
    """The fixes differ: fetch it, versus fetch it again."""
    with pytest.raises(Exception) as exc:
        ms.verify_file(tmp_path / 'nope.json', ms.MODEL_FILES['small.json'])
    assert exc.value.kind is RelationExtractionErrorKind.MODEL_MISSING


def test_a_wrong_size_is_reported_without_hashing(tmp_path, fake_table, monkeypatch):
    """Size first, because it is a stat and catches the common failure."""
    target = ms.file_path(tmp_path, 'weights.bin')
    target.write_bytes(b'c' * 3)
    monkeypatch.setattr(ms, 'sha256_file', lambda *a, **k: pytest.fail(
        'hashed a file whose size already disagreed'))

    with pytest.raises(Exception) as exc:
        ms.verify_file(target, ms.MODEL_FILES['weights.bin'])
    assert exc.value.kind is RelationExtractionErrorKind.MODEL_CORRUPT
    assert '3 bytes' in exc.value.message


def test_the_right_size_with_the_wrong_content_is_caught(tmp_path, fake_table):
    """The case the cheap check cannot see, which is why the digest decides."""
    target = ms.file_path(tmp_path, 'weights.bin')
    target.write_bytes(b'X' * 15)

    with pytest.raises(Exception) as exc:
        ms.verify_file(target, ms.MODEL_FILES['weights.bin'])
    assert exc.value.kind is RelationExtractionErrorKind.MODEL_CORRUPT
    assert 'sha256' in str(exc.value.detail)


def test_a_correct_file_verifies(tmp_path, fake_table):
    _install(tmp_path, fake_table, only={'weights.bin'})
    ms.verify_file(
        ms.file_path(tmp_path, 'weights.bin', create=False),
        ms.MODEL_FILES['weights.bin'],
    )


def test_verify_dir_hashes_the_whole_set(tmp_path, fake_table):
    _install(tmp_path, fake_table)
    ms.verify_dir(tmp_path)


def test_verify_dir_reports_the_smallest_failure_first(tmp_path, fake_table):
    """A corrupt config is reported in milliseconds rather than after the
    weights, which is the whole reason the order is ascending."""
    _install(tmp_path, fake_table)
    ms.file_path(tmp_path, 'small.json', create=False).write_bytes(b'z' * 5)
    ms.file_path(tmp_path, 'weights.bin', create=False).write_bytes(b'z' * 15)

    with pytest.raises(Exception) as exc:
        ms.verify_dir(tmp_path)
    assert 'small.json' in exc.value.message


def test_progress_runs_across_the_whole_set_not_per_file(tmp_path, fake_table):
    """The offset bug a closure over the loop variable would produce.

    ``verify_dir`` binds the running offset as a default argument. A closure
    over the loop variable would report every file from the FINAL offset, so
    the sequence would end at 90 for 30 bytes of files and would not be
    monotonic. Both are asserted, because the first alone passes for a
    relay that reports nothing at all.
    """
    _install(tmp_path, fake_table)
    seen = []
    ms.verify_dir(tmp_path, progress=lambda done, total: seen.append((done, total)))

    assert seen, "no progress was reported at all"
    assert all(total == 30 for _, total in seen)
    values = [done for done, _ in seen]
    assert values == sorted(values), f"not monotonic: {values}"
    assert values[-1] == 30, f"ended at {values[-1]} for 30 bytes of files"


def test_a_cancel_is_honoured_between_chunks(tmp_path, fake_table):
    """Hashing 834 MB is seconds of work. A cancel that applied only to the
    network half would look like the button had stopped responding."""
    _install(tmp_path, fake_table, only={'weights.bin'})
    target = ms.file_path(tmp_path, 'weights.bin', create=False)

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Exception) as exc:
        ms.sha256_file(target, cancel=cancel, chunk_bytes=4)
    assert exc.value.kind is RelationExtractionErrorKind.DOWNLOAD_CANCELLED


def test_sha256_file_agrees_with_hashlib_across_chunk_boundaries(tmp_path):
    """A chunk size that does not divide the file is the off-by-one case."""
    blob = bytes(range(256)) * 40
    target = tmp_path / 'blob.bin'
    target.write_bytes(blob)
    assert ms.sha256_file(target, chunk_bytes=7) == hashlib.sha256(blob).hexdigest()


# --------------------------------------------------------------------------
# The quarantine, for this module specifically
# --------------------------------------------------------------------------

def test_importing_model_spec_does_not_import_the_runtime():
    """``model_spec`` is not re-exported by the package ``__init__``.

    So the package-level quarantine test in
    ``test_relation_extraction_availability.py`` does not cover this file --
    and this is the one the download path and the Settings line both import by
    name. On the default artifact torch does not exist, so a module-scope
    import here would be an ImportError before the window appeared.

    Runs against the relations venv when there is one, so the assertion can
    actually fail; against a venv with no torch it is a tautology, which is
    why it skips with a reason rather than reporting a pass.
    """
    relations_python = REPO_ROOT / '.venv-relations' / 'bin' / 'python'
    interpreter = (str(relations_python) if relations_python.exists()
                   else sys.executable)

    probe = (
        "import sys; sys.path[:0] = [%r, %r]\n"
        "import app.relation_extraction.model_spec as m\n"
        "loaded = [n for n in (%r) if n in sys.modules]\n"
        "print('LOADED:' + ','.join(loaded))\n"
        % (str(REPO_ROOT), str(REPO_ROOT / 'src'),
           ms_runtime_packages())
    )
    out = subprocess.run(
        [interpreter, '-c', probe], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, f"probe failed:\n{out.stdout}\n{out.stderr}"

    loaded = out.stdout.strip().removeprefix('LOADED:')
    assert loaded == '', (
        f"importing app.relation_extraction.model_spec loaded {loaded}")

    if interpreter == sys.executable:
        pytest.skip(
            'ran against the default venv, which has no runtime to load; the '
            'assertion above cannot fail here. Build .venv-relations for this '
            'to mean something.')


def ms_runtime_packages():
    from app.relation_extraction.availability import RUNTIME_PACKAGES
    return RUNTIME_PACKAGES
