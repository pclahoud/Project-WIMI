#!/usr/bin/env python3
"""Fetch the pinned whisper.cpp CLI binary into vendor/whisper/<platform>/.

WIMI runs speech-to-text by shelling out to whisper.cpp's ``whisper-cli``
binary (issue #59, plan section 3.2: no Python bindings, because native
extensions have failed to freeze here three times). This script downloads
the pinned release asset for one platform, verifies its sha256 against the
pins below, and extracts the binary, its shared libraries and the MIT
LICENSE into ``vendor/whisper/<platform>/``.

It does NOT touch model weights. Owner decision D2: the weights download
at first run into ``app_data/models/``, never from a build step, so that a
build host with a warm ``vendor/`` cannot quietly ship them. Weight pinning
is ``src/app/stt/model_spec.py`` and ``scripts/pin_whisper_model.py``.

Usage:
    python scripts/fetch_whisper.py                     # host platform
    python scripts/fetch_whisper.py --platform windows
    python scripts/fetch_whisper.py --platform all --force
    python scripts/fetch_whisper.py --platform windows --check   # no network

OUTPUT LAYOUT -- this is the interface the build wiring reads (T5).
Everything lands FLAT in one directory per platform; the archive's own
``Release/`` and ``whisper-bin-ubuntu-x64/`` prefixes are stripped, because
whisper-cli finds its libraries beside itself (Windows: same-directory DLL
search; Linux: ``RUNPATH=$ORIGIN``, measured).

    vendor/whisper/windows/whisper-cli.exe
    vendor/whisper/windows/whisper.dll
    vendor/whisper/windows/ggml.dll
    vendor/whisper/windows/ggml-base.dll
    vendor/whisper/windows/ggml-cpu-*.dll        (nine of them)
    vendor/whisper/windows/LICENSE
    vendor/whisper/windows/fetch_manifest.json

The spec files bundle that tree to ``_internal/whisper/<platform>/``.
``/vendor/`` is git-ignored (.gitignore:217), so nothing here is committed.

PLATFORMS

  windows      SHIP TARGET. ``whisper-bin-x64.zip``. Deliberately not
               ``whisper-blas-bin-x64.zip`` (+13 MB of libopenblas) and not
               the cuBLAS variants (270 MB / 674 MB, assume an NVIDIA GPU).

  linux        DEV ONLY -- NOT A SHIP TARGET. WIMI does not distribute a
               Linux build. This exists so the development box, which is
               Linux, can run a real transcription for the integration test
               (T6) and the accuracy harness (T3). Do not add it to a spec
               file or a build script.

  macos-arm64  SHIP TARGET, but NOT FETCHABLE. whisper.cpp publishes no
               macOS binary and never has: the release workflow has
               ``ubuntu-*`` and ``windows-*`` jobs, and its single
               ``macos-latest`` job builds an iOS xcframework
               (``-DCMAKE_SYSTEM_NAME=iOS``), which is not a runnable macOS
               CLI. This is where the shape stops matching
               ``scripts/fetch_llama_server.py`` -- llama.cpp does publish
               macos-arm64 assets. Asking for it here exits 2 and prints the
               source-build recipe rather than producing nothing.

TO BUMP THE PIN

Change ``RELEASE_TAG``, then re-run and paste in the digests it prints. Note
that binaries live on **build-number tags** (``b5130``); several semantic
``vX.Y.Z`` tags carry no assets at all, so a ``v``-pin can fetch nothing.
Every sha256 below was computed from a fresh download by this script, never
transcribed from a web page. Refresh the file lists too: if upstream adds a
CPU variant the script refuses the archive rather than guess.

Stdlib only -- runnable with any Python 3.9+, no venv required.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

RELEASE_TAG = "b5130"

RELEASE_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/{tag}/{asset}"

# The Windows zip ships no LICENSE file (measured). Fetch MIT from the repo
# root at the same tag. Cross-check: this digest is byte-identical to the
# LICENSE the Linux tarball does carry.
LICENSE_URL = "https://raw.githubusercontent.com/ggml-org/whisper.cpp/{tag}/LICENSE"
LICENSE_SHA256 = "94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d"
LICENSE_NAME = "LICENSE"

MANIFEST_NAME = "fetch_manifest.json"

# Why every CPU variant ships, stated where somebody would delete one.
CPU_DISPATCH_NOTE = (
    "ggml loads the CPU variant matching the host processor at runtime,\n"
    "  with no static import (observed: whisper-cli.exe imports only ggml.dll\n"
    "  and whisper.dll; the Linux binary logged 'loaded CPU backend from\n"
    "  libggml-cpu-haswell.so'). Trimming 'the ones we do not need' therefore\n"
    "  produces a build that runs on the build machine and fails on a\n"
    "  student's."
)

WINDOWS_CPU_DLLS = (
    "ggml-cpu-alderlake.dll",
    "ggml-cpu-cannonlake.dll",
    "ggml-cpu-cascadelake.dll",
    "ggml-cpu-haswell.dll",
    "ggml-cpu-icelake.dll",
    "ggml-cpu-sandybridge.dll",
    "ggml-cpu-skylakex.dll",
    "ggml-cpu-sse42.dll",
    "ggml-cpu-x64.dll",
)

LINUX_CPU_SOS = (
    "libggml-cpu-alderlake.so",
    "libggml-cpu-cannonlake.so",
    "libggml-cpu-cascadelake.so",
    "libggml-cpu-cooperlake.so",
    "libggml-cpu-haswell.so",
    "libggml-cpu-icelake.so",
    "libggml-cpu-ivybridge.so",
    "libggml-cpu-piledriver.so",
    "libggml-cpu-sandybridge.so",
    "libggml-cpu-sapphirerapids.so",
    "libggml-cpu-skylakex.so",
    "libggml-cpu-sse42.so",
    "libggml-cpu-x64.so",
    "libggml-cpu-zen4.so",
)

PLATFORMS = {
    "windows": {
        "asset": "whisper-bin-x64.zip",
        "sha256": "f9ec6c52a2e949b62ab51fa21d0d497958f9e41c3010c157c4e42932d5316f3c",
        "kind": "zip",
        "binary": "whisper-cli.exe",
        # Extracted from the archive, by basename. Nothing else in the zip is
        # WIMI's business: llama.dll, parakeet*, SDL2.dll, every test-* and
        # the deprecated main.exe stub all stay behind.
        "files": (
            "whisper-cli.exe",
            "whisper.dll",
            "ggml.dll",
            "ggml-base.dll",
        ) + WINDOWS_CPU_DLLS,
        "links": {},
        "cpu_pattern": "ggml-cpu-*.dll",
        "ship": True,
    },
    "linux": {
        "asset": "whisper-bin-ubuntu-x64.tar.gz",
        "sha256": "53e7fd8b5764edad916b8848dd0af6abb1ff1d3b86c899e79c78652412536c32",
        "kind": "tar.gz",
        "binary": "whisper-cli",
        "files": (
            "whisper-cli",
            "libwhisper.so.1.9.4",
            "libggml.so.0.23.0",
            "libggml-base.so.0.23.0",
        ) + LINUX_CPU_SOS,
        # The SONAME links the loader actually resolves: whisper-cli asks for
        # libwhisper.so.1 and libggml.so.0, not for the versioned filenames.
        "links": {
            "libwhisper.so.1": "libwhisper.so.1.9.4",
            "libggml.so.0": "libggml.so.0.23.0",
            "libggml-base.so.0": "libggml-base.so.0.23.0",
        },
        "cpu_pattern": "libggml-cpu-*.so",
        "ship": False,
    },
}

# Named so that asking for it is answered, not ignored.
SOURCE_BUILD_PLATFORMS = ("macos-arm64",)

MACOS_BUILD_RECIPE = """\
    git clone https://github.com/ggml-org/whisper.cpp
    cd whisper.cpp && git checkout {tag}
    cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_METAL_EMBED_LIBRARY=ON
    cmake --build build -j --config Release
    mkdir -p "{dest}"
    cp build/bin/whisper-cli "{dest}/"
    cp build/src/libwhisper*.dylib build/ggml/src/libggml*.dylib "{dest}/"
    cp LICENSE "{dest}/"
