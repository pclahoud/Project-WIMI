"""Resolution, verification and invocation for the speech engine (#59, T6).

Two layers, deliberately:

**Layer 1 always runs.** A fake ``whisper-cli`` -- a three-line shell script
that records its argv, prints a canned transcript on stdout, prints noise on
stderr and exits with whatever code the test asked for -- stands in for the
real binary. That is enough to hold the parts of the contract that are ours:
the exact command line T1 settled, stdout-is-the-transcript, stderr captured
and never parsed, the temp WAV deleted on every path, and a wedged run killed
at the ceiling.

**Layer 2 needs the real engine and skips without it.** It transcribes a
checked-in three-second WAV. Nothing on this machine can produce that binary
-- ``vendor/whisper/`` is populated by ``scripts/fetch_whisper.py`` (T4) at
build time -- so the skip is the normal outcome until that script has been
run, and the skip reason says so.

The fake is a **Python** stub, identical on every platform, reading its canned
output from a JSON file beside it. It used to be a POSIX ``sh`` script plus a
parallel Windows ``.cmd`` written from the documentation and never executed;
when T18 finally ran it, all three of its behaviours were wrong and eight tests
failed for reasons that had nothing to do with the product (#184). One of them
inverted: the stub's `echo ` printed ``ECHO is off.`` where empty stdout was
required, so a test asserting the runtime *rejects* empty stdout reported DID
NOT RAISE — which reads as the product failing to catch a real trap, and was
exactly backwards.

A test helper is only load-bearing if a failure in it means the product is
wrong. Two implementations of one contract cannot promise that; one can.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

from app.stt import runtime as rt
from app.stt.errors import SttError, SttErrorKind

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[2]
WAV_FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'stt_runtime_sample.wav'

#: What the fixture was synthesised from, for the layer-2 assertion message.
FIXTURE_TEXT = 'This is a test of the speech to text runtime.'

CANNED_TRANSCRIPT = 'Deep vein thrombosis presents with unilateral leg swelling.'
CANNED_STDERR = (
    'whisper_init_from_file_with_params_no_state: loading model\n'
    'whisper_print_timings: total time = 812.00 ms\n'
)


# ---------------------------------------------------------------- the fake

def fake_whisper(
    tmp_path: Path,
    *,
    stdout: str = CANNED_TRANSCRIPT,
    stderr: str = CANNED_STDERR,
    exit_code: int = 0,
    hang: bool = False,
) -> tuple[Path, Path]:
    """Write an executable stand-in for ``whisper-cli``.

    Returns ``(binary, argv_log)``; the log holds one argument per line,
    written before the fake does anything else, so it exists even for the
    hanging and failing variants.
    """
    argv_log = tmp_path / 'argv.txt'

    # One implementation, both platforms (#184). The previous version wrote a
    # POSIX `sh` script and a Windows `.cmd`, and the `.cmd` branch -- marked
    # `# pragma: no cover - not exercised on this box` -- had never run
    # anywhere until T18 ran it. It broke this docstring three ways: `echo %*`
    # put every argument on ONE line, only the FIRST line of stderr was
    # emitted, and `echo ` with an empty argument printed `ECHO is off.`
    # instead of nothing. That last one made
    # `test_empty_stdout_is_a_failure_even_at_exit_zero` report DID NOT RAISE
    # on Windows -- which reads exactly like the product failing to catch the
    # "exits 0 on unreadable audio" trap, and is the precise opposite: the
    # stub was handing it non-empty stdout, so not raising was correct.
    #
    # A test helper that can only be wrong in one direction is worth more than
    # a faster one, so the canned text lives in a JSON file the stub READS,
    # never interpolated into code. There is nothing left to escape -- the old
    # POSIX branch hand-quoted single quotes and the `.cmd` branch quoted
    # nothing at all, so `&`, `<`, `>`, `|` or `^` in a transcript would have
    # broken it.
    stub = tmp_path / 'whisper_stub.py'
    config = stub.with_suffix('.json')
    config.write_text(json.dumps({
        'argv_log': str(argv_log),
        'stdout': stdout,
        'stderr': stderr,
        'exit_code': exit_code,
        'hang': hang,
    }), encoding='utf-8')

    # Bytes, not text: Python's text mode rewrites '\n' to '\r\n' on Windows,
    # which would hand the product different trailing whitespace per platform
    # -- the same divergence in a new place. The old POSIX branch used
    # `printf '%s'` (no trailing newline) against `echo` (which appends one).
    stub.write_text(
        'import json, pathlib, sys, time\n'
        'cfg = json.loads(pathlib.Path(__file__).with_suffix(".json")'
        '.read_text(encoding="utf-8"))\n'
        '# argv first, before anything else can fail, so the log exists even\n'
        '# for the hanging and failing variants -- as the docstring promises.\n'
        'pathlib.Path(cfg["argv_log"]).write_text(\n'
        '    "".join(a + "\\n" for a in sys.argv[1:]), encoding="utf-8")\n'
        'if cfg["hang"]:\n'
        '    # sleep in THIS process. The shell version had to `exec sleep` so\n'
        '    # no grandchild inherited the stdout pipe and kept communicate()\n'
        '    # blocked past the kill; one process cannot have that problem.\n'
        '    time.sleep(30)\n'
        '    sys.exit(0)\n'
        'sys.stderr.buffer.write(cfg["stderr"].encode("utf-8"))\n'
        'sys.stderr.buffer.flush()\n'
        'sys.stdout.buffer.write(cfg["stdout"].encode("utf-8"))\n'
        'sys.stdout.buffer.flush()\n'
        'sys.exit(cfg["exit_code"])\n',
        encoding='utf-8',
    )

    # The runtime invokes `binary` as an executable, so each platform needs the
    # launcher it can actually exec. This is the ONLY branch left, it is one
    # line per side, and neither side carries logic that can disagree.
    if os.name == 'nt':
        binary = tmp_path / 'whisper-cli.cmd'
        binary.write_text(
            f'@"{sys.executable}" "{stub}" %*\r\n', encoding='utf-8')
    else:
        binary = tmp_path / 'whisper-cli'
        binary.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{stub}" "$@"\n',
            encoding='utf-8')
    binary.chmod(0o755)
    return binary, argv_log


def model_file(tmp_path: Path, content: bytes = b'ggml-fake-weights') -> rt.ModelFile:
    """Install a fake model under ``<app_data>/models/whisper`` and pin it."""
    path = rt.model_dir(tmp_path) / 'ggml-base.en.bin'
    path.write_bytes(content)
    return rt.ModelFile(
        size='base.en',
        filename='ggml-base.en.bin',
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )


def make_runtime(tmp_path: Path, binary: Path, spec: rt.ModelFile, **kw):
    return rt.WhisperRuntime(
        app_data_dir=tmp_path,
        model_size=spec.size,
        binary=binary,
        spec_lookup=lambda size: spec,
        **kw,
    )


@pytest.fixture(autouse=True)
def _clean_verdicts():
    rt.clear_verification_cache()
    yield
    rt.clear_verification_cache()


# --------------------------------------------- the fake keeps its own word

def test_the_fake_honours_its_contract_on_this_platform(tmp_path):
    """Pin `fake_whisper`'s three promises, because they were once all false.

    Every other test in this file trusts the stub. On Windows that trust was
    misplaced for the whole of Waves 0-4: the `.cmd` branch put every argument
    on one line, emitted only the first line of stderr, and turned empty
    stdout into `ECHO is off.` (#184). Eight tests failed and one *inverted* --
    `test_empty_stdout_is_a_failure_even_at_exit_zero` reported DID NOT RAISE,
    which reads as the product failing to catch the "exits 0 on unreadable
    audio" trap and was the exact opposite.

    None of those were visible from Linux, where the POSIX branch was correct
    and every test was green. So this asserts the helper's contract directly,
    on whatever platform it is running, rather than inferring it from tests
    that would go red for product-shaped reasons instead.

    All three assertions below fail against the old `.cmd` branch.
    """
    binary, argv_log = fake_whisper(tmp_path, stdout='', exit_code=0)

    # A prompt with a space, always -- that is the quoting the old branches
    # could plausibly have broken and the product genuinely depends on.
    #
    # Shell metacharacters are asserted on POSIX ONLY, and the reason is not
    # "cmd.exe is awkward". On Windows the fake must be launched through a
    # one-line `.cmd` shim, because `subprocess` needs an executable image and
    # a `.py` file is not one. cmd.exe parses its command line BEFORE `%*` is
    # substituted, so `a&b` arrives as `a` and cmd tries to run `b` as a
    # command (measured on Windows 10 Pro 19045: rc 255, stderr "The system
    # cannot find the file specified"). No amount of correctness inside the
    # stub can reach that -- the damage is upstream of it.
    #
    # It is safe to scope this because **the product has no shell to be
    # mangled by**. `binary_name()` returns `whisper-cli.exe` on win32, there
    # is no `shell=True` and no `.cmd`/`.bat` anywhere in `src/app/stt/`, and
    # `subprocess` only routes through cmd.exe for a batch target or
    # `shell=True`. The same argument through a real executable was measured
    # byte-intact on the same machine, in the same experiment, as the control.
    #
    # This matters rather than being a technicality: priming text comes from
    # subject names, and `Ears, Nose & Throat` is an entirely ordinary one.
    # It reaches the real `whisper-cli.exe` unharmed. It cannot reach a `.cmd`
    # unharmed, and the `.cmd` exists only here.
    #
    # Making the fake a real executable *is* possible -- a `[sys.executable,
    # stub]` command prefix spliced into `build_argv` would do it, since
    # Python stops claiming flags once it has a script path. It was rejected:
    # it buys a property the product does not have, at the cost of the fake no
    # longer being a path you can exec, which is what the product is handed.
    prompt = 'a b' if os.name == 'nt' else 'a&b<c>d|e^f'
    args = ['-m', 'model.bin', '-f', 'a b.wav', '-l', 'en', '--prompt', prompt]
    proc = subprocess.run(
        [str(binary), *args], capture_output=True, text=True, timeout=30)

    # 1. One argument per line, arguments intact, spaces preserved. This is
    #    the assertion that caught the old `echo %*`, which put all eleven on
    #    one line and left seven tests indexing a single element.
    assert argv_log.read_text(encoding='utf-8').splitlines() == args

    # 2. The WHOLE of stderr, not its first line. `whisper_print_timings` is
    #    on line 2 of CANNED_STDERR, and tests assert the runtime surfaces it.
    assert proc.stderr == CANNED_STDERR
    assert 'whisper_print_timings' in proc.stderr

    # 3. Empty stdout is genuinely empty. This is the one that inverted.
    assert proc.stdout == '', (
        f'the fake emitted {proc.stdout!r} when asked for empty stdout; a test '
        f'asserting the product rejects empty stdout would pass it non-empty '
        f'stdout and then blame the product for not raising (#184)'
    )


def test_the_fake_does_not_add_a_trailing_newline(tmp_path):
    """Both platforms must hand the product byte-identical stdout.

    The old POSIX branch used `printf '%s'` (no trailing newline) and the old
    `.cmd` used `echo` (which appends one), so the two platforms disagreed even
    where they were both "working". The stub writes bytes for the same reason:
    Python's text mode would rewrite '\\n' to '\\r\\n' on Windows and
    reintroduce the divergence one layer down.
    """
    binary, _ = fake_whisper(tmp_path, stdout=CANNED_TRANSCRIPT)
    proc = subprocess.run(
        [str(binary)], capture_output=True, timeout=30)
    assert proc.stdout == CANNED_TRANSCRIPT.encode('utf-8')


# ------------------------------------------------------- where things live

def test_the_binary_is_whisper_cli_and_never_main():
    """T1: ``main``/``main.exe`` is a deprecated stub, not a fallback."""
    assert rt.binary_name().startswith('whisper-cli')
    assert 'main' not in rt.binary_name()


def test_dev_mode_resolves_the_vendored_tree(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    assert rt.engine_root() == REPO_ROOT / 'vendor' / 'whisper'
    assert rt.binary_dir() == REPO_ROOT / 'vendor' / 'whisper' / rt.host_platform()


def test_frozen_is_meipass_on_windows_onedir(monkeypatch, tmp_path):
    """``dist/WIMI/_internal/whisper/windows/`` -- where PyInstaller points."""
    exe_dir = tmp_path / 'WIMI'
    internal = exe_dir / '_internal'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe_dir / 'WIMI.exe'))
    monkeypatch.setattr(sys, '_MEIPASS', str(internal), raising=False)

    assert rt.engine_root() == internal / 'whisper'


def test_frozen_is_meipass_inside_a_macos_app(monkeypatch, tmp_path):
    """``WIMI.app/Contents/Frameworks/whisper/`` -- the other shape.

    ``Path(sys.executable).parent / '_internal'`` would be
    ``Contents/MacOS/_internal``, which does not exist inside a bundle. This
    is the case that decides between the two base paths, and T18 is what
    confirms it against a real build.
    """
    exe_dir = tmp_path / 'WIMI.app' / 'Contents' / 'MacOS'
    frameworks = tmp_path / 'WIMI.app' / 'Contents' / 'Frameworks'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe_dir / 'WIMI'))
    monkeypatch.setattr(sys, '_MEIPASS', str(frameworks), raising=False)

    assert rt.engine_root() == frameworks / 'whisper'
    assert rt.binary_dir() == frameworks / 'whisper' / rt.host_platform()


def test_the_frozen_path_never_probes_the_filesystem(monkeypatch, tmp_path):
    """``_MEIPASS`` is the answer by definition, not a candidate to be tested.

    Nothing on disk exists here; the resolver must still name the directory.
    A resolver that probed would return the other base path -- or nothing.
    """
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'nowhere' / 'WIMI'))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'also-nowhere'), raising=False)

    assert rt.engine_root() == tmp_path / 'also-nowhere' / 'whisper'
    assert not rt.engine_root().exists()


def test_no_platform_tag_contains_a_dot(monkeypatch):
    """PyInstaller rewrites a dotted directory under ``Contents/Frameworks``.

    It leaves a symlink behind to satisfy codesign, so a tag like
    ``macos.arm64`` would not have been collected verbatim and the runtime
    would look in a name the build no longer uses.
    """
    for platform_name, machine in (
        ('win32', 'AMD64'), ('darwin', 'arm64'), ('darwin', 'x86_64'), ('linux', 'x86_64'),
    ):
        monkeypatch.setattr(sys, 'platform', platform_name)
        monkeypatch.setattr(rt.platform_mod, 'machine', lambda m=machine: m)
        assert '.' not in rt.host_platform()


@pytest.mark.parametrize('frozen', [False, True])
def test_the_model_path_has_no_frozen_branch(monkeypatch, tmp_path, frozen):
    """The model is downloaded, so it is in ``app_data`` either way (D2)."""
    if frozen:
        monkeypatch.setattr(sys, 'frozen', True, raising=False)
        monkeypatch.setattr(sys, 'executable', str(tmp_path / 'WIMI' / 'WIMI.exe'))
    else:
        monkeypatch.delattr(sys, 'frozen', raising=False)

    assert rt.model_dir(tmp_path) == tmp_path / 'models' / 'whisper'
    assert rt.model_dir(tmp_path).is_dir()   # created eagerly


def test_a_present_but_unexecutable_binary_does_not_count(monkeypatch, tmp_path):
    if os.name == 'nt':
        pytest.skip('the executable bit is a POSIX notion')
    monkeypatch.delattr(sys, 'frozen', raising=False)
    binary, _ = fake_whisper(tmp_path)
    binary.chmod(0o644)
    monkeypatch.setattr(rt, 'binary_path', lambda: binary)

    assert rt.find_binary() is None


# ------------------------------------------------- three states, not one

def test_no_binary_and_no_model_are_different_problems(tmp_path):
    """The whole point of the three states: different fixes, different kinds."""
    spec = rt.ModelFile(size='base.en', filename='ggml-base.en.bin')
    runtime = rt.WhisperRuntime(
        app_data_dir=tmp_path,
        model_size='base.en',
        binary=tmp_path / 'nothing-here',
        spec_lookup=lambda size: spec,
    )
    status = runtime.availability().to_dict()

    assert status['engine_ready'] is False
    assert status['model_ready'] is False
    assert status['engine']['error']['kind'] == SttErrorKind.BINARY_MISSING.value
    assert status['model']['error']['kind'] == SttErrorKind.MODEL_MISSING.value
    assert status['engine']['error']['kind'] != status['model']['error']['kind']


def test_an_engine_without_a_model_says_so(tmp_path):
    binary, _ = fake_whisper(tmp_path)
    spec = rt.ModelFile(size='base.en', filename='ggml-base.en.bin')
    runtime = make_runtime(tmp_path, binary, spec)
    status = runtime.availability().to_dict()

    assert status['engine_ready'] is True
    assert status['model_ready'] is False
    assert status['model']['error']['kind'] == SttErrorKind.MODEL_MISSING.value
    # Not installed at all -- as opposed to installed and corrupt.
    assert status['model']['installed'] is False
    assert status['model']['size'] == 'base.en'


def test_a_corrupt_model_is_installed_but_not_ready(tmp_path):
    binary, _ = fake_whisper(tmp_path)
    spec = model_file(tmp_path)
    truncated = spec.size_bytes // 2
    (rt.model_dir(tmp_path) / spec.filename).write_bytes(b'x' * truncated)
    runtime = make_runtime(tmp_path, binary, spec)
    status = runtime.availability().to_dict()

    assert status['model_ready'] is False
    assert status['model']['error']['kind'] == SttErrorKind.MODEL_CORRUPT.value
    assert status['model']['installed'] is True


def test_both_present_is_ready_and_the_microphone_is_still_separate(tmp_path):
    binary, _ = fake_whisper(tmp_path)
    spec = model_file(tmp_path)
    runtime = make_runtime(tmp_path, binary, spec)

    unasked = runtime.availability()
    assert unasked.engine.ready and unasked.model.ready
    # Nobody asked the recorder. That is not "no microphone" and must not be
    # rendered as one.
    assert unasked.to_dict()['microphone_ready'] is None
    assert unasked.ready is False

    asked = runtime.availability(microphone={'ready': True, 'devices': ['Default']})
    assert asked.to_dict()['microphone_ready'] is True
    assert asked.ready is True
    assert asked.to_dict()['mic']['devices'] == ['Default']

    no_mic = runtime.availability(microphone={'ready': False, 'devices': []})
    assert no_mic.to_dict()['microphone_ready'] is False
    # Engine and model unaffected: three states, independently reported.
    assert no_mic.engine.ready and no_mic.model.ready


# ------------------------------------------------------------ verification

def test_a_matching_model_verifies(tmp_path):
    spec = model_file(tmp_path)
    rt.verify_model_file(rt.model_dir(tmp_path) / spec.filename, spec)


def test_a_wrong_size_is_named_before_anything_is_hashed(tmp_path, monkeypatch):
    spec = model_file(tmp_path)
    path = rt.model_dir(tmp_path) / spec.filename
    path.write_bytes(b'short')
    monkeypatch.setattr(rt, '_sha256_file', _never_called)

    with pytest.raises(SttError) as caught:
        rt.verify_model_file(path, spec)
    assert caught.value.kind is SttErrorKind.MODEL_CORRUPT
    assert 'expected' in caught.value.detail


def test_a_wrong_digest_is_named(tmp_path):
    spec = model_file(tmp_path, b'A' * 64)
    path = rt.model_dir(tmp_path) / spec.filename
    path.write_bytes(b'B' * 64)      # same length, different bytes

    with pytest.raises(SttError) as caught:
        rt.verify_model_file(path, spec)
    assert caught.value.kind is SttErrorKind.MODEL_CORRUPT
    assert 'sha256' in caught.value.detail


def test_an_unpinned_digest_checks_the_size_only(tmp_path, caplog):
    content = b'ggml-unpinned'
    path = rt.model_dir(tmp_path) / 'ggml-base.en.bin'
    path.write_bytes(content)
    spec = rt.ModelFile('base.en', 'ggml-base.en.bin', sha256='', size_bytes=len(content))

    rt.verify_model_file(path, spec)          # does not raise
    assert 'no pinned sha256' in caplog.text


def test_the_verdict_is_cached_and_reinstated_when_the_file_changes(tmp_path, monkeypatch):
    """Verifying 141 MB on every status poll would be visible to a student."""
    calls = []
    real = rt._sha256_file
    monkeypatch.setattr(
        rt, '_sha256_file', lambda p: (calls.append(p), real(p))[1]
    )
    spec = model_file(tmp_path, b'C' * 128)
    path = rt.model_dir(tmp_path) / spec.filename

    rt.verify_model_file(path, spec)
    rt.verify_model_file(path, spec)
    assert len(calls) == 1

    # A replaced file must be verified again, not inherit the old verdict.
    path.write_bytes(b'D' * 128)
    os.utime(path, (time.time() + 2, time.time() + 2))
    with pytest.raises(SttError):
        rt.verify_model_file(path, spec)
    assert len(calls) == 2


def _never_called(path):
    raise AssertionError(f'hashed {path} when the byte size already disagreed')


# ------------------------------------------------------------------- argv

def test_the_command_line_is_the_one_T1_settled(tmp_path):
    binary, _ = fake_whisper(tmp_path)
    spec = model_file(tmp_path)
    runtime = make_runtime(tmp_path, binary, spec, threads=3)
    model = rt.model_dir(tmp_path) / spec.filename
    wav = tmp_path / 'clip.wav'

    assert runtime.build_argv(binary, model, wav) == [
        str(binary),
        '-m', str(model),
        '-f', str(wav),
        '-l', 'en',
        '-t', '3',
        '-np',
        '-nt',
    ]


def test_prompt_is_present_only_when_priming_produced_something(tmp_path):
    binary, _ = fake_whisper(tmp_path)
    spec = model_file(tmp_path)
    runtime = make_runtime(tmp_path, binary, spec)
    model = rt.model_dir(tmp_path) / spec.filename
    wav = tmp_path / 'clip.wav'

    assert '--prompt' not in runtime.build_argv(binary, model, wav)
    assert '--prompt' not in runtime.build_argv(binary, model, wav, prompt='')
    assert '--prompt' not in runtime.build_argv(binary, model, wav, prompt='   \n ')

    primed = runtime.build_argv(binary, model, wav, prompt='thrombosis, embolism')
    assert primed[-2:] == ['--prompt', 'thrombosis, embolism']


def test_the_default_thread_count_leaves_headroom():
    assert 1 <= rt.default_thread_count() <= 4


# -------------------------------------------------------------- invocation

def test_stdout_is_the_transcript_and_stderr_is_not(tmp_path):
    binary, argv_log = fake_whisper(tmp_path)
    spec = model_file(tmp_path)
    runtime = make_runtime(tmp_path, binary, spec)
    wav = tmp_path / 'clip.wav'
    wav.write_bytes(b'RIFF....')

    result = runtime.transcribe(wav, prompt='thrombosis')

    assert result.text == CANNED_TRANSCRIPT
    # stderr is carried for the log and never mixed into the transcript.
    assert 'whisper_print_timings' in result.stderr
    assert 'whisper_print_timings' not in result.text
    assert result.ms >= 0

    argv = argv_log.read_text().splitlines()
    assert argv[:2] == ['-m', str(rt.model_dir(tmp_path) / spec.filename)]
    assert argv[2:4] == ['-f', str(wav)]
    assert '-np' in argv and '-nt' in argv
    assert argv[-2:] == ['--prompt', 'thrombosis']


def test_empty_stdout_is_a_failure_even_at_exit_zero(tmp_path):
    """The measured shape of an unreadable recording (#59 comment #2185).

    ``whisper-cli`` exits **0** on an audio file it cannot read, prints
    ``error: failed to read audio file`` on stderr and writes nothing to
    stdout. A missing model returns 3, so the return code separates those two
    and not this one: for unreadable audio, empty stdout is the only signal
    there is. Checking only ``returncode != 0`` would hand the student a
    silently empty field.
    """
    binary, _ = fake_whisper(
        tmp_path, stdout='\n', stderr='error: failed to read audio file', exit_code=0,
    )
    spec = model_file(tmp_path)
    wav = tmp_path / 'clip.wav'
    wav.write_bytes(b'this is not audio')

    with pytest.raises(SttError) as caught:
        make_runtime(tmp_path, binary, spec).transcribe(wav)
    assert caught.value.kind is SttErrorKind.TRANSCRIPTION_FAILED
    assert 'failed to read audio file' in caught.value.detail
    assert caught.value.retryable is True


def test_a_non_zero_exit_carries_the_stderr_tail(tmp_path):
    binary, _ = fake_whisper(
        tmp_path, exit_code=3, stderr='error: failed to initialize whisper context',
    )
    spec = model_file(tmp_path)
    wav = tmp_path / 'clip.wav'
    wav.write_bytes(b'RIFF....')

    with pytest.raises(SttError) as caught:
        make_runtime(tmp_path, binary, spec).transcribe(wav)
    assert caught.value.kind is SttErrorKind.TRANSCRIPTION_FAILED
    assert 'failed to initialize whisper context' in caught.value.detail
    assert caught.value.retryable is True


def test_a_wedged_run_is_killed_at_the_ceiling(tmp_path):
    """One worker means one wedged subprocess would hold the feature forever."""
    if os.name == 'nt':  # pragma: no cover
        pytest.skip('the hanging fake is a POSIX sh script')
    binary, _ = fake_whisper(tmp_path, hang=True)
    spec = model_file(tmp_path)
    wav = tmp_path / 'clip.wav'
    wav.write_bytes(b'RIFF....')
    runtime = make_runtime(tmp_path, binary, spec, timeout_s=1.0)

    started = time.monotonic()
    with pytest.raises(SttError) as caught:
        runtime.transcribe(wav)
    elapsed = time.monotonic() - started

    assert caught.value.kind is SttErrorKind.TRANSCRIPTION_TIMEOUT
    assert elapsed < 15, f'the kill did not happen at the ceiling ({elapsed:.1f}s)'
    assert not wav.exists()


@pytest.mark.parametrize(
    'kwargs',
    [{}, {'exit_code': 4}, {'hang': True}],
    ids=['success', 'failure', 'timeout'],
)
def test_the_recording_is_deleted_on_every_path(tmp_path, kwargs):
    if kwargs.get('hang') and os.name == 'nt':  # pragma: no cover
        pytest.skip('the hanging fake is a POSIX sh script')
    binary, _ = fake_whisper(tmp_path, **kwargs)
    spec = model_file(tmp_path)
    wav = tmp_path / 'clip.wav'
    wav.write_bytes(b'RIFF....')
    runtime = make_runtime(tmp_path, binary, spec, timeout_s=1.0)

    try:
        runtime.transcribe(wav)
    except SttError:
        pass

    assert not wav.exists()


def test_a_file_this_process_does_not_own_survives(tmp_path):
    binary, _ = fake_whisper(tmp_path)
    spec = model_file(tmp_path)
    wav = tmp_path / 'fixture.wav'
    wav.write_bytes(b'RIFF....')

    make_runtime(tmp_path, binary, spec).transcribe(wav, delete_audio=False)
    assert wav.exists()


def test_the_missing_binary_is_reported_before_anything_runs(tmp_path):
    spec = model_file(tmp_path)
    runtime = rt.WhisperRuntime(
        app_data_dir=tmp_path,
        model_size=spec.size,
        binary=tmp_path / 'not-installed',
        spec_lookup=lambda size: spec,
    )
    wav = tmp_path / 'clip.wav'
    wav.write_bytes(b'RIFF....')

    with pytest.raises(SttError) as caught:
        runtime.transcribe(wav)
    assert caught.value.kind is SttErrorKind.BINARY_MISSING
    assert caught.value.retryable is False
    # The finally still ran: the recording does not outlive the failure.
    assert not wav.exists()


def test_a_missing_model_never_reaches_the_engine(tmp_path):
    """``whisper-cli`` exits 3 for a missing model. We never find out.

    Verification happens first, so a missing or corrupt model is named as
    itself (``model_missing``/``model_corrupt``, with a download or a
    re-download as the fix) instead of arriving as a subprocess exit code
    that has to be told apart from exit 0 on unreadable audio.
    """
    binary, argv_log = fake_whisper(tmp_path)
    spec = rt.ModelFile('base.en', 'ggml-base.en.bin', sha256='ab' * 32, size_bytes=10)
    wav = tmp_path / 'clip.wav'
    wav.write_bytes(b'RIFF....')

    with pytest.raises(SttError) as caught:
        make_runtime(tmp_path, binary, spec).transcribe(wav)

    assert caught.value.kind is SttErrorKind.MODEL_MISSING
    assert not argv_log.exists(), 'the engine was invoked with no model'
    assert not wav.exists()


@pytest.mark.parametrize('suffix', ['.wav', '.mp3', '.ogg', '.flac', '.m4a'])
def test_no_input_format_is_enforced(tmp_path, suffix):
    """T1: whisper.cpp resamples whatever it is handed. We do not validate."""
    binary, argv_log = fake_whisper(tmp_path)
    spec = model_file(tmp_path)
    audio = tmp_path / f'clip{suffix}'
    audio.write_bytes(b'not really audio')

    result = make_runtime(tmp_path, binary, spec).transcribe(audio)

    assert result.text == CANNED_TRANSCRIPT
    assert str(audio) in argv_log.read_text().splitlines()


# ---------------------------------------------- the pin table T21 provides

def test_a_spec_is_read_from_a_mapping_or_an_object():
    """``model_spec.py`` is T21's; this only pins the fields we consume."""
    from_mapping = rt.ModelFile.from_spec(
        'base.en',
        {'filename': 'ggml-base.en.bin', 'sha256': 'ab' * 32, 'size_bytes': 147964211},
    )

    class Spec:
        filename = 'ggml-base.en.bin'
        sha256 = 'ab' * 32
        size_bytes = 147964211

    from_object = rt.ModelFile.from_spec('base.en', Spec())

    assert from_mapping == from_object
    assert from_mapping.filename == 'ggml-base.en.bin'
    assert from_mapping.size_bytes == 147964211


def test_a_spec_without_a_filename_is_refused():
    with pytest.raises(ValueError):
        rt.ModelFile.from_spec('base', {'sha256': 'ab' * 32})


# ----------------------------------------------------- layer 2: real engine

def _real_binary() -> Path | None:
    found = rt.find_binary()
    if found is not None:
        return found
    on_path = shutil.which('whisper-cli')
    return Path(on_path) if on_path else None


def _installed_model() -> Path | None:
    """A ggml model already downloaded into this checkout's ``app_data``.

    Deliberately only that one place, so the real-engine tests exercise the
    same ``model_dir()`` this module resolves in production rather than a
    special case built for the test.
    """
    for path in sorted((REPO_ROOT / 'app_data' / 'models' / 'whisper').glob('ggml-*.bin')):
        if path.is_file():
            return path
    return None


@pytest.fixture
def real_engine():
    """A ``WhisperRuntime`` on the vendored binary and a downloaded model.

    Skips when either is absent, which is the normal state of a fresh
    checkout: ``vendor/whisper/`` is git-ignored and filled by
    ``scripts/fetch_whisper.py``, and the weights are downloaded at runtime.
    """
    binary = _real_binary()
    if binary is None:
        pytest.skip(
            'no whisper-cli: run `python scripts/fetch_whisper.py --platform '
            '<platform>` to populate vendor/whisper/, or put one on PATH'
        )
    model = _installed_model()
    if model is None:
        pytest.skip(
            'no ggml model in app_data/models/whisper/ -- download one '
            '(WIMI does this on first run; see src/app/stt/download.py)'
        )
    spec = rt.ModelFile(
        size=model.stem.replace('ggml-', ''),
        filename=model.name,
        sha256='',                       # the pin is T21's; size-only here
        size_bytes=model.stat().st_size,
    )
    return rt.WhisperRuntime(
        app_data_dir=REPO_ROOT / 'app_data',
        model_size=spec.size,
        binary=binary,
        spec_lookup=lambda size: spec,
    )


@pytest.mark.slow
def test_the_real_engine_transcribes_the_fixture(real_engine, tmp_path):
    """The done-when: a real transcription of a real three-second recording."""
    assert WAV_FIXTURE.is_file(), f'missing audio fixture: {WAV_FIXTURE}'
    # Copy rather than pointing at the fixture, so the deletion in
    # transcribe()'s finally is exercised for real without losing it.
    clip = tmp_path / 'clip.wav'
    shutil.copyfile(WAV_FIXTURE, clip)

    result = real_engine.transcribe(clip, prompt='thrombosis, embolism')

    assert not clip.exists()
    assert result.text.strip(), (
        'the engine ran but produced nothing; stderr was:\n' + result.stderr
    )
    # Hyphens become spaces before the split, because **where a model puts
    # them is a model's choice and not a transcription error**. Measured on
    # this box (#59, T17): the same fixture and the same binary give
    # "the speech to text runtime" on ``tiny.en`` and "the speech-to-text
    # runtime" on ``small.en-q5_1`` -- which is the pinned default, so this
    # assertion failed against a perfect transcript on any machine that had
    # downloaded the model WIMI actually ships with. Nothing noticed, because
    # the fixture skips wherever ``vendor/whisper/`` or the weights are
    # absent: every worktree, and CI.
    words = {
        w.strip('.,!?').lower() for w in result.text.replace('-', ' ').split()
    }
    assert {'test', 'speech'} <= words, (
        'the fixture is SYNTHESISED speech (ffmpeg flite, voice=slt) reading '
        f'{FIXTURE_TEXT!r}; whisper heard {result.text!r}. Check the audio '
        'before concluding the runtime is broken.'
    )


@pytest.mark.slow
def test_the_real_engine_exits_zero_on_audio_it_cannot_read(real_engine, tmp_path):
    """The measured fact the empty-stdout check exists for (#59 comment #2185).

    Confirmed here against whisper.cpp 1.9.4 (b5130) on Linux: a text file
    named ``.wav`` exits **0** with nothing on stdout. If a future release
    ever starts exiting non-zero this test still passes -- what it guards is
    that the wrapper reports the failure at all.
    """
    not_audio = tmp_path / 'clip.wav'
    not_audio.write_text('this is plainly not audio\n', encoding='utf-8')

    with pytest.raises(SttError) as caught:
        real_engine.transcribe(not_audio)

    assert caught.value.kind is SttErrorKind.TRANSCRIPTION_FAILED
    assert 'failed to read audio' in caught.value.detail
    assert not not_audio.exists()


@pytest.mark.slow
def test_the_real_engine_hallucinates_on_silence_rather_than_saying_nothing(
    real_engine, tmp_path,
):
    """Why treating empty stdout as a failure cannot swallow a silent recording.

    Three seconds of digital silence comes back as a *word* (``" you"`` on
    ``tiny.en``), not as empty output -- so "empty" never means "the student
    said nothing". It also shows why the recorder's peak check matters beyond
    the Windows privacy toggle: without it, an invented word lands in the
    reflection field.
    """
    silence = tmp_path / 'silence.wav'
    with wave.open(str(silence), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b'\x00\x00' * 16000 * 3)

    result = real_engine.transcribe(silence)

    assert result.text.strip(), (
        'silence produced empty stdout on this build, which would make the '
        'empty-stdout failure check fire on a quiet recording. Re-read the '
        'table in runtime.py before changing that check.'
    )


def test_the_fixture_is_the_recording_it_claims_to_be():
    """A three-second 16 kHz mono WAV, checked without opening the engine."""
    assert WAV_FIXTURE.is_file()
    with wave.open(str(WAV_FIXTURE), 'rb') as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 16000
        seconds = handle.getnframes() / handle.getframerate()
    assert 2.0 <= seconds <= 4.0, f'{seconds:.2f}s is not a 2-3 second clip'
