"""Publish a snapshot of master to the public GitHub mirror.

Takes the committed tree of ``master`` (never the working directory), scans it
against a local denylist of sensitive patterns, commits it onto the ``public``
branch under the public author identity, and pushes to the ``github`` remote.
The private commit history on ``master`` is never pushed.

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


def scan(patterns):
    """Grep the committed tree of SOURCE_BRANCH for denylisted patterns."""
    result = git(
        "grep", "-i", "-E", "-n",
        *[arg for p in patterns for arg in ("-e", p)],
        SOURCE_BRANCH,
        check=False,
    )
    if result.returncode == 0:
        print("PII scan FAILED — denylisted patterns found in the "
              f"committed tree of {SOURCE_BRANCH}:\n", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        sys.exit("Aborting. Scrub the matches (and commit) before publishing.")
    if result.returncode != 1:
        sys.exit(f"git grep failed unexpectedly:\n{result.stderr.strip()}")
    print(f"PII scan passed ({len(patterns)} patterns, no matches).")


def publish(message, dry_run):
    source_tree = git("rev-parse", f"{SOURCE_BRANCH}^{{tree}}").stdout.strip()
    public_head = git("rev-parse", PUBLIC_BRANCH).stdout.strip()
    public_tree = git("rev-parse", f"{PUBLIC_BRANCH}^{{tree}}").stdout.strip()

    if source_tree == public_tree:
        print(f"No content changes: {PUBLIC_BRANCH} already matches "
              f"{SOURCE_BRANCH}. Pushing in case the remote is behind.")
        new_head = public_head
    else:
        if dry_run:
            diff = git("diff", "--stat", PUBLIC_BRANCH, SOURCE_BRANCH)
            print(f"Would publish these changes:\n{diff.stdout}")
            print("Dry run — no commit created, nothing pushed.")
            return
        import os
        env = os.environ.copy()
        env.update(
            GIT_AUTHOR_NAME=PUBLIC_NAME,
            GIT_AUTHOR_EMAIL=PUBLIC_EMAIL,
            GIT_COMMITTER_NAME=PUBLIC_NAME,
            GIT_COMMITTER_EMAIL=PUBLIC_EMAIL,
        )
        new_head = git(
            "commit-tree", source_tree, "-p", public_head, "-m", message,
            env=env,
        ).stdout.strip()
        git("update-ref", f"refs/heads/{PUBLIC_BRANCH}", new_head, public_head)
        print(f"Created {PUBLIC_BRANCH} commit {new_head[:9]}: {message}")

    if dry_run:
        print("Dry run — nothing pushed.")
        return
    git("push", REMOTE, f"{PUBLIC_BRANCH}:{REMOTE_BRANCH}")
    print(f"Pushed {new_head[:9]} to {REMOTE}/{REMOTE_BRANCH}.")


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
    args = parser.parse_args()

    preflight()
    scan(load_denylist())
    publish(args.message, args.dry_run)


if __name__ == "__main__":
    main()
