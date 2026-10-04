"""Tests for ``scripts/fetch_whisper.py`` -- the whisper.cpp binary fetcher.

What is worth testing here is not that the constants say what they say. It
is the handful of behaviours that stand between a build host and an
executable that runs on the build machine and fails on a student's:

* every pinned file arrives, flat, plus a licence the archive does not carry;
* a bad digest refuses **and leaves a good tree alone**;
* an incomplete tree is noticed on a later run, not reported as ready --
  ``fetch_llama_server.py``'s "does the binary exist" short-circuit would
  call a tree missing eight DLLs already present;
* an archive whose CPU-variant set has drifted from the pin is refused,
  because ggml picks one by ``LoadLibrary`` at runtime and a silently
  narrowed set only fails on hardware nobody here owns;
* ``macos-arm64`` says why it cannot be fetched instead of doing nothing;
* nothing reaches for model weights (owner decision D2).

Everything runs offline against synthetic archives. The one test that does
touch the network checks the real pins and is opt-in -- set
``WIMI_WHISPER_NETWORK_TESTS=1`` -- because a CI run should not pull 8.5 MB
from GitHub to learn something a pin bump already had to prove.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "fetch_whisper.py"


def _load_script():
    """Import the fetcher by path -- ``scripts/`` is not a package.

    The same arrangement ``tests/test_ascii_prints_gate.py`` uses, for the
    same reason.
    """
    spec = importlib.util.spec_from_file_location("fetch_whisper", SCRIPT_PATH)
    assert spec and spec.loader, "could not load %s" % SCRIPT_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = _load_script()


# --------------------------------------------------------------------------
# Rig: synthetic archives, a fake network, a scratch vendor directory.
# --------------------------------------------------------------------------


def _payload(name: str) -> bytes:
    """Distinct, non-empty bytes per member, so digests differ."""
    return ("payload for " + name + "\n").encode() * 8


def _write_zip(path: Path, names, prefix="Release/") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(prefix + name, _payload(name))


def _write_targz(path: Path, names, prefix="whisper-bin-ubuntu-x64/") -> None:
    with tarfile.open(path, "w:gz") as tf:
        for name in names:
            data = _payload(name)
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Rig:
    """A patched fetcher: scratch vendor dir, synthetic assets, no network."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp = tmp_path
        self.vendor = tmp_path / "vendor" / "whisper"
        self.sources = tmp_path / "sources"
        self.sources.mkdir()
        self.urls: list = []
        self.responses: dict = {}

        monkeypatch.setattr(fetch, "VENDOR_DIR", self.vendor)
        monkeypatch.setattr(fetch, "PLATFORMS", copy.deepcopy(fetch.PLATFORMS))
        monkeypatch.setattr(fetch, "download", self._download)

        licence = self.sources / "LICENSE"
        licence.write_text("MIT License\n\nsynthetic\n", encoding="utf-8")
        monkeypatch.setattr(fetch, "LICENSE_SHA256", _sha256(licence))
        self.responses[fetch.LICENSE_URL.format(tag=fetch.RELEASE_TAG)] = licence
        self.licence = licence

    def _download(self, url: str, dest: Path) -> None:
        self.urls.append(url)
        source = self.responses.get(url)
        if source is None:
            raise AssertionError("unexpected download: " + url)
        shutil.copyfile(source, dest)

    def stage(self, key: str, names=None, **overrides):
        """Build the platform's asset from ``names`` and repin its digest."""
        pin = fetch.PLATFORMS[key]
        if names is None:
            names = list(pin["files"])
        asset = self.sources / pin["asset"]
        if pin["kind"] == "zip":
            _write_zip(asset, names)
        else:
            _write_targz(asset, names)
        pin["sha256"] = _sha256(asset)
        pin.update(overrides)
        self.responses[
            fetch.RELEASE_URL.format(tag=fetch.RELEASE_TAG, asset=pin["asset"])
        ] = asset
        return asset

    def out(self, key: str) -> Path:
        return self.vendor / key

    def run(self, *argv) -> int:
        return fetch.main(list(argv))


@pytest.fixture
def rig(tmp_path, monkeypatch) -> Rig:
    return Rig(tmp_path, monkeypatch)


# --------------------------------------------------------------------------
# A fetch produces a complete, flat tree with a licence in it.
# --------------------------------------------------------------------------


