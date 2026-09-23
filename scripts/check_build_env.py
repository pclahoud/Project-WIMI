#!/usr/bin/env python3
"""Refuse to build unless the environment matches ``requirements-prod.txt``.

Why this exists (#135)
----------------------
The Windows build machine drifted to ``PyQt6 6.10.1`` while
``requirements-prod.txt`` pinned ``6.9.1``, and the drift reached
``dist/WIMI/_internal/PyQt6/Qt6/bin/Qt6WebEngineCore.dll``. So the **shipped
binary ran Chromium 134 while every test on every other machine ran Chromium
130**, and nothing anywhere said so.

That is not a hypothetical cost. QtWebEngine 6.10 stopped re-invalidating
``:empty``, which silently broke five CSS rules — the entry form's subject and
error-type chips rendered at zero pixels (#136), and the notes container did
too (#134). Neither was reachable by any test, because on the pinned stack the
behaviour is correct. A green suite said nothing about the artifact.

A pin nobody checks is a comment. This script is the check.

What it verifies
----------------
1. **Every ``==`` pin in requirements-prod.txt** matches what is installed.
2. **The Qt binary wheels specifically.** ``PyQt6`` and ``PyQt6-WebEngine`` are
   thin bindings; the actual Qt and Chromium binaries live in ``PyQt6-Qt6`` and
   ``PyQt6-WebEngine-Qt6``, which are *transitive* dependencies. Pinning only
   the bindings leaves the shipped Chromium free to float inside the binding's
   version range, which is the precise hole this drift went through. Both are
   now pinned, and both are checked.
3. **The runtime Qt / WebEngine / Chromium versions**, read from the loaded
   libraries rather than from package metadata. This is the only check that
   sees what will actually be bundled; a wheel version is a claim, the loaded
   library is the fact.
4. **The Python version**, against a declared range. CI, Linux dev and the
   Windows build machine were found running 3.11, 3.12 and 3.13 respectively.

Usage
-----
Run from the project root. The build scripts call it before PyInstaller::

    python scripts/check_build_env.py

Exit codes:

* ``0`` — the environment matches; it is safe to build.
* ``1`` — a mismatch. **Do not ship the result of a build made anyway.**

``--warn-only`` downgrades failures to warnings and always exits 0. It exists
for inspecting a machine you are not about to build on. Never wire it into a
build script — a guard that cannot stop the build is the comment it replaced.
"""
from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = PROJECT_ROOT / "requirements-prod.txt"

# Minimum supported Python, from docs/BUILD_WINDOWS.md ("Python 3.11+"), and
# the highest version actually exercised. Above the tested ceiling is a warning
# rather than an error: a newer interpreter is untested, not known-broken.
MIN_PYTHON = (3, 11)
MAX_TESTED_PYTHON = (3, 13)

# The Chromium major that the pinned QtWebEngine provides. Checked because it
# is the number that decides rendering behaviour, and because it is the one
# thing no package pin states directly -- the #135 drift was invisible in
# `pip list` terms until someone asked the running engine.
#
# Update this ONLY alongside a deliberate PyQt6-WebEngine-Qt6 bump, and re-read
# #134/#136 first: moving off 130 means `:empty` no longer controls `display`
# correctly, and that must be fixed before the bump, not after.
EXPECTED_CHROMIUM_MAJOR = 130

# A `name==version` line, ignoring comments, extras and environment markers.
PIN_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._+!-]+)\s*$")


