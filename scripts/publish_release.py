"""Publish a snapshot of master to the public GitHub mirror.

Takes the committed tree of ``master`` (never the working directory), strips
the paths in ``EXCLUDE_PREFIXES``, scans what is left against a local denylist
of sensitive patterns, commits it onto the ``public`` branch under the public
author identity, and pushes to the ``github`` remote. The private commit
history on ``master`` is never pushed.

The scan runs on the tree that will actually be published, after exclusion --
not on ``master`` -- so a match inside an excluded directory cannot block a
publish that would never have exposed it.

The denylist lives in ``.publish_denylist.txt`` at the repo root. It is
git-ignored on purpose: the patterns describe exactly the information that
must never appear in the published tree, so the file itself must never be
tracked. One extended-regex pattern per line, ``#`` comments allowed.
Publishing refuses to run without it.

Usage:
    python scripts/publish_release.py [-m "commit message"] [--dry-run]
    python scripts/publish_release.py --tag            # vAPP_VERSION
    python scripts/publish_release.py --tag v0.2.0     # must match APP_VERSION

--dry-run performs the PII scan and reports what would be published -- and
what it would tag -- without committing or pushing anything.

A RELEASE TAG MUST AGREE WITH ``APP_VERSION`` (#425). `--tag` with no value
derives the tag from it; an explicit value that disagrees is refused before
anything is built or pushed. Nothing connected the two until this, so
``--tag v0.2.0`` would have published binaries reporting ``0.1.1-beta`` with
no gate objecting -- and `v0.1.0-beta` already shipped under the MIT
declaration that #195 replaced, so two artifacts could claim one version
under different licences. There is no override: bump ``APP_VERSION``.
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

# The one build-time APP_VERSION reader (see `app_version` below). Imported as
# a module rather than a name so the indirection is visible at the call site.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_license_files  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DENYLIST = REPO_ROOT / ".publish_denylist.txt"

SOURCE_BRANCH = "master"
PUBLIC_BRANCH = "public"
REMOTE = "github"
REMOTE_BRANCH = "main"

#: Path prefixes stripped from the published tree. The mirror is a
#: read-only showcase, and ``docs/`` is where this project keeps its
#: internal planning, decision records and handoff notes -- material
#: written for whoever maintains WIMI, not for a visitor.
#:
#: Anything the README points at must NOT live under one of these, or the
#: published front page renders with broken images and dead links. That is
#: why the README's screenshots live in ``assets/`` and not in
#: ``docs/testing/images/`` where the rest of them are.
EXCLUDE_PREFIXES = (
    # Internal planning, decision records and handoff notes -- written for
    # whoever maintains WIMI, not for a visitor.
    # (This now also covers the phase 5/6 wireframes -- ~1.9 MB of design
    # files in a format nothing on a visitor's machine opens -- which used
    # to sit in a top-level "wireframe designs/" and needed its own entry.)
    "docs/",
    # This project's own agent tooling: slash commands and the private
    # tracker's issue templates. Internal workflow, not part of the app.
    ".claude/",
    ".forgejo/",
    # MCP server wiring for local development. Harmless -- it points at
    # 127.0.0.1 -- but it is plumbing for working ON WIMI, not using it.
    ".mcp.json",
    # A 3,108-row export of the owner's own subject tree, committed in
    # January for a one-off analysis and described in the handoff notes as
    # "user-provided data for analysis". Not personal, but it is somebody's
    # real data rather than a worked example, and docs/examples/ already
    # documents the import format properly.
    "examples/subject_nodes.csv",
    # The agent orientation file: an internal engineering record full of
    # private-tracker issue numbers, machine names and figures measured on
    # the owner's own study profile. Owner's decision 2026-10-04: it is not
    # published. The README must not link to it.
    "CLAUDE.md",
    # Tests for real_ladybug, a graph library that was evaluated and removed.
    # They cannot pass on any machine -- the spike files abort collection and
    # the graph files fail on `_graph_available` -- so publishing them only
    # tells a visitor who runs `pytest` that the suite is broken. Exact paths,
    # not a shared prefix: `git rm` takes pathspecs, so a partial filename
    # would match nothing there while `startswith` matched it here.
    "tests/spike/",
    "tests/database/test_graph_dual_write.py",
    "tests/database/test_graph_phase1.py",
    "tests/database/test_graph_read_switchover.py",
    "tests/database/test_graph_shadow_reads.py",
    # NOTHING HERE FOR #437 ANY MORE, DELIBERATELY. Eight entries used to sit
    # below this line: a verbatim copy of NBME/FSMB's published USMLE Content
    # Outline, the parser written for that one document, that parser's test,
    # and the five test files thought to invoke it. They are gone because the
    # document is gone -- `tests/fixtures/exam_outline.json` is synthetic, so
    # there is nothing left to withhold, and the published suite covers
    # polyhierarchy rollups, STT priming and the folder-sync round trip again.
    # One of those five (`tests/app/test_stt_priming.py`) never invoked the
    # fixture at all; it was classified by a grep that matched a docstring.
    # If a third party's document is ever added to a published directory
    # again, this is where it would have to be named -- but excluding tests is
    # the expensive way to fix it, and replacing the document is the cheap one.
)

PUBLIC_NAME = "pclahoud"
PUBLIC_EMAIL = "14871598+pclahoud@users.noreply.github.com"


def git(*args, check=True, env=None):
    """Run a git command in the repo root and return its stdout, stripped."""
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        sys.exit(
            f"git {' '.join(args)} failed "
            f"(exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return result


def preflight():
    git("rev-parse", "--verify", f"refs/heads/{SOURCE_BRANCH}")
    git("rev-parse", "--verify", f"refs/heads/{PUBLIC_BRANCH}")
    remote = git("remote", "get-url", REMOTE, check=False)
    if remote.returncode != 0:
        sys.exit(
            f"Remote '{REMOTE}' is not configured. Add it with:\n"
            f"  git remote add {REMOTE} <github-ssh-url>"
        )
    print(f"Publishing {SOURCE_BRANCH} -> {REMOTE}/{REMOTE_BRANCH} "
          f"({remote.stdout.strip()})")


#: `--tag` with no value means "derive it from APP_VERSION".
DERIVE_TAG = "<derive>"


def app_version():
    """APP_VERSION, through the one build-time reader, with a strict policy.

    THE PARSER IS NOT DUPLICATED HERE ON PURPOSE. There are already two ways
    to get this value and they differ by mechanism, legitimately:

      * `app.profile_archive._app_version()` imports the constant. In-process,
        Qt available.
      * `scripts.stage_license_files._app_version()` parses
        `src/app/__init__.py`, because a build has no Qt and no app on the
        path.

    A publish is the second case, so it reuses that reader rather than adding
    a third copy of the same six lines. A first draft of this function did add
    one, which is the duplication #588 is about -- two readers of one file
    that can disagree after somebody changes the format.

    What differs is the POLICY, not the parsing: the stager degrades to the
    string "unknown" because a notices document with a vague version still
    conveys the licence, while a release tagged `vunknown` -- or, worse, a tag
    silently *agreeing* because both sides read "unknown" -- is worse than
    not publishing. So that sentinel is the contract between them, and this
    refuses on it.
    """
    version = stage_license_files._app_version()
    if version == "unknown":
        sys.exit(
            "Could not read APP_VERSION from src/app/__init__.py.\n"
            "A release tag is derived from it, so publishing cannot continue\n"
            "without knowing what version this tree calls itself.\n"
            "(scripts/stage_license_files.py is the one reader; check that the\n"
            "assignment still begins the line.)"
        )
    return version


def resolve_tag(requested):
    """The tag to create, refusing anything APP_VERSION does not back (#425).

    `v0.1.0-beta` was published under the MIT declaration and WIMI is now
    GPL-3.0, so two artifacts could call themselves one version under
    different licences -- which is the inverse of what #272's conveyance work
    is for. Nothing connected a tag to the version until this: `--tag v0.2.0`
    would have published binaries reporting `0.1.1-beta` and no gate anywhere
    would have noticed.

    `--tag` with no value derives the tag, so there is nothing to get wrong.
    An explicit value is still accepted -- muscle memory, and it reads better
    in a release checklist -- but it has to agree.

    There is deliberately NO override flag. The escape hatch is to bump
    APP_VERSION, which is the thing you wanted if the tag is ahead; a flag
    would let the two diverge exactly when somebody is in a hurry, which is
    when this matters most. Same reasoning as the denylist having no
    allowlist.
    """
    if requested is None:
        return None
    expected = f"v{app_version()}"
    if requested == DERIVE_TAG:
        print(f"Tag derived from APP_VERSION: {expected}")
        return expected
    if requested != expected:
        sys.exit(
            f"Refusing to publish: the tag and APP_VERSION disagree.\n"
            f"  --tag        {requested}\n"
            f"  APP_VERSION  {app_version()}  (expects the tag {expected})\n"
            "\n"
            "A tagged release must report the version it is tagged as, or a\n"
            "recipient cannot tell two artifacts of the same name apart --\n"
            "which already happened once: v0.1.0-beta shipped under MIT and\n"
            "WIMI is now GPL-3.0 (#425, #195).\n"
            "\n"
            "Either bump APP_VERSION in src/app/__init__.py to match the tag\n"
            f"you want, or pass `--tag` with no value to use {expected}."
        )
    return requested


def load_denylist():
    if not DENYLIST.exists():
        sys.exit(
            f"Denylist not found: {DENYLIST}\n"
            "Refusing to publish without a PII scan. Create the file with one\n"
            "extended-regex pattern per line covering every identifier that\n"
            "must never be published (names, emails, private IPs, local\n"
            "paths). It is git-ignored and stays on this machine."
        )
    patterns = [
        line.strip()
        for line in DENYLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not patterns:
        sys.exit(f"Denylist {DENYLIST} contains no patterns; refusing to publish.")
    return patterns


def build_public_tree():
    """The tree that will actually be published: SOURCE_BRANCH minus EXCLUDE_PREFIXES.

    Built in a scratch index so the working tree and the real index are
    never touched -- publishing must be safe to run with work in progress.
    Returns (tree_sha, removed_paths).
    """
    source_tree = git("rev-parse", f"{SOURCE_BRANCH}^{{tree}}").stdout.strip()
    if not EXCLUDE_PREFIXES:
        return source_tree, []

    import os
    import tempfile

    with tempfile.TemporaryDirectory(prefix="wimi_publish_") as tmp:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(Path(tmp) / "index")
        git("read-tree", source_tree, env=env)

        listing = git("ls-files", env=env).stdout.splitlines()
        removed = [p for p in listing if p.startswith(EXCLUDE_PREFIXES)]
        if removed:
            # Batched: one rm per prefix, not per path.
            git("rm", "--cached", "-q", "-r", "--", *EXCLUDE_PREFIXES, env=env)
        tree = git("write-tree", env=env).stdout.strip()

    return tree, removed


def scan(patterns, tree):
    """Grep the tree that will be PUBLISHED for denylisted patterns.

    Deliberately the published tree and not ``SOURCE_BRANCH``: scanning
    the source would abort a publish over a match inside an excluded
    directory that no visitor will ever see. An over-strict gate that
    blocks on something harmless is how a denylist ends up being loosened
    to make it pass, which is worse than the false positive.
    """
    result = git(
        "grep", "-i", "-E", "-n",
        *[arg for p in patterns for arg in ("-e", p)],
        tree,
        check=False,
    )
    if result.returncode == 0:
        print("PII scan FAILED -- denylisted patterns found in the tree "
              "that would be published:\n", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        sys.exit("Aborting. Scrub the matches (and commit) before publishing.")
    if result.returncode != 1:
        sys.exit(f"git grep failed unexpectedly:\n{result.stderr.strip()}")
    print(f"PII scan passed ({len(patterns)} patterns, no matches).")


def public_env():
    """Environment overriding author, committer, and tagger identity.

    Everything that reaches GitHub must carry the public identity: commits
    read GIT_AUTHOR_*/GIT_COMMITTER_*, and annotated tags embed the
    GIT_COMMITTER_* values as the tagger. The repo-local git config holds
    the private identity, so never create public commits or tags without
    this override.
    """
    import os
    env = os.environ.copy()
    env.update(
        GIT_AUTHOR_NAME=PUBLIC_NAME,
        GIT_AUTHOR_EMAIL=PUBLIC_EMAIL,
        GIT_COMMITTER_NAME=PUBLIC_NAME,
        GIT_COMMITTER_EMAIL=PUBLIC_EMAIL,
    )
    return env


def _report_tag(tag):
    """What a dry run would tag, since it returns before the tag is created.

    Without this a `--dry-run --tag` rehearsal said nothing about the tag at
    all -- so the one command meant for rehearsing a release was silent about
    the part #425 is concerned with.
    """
    if tag:
        print(f"Would tag the published snapshot as {tag}.")


def publish(source_tree, message, dry_run, tag=None):
    public_head = git("rev-parse", PUBLIC_BRANCH).stdout.strip()
    public_tree = git("rev-parse", f"{PUBLIC_BRANCH}^{{tree}}").stdout.strip()

    if source_tree == public_tree:
        print(f"No content changes: {PUBLIC_BRANCH} already matches "
              f"{SOURCE_BRANCH}. Pushing in case the remote is behind.")
        new_head = public_head
    else:
        if dry_run:
            diff = git("diff", "--stat", public_tree, source_tree)
            print(f"Would publish these changes:\n{diff.stdout}")
            _report_tag(tag)
            print("Dry run -- no commit created, nothing pushed.")
            return
        new_head = git(
            "commit-tree", source_tree, "-p", public_head, "-m", message,
            env=public_env(),
        ).stdout.strip()
        git("update-ref", f"refs/heads/{PUBLIC_BRANCH}", new_head, public_head)
        print(f"Created {PUBLIC_BRANCH} commit {new_head[:9]}: {message}")

    if dry_run:
        _report_tag(tag)
        print("Dry run -- nothing pushed.")
        return
    git("push", REMOTE, f"{PUBLIC_BRANCH}:{REMOTE_BRANCH}")
    print(f"Pushed {new_head[:9]} to {REMOTE}/{REMOTE_BRANCH}.")

    if tag:
        git("tag", "-a", tag, new_head, "-m", message, env=public_env())
        git("push", REMOTE, tag)
        print(f"Tagged {new_head[:9]} as {tag} (public identity) and pushed.")


def main():
    parser = argparse.ArgumentParser(
        description="Publish a scrubbed snapshot of master to GitHub."
    )
    parser.add_argument(
        "-m", "--message",
        default=f"Release snapshot {datetime.date.today():%Y-%m-%d}",
        help="commit message for the public snapshot",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="scan and report only; do not commit or push",
    )
    parser.add_argument(
        "--tag", metavar="NAME", nargs="?", const=DERIVE_TAG, default=None,
        help="also create an annotated tag on the published snapshot "
             "(under the public identity) and push it. With no value the tag "
             "is derived from APP_VERSION; an explicit value must agree with "
             "it (#425)",
    )
    args = parser.parse_args()

    # Resolved FIRST, before the tree is built or anything is pushed. The tag
    # is created after the push, so a mismatch found there would leave the
    # snapshot already public with no tag -- a half-done release is worse than
    # a refused one.
    tag = resolve_tag(args.tag)

    preflight()
    patterns = load_denylist()
    source_tree, removed = build_public_tree()
    if removed:
        prefixes = ", ".join(EXCLUDE_PREFIXES)
        print(f"Excluded {len(removed)} path(s) under: {prefixes}")
    scan(patterns, source_tree)
    publish(source_tree, args.message, args.dry_run, tag)


if __name__ == "__main__":
    main()
