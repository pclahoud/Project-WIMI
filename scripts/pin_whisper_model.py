#!/usr/bin/env python3
"""Refresh the whisper model pins in src/app/stt/model_spec.py.

Issue #59, task T21. Owner's decision D2 puts the model weights outside the
installer, downloaded on first run and sha256-verified, which means the pin
table is the only thing standing between a student and whatever the host
happens to be serving. A pin that is WRONG is worse than no pin at all,
because every consumer downstream trusts it -- so no digest in that file is
ever typed by hand. Task T1 transcribed its own sha256 values truncated to 63
characters; this script exists so that class of mistake cannot reach the
table.

Run it from a network that can reach huggingface.co (some networks 401
anonymous HF traffic; pass a token if needed):

    python scripts/pin_whisper_model.py              # query, cross-check, rewrite
    python scripts/pin_whisper_model.py --check      # query and print only
    python scripts/pin_whisper_model.py --download-check base-q5_1
    HF_TOKEN=hf_... python scripts/pin_whisper_model.py

Mirrors scripts/pin_capture_model.py on feature/ai-capture, which does the
same job for the AI-capture GGUF. Stdlib only, ASCII output.

TWO INDEPENDENT SOURCES, ON PURPOSE
-----------------------------------
The .bin files in the repo are git-LFS objects, and Hugging Face exposes each
one's digest twice:

  1. the model API with ?blobs=true, which also carries the repo's commit sha
     (that is what gets pinned as the revision);
  2. the plain "raw" URL for the file, which returns the LFS POINTER TEXT --
     three lines carrying "oid sha256:<hex>" and "size <bytes>" -- rather than
     the gigabytes themselves.

Measured 2026-09-23: both routes agree, and the raw route returns 129 bytes
for a 77 MB model. So the pins can be refreshed without downloading anything,
and the second route is used as a cross-check rather than as a shortcut. If
the two ever disagree the script refuses to write, because at that point
nobody knows which one is the model.

--download-check is the third leg: it actually fetches one model and hashes
the bytes, which is the only thing that proves the pointer text describes the
file the resolve URL serves. Use the smallest model; delete it afterwards
(this script does).

This script deliberately shares NO code with src/app/stt/download.py. A
cross-check that runs through the thing it is checking proves nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SPEC_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "app" / "stt" / "model_spec.py"
)

BEGIN_MARK = "# --- BEGIN PINS (rewritten by scripts/pin_whisper_model.py) ---"
END_MARK = "# --- END PINS ---"

REPO_RE = re.compile(r"^MODEL_REPO = '([^']+)'", re.MULTILINE)
REVISION_RE = re.compile(r"^MODEL_REVISION = '([0-9a-f]{40})'", re.MULTILINE)
ROW_RE = re.compile(
    r"^\s*\('(?P<size>[^']+)', '(?P<filename>[^']+)', "
    r"'(?P<sha256>[0-9a-f]+)', (?P<bytes>\d+)\),\s*$"
)
POINTER_OID_RE = re.compile(r"^oid sha256:([0-9a-f]{64})$", re.MULTILINE)
POINTER_SIZE_RE = re.compile(r"^size (\d+)$", re.MULTILINE)

USER_AGENT = "WIMI-pin/1.0"
TIMEOUT_S = 60


# --------------------------------------------------------------------------
# reading what is pinned now
# --------------------------------------------------------------------------


class Row:
    def __init__(self, size: str, filename: str, sha256: str, size_bytes: int):
        self.size = size
        self.filename = filename
        self.sha256 = sha256
        self.size_bytes = size_bytes

    def render(self) -> str:
        return (
            f"        ('{self.size}', '{self.filename}', "
            f"'{self.sha256}', {self.size_bytes}),"
        )


def read_spec(source: str) -> Tuple[str, str, List[Row]]:
    """Repo, revision and the rows between the markers."""
    repo = REPO_RE.search(source)
    revision = REVISION_RE.search(source)
    if not repo:
        raise SystemExit(f"Could not find MODEL_REPO in {SPEC_PATH}")
    if not revision:
        raise SystemExit(f"Could not find MODEL_REVISION in {SPEC_PATH}")

    block = extract_block(source)
    rows = []
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        match = ROW_RE.match(line)
        if not match:
            raise SystemExit(
                "Unrecognised line in the pin block. Every row must read\n"
                "    ('<size>', '<filename>', '<sha256>', <bytes>),\n"
                f"and this one does not:\n{line}"
            )
        rows.append(
            Row(
                match.group("size"),
                match.group("filename"),
                match.group("sha256"),
                int(match.group("bytes")),
            )
        )
    if not rows:
        raise SystemExit("The pin block is empty; there is nothing to refresh.")
    return repo.group(1), revision.group(1), rows


def extract_block(source: str) -> str:
    start = source.find(BEGIN_MARK)
    end = source.find(END_MARK)
    if start < 0 or end < 0 or end < start:
        raise SystemExit(
            f"Could not find the pin markers in {SPEC_PATH}.\n"
            f"Expected a line containing {BEGIN_MARK!r} and a later one "
            f"containing {END_MARK!r}."
        )
    return source[start + len(BEGIN_MARK):end]


def replace_block(source: str, rows: List[Row]) -> str:
    start = source.find(BEGIN_MARK)
    end = source.find(END_MARK)
    body = "\n" + "\n".join(row.render() for row in rows) + "\n        "
    return source[: start + len(BEGIN_MARK)] + body + source[end:]


def replace_revision(source: str, revision: str) -> str:
    return REVISION_RE.sub(f"MODEL_REVISION = '{revision}'", source, count=1)


# --------------------------------------------------------------------------
# the network
# --------------------------------------------------------------------------


def http_get(url: str, token: Optional[str]) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read()


def api_blobs(repo: str, token: Optional[str]) -> dict:
    url = f"https://huggingface.co/api/models/{repo}?blobs=true"
    try:
        return json.loads(http_get(url, token).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"Hugging Face API returned HTTP {exc.code} for {url}. "
            "If your network 401s anonymous HF traffic, pass --token or set "
            "HF_TOKEN."
        )
    except Exception as exc:  # noqa: BLE001 - one clear failure path
        raise SystemExit(f"Hugging Face API request failed ({exc}).")


def lfs_pointer(repo: str, revision: str, filename: str, token: Optional[str]):
    """The file's LFS pointer text: (sha256, size), or None if it is not one.

    A file small enough not to be in LFS comes back as its own content, which
    will not match the pointer shape. That is reported rather than guessed at.
    """
    url = f"https://huggingface.co/{repo}/raw/{revision}/{filename}"
    try:
        body = http_get(url, token).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Could not read the LFS pointer for {filename} ({exc}).")
    oid = POINTER_OID_RE.search(body)
    size = POINTER_SIZE_RE.search(body)
    if not oid or not size:
        return None
    return oid.group(1), int(size.group(1))


def download_and_hash(repo: str, revision: str, filename: str, token: Optional[str],
                      keep_in: Optional[str] = None) -> Tuple[str, int]:
    """Fetch a model for real and hash the bytes. The only end-to-end proof."""
    url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)

    directory = keep_in or tempfile.mkdtemp(prefix="wimi-pin-")
    target = Path(directory) / filename
    digest = hashlib.sha256()
    written = 0
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            with open(target, "wb") as handle:
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    handle.write(block)
                    digest.update(block)
                    written += len(block)
                    sys.stdout.write(f"\r  downloaded {written:,} bytes")
                    sys.stdout.flush()
        sys.stdout.write("\n")
    finally:
        if keep_in is None:
            try:
                target.unlink()
                os.rmdir(directory)
            except OSError:
                pass
    return digest.hexdigest(), written


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true",
        help="Query and print the values without rewriting model_spec.py.",
    )
    parser.add_argument(
        "--no-cross-check", action="store_true",
        help="Skip the LFS-pointer cross-check (one small request per model).",
    )
    parser.add_argument(
        "--download-check", metavar="SIZE",
        help="Also download that model for real and hash it, proving the pin "
             "end to end. Use the smallest one; the file is deleted after.",
    )
    parser.add_argument(
        "--keep-download", metavar="DIR",
        help="With --download-check, keep the downloaded file in DIR. Never "
             "point this inside the repository.",
    )
    parser.add_argument(
        "--token", default=os.environ.get("HF_TOKEN"),
        help="Hugging Face token (default: HF_TOKEN env var).",
    )
    args = parser.parse_args()

    source = SPEC_PATH.read_text(encoding="utf-8")
    repo, old_revision, rows = read_spec(source)
    print(f"Spec:     {SPEC_PATH}")
    print(f"Repo:     {repo}")
    print(f"Pinned:   {old_revision}")
    print(f"Models:   {len(rows)}")
    print()

    info = api_blobs(repo, args.token)
    revision = info.get("sha")
    if not revision:
        raise SystemExit("The Hugging Face response carried no repo commit sha.")
    licence = (info.get("cardData") or {}).get("license")
    print(f"Revision: {revision}" + ("  (unchanged)" if revision == old_revision else "  (NEW)"))
    print(f"Licence:  {licence}")
    if licence and licence.lower() != "mit":
        print("WARNING: model_spec.py records MIT. Check MODEL_LICENCE.")
    print()

    siblings: Dict[str, dict] = {
        str(entry.get("rfilename")): entry for entry in (info.get("siblings") or [])
    }

    updated: List[Row] = []
    changes = 0
    problems = 0
    for row in rows:
        entry = siblings.get(row.filename)
        if entry is None:
            print(f"MISSING  {row.filename}: not in the repo listing")
            problems += 1
            updated.append(row)
            continue
        lfs = entry.get("lfs") or {}
        sha256 = lfs.get("sha256")
        size_bytes = lfs.get("size") or entry.get("size")
        if not sha256 or not size_bytes:
            print(f"MISSING  {row.filename}: no LFS sha256 in the API response")
            problems += 1
            updated.append(row)
            continue

        if not args.no_cross_check:
            pointer = lfs_pointer(repo, revision, row.filename, args.token)
            if pointer is None:
                print(f"PROBLEM  {row.filename}: the raw URL is not an LFS pointer")
                problems += 1
                updated.append(row)
                continue
            pointer_sha, pointer_size = pointer
            if pointer_sha != sha256 or pointer_size != int(size_bytes):
                print(
                    f"CONFLICT {row.filename}: API says {sha256}/{size_bytes}, "
                    f"the LFS pointer says {pointer_sha}/{pointer_size}"
                )
                problems += 1
                updated.append(row)
                continue

        changed = sha256 != row.sha256 or int(size_bytes) != row.size_bytes
        changes += 1 if changed else 0
        mark = "CHANGED " if changed else "same    "
        print(f"{mark} {row.size:<12} {sha256}  {int(size_bytes):>12,} B")
        updated.append(Row(row.size, row.filename, sha256, int(size_bytes)))

    print()

    if args.download_check:
        target = next((r for r in updated if r.size == args.download_check), None)
        if target is None:
            raise SystemExit(
                f"--download-check {args.download_check}: not in the pin block. "
                f"Pinned sizes are {', '.join(r.size for r in updated)}."
            )
        print(f"Downloading {target.filename} to hash it for real...")
        actual_sha, actual_bytes = download_and_hash(
            repo, revision, target.filename, args.token, args.keep_download
        )
        ok = actual_sha == target.sha256 and actual_bytes == target.size_bytes
        print(f"  sha256 {actual_sha}")
        print(f"  bytes  {actual_bytes:,}")
        print("  MATCHES the pin" if ok else "  DOES NOT MATCH the pin")
        if not ok:
            problems += 1
        print()

    if problems:
        print(f"{problems} problem(s); not rewriting {SPEC_PATH.name}.")
        return 1

    if args.check:
        print("--check: not rewriting model_spec.py")
        return 0

    rewritten = replace_block(replace_revision(source, revision), updated)
    if rewritten == source:
        print("Nothing changed (already pinned to these values).")
        return 0

    SPEC_PATH.write_text(rewritten, encoding="utf-8")
    print(
        f"Pinned {changes} changed digest(s) and revision {revision[:12]} "
        f"in {SPEC_PATH.name}."
    )
    print("Re-run the test suite, then commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
