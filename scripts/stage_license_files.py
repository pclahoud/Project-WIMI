#!/usr/bin/env python3
"""Put the licence texts and the source-location notice into a built bundle.

GPL-3.0 section 4 requires a copy of the licence to be conveyed *with* the
program, and section 6 requires the corresponding source for an object-code
distribution to accompany it or be obtainable from a stated place. Settings ->
About is WIMI's Appropriate Legal Notices under section 5(d) and names every
component's licence (#195, owner's decision (a)) -- but naming a licence is not
conveying it, and until #272 the bundle carried **no** copyleft licence text at
all. The only `LICENSE` in `dist/` was whisper.cpp's MIT, and it is there only
because `scripts/fetch_whisper.py` happens to drop it in
`vendor/whisper/<platform>/`.

Worse, the About panel *said* the GPL text was "in the LICENSE file distributed
with WIMI". It was not. `wimi.spec` contains no reference to the root `LICENSE`
-- measured, not inferred -- so the one document that exists to carry WIMI's
legal notices contained a false statement about where to find its own licence.

This script is the fix, and it runs from BOTH build scripts.

Why one Python script instead of a few lines in each build script
-----------------------------------------------------------------
`build_windows.bat` is batch and `build_macos.sh` is bash. CLAUDE.md already
records that `wimi.spec` and `wimi_macos.spec` "are clones with no shared helper
and a change made in one of them is a bug that only shows on the other
platform". The build scripts have exactly that shape and a worse version of it,
because the two languages make a copied change harder to eyeball. So the logic
lives here once and each script calls it with one line.

Why the dist root and not the spec's ``datas``
----------------------------------------------
PyInstaller 6 puts everything from ``datas`` under ``_internal/``. A recipient
looking for the licence of the program they were handed should not have to open
a directory named ``_internal``, and the About panel should not have to print
that path to be truthful. Both build scripts construct the dist directory
anyway (macOS ``mv``s the ``.app`` into a fresh one; Windows ``mkdir``s
``app_data`` and ``logs`` inside PyInstaller's), so copying in afterwards is the
natural seam and keeps exactly one copy of each file in the bundle.

The relations artifact also conveys its runtime's licences (#336)
------------------------------------------------------------------
When ``WIMI_BUILD_RELATIONS=1`` (both build scripts set it for a ``relations``
build) or ``--relations`` is passed, :mod:`relations_third_party` also stages
every licence file of the relation-extraction runtime and its dependencies
into ``licenses/third-party/``, with an ``INDEX.txt``. It reads the build
environment's installed metadata, so it must run under the interpreter that
built the bundle, which is how both build scripts already call it. A default
build stages nothing extra: the runtime is not in it.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The public mirror. CLAUDE.md, "Remotes & Publishing to GitHub": `master` is
# NEVER pushed here -- only snapshot commits from the `public` branch, onto
# branch `main`. That has a consequence this file has to be honest about; see
# _source_notice().
PUBLIC_REPO = "https://github.com/pclahoud/Project-WIMI"

# (source relative to repo root, destination relative to the bundle root)
LICENSE_FILES = [
    (Path("LICENSE"), Path("LICENSE")),
    (Path("licenses") / "LGPL-3.0.txt", Path("licenses") / "LGPL-3.0.txt"),
]

SOURCE_NOTICE_NAME = "CORRESPONDING-SOURCE.txt"


def _app_version() -> str:
    """Read APP_VERSION without importing the app (no Qt at build time)."""
    init = REPO_ROOT / "src" / "app" / "__init__.py"
    for line in init.read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip("'\"")
    return "unknown"


def _git(*args: str) -> str | None:
    """Best-effort git query. A build from a tarball has no repository."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
            timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def _relations_requested(flag: bool) -> bool:
    return flag or os.environ.get("WIMI_BUILD_RELATIONS") == "1"