"""

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "vendor" / "whisper"


def host_platform() -> str:
    """The key this host would fetch by default.

    Any macOS host answers ``macos-arm64``: WIMI's macOS build is arm64 only
    (#59 -> build_macos.sh), and an Intel Mac has no asset to fetch either,
    so the source-build refusal is the right answer for both.
    """
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos-arm64"
    return "linux"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    print("  downloading " + url)
    request = urllib.request.Request(
        url, headers={"User-Agent": "WIMI-build/1.0"}
    )
    with urllib.request.urlopen(request, timeout=300) as resp:
        with open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)


def expected_entries(key: str) -> tuple:
    """Every name that must exist in vendor/whisper/<key>/ after a fetch."""
    pin = PLATFORMS[key]
    return tuple(pin["files"]) + tuple(pin["links"]) + (LICENSE_NAME,)


def missing_entries(key: str, out_dir: Path) -> list:
    """Names that are absent, empty, or a symlink pointing at nothing.

    An empty file counts as missing on purpose: a half-written DLL is not a
    DLL, and the failure it produces at runtime is far less legible than a
    build-time complaint here.
    """
    missing = []
    for name in expected_entries(key):
        path = out_dir / name
        if path.is_symlink():
            if not path.exists():
                missing.append(name + " (broken symlink)")
            continue
        if not path.is_file():
            missing.append(name)
        elif path.stat().st_size == 0:
            missing.append(name + " (empty)")
    return missing


def archive_basenames(archive: Path, kind: str) -> list:
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            return [
                Path(info.filename).name
                for info in zf.infolist()
                if not info.is_dir()
            ]
    with tarfile.open(archive, "r:gz") as tf:
        return [Path(m.name).name for m in tf.getmembers() if not m.isdir()]


def cpu_variant_drift(key: str, present: list) -> str:
    """Refuse an archive whose CPU-variant set is not the pinned one.

    This is the check that catches an upstream bump adding or renaming a
    variant. Silence here is the dangerous outcome -- see CPU_DISPATCH_NOTE.
    """
    pin = PLATFORMS[key]
    pattern = pin["cpu_pattern"]
    in_archive = {n for n in present if fnmatch.fnmatch(n, pattern)}
    pinned = {n for n in pin["files"] if fnmatch.fnmatch(n, pattern)}
    if in_archive == pinned:
        return ""
    added = sorted(in_archive - pinned)
    gone = sorted(pinned - in_archive)
    lines = [
        "CPU variant set does not match the pin for release " + RELEASE_TAG + ".",
        "  " + CPU_DISPATCH_NOTE,
        "  pinned  (%d): %s" % (len(pinned), ", ".join(sorted(pinned))),
        "  archive (%d): %s" % (len(in_archive), ", ".join(sorted(in_archive))),
    ]
    if added:
        lines.append("  in the archive but not pinned: " + ", ".join(added))
    if gone:
        lines.append("  pinned but not in the archive: " + ", ".join(gone))
    lines.append("  Update the file list in this script, then re-run.")
    return "\n".join(lines)


def extract(key: str, archive: Path, out_dir: Path) -> int:
    """Extract the pinned members flat into out_dir. Returns the count.

    Selection is by basename against the pinned list, so a crafted archive
    cannot write outside out_dir: a member whose name is not in the pin is
    never opened, and the one that is gets written to out_dir / <basename>.
    """
    pin = PLATFORMS[key]
    wanted = set(pin["files"])
    count = 0

    if pin["kind"] == "zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                base = Path(info.filename).name
                if info.is_dir() or base not in wanted:
                    continue
                with zf.open(info) as src:
                    with open(out_dir / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                count += 1
    else:
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                base = Path(member.name).name
                if not member.isfile() or base not in wanted:
                    continue
                src = tf.extractfile(member)
                if src is None:
                    continue
                with src, open(out_dir / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                count += 1

    for link_name, target in pin["links"].items():
        link_path = out_dir / link_name
        try:
            os.symlink(target, link_path)
        except (OSError, NotImplementedError):
            # Cross-fetching to a filesystem or an OS that will not make one
            # (Windows without developer mode). A copy resolves the same
            # SONAME lookup at the cost of a duplicate.
            shutil.copyfile(out_dir / target, link_path)
            print("  note: copied " + link_name + " (symlinks unavailable here)")
        count += 1

    if key != "windows":
        for name in pin["files"]:
            path = out_dir / name
            if path.is_file():
                path.chmod(0o755)

    return count


def write_manifest(key: str, out_dir: Path, asset_digest: str) -> None:
    """Record what was installed, digest by digest, computed here.

    The archive's sha256 proves what was downloaded; this proves what came
    out of it and is still on disk. --check reads it back, so a truncated
    file is caught before a build carries it.
    """
    pin = PLATFORMS[key]
    files = {}
    for name in expected_entries(key):
        path = out_dir / name
        if path.is_file():
            files[name] = sha256_file(path)
    manifest = {
        "release_tag": RELEASE_TAG,
        "platform": key,
        "asset": pin["asset"],
        "asset_sha256": asset_digest,
        "license_sha256": LICENSE_SHA256,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files,
    }
    with open(out_dir / MANIFEST_NAME, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")


def manifest_mismatches(key: str, out_dir: Path) -> list:
    """Installed files whose digest no longer matches the manifest."""
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return []
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return [MANIFEST_NAME + " (unreadable)"]
    if manifest.get("release_tag") != RELEASE_TAG:
        return [
            "installed from release %s, this script pins %s"
            % (manifest.get("release_tag"), RELEASE_TAG)
        ]
    bad = []
    for name, digest in sorted(manifest.get("files", {}).items()):
        path = out_dir / name
        if path.is_file() and sha256_file(path) != digest:
            bad.append(name)
    return bad


def report_incomplete(key: str, out_dir: Path, missing: list, bad: list) -> None:
    print("[" + key + "] installation at " + str(out_dir) + " is INCOMPLETE:")
    for name in missing:
        print("    missing: " + name)
    for name in bad:
        print("    changed: " + name)
    if any(fnmatch.fnmatch(n.split(" ")[0], PLATFORMS[key]["cpu_pattern"])
           for n in missing + bad):
        print("  " + CPU_DISPATCH_NOTE)


def source_build_refusal(key: str) -> int:
    """Answer --platform macos-arm64 with the reason, not with silence."""
    dest = VENDOR_DIR / key
    print(
        "[" + key + "] there is no asset to fetch, and there never has been.",
        file=sys.stderr,
    )
    print(
        "  whisper.cpp's release workflow builds on ubuntu-* and windows-*.\n"
        "  Its one macos-latest job produces an iOS xcframework\n"
        "  (-DCMAKE_SYSTEM_NAME=iOS), which is not a runnable macOS CLI.\n"
        "  (llama.cpp does publish macos-arm64 assets; whisper.cpp does not.\n"
        "  That is the one place the two stop being the same shape.)\n"
        "\n"
        "  Build it from source on the Apple Silicon machine, which needs\n"
        "  Xcode Command Line Tools and CMake -- a real new prerequisite for\n"
        "  build_macos.sh (plan section 3.2). GGML_METAL_EMBED_LIBRARY=ON\n"
        "  embeds the Metal shaders so there is no .metallib to carry:\n"
        "\n"
        + MACOS_BUILD_RECIPE.format(tag=RELEASE_TAG, dest=dest)
        + "\n"
        "  The exact dylib set is not pinned here because nobody has run that\n"
        "  build yet; inventing a file list would make --check assert a guess.\n"
        "  T19 measures it on the hardware and pins it, and only then can this\n"
        "  platform be checked the way windows and linux are.",
        file=sys.stderr,
    )
    return 2


def fetch_platform(key: str, force: bool, check_only: bool) -> bool:
    pin = PLATFORMS[key]
    out_dir = VENDOR_DIR / key

    # A directory that is not there yet is not a broken installation; only
    # report incompleteness when there was something to be incomplete.
    fresh = not out_dir.exists()
    missing = [] if fresh else missing_entries(key, out_dir)
    bad = manifest_mismatches(key, out_dir) if (not fresh and not missing) else []

    if check_only:
        if fresh:
            print(
                "[" + key + "] nothing installed at " + str(out_dir),
                file=sys.stderr,
            )
            return False
        if missing or bad:
            report_incomplete(key, out_dir, missing, bad)
            return False
        print(
            "[" + key + "] complete: %d entries at %s (release %s)"
            % (len(expected_entries(key)), out_dir, RELEASE_TAG)
        )
        if not (out_dir / MANIFEST_NAME).is_file():
            print(
                "  note: no " + MANIFEST_NAME + " -- names were checked,"
                " digests could not be."
            )
        return True

    if not fresh and not missing and not bad and not force:
        print(
            "[" + key + "] already present at " + str(out_dir)
            + " (use --force to refetch)"
        )
        return True

    if missing or bad:
        report_incomplete(key, out_dir, missing, bad)
        print("[" + key + "] refetching.")

    if not pin["ship"]:
        print("[" + key + "] NOTE: development target only, never distributed.")

    print("[" + key + "] fetching " + pin["asset"] + " (release " + RELEASE_TAG + ")")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / pin["asset"]
        try:
            download(RELEASE_URL.format(tag=RELEASE_TAG, asset=pin["asset"]), archive)
        except (urllib.error.URLError, OSError) as exc:
            print("[" + key + "] download failed: " + str(exc), file=sys.stderr)
            return False

        actual = sha256_file(archive)
        if actual != pin["sha256"]:
            print(
                "[" + key + "] SHA256 MISMATCH!\n"
                "  expected " + pin["sha256"] + "\n"
                "  actual   " + actual + "\n"
                "  Refusing to install. Nothing on disk was touched.",
                file=sys.stderr,
            )
            return False

        drift = cpu_variant_drift(key, archive_basenames(archive, pin["kind"]))
        if drift:
            print("[" + key + "] " + drift, file=sys.stderr)
            print(
                "  Refusing to install. Nothing on disk was touched.",
                file=sys.stderr,
            )
            return False

        licence = Path(tmp) / LICENSE_NAME
        try:
            download(LICENSE_URL.format(tag=RELEASE_TAG), licence)
        except (urllib.error.URLError, OSError) as exc:
            print("[" + key + "] LICENSE download failed: " + str(exc), file=sys.stderr)
            return False
        licence_digest = sha256_file(licence)
        if licence_digest != LICENSE_SHA256:
            print(
                "[" + key + "] LICENSE SHA256 MISMATCH!\n"
                "  expected " + LICENSE_SHA256 + "\n"
                "  actual   " + licence_digest + "\n"
                "  Refusing to install. Nothing on disk was touched.",
                file=sys.stderr,
            )
            return False

        # Every check has passed; only now is the existing tree disturbed.
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        count = extract(key, archive, out_dir)
        shutil.copyfile(licence, out_dir / LICENSE_NAME)
        count += 1

    still_missing = missing_entries(key, out_dir)
    if still_missing:
        print(
            "[" + key + "] the archive did not contain everything pinned:",
            file=sys.stderr,
        )
        for name in still_missing:
            print("    missing: " + name, file=sys.stderr)
        return False

    write_manifest(key, out_dir, actual)
    print("[" + key + "] installed " + str(count) + " files into " + str(out_dir))
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the pinned whisper.cpp CLI binary into "
            "vendor/whisper/<platform>/. Model weights are NOT fetched here "
            "(owner decision D2: they download at first run)."
        ),
    )
    parser.add_argument(
        "--platform",
        action="append",
        choices=[*PLATFORMS, *SOURCE_BUILD_PLATFORMS, "all"],
        help=(
            "Platform(s) to fetch (repeatable). Default: host platform. "
            "'all' means every platform with a published asset."
        ),
    )
    parser.add_argument(
        "--force", action="store_true", help="Refetch even if present."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify what is on disk and exit. Never touches the network.",
    )
    args = parser.parse_args(argv)

    keys = args.platform or [host_platform()]
    if "all" in keys:
        keys = [k for k in keys if k != "all"] + list(PLATFORMS)
        print(
            "note: 'all' covers " + ", ".join(PLATFORMS)
            + ". macos-arm64 has no asset to fetch -- ask for it by name to"
            " see the source-build recipe."
        )

    status = 0
    for key in dict.fromkeys(keys):
        if key in SOURCE_BUILD_PLATFORMS:
            # 2, distinct from 1: "there is nothing here to fetch, build it"
            # is a different answer from "the fetch failed".
            status = max(status, source_build_refusal(key))
            continue
        if key not in PLATFORMS:
            print("unknown platform: " + key, file=sys.stderr)
            status = max(status, 2)
            continue
        if not fetch_platform(key, args.force, args.check):
            status = max(status, 1)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
