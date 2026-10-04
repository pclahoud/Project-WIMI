"""Tests for ``scripts/pin_whisper_model.py``, the #59 T21 pin refresher.

The pin table is the only thing between a student's first recording and
whatever the host happens to be serving, and everything downstream trusts it:
``download.py`` verifies against it, ``runtime.py`` (T6) re-verifies against it
at load time, and §3.7 keeps no other record that a model is installed. **A
wrong pin is worse than no pin**, so the script that writes those digests is
tested for the two failure modes that would be silent:

* it **misreads** the table -- a row the regex does not match is dropped, and
  a model quietly stops being pinned;
* it **mangles** the file -- the rewrite has to leave valid Python that says
  exactly what the network said and nothing else.

Both are checked by round-tripping through a miniature spec module and
``exec``-ing the result, and by parsing the *real* ``model_spec.py`` and
comparing the script's view of it against what Python imports. Those two must
agree; if they ever do not, the script is editing a table nobody reads.

The network half is opt-in. Set ``WIMI_STT_NETWORK=1`` to run the live
``--check`` against huggingface.co. It is not a marker because
``--strict-markers`` would need one registered in ``pytest.ini``, and a shared
file is not worth editing for a skip.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "pin_whisper_model.py"
SPEC_PATH = PROJECT_ROOT / "src" / "app" / "stt" / "model_spec.py"

pytestmark = pytest.mark.unit


def _load_script():
    """Import the script by path -- ``scripts/`` is not a package.

    The same arrangement ``tests/test_import_guide_sync.py`` and
    ``tests/test_stt_measure.py`` use, for the same reason.
    """
    spec = importlib.util.spec_from_file_location("pin_whisper_model", SCRIPT_PATH)
    assert spec and spec.loader, f"could not load {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pin = _load_script()


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64

MINI_SPEC = f"""\
MODEL_REPO = 'org/repo'
MODEL_REVISION = '{"0" * 40}'


def _pins():
    return (
        {pin.BEGIN_MARK}
        ('tiny', 'ggml-tiny.bin', '{DIGEST_A}', 100),
        ('base', 'ggml-base.bin', '{DIGEST_B}', 200),
        {pin.END_MARK}
    )