def _normalise(name: str) -> str:
    """PEP 503 normalisation, so PyQt6_sip and pyqt6-sip compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(path: Path) -> dict[str, str]:
    """Return ``{normalised_name: version}`` for every ``==`` pin in *path*.

    Lines using ``>=`` or any other operator are deliberately skipped: they are
    not claims about an exact version, so there is nothing to verify.
    """
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN_RE.match(line)
        if match:
            pins[_normalise(match.group(1))] = match.group(2)
    return pins


def installed_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def check_provenance(notes: list[str]) -> None:
    """Record which commit this artifact is being built from.

    Requested by the macOS session while planning cross-machine sync, and it
    is the right instinct: #135 was a build whose provenance nobody could
    state afterwards. A version table says what the environment was; this says
    what the *source* was, and an artifact needs both to be traceable.

    A dirty tree is a NOTE rather than an error — building from a
    work-in-progress tree is legitimate during development. It is only a
    problem for something you intend to ship, and the note says so.
    """
    import subprocess

    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=PROJECT_ROOT, capture_output=True,
                text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    sha = _git("rev-parse", "HEAD")
    if sha is None:
        print("  commit  (not a git checkout \u2014 provenance unavailable)")
        notes.append(
            "Source is not a git checkout, so the build cannot be traced to a "
            "commit. Fine for a scratch build; not fine for anything shipped."
        )
        return

    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"

    # Tracked modifications break provenance: the artifact corresponds to no
    # commit. Untracked files usually do not -- artifacts/, scratch dirs and
    # the like are normal here -- so they are counted separately rather than
    # reported as dirt. A gate that cries wolf on every build gets ignored.
    tracked = _git("status", "--porcelain", "--untracked-files=no") or ""
    untracked = _git("ls-files", "--others", "--exclude-standard") or ""
    n_tracked = len([l for l in tracked.splitlines() if l.strip()])
    n_untracked = len([l for l in untracked.splitlines() if l.strip()])
    extra = f", {n_untracked} untracked" if n_untracked else ""

    if n_tracked:
        print(f"  commit  {sha[:10]} on {branch}  "
              f"(DIRTY: {n_tracked} uncommitted change(s){extra})")
        notes.append(
            f"Working tree has {n_tracked} uncommitted tracked change(s), so "
            f"this artifact corresponds to no commit. Do not ship it without "
            f"committing first."
        )
    else:
        print(f"  commit  {sha[:10]} on {branch}  (clean{extra})")


def check_python(problems: list[str], notes: list[str]) -> None:
    current = sys.version_info[:2]
    pretty = f"{current[0]}.{current[1]}"
    if current < MIN_PYTHON:
        problems.append(
            f"Python {pretty} is below the supported minimum "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} (docs/BUILD_WINDOWS.md)."
        )
    elif current > MAX_TESTED_PYTHON:
        notes.append(
            f"Python {pretty} is newer than the highest tested version "
            f"{MAX_TESTED_PYTHON[0]}.{MAX_TESTED_PYTHON[1]}. Not known-broken, "
            f"but nothing has been run against it."
        )
    print(f"  python  {pretty:<12} (supported {MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
          f"-{MAX_TESTED_PYTHON[0]}.{MAX_TESTED_PYTHON[1]})")


def check_pins(problems: list[str]) -> None:
    if not REQUIREMENTS.exists():
        problems.append(f"{REQUIREMENTS} is missing; nothing to check against.")
        return

    pins = parse_pins(REQUIREMENTS)
    if not pins:
        problems.append(
            f"{REQUIREMENTS.name} declares no `==` pins. Either the file is "
            f"wrong or this check is reading the wrong file; both are bugs."
        )
        return

    for name in sorted(pins):
        expected = pins[name]
        actual = installed_version(name)
        if actual is None:
            print(f"  {name:<24} MISSING      (pinned {expected})")
            problems.append(f"{name} is pinned at {expected} but is not installed.")
        elif actual != expected:
            print(f"  {name:<24} {actual:<12} != pinned {expected}")
            problems.append(
                f"{name} is {actual}, pinned at {expected}."
            )
        else:
            print(f"  {name:<24} {actual}")


def check_runtime_qt(problems: list[str]) -> None:
    """Ask the loaded libraries, not the package metadata.

    A wheel version is a claim about what was installed. These are the versions
    that will be copied into the frozen bundle.
    """
    try:
        from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        from PyQt6.QtWebEngineCore import (
            qWebEngineVersion,
            qWebEngineChromiumVersion,
        )
    except Exception as exc:  # ImportError, or a Qt plugin failure
        problems.append(
            f"Could not load PyQt6/QtWebEngineCore to read runtime versions: "
            f"{exc}. A build cannot be trusted from an environment where the "
            f"engine will not import."
        )
        return

    chromium = qWebEngineChromiumVersion()
    print(f"  Qt runtime               {QT_VERSION_STR}")
    print(f"  PyQt6 runtime            {PYQT_VERSION_STR}")
    print(f"  QtWebEngine runtime      {qWebEngineVersion()}")
    print(f"  Chromium                 {chromium}")

    try:
        major = int(str(chromium).split(".", 1)[0])
    except (ValueError, IndexError):
        problems.append(f"Could not parse a major version from Chromium {chromium!r}.")
        return

    if major != EXPECTED_CHROMIUM_MAJOR:
        problems.append(
            f"Chromium is {chromium} (major {major}); this project expects major "
            f"{EXPECTED_CHROMIUM_MAJOR}. This is the #135 failure exactly: the "
            f"engine that ships is not the engine that was tested. See #134 and "
            f"#136 for what Chromium 134 changes."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the build environment matches requirements-prod.txt.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Report mismatches but always exit 0. For inspection only; never "
             "wire this into a build script.",
    )
    args = parser.parse_args()

    problems: list[str] = []
    notes: list[str] = []

    print("Build environment check (#135)\n")
    check_provenance(notes)
    check_python(problems, notes)
    print()
    check_pins(problems)
    print()
    check_runtime_qt(problems)
    print()

    for note in notes:
        print(f"NOTE: {note}")
    if notes:
        print()

    if not problems:
        print("OK: environment matches requirements-prod.txt. Safe to build.")
        return 0

    print(f"MISMATCH: {len(problems)} problem(s) found.\n")
    for problem in problems:
        print(f"  - {problem}")
    print(
        "\nFix the environment before building:\n"
        "    pip install -r requirements-prod.txt\n"
        "\nIf a version should change, change it in requirements-prod.txt "
        "deliberately\nand say why in the commit -- do not adjust this script "
        "to match a drifted\nmachine. That inverts the check."
    )

    if args.warn_only:
        print("\n(--warn-only: exiting 0 anyway. Do not ship a build made now.)")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
