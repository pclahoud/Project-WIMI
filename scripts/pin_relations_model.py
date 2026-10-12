#!/usr/bin/env python3
"""Refresh the GLiNER2 model pins in src/app/relation_extraction/model_spec.py.

Issue #60. The weights are outside the installer, downloaded on first use and
sha256-verified, which means the pin table is the only thing standing between a
student and whatever the host happens to be serving. A pin that is WRONG is
worse than no pin, because every consumer downstream trusts it -- so no digest
in that file is ever typed by hand. #59's task T1 transcribed its own sha256
values truncated to 63 characters; this script exists so that class of mistake
cannot reach the table.

    python scripts/pin_relations_model.py              # query, cross-check, rewrite
    python scripts/pin_relations_model.py --check      # query and print only
    python scripts/pin_relations_model.py --download-check model.safetensors
    HF_TOKEN=hf_... python scripts/pin_relations_model.py

Stdlib only, ASCII output. Sibling of scripts/pin_whisper_model.py, which does
the same job for the whisper weights; the differences below are all forced by
GLiNER2 being a transformers DIRECTORY rather than one .bin file.

TWO ROUTES FOR AN LFS FILE, ONE FOR A SMALL ONE -- and saying which
-------------------------------------------------------------------
pin_whisper_model.py can claim two independent sources for every pin, because
every whisper model is a git-LFS object. That is not true here, and pretending
otherwise would be the more dangerous error.

  LFS files (model.safetensors, spm.model, and the images we skip):
      1. the model API with ?blobs=true, whose `lfs.oid` is the content's
         sha256;
      2. the plain "raw" URL, which returns the LFS POINTER TEXT -- three lines
         carrying "oid sha256:<hex>" and "size <bytes>" -- rather than the
         gigabytes themselves.
      Both are consulted and must agree, or this script refuses to write. That
      is how an 834 MB file gets pinned without downloading it.

  NON-LFS files (the configs and tokenizer.json, 8.7 MB the lot):
      there is no pointer, because the raw URL returns the file. So there is
      exactly ONE route -- hashing the bytes -- which is the strongest evidence
      available and is cheap at this size. It is reported as one route rather
      than dressed up as two.

THE OID-IS-A-SHA256 CLAIM IS RE-CHECKED EVERY RUN, FOR FREE
-----------------------------------------------------------
Routes 1 and 2 agreeing proves only that Hugging Face is self-consistent;
neither reads the bytes. The claim underneath -- that an LFS oid IS the sha256
of the content -- is verified on every invocation without a flag, because
`spm.model` is both an LFS object and small (2.4 MB): any LFS file at or under
LFS_HASH_CEILING_BYTES is downloaded and hashed, and a disagreement between
that hash and the oid is a hard failure. Measured 2026-10-05: they match.

Nothing proves it for `model.safetensors` short of fetching 834 MB, which is
what --download-check is for. Run it once when the revision moves.

A FILE IN NEITHER LIST IS A HARD FAILURE
----------------------------------------
The repository holds 14 files; the model needs 8. The pin table names those 8
and model_spec.IGNORED_FILES names the other 6, and together they must
partition the listing. A file in neither makes this script refuse, naming it,
because the alternative is a new required artefact going silently unpinned the
day the publisher adds one -- and the symptom would be a model that fails to
load with a message about neither the file nor the pin.

This script deliberately shares NO code with the downloader. A cross-check that
runs through the thing it is checking proves nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SPEC_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "app" / "relation_extraction" / "model_spec.py"
)

BEGIN_MARK = "# --- BEGIN PINS (rewritten by scripts/pin_relations_model.py) ---"
END_MARK = "# --- END PINS ---"

REPO_RE = re.compile(r"^MODEL_REPO = '([^']+)'", re.MULTILINE)
REVISION_RE = re.compile(r"^MODEL_REVISION = '([0-9a-f]{40})'", re.MULTILINE)
IGNORED_BLOCK_RE = re.compile(
    r"^IGNORED_FILES: Tuple\[str, \.\.\.\] = \((?P<body>.*?)^\)", re.MULTILINE | re.DOTALL
)
IGNORED_ITEM_RE = re.compile(r"'([^']+)'")
ROW_RE = re.compile(
    r"^\s*\('(?P<name>[^']+)', '(?P<sha256>[0-9a-f]{64})', (?P<bytes>\d+)\),\s*$"
)
POINTER_OID_RE = re.compile(r"^oid sha256:([0-9a-f]{64})$", re.MULTILINE)
POINTER_SIZE_RE = re.compile(r"^size (\d+)$", re.MULTILINE)

USER_AGENT = "WIMI-pin/1.0"
TIMEOUT_S = 120

#: An LFS object at or under this size is downloaded and hashed on every run,
#: so the "oid is a sha256" assumption is a measurement rather than a belief.
#: 4 MiB covers spm.model (2.4 MB) and costs a couple of seconds.
LFS_HASH_CEILING_BYTES = 4 << 20

ZERO_DIGEST = "0" * 64


# --------------------------------------------------------------------------
# reading what is pinned now
# --------------------------------------------------------------------------


class Row:
    def __init__(self, name: str, sha256: str, size_bytes: int):
        self.name = name
        self.sha256 = sha256
        self.size_bytes = size_bytes
        #: How the digest was established, printed in the report so a reader
        #: can tell a two-route LFS pin from a hashed one.
        self.sources: Tuple[str, ...] = ()

    @property
    def unpinned(self) -> bool:
        return self.sha256 == ZERO_DIGEST or self.size_bytes == 0

    def render(self) -> str:
        return f"        ('{self.name}', '{self.sha256}', {self.size_bytes}),"


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


def read_spec(source: str) -> Tuple[str, str, List[Row], Tuple[str, ...]]:
    """Repo, revision, the rows between the markers, and IGNORED_FILES."""
    repo = REPO_RE.search(source)
    revision = REVISION_RE.search(source)
    if not repo:
        raise SystemExit(f"Could not find MODEL_REPO in {SPEC_PATH}")
    if not revision:
        raise SystemExit(f"Could not find MODEL_REVISION in {SPEC_PATH}")

    ignored_block = IGNORED_BLOCK_RE.search(source)
    if not ignored_block:
        raise SystemExit(
            f"Could not find IGNORED_FILES in {SPEC_PATH}. It is half of the "
            "partition this script checks; without it a new repository file "
            "could not be classified."
        )
    ignored = tuple(IGNORED_ITEM_RE.findall(ignored_block.group("body")))

    rows = []
    for line in extract_block(source).splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        match = ROW_RE.match(line)
        if not match:
            raise SystemExit(
                "Unrecognised line in the pin block. Every row must read\n"
                "    ('<name>', '<64 hex digits>', <bytes>),\n"
                f"and this one does not:\n{line}"
            )
        rows.append(
            Row(match.group("name"), match.group("sha256"), int(match.group("bytes")))
        )
    if not rows:
        raise SystemExit("The pin block is empty; there is nothing to refresh.")
    return repo.group(1), revision.group(1), rows, ignored


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


def api_blobs(repo: str, revision: Optional[str], token: Optional[str]) -> dict:
    """The listing, with `lfs` per file and the commit sha.

    Queried at a revision when one is given, so a rerun describes the pinned
    commit rather than whatever `main` has become since.
    """
    if revision:
        url = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
    else:
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


def raw_url(repo: str, revision: str, name: str) -> str:
    return (
        f"https://huggingface.co/{repo}/raw/{revision}/"
        f"{urllib.parse.quote(name)}"
    )


def resolve_url(repo: str, revision: str, name: str) -> str:
    return (
        f"https://huggingface.co/{repo}/resolve/{revision}/"
        f"{urllib.parse.quote(name)}"
    )


def raw_body(repo: str, revision: str, name: str, token: Optional[str]) -> bytes:
    try:
        return http_get(raw_url(repo, revision, name), token)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Could not read the raw URL for {name} ({exc}).")


def parse_pointer(body: bytes) -> Optional[Tuple[str, int]]:
    """``(sha256, size)`` from LFS pointer text, or None if this is not one."""
    text = body.decode("utf-8", "replace")
    oid = POINTER_OID_RE.search(text)
    size = POINTER_SIZE_RE.search(text)
    if not oid or not size:
        return None
    return oid.group(1), int(size.group(1))


def download_and_hash(
    repo: str, revision: str, name: str, token: Optional[str], *, quiet: bool = False
) -> Tuple[str, int]:
    """Fetch a file for real and hash the bytes. The only end-to-end proof."""
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(resolve_url(repo, revision, name), headers=headers)

    digest = hashlib.sha256()
    read = 0
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            digest.update(block)
            read += len(block)
            if not quiet:
                sys.stdout.write(f"\r  downloaded {read:,} bytes")
                sys.stdout.flush()
    if not quiet:
        sys.stdout.write("\n")
    return digest.hexdigest(), read


# --------------------------------------------------------------------------
# resolving one file's pin
# --------------------------------------------------------------------------


def resolve_row(
    row: Row, repo: str, revision: str, sibling: dict, token: Optional[str]
) -> List[str]:
    """Fill ``row`` from the network. Returns a list of problems (empty is good)."""
    problems: List[str] = []
    lfs = sibling.get("lfs") or {}
    api_oid = lfs.get("oid") or lfs.get("sha256")
    api_size = sibling.get("size")

    body = raw_body(repo, revision, row.name, token)
    pointer = parse_pointer(body)

    if api_oid:
        # An LFS object. Two routes, and they must agree.
        if pointer is None:
            problems.append(
                f"{row.name}: the API says this is an LFS object but the raw URL "
                f"did not return pointer text. One of the two routes is wrong, "
                f"and this script will not guess which."
            )
            return problems
        pointer_oid, pointer_size = pointer
        if pointer_oid != api_oid:
            problems.append(
                f"{row.name}: the API oid and the LFS pointer DISAGREE "
                f"({api_oid} vs {pointer_oid}). Nobody knows which one is the "
                f"file; refusing to write."
            )
            return problems
        if api_size is not None and pointer_size != api_size:
            problems.append(
                f"{row.name}: API size {api_size} != pointer size {pointer_size}."
            )
            return problems

        row.sha256 = api_oid
        row.size_bytes = pointer_size
        row.sources = ("api blobs", "lfs pointer")

        if pointer_size <= LFS_HASH_CEILING_BYTES:
            # Free standing control: does the oid actually hash the content?
            hashed, read = download_and_hash(
                repo, revision, row.name, token, quiet=True
            )
            if read != pointer_size:
                problems.append(
                    f"{row.name}: fetched {read} bytes, pointer says {pointer_size}."
                )
            elif hashed != api_oid:
                problems.append(
                    f"{row.name}: THE LFS OID IS NOT THE CONTENT'S SHA256 "
                    f"(oid {api_oid}, hashed {hashed}). Every large pin in this "
                    f"table rests on that assumption, so this is a refusal, not "
                    f"a warning."
                )
            else:
                row.sources = row.sources + ("hashed the bytes",)
        return problems

    # Not an LFS object: the raw URL gave us the file itself. One route, and it
    # is the bytes, which is the strongest one available.
    if pointer is not None:
        problems.append(
            f"{row.name}: the API does not report this as LFS, but the raw URL "
            f"returned something shaped like pointer text. Refusing to pin "
            f"either interpretation."
        )
        return problems

    row.sha256 = hashlib.sha256(body).hexdigest()
    row.size_bytes = len(body)
    row.sources = ("hashed the bytes",)
    if api_size is not None and api_size != row.size_bytes:
        problems.append(
            f"{row.name}: API size {api_size} != {row.size_bytes} bytes fetched."
        )
    return problems


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true",
        help="query and report; do not write the file",
    )
    parser.add_argument(
        "--revision", default=None,
        help="pin this commit instead of the repository's current head",
    )
    parser.add_argument(
        "--download-check", metavar="NAME", default=None,
        help="also fetch NAME in full and hash it, the end-to-end proof "
             "(model.safetensors is 834 MB)",
    )
    parser.add_argument("--token", default=os.environ.get("HF_TOKEN"))
    args = parser.parse_args()

    source = SPEC_PATH.read_text(encoding="utf-8")
    repo, pinned_revision, rows, ignored = read_spec(source)

    print(f"spec       {SPEC_PATH}")
    print(f"repo       {repo}")
    print(f"pinned at  {pinned_revision}")

    wanted_revision = args.revision
    listing = api_blobs(repo, wanted_revision, args.token)
    head = listing.get("sha")
    if not head or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise SystemExit(f"The API did not return a usable commit sha (got {head!r}).")
    revision = wanted_revision or head
    print(f"reading    {revision}"
          + ("" if revision == pinned_revision else "   <- CHANGES the pin"))

    licence = (listing.get("cardData") or {}).get("license")
    if licence:
        print(f"licence    {licence}   (see #336 before treating this as discharged)")
    if listing.get("gated"):
        raise SystemExit(
            "This repository is GATED. A student's first use would need "
            "credentials, which contradicts #59's D2 download-on-first-use "
            "design. Stopping rather than pinning something unreachable."
        )

    siblings: Dict[str, dict] = {
        s["rfilename"]: s for s in listing.get("siblings", []) if "rfilename" in s
    }

    # ---- the partition check, before any pinning ------------------------
    pinned_names = {row.name for row in rows}
    problems: List[str] = []

    unclassified = sorted(set(siblings) - pinned_names - set(ignored))
    if unclassified:
        problems.append(
            "These repository files are in neither the pin table nor "
            "IGNORED_FILES, so nobody has decided whether the model needs "
            "them:\n    " + "\n    ".join(unclassified)
            + "\n  Add each to one list or the other in model_spec.py. A new "
              "REQUIRED file left unpinned would not be downloaded, and the "
              "model would fail to load with a message about neither the file "
              "nor the pin."
        )

    vanished = sorted(pinned_names - set(siblings))
    if vanished:
        problems.append(
            "These pinned files are not in the repository at this revision:\n    "
            + "\n    ".join(vanished)
        )

    stale_ignores = sorted(set(ignored) - set(siblings))
    if stale_ignores:
        problems.append(
            "IGNORED_FILES names files that no longer exist, so the list is "
            "drifting:\n    " + "\n    ".join(stale_ignores)
        )

    if problems:
        for problem in problems:
            print(f"\n  - {problem}")
        print("\nREFUSED: nothing was written.")
        return 1

    # ---- resolve every pin ----------------------------------------------
    print()
    for row in rows:
        before = (row.sha256, row.size_bytes)
        problems += resolve_row(row, repo, revision, siblings[row.name], args.token)
        if row.unpinned:
            continue
        changed = "" if before == (row.sha256, row.size_bytes) else "  CHANGED"
        if before[0] == ZERO_DIGEST:
            changed = "  NEW"
        print(f"  {row.size_bytes:>12,}  {row.sha256}  {row.name}{changed}")
        print(f"                via {', '.join(row.sources)}")

    if args.download_check:
        name = args.download_check
        if name not in pinned_names:
            raise SystemExit(f"{name!r} is not a pinned file.")
        row = next(r for r in rows if r.name == name)
        print(f"\nend-to-end check: fetching {name} ({row.size_bytes:,} bytes)")
        hashed, read = download_and_hash(repo, revision, name, args.token)
        if (hashed, read) != (row.sha256, row.size_bytes):
            problems.append(
                f"{name}: downloaded {read} bytes with sha256 {hashed}, but the "
                f"resolved pin says {row.size_bytes} / {row.sha256}."
            )
        else:
            print("  matches the resolved pin")

    total = sum(row.size_bytes for row in rows)
    print(f"\n  {total:>12,}  TOTAL  ({total / 1_000_000:.1f} MB decimal, "
          f"{total / (1 << 20):.1f} MiB)")

    if problems:
        for problem in problems:
            print(f"\n  - {problem}")
        print("\nREFUSED: nothing was written.")
        return 1

    if any(row.unpinned for row in rows):
        print("\nREFUSED: some rows are still unpinned after resolving.")
        return 1

    if args.check:
        print("\n--check: nothing written.")
        return 0

    # Ascending by size, so the table's download and verification order puts
    # the cheap metadata before 834 MB of weights. Sorted here rather than
    # maintained by hand, because a row added by hand in the wrong place would
    # be a silent regression of that property -- the cost being that a failure
    # which should surface in milliseconds surfaces after the weights.
    # Tie-break on name so the output is stable.
    rows.sort(key=lambda row: (row.size_bytes, row.name))
    updated = replace_block(source, rows)
    updated = replace_revision(updated, revision)
    if updated == source:
        print("\nAlready up to date; nothing written.")
        return 0
    SPEC_PATH.write_text(updated, encoding="utf-8")
    print(f"\nWrote {SPEC_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