def test_a_fetch_lands_every_pinned_file_plus_the_licence(rig):
    # The real zip also carries llama.dll, SDL2.dll, parakeet* and a dozen
    # test binaries. None of them is WIMI's business.
    decoys = ["llama.dll", "SDL2.dll", "main.exe", "test-vad.exe", "bench.exe"]
    rig.stage("windows", list(fetch.PLATFORMS["windows"]["files"]) + decoys)

    assert rig.run("--platform", "windows") == 0

    out = rig.out("windows")
    for name in fetch.PLATFORMS["windows"]["files"]:
        assert (out / name).is_file(), name + " was not installed"
    assert (out / "LICENSE").read_text(encoding="utf-8").startswith("MIT")
    for name in decoys:
        assert not (out / name).exists(), name + " should not have been kept"


def test_the_archive_directory_prefix_is_stripped(rig):
    """whisper-cli finds its libraries beside itself, not under Release/."""
    rig.stage("windows")
    assert rig.run("--platform", "windows") == 0
    assert not (rig.out("windows") / "Release").exists()
    assert (rig.out("windows") / "whisper-cli.exe").is_file()


def test_all_nine_windows_cpu_libraries_are_installed(rig):
    rig.stage("windows")
    assert rig.run("--platform", "windows") == 0
    installed = sorted(p.name for p in rig.out("windows").glob("ggml-cpu-*.dll"))
    assert len(installed) == 9, installed


def test_a_second_run_does_not_download_again(rig):
    rig.stage("windows")
    assert rig.run("--platform", "windows") == 0
    before = len(rig.urls)
    assert rig.run("--platform", "windows") == 0
    assert len(rig.urls) == before


def test_force_downloads_again(rig):
    rig.stage("windows")
    assert rig.run("--platform", "windows") == 0
    before = len(rig.urls)
    assert rig.run("--platform", "windows", "--force") == 0
    assert len(rig.urls) > before


# --------------------------------------------------------------------------
# An incomplete tree is noticed. This is the silent-failure mode.
# --------------------------------------------------------------------------


def test_a_deleted_cpu_library_is_noticed_and_refetched(rig, capsys):
    rig.stage("windows")
    assert rig.run("--platform", "windows") == 0
    (rig.out("windows") / "ggml-cpu-skylakex.dll").unlink()
    capsys.readouterr()

    assert rig.run("--platform", "windows") == 0

    output = capsys.readouterr().out
    assert "ggml-cpu-skylakex.dll" in output
    assert "INCOMPLETE" in output
    # and it is back
    assert (rig.out("windows") / "ggml-cpu-skylakex.dll").is_file()


def test_a_deleted_cpu_library_is_not_reported_as_already_present(rig, capsys):
    """The short-circuit must not key on the binary alone."""
    rig.stage("windows")
    rig.run("--platform", "windows")
    (rig.out("windows") / "ggml-cpu-haswell.dll").unlink()
    capsys.readouterr()

    rig.run("--platform", "windows")

    assert "already present" not in capsys.readouterr().out


def test_check_names_the_missing_library_without_the_network(rig, capsys):
    rig.stage("windows")
    assert rig.run("--platform", "windows") == 0
    (rig.out("windows") / "ggml-cpu-sse42.dll").unlink()
    before = len(rig.urls)
    capsys.readouterr()

    assert rig.run("--platform", "windows", "--check") == 1

    assert "ggml-cpu-sse42.dll" in capsys.readouterr().out
    assert len(rig.urls) == before, "--check must not touch the network"


def test_the_incompleteness_report_explains_why_the_set_matters(rig, capsys):
    """A build engineer reading the failure needs the reason, not a name."""
    rig.stage("windows")
    rig.run("--platform", "windows")
    (rig.out("windows") / "ggml-cpu-x64.dll").unlink()
    capsys.readouterr()

    rig.run("--platform", "windows", "--check")

    assert "runtime" in capsys.readouterr().out.lower()


def test_an_emptied_file_counts_as_missing(rig, capsys):
    rig.stage("windows")
    rig.run("--platform", "windows")
    (rig.out("windows") / "ggml.dll").write_bytes(b"")
    capsys.readouterr()

    assert rig.run("--platform", "windows", "--check") == 1
    assert "ggml.dll" in capsys.readouterr().out


def test_a_tampered_file_is_caught_by_the_manifest(rig, capsys):
    """Presence is not integrity: a non-empty wrong file must still fail."""
    rig.stage("windows")
    rig.run("--platform", "windows")
    target = rig.out("windows") / "whisper.dll"
    target.write_bytes(target.read_bytes() + b"x")
    capsys.readouterr()

    assert rig.run("--platform", "windows", "--check") == 1
    assert "whisper.dll" in capsys.readouterr().out


def test_check_on_nothing_installed_fails(rig):
    assert rig.run("--platform", "windows", "--check") == 1


