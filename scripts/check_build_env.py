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

The relations variant (#60)
---------------------------
WIMI ships two artifacts per platform (owner's decision, 2026-10-04): the
default one, and a larger one carrying the relation-extraction runtime. The
flag is ``WIMI_BUILD_RELATIONS=1`` (``--relations`` here), orthogonal to
``WIMI_BUILD_VARIANT``.

**The default mode is unchanged and must stay green on a machine with no
torch.** That is not a nicety — it is the whole reason the runtime went into
its own requirements file instead of ``requirements-prod.txt``. Adding it there
would have made this gate demand torch for everybody's build, and both build
scripts refuse to build on a mismatch.

When the flag IS set, two further things are checked:

5. **``requirements-relations.txt`` is satisfied**, the same way the prod pins
   are.
6. **torch is the CPU build.** Not "torch imports" — the CPU build
   specifically. The #60 spike measured ``gliner2[local]`` resolving from PyPI
   and pulling 5.6 GB, 3.2 GB of it NVIDIA CUDA libraries, on a machine with
   no NVIDIA GPU, against 863 MB from ``--index-url
   https://download.pytorch.org/whl/cpu``. A maintainer who installed the
   default wheel would ship several gigabytes of GPU libraries that can never
   execute, and nothing would notice. #135's shape exactly, which is why it is
   a gate and not a note.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from importlib import metadata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = PROJECT_ROOT / "requirements-prod.txt"

# The relation-extraction runtime, checked only when the relations flag is set
# (#60). Deliberately a separate file: see the module docstring.
RELATIONS_REQUIREMENTS = PROJECT_ROOT / "requirements-relations.txt"

# Distributions that exist only to serve a GPU. Their presence means the
# installed torch came from the default PyPI index rather than the CPU one, and
# they are where the 3.2 GB in the #60 spike went.
GPU_DIST_PREFIXES = ("nvidia", "triton", "pytorch-triton")

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


def _satisfies(actual: str, expected: str) -> bool:
    """Does *actual* satisfy the ``==expected`` pin?

    Normally this is string equality, and for every pin in
    ``requirements-prod.txt`` it still is -- none of them carries a local
    version label, so nothing about the prod check is loosened here.

    The one case that needs more is PEP 440's rule for local version labels:
    *if the specifier has no local label, the candidate's local label is
    ignored*. It matters for exactly one pin and it is not cosmetic. The torch
    wheel from the CPU index reports ``2.14.1+cpu`` on Linux and Windows, while
    macOS has only one torch build and reports a bare ``2.14.1``. A pin written
    ``==2.14.1+cpu`` is therefore unsatisfiable on macOS, and a plain string
    comparison against ``==2.14.1`` would reject the Linux wheel. Implementing
    the spec's rule makes one portable pin work on all three.

    This is a correctness fix rather than a relaxation: a pin that DOES name a
    local label is still compared in full, so ``==2.14.1+cpu`` would reject
    ``2.14.1+cu124``. And it buys nothing for CPU-ness -- that claim is
    ``check_relations_runtime``'s job, because a version string is not a build.
    """
    if actual == expected:
        return True
    if "+" in expected:
        return False
    return actual.split("+", 1)[0] == expected


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


def check_interpreter(problems: list[str], notes: list[str]) -> None:
    """Is this the project's venv, or just *a* Python? (#183)

    Both build scripts check that `.venv/Scripts/activate.bat` (or
    `bin/activate`) **exists**, then call it, then run `python`. That guard is
    the wrong one: the failure mode is an activate script that is present and
    broken.

    A venv hardcodes absolute paths. Rename or move the directory and
    `activate` exports a `VIRTUAL_ENV` that no longer exists, prepends a
    `Scripts`/`bin` that is not there, and the `python` on the next line is
    whatever the system has. On a Windows machine here a `.venv` created as
    `venv` did exactly that, and the build ran on the system interpreter with
    no warning at all.

    It surfaced only by luck: the system Python happened to differ from the
    venv in one pinned package, so `check_pins` caught it. **Had the two
    agreed on every pin, the build would have completed from an environment
    nobody selected and reported nothing unusual** -- #135 through a different
    door, where the gate verifies *an* environment and nothing verifies it is
    the *right* one.

    `sys.prefix` is the honest answer, because the interpreter sets it. A
    stale `VIRTUAL_ENV` cannot forge it.
    """
    venv = PROJECT_ROOT / ".venv"
    actual = Path(sys.prefix).resolve()

    if not venv.exists():
        # Not a failure. The gate is runnable outside a checkout that has one
        # -- a git worktree, or a machine using a different environment
        # manager -- and refusing there would only teach people to skip it.
        notes.append(
            f"No .venv at {venv}, so the interpreter could not be checked "
            f"against it. Running from {actual}."
        )
        print(f"  venv    (none at {venv.name}/)  running {actual}")
        return

    if actual != venv.resolve():
        problems.append(
            f"This is not the project's venv. sys.prefix is {actual}, but the "
            f"checkout's venv is {venv.resolve()}. Activation did not take -- a "
            f"venv that has been renamed or moved leaves an activate script "
            f"that exists, runs, and silently leaves the system Python on PATH "
            f"(#183). Recreate it with `python -m venv .venv`, or activate the "
            f"right one. Do not build from here: nothing downstream can tell "
            f"you which interpreter produced the artifact."
        )
        print(f"  venv    MISMATCH     {actual}")
        return

    print(f"  venv    {venv.name:<12} (sys.prefix matches)")


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


def check_pins(problems: list[str], requirements: Path = REQUIREMENTS,
               install_hint: str | None = None) -> None:
    """Verify every ``==`` pin in *requirements* against what is installed.

    Parameterised by file so the relations requirements go through the same
    check as the prod ones rather than a second implementation (#60). The
    default argument keeps every existing caller and the default build path
    byte-identical in behaviour.
    """
    if not requirements.exists():
        problems.append(f"{requirements} is missing; nothing to check against.")
        return

    pins = parse_pins(requirements)
    if not pins:
        problems.append(
            f"{requirements.name} declares no `==` pins. Either the file is "
            f"wrong or this check is reading the wrong file; both are bugs."
        )
        return

    hint = f" Install with: {install_hint}" if install_hint else ""
    for name in sorted(pins):
        expected = pins[name]
        actual = installed_version(name)
        if actual is None:
            print(f"  {name:<24} MISSING      (pinned {expected})")
            problems.append(
                f"{name} is pinned at {expected} but is not installed.{hint}"
            )
        elif not _satisfies(actual, expected):
            print(f"  {name:<24} {actual:<12} != pinned {expected}")
            problems.append(
                f"{name} is {actual}, pinned at {expected}.{hint}"
            )
        else:
            print(f"  {name:<24} {actual}")


def check_runtime_qt(problems: list[str]) -> None:
    """Ask the loaded libraries, not the package metadata.

    A wheel version is a claim about what was installed. These are the versions
    that will be copied into the frozen bundle.
    """
    try:
        from PyQt6.QtCore import qVersion, QT_VERSION_STR, PYQT_VERSION_STR
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

    # `qVersion()` asks the loaded libQt6Core. `QT_VERSION_STR` is a constant
    # baked into the PyQt6 bindings at *their* build time, and the two differ
    # on a correctly-pinned machine -- measured 6.9.2 against 6.9.0 here, two
    # patch versions apart (#188). Printing the constant under the label
    # "Qt runtime" is the thing this function's own docstring warns against,
    # and it is the line most likely to miss the next #135 in the Qt layer.
    #
    # The bindings constant is still worth showing: a large gap between what
    # PyQt6 was built against and what it loaded is its own smell. It just
    # must not be the line called "runtime".
    qt_runtime = qVersion()
    webengine = qWebEngineVersion()
    chromium = qWebEngineChromiumVersion()
    print(f"  Qt runtime               {qt_runtime}")
    print(f"  Qt bindings built for    {QT_VERSION_STR}")
    print(f"  PyQt6 runtime            {PYQT_VERSION_STR}")
    print(f"  QtWebEngine runtime      {webengine}")
    print(f"  Chromium                 {chromium}")

    # Reading the right value is only half the job: before #188 these were
    # printed and never compared, so core Qt was checked by nobody. The wheels
    # named here are the ones carrying the binaries that get bundled, which is
    # why CLAUDE.md singles them out.
    pins = parse_pins(REQUIREMENTS) if REQUIREMENTS.exists() else {}
    for label, actual, pin_name in (
        ("Qt", qt_runtime, "pyqt6-qt6"),
        ("QtWebEngine", webengine, "pyqt6-webengine-qt6"),
    ):
        expected = pins.get(pin_name)
        if expected is None:
            continue
        if str(actual) != expected:
            problems.append(
                f"{label} runtime is {actual}, but {pin_name} is pinned at "
                f"{expected}. The loaded library is what gets copied into the "
                f"bundle, so this is the #135 shape: the thing that ships is "
                f"not the thing that was tested. If the two legitimately differ "
                f"in format rather than in substance, loosen this comparison "
                f"deliberately -- do not delete it."
            )

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


CPU_INDEX_HINT = (
    "pip install -r requirements-relations.txt "
    "--index-url https://download.pytorch.org/whl/cpu "
    "--extra-index-url https://pypi.org/simple"
)


def check_relations_runtime(problems: list[str], notes: list[str]) -> None:
    """Is the relation-extraction runtime present, and is torch the CPU build?

    Only called when the relations flag is set. Two separate claims, and the
    second is the one with teeth:

    * ``torch.version.cuda`` is the authoritative in-process signal and is
      ``None`` on a CPU build on every platform. It is preferred over the
      version string because macOS CPU wheels carry no ``+cpu`` label, so the
      label is not a portable test (see ``_satisfies``).
    * **No ``nvidia-*`` or ``triton`` distribution may be installed.** This is
      not redundant with the first check -- it is the one that measures the
      cost. It is where the #60 spike's 3.2 GB went, those wheels are what
      PyInstaller would collect into the artifact, and they can be sitting in
      the environment from an earlier default-index install even when the
      currently-imported torch reports no CUDA.

    Importing torch costs about 1.5 s (measured) and happens only on the
    relations path, so the default build pays nothing for this function
    existing.
    """
    print("Relations runtime (#60)\n")
    check_pins(problems, RELATIONS_REQUIREMENTS, install_hint=CPU_INDEX_HINT)
    print()

    # The GPU-wheel scan first: it needs no import, and if torch itself will
    # not load the scan is still the more actionable of the two findings.
    gpu_dists: list[tuple[str, str]] = []
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue
        if _normalise(name).startswith(GPU_DIST_PREFIXES):
            gpu_dists.append((name, dist.version))

    if gpu_dists:
        listed = ", ".join(f"{n}=={v}" for n, v in sorted(gpu_dists))
        print(f"  GPU wheels               {len(gpu_dists)} FOUND")
        problems.append(
            f"{len(gpu_dists)} GPU-only distribution(s) are installed: {listed}. "
            f"That means torch came from the default PyPI index, not the CPU "
            f"one. The #60 spike measured this as 5.6 GB with 3.2 GB of CUDA "
            f"libraries on a machine with no NVIDIA GPU, against 863 MB from "
            f"the CPU index -- and PyInstaller would collect them into the "
            f"artifact, where they can never execute. Reinstall with:\n"
            f"      {CPU_INDEX_HINT}"
        )
    else:
        print("  GPU wheels               none installed")

    try:
        import torch  # noqa: PLC0415 -- deliberately not at module scope
    except Exception as exc:
        problems.append(
            f"The relations flag is set but torch will not import: {exc}. "
            f"The relations artifact cannot be built from this environment.\n"
            f"      {CPU_INDEX_HINT}"
        )
        return

    cuda = torch.version.cuda
    hip = getattr(torch.version, "hip", None)
    print(f"  torch                    {torch.__version__}")
    print(f"  torch.version.cuda       {cuda}")
    print(f"  torch.version.hip        {hip}")

    if cuda is not None or hip is not None:
        problems.append(
            f"torch reports an accelerator build (cuda={cuda!r}, hip={hip!r}); "
            f"the relations artifact must bundle the CPU build. Several "
            f"gigabytes of GPU libraries that can never execute would ship, "
            f"and nothing downstream would report it -- #135's shape. "
            f"Reinstall with:\n      {CPU_INDEX_HINT}"
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
    parser.add_argument(
        "--relations",
        action="store_true",
        default=os.environ.get("WIMI_BUILD_RELATIONS") == "1",
        help="also verify requirements-relations.txt and that torch is the CPU "
             "build (#60). Defaults to on when WIMI_BUILD_RELATIONS=1, which "
             "is what the build scripts export, so neither script needs to "
             "pass it.",
    )
    args = parser.parse_args()

    problems: list[str] = []
    notes: list[str] = []

    print("Build environment check (#135)\n")
    # Say which artifact is being checked. Without this line a reader cannot
    # tell a green default run from a green relations run, and they are
    # different claims about different artifacts (#60).
    print(f"  artifact{'':<8} "
          f"{'relations (torch bundled)' if args.relations else 'default (no torch)'}")
    check_provenance(notes)
    check_interpreter(problems, notes)
    check_python(problems, notes)
    print()
    check_pins(problems)
    print()
    check_runtime_qt(problems)
    print()

    if args.relations:
        check_relations_runtime(problems, notes)
        print()
    else:
        # Stated rather than silent: the default artifact deliberately does not
        # have the relation-extraction runtime, so its absence is not a finding
        # and must not read as one.
        print("Relations runtime (#60)\n")
        print("  not checked -- this is the default artifact, which ships "
              "without it by design.")
        print("  Pass --relations (or WIMI_BUILD_RELATIONS=1) to build the "
              "other one.")
        print()

    for note in notes:
        print(f"NOTE: {note}")
    if notes:
        print()

    if not problems:
        if args.relations:
            print("OK: environment matches requirements-prod.txt and "
                  "requirements-relations.txt,")
            print("    and torch is the CPU build. Safe to build the relations "
                  "artifact.")
        else:
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
