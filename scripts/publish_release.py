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

--dry-run performs the PII scan and reports what would be published without
committing or pushing anything.
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

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
EXCLUDE_PREFIXES = ("docs/",)

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
            print("Dry run -- no commit created, nothing pushed.")
            return
        new_head = git(
            "commit-tree", source_tree, "-p", public_head, "-m", message,
            env=public_env(),
        ).stdout.strip()
        git("update-ref", f"refs/heads/{PUBLIC_BRANCH}", new_head, public_head)
        print(f"Created {PUBLIC_BRANCH} commit {new_head[:9]}: {message}")

    if dry_run:
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
        "--tag", metavar="NAME",
        help="also create an annotated tag on the published snapshot "
             "(under the public identity) and push it",
    )
    args = parser.parse_args()

    preflight()
    patterns = load_denylist()
    source_tree, removed = build_public_tree()
    if removed:
        prefixes = ", ".join(EXCLUDE_PREFIXES)
        print(f"Excluded {len(removed)} path(s) under: {prefixes}")
    scan(patterns, source_tree)
    publish(source_tree, args.message, args.dry_run, args.tag)


if __name__ == "__main__":
    main()