def _source_notice(relations: bool = False) -> str:
    """The section 6 notice.

    This states a *place* (section 6(d)), which is what a published mirror
    supports, rather than a written offer (section 6(b)) -- a written offer has
    to name someone who will honour it, and choosing that contact is the
    owner's decision, not this script's. #272 asked for "a written offer"; what
    is implementable without inventing an address is 6(d), and the difference
    is stated here rather than glossed.

    The honest awkwardness: the build commit is a `master` commit, and `master`
    is never pushed to the public mirror -- it receives squashed snapshots on
    `public`. So the hash below is NOT findable on GitHub and is recorded for
    the maintainer's traceability only. A release **tag** is pushed there
    (`scripts/publish_release.py --tag`), so when the build sits on one, that
    tag is the identifier a recipient can actually use.
    """
    version = _app_version()
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit = _git("rev-parse", "HEAD")
    tag = _git("describe", "--tags", "--exact-match")
    dirty = _git("status", "--porcelain")

    lines = [
        "CORRESPONDING SOURCE FOR THIS BUILD",
        "===================================",
        "",
        "WIMI is free software licensed under the GNU General Public License,",
        "version 3. You have the right to the complete corresponding source code",
        "for this build.",
        "",
        "It is published at:",
        "",
        f"    {PUBLIC_REPO}",
        "",
        "and may be downloaded from there at no charge.",
        "",
        f"WIMI version : {version}",
        f"Built        : {built}",
    ]

    if tag:
        lines += [
            f"Release tag  : {tag}",
            "",
            "That tag identifies the corresponding source in the repository above.",
        ]
    else:
        lines += [
            "Release tag  : (none -- this is not a tagged release build)",
            "",
            "This build was not made from a tagged release, so the source above is",
            "the current published tree rather than an exact match for this binary.",
        ]

    if commit:
        lines += [
            "",
            f"Internal build commit: {commit}"
            + ("  (WORKING TREE NOT CLEAN)" if dirty else ""),
            "This identifies the build in the maintainer's own repository. The",
            "public repository receives squashed snapshots, so this hash will not",
            "resolve there; it is recorded for traceability, not for fetching.",
        ]

    # The interpreter that produced the artifact (#365). Recorded here because
    # this file is in the bundle and outlives the build, which the build log is
    # not: that issue's complaint was that check_build_env's above-the-ceiling
    # note was "the only record, and the most perishable possible place to keep
    # one". Nobody could answer "what was this built with" about an artifact in
    # hand.
    #
    # Build provenance, not a licence term -- it sits under the traceability
    # paragraph above for that reason, and the licence sections follow below.
    lines += [
        "",
        f"Built with Python {platform.python_version()} on "
        f"{platform.system()} ({platform.machine()}).",
    ]

    lines += [
        "",
        "LICENCE TEXTS CONVEYED WITH THIS BUILD",
        "--------------------------------------",
        "",
        "  LICENSE                  GNU GPL v3   -- WIMI itself",
        "  licenses/LGPL-3.0.txt    GNU LGPL v3  -- Qt 6 and QtWebEngine",
        "",
        "LGPL-3.0 is not a standalone licence: it incorporates the terms and",
        "conditions of GPL-3.0 and adds permissions to them, so both texts are",
        "needed to read either one.",
        "",
    ]
    if relations:
        lines += [
            "  licenses/third-party/    the relation-extraction runtime (PyTorch,",
            "                           Transformers, GLiNER2 and their dependencies):",
            "                           each component's own licence and notice",
            "                           files, listed in licenses/third-party/INDEX.txt",
            "",
        ]
    lines += [
        "Licences for the remaining bundled components are listed in the",
        "application under Settings -> About.",
        "",
    ]
    return "\n".join(lines)


def stage(bundle_dir: Path, relations: bool = False) -> list[Path]:
    """Copy the licence texts and write the source notice. Returns what it wrote.

    With ``relations``, also stage the relations runtime's third-party licence
    files (#336); see the module docstring.
    """
    if not bundle_dir.is_dir():
        raise SystemExit(f"ERROR: bundle directory does not exist: {bundle_dir}")

    written: list[Path] = []
    for src_rel, dest_rel in LICENSE_FILES:
        src = REPO_ROOT / src_rel
        if not src.is_file():
            # Never ship a build claiming a licence file it does not have.
            raise SystemExit(f"ERROR: licence text missing from the repository: {src}")
        dest = bundle_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(dest)

    if relations:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import relations_third_party

        staged = relations_third_party.stage_relations(bundle_dir)
        root = bundle_dir / relations_third_party.THIRD_PARTY_DIR
        # The other half of #408. Both .spec files drop torch's vendored
        # licence tree from the bundle on the understanding that THIS folder
        # carries it. A relations build where that tree is gone and this one
        # is empty would convey nothing for torch, which is worse than before.
        torch_dirs = [p for p in root.glob("torch-*") if p.is_dir()]
        torch_texts = [f for d in torch_dirs for f in d.iterdir()
                       if f.is_file() and f.name != relations_third_party.FILES_NAME]
        if not torch_texts:
            raise SystemExit(
                "ERROR: no torch licence texts were staged under "
                f"{root}. The .spec files drop torch's own licence tree from the "
                "bundle (#408) because this folder conveys it; refusing to "
                "produce an artifact that conveys neither.")
        written.append(root / relations_third_party.INDEX_NAME)
        print(f"  staged licences for {len(staged)} relations-runtime components "
              f"({sum(len(s.files) for s in staged)} files)")

    notice = bundle_dir / SOURCE_NOTICE_NAME
    notice.write_text(_source_notice(relations), encoding="utf-8")
    written.append(notice)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "bundle_dir", nargs="?",
        help="the built bundle's root, e.g. dist/WIMI",
    )
    parser.add_argument(
        "--print-version", action="store_true",
        help="print APP_VERSION and exit, for the build scripts' asset names "
             "(#425). This module is the one build-time reader of it; a "
             "second copy of the parser is what that issue is about",
    )
    parser.add_argument(
        "--relations", action="store_true",
        help="also stage the relations runtime's licences (implied by "
             "WIMI_BUILD_RELATIONS=1, which both build scripts set)",
    )
    args = parser.parse_args()

    if args.print_version:
        # Bare, on one line, with no decoration: both build scripts capture
        # this into a shell variable and put it in a filename.
        print(_app_version())
        return 0
    if not args.bundle_dir:
        parser.error("bundle_dir is required unless --print-version is given")

    written = stage(Path(args.bundle_dir), relations=_relations_requested(args.relations))
    for path in written:
        print(f"  staged {path.relative_to(Path(args.bundle_dir).parent.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