PINS = _pins()
"""


def exec_spec(source: str) -> dict:
    namespace: dict = {}
    exec(compile(source, "<mini_spec>", "exec"), namespace)
    return namespace


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def test_reads_repo_revision_and_rows():
    repo, revision, rows = pin.read_spec(MINI_SPEC)

    assert repo == "org/repo"
    assert revision == "0" * 40
    assert [(r.size, r.filename, r.sha256, r.size_bytes) for r in rows] == [
        ("tiny", "ggml-tiny.bin", DIGEST_A, 100),
        ("base", "ggml-base.bin", DIGEST_B, 200),
    ]


def test_the_scripts_view_of_the_real_table_matches_what_python_imports():
    """The regex and the interpreter must be looking at the same table."""
    from app.stt import model_spec

    repo, revision, rows = pin.read_spec(SPEC_PATH.read_text(encoding="utf-8"))

    assert repo == model_spec.MODEL_REPO
    assert revision == model_spec.MODEL_REVISION
    assert [r.size for r in rows] == list(model_spec.MODEL_SIZES)
    for row in rows:
        live = model_spec.MODELS[row.size]
        assert (row.filename, row.sha256, row.size_bytes) == (
            live.filename,
            live.sha256,
            live.size_bytes,
        )


def test_a_missing_marker_is_a_clear_refusal_not_a_silent_no_op():
    with pytest.raises(SystemExit) as caught:
        pin.read_spec("MODEL_REPO = 'org/repo'\nMODEL_REVISION = '%s'\n" % ("0" * 40))
    assert "marker" in str(caught.value).lower()


def test_a_row_the_regex_cannot_read_stops_the_script():
    """A dropped row would silently unpin a model."""
    broken = MINI_SPEC.replace(
        f"('base', 'ggml-base.bin', '{DIGEST_B}', 200),",
        'ModelSpec(size="base"),',
    )
    with pytest.raises(SystemExit) as caught:
        pin.read_spec(broken)
    assert "Unrecognised line" in str(caught.value)


def test_an_empty_pin_block_is_refused():
    empty = MINI_SPEC.replace(
        f"        ('tiny', 'ggml-tiny.bin', '{DIGEST_A}', 100),\n"
        f"        ('base', 'ggml-base.bin', '{DIGEST_B}', 200),\n",
        "",
    )
    with pytest.raises(SystemExit) as caught:
        pin.read_spec(empty)
    assert "empty" in str(caught.value)


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def test_rewriting_unchanged_rows_is_byte_identical():
    """Otherwise "nothing changed" would not mean nothing changed."""
    _, _, rows = pin.read_spec(MINI_SPEC)

    assert pin.replace_block(MINI_SPEC, rows) == MINI_SPEC


def test_a_rewritten_file_is_still_valid_python_and_says_the_new_thing():
    _, _, rows = pin.read_spec(MINI_SPEC)
    rows[1] = pin.Row("base", "ggml-base.bin", "c" * 64, 999)

    rewritten = pin.replace_block(MINI_SPEC, rows)

    assert exec_spec(rewritten)["PINS"] == (
        ("tiny", "ggml-tiny.bin", DIGEST_A, 100),
        ("base", "ggml-base.bin", "c" * 64, 999),
    )
    # and re-reading it agrees with what was written
    assert [r.sha256 for r in pin.read_spec(rewritten)[2]] == [DIGEST_A, "c" * 64]


def test_adding_a_row_lands_in_the_table_in_order():
    _, _, rows = pin.read_spec(MINI_SPEC)
    rows.append(pin.Row("small", "ggml-small.bin", "d" * 64, 300))

    pins = exec_spec(pin.replace_block(MINI_SPEC, rows))["PINS"]

    assert [row[0] for row in pins] == ["tiny", "base", "small"]


def test_the_revision_is_replaced_once_and_only_the_revision():
    rewritten = pin.replace_revision(MINI_SPEC, "f" * 40)

    namespace = exec_spec(rewritten)
    assert namespace["MODEL_REVISION"] == "f" * 40
    assert namespace["MODEL_REPO"] == "org/repo"
    assert namespace["PINS"][0][2] == DIGEST_A, "the digests are untouched"


def test_the_real_spec_round_trips_untouched():
    source = SPEC_PATH.read_text(encoding="utf-8")
    _, revision, rows = pin.read_spec(source)

    assert pin.replace_block(pin.replace_revision(source, revision), rows) == source


# --------------------------------------------------------------------------
# the LFS pointer, which is what makes a network-cheap refresh possible
# --------------------------------------------------------------------------


def test_a_pointer_is_parsed_into_a_digest_and_a_size(monkeypatch):
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{DIGEST_A}\n"
        "size 77704715\n"
    )
    monkeypatch.setattr(pin, "http_get", lambda url, token: pointer.encode())

    assert pin.lfs_pointer("org/repo", "0" * 40, "ggml-tiny.bin", None) == (
        DIGEST_A,
        77704715,
    )


def test_something_that_is_not_a_pointer_is_reported_not_guessed_at(monkeypatch):
    monkeypatch.setattr(pin, "http_get", lambda url, token: b"\x00\x01binary model")

    assert pin.lfs_pointer("org/repo", "0" * 40, "ggml-tiny.bin", None) is None


# --------------------------------------------------------------------------
# house rules
# --------------------------------------------------------------------------


def test_the_script_is_pure_ascii():
    """``scripts/check_ascii_prints.py`` covers ``src/`` and ``run_wimi.py``
    only, but the reason behind it (#137: a redirected stdout on Windows
    encodes through cp1252 and an em dash raises from inside ``print()``)
    applies to anything anybody pipes into a log file."""
    SCRIPT_PATH.read_text(encoding="utf-8").encode("ascii")


def test_the_script_shares_no_code_with_the_downloader_it_checks():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]  # ignore the docstring, which names them

    assert "from app" not in body
    assert "import app" not in body
    assert "download.py" not in body.replace("src/app/stt/download.py", "")


# --------------------------------------------------------------------------
# the live host, opt-in
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("WIMI_STT_NETWORK"),
    reason="set WIMI_STT_NETWORK=1 to query huggingface.co",
)
def test_check_against_the_real_host_leaves_the_pins_alone():
    before = SPEC_PATH.read_bytes()

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHANGED" not in result.stdout, "the committed pins have drifted"
    assert "CONFLICT" not in result.stdout, "the API and the LFS pointer disagree"
    assert SPEC_PATH.read_bytes() == before, "--check must not write"