def test_the_manifest_records_a_digest_per_installed_file(rig):
    rig.stage("windows")
    rig.run("--platform", "windows")

    manifest = json.loads(
        (rig.out("windows") / fetch.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["release_tag"] == fetch.RELEASE_TAG
    for name in fetch.PLATFORMS["windows"]["files"]:
        assert manifest["files"][name] == _sha256(rig.out("windows") / name)


# --------------------------------------------------------------------------
# Digests.
# --------------------------------------------------------------------------


def test_a_wrong_asset_digest_refuses_and_installs_nothing(rig, capsys):
    rig.stage("windows")
    fetch.PLATFORMS["windows"]["sha256"] = "00" * 32

    assert rig.run("--platform", "windows") == 1

    assert "MISMATCH" in capsys.readouterr().err
    assert not rig.out("windows").exists()


def test_a_wrong_asset_digest_leaves_a_good_tree_intact(rig):
    """Nothing is deleted until every check has passed."""
    rig.stage("windows")
    assert rig.run("--platform", "windows") == 0
    good = sorted(p.name for p in rig.out("windows").iterdir())

    fetch.PLATFORMS["windows"]["sha256"] = "11" * 32
    assert rig.run("--platform", "windows", "--force") == 1

    assert sorted(p.name for p in rig.out("windows").iterdir()) == good


def test_a_wrong_licence_digest_refuses(rig, capsys, monkeypatch):
    rig.stage("windows")
    monkeypatch.setattr(fetch, "LICENSE_SHA256", "22" * 32)

    assert rig.run("--platform", "windows") == 1

    assert "LICENSE" in capsys.readouterr().err
    assert not rig.out("windows").exists()


def test_the_asset_digest_is_checked_before_the_licence_is_fetched(rig):
    """A bad asset should not cost a second request."""
    rig.stage("windows")
    fetch.PLATFORMS["windows"]["sha256"] = "33" * 32

    rig.run("--platform", "windows")

    assert not any("LICENSE" in url for url in rig.urls)


# --------------------------------------------------------------------------
# Upstream drift in the CPU-variant set.
# --------------------------------------------------------------------------


def test_an_archive_with_an_extra_cpu_variant_is_refused(rig, capsys):
    """A bump that adds a variant must stop the build, not widen silently."""
    names = list(fetch.PLATFORMS["windows"]["files"]) + ["ggml-cpu-zen5.dll"]
    rig.stage("windows", names)

    assert rig.run("--platform", "windows") == 1

    err = capsys.readouterr().err
    assert "ggml-cpu-zen5.dll" in err
    assert not rig.out("windows").exists()


def test_an_archive_missing_a_cpu_variant_is_refused(rig, capsys):
    names = [
        n for n in fetch.PLATFORMS["windows"]["files"]
        if n != "ggml-cpu-icelake.dll"
    ]
    rig.stage("windows", names)

    assert rig.run("--platform", "windows") == 1

    assert "ggml-cpu-icelake.dll" in capsys.readouterr().err
    assert not rig.out("windows").exists()


def test_a_cpu_drift_refusal_does_not_destroy_a_good_tree(rig):
    rig.stage("windows")
    assert rig.run("--platform", "windows") == 0

    rig.stage("windows", list(fetch.PLATFORMS["windows"]["files"]) + ["ggml-cpu-zen5.dll"])
    assert rig.run("--platform", "windows", "--force") == 1

    assert (rig.out("windows") / "whisper-cli.exe").is_file()


def test_an_archive_missing_a_pinned_library_fails_after_extraction(rig, capsys):
    names = [n for n in fetch.PLATFORMS["windows"]["files"] if n != "whisper.dll"]
    rig.stage("windows", names)

    assert rig.run("--platform", "windows") == 1

    assert "whisper.dll" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Linux: dev-only, and the SONAME links the loader actually asks for.
# --------------------------------------------------------------------------


def test_the_linux_soname_links_are_created(rig):
    rig.stage("linux")
    assert rig.run("--platform", "linux") == 0

    out = rig.out("linux")
    for link, target in fetch.PLATFORMS["linux"]["links"].items():
        path = out / link
        assert path.exists(), link + " missing"
        assert path.read_bytes() == (out / target).read_bytes()


def test_the_linux_binary_is_made_executable(rig):
    rig.stage("linux")
    rig.run("--platform", "linux")
    assert os.access(rig.out("linux") / "whisper-cli", os.X_OK)


def test_all_fourteen_linux_cpu_libraries_are_installed(rig):
    rig.stage("linux")
    rig.run("--platform", "linux")
    installed = sorted(p.name for p in rig.out("linux").glob("libggml-cpu-*.so"))
    assert len(installed) == 14, installed


def test_the_linux_fetch_says_it_is_not_a_ship_target(rig, capsys):
    rig.stage("linux")
    rig.run("--platform", "linux")
    assert "development target only" in capsys.readouterr().out


# --------------------------------------------------------------------------
# macOS: answered, never silent.
# --------------------------------------------------------------------------


def test_macos_arm64_exits_two_and_names_the_reason(rig, capsys):
    assert rig.run("--platform", "macos-arm64") == 2

    err = capsys.readouterr().err
    assert "no asset to fetch" in err
    assert "source" in err.lower()
    assert "cmake" in err.lower(), "the recipe must be printed, not alluded to"


def test_macos_arm64_produces_no_directory(rig):
    rig.run("--platform", "macos-arm64")
    assert not (rig.vendor / "macos-arm64").exists()


def test_macos_arm64_does_not_touch_the_network(rig):
    rig.run("--platform", "macos-arm64")
    assert rig.urls == []


def test_all_covers_the_fetchable_platforms_and_says_macos_is_not_one(rig, capsys):
    rig.stage("windows")
    rig.stage("linux")

    assert rig.run("--platform", "all") == 0

    out = capsys.readouterr().out
    assert "macos-arm64" in out, "'all' must say what it is leaving out"
    assert (rig.out("windows") / "whisper-cli.exe").is_file()
    assert (rig.out("linux") / "whisper-cli").is_file()


# --------------------------------------------------------------------------
# Scope: the binary, and only the binary (owner decision D2).
# --------------------------------------------------------------------------


def test_nothing_reaches_for_model_weights(rig):
    rig.stage("windows")
    rig.stage("linux")
    rig.run("--platform", "all")

    for url in rig.urls:
        lowered = url.lower()
        assert "huggingface" not in lowered
        assert "ggml-base" not in lowered
        assert not lowered.endswith(".bin"), url


def test_no_model_directory_is_created(rig, tmp_path):
    rig.stage("windows")
    rig.run("--platform", "windows")

    stray = [p for p in tmp_path.rglob("*") if p.is_dir() and "model" in p.name]
    assert stray == []


# --------------------------------------------------------------------------
# Standing properties of the script itself.
# --------------------------------------------------------------------------


def test_the_script_imports_only_the_standard_library():
    """A build script must run on a bare interpreter, before any venv."""
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is None:  # pragma: no cover - Python < 3.10
        pytest.skip("sys.stdlib_module_names needs Python 3.10+")
    outside = sorted(r for r in roots if r not in stdlib and r != "__future__")
    assert outside == [], "third-party imports: " + ", ".join(outside)


def test_every_print_is_ascii():
    """The build scripts redirect stdout, and cp1252 raises inside print (#137)."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"):
            continue
        for literal in ast.walk(node):
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                if not literal.value.isascii():
                    offenders.append((literal.lineno, literal.value[:40]))
    assert offenders == [], offenders


def test_the_vendor_directory_is_git_ignored():
    """The tree this script writes must never reach the public mirror."""
    target = PROJECT_ROOT / "vendor" / "whisper" / "windows" / "whisper-cli.exe"
    result = subprocess.run(
        ["git", "check-ignore", "-v", str(target)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "vendor/whisper/ is NOT ignored"
    assert "/vendor/" in result.stdout


def test_the_release_tag_is_a_build_tag_not_a_semantic_one():
    """Semantic tags are not reliably asset-bearing; build tags are.

    v1.9.3 and v1.9.4 publish no assets at all, so a ``v``-pin can fetch
    nothing -- checked against the real release list on 2026-09-23.
    """
    assert fetch.RELEASE_TAG.startswith("b")
    assert fetch.RELEASE_TAG[1:].isdigit()


# --------------------------------------------------------------------------
# The real pins. Opt-in: WIMI_WHISPER_NETWORK_TESTS=1
# --------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("WIMI_WHISPER_NETWORK_TESTS") != "1",
    reason="set WIMI_WHISPER_NETWORK_TESTS=1 to verify the pins against GitHub",
)
@pytest.mark.parametrize("key", sorted(fetch.PLATFORMS))
def test_the_pinned_digests_match_what_upstream_serves(key, tmp_path):
    import urllib.request

    pin = fetch.PLATFORMS[key]
    url = fetch.RELEASE_URL.format(tag=fetch.RELEASE_TAG, asset=pin["asset"])
    dest = tmp_path / pin["asset"]
    request = urllib.request.Request(url, headers={"User-Agent": "WIMI-test/1.0"})
    with urllib.request.urlopen(request, timeout=300) as resp:
        with open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
    assert _sha256(dest) == pin["sha256"], key + " pin is stale"
